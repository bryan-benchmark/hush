"""Rolling evidence on the frozen NBC score. Thresholds were not chosen on October.

A consecutive hold needs every second. A rolling hold needs 60 percent of the
seconds in the last 10 or 20, the share named before this run. The return is
three seconds at or below zero, the logistic boundary, which sits under both
start lines. The 8.285 line is the NBC clear-program ceiling and is diagnostic
only. Nothing here trains a model or moves a speaker.
"""

from __future__ import annotations

from experiments.nfl75.persist import HOLE_S, RETURN_PERSIST_S, _EPS

# Twelve of the last twenty seconds. Fixed before either Prime game is read.
ACCUMULATED_FRACTION = 0.60
ROLL_WINDOWS = (10, 20)
SUPPORT_WITHIN = (10.0, 20.0, 30.0)
# Product keep requires this much more coverage than the consecutive hold
# at the same line, on every development tape, inside the false-mute caps.
KEEP_COVERAGE_MARGIN = 0.25
LOGISTIC_RETURN = 0.0


def _advance(previous: float | None, moment: float) -> float:
    if previous is None:
        return 1.0
    if moment < previous - _EPS:
        raise ValueError("score time moved backwards")
    gap = moment - previous
    if gap > HOLE_S:
        return 1.0
    return gap


def _complete(times: list[float], end: int, window: int) -> tuple[int, int] | None:
    """Index range [start, end] of `window` one-second samples, or None."""
    start = end - window + 1
    if start < 0:
        return None
    if float(times[end]) - float(times[start]) > (window - 1) + 0.25:
        return None
    if float(times[end]) - float(times[start]) < (window - 1) - 0.25:
        return None
    for index in range(start + 1, end + 1):
        if float(times[index]) - float(times[index - 1]) > HOLE_S:
            return None
    return start, end


def _longest(scores: list[float], line: float) -> int:
    best = 0
    run = 0
    for score in scores:
        if score >= line:
            run += 1
            best = max(best, run)
        else:
            run = 0
    return best


def window_row(times: list[float], scores: list[float], index: int, window: int, line: float) -> dict | None:
    span = _complete(times, index, window)
    if span is None:
        return None
    start, end = span
    chunk = [float(scores[item]) for item in range(start, end + 1)]
    above = sum(1 for score in chunk if score >= line)
    return {
        "above": above,
        "fraction": above / window,
        "mean": sum(chunk) / window,
        "maximum": max(chunk),
        "longest_run": _longest(chunk, line),
        "ready": True,
    }


def rolling(times: list[float], scores: list[float], window: int, line: float) -> list[dict | None]:
    return [window_row(times, scores, index, window, line) for index in range(len(times))]


def covers_accumulated(
    times: list[float],
    scores: list[float],
    *,
    window: int,
    line: float,
    fraction: float = ACCUMULATED_FRACTION,
    return_line: float = LOGISTIC_RETURN,
    return_persist_s: float = RETURN_PERSIST_S,
) -> list[tuple[float, float]]:
    """Cover when a full past window is at least `fraction` positive."""
    if len(times) != len(scores):
        raise ValueError("each second needs one score")
    if return_line >= line:
        raise ValueError("the return line must sit below the start line")
    state = "play"
    cold = 0.0
    previous: float | None = None
    opened: float | None = None
    covers: list[tuple[float, float]] = []
    for index, (moment, score) in enumerate(zip(times, scores)):
        moment = float(moment)
        score = float(score)
        gap = None if previous is None else moment - previous
        if gap is not None and gap > HOLE_S:
            cold = 0.0
        dt = _advance(previous, moment)
        previous = moment
        if score <= return_line:
            cold += dt
        else:
            cold = 0.0
        row = window_row(times, scores, index, window, line)
        hot = row is not None and row["fraction"] + _EPS >= fraction
        if state == "play" and hot:
            state = "cover"
            opened = moment
            cold = 0.0
        elif state == "cover" and cold + _EPS >= return_persist_s:
            state = "play"
            covers.append((float(opened), moment))
            opened = None
    if opened is not None and previous is not None:
        covers.append((opened, previous + 1.0))
    return covers


def support_by_break(
    times: list[float],
    scores: list[float],
    commercials: list[tuple[float, float]],
    *,
    window: int,
    line: float,
    fraction: float = ACCUMULATED_FRACTION,
) -> list[dict]:
    """First causal window that reaches the fraction at or after the break starts.

    A hit counts as support only when at least half of the required positive
    seconds are inside the break. Football before the break can fill a window,
    and that does not count as detecting the advertisement.
    """
    needed = max(1, int(round(fraction * window)) // 2)
    found = []
    for index, (start, end) in enumerate(commercials, start=1):
        hit = None
        inside = 0
        for cursor, moment in enumerate(times):
            moment = float(moment)
            if moment < start - _EPS:
                continue
            row = window_row(times, scores, cursor, window, line)
            if row is None or row["fraction"] + _EPS < fraction:
                continue
            span = _complete(times, cursor, window)
            inside = 0
            if span is not None:
                left, right = span
                inside = sum(
                    1
                    for item in range(left, right + 1)
                    if float(scores[item]) >= line and float(times[item]) >= start - _EPS
                )
            hit = moment - start
            break
        found.append(
            {
                "break": index,
                "start_s": start,
                "end_s": end,
                "length_s": end - start,
                "delay_s": None if hit is None else hit,
                "positives_inside_break": inside,
                "within": {
                    str(int(limit)): hit is not None and hit <= limit + _EPS and inside >= needed
                    for limit in SUPPORT_WITHIN
                },
            }
        )
    return found


def context_name(moment: float, commercials: list[tuple[float, float]]) -> str:
    """Where a second sits. Gold has no music, promo, or halftime marks."""
    for start, end in commercials:
        if start - _EPS <= moment < end - _EPS:
            if moment < start + 15 or moment >= end - 15:
                return "commercial_edge"
            return "commercial_interior"
    after = [moment - end for _start, end in commercials if end <= moment + _EPS]
    before = [start - moment for start, _end in commercials if start >= moment - _EPS]
    if any(0 <= gap <= 15 for gap in after):
        return "return_transition"
    if after and min(after) > 60 and (not before or min(before) > 60):
        return "ordinary_program"
    return "other_program"
