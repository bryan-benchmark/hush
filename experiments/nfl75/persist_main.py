"""Score the two persistence settings on October 8. Does not mute or open a holdout.

    python -m experiments.nfl75.persist_main
"""

from __future__ import annotations

import json
from pathlib import Path

from experiments.ledger import sha256_file
from experiments.measurement.metrics import target_commercials
from experiments.nfl75.inventory import active_intervals, coverage_by_session, wall_gaps
from experiments.nfl75.persist import (
    PERSIST_SECONDS,
    RETURN_PERSIST_S,
    SESSION,
    WINDOW_S,
    _logits,
    covers_from_scores,
    nbc_lines,
    playback,
    pods_that_never_hold,
    sustained_runs,
)
from experiments.nfl75.score import score_product
from tools.gpu_lab.embed import cache_path
from tools.gpu_lab.splits import HOLDOUTS

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "docs" / "ohush" / "research" / "NFL75_PERSIST_001"


def _round(value, places: int):
    if value is None:
        return None
    return round(float(value), places)


def measure() -> dict:
    if SESSION in HOLDOUTS:
        raise RuntimeError(f"refusing sealed holdout {SESSION}")
    lines = nbc_lines()
    head = lines.pop("head")
    times, scores, _labels = _logits(head, SESSION)
    # Labels from the cache stay out of the decision. The scorer reads gold on its own.
    clock = [float(moment) for moment in times]
    values = [float(score) for score in scores]
    coverage = coverage_by_session()[SESSION]
    intervals = active_intervals(SESSION)
    commercials = target_commercials(intervals)
    runs = sustained_runs(clock, values, lines["start_line"])
    settings = []
    for persist_s in PERSIST_SECONDS:
        spans = playback(
            coverage,
            clock,
            values,
            persist_s=persist_s,
            start_line=lines["start_line"],
            return_line=lines["return_line"],
        )
        scored = score_product(
            coverage,
            intervals,
            spans,
            session=SESSION,
            audio_present=True,
            wall_gap_s=wall_gaps().get(SESSION, 0.0),
        )
        pods = pods_that_never_hold(
            commercials,
            clock,
            values,
            line=lines["start_line"],
            persist_s=persist_s,
        )
        covers = covers_from_scores(
            clock,
            values,
            persist_s=persist_s,
            start_line=lines["start_line"],
            return_line=lines["return_line"],
        )
        settings.append(
            {
                "persist_s": persist_s,
                "return_persist_s": RETURN_PERSIST_S,
                "covers": [{"start_s": round(a, 3), "end_s": round(b, 3)} for a, b in covers],
                "commercial_s": _round(scored["commercial_s"], 3),
                "commercial_covered_s": _round(scored["commercial_covered_s"], 3),
                "commercial_coverage": _round(scored["commercial_coverage"], 4),
                "program_s": _round(scored["program_s"], 3),
                "program_covered_s": _round(scored["program_covered_s"], 3),
                "false_mute_episodes": scored["false_mute_episodes"],
                "false_mutes_per_hour": _round(scored["false_mutes_per_hour"], 3),
                "longest_false_mute_s": _round(scored["longest_false_mute_s"], 3),
                "program_hidden_per_hour": _round(scored["program_hidden_per_hour"], 3),
                "acceptance": scored["acceptance"],
                "pods_total": len(pods),
                "pods_that_never_hold": sum(1 for row in pods if row["never_holds"]),
                "pods": [
                    {
                        "break": row["break"],
                        "start_s": round(row["start_s"], 3),
                        "end_s": round(row["end_s"], 3),
                        "longest_run_s": row["longest_run_s"],
                        "never_holds": row["never_holds"],
                    }
                    for row in pods
                ],
            }
        )
    cache = cache_path(SESSION, WINDOW_S)
    return {
        "experiment": "NFL75_PERSIST_001",
        "session": SESSION,
        "role": "development_prime",
        "deployable": False,
        "speakers_moved": False,
        "start_line": lines["start_line"],
        "return_line": lines["return_line"],
        "return_setter": {
            "session": lines["return_setter"]["session"],
            "t": lines["return_setter"]["t"],
            "score": round(lines["return_setter"]["score"], 6),
        },
        "fit": lines["fit"],
        "window_s": WINDOW_S,
        "cache_sha256": sha256_file(cache),
        "score_rows": len(clock),
        "runs_at_or_above_start_line": len(runs),
        "longest_run_s": max((row["seconds"] for row in runs), default=0),
        "runs_of_at_least_10s": sum(1 for row in runs if row["seconds"] >= 10),
        "runs_of_at_least_20s": sum(1 for row in runs if row["seconds"] >= 20),
        "settings": settings,
        "note": (
            "Command intervals. The 1.5-second return fade is not charged. "
            "October was already inspected and did not set either line."
        ),
    }


def main() -> None:
    result = measure()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    for row in result["settings"]:
        print(
            f"persist {row['persist_s']:.0f}s  "
            f"covered {row['commercial_covered_s']} / {row['commercial_s']}  "
            f"coverage {row['commercial_coverage']}  "
            f"episodes {row['false_mute_episodes']}  "
            f"longest {row['longest_false_mute_s']}  "
            f"hidden/hour {row['program_hidden_per_hour']}  "
            f"pods that never hold {row['pods_that_never_hold']} / {row['pods_total']}",
            flush=True,
        )
    print(
        f"start line {result['start_line']}  return line {result['return_line']}  "
        f"longest run {result['longest_run_s']}s  "
        f"runs>=10 {result['runs_of_at_least_10s']}  runs>=20 {result['runs_of_at_least_20s']}",
        flush=True,
    )


if __name__ == "__main__":
    main()
