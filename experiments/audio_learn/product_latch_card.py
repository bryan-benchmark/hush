"""Latch keep/reject on the product scorecard only — raw receipts every run.

Variants:
  frozen
  cooldown_8s / cooldown_12s   (force p=0 after non_broadcast ends)
  whitworth_1s                 (ECAPA Whitworth>=0.25 veto for 1s)
  cooldown_8s_whitworth_1s

Non-broadcast ends come from broadcast_labels (not original gold alone).
Live path untouched.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from experiments.audio_learn.boundary_recovery import apply_cooldown
from experiments.audio_learn.desk_voice_hold import HOLD_S, LINE, NAMES, _hot_ends, _veto
from experiments.audio_learn.product_scorecard import (
    DATA,
    EVAL,
    aggregate,
    load_accepted,
    load_frozen_probs,
    non_broadcast_intervals,
    score_run,
)
from experiments.audio_learn.splits import EVAL as EVAL_SESSIONS

OUT = DATA / "product_latch_card"


def _non_broadcast_spans(session: str, accepted: list[dict]) -> list[tuple[float, float]]:
    return [(float(r["start_s"]), float(r["end_s"])) for r in accepted if r["session"] == session and r["bucket"] == "non_broadcast"]


def _apply_whitworth(session: str, times: np.ndarray, probs: np.ndarray) -> np.ndarray:
    hot = _hot_ends(session, ["Andrew Whitworth"])
    return _veto(times, probs, hot, HOLD_S)


def _delta(base: dict, other: dict) -> dict:
    cells = {}
    for k in base["cells"]:
        cells[k] = round(other["cells"][k] - base["cells"][k], 1)
    return {
        "non_broadcast_coverage_delta": round(
            (other["non_broadcast_coverage"] or 0) - (base["non_broadcast_coverage"] or 0), 4
        ),
        "broadcast_muted_s_delta": round(other["broadcast_muted_s"] - base["broadcast_muted_s"], 1),
        "cells_delta": cells,
        "focus_odell_delta": round(
            other["focus"]["hush_20260924_220624"]["odell"] - base["focus"]["hush_20260924_220624"]["odell"],
            2,
        ),
        "focus_palmer_delta": round(
            other["focus"]["hush_20260924_220624"]["palmer"] - base["focus"]["hush_20260924_220624"]["palmer"],
            2,
        ),
        "focus_chilis_covered": other["focus"]["hush_20260924_220624"]["chilis"],
        "focus_amex_covered": other["focus"]["hush_20261008_205100"]["amex"],
    }


def _keep_reject(name: str, base: dict, other: dict, intent: str) -> dict:
    """Hard rules from product cells — not vibes."""
    d = _delta(base, other)
    cov_drop = -d["non_broadcast_coverage_delta"]
    desk_delta = d["cells_delta"]["desk_s"]
    return_delta = d["cells_delta"]["show_return_s"]
    reasons = []
    decision = "KEEP"
    if cov_drop > 0.02:
        decision = "REJECT"
        reasons.append(f"non_broadcast coverage drop {cov_drop:.4f} > 0.02")
    if desk_delta > 1.0:
        decision = "REJECT"
        reasons.append(f"desk muted seconds rose {desk_delta}")
    # chili/amex must stay covered (they are non_broadcast)
    if other["focus"]["hush_20260924_220624"]["chilis"] < base["focus"]["hush_20260924_220624"]["chilis"] - 2:
        decision = "REJECT"
        reasons.append("Chili's cover lost")
    if other["focus"]["hush_20261008_205100"]["amex"] < base["focus"]["hush_20261008_205100"]["amex"] - 2:
        decision = "REJECT"
        reasons.append("Amex cover lost")
    if intent == "sticky_return" and return_delta >= -2 and decision == "KEEP":
        decision = "REJECT"
        reasons.append(f"show_return cell barely moved ({return_delta})")
    if intent == "desk" and desk_delta > -5 and d["focus_odell_delta"] > -5 and decision == "KEEP":
        decision = "REJECT"
        reasons.append("desk/Odell not materially freed")
    if not reasons and decision == "KEEP":
        reasons.append("coverage held; target cell improved; Chili's/Amex held")
    return {"run": name, "intent": intent, "decision": decision, "reasons": reasons, "delta": d}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    accepted = load_accepted()
    frozen = load_frozen_probs(EVAL_SESSIONS)

    variants: dict[str, dict[str, tuple[np.ndarray, np.ndarray]]] = {"frozen": frozen}
    for cool in (8.0, 12.0):
        keyed = {}
        for session, (times, probs) in frozen.items():
            ads = _non_broadcast_spans(session, accepted)
            keyed[session] = (times, apply_cooldown(times, probs, ads, cool))
        variants[f"cooldown_{int(cool)}s"] = keyed

    whit = {}
    for session, (times, probs) in frozen.items():
        whit[session] = (times, _apply_whitworth(session, times, probs))
    variants["whitworth_1s"] = whit

    combo = {}
    for session, (times, probs) in frozen.items():
        ads = _non_broadcast_spans(session, accepted)
        cooled = apply_cooldown(times, probs, ads, 8.0)
        combo[session] = (times, _apply_whitworth(session, times, cooled))
    variants["cooldown_8s_whitworth_1s"] = combo

    reports = {}
    for name, probs_map in variants.items():
        reports[name] = score_run(name, probs_map, OUT)

    base = reports["frozen"]["aggregate"]
    intents = {
        "cooldown_8s": "sticky_return",
        "cooldown_12s": "sticky_return",
        "whitworth_1s": "desk",
        "cooldown_8s_whitworth_1s": "desk",
    }
    decisions = {}
    for name, intent in intents.items():
        decisions[name] = _keep_reject(name, base, reports[name]["aggregate"], intent)
        print(
            f"KEEP/REJECT {name}: {decisions[name]['decision']} :: {decisions[name]['reasons']}",
            flush=True,
        )

    # raw cell table
    print("\n=== RAW CELL TABLE (broadcast muted seconds by class) ===", flush=True)
    print(
        f"{'run':28} {'cov':7} {'bcast_mut':9} {'desk':7} {'return':7} {'other':7} {'unlab':7} {'odell':7} {'palmer':7}",
        flush=True,
    )
    for name, rep in reports.items():
        a = rep["aggregate"]
        od = a["focus"]["hush_20260924_220624"]["odell"]
        pa = a["focus"]["hush_20260924_220624"]["palmer"]
        print(
            f"{name:28} {a['non_broadcast_coverage']:.4f} {a['broadcast_muted_s']:9.1f} "
            f"{a['cells']['desk_s']:7.1f} {a['cells']['show_return_s']:7.1f} "
            f"{a['cells']['other_broadcast_s']:7.1f} {a['cells']['unlabeled_program_s']:7.1f} "
            f"{od:7.1f} {pa:7.1f}",
            flush=True,
        )

    summary = {
        "product_goal": "play broadcast / mute non_broadcast",
        "controller": reports["frozen"]["aggregate"],
        "line_voice": LINE,
        "hold_s": HOLD_S,
        "decisions": decisions,
        "aggregates": {k: v["aggregate"] for k, v in reports.items()},
        "receipt_root": str(OUT),
    }
    (OUT / "SUMMARY.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (OUT / "KEEP_REJECT.md").write_text(
        "\n".join(
            [
                "# Product latch keep/reject (raw cells)",
                "",
                "Scorecard: `product_scorecard` cells — desk / show_return / other_broadcast / unlabeled.",
                "Mute target: accepted non_broadcast labels.",
                "",
                *[
                    f"## {name}\n- **{row['decision']}**\n"
                    + "\n".join(f"- {r}" for r in row["reasons"])
                    + "\n- delta: `"
                    + json.dumps(row["delta"])
                    + "`\n"
                    for name, row in decisions.items()
                ],
                "",
                f"Receipts: `{OUT}`",
            ]
        ),
        encoding="utf-8",
    )
    print("wrote", OUT / "SUMMARY.json", flush=True)


if __name__ == "__main__":
    main()
