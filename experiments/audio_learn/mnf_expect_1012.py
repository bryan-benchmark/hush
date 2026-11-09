"""Expected product KPIs on the Oct 12 MNF tape (TRAIN — in-sample).

Not a blind exam. No MNF ECAPA latch. Writes
C:\\OHushData\\gpu_lab\\audio_learn\\mnf_expect_1012\\
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from experiments.audio_learn.controller import decisions
from experiments.audio_learn.encoder import DATA_ROOT
from experiments.audio_learn.product_scorecard import DATA, load_accepted, score_product_ontology
from experiments.audio_learn.research_latch import apply_research_latch
from experiments.audio_learn.studio_fit import CONTROLLER
from experiments.ledger import sha256_file
from experiments.nfl75.inventory import coverage_by_session
from experiments.nfl75.score import playback_from_decisions

SESSION = "hush_20261012_204200"
HEAD = DATA_ROOT / "checkpoints" / "frozen_head.pt"
OUT = DATA / "mnf_expect_1012"


def _merge_covers(times: np.ndarray, probs: np.ndarray) -> list[tuple[float, float]]:
    coverage = coverage_by_session()[SESSION]
    rows = decisions(times.tolist(), probs.tolist(), **CONTROLLER)
    spans = playback_from_decisions(coverage, rows)
    merged: list[list[float]] = []
    for span in spans:
        if span.state != "covered":
            continue
        if merged and abs(span.start - merged[-1][1]) <= 1e-6:
            merged[-1][1] = float(span.end)
        else:
            merged.append([float(span.start), float(span.end)])
    return [(a, b) for a, b in merged if b > a]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    pred = np.load(DATA_ROOT / "predictions" / "frozen" / f"{SESSION}.npz")
    times = pred["t"].astype(np.float64)
    frozen_p = pred["p"].astype(np.float64)
    cool_p = apply_research_latch(SESSION, times, frozen_p, with_voice=False)

    accepted = [r for r in load_accepted() if r["session"] == SESSION]
    nb = sum(float(r["end_s"]) - float(r["start_s"]) for r in accepted if r["bucket"] == "non_broadcast")
    bc = sum(float(r["end_s"]) - float(r["start_s"]) for r in accepted if r["bucket"] == "broadcast")

    results = {}
    for name, probs in (("frozen", frozen_p), ("cool", cool_p)):
        scored = score_product_ontology(SESSION, times, probs)
        covers = _merge_covers(times, probs)
        keep = {
            key: scored.get(key)
            for key in (
                "non_broadcast_coverage",
                "non_broadcast_covered_s",
                "non_broadcast_s",
                "broadcast_muted_s",
                "false_mute_episodes",
                "longest_false_mute_s",
                "cells",
                "focus",
            )
        }
        results[name] = {
            "product": keep,
            "cover_s": round(sum(b - a for a, b in covers), 2),
            "episodes": len(covers),
            "longest_s": round(max((b - a for a, b in covers), default=0.0), 2),
            "top5": [
                {"start_s": round(a, 2), "end_s": round(b, 2), "length_s": round(b - a, 2)}
                for a, b in sorted(covers, key=lambda row: -(row[1] - row[0]))[:5]
            ],
        }

    cool = results["cool"]["product"]
    frozen = results["frozen"]["product"]
    delta = {
        "cov_delta": round(cool["non_broadcast_coverage"] - frozen["non_broadcast_coverage"], 4),
        "broadcast_muted_delta": round(cool["broadcast_muted_s"] - frozen["broadcast_muted_s"], 1),
        "desk_delta": round(cool["cells"]["desk_s"] - frozen["cells"]["desk_s"], 1),
    }
    summary = {
        "session": SESSION,
        "show": "Monday Night Football",
        "service": "Cable / antenna",
        "role": "TRAIN — frozen head saw this tape; not a blind transfer claim",
        "labels": {
            "accepted_rows": len(accepted),
            "non_broadcast_s": round(nb, 1),
            "broadcast_s": round(bc, 1),
        },
        "live_tonight": {
            "engine": "ohush_live sports_daemon (speaker+audio), NOT research frozen GRU stack",
            "show_key": "mnf",
            "enroll": "Joe Buck + Troy Aikman via enroll_mnf.npy",
            "enroll_role": "return floor 0.10 only — does not start covers",
        },
        "controller": CONTROLLER,
        "results": results,
        "cool_vs_frozen": delta,
        "frozen_head_sha256": sha256_file(HEAD),
    }
    (OUT / "SUMMARY.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    lines = [
        "# MNF expected KPIs — hush_20261012_204200",
        "",
        "**TRAIN tape** (in-sample for frozen head). Thin ontology labels. No MNF voice latch.",
        "",
        "## Product cells (cooldown_8s)",
        f"- coverage **{cool['non_broadcast_coverage']}**",
        f"- non_broadcast covered {cool['non_broadcast_covered_s']} / {cool['non_broadcast_s']}",
        f"- broadcast_muted_s **{cool['broadcast_muted_s']}**",
        f"- desk_s **{cool['cells']['desk_s']}**",
        f"- longest_false_mute_s **{cool['longest_false_mute_s']}**",
        f"- false_mute_episodes {cool['false_mute_episodes']}",
        "",
        "## Raw cover",
        f"- cover_s {results['cool']['cover_s']} longest {results['cool']['longest_s']} episodes {results['cool']['episodes']}",
        "",
        "## Tonight on Mac",
        "Live booth = speaker+audio with show=`mnf` + `enroll_mnf.npy`.",
        "Do not expect TNF research-stack desk numbers.",
        (
            f"Ballpark from this TRAIN cool card: coverage ~{cool['non_broadcast_coverage']}, "
            f"desk FP ~{cool['cells']['desk_s']}s, longest FP ~{cool['longest_false_mute_s']}s "
            "(optimistic vs a true blind MNF)."
        ),
    ]
    (OUT / "EXPECT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"cool_vs_frozen": delta, "cool": cool}, indent=2), flush=True)


if __name__ == "__main__":
    main()
