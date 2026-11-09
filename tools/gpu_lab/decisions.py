"""Causal decisions for one frozen audio window.

A decision stamped at time t may use audio from [t - window, t) only.
The mute it orders covers [t, t + hop). It cannot cover audio that already
played, and it cannot see audio that has not arrived.
"""

from __future__ import annotations

import math

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

from experiments.measurement.metrics import Span

from tools.gpu_lab.ladder import pairs, score_mask

HOP_S = 1.0
THRESHOLDS = tuple(round(i / 100, 2) for i in range(1, 100))


def window_bounds(t: float, window_s: float) -> tuple[float, float]:
    if window_s <= 0:
        raise ValueError("window must be positive")
    return t - window_s, t


def decision_times(start: float, end: float, window_s: float, hop_s: float = HOP_S) -> list[float]:
    """Times when a full past window exists and the following hop still fits."""
    if hop_s <= 0:
        raise ValueError("hop must be positive")
    times = []
    t = start + window_s
    while t + hop_s <= end + 1e-9:
        times.append(round(t, 6))
        t += hop_s
    return times


def _inside(start: float, end: float, spans: list[tuple[float, float]]) -> bool:
    return any(a <= start + 1e-9 and end <= b + 1e-9 for a, b in spans)


def label_action(mask: dict, t: float, hop_s: float = HOP_S) -> int:
    """Class of the second the decision will cover. Mixed seconds are excluded."""
    start, end = t, t + hop_s
    if _inside(start, end, pairs(mask, "verified_commercial")):
        return 1
    if _inside(start, end, pairs(mask, "verified_program")):
        return 0
    return -1


def playback_from_scores(
    coverage: tuple[float, float],
    times: list[float],
    scores: list[float],
    threshold: float,
    hop_s: float = HOP_S,
) -> list[Span]:
    if len(times) != len(scores):
        raise ValueError("each decision needs one score")
    c0, c1 = coverage
    raw: list[tuple[float, float, str]] = []
    cursor = c0
    for t, score in zip(times, scores):
        if t < c0 - 1e-9:
            raise ValueError(f"decision at {t} is before coverage")
        action_end = min(t + hop_s, c1)
        if t > cursor + 1e-6:
            raw.append((cursor, t, "program"))
        state = "covered" if score >= threshold else "program"
        if action_end > t:
            raw.append((t, action_end, state))
        cursor = action_end
    if cursor < c1 - 1e-6:
        raw.append((cursor, c1, "program"))
    merged: list[tuple[float, float, str]] = []
    for start, end, state in raw:
        if end <= start:
            continue
        if merged and merged[-1][2] == state and abs(merged[-1][1] - start) <= 1e-6:
            merged[-1] = (merged[-1][0], end, state)
        else:
            merged.append((start, end, state))
    return [Span(start=start, end=end, state=state) for start, end, state in merged]


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def pod_losses(commercials: list[tuple[float, float]], playback: list[Span]) -> list[dict]:
    """Split each commercial into missed, late start, and early unmute seconds."""
    rows = []
    for start, end in commercials:
        onset = 0.0
        early = 0.0
        covered = 0.0
        saw_cover = False
        for span in playback:
            seconds = _overlap(start, end, span.start, span.end)
            if seconds <= 0:
                continue
            if span.state == "covered":
                saw_cover = True
                covered += seconds
            elif saw_cover:
                early += seconds
            else:
                onset += seconds
        if covered <= 1e-9:
            cause = "missed"
            missed = end - start
            onset = 0.0
            early = 0.0
        elif early > onset:
            cause = "early_unmute"
            missed = 0.0
        else:
            cause = "late_start"
            missed = 0.0
        rows.append(
            {
                "start_seconds": round(start, 3),
                "end_seconds": round(end, 3),
                "cause": cause,
                "missed_s": round(missed, 3),
                "late_start_s": round(onset, 3),
                "early_unmute_s": round(early, 3),
                "held_s": round(covered, 3),
            }
        )
    return rows


def program_incidents(program: list[tuple[float, float]], playback: list[Span]) -> list[dict]:
    incidents = []
    for span in playback:
        if span.state != "covered":
            continue
        cut = sum(_overlap(span.start, span.end, a, b) for a, b in program)
        if cut <= 1e-9:
            continue
        incidents.append(
            {
                "start_seconds": round(span.start, 3),
                "end_seconds": round(span.end, 3),
                "program_s": round(cut, 3),
            }
        )
    return incidents


