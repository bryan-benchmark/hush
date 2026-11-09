"""One rolling mean on the frozen NBC score.

The window and the start line are chosen from the two NBC fit games, then
frozen. Prime audio is not an input to that choice. Those two games are also
the games the logistic head was fit on, so the line is in-sample.

A cover starts when the arithmetic mean of one complete past window sits at
or above the frozen line. It returns when the raw score stays at or below
zero for three seconds. That return is the previous rule. It is scored beside
an oracle that restores a covered commercial at the annotated end. A cover
that never touches a commercial is left in place, so a false start remains.

Nothing here trains a model or moves a speaker.
"""

from __future__ import annotations

import math

import numpy as np

from experiments.nfl75.accumulate import _advance, _complete
from experiments.nfl75.contract import (
    COVERAGE_MIN,
    FALSE_MUTES_PER_HOUR_MAX,
    LONGEST_FALSE_MUTE_S_MAX,
    PROGRAM_HIDDEN_PER_HOUR_MAX,
)
from experiments.nfl75.diagnose import perfect_endings
from experiments.nfl75.persist import FIT, HOLE_S, RETURN_PERSIST_S, _EPS
from experiments.nfl75.score import playback_from_covers

# The two windows already measured. No other length is added after Prime.
WINDOWS = (10, 20)
# Logistic boundary. Sits under both of the old frozen lines and is not refit.
LOGISTIC_RETURN = 0.0
# Half of the window has to fall inside the break before a crossing counts
# as evidence for that break. Football before the break can lift the mean.
PRE_SECONDS = 30.0
POST_SECONDS = 30.0
EDGE_S = 15.0
ORDINARY_GAP_S = 60.0
PRIME_SESSIONS = ("hush_20261008_205100", "hush_20260924_220624")


def assert_nbc_only(sessions: tuple[str, ...]) -> None:
    """The start line reads the NBC fit games and no Prime tape."""
    if tuple(sessions) != tuple(FIT):
        raise RuntimeError("the rolling-mean line is chosen on the two NBC fit games only")
    if set(PRIME_SESSIONS) & set(sessions):
        raise RuntimeError("Prime audio cannot choose the start line")


def rolling_means(times: list[float], scores: list[float], window: int) -> list[float | None]:
    """Causal arithmetic mean. A short prefix or a hole leaves a gap, not a zero."""
    if len(times) != len(scores):
        raise ValueError("each second needs one score")
    if window < 1:
        raise ValueError("window must be a positive length")
    means: list[float | None] = []
    for index in range(len(times)):
        span = _complete(times, index, window)
        if span is None:
            means.append(None)
            continue
        start, end = span
        if end != index:
            raise RuntimeError("the window has to end on the decision second")
        total = 0.0
        decision = float(times[index])
        for item in range(start, end + 1):
            if float(times[item]) > decision + _EPS:
                raise RuntimeError("rolling mean reads a future score")
            total += float(scores[item])
        means.append(total / window)
    return means


def covers_from_mean(
    times: list[float],
    scores: list[float],
    *,
    window: int,
    start_line: float,
    return_line: float = LOGISTIC_RETURN,
    return_persist_s: float = RETURN_PERSIST_S,
) -> list[tuple[float, float]]:
    """Start on the rolling mean. Return on the raw score staying at or below zero."""
    if len(times) != len(scores):
        raise ValueError("each second needs one score")
    means = rolling_means(times, scores, window)
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
        mean = means[index]
        hot = mean is not None and mean >= start_line
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


