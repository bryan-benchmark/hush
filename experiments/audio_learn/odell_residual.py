"""Residual Odell under Clarissa research stack + Gonzalez cover probe.

1) Hop audit on Odell span: when cover remains, what does ECAPA say?
2) Product cards: cool + Gonzalez m0.10; cool + Clarissa|Gonzalez m0.10
   vs cooldown_8s / Clarissa KEEP baseline.

Live untouched.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from experiments.audio_learn.controller import decisions
from experiments.audio_learn.desk_voice_hold import ECAPA, HOLD_S, LINE, NAMES
from experiments.audio_learn.odell_cover_cast import MARGIN, _apply_cover_voice, _decide, _hot_ends
from experiments.audio_learn.product_scorecard import DATA, load_frozen_probs, score_run
from experiments.audio_learn.research_latch import apply_research_latch
from experiments.audio_learn.splits import EVAL
from experiments.audio_learn.studio_fit import CONTROLLER

OUT = DATA / "odell_residual"
ODELL = ("hush_20260924_220624", 7035.0, 7095.2)


def _ecapa_at(session: str, t: float) -> dict:
    data = np.load(ECAPA / f"{session}.npz")
    ended = np.flatnonzero(data["end"] <= t + 1e-9)
    if ended.size == 0:
        return {}
    i = int(ended[-1])
    scores = {
        name: round(float(data["people"][i, slot]), 3)
        for slot, name in enumerate(NAMES)
        if np.isfinite(data["people"][i, slot])
    }
    if not scores:
        return {}
    best = max(scores, key=scores.get)
    ordered = sorted(scores.values(), reverse=True)
    gap = round(ordered[0] - ordered[1], 3) if len(ordered) > 1 else None
    return {
        "voice_best": best,
        "voice_cos": scores[best],
        "voice_gap": gap,
        "voice_ge_line": scores[best] >= LINE,
        "scores": scores,
        "window_end": round(float(data["end"][i]), 3),
    }


def audit_odell_residual() -> dict:
    session, t0, t1 = ODELL
    frozen = load_frozen_probs((session,))
    times, raw = frozen[session]
    latch = apply_research_latch(session, times, raw, with_voice=True)
    cool = apply_research_latch(session, times, raw, with_voice=False)
    rows_latch = decisions(times.tolist(), latch.tolist(), **CONTROLLER)
    rows_cool = decisions(times.tolist(), cool.tolist(), **CONTROLLER)
    hops = []
    still_cover = 0
    freed = 0
    for i, t in enumerate(times.tolist()):
        if t < t0 or t > t1:
            continue
        a_l = rows_latch[i]["action"]
        a_c = rows_cool[i]["action"]
        voice = _ecapa_at(session, float(t))
        if a_c == "cover" and a_l == "play":
            freed += 1
        if a_l == "cover":
            still_cover += 1
        if abs(t * 4 - round(t * 4)) > 1e-6:
            # keep all hops in jsonl; print subsample elsewhere
            pass
        hops.append(
            {
                "t": round(float(t), 3),
                "p_cool": round(float(cool[i]), 4),
                "p_latch": round(float(latch[i]), 4),
                "action_cool": a_c,
                "action_latch": a_l,
                **voice,
            }
        )
    # summarize still-cover voice
    cover_hops = [h for h in hops if h["action_latch"] == "cover"]
    best_counts: dict[str, int] = {}
    clarissa_ge = 0
    whit_ge = 0
    gonz_ge = 0
    none_ge = 0
    for h in cover_hops:
        b = h.get("voice_best") or "none"
        best_counts[b] = best_counts.get(b, 0) + 1
        sc = h.get("scores") or {}
        if sc.get("Clarissa Thompson", -1) >= LINE and (h.get("voice_gap") or 0) >= MARGIN and h.get("voice_best") == "Clarissa Thompson":
            clarissa_ge += 1
        elif sc.get("Andrew Whitworth", -1) >= LINE:
            whit_ge += 1
        elif sc.get("Tony Gonzalez", -1) >= LINE:
            gonz_ge += 1
        if not h.get("voice_ge_line"):
            none_ge += 1
    summary = {
        "span": [t0, t1],
        "n_hops": len(hops),
        "still_cover_hops": still_cover,
        "freed_by_clarissa_hops": freed,
        "still_cover_best_counts": best_counts,
        "still_cover_clarissa_would_pass_gate": clarissa_ge,
        "still_cover_whitworth_ge_line": whit_ge,
        "still_cover_gonzalez_ge_line": gonz_ge,
        "still_cover_no_voice_ge_line": none_ge,
    }
    dest = OUT / "odell_hop_audit"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    with (dest / "hops.jsonl").open("w", encoding="utf-8") as fh:
        for h in hops:
            fh.write(json.dumps(h) + "\n")
    print("ODELL RESIDUAL", json.dumps(summary, indent=2), flush=True)
    return summary


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    audit_odell_residual()

    frozen = load_frozen_probs(EVAL)
    cool = {s: (t, apply_research_latch(s, t, p, with_voice=False)) for s, (t, p) in frozen.items()}
    reports = {"cooldown_8s": score_run("cooldown_8s", cool, OUT)}

    panels = {
        "gonzalez": ["Tony Gonzalez"],
        "clarissa": ["Clarissa Thompson"],
        "clarissa_or_gonzalez": ["Clarissa Thompson", "Tony Gonzalez"],
    }
    for panel_name, allow in panels.items():
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
            }
        name = f"cool_cover_{panel_name}_m{MARGIN:.2f}"
        reports[name] = score_run(name, keyed, OUT)
        (OUT / name / "veto_hops.json").write_text(json.dumps(hops, indent=2), encoding="utf-8")
        print("veto_hops", name, hops, flush=True)

    base = reports["cooldown_8s"]["aggregate"]
    verdicts = {}
    print("\n=== KEEP/REJECT vs cooldown_8s ===", flush=True)
    for name, rep in reports.items():
        if name == "cooldown_8s":
            continue
        verdicts[name] = _decide(name, base, rep["aggregate"])
        print(name, verdicts[name]["decision"], verdicts[name]["reasons"], verdicts[name]["delta"], flush=True)

    print("\n=== RAW CELL TABLE ===", flush=True)
    print(f"{'run':40} {'cov':7} {'desk':7} {'odell':7} {'amex':7}", flush=True)
    for name, rep in reports.items():
        a = rep["aggregate"]
        print(
            f"{name:40} {a['non_broadcast_coverage']:.4f} {a['cells']['desk_s']:7.1f} "
            f"{a['focus']['hush_20260924_220624']['odell']:7.1f} "
            f"{a['focus']['hush_20261008_205100']['amex']:7.1f}",
            flush=True,
        )

    summary = {"decisions": verdicts, "aggregates": {k: v["aggregate"] for k, v in reports.items()}}
    (OUT / "SUMMARY.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (OUT / "KEEP_REJECT.md").write_text(
        "\n".join(
            [
                "# Residual Odell / Gonzalez probe",
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