def sustained_scores(times: list[float], scores: list[float], sustain_s: int) -> list[float]:
    """Minimum of the last ``sustain_s`` decision scores.

    A one-second spike cannot fire a longer sustain. Seconds before that run
    exists stay at 0, so the mute cannot start early. The samples are the
    decisions already stamped at or before t.
    """
    if sustain_s < 1:
        raise ValueError("sustain must be at least 1 second")
    if len(times) != len(scores):
        raise ValueError("each decision needs one score")
    if sustain_s == 1:
        return list(scores)
    held: list[float] = []
    for index, score in enumerate(scores):
        window = [score]
        ready = True
        for back in range(1, sustain_s):
            previous = index - back
            if previous < 0 or abs(times[previous + 1] - times[previous] - HOP_S) > 1e-3:
                ready = False
                break
            window.append(scores[previous])
        held.append(min(window) if ready else 0.0)
    return held


def relative_excess(times: list[float], scores: list[float], memory_s: int, quantile: float) -> list[float]:
    """How far this second sits above the recent scores of the same broadcast.

    The reference is a quantile of decision scores in [t - memory, t). The
    current second is not in that reference. Until a full memory exists, the
    excess stays too low to mute.
    """
    if memory_s < 1:
        raise ValueError("memory must cover at least one past second")
    if not 0.0 < quantile < 1.0:
        raise ValueError("quantile must be between 0 and 1")
    if len(times) != len(scores):
        raise ValueError("each decision needs one score")
    clock = np.asarray(times, dtype=np.float64)
    values = np.asarray(scores, dtype=np.float64)
    excess = np.full(len(values), -1.0e9, dtype=np.float64)
    if len(values) <= memory_s:
        return excess.tolist()
    contiguous = bool(np.max(np.abs(np.diff(clock) - HOP_S)) <= 1e-3)
    if contiguous:
        view = sliding_window_view(values, memory_s)
        refs = np.quantile(view[: len(values) - memory_s], quantile, axis=1)
        excess[memory_s:] = values[memory_s:] - refs
        return excess.tolist()
    for index, moment in enumerate(clock):
        start = int(np.searchsorted(clock, moment - memory_s, side="left"))
        past = values[start:index]
        if len(past) < memory_s:
            continue
        excess[index] = float(values[index] - np.quantile(past[-memory_s:], quantile))
    return excess.tolist()


def _separating_threshold(times: list[float], scores: list[float], program: list[tuple[float, float]]) -> float | None:
    """Cutoff just above every score that would touch verified program audio.

    The 0.01 grid ends at 0.99. These probabilities pile up above that, so the
    grid can miss the first threshold that leaves the game on.
    """
    ceiling = None
    for t, score in zip(times, scores):
        if any(_overlap(t, t + HOP_S, start, end) > 1e-9 for start, end in program):
            ceiling = score if ceiling is None else max(ceiling, score)
    if ceiling is None:
        return None
    threshold = math.nextafter(float(ceiling), math.inf)
    if not any(score >= threshold for score in scores):
        return None
    return threshold


def lock_threshold(mask: dict, times: list[float], scores: list[float]) -> dict:
    """Pick the mute rule on one calibration broadcast. October is not passed in."""
    coverage = pairs(mask, "coverage")[0]
    program = pairs(mask, "verified_program")
    extra = _separating_threshold(times, scores, program)
    thresholds = THRESHOLDS if extra is None else THRESHOLDS + (extra,)
    best = None
    curve = []
    for threshold in thresholds:
        playback = playback_from_scores(coverage, times, scores, threshold)
        scored = score_mask(mask, playback)
        point = {
            "threshold": threshold,
            "broken": scored["broken"],
            "commercial_held_s": scored["commercial_held_s"],
            "program_cut_s": scored["program_cut_s"],
            "false_cover_incidents": scored["false_cover_incidents"],
        }
        curve.append(point)
        if point["broken"]:
            continue
        if best is None or point["commercial_held_s"] > best["commercial_held_s"]:
            best = point
    return {
        "locked": best,
        "curve": curve,
        "unbroken_points": sum(1 for row in curve if not row["broken"]),
    }
