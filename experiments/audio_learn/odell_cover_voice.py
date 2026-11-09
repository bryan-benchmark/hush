"""Odell probe: enrolled-voice veto only while already covering.

Baseline: research_latch (cooldown_8s) — KEEP.
Rejected earlier: whitworth anytime (Amex leak).

This card only clears p when:
  1) research_latch probabilities already put the controller in cover, and
  2) Andrew Whitworth cosine >= 0.25 on a window that has ended.

Optional gap: best - runner_up >= MARGIN.
Product scorecard cells only. Live untouched.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from experiments.audio_learn.controller import decisions
from experiments.audio_learn.desk_voice_hold import ECAPA, HOLD_S, LINE, NAMES
from experiments.audio_learn.product_scorecard import DATA, load_frozen_probs, score_run
from experiments.audio_learn.research_latch import apply_research_latch
from experiments.audio_learn.splits import EVAL
from experiments.audio_learn.studio_fit import CONTROLLER

OUT = DATA / "odell_cover_voice"
MARGINS = (0.0, 0.10, 0.15)


def _whitworth_hot_ends(session: str, margin: float) -> np.ndarray:
    data = np.load(ECAPA / f"{session}.npz")
    ends = data["end"]
    people = data["people"]
    order = np.argsort(ends)
    ends = ends[order]
    people = people[order]
    wi = NAMES.index("Andrew Whitworth")
    w = people[:, wi].astype(np.float64)
    # runner-up among other enrolled names
    mask = np.ones(people.shape[1], dtype=bool)
    mask[wi] = False
    with np.errstate(invalid="ignore"):
        others = np.nanmax(people[:, mask], axis=1)
    hot = np.isfinite(w) & (w >= LINE) & ((w - np.nan_to_num(others, nan=-1.0)) >= margin)
    return ends[hot]


def _cover_mask(times: np.ndarray, probs: np.ndarray) -> np.ndarray:
    rows = decisions(times.tolist(), probs.tolist(), **CONTROLLER)
    return np.array([r["action"] == "cover" for r in rows], dtype=bool)


def _veto_while_covering(
    times: np.ndarray,
    probs: np.ndarray,
    hot_ends: np.ndarray,
    hold_s: float,
    covering: np.ndarray,
) -> np.ndarray:
    right = np.searchsorted(hot_ends, times, side="right")
    left = np.searchsorted(hot_ends, times - hold_s, side="left")
    voice_hot = right > left
    out = np.array(probs, dtype=np.float64, copy=True)
    out[covering & voice_hot] = 0.0
    return out


def _delta(base: dict, other: dict) -> dict:
    return {
        "cov_delta": round((other["non_broadcast_coverage"] or 0) - (base["non_broadcast_coverage"] or 0), 4),
        "broadcast_muted_delta": round(other["broadcast_muted_s"] - base["broadcast_muted_s"], 1),
        "desk_delta": round(other["cells"]["desk_s"] - base["cells"]["desk_s"], 1),
        "return_delta": round(other["cells"]["show_return_s"] - base["cells"]["show_return_s"], 1),
        "odell_delta": round(
            other["focus"]["hush_20260924_220624"]["odell"] - base["focus"]["hush_20260924_220624"]["odell"],
            2,
        ),
        "amex_delta": round(
            other["focus"]["hush_20261008_205100"]["amex"] - base["focus"]["hush_20261008_205100"]["amex"],
            2,
        ),
        "chilis_delta": round(
            other["focus"]["hush_20260924_220624"]["chilis"] - base["focus"]["hush_20260924_220624"]["chilis"],
            2,
        ),
    }


def _decide(name: str, base: dict, other: dict) -> dict:
    d = _delta(base, other)
    reasons = []
    decision = "KEEP"
    if -d["cov_delta"] > 0.02:
        decision = "REJECT"
        reasons.append(f"coverage drop {-d['cov_delta']:.4f} > 0.02")
    if d["amex_delta"] < -2 or d["chilis_delta"] < -2:
        decision = "REJECT"
        reasons.append(f"spot leak amex_delta={d['amex_delta']} chilis_delta={d['chilis_delta']}")
    if d["desk_delta"] > 1:
        decision = "REJECT"
        reasons.append(f"desk muted rose {d['desk_delta']}")
    if d["odell_delta"] > -5 and d["desk_delta"] > -10:
        if decision == "KEEP":
            decision = "REJECT"
        reasons.append(f"Odell/desk not materially freed (odell_delta={d['odell_delta']}, desk_delta={d['desk_delta']})")
    if not reasons:
        reasons.append("coverage held; spots held; desk/Odell freed")
    return {"run": name, "decision": decision, "reasons": reasons, "delta": d}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    frozen = load_frozen_probs(EVAL)
    baseline = {}
    for session, (times, probs) in frozen.items():
        baseline[session] = (times, apply_research_latch(session, times, probs))

    reports = {}
    reports["research_latch"] = score_run("research_latch", baseline, OUT)

    # rejected control: whitworth anytime on research latch
    anytime = {}
    for session, (times, probs) in baseline.items():
        hot = _whitworth_hot_ends(session, 0.0)
        right = np.searchsorted(hot, times, side="right")
        left = np.searchsorted(hot, times - HOLD_S, side="left")
        out = np.array(probs, dtype=np.float64, copy=True)
        out[right > left] = 0.0
        anytime[session] = (times, out)
    reports["latch_whitworth_anytime"] = score_run("latch_whitworth_anytime", anytime, OUT)

    for margin in MARGINS:
        keyed = {}
        veto_hops = {}
        for session, (times, probs) in baseline.items():
            covering = _cover_mask(times, probs)
            hot = _whitworth_hot_ends(session, margin)
            scored = _veto_while_covering(times, probs, hot, HOLD_S, covering)
            keyed[session] = (times, scored)
            # raw hop audit: how many cover hops cleared
            voice_hot = np.searchsorted(hot, times, side="right") > np.searchsorted(hot, times - HOLD_S, side="left")
            cleared = int(np.sum(covering & voice_hot))
            cover_n = int(np.sum(covering))
            veto_hops[session] = {"cover_hops": cover_n, "cleared_by_voice": cleared, "hot_ends": int(hot.size)}
        name = f"latch_cover_whitworth_m{margin:.2f}"
        reports[name] = score_run(name, keyed, OUT)
        (OUT / name / "veto_hops.json").write_text(json.dumps(veto_hops, indent=2), encoding="utf-8")
        print("veto_hops", name, veto_hops, flush=True)

    base_agg = reports["research_latch"]["aggregate"]
    decisions = {}
    print("\n=== KEEP/REJECT vs research_latch ===", flush=True)
    for name, rep in reports.items():
        if name == "research_latch":
            continue
        decisions[name] = _decide(name, base_agg, rep["aggregate"])
        print(name, decisions[name]["decision"], decisions[name]["reasons"], decisions[name]["delta"], flush=True)

    print("\n=== RAW CELL TABLE ===", flush=True)
    print(
        f"{'run':32} {'cov':7} {'desk':7} {'return':7} {'odell':7} {'amex':7} {'chilis':7}",
        flush=True,
    )
    for name, rep in reports.items():
        a = rep["aggregate"]
        print(
            f"{name:32} {a['non_broadcast_coverage']:.4f} {a['cells']['desk_s']:7.1f} "
            f"{a['cells']['show_return_s']:7.1f} {a['focus']['hush_20260924_220624']['odell']:7.1f} "
            f"{a['focus']['hush_20261008_205100']['amex']:7.1f} "
            f"{a['focus']['hush_20260924_220624']['chilis']:7.1f}",
            flush=True,
        )

    summary = {
        "baseline": "research_latch cooldown_8s",
        "line": LINE,
        "hold_s": HOLD_S,
        "margins": MARGINS,
        "decisions": decisions,
        "aggregates": {k: v["aggregate"] for k, v in reports.items()},
    }
    (OUT / "SUMMARY.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (OUT / "KEEP_REJECT.md").write_text(
        "\n".join(
            [
                "# Odell cover-only Whitworth vs research_latch",
                "",
                *[
                    f"## {n}\n- **{d['decision']}**\n"
                    + "\n".join(f"- {r}" for r in d["reasons"])
                    + f"\n- `{json.dumps(d['delta'])}`\n"
                    for n, d in decisions.items()
                ],
            ]
        ),
        encoding="utf-8",
    )
    print("wrote", OUT, flush=True)


if __name__ == "__main__":
    main()