def oracle_end_covers(
    coverage: tuple[float, float],
    covers: list[tuple[float, float]],
    commercials: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    """Gold endings for covers that touch a commercial. False starts stay."""
    playback = playback_from_covers(coverage, covers)
    return perfect_endings(playback, commercials)


def _opened_in_commercial(moment: float, commercials: list[tuple[float, float]]) -> bool:
    return any(start - _EPS <= moment < end - _EPS for start, end in commercials)


def false_start_covers(
    covers: list[tuple[float, float]],
    commercials: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    """Covers whose open second is programming, including a prefix that runs into an ad."""
    return [row for row in covers if not _opened_in_commercial(row[0], commercials)]


def signal_by_break(
    times: list[float],
    means: list[float | None],
    commercials: list[tuple[float, float]],
    *,
    window: int,
    start_line: float,
) -> list[dict]:
    """First in-break crossing. A window that is still mostly football does not count."""
    needed = math.ceil(window / 2)
    found = []
    for index, (start, end) in enumerate(commercials, start=1):
        delay = None
        inside = 0
        for cursor, moment in enumerate(times):
            moment = float(moment)
            if moment < start - _EPS:
                continue
            mean = means[cursor]
            if mean is None or mean < start_line:
                continue
            span = _complete(times, cursor, window)
            count = 0
            if span is not None:
                left, right = span
                count = sum(
                    1
                    for item in range(left, right + 1)
                    if start - _EPS <= float(times[item]) < end - _EPS
                )
            if count < needed:
                continue
            delay = moment - start
            inside = count
            break
        found.append(
            {
                "break": index,
                "start_s": start,
                "end_s": end,
                "length_s": end - start,
                "delay_s": delay,
                "samples_inside_break": inside,
                "during_break": delay is not None and delay <= (end - start) + _EPS,
            }
        )
    return found


def _percentiles(values: list[float]) -> dict[str, float]:
    if not values:
        raise ValueError("a percentile needs at least one score")
    column = np.asarray(values, dtype=np.float64)
    return {
        "n": float(column.size),
        "p10": float(np.percentile(column, 10)),
        "p50": float(np.percentile(column, 50)),
        "p90": float(np.percentile(column, 90)),
    }


def choose_start(pooled: dict[int, dict[str, list[float]]]) -> dict:
    """One window and one line. Both come from NBC commercial and program means.

    The window is whichever of 10 and 20 seconds has the larger gap between
    the commercial 10th percentile and the program 90th percentile. Program
    seconds include the boundary seconds. Commercial seconds include the
    edges of each break.

    When that gap is open, the line is the midpoint. When the central masses
    overlap, the line is the program 90th percentile. The branch is recorded
    and is not revisited on Prime.
    """
    if set(pooled) != set(WINDOWS):
        raise ValueError("the choice is only between the 10 and 20 second windows")
    receipt = []
    best: dict | None = None
    for window in WINDOWS:
        commercial = pooled[window]["commercial"]
        program = pooled[window]["program"]
        stats_c = _percentiles(commercial)
        stats_p = _percentiles(program)
        gap = stats_c["p10"] - stats_p["p90"]
        row = {
            "window_s": window,
            "gap": gap,
            "commercial": stats_c,
            "program": stats_p,
        }
        receipt.append(row)
        if best is None or gap > best["gap"] + 1e-9 or (
            abs(gap - best["gap"]) <= 1e-9 and window < best["window_s"]
        ):
            best = row
    if best is None:
        raise RuntimeError("no window was scored")
    commercial_p10 = best["commercial"]["p10"]
    program_p90 = best["program"]["p90"]
    if commercial_p10 > program_p90:
        line = (commercial_p10 + program_p90) / 2.0
        placement = "midpoint_of_commercial_p10_and_program_p90"
    else:
        line = program_p90
        placement = "program_p90_because_the_central_masses_overlap"
    return {
        "window_s": int(best["window_s"]),
        "start_line": float(line),
        "placement": placement,
        "gap": float(best["gap"]),
        "commercial_p10": float(commercial_p10),
        "program_p90": float(program_p90),
        "candidates": receipt,
    }


def assign_context(moment: float, commercials: list[tuple[float, float]]) -> set[str]:
    """Decision-second context. A second may be both a return and an approach."""
    for start, end in commercials:
        if start - _EPS <= moment < end - _EPS:
            if moment >= start + EDGE_S and moment < end - EDGE_S:
                return {"commercial_interior"}
            return {"commercial_edge"}
    names: set[str] = set()
    after = [moment - end for _start, end in commercials if end <= moment + _EPS]
    before = [start - moment for start, _end in commercials if start >= moment - _EPS]
    if any(0.0 <= gap < POST_SECONDS for gap in after):
        names.add("post_return_30")
    if any(0.0 < gap <= PRE_SECONDS for gap in before):
        names.add("pre_commercial_30")
    far_after = min(after) if after else math.inf
    far_before = min(before) if before else math.inf
    if far_after > ORDINARY_GAP_S and far_before > ORDINARY_GAP_S:
        names.add("ordinary_football")
    if not names:
        names.add("other_program")
    return names


def quantiles(values: list[float]) -> dict | None:
    if not values:
        return None
    column = np.asarray(values, dtype=np.float64)
    rendered = {
        "n": int(column.size),
        "min": round(float(column.min()), 3),
        "max": round(float(column.max()), 3),
    }
    for percentile in (10, 25, 50, 75, 90, 99):
        rendered[f"p{percentile}"] = round(float(np.percentile(column, percentile)), 3)
    return rendered


def overlap_coefficient(left: list[float], right: list[float]) -> float | None:
    """Histogram intersection. 1 is the same distribution. 0 is no shared mass."""
    if len(left) < 2 or len(right) < 2:
        return None
    first = np.asarray(left, dtype=np.float64)
    second = np.asarray(right, dtype=np.float64)
    low = float(min(first.min(), second.min()))
    high = float(max(first.max(), second.max()))
    if high - low < 1e-9:
        return 1.0
    bins = np.linspace(low, high, 61)
    left_density, _edges = np.histogram(first, bins=bins, density=True)
    right_density, _edges = np.histogram(second, bins=bins, density=True)
    width = float(bins[1] - bins[0])
    return float(np.minimum(left_density, right_density).sum() * width)


def product_caps(row: dict) -> bool:
    rate = row.get("false_mutes_per_hour")
    longest = row.get("longest_false_mute_s")
    hidden = row.get("program_hidden_per_hour")
    if rate is None or longest is None or hidden is None:
        return False
    return (
        float(rate) < FALSE_MUTES_PER_HOUR_MAX
        and float(longest) < LONGEST_FALSE_MUTE_S_MAX
        and float(hidden) < PROGRAM_HIDDEN_PER_HOUR_MAX
    )


def _coverage_ok(row: dict) -> bool:
    value = row.get("commercial_coverage")
    return value is not None and float(value) + 1e-12 >= COVERAGE_MIN


def decide(oracle_rows: list[dict], actual_rows: list[dict]) -> dict:
    """KEEP only when both Prime games clear the gates under both returns.

    The gates are the NFL75 caps. Clearing them here is a development
    inspection. It is not a deployable pass and it does not authorize a mute.
    """
    if len(oracle_rows) != len(actual_rows) or not oracle_rows:
        raise ValueError("each game needs an oracle row and an actual row")
    oracle_coverage = all(_coverage_ok(row) for row in oracle_rows)
    oracle_caps = all(product_caps(row) for row in oracle_rows)
    actual_coverage = all(_coverage_ok(row) for row in actual_rows)
    actual_caps = all(product_caps(row) for row in actual_rows)
    if oracle_coverage and oracle_caps and actual_coverage and actual_caps:
        verdict = "KEEP"
        start = "KEEP"
        paired = "KEEP"
        nxt = (
            "Freeze this candidate. The next recording has to be an untouched "
            "evaluation set. Do not retune on these two Prime games."
        )
    elif oracle_coverage and oracle_caps:
        verdict = "REJECT"
        start = "KEEP"
        paired = "REJECT"
        nxt = (
            "Keep this start line frozen. The next measurement is return-to-program "
            "evidence, not another commercial-start model."
        )
    elif oracle_coverage:
        verdict = "REJECT"
        start = "REJECT"
        paired = "REJECT"
        nxt = (
            "The mean can see advertising and still starts during programming. "
            "The next change is a better classifier or an independent protective "
            "signal. Do not add another timer on this line."
        )
    else:
        verdict = "REJECT"
        start = "REJECT"
        paired = "REJECT"
        nxt = (
            "This rolling mean does not identify enough advertising even with "
            "ideal returns. Stop tuning timers. The next change is a better "
            "audio representation or a new classifier."
        )
    return {
        "verdict": verdict,
        "start_detector": start,
        "actual_return": paired,
        "oracle_coverage_clears_75_on_every_game": oracle_coverage,
        "oracle_false_mute_caps": oracle_caps,
        "actual_coverage_clears_75_on_every_game": actual_coverage,
        "actual_false_mute_caps": actual_caps,
        "next_change": nxt,
        "deployable": False,
    }
