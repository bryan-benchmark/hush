"""Causal pause after a frozen 0.25 match. The mean stays at 0.163.

Entry protection can refuse to open a cover. Release protection can close a
cover that is already open. One candidate does one of those. The published
one-second veto and the blind five-second hold do both, and they are
baselines.

`while_mean_cold` moves an entry timer only when the 10-second mean is below
the frozen line at the match. A hot mean does not extend it. That reuses the
frozen line. It is not a new threshold.

A decision sees speaker windows that have already ended, and scores at or
before that decision. Gold is not an input. A gap of zero protects only a
decision timestamp that lands on the match. It does not look ahead to the
next second.
"""

from __future__ import annotations

import bisect
import math
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from experiments.nfl75.accumulate import _advance
from experiments.nfl75.mean import LOGISTIC_RETURN, rolling_means
from experiments.nfl75.persist import HOLE_S, RETURN_PERSIST_S, _EPS
from hush.speaker_memory import MATCH_COSINE

GAPS = (0.0, 1.0, 2.0, 3.0, 5.0)
# Measurement bucket for "the mute was late at the boundary." The mean
# window is already 10 seconds. This is not a protection length.
ONSET_S = 10.0
# Ticket gate. Half a percentage point of causal coverage, each tape.
COVERAGE_SLACK = 0.005


def _ordered(ends: list[float]) -> None:
    for index in range(1, len(ends)):
        if ends[index] + _EPS < ends[index - 1]:
            raise ValueError("speaker windows are not in time order")


def _mean_as_of(times: list[float], means: list[float | None], moment: float) -> float | None:
    """Latest rolling mean whose decision time is at or before `moment`."""
    index = bisect.bisect_right(times, moment + _EPS) - 1
    if index < 0:
        return None
    if float(times[index]) > moment + _EPS:
        raise RuntimeError("a rolling mean was read from after the match")
    return means[index]


def pause_covers(
    times: list[float],
    scores: list[float],
    ends: list[float],
    cosines: list[float],
    *,
    window: int,
    start_line: float,
    gap_s: float,
    effect: str,
    refresh: str = "always",
    line: float = MATCH_COSINE,
    return_line: float = LOGISTIC_RETURN,
    return_persist_s: float = RETURN_PERSIST_S,
    trace: list | None = None,
) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    """Cover intervals, and the intervals kept in play by a speaker match.

    `effect="entry"` refuses to open while the gap is live and leaves an
    open cover to the frozen three-second return. `effect="release"` closes
    an open cover when the gap is live, and does not reopen until that same
    gap has ended. Reopening on the next sample would undo the release.
    `effect="mixed"` is the published hold: it blocks the open and it closes
    the cover. `refresh="while_mean_cold"` is entry-only.
    """
    if effect not in ("entry", "release", "mixed"):
        raise ValueError("effect must be entry, release, or mixed")
    if refresh not in ("always", "while_mean_cold"):
        raise ValueError("refresh must be always or while_mean_cold")
    if refresh == "while_mean_cold" and effect != "entry":
        raise ValueError("a cold mean can limit an entry pause, not a release")
    if gap_s < 0:
        raise ValueError("gap must be zero or positive")
    if len(times) != len(scores):
        raise ValueError("each second needs one score")
    if len(ends) != len(cosines):
        raise ValueError("each speaker window needs one cosine")
    _ordered(ends)
    means = rolling_means(times, scores, window)
    blocks_open = effect in ("entry", "mixed", "release")
    closes_cover = effect in ("release", "mixed")
    state = "play"
    cold = 0.0
    previous: float | None = None
    opened: float | None = None
    cursor = 0
    last_end: float | None = None
    last_cosine: float | None = None
    last_index: int | None = None
    grant_until: float | None = None
    covers: list[tuple[float, float]] = []
    points: list[tuple[float, bool]] = []
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
        while cursor < len(ends) and float(ends[cursor]) <= moment + _EPS:
            value = float(cosines[cursor])
            if math.isfinite(value) and value + _EPS >= line:
                last_end = float(ends[cursor])
                last_cosine = value
                last_index = cursor
                if refresh == "while_mean_cold":
                    seen = _mean_as_of(times, means, last_end)
                    if seen is None or seen < start_line:
                        grant_until = last_end + gap_s
            cursor += 1
        if refresh == "while_mean_cold":
            protected = grant_until is not None and moment <= grant_until + _EPS
        else:
            protected = last_end is not None and moment - last_end <= gap_s + _EPS
        mean = means[index]
        hot = mean is not None and mean >= start_line
        reason = "mean_below_line"
        if state == "cover" and closes_cover and protected:
            state = "play"
            covers.append((float(opened), moment))
            opened = None
            reason = "released_on_match"
        elif state == "cover" and cold + _EPS >= return_persist_s:
            state = "play"
            covers.append((float(opened), moment))
            opened = None
            reason = "returned_on_score"
        elif state == "play" and hot and not (protected and blocks_open):
            state = "cover"
            opened = moment
            cold = 0.0
            reason = "opened_on_mean"
        elif state == "play" and hot and protected:
            reason = "speaker_hold"
        elif state == "cover":
            reason = "held_cover"
        speaker_play = reason in ("speaker_hold", "released_on_match")
        points.append((moment, speaker_play))
        if trace is not None:
            age = None if last_end is None else moment - last_end
            trace.append(
                {
                    "t": moment,
                    "score": score,
                    "mean": None if mean is None else float(mean),
                    "hot": hot,
                    "protected": protected,
                    "state": state,
                    "reason": reason,
                    "match_end_s": last_end,
                    "match_cosine": last_cosine,
                    "match_age_s": age,
                    "match_index": last_index,
                }
            )
    if opened is not None and previous is not None:
        covers.append((opened, previous + 1.0))
    holds: list[tuple[float, float]] = []
    for index, (moment, speaker_play) in enumerate(points):
        if not speaker_play:
            continue
        end = points[index + 1][0] if index + 1 < len(points) else moment + 1.0
        if end > moment:
            holds.append((moment, end))
    return covers, _merge(holds)


