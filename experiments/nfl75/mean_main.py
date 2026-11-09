"""Freeze one rolling mean on the NBC games, then score the two Prime tapes.

    python -m experiments.nfl75.mean_main

October 8 and September 24 do not move the window or the start line. The
oracle return is diagnostic. Speakers stay put. No model is trained.
"""

from __future__ import annotations

import json
from pathlib import Path

from experiments.measurement.metrics import program_regions, target_commercials
from experiments.nfl75.diagnose import perfect_endings
from experiments.nfl75.inventory import active_intervals, coverage_by_session, excluded_ranges, wall_gaps
from experiments.nfl75.mean import (
    PRIME_SESSIONS,
    WINDOWS,
    assert_nbc_only,
    assign_context,
    choose_start,
    covers_from_mean,
    decide,
    false_start_covers,
    overlap_coefficient,
    product_caps,
    quantiles,
    rolling_means,
    signal_by_break,
)
from experiments.nfl75.persist import FIT, WINDOW_S, _logits, nbc_lines
from experiments.nfl75.score import _with_exclusions, playback_from_covers, score_product
from tools.gpu_lab.embed import MODEL_ID, cache_path
from tools.gpu_lab.splits import HOLDOUTS

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "docs" / "ohush" / "research" / "NFL75_MEAN_001"


def _round(value, places: int):
    if value is None:
        return None
    return round(float(value), places)


def _inside(moment: float, ranges: list[tuple[float, float]]) -> bool:
    return any(start - 1e-9 <= moment < end - 1e-9 for start, end in ranges)


def _stream(head, session: str) -> tuple[list[float], list[float]]:
    if session in HOLDOUTS:
        raise RuntimeError(f"refusing sealed holdout {session}")
    times, scores, _labels = _logits(head, session)
    return [float(moment) for moment in times], [float(score) for score in scores]


def _labels(session: str):
    coverage = coverage_by_session()[session]
    intervals = active_intervals(session)
    combined = _with_exclusions(intervals, excluded_ranges(session, intervals))
    return coverage, intervals, target_commercials(intervals), program_regions(coverage, combined)


