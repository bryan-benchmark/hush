"""Replay scorer for the NFL75 product contract.

Legacy `score_timeline` is not modified. This module reads the same interval
rules and then counts false-mute episodes with an explicit merge.
"""

from __future__ import annotations

from experiments.measurement.metrics import (
    Interval,
    Span,
    TimelineError,
    excluded,
    program_regions,
    score_timeline,
    target_commercials,
)

from experiments.nfl75.contract import (
    COVERAGE_MIN,
    EXPERIMENT,
    FALSE_MUTES_PER_HOUR_MAX,
    LONGEST_FALSE_MUTE_S_MAX,
    MERGE_GAP_S,
    MERGE_RULE,
    PROGRAM_HIDDEN_PER_HOUR_MAX,
    THRESHOLDS,
)

ScoreError = TimelineError
_EPS = 1e-6


def _merge(ranges: list[tuple[float, float]]) -> list[tuple[float, float]]:
    ordered = sorted((start, end) for start, end in ranges if end > start)
    if not ordered:
        return []
    out = [ordered[0]]
    for start, end in ordered[1:]:
        prev_s, prev_e = out[-1]
        if start <= prev_e + _EPS:
            out[-1] = (prev_s, max(prev_e, end))
        else:
            out.append((start, end))
    return out


def _clip(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def _intersect(base: list[tuple[float, float]], cut: list[tuple[float, float]]) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for a0, a1 in base:
        for b0, b1 in cut:
            left, right = max(a0, b0), min(a1, b1)
            if right > left:
                out.append((left, right))
    return _merge(out)


def _seconds(ranges: list[tuple[float, float]]) -> float:
    return sum(end - start for start, end in ranges)


def always_play(coverage: tuple[float, float]) -> list[Span]:
    start, end = coverage
    return [Span(start, end, "program")]


def playback_from_covers(coverage: tuple[float, float], covers: list[tuple[float, float]]) -> list[Span]:
    """Fill [coverage] with covered pieces. Uncovered time is program."""
    c0, c1 = coverage
    spans: list[Span] = []
    cursor = c0
    for start, end in _merge(covers):
        start = max(start, c0)
        end = min(end, c1)
        if end <= start + _EPS:
            continue
        if start > cursor + _EPS:
            spans.append(Span(cursor, start, "program"))
        spans.append(Span(start, end, "covered"))
        cursor = end
    if cursor < c1 - _EPS:
        spans.append(Span(cursor, c1, "program"))
    return spans


def playback_from_decisions(
    coverage: tuple[float, float],
    decisions: list[dict],
) -> list[Span]:
    """Hold each action until the next decision. Before the first, play.

    `clock` must be `capture`. `evidence_through` is the last audio sample the
    decision is allowed to have used, and it must be at or before `available_at`.
    """
    c0, c1 = coverage
    rows = sorted(decisions, key=lambda row: float(row["available_at"]))
    previous = None
    for index, row in enumerate(rows):
        if row.get("clock", "capture") != "capture":
            raise ScoreError(
                f"decision {index} uses clock {row.get('clock')!r}; the audio clock is capture"
            )
        available = float(row["available_at"])
        evidence = float(row["evidence_through"])
        if evidence > available + _EPS:
            raise ScoreError(f"decision {index} reads audio after available_at")
        if row.get("action") not in ("play", "cover"):
            raise ScoreError(f"decision {index} has unknown action {row.get('action')!r}")
        if available < c0 - _EPS or available > c1 + _EPS:
            raise ScoreError(f"decision {index} is outside coverage")
        if previous is not None and abs(available - previous) <= _EPS:
            raise ScoreError(f"decision {index} shares a timestamp with the previous decision")
        previous = available
    spans: list[Span] = []
    cursor = c0
    state = "program"
    for row in rows:
        available = float(row["available_at"])
        if available > cursor + _EPS:
            spans.append(Span(cursor, available, state))
        state = "covered" if row["action"] == "cover" else "program"
        cursor = available
    if c1 > cursor + _EPS:
        spans.append(Span(cursor, c1, state))
    return spans


def _with_exclusions(intervals: list[Interval], excluded_ranges: list[tuple[float, float]] | None) -> list[Interval]:
    extra = []
    for index, (start, end) in enumerate(excluded_ranges or []):
        if end <= start:
            raise ScoreError(f"excluded range {index} ends before it starts")
        extra.append(Interval(start, end, "other", "unsure", "unsure"))
    return list(intervals) + extra


def _covered_pieces(program: list[tuple[float, float]], playback: list[Span]) -> list[tuple[float, float]]:
    pieces = []
    for span in playback:
        if span.state != "covered":
            continue
        pieces.extend(_intersect([(span.start, span.end)], program))
    return _merge(pieces)


def merge_false_mute_episodes(
    pieces: list[tuple[float, float]],
    gap_s: float = MERGE_GAP_S,
) -> list[dict]:
    """Merge program-cover pieces separated by a short heard gap."""
    ordered = _merge(pieces)
    episodes: list[dict] = []
    current: dict | None = None
    for start, end in ordered:
        if current is None:
            current = {"start": start, "end": end, "parts": [(start, end)], "gaps": []}
            continue
        gap = start - current["end"]
        if gap <= gap_s + _EPS:
            current["gaps"].append(gap)
            current["parts"].append((start, end))
            current["end"] = end
        else:
            episodes.append(current)
            current = {"start": start, "end": end, "parts": [(start, end)], "gaps": []}
    if current is not None:
        episodes.append(current)
    rendered = []
    for episode in episodes:
        duration = _seconds(episode["parts"])
        rendered.append(
            {
                "start_s": episode["start"],
                "end_s": episode["end"],
                "duration_s": duration,
                "heard_gap_s": sum(gap for gap in episode["gaps"] if gap > 0),
                "parts": [{"start_s": a, "end_s": b} for a, b in episode["parts"]],
            }
        )
    return rendered


def _break_rows(
    commercials: list[tuple[float, float]],
    playback: list[Span],
    coverage_end: float,
) -> list[dict]:
    rows = []
    for index, (start, end) in enumerate(commercials, start=1):
        covered = 0.0
        first = None
        for span in playback:
            if span.state != "covered" or span.end <= start or span.start >= end:
                continue
            covered += _clip(start, end, span.start, span.end)
            if first is None:
                first = max(span.start, start)
        late = 0.0
        censored = False
        for span in playback:
            if span.state == "covered" and span.start < end - _EPS and span.end > end + _EPS:
                late = span.end - end
                censored = abs(span.end - coverage_end) <= 1e-3
                break
        rows.append(
            {
                "break": index,
                "start_s": start,
                "end_s": end,
                "length_s": end - start,
                "covered_s": covered,
                "missed_s": (end - start) - covered,
                "start_delay_s": None if first is None else first - start,
                "missed_break": first is None,
                "late_return_s": late,
                "late_return_censored_at_coverage_end": censored,
            }
        )
    return rows


def judge(metrics: dict, *, oracle: bool = False) -> dict:
    """All four caps are required. A missing denominator is not a pass.

    Oracle boundaries can describe a bottleneck. They cannot pass acceptance.
    """
    reasons: list[str] = []
    if oracle or metrics.get("oracle"):
        reasons.append("oracle boundaries are diagnostic and cannot pass product acceptance")
    if not metrics.get("evaluable"):
        reasons.append("timeline is not evaluable")
        reasons.extend(metrics.get("blockers") or [])
    coverage = metrics.get("commercial_coverage")
    rate = metrics.get("false_mutes_per_hour")
    longest = metrics.get("longest_false_mute_s")
    hidden = metrics.get("program_hidden_per_hour")
    if coverage is None:
        reasons.append("commercial coverage has no eligible seconds")
    elif coverage < COVERAGE_MIN:
        reasons.append(f"commercial coverage {coverage:.4f} is below {COVERAGE_MIN}")
    if rate is None:
        reasons.append("false-mute rate has no eligible program hour")
    elif rate >= FALSE_MUTES_PER_HOUR_MAX:
        reasons.append(f"false mutes per hour {rate:.4f} are not below {FALSE_MUTES_PER_HOUR_MAX}")
    if longest is None:
        reasons.append("longest false mute is unknown")
    elif longest >= LONGEST_FALSE_MUTE_S_MAX:
        reasons.append(f"longest false mute {longest:.3f}s is not below {LONGEST_FALSE_MUTE_S_MAX}")
    if hidden is None:
        reasons.append("hidden program per hour has no eligible program hour")
    elif hidden >= PROGRAM_HIDDEN_PER_HOUR_MAX:
        reasons.append(f"hidden program {hidden:.4f}s/hour is not below {PROGRAM_HIDDEN_PER_HOUR_MAX}")
    # De-duplicate while keeping order.
    unique = list(dict.fromkeys(reasons))
    return {"pass": not unique, "reasons": unique}


def _clip_ref(session: str | None, start: float, end: float, audio_present: bool) -> dict:
    ref = {
        "session": session,
        "start_s": start,
        "end_s": end,
        "audio": "present" if audio_present else "not_in_checkout",
    }
    if session is not None:
        ref["href"] = f"recordings/*/{session}#t={start:.3f},{end:.3f}"
    return ref


def score_product(
    coverage: tuple[float, float],
    intervals: list[Interval],
    playback: list[Span],
    capture_gaps: list[tuple[float, float]] | None = None,
    excluded_ranges: list[tuple[float, float]] | None = None,
    session: str | None = None,
    oracle: bool = False,
    audio_present: bool = False,
    wall_gap_s: float = 0.0,
) -> dict:
    """Score one continuous capture clock.

    Missing playback is excluded from both rates and blocks acceptance.
    Unsure gold and excluded ranges are reported and are neither successes
    nor hidden football. Capture gaps must sit outside coverage; a gap that
    was already removed from the elapsed clock is a wall gap, not a capture
    gap on this clock.
    """
    combined = _with_exclusions(intervals, excluded_ranges)
    legacy = score_timeline(coverage, combined, playback, capture_gaps)
    commercials = target_commercials(intervals)
    gold_unsure = excluded(intervals)
    unmarked = _merge(list(excluded_ranges or []))
    if _intersect(commercials, unmarked):
        raise ScoreError("an excluded range overlaps a commercial mute target")
    program = program_regions(coverage, combined)
    pieces = _covered_pieces(program, playback)
    episodes = merge_false_mute_episodes(pieces)
    for episode in episodes:
        episode["clip"] = _clip_ref(session, episode["start_s"], episode["end_s"], audio_present)
    breaks = _break_rows(commercials, playback, coverage[1])
    commercial_s = _seconds(commercials)
    covered_ads = sum(row["covered_s"] for row in breaks)
    # Missing commercial seconds are inside the legacy unscorable count.
    commercial_missing = float(legacy["commercial_missing_s"])
    program_missing = float(legacy["program_missing_s"])
    program_s = _seconds(program)
    program_covered = _seconds(pieces)
    observed_commercial = commercial_s - commercial_missing
    observed_program = program_s - program_missing
    blockers = []
    if commercial_missing > _EPS:
        blockers.append(f"commercial playback missing {commercial_missing:.3f}s")
    if program_missing > _EPS:
        blockers.append(f"program playback missing {program_missing:.3f}s")
    if observed_commercial <= _EPS:
        blockers.append("no observed commercial seconds")
    if observed_program <= _EPS:
        blockers.append("no observed program seconds")
    evaluable = not blockers
    coverage_fraction = None
    if observed_commercial > _EPS and commercial_missing <= _EPS:
        coverage_fraction = covered_ads / commercial_s
    program_hours = None if observed_program <= _EPS or program_missing > _EPS else observed_program / 3600.0
    episode_count = len(episodes)
    longest = max((episode["duration_s"] for episode in episodes), default=0.0)
    per_hour = None if program_hours is None else episode_count / program_hours
    hidden_per_hour = None if program_hours is None else program_covered / program_hours
    metrics = {
        "experiment": EXPERIMENT,
        "session": session,
        "oracle": oracle,
        "deployable": False,
        "evaluable": evaluable,
        "blockers": blockers,
        "merge_rule": MERGE_RULE,
        "merge_gap_s": MERGE_GAP_S,
        "thresholds": dict(THRESHOLDS),
        "coverage_s": float(legacy["coverage_s"]),
        "commercial_s": commercial_s,
        "commercial_covered_s": covered_ads,
        "commercial_missed_s": commercial_s - covered_ads - commercial_missing,
        "commercial_missing_s": commercial_missing,
        "commercial_coverage": coverage_fraction,
        "program_s": program_s,
        "program_covered_s": program_covered,
        "program_missing_s": program_missing,
        "program_hours": program_hours,
        "false_mute_episodes": episode_count,
        "false_mutes_per_hour": per_hour,
        "longest_false_mute_s": longest,
        "program_hidden_per_hour": hidden_per_hour,
        "unsure_s": _seconds(gold_unsure),
        "excluded_unmarked_s": _seconds(unmarked),
        "capture_gap_s": float(legacy["capture_gap_s"]),
        "wall_gap_s": wall_gap_s,
        "breaks": breaks,
        "episodes": episodes,
        "legacy_research_score_left_unchanged": True,
    }
    metrics["acceptance"] = judge(metrics, oracle=oracle)
    return metrics


def aggregate(rows: list[dict], *, oracle: bool = False) -> dict:
    """Sum seconds, then divide. Do not average per-game percentages."""
    commercial_s = sum(row["commercial_s"] for row in rows)
    covered = sum(row["commercial_covered_s"] for row in rows)
    missing_c = sum(row["commercial_missing_s"] for row in rows)
    program_s = sum(row["program_s"] for row in rows)
    program_covered = sum(row["program_covered_s"] for row in rows)
    missing_p = sum(row["program_missing_s"] for row in rows)
    episodes = sum(row["false_mute_episodes"] for row in rows)
    longest = max((row["longest_false_mute_s"] for row in rows), default=0.0)
    blockers = []
    if any(not row["evaluable"] for row in rows):
        blockers.append("a recording is not evaluable")
    if missing_c > _EPS:
        blockers.append("commercial playback missing")
    if missing_p > _EPS:
        blockers.append("program playback missing")
    if commercial_s - missing_c <= _EPS:
        blockers.append("no observed commercial seconds")
    if program_s - missing_p <= _EPS:
        blockers.append("no observed program seconds")
    evaluable = not blockers
    program_hours = None if not evaluable else (program_s - missing_p) / 3600.0
    metrics = {
        "experiment": EXPERIMENT,
        "session": "aggregate",
        "sessions": [row["session"] for row in rows],
        "oracle": oracle,
        "deployable": False,
        "evaluable": evaluable,
        "blockers": blockers,
        "merge_rule": MERGE_RULE,
        "merge_gap_s": MERGE_GAP_S,
        "thresholds": dict(THRESHOLDS),
        "commercial_s": commercial_s,
        "commercial_covered_s": covered,
        "commercial_missed_s": commercial_s - covered - missing_c,
        "commercial_missing_s": missing_c,
        "commercial_coverage": None if not evaluable else covered / commercial_s,
        "program_s": program_s,
        "program_covered_s": program_covered,
        "program_missing_s": missing_p,
        "program_hours": program_hours,
        "false_mute_episodes": episodes,
        "false_mutes_per_hour": None if program_hours is None else episodes / program_hours,
        "longest_false_mute_s": longest,
        "program_hidden_per_hour": None if program_hours is None else program_covered / program_hours,
        "unsure_s": sum(row["unsure_s"] for row in rows),
        "excluded_unmarked_s": sum(row["excluded_unmarked_s"] for row in rows),
        "capture_gap_s": sum(row["capture_gap_s"] for row in rows),
        "wall_gap_s": sum(row["wall_gap_s"] for row in rows),
        "legacy_research_score_left_unchanged": True,
    }
    metrics["acceptance"] = judge(metrics, oracle=oracle)
    return metrics
