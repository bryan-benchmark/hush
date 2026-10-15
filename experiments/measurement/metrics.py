"""Interval metrics for OHush.

Times are seconds on one clock. Unsure boundaries are excluded from both the
commercial target and the program target. A fully annotated range is required
before program-covered time means anything: outside that range this module
does not score.

Invalid timelines raise TimelineError. Nothing is sorted, clipped, or merged
to make a bad timeline look scoreable. A forward gap in playback is missing
evidence, not a clock reset. A clock that moves backwards, two states on the
same second, an unknown state, or a gold interval that leaves the coverage
range is an error.

A program mark names the show. It may contain commercials. It does not claim
those seconds are commercial-free, and it is not a commercial boundary. Two
mute targets that claim the same second are still an error. A capture gap is
not coverage time. One that is given coordinates inside the coverage range is
an error, because that mixes the elapsed clock with a hole that was removed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


class TimelineError(ValueError):
    """The timeline is not safe to score. No field was repaired."""


_PLAYBACK_STATES = frozenset({"program", "covered"})
_EPS = 1e-6


@dataclass(frozen=True)
class Interval:
    start: float
    end: float
    event_class: str
    desired_action: str
    confidence: str


@dataclass(frozen=True)
class Span:
    """Playback state on [start, end). state is 'program' or 'covered'."""

    start: float
    end: float
    state: str


def _clip(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def _merge(ranges: list[tuple[float, float]]) -> list[tuple[float, float]]:
    if not ranges:
        return []
    ordered = sorted(ranges)
    out = [ordered[0]]
    for start, end in ordered[1:]:
        prev_s, prev_e = out[-1]
        if start <= prev_e:
            out[-1] = (prev_s, max(prev_e, end))
        else:
            out.append((start, end))
    return out


def _subtract(base: list[tuple[float, float]], cut: list[tuple[float, float]]) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    cuts = _merge(cut)
    for start, end in _merge(base):
        cursor = start
        for c0, c1 in cuts:
            if c1 <= cursor or c0 >= end:
                continue
            if c0 > cursor:
                out.append((cursor, min(c0, end)))
            cursor = max(cursor, c1)
            if cursor >= end:
                break
        if cursor < end:
            out.append((cursor, end))
    return [(a, b) for a, b in out if b > a]


def target_commercials(intervals: list[Interval]) -> list[tuple[float, float]]:
    """LABEL_POLICY_V1 scoring target: commercial, mute, not unsure."""
    return _merge(
        [
            (row.start, row.end)
            for row in intervals
            if row.event_class == "commercial"
            and row.desired_action == "mute"
            and row.confidence != "unsure"
            and row.end > row.start
        ]
    )


def excluded(intervals: list[Interval]) -> list[tuple[float, float]]:
    return _merge(
        [
            (row.start, row.end)
            for row in intervals
            if row.confidence == "unsure" or row.desired_action == "unsure"
            if row.end > row.start
        ]
    )


def program_regions(coverage: tuple[float, float], intervals: list[Interval]) -> list[tuple[float, float]]:
    """Annotated time that is not a mute-target and not an unsure boundary."""
    cover = target_commercials(intervals)
    drop = _merge(cover + excluded(intervals))
    return _subtract([coverage], drop)


def _finite(value: float, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise TimelineError(f"{label} is not a finite time")
    return float(value)


def validate_timeline(
    coverage: tuple[float, float],
    intervals: list[Interval],
    playback: list[Span],
) -> tuple[float, float]:
    """Reject a timeline that cannot be scored without repairing it.

    Playback must already be in chronological order. Touching endpoints are
    allowed. A later span that starts before the previous span ends, or before
    the previous span starts, is rejected. Gold intervals must lie inside
    coverage. Program-identity marks may contain other marks. Mute targets
    may not overlap one another, and two program-identity marks may not
    overlap each other.
    """
    if len(coverage) != 2:
        raise TimelineError("coverage must be a start and an end")
    c0 = _finite(coverage[0], "coverage start")
    c1 = _finite(coverage[1], "coverage end")
    if c1 <= c0:
        raise TimelineError("coverage end must be after start")

    gold: list[tuple[float, float, int]] = []
    for index, row in enumerate(intervals):
        start = _finite(row.start, f"interval {index} start")
        end = _finite(row.end, f"interval {index} end")
        if end <= start:
            raise TimelineError(f"interval {index} end must be after start")
        if start < c0 - _EPS or end > c1 + _EPS:
            raise TimelineError(f"interval {index} crosses the coverage boundary")
        gold.append((start, end, index))
    claims = [item for item in gold if not is_program_context(intervals[item[2]])]
    contexts = [item for item in gold if is_program_context(intervals[item[2]])]
    _reject_overlaps(intervals, claims, "intervals")
    _reject_overlaps(intervals, contexts, "program marks")

    previous_start: float | None = None
    previous_end: float | None = None
    for index, span in enumerate(playback):
        start = _finite(span.start, f"playback {index} start")
        end = _finite(span.end, f"playback {index} end")
        if end <= start:
            raise TimelineError(f"playback {index} end must be after start")
        if span.state not in _PLAYBACK_STATES:
            raise TimelineError(f"playback {index} has unknown state {span.state!r}")
        if start < c0 - _EPS or end > c1 + _EPS:
            raise TimelineError(f"playback {index} crosses the coverage boundary")
        if previous_start is not None and start < previous_start - _EPS:
            raise TimelineError(f"playback {index} moves backwards")
        if previous_end is not None and start < previous_end - _EPS:
            raise TimelineError(f"playback {index} overlaps the previous span")
        previous_start = start
        previous_end = end
    return c0, c1


def is_program_context(row: Interval) -> bool:
    """A show name. Not a mute target, and not a claim that every second is program audio."""
    return row.event_class == "program" and row.desired_action == "play"


def row_class(intervals: list[Interval], index: int) -> str:
    row = intervals[index]
    return f"{row.event_class}/{row.desired_action}/{row.confidence}"


def _reject_overlaps(intervals: list[Interval], items: list[tuple[float, float, int]], kind: str) -> None:
    ordered = sorted(items, key=lambda item: (item[0], item[1], item[2]))
    for (start, end, index), (nxt, _nxt_end, nxt_index) in zip(ordered, ordered[1:]):
        if nxt < end - _EPS:
            raise TimelineError(
                f"{kind} {index} and {nxt_index} overlap "
                f"({row_class(intervals, index)} vs {row_class(intervals, nxt_index)})"
            )


def _overlap_state(regions: list[tuple[float, float]], playback: list[Span], state: str) -> float:
    total = 0.0
    for r0, r1 in regions:
        for span in playback:
            if span.state != state:
                continue
            total += _clip(r0, r1, span.start, span.end)
    return total


def _incidents(regions: list[tuple[float, float]], playback: list[Span], state: str) -> int:
    """Count entries into `state` that overlap a region. One long cover is one incident."""
    count = 0
    for span in playback:
        if span.state != state or span.end <= span.start:
            continue
        if any(_clip(r0, r1, span.start, span.end) > 0 for r0, r1 in regions):
            count += 1
    return count


def _latencies(intervals: list[Interval], playback: list[Span]) -> list[float | None]:
    """Seconds from each target start until the first covered sample, or None if never."""
    out: list[float | None] = []
    for row in intervals:
        if not (
            row.event_class == "commercial"
            and row.desired_action == "mute"
            and row.confidence != "unsure"
        ):
            continue
        hit = None
        for span in playback:
            if span.state != "covered" or span.end <= row.start or span.start >= row.end:
                continue
            began = max(span.start, row.start)
            hit = began - row.start
            break
        out.append(hit)
    return out


def _percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * p
    lo = int(rank)
    hi = min(lo + 1, len(ordered) - 1)
    frac = rank - lo
    return ordered[lo] * (1 - frac) + ordered[hi] * frac


def _missing(regions: list[tuple[float, float]], playback: list[Span]) -> float:
    """Region seconds with no playback span. Not called program, and not called covered."""
    observed = [(span.start, span.end) for span in playback if span.end > span.start]
    return sum(end - start for start, end in _subtract(regions, observed))


def _gap_seconds(capture_gaps: list[tuple[float, float]] | None, coverage: tuple[float, float]) -> float:
    if not capture_gaps:
        return 0.0
    checked: list[tuple[float, float, int]] = []
    for index, (start, end) in enumerate(capture_gaps):
        start_f = _finite(start, f"capture gap {index} start")
        end_f = _finite(end, f"capture gap {index} end")
        if end_f <= start_f:
            raise TimelineError(f"capture gap {index} end must be after start")
        if _clip(start_f, end_f, coverage[0], coverage[1]) > _EPS:
            raise TimelineError(f"capture gap {index} overlaps coverage")
        checked.append((start_f, end_f, index))
    ordered = sorted(checked)
    for (start, end, index), (nxt, _nxt_end, nxt_index) in zip(ordered, ordered[1:]):
        if nxt < end - _EPS:
            raise TimelineError(f"capture gaps {index} and {nxt_index} overlap")
    return sum(end - start for start, end, _index in checked)


def score_timeline(
    coverage: tuple[float, float],
    intervals: list[Interval],
    playback: list[Span],
    capture_gaps: list[tuple[float, float]] | None = None,
) -> dict:
    """Score one continuous clock inside a fully annotated coverage range.

    Playback states must be 'program' or 'covered', already in time order,
    and non-overlapping. Gaps in playback are missing evidence. They are not
    program. A program-identity mark is context: commercials inside it stay
    mute targets. A change from one show to another is not a commercial.
    """
    c0, c1 = validate_timeline(coverage, intervals, playback)
    capture_gap_s = _gap_seconds(capture_gaps, (c0, c1))
    commercials = target_commercials(intervals)
    program = program_regions((c0, c1), intervals)
    context = _merge(
        [(row.start, row.end) for row in intervals if is_program_context(row) and row.end > row.start]
    )
    commercial_s = sum(b - a for a, b in commercials)
    program_s = sum(b - a for a, b in program)
    heard = _overlap_state(commercials, playback, "program")
    covered_ads = _overlap_state(commercials, playback, "covered")
    program_covered = _overlap_state(program, playback, "covered")
    program_heard = _overlap_state(program, playback, "program")
    commercial_missing = _missing(commercials, playback)
    program_missing = _missing(program, playback)
    coverage_s = c1 - c0
    unsure_s = sum(b - a for a, b in excluded(intervals))
    eligible_s = commercial_s + program_s
    observed_s = heard + covered_ads + program_heard + program_covered
    conserved = unsure_s + observed_s + commercial_missing + program_missing
    if abs(conserved - coverage_s) > 1e-4:
        raise TimelineError(
            f"eligible seconds were not conserved ({conserved:.6f} vs {coverage_s:.6f})"
        )
    latencies = _latencies(intervals, playback)
    caught = [value for value in latencies if value is not None]
    missed = sum(1 for value in latencies if value is None)
    # A commercial that starts already on program is heard time, not a false return.
    # A false return is a program span inside a target that follows a covered span.
    false_returns = _false_returns(commercials, playback)
    false_covers = _incidents(program, playback, "covered")
    return {
        "coverage_s": round(coverage_s, 3),
        "target_commercial_s": round(commercial_s, 3),
        "program_s": round(program_s, 3),
        "unsure_s": round(unsure_s, 3),
        "commercial_heard_s": round(heard, 3),
        "commercial_covered_s": round(covered_ads, 3),
        "commercial_covered_fraction": None
        if commercial_s <= 0
        else round(covered_ads / commercial_s, 4),
        "program_heard_s": round(program_heard, 3),
        "program_covered_s": round(program_covered, 3),
        "program_covered_per_hour": None
        if program_s <= 0
        else round(program_covered / (program_s / 3600.0), 4),
        "program_missing_s": round(program_missing, 3),
        "commercial_missing_s": round(commercial_missing, 3),
        "eligible_s": round(eligible_s, 3),
        "observed_s": round(observed_s, 3),
        "observed_fraction": None if eligible_s <= 0 else round(observed_s / eligible_s, 4),
        "false_cover_incidents": false_covers,
        "false_returns_inside_commercials": false_returns,
        "starts": len(latencies),
        "starts_missed": missed,
        "start_delay_median_s": None if not caught else round(_percentile(caught, 0.5), 3),
        "start_delay_p95_s": None if not caught else round(_percentile(caught, 0.95), 3),
        "unscorable_s": round(commercial_missing + program_missing, 3),
        "program_context_s": round(sum(end - start for start, end in context), 3),
        "program_context_overlap_commercial_s": round(
            sum(_clip(a0, a1, b0, b1) for a0, a1 in context for b0, b1 in commercials),
            3,
        ),
        "program_context_marks": sum(1 for row in intervals if is_program_context(row)),
        "capture_gap_s": round(capture_gap_s, 3),
    }


def _false_returns(commercials: list[tuple[float, float]], playback: list[Span]) -> int:
    count = 0
    for r0, r1 in commercials:
        saw_cover = False
        for span in playback:
            if span.end <= r0 or span.start >= r1:
                continue
            if span.state == "covered":
                saw_cover = True
            elif span.state == "program" and saw_cover and _clip(r0, r1, span.start, span.end) > 0:
                count += 1
                saw_cover = False
    return count