def _causal(session: str, times: list[float], coverage: tuple[float, float]) -> dict:
    """Stamp contract only. The encoder is not re-run, so this is not a prefix proof."""
    meta_path = cache_path(session, WINDOW_S).with_suffix(".json")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    issues = []
    if meta.get("model") != MODEL_ID:
        issues.append(f"sidecar model is {meta.get('model')!r}")
    if float(meta.get("window_s", -1)) != WINDOW_S:
        issues.append(f"sidecar window is {meta.get('window_s')!r}")
    if times[0] + 1e-3 < coverage[0] + WINDOW_S:
        issues.append("the first score starts before a full past window")
    if times[-1] + 1.0 > coverage[1] + 1e-3:
        issues.append("the last score orders a hop past the end of coverage")
    gaps = [times[index] - times[index - 1] for index in range(1, len(times))]
    backwards = sum(1 for gap in gaps if gap < -1e-9)
    if backwards:
        issues.append(f"{backwards} timestamps move backwards")
    ordered = sorted(gaps)
    median = ordered[len(ordered) // 2] if ordered else None
    if median is None or abs(median - 1.0) > 0.05:
        issues.append(f"median hop is {median}")
    return {
        "causal_under_stamp_contract": not issues,
        "encoder_prefix_reproven": False,
        "issues": issues,
        "model": meta.get("model"),
        "window_s": meta.get("window_s"),
        "n": len(times),
        "first_t": round(times[0], 3),
        "last_t": round(times[-1], 3),
        "median_hop_s": None if median is None else round(float(median), 3),
        "audio_contract": "each score stamped at t uses audio [t-5, t); the mean uses stamps at or before the decision",
    }


def _share(means: list[float | None], mask: list[bool], line: float) -> dict:
    chosen = [mean for mean, keep in zip(means, mask) if keep and mean is not None]
    if not chosen:
        return {"n": 0, "share_at_or_above": None}
    hits = sum(1 for mean in chosen if mean >= line)
    return {"n": len(chosen), "share_at_or_above": round(hits / len(chosen), 4)}


def _policy_summary(name: str, scored: dict, covers: list[tuple[float, float]], *, oracle: bool) -> dict:
    false_breaks = sum(1 for row in scored["breaks"] if float(row["late_return_s"]) > 1e-6)
    return {
        "name": name,
        "oracle": oracle,
        "diagnostic_only": oracle or not scored["evaluable"],
        "deployable": False,
        "covers": len(covers),
        "commercial_s": _round(scored["commercial_s"], 3),
        "commercial_covered_s": _round(scored["commercial_covered_s"], 3),
        "commercial_coverage": _round(scored["commercial_coverage"], 4),
        "program_s": _round(scored["program_s"], 3),
        "program_covered_s": _round(scored["program_covered_s"], 3),
        "false_mute_episodes": scored["false_mute_episodes"],
        "false_mutes_per_hour": _round(scored["false_mutes_per_hour"], 3),
        "longest_false_mute_s": _round(scored["longest_false_mute_s"], 3),
        "program_hidden_per_hour": _round(scored["program_hidden_per_hour"], 3),
        "late_return_breaks": false_breaks,
        "product_caps": product_caps(scored),
        "acceptance_pass": scored["acceptance"]["pass"],
    }


def _touching(covers: list[tuple[float, float]], start: float, end: float) -> list[list[float]]:
    rows = []
    for left, right in covers:
        if min(right, end) - max(left, start) > 1e-9:
            rows.append([round(left, 3), round(right, 3)])
    return rows


def select(head) -> dict:
    assert_nbc_only(FIT)
    pooled: dict[int, dict[str, list[float]]] = {window: {"commercial": [], "program": []} for window in WINDOWS}
    in_sample = []
    for session in FIT:
        times, scores = _stream(head, session)
        coverage, _intervals, commercials, program = _labels(session)
        causal = _causal(session, times, coverage)
        if not causal["causal_under_stamp_contract"]:
            raise RuntimeError(f"{session} failed the stamp contract: {causal['issues']}")
        means_by_window = {window: rolling_means(times, scores, window) for window in WINDOWS}
        for window, means in means_by_window.items():
            for moment, mean in zip(times, means):
                if mean is None:
                    continue
                if _inside(moment, commercials):
                    pooled[window]["commercial"].append(mean)
                elif _inside(moment, program):
                    pooled[window]["program"].append(mean)
        in_sample.append({"session": session, "causal": causal, "means": means_by_window, "times": times, "scores": scores})
    choice = choose_start(pooled)
    window = choice["window_s"]
    line = choice["start_line"]
    described = []
    for row in in_sample:
        times = row["times"]
        means = row["means"][window]
        _coverage, _intervals, commercials, program = _labels(row["session"])
        commercial_mask = [_inside(moment, commercials) for moment in times]
        program_mask = [_inside(moment, program) for moment in times]
        signals = signal_by_break(times, means, commercials, window=window, start_line=line)
        described.append(
            {
                "session": row["session"],
                "in_sample": True,
                "commercial_seconds": _share(means, commercial_mask, line),
                "program_seconds": _share(means, program_mask, line),
                "breaks": len(signals),
                "signal_within_30": sum(
                    1 for item in signals if item["delay_s"] is not None and item["delay_s"] <= 30.0
                ),
                "no_signal": sum(1 for item in signals if item["delay_s"] is None),
            }
        )
    choice["candidates"] = [
        {
            "window_s": row["window_s"],
            "gap": _round(row["gap"], 4),
            "commercial_p10": _round(row["commercial"]["p10"], 4),
            "commercial_p50": _round(row["commercial"]["p50"], 4),
            "program_p50": _round(row["program"]["p50"], 4),
            "program_p90": _round(row["program"]["p90"], 4),
            "commercial_n": int(row["commercial"]["n"]),
            "program_n": int(row["program"]["n"]),
        }
        for row in choice["candidates"]
    ]
    choice["start_line"] = float(choice["start_line"])
    choice["in_sample"] = described
    choice["prior_training_overlap"] = {
        "logistic_fit_sessions": list(FIT),
        "selection_sessions": list(FIT),
        "same_games": True,
        "gpu_lab_TRAIN_also_names": "hush_20260924_220624",
        "september_24_used_to_fit_this_head": False,
        "september_24_used_to_choose_this_line": False,
        "october_8_used_to_choose_this_line": False,
        "note": (
            "The line is chosen on the same two NBC games the logistic head was fit on. "
            "Those scores are in-sample. September 24 is named in the gpu_lab TRAIN split "
            "and was not used to fit this head or to place this line. Prime replay is a "
            "development inspection, not held-out confirmation."
        ),
    }
    return choice


def _contexts(times, means, commercials, program, line: float) -> dict:
    buckets: dict[str, list[float]] = {}
    both = 0
    for moment, mean in zip(times, means):
        if mean is None or not (_inside(moment, commercials) or _inside(moment, program)):
            continue
        names = assign_context(moment, commercials)
        if "post_return_30" in names and "pre_commercial_30" in names:
            both += 1
        for name in names:
            buckets.setdefault(name, []).append(mean)
    rendered = {}
    for name, values in buckets.items():
        spread = quantiles(values)
        if spread is not None:
            spread["share_at_or_above_start"] = round(
                sum(1 for value in values if value >= line) / len(values), 4
            )
        rendered[name] = spread
    pairs = (
        ("commercial_interior", "ordinary_football"),
        ("commercial_interior", "pre_commercial_30"),
        ("commercial_interior", "post_return_30"),
        ("commercial_interior", "commercial_edge"),
    )
    overlaps = []
    for left, right in pairs:
        overlaps.append(
            {
                "left": left,
                "right": right,
                "overlap": None
                if left not in buckets or right not in buckets
                else _round(overlap_coefficient(buckets[left], buckets[right]), 4),
            }
        )
    return {"groups": rendered, "overlap": overlaps, "seconds_in_both_boundary_bands": both}


def measure_session(head, choice: dict, session: str) -> dict:
    if session not in PRIME_SESSIONS:
        raise RuntimeError(f"{session} is not one of the two Prime development tapes")
    times, scores = _stream(head, session)
    coverage, intervals, commercials, program = _labels(session)
    causal = _causal(session, times, coverage)
    window = int(choice["window_s"])
    line = float(choice["start_line"])
    means = rolling_means(times, scores, window)
    covers = covers_from_mean(times, scores, window=window, start_line=line)
    oracle = perfect_endings(playback_from_covers(coverage, covers), commercials)
    summaries = []
    break_rows = []
    actual_breaks = []
    oracle_breaks = []
    for name, rows, is_oracle in (
        ("rolling_mean_oracle_return", oracle, True),
        ("rolling_mean_actual_return", covers, False),
    ):
        playback = playback_from_covers(coverage, rows)
        scored = score_product(
            coverage,
            intervals,
            playback,
            session=session,
            oracle=is_oracle,
            audio_present=True,
            wall_gap_s=wall_gaps().get(session, 0.0),
            excluded_ranges=excluded_ranges(session, intervals),
        )
        summaries.append(_policy_summary(name, scored, rows, oracle=is_oracle))
        if name == "rolling_mean_actual_return":
            actual_breaks = scored["breaks"]
        else:
            oracle_breaks = scored["breaks"]
    if len(actual_breaks) != len(commercials) or len(oracle_breaks) != len(commercials):
        raise RuntimeError("break rows do not match the commercial ledger")
    signals = signal_by_break(times, means, commercials, window=window, start_line=line)
    openings = false_start_covers(covers, commercials)
    for signal, actual, gold in zip(signals, actual_breaks, oracle_breaks):
        break_rows.append(
            {
                "break": signal["break"],
                "start_s": _round(signal["start_s"], 3),
                "end_s": _round(signal["end_s"], 3),
                "length_s": _round(signal["length_s"], 3),
                "signal_delay_s": _round(signal["delay_s"], 3),
                "signal_during_break": signal["during_break"],
                "causal_covers": _touching(covers, signal["start_s"], signal["end_s"]),
                "oracle_covers": _touching(oracle, signal["start_s"], signal["end_s"]),
                "causal_covered_s": _round(actual["covered_s"], 3),
                "oracle_covered_s": _round(gold["covered_s"], 3),
                "causal_late_return_s": _round(actual["late_return_s"], 3),
                "oracle_late_return_s": _round(gold["late_return_s"], 3),
                "causal_start_delay_s": _round(actual["start_delay_s"], 3),
                "opened_before_break": any(left < signal["start_s"] - 1e-6 for left, _right in covers if min(_right, signal["end_s"]) - max(left, signal["start_s"]) > 1e-9),
            }
        )
    commercial_mask = [_inside(moment, commercials) for moment in times]
    program_mask = [_inside(moment, program) for moment in times]
    return {
        "session": session,
        "development_inspection": True,
        "deployable": False,
        "causal": causal,
        "false_start_events": len(openings),
        "false_start_open_s": [round(start, 3) for start, _end in openings],
        "commercial_seconds": _share(means, commercial_mask, line),
        "program_seconds": _share(means, program_mask, line),
        "signal_within_10": sum(1 for row in signals if row["delay_s"] is not None and row["delay_s"] <= 10.0),
        "signal_within_20": sum(1 for row in signals if row["delay_s"] is not None and row["delay_s"] <= 20.0),
        "signal_within_30": sum(1 for row in signals if row["delay_s"] is not None and row["delay_s"] <= 30.0),
        "signal_eventually": sum(1 for row in signals if row["delay_s"] is not None),
        "no_signal": sum(1 for row in signals if row["delay_s"] is None),
        "policies": summaries,
        "breaks": break_rows,
        "contexts": _contexts(times, means, commercials, program, line),
    }


def _cell(sessions: list[dict], policy: str, field: str):
    return {row["session"]: next(item[field] for item in row["policies"] if item["name"] == policy) for row in sessions}


def main() -> None:
    lines = nbc_lines()
    choice = select(lines["head"])
    prime = [measure_session(lines["head"], choice, session) for session in PRIME_SESSIONS]
    by_policy = {
        "oracle": [next(item for item in row["policies"] if item["oracle"]) for row in prime],
        "actual": [next(item for item in row["policies"] if not item["oracle"]) for row in prime],
    }
    verdict = decide(by_policy["oracle"], by_policy["actual"])
    if not all(row["causal"]["causal_under_stamp_contract"] for row in prime):
        verdict = {
            **verdict,
            "verdict": "DIAGNOSTIC",
            "next_change": "A score stamp failed the past-only contract. Do not treat these numbers as causal.",
        }
    payload = {
        "experiment": "NFL75_MEAN_001",
        "deployable": False,
        "automatic_mute": False,
        "fit": lines["fit"],
        "published_start_line_left_untouched": lines["start_line"],
        "clear_program_ceiling_left_untouched": lines["return_line"],
        "frozen": {
            "window_s": choice["window_s"],
            "start_line": choice["start_line"],
            "placement": choice["placement"],
            "gap": choice["gap"],
            "return": "three raw seconds at or below zero",
            "candidates": choice["candidates"],
            "prior_training_overlap": choice["prior_training_overlap"],
            "in_sample_nbc": choice["in_sample"],
        },
        "verdict": verdict,
        "prime": [
            {key: value for key, value in row.items() if key != "breaks"} | {"breaks": row["breaks"]}
            for row in prime
        ],
        "comparison": {
            "commercial_coverage": {
                "oracle": _cell(prime, "rolling_mean_oracle_return", "commercial_coverage"),
                "actual": _cell(prime, "rolling_mean_actual_return", "commercial_coverage"),
            },
            "false_start_events": {row["session"]: row["false_start_events"] for row in prime},
            "false_mute_episodes": {
                "oracle": _cell(prime, "rolling_mean_oracle_return", "false_mute_episodes"),
                "actual": _cell(prime, "rolling_mean_actual_return", "false_mute_episodes"),
            },
            "late_return_breaks": {
                "oracle": _cell(prime, "rolling_mean_oracle_return", "late_return_breaks"),
                "actual": _cell(prime, "rolling_mean_actual_return", "late_return_breaks"),
            },
            "longest_false_mute_s": {
                "oracle": _cell(prime, "rolling_mean_oracle_return", "longest_false_mute_s"),
                "actual": _cell(prime, "rolling_mean_actual_return", "longest_false_mute_s"),
            },
            "program_covered_s": {
                "oracle": _cell(prime, "rolling_mean_oracle_return", "program_covered_s"),
                "actual": _cell(prime, "rolling_mean_actual_return", "program_covered_s"),
            },
            "program_hidden_per_hour": {
                "oracle": _cell(prime, "rolling_mean_oracle_return", "program_hidden_per_hour"),
                "actual": _cell(prime, "rolling_mean_actual_return", "program_hidden_per_hour"),
            },
        },
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(verdict["verdict"], verdict["start_detector"], verdict["actual_return"])
    print(verdict["next_change"])
    print(
        f"window {choice['window_s']} line {choice['start_line']:.4f} via {choice['placement']}"
    )
    for row in prime:
        oracle = row["policies"][0]
        actual = row["policies"][1]
        print(
            row["session"],
            f"oracle {oracle['commercial_coverage']} hidden {oracle['program_covered_s']} worst {oracle['longest_false_mute_s']}",
            f"actual {actual['commercial_coverage']} hidden {actual['program_covered_s']} worst {actual['longest_false_mute_s']}",
            f"false starts {row['false_start_events']}",
            f"signals within 30 {row['signal_within_30']}/{row['signal_eventually'] + row['no_signal']}",
        )


if __name__ == "__main__":
    main()
