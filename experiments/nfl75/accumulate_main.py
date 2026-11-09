"""Compare consecutive holds with a 60 percent rolling count.

    python -m experiments.nfl75.accumulate_main

October 8 and September 24 are development. Neither tape chooses a threshold.
The 8.285 line is diagnostic. Speakers stay put.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from experiments.measurement.metrics import program_regions, target_commercials
from experiments.nfl75.accumulate import (
    ACCUMULATED_FRACTION,
    KEEP_COVERAGE_MARGIN,
    LOGISTIC_RETURN,
    ROLL_WINDOWS,
    context_name,
    covers_accumulated,
    rolling,
    support_by_break,
)
from experiments.nfl75.inventory import active_intervals, coverage_by_session, wall_gaps
from experiments.nfl75.persist import (
    PERSIST_SECONDS,
    PUBLISHED_START_LINE,
    RETURN_PERSIST_S,
    _logits,
    covers_from_scores,
    nbc_lines,
    sustained_runs,
)
from experiments.nfl75.score import playback_from_covers, score_product
from tools.gpu_lab.splits import HOLDOUTS

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "docs" / "ohush" / "research" / "NFL75_ACCUMULATE_001"
SESSIONS = ("hush_20261008_205100", "hush_20260924_220624")


def _round(value, places: int):
    if value is None:
        return None
    return round(float(value), places)


def _spread(values: list[float]) -> dict | None:
    if not values:
        return None
    column = np.asarray(values, dtype=np.float64)
    return {
        "n": int(column.size),
        "p50": round(float(np.percentile(column, 50)), 3),
        "p90": round(float(np.percentile(column, 90)), 3),
        "p99": round(float(np.percentile(column, 99)), 3),
        "max": round(float(column.max()), 3),
        "share_at_least_60": round(float(np.mean(column >= ACCUMULATED_FRACTION)), 4),
    }


def _policy_row(name: str, scored: dict, covers: list[tuple[float, float]], *, diagnostic: bool) -> dict:
    return {
        "name": name,
        "diagnostic_only": diagnostic,
        "covers": len(covers),
        "commercial_s": _round(scored["commercial_s"], 3),
        "commercial_covered_s": _round(scored["commercial_covered_s"], 3),
        "commercial_coverage": _round(scored["commercial_coverage"], 4),
        "program_covered_s": _round(scored["program_covered_s"], 3),
        "false_mute_episodes": scored["false_mute_episodes"],
        "false_mutes_per_hour": _round(scored["false_mutes_per_hour"], 3),
        "longest_false_mute_s": _round(scored["longest_false_mute_s"], 3),
        "program_hidden_per_hour": _round(scored["program_hidden_per_hour"], 3),
        "acceptance": scored["acceptance"]["pass"],
    }


def _inside_caps(row: dict) -> bool:
    return (
        (row["false_mutes_per_hour"] or 0) < 1
        and (row["longest_false_mute_s"] or 0) < 10
        and (row["program_hidden_per_hour"] or 0) < 5
    )


def _separated(commercial: dict | None, program: dict | None) -> bool:
    if not commercial or not program:
        return False
    # Both medians at zero is not separation. The commercial middle of the
    # window has to clear the program tail, and the 60 percent rate has to
    # be higher by a real margin.
    return (
        commercial["p50"] > program["p90"]
        and commercial["share_at_least_60"] > program["share_at_least_60"] + 0.05
    )


def measure_session(head, lines: dict, session: str) -> dict:
    if session in HOLDOUTS:
        raise RuntimeError(f"refusing sealed holdout {session}")
    times, scores, _labels = _logits(head, session)
    clock = [float(moment) for moment in times]
    values = [float(score) for score in scores]
    coverage = coverage_by_session()[session]
    intervals = active_intervals(session)
    commercials = target_commercials(intervals)
    program = program_regions(coverage, intervals)
    high = lines["start_line"]
    clear = lines["return_line"]
    policies = []
    for persist_s in PERSIST_SECONDS:
        covers = covers_from_scores(
            clock, values, persist_s=persist_s, start_line=high, return_line=clear
        )
        scored = score_product(
            coverage,
            intervals,
            playback_from_covers(coverage, covers),
            session=session,
            audio_present=True,
            wall_gap_s=wall_gaps().get(session, 0.0),
        )
        policies.append(_policy_row(f"consecutive_{persist_s:.0f}s_at_12.155", scored, covers, diagnostic=False))
        covers = covers_from_scores(
            clock, values, persist_s=persist_s, start_line=clear, return_line=LOGISTIC_RETURN
        )
        scored = score_product(
            coverage,
            intervals,
            playback_from_covers(coverage, covers),
            session=session,
            audio_present=True,
            wall_gap_s=wall_gaps().get(session, 0.0),
        )
        policies.append(_policy_row(f"consecutive_{persist_s:.0f}s_at_8.285", scored, covers, diagnostic=True))
    for window in ROLL_WINDOWS:
        for line, label, diagnostic in ((high, "12.155", False), (clear, "8.285", True)):
            covers = covers_accumulated(clock, values, window=window, line=line)
            scored = score_product(
                coverage,
                intervals,
                playback_from_covers(coverage, covers),
                session=session,
                audio_present=True,
                wall_gap_s=wall_gaps().get(session, 0.0),
            )
            policies.append(
                _policy_row(f"rolling_{window}s_{int(ACCUMULATED_FRACTION * 100)}pct_at_{label}", scored, covers, diagnostic=diagnostic)
            )
    distributions = []
    for window in ROLL_WINDOWS:
        for line, label in ((high, "12.155"), (clear, "8.285")):
            rows = rolling(clock, values, window, line)
            buckets: dict[str, dict[str, list[float]]] = {}
            for moment, row in zip(clock, rows):
                if row is None or not _inside(moment, commercials, program):
                    continue
                names = [context_name(moment, commercials)]
                names.append("commercial" if _inside(moment, commercials, []) else "program")
                for name in names:
                    bucket = buckets.setdefault(name, {"fraction": [], "mean": [], "maximum": [], "longest_run": []})
                    bucket["fraction"].append(row["fraction"])
                    bucket["mean"].append(row["mean"])
                    bucket["maximum"].append(row["maximum"])
                    bucket["longest_run"].append(row["longest_run"])
            rendered = {}
            for name, bucket in buckets.items():
                rendered[name] = {
                    "fraction": _spread(bucket["fraction"]),
                    "mean_score": _spread(bucket["mean"]),
                    "maximum_score": _spread(bucket["maximum"]),
                    "longest_run": _spread(bucket["longest_run"]),
                }
            commercial = rendered.get("commercial", {}).get("fraction")
            program_spread = rendered.get("program", {}).get("fraction")
            distributions.append(
                {
                    "window_s": window,
                    "line": label,
                    "separated": _separated(commercial, program_spread),
                    "groups": rendered,
                }
            )
    support = []
    for window in ROLL_WINDOWS:
        for line, label in ((high, "12.155"), (clear, "8.285")):
            rows = support_by_break(clock, values, commercials, window=window, line=line)
            support.append(
                {
                    "window_s": window,
                    "line": label,
                    "breaks": len(rows),
                    "within_10": sum(1 for row in rows if row["within"]["10"]),
                    "within_20": sum(1 for row in rows if row["within"]["20"]),
                    "within_30": sum(1 for row in rows if row["within"]["30"]),
                    "no_window": sum(1 for row in rows if row["delay_s"] is None),
                    "pods": [
                        {
                            "break": row["break"],
                            "start_s": round(row["start_s"], 3),
                            "length_s": round(row["length_s"], 3),
                            "delay_s": None if row["delay_s"] is None else round(row["delay_s"], 3),
                            "positives_inside_break": row["positives_inside_break"],
                            "within_30": row["within"]["30"],
                        }
                        for row in rows
                    ],
                }
            )
    runs = sustained_runs(clock, values, clear)
    return {
        "session": session,
        "role": "development_prime",
        "score_rows": len(clock),
        "commercial_breaks": len(commercials),
        "longest_run_at_8.285": max((row["seconds"] for row in runs), default=0),
        "runs_of_at_least_10s_at_8.285": sum(1 for row in runs if row["seconds"] >= 10),
        "runs_of_at_least_20s_at_8.285": sum(1 for row in runs if row["seconds"] >= 20),
        "policies": policies,
        "distributions": distributions,
        "support": support,
    }


def _inside(moment: float, commercials: list[tuple[float, float]], program: list[tuple[float, float]]) -> bool:
    ranges = commercials + program
    return any(start - 1e-9 <= moment < end - 1e-9 for start, end in ranges)


def verdict(sessions: list[dict]) -> dict:
    """Fixed before the tapes were read. A keep is not a mute authorization."""
    consecutive = []
    accumulated = []
    for session in sessions:
        for row in session["policies"]:
            item = {**row, "session": session["session"]}
            if row["name"].startswith("consecutive_"):
                consecutive.append(item)
            else:
                accumulated.append(item)
    consecutive_rejected = all((row["commercial_coverage"] or 0) < 0.75 or not _inside_caps(row) for row in consecutive)
    best_consecutive = {}
    for row in consecutive:
        key = (row["session"], "12.155" if "12.155" in row["name"] else "8.285")
        best_consecutive[key] = max(best_consecutive.get(key, 0.0), row["commercial_coverage"] or 0.0)
    keepers = []
    for row in accumulated:
        line = "12.155" if "12.155" in row["name"] else "8.285"
        baseline = best_consecutive[(row["session"], line)]
        if (
            (row["commercial_coverage"] or 0) >= baseline + KEEP_COVERAGE_MARGIN
            and _inside_caps(row)
        ):
            keepers.append(row["name"] + "@" + row["session"])
    by_session = {row["session"] for row in accumulated}
    kept_names = {item.split("@", 1)[0] for item in keepers}
    accumulated_kept = any(all(f"{name}@{session}" in keepers for session in by_session) for name in kept_names)
    separated = []
    for session in sessions:
        for row in session["distributions"]:
            if row["separated"]:
                separated.append(f"{session['session']} {row['window_s']}s at {row['line']}")
    if accumulated_kept:
        recommendation = "KEEP accumulated evidence. Build the simplest rolling count. Do not mute from it yet."
    elif separated:
        recommendation = (
            "REJECT both confirmation rules as a product. Some rolling fractions separate, "
            "and the 60 percent bar still misses the false-mute caps or the coverage margin. "
            "Do not add more timers on these lines."
        )
    else:
        recommendation = (
            "REJECT consecutive holds and the 60 percent count. "
            "Seconds above 12.155 and 8.285 do not accumulate through an advertisement. "
            "The mean score still sits higher in ads than in ordinary football, so the "
            "next measurement is a rolling mean with a cutoff frozen on the NBC games. "
            "Do not train a new model, and do not add another timer on these two lines."
        )
    return {
        "consecutive": "REJECT" if consecutive_rejected else "KEEP",
        "accumulated": "KEEP" if accumulated_kept else "REJECT",
        "distributions_that_separate": separated,
        "recommendation": recommendation,
    }


def main() -> None:
    lines = nbc_lines()
    head = lines.pop("head")
    if abs(lines["start_line"] - PUBLISHED_START_LINE) > 0:
        raise RuntimeError("the 12.155 line moved")
    sessions = [measure_session(head, lines, session) for session in SESSIONS]
    result = {
        "experiment": "NFL75_ACCUMULATE_001",
        "deployable": False,
        "speakers_moved": False,
        "october_chose_thresholds": False,
        "fraction": ACCUMULATED_FRACTION,
        "return_persist_s": RETURN_PERSIST_S,
        "logistic_return": LOGISTIC_RETURN,
        "start_line": lines["start_line"],
        "clear_program_line": lines["return_line"],
        "fit": lines["fit"],
        "sessions": sessions,
        "verdict": verdict(sessions),
        "labels": (
            "These Prime ledgers mark ad breaks only. Music, promos, halftime, and "
            "announcer turns are not labeled. ordinary_program is more than 60 seconds "
            "from every break. return_transition is the 15 seconds after a break. "
            "commercial_edge is the first and last 15 seconds of a break."
        ),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(result["verdict"]["recommendation"], flush=True)
    print(
        f"consecutive {result['verdict']['consecutive']}  accumulated {result['verdict']['accumulated']}",
        flush=True,
    )
    for session in sessions:
        print(session["session"], flush=True)
        for row in session["policies"]:
            print(
                f"  {row['name']}  coverage {row['commercial_coverage']}  "
                f"episodes {row['false_mute_episodes']}  longest {row['longest_false_mute_s']}  "
                f"hidden/hour {row['program_hidden_per_hour']}",
                flush=True,
            )


if __name__ == "__main__":
    main()
