"""Odell probe: cover-only enrolled names with margin, on cooldown_8s.

Baseline: research cooldown only (with_voice=False).
Compare Whitworth (KEEP m0.10), Clarissa, and Whitworth∪Clarissa.

Live untouched. Product scorecard cells only.
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

OUT = DATA / "odell_cover_cast"
MARGIN = 0.10
PANELS = {
    "whitworth": ["Andrew Whitworth"],
    "clarissa": ["Clarissa Thompson"],
    "whit_or_clarissa": ["Andrew Whitworth", "Clarissa Thompson"],
}


def _hot_ends(session: str, allow: list[str], margin: float) -> np.ndarray:
    data = np.load(ECAPA / f"{session}.npz")
    ends = data["end"]
    people = data["people"]
    order = np.argsort(ends)
    ends = ends[order]
    people = people[order]
    idx = [NAMES.index(n) for n in allow]
    with np.errstate(invalid="ignore"):
        best = np.nanmax(people[:, idx], axis=1)
        # runner-up: max among names NOT in allow (booth others) and second in allow if multiple
        other_idx = [i for i, n in enumerate(NAMES) if n not in allow]
        if other_idx:
            rival = np.nanmax(people[:, other_idx], axis=1)
        else:
            rival = np.full(len(ends), -1.0)
        # if panel has 2+, also compare against the other panel member
        if len(idx) > 1:
            # second best within panel
            panel = people[:, idx]
            # sort descending along names
            part = np.partition(np.nan_to_num(panel, nan=-1.0), -2, axis=1)
            second = part[:, -2]
            rival = np.maximum(np.nan_to_num(rival, nan=-1.0), second)
    hot = np.isfinite(best) & (best >= LINE) & ((best - np.nan_to_num(rival, nan=-1.0)) >= margin)
    return ends[hot]


def _apply_cover_voice(times: np.ndarray, probs: np.ndarray, hot_ends: np.ndarray) -> np.ndarray:
    rows = decisions(times.tolist(), probs.tolist(), **CONTROLLER)
    covering = np.array([r["action"] == "cover" for r in rows], dtype=bool)
    right = np.searchsorted(hot_ends, times, side="right")
    left = np.searchsorted(hot_ends, times - HOLD_S, side="left")
    out = np.array(probs, dtype=np.float64, copy=True)
    out[covering & (right > left)] = 0.0
    return out


def _delta(base: dict, other: dict) -> dict:
    return {
        "cov_delta": round((other["non_broadcast_coverage"] or 0) - (base["non_broadcast_coverage"] or 0), 4),
        "desk_delta": round(other["cells"]["desk_s"] - base["cells"]["desk_s"], 1),
        "odell_delta": round(
            other["focus"]["hush_20260924_220624"]["odell"] - base["focus"]["hush_20260924_220624"]["odell"],
            2,
        ),
        "whitworth_delta": round(
            other["focus"]["hush_20260924_220624"]["whitworth"] - base["focus"]["hush_20260924_220624"]["whitworth"],
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
        reasons.append(f"spot leak amex={d['amex_delta']} chilis={d['chilis_delta']}")
    if d["desk_delta"] > 1:
        decision = "REJECT"
        reasons.append(f"desk muted rose {d['desk_delta']}")
    if d["odell_delta"] > -5 and d["desk_delta"] > -10:
        if decision == "KEEP":
            decision = "REJECT"
        reasons.append(f"Odell/desk not materially freed odell={d['odell_delta']} desk={d['desk_delta']}")
    if not reasons:
        reasons.append("coverage held; spots held; desk/Odell freed")
    return {"run": name, "decision": decision, "reasons": reasons, "delta": d}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    frozen = load_frozen_probs(EVAL)
    cool = {s: (t, apply_research_latch(s, t, p, with_voice=False)) for s, (t, p) in frozen.items()}
    reports = {"cooldown_8s": score_run("cooldown_8s", cool, OUT)}

    for panel_name, allow in PANELS.items():
        keyed = {}
        hops = {}
        for session, (times, probs) in cool.items():
            hot = _hot_ends(session, allow, MARGIN)
            keyed[session] = (times, _apply_cover_voice(times, probs, hot))
            rows = decisions(times.tolist(), probs.tolist(), **CONTROLLER)
            covering = np.array([r["action"] == "cover" for r in rows], dtype=bool)
            voice = np.searchsorted(hot, times, side="right") > np.searchsorted(hot, times - HOLD_S, side="left")
            hops[session] = {
                "cover_hops": int(covering.sum()),
                "cleared": int((covering & voice).sum()),
                "hot_ends": int(hot.size),
                "allow": allow,
            }
        name = f"cool_cover_{panel_name}_m{MARGIN:.2f}"
        reports[name] = score_run(name, keyed, OUT)
        (OUT / name / "veto_hops.json").write_text(json.dumps(hops, indent=2), encoding="utf-8")
        print("veto_hops", name, hops, flush=True)

    # also score current research stack for reference
    stack = {s: (t, apply_research_latch(s, t, p, with_voice=True)) for s, (t, p) in frozen.items()}
    reports["research_stack_whit_m0.10"] = score_run("research_stack_whit_m0.10", stack, OUT)

    base = reports["cooldown_8s"]["aggregate"]
    verdicts = {}
    print("\n=== KEEP/REJECT vs cooldown_8s ===", flush=True)
    for name, rep in reports.items():
        if name == "cooldown_8s":
            continue
        verdicts[name] = _decide(name, base, rep["aggregate"])
        print(name, verdicts[name]["decision"], verdicts[name]["reasons"], verdicts[name]["delta"], flush=True)

    print("\n=== RAW CELL TABLE ===", flush=True)
    print(f"{'run':36} {'cov':7} {'desk':7} {'odell':7} {'whit':7} {'amex':7} {'chilis':7}", flush=True)
    for name, rep in reports.items():
        a = rep["aggregate"]
        f24 = a["focus"]["hush_20260924_220624"]
        f08 = a["focus"]["hush_20261008_205100"]
        print(
            f"{name:36} {a['non_broadcast_coverage']:.4f} {a['cells']['desk_s']:7.1f} "
            f"{f24['odell']:7.1f} {f24['whitworth']:7.1f} {f08['amex']:7.1f} {f24['chilis']:7.1f}",
            flush=True,
        )

    summary = {"margin": MARGIN, "decisions": verdicts, "aggregates": {k: v["aggregate"] for k, v in reports.items()}}
    (OUT / "SUMMARY.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (OUT / "KEEP_REJECT.md").write_text(
        "\n".join(
            [
                "# Cover-cast panels vs cooldown_8s",
                "",
                *[
                    f"## {n}\n- **{d['decision']}**\n"
                    + "\n".join(f"- {r}" for r in d["reasons"])
                    + f"\n- `{json.dumps(d['delta'])}`\n"
                    for n, d in verdicts.items()
                ],
            ]
        ),
        encoding="utf-8",
    )
    print("wrote", OUT, flush=True)


if __name__ == "__main__":
    main()
