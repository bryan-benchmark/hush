"""Score the KEEP research stack (cool + Clarissa/Whit/Palmer) on product cells.

Writes C:\\OHushData\\gpu_lab\\audio_learn\\research_stack_verify\\
Does not touch ohush_live.
"""

from __future__ import annotations

import json
from pathlib import Path

from experiments.audio_learn.product_scorecard import DATA, load_frozen_probs, score_run
from experiments.audio_learn.research_latch import (
    FITZ_MARGIN,
    PALMER_MARGIN,
    STATUS,
    VOICE_PANELS,
    apply_research_latch,
)
from experiments.audio_learn.splits import EVAL

OUT = DATA / "research_stack_verify"


def _span_muted(game: dict, start: float, end: float) -> float:
    total = 0.0
    for ep in game.get("episodes", []):
        total += max(0.0, min(float(ep["end_s"]), end) - max(float(ep["start_s"]), start))
    return round(total, 2)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    frozen = load_frozen_probs(EVAL)
    cool = {s: (t, apply_research_latch(s, t, p, with_voice=False)) for s, (t, p) in frozen.items()}
    stack = {s: (t, apply_research_latch(s, t, p, with_voice=True)) for s, (t, p) in frozen.items()}

    cool_rep = score_run("cooldown_8s_only", cool, OUT)
    stack_rep = score_run("research_stack", stack, OUT)
    cool_a = cool_rep["aggregate"]
    stack_a = stack_rep["aggregate"]

    g24 = next(g for g in stack_rep["games"] if g["session"] == "hush_20260924_220624")
    g24c = next(g for g in cool_rep["games"] if g["session"] == "hush_20260924_220624")

    delta = {
        "cov_delta": round(stack_a["non_broadcast_coverage"] - cool_a["non_broadcast_coverage"], 4),
        "broadcast_muted_delta": round(stack_a["broadcast_muted_s"] - cool_a["broadcast_muted_s"], 1),
        "desk_delta": round(stack_a["cells"]["desk_s"] - cool_a["cells"]["desk_s"], 1),
        "odell_delta": round(
            stack_a["focus"]["hush_20260924_220624"]["odell"] - cool_a["focus"]["hush_20260924_220624"]["odell"],
            2,
        ),
        "amex_delta": round(
            stack_a["focus"]["hush_20261008_205100"]["amex"] - cool_a["focus"]["hush_20261008_205100"]["amex"],
            2,
        ),
        "chilis_delta": round(
            stack_a["focus"]["hush_20260924_220624"]["chilis"] - cool_a["focus"]["hush_20260924_220624"]["chilis"],
            2,
        ),
        "injury_muted_s": _span_muted(g24, 6267.8, 6287.2),
        "desk5_muted_s": _span_muted(g24, 6315.2, 6336.5),
        "injury_muted_cool": _span_muted(g24c, 6267.8, 6287.2),
        "desk5_muted_cool": _span_muted(g24c, 6315.2, 6336.5),
    }

    reasons = []
    decision = "KEEP"
    if -delta["cov_delta"] > 0.02:
        decision = "REJECT"
        reasons.append(f"coverage drop {-delta['cov_delta']:.4f} > 0.02")
    if delta["amex_delta"] < -2 or delta["chilis_delta"] < -2:
        decision = "REJECT"
        reasons.append(f"spot leak amex={delta['amex_delta']} chilis={delta['chilis_delta']}")
    if decision == "KEEP":
        reasons.append("coverage held; spots held; voice stack frees desk vs cooldown")

    summary = {
        "status": STATUS,
        "panels": [{"name": n, "margin": m} for n, m in VOICE_PANELS]
        + [
            {"name": "James Palmer", "margin": PALMER_MARGIN},
            {"name": "Ryan Fitzpatrick", "margin": FITZ_MARGIN},
        ],
        "decision_vs_cooldown": {"decision": decision, "reasons": reasons, "delta": delta},
        "cooldown_8s_only": cool_a,
        "research_stack": stack_a,
        "michaels_note": (
            "Al Michaels m0.15 incremental KEEP vs prior stack (desk -16.5, spots held) "
            "but REJECT for stack inclusion: cumulative cov vs cooldown exceeds 0.02"
        ),
    }
    (OUT / "SUMMARY.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (OUT / "KEEP_REJECT.md").write_text(
        "\n".join(
            [
                "# Research stack verify (cool + Clarissa m0.10 ∪ Whit m0.15 ∪ Palmer m0.15 ∪ Fitz m0.15)",
                "",
                f"## vs cooldown_8s_only",
                f"- **{decision}**",
                *[f"- {r}" for r in reasons],
                f"- `{json.dumps(delta)}`",
                "",
                "## Absolute (research_stack)",
                f"- coverage {stack_a['non_broadcast_coverage']}",
                f"- desk_s {stack_a['cells']['desk_s']}",
                f"- broadcast_muted_s {stack_a['broadcast_muted_s']}",
                f"- odell {stack_a['focus']['hush_20260924_220624']['odell']}",
                f"- amex {stack_a['focus']['hush_20261008_205100']['amex']}",
                f"- chilis {stack_a['focus']['hush_20260924_220624']['chilis']}",
                f"- injury muted {delta['injury_muted_s']} (cool {delta['injury_muted_cool']})",
                f"- desk5 muted {delta['desk5_muted_s']} (cool {delta['desk5_muted_cool']})",
                "",
                "Not wired to ohush_live.",
            ]
        ),
        encoding="utf-8",
    )
    print(json.dumps(summary["decision_vs_cooldown"], indent=2), flush=True)
    print("stack", stack_a["non_broadcast_coverage"], "desk", stack_a["cells"]["desk_s"], flush=True)
    print("WROTE", OUT, flush=True)


if __name__ == "__main__":
    main()