def _merge(ranges: list[tuple[float, float]]) -> list[tuple[float, float]]:
    ordered = sorted((float(start), float(end)) for start, end in ranges if end > start)
    if not ordered:
        return []
    out = [ordered[0]]
    for start, end in ordered[1:]:
        prev_s, prev_e = out[-1]
        if start <= prev_e + 1e-6:
            out[-1] = (prev_s, max(prev_e, end))
        else:
            out.append((start, end))
    return out


def _intersect(left: list[tuple[float, float]], right: list[tuple[float, float]]) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for a0, a1 in left:
        for b0, b1 in right:
            start, end = max(a0, b0), min(a1, b1)
            if end > start:
                out.append((start, end))
    return _merge(out)


def _difference(base: list[tuple[float, float]], cut: list[tuple[float, float]]) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for a0, a1 in _merge(base):
        cursor = a0
        for b0, b1 in _merge(cut):
            if b1 <= cursor:
                continue
            if b0 >= a1:
                break
            if b0 > cursor:
                out.append((cursor, min(b0, a1)))
            cursor = max(cursor, b1)
            if cursor >= a1:
                break
        if cursor < a1:
            out.append((cursor, a1))
    return _merge(out)


def seconds(ranges: list[tuple[float, float]]) -> float:
    return sum(end - start for start, end in ranges)


def commercial_given_back(
    baseline: list[tuple[float, float]],
    candidate: list[tuple[float, float]],
    commercials: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    """Gold-ad seconds the baseline muted and this candidate left playing."""
    return _difference(_intersect(baseline, commercials), candidate)


def onset_ranges(commercials: list[tuple[float, float]], onset_s: float = ONSET_S) -> list[tuple[float, float]]:
    return [(start, min(end, start + onset_s)) for start, end in commercials if end > start]


def overlap_seconds(ranges: list[tuple[float, float]], spans: list[tuple[float, float]]) -> float:
    return seconds(_intersect(ranges, spans))
