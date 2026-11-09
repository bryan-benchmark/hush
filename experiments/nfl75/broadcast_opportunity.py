"""Broadcast-opportunity gate for the frozen rolling-mean commercial score.

The score is confirmation. It does not mute on its own. A cover can open
only while a predeclared transition is eligible:

- A. Thirty seconds have passed since a recognized booth voice.
- B. An explicit sign-off and an acoustic onset agree within 3 seconds.
- C. Stoppage language, then a speaker change and an acoustic onset.
- D. A speaker change and an acoustic onset, with no phrase required.

A, B, C, and D were named before this module was run. No second threshold
is searched. Booth identity is the published 0.25 cosine to Al Michaels or
Kirk Herbstreit. The acoustic onset is the frozen 18 dB drop against the
previous 2 seconds, without the short-dip recovery filter. Sign-off phrases
are the frozen EXP-03 list. A timeout or a two-minute warning does not mute
by itself.

Gold boundaries are not an input to eligibility.
"""

from __future__ import annotations

import bisect
import math

import numpy as np

from experiments.nfl75.accumulate import _advance
from experiments.nfl75.persist import HOLE_S, RETURN_PERSIST_S, _EPS

# Published SpeechBrain line. Not retuned.
MATCH_COSINE = 0.25
BOOTH_NAMES = ("Al Michaels", "Kirk Herbstreit")
# The absence hypothesis. Not a searched hold.
ABSENCE_S = 30.0
# EXP-03 already scored phrase and DSP agreement inside this window.
NEAR_S = 3.0
# Football p90 in EXP-C is 181.9 s. Rounded down. An opportunity expires.
# It is not an unmute clock.
OPPORTUNITY_S = 180.0
# Frozen relative drop from EXP-01. The 200 ms recovery filter is not
# applied: that filter was what rejected the level change at a boundary.
DROP_DB = 18.0
PAST_S = 2.0
PAST_FLOOR_DB = -45.0
FRAME_S = 0.040
# Strong phrases, copied from the frozen EXP-03 list.
SIGN_OFF = (
    "we'll be right back",
    "we will be right back",
    "be right back",
    "when we come back",
    "after these messages",
    "these messages",
    "commercial break",
    "going to commercial",
    "we'll return",
    "we will return",
    "back after this",
)
# Game-state language. Detected, and not a mute by itself.
STOPPAGE = (
    "two-minute warning",
    "two minute warning",
    "end of the quarter",
    "end of the half",
    "end of quarter",
    "timeout",
    "injury",
    "injured",
    "halftime",
)


def normalize(text: str) -> str:
    return " ".join(text.lower().replace("-", " ").split())


def phrases_in(text: str, phrases: tuple[str, ...]) -> list[str]:
    folded = normalize(text)
    return [phrase for phrase in phrases if normalize(phrase) in folded]


def fixed_delay_ceiling(durations: list[float], delay_s: float) -> dict:
    """Coverage if every break is caught after a fixed wait and returned perfectly.

    A break shorter than the wait is missed entirely. This is a ceiling, not
    a detector result.
    """
    if delay_s < 0:
        raise ValueError("delay must be non-negative")
    total = float(sum(durations))
    if total <= 0:
        raise ValueError("no commercial seconds")
    covered = 0.0
    reachable = 0
    for duration in durations:
        if duration <= 0:
            raise ValueError("a break needs a positive duration")
        left = duration - delay_s
        if left > 0:
            covered += left
            reachable += 1
    return {
        "delay_s": delay_s,
        "breaks": len(durations),
        "breaks_reachable": reachable,
        "commercial_s": round(total, 3),
        "coverable_s": round(covered, 3),
        "coverage": round(covered / total, 4),
    }


def _finite(value: float) -> bool:
    return math.isfinite(float(value))


def booth_cosine(people: np.ndarray, names: list[str]) -> np.ndarray:
    """Per-window cosine to the booth only. Studio voices stay out."""
    columns = [index for index, name in enumerate(names) if name in BOOTH_NAMES]
    if len(columns) != len(BOOTH_NAMES):
        missing = [name for name in BOOTH_NAMES if name not in names]
        raise RuntimeError(f"booth enrollment is missing {missing}")
    block = np.asarray(people[:, columns], dtype=np.float64)
    out = np.full(block.shape[0], np.nan, dtype=np.float64)
    finite = np.isfinite(block)
    any_finite = finite.any(axis=1)
    if any_finite.any():
        masked = np.where(finite, block, -np.inf)
        out[any_finite] = masked[any_finite].max(axis=1)
    return out


def match_times(ends: list[float], cosines: list[float], line: float = MATCH_COSINE) -> list[float]:
    found = []
    for end, score in zip(ends, cosines):
        if _finite(score) and float(score) >= line:
            found.append(float(end))
    return found


def other_speech_times(ends: list[float], cosines: list[float], line: float = MATCH_COSINE) -> list[float]:
    """Speech windows whose booth cosine is known and below the match line."""
    found = []
    for end, score in zip(ends, cosines):
        if _finite(score) and float(score) < line:
            found.append(float(end))
    return found


def _in_window(moments: list[float], left: float, right: float) -> list[float]:
    """Moments in (left, right]. `moments` is sorted."""
    if not moments:
        return []
    lo = bisect.bisect_right(moments, left)
    hi = bisect.bisect_right(moments, right)
    return moments[lo:hi]


def arms_d(
    acoustic: list[float],
    other_ends: list[float],
    match_ends: list[float],
    *,
    near_s: float = NEAR_S,
    recent_s: float = ABSENCE_S,
) -> list[float]:
    """Acoustic onset plus a changed speaker, after the booth was recently heard.

    The arm time is the later of the onset and the other-speech window, so a
    window that has not ended yet cannot arm.
    """
    arms = []
    for onset in acoustic:
        onset = float(onset)
        if not _in_window(match_ends, onset - recent_s - _EPS, onset):
            continue
        others = _in_window(other_ends, onset - near_s - _EPS, onset + near_s)
        if not others:
            continue
        earlier = [moment for moment in others if moment <= onset + _EPS]
        arms.append(onset if earlier else min(others))
    return _unique(arms)


def arms_b(
    signoffs: list[float],
    acoustic: list[float],
    *,
    near_s: float = NEAR_S,
) -> list[float]:
    """Sign-off plus an acoustic onset. The phrase alone returns nothing."""
    arms = []
    for phrase in signoffs:
        phrase = float(phrase)
        hits = _in_window(acoustic, phrase - near_s - _EPS, phrase + near_s)
        if not hits:
            continue
        earlier = [moment for moment in hits if moment <= phrase + _EPS]
        arms.append(phrase if earlier else min(hits))
    return _unique(arms)


def arms_c(
    stoppages: list[float],
    d_arms: list[float],
    match_ends: list[float],
) -> list[float]:
    """Stoppage language, then a D arm before the booth is heard again.

    The stoppage by itself is not an arm.
    """
    arms = []
    for phrase in stoppages:
        phrase = float(phrase)
        for arm in d_arms:
            if arm + _EPS < phrase:
                continue
            if _in_window(match_ends, phrase, arm):
                continue
            arms.append(float(arm))
            break
    return _unique(arms)


def _unique(moments: list[float]) -> list[float]:
    ordered = sorted(set(round(moment, 6) for moment in moments))
    return [float(moment) for moment in ordered]


def _age_at(match_ends: list[float], moment: float) -> float | None:
    index = bisect.bisect_right(match_ends, moment + _EPS) - 1
    if index < 0:
        return None
    return float(moment) - match_ends[index]


def _edge_open(moment: float, arms: list[float], match_ends: list[float], horizon_s: float) -> bool:
    if not arms:
        return False
    last = bisect.bisect_right(arms, moment + _EPS) - 1
    if last < 0:
        return False
    arm = arms[last]
    if moment - arm > horizon_s + _EPS:
        return False
    return not _in_window(match_ends, arm, moment)


def covers_opportunity(
    times: list[float],
    scores: list[float],
    means: list[float | None],
    match_ends: list[float],
    *,
    mode: str,
    d_arms: list[float] | None = None,
    b_arms: list[float] | None = None,
    c_arms: list[float] | None = None,
    start_line: float,
    return_line: float = 0.0,
    return_persist_s: float = RETURN_PERSIST_S,
    absence_s: float = ABSENCE_S,
    horizon_s: float = OPPORTUNITY_S,
) -> tuple[list[tuple[float, float]], list[bool]]:
    """Covers, and whether each decision second was eligible.

    `mode` is a combination of the letters A, B, C, and D. Gold is unused.
    """
    if len(times) != len(scores) or len(times) != len(means):
        raise ValueError("each second needs a score and a mean")
    allowed = set(mode)
    if not allowed or allowed - set("ABCD"):
        raise ValueError(f"unknown opportunity mode {mode!r}")
    d_arms = d_arms or []
    b_arms = b_arms or []
    c_arms = c_arms or []
    edge: list[float] = []
    if "B" in allowed:
        edge.extend(b_arms)
    if "C" in allowed:
        edge.extend(c_arms)
    if "D" in allowed:
        edge.extend(d_arms)
    edge = _unique(edge)
    state = "play"
    cold = 0.0
    previous: float | None = None
    opened: float | None = None
    covers: list[tuple[float, float]] = []
    eligible_flags: list[bool] = []
    for index, moment in enumerate(times):
        moment = float(moment)
        score = float(scores[index])
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
        age = _age_at(match_ends, moment)
        absence = "A" in allowed and age is not None and age + _EPS >= absence_s
        edge_on = bool(edge) and _edge_open(moment, edge, match_ends, horizon_s)
        eligible = absence or edge_on
        eligible_flags.append(eligible)
        if state == "cover" and not eligible:
            state = "play"
            covers.append((float(opened), moment))
            opened = None
        elif state == "play" and eligible and hot:
            state = "cover"
            opened = moment
            cold = 0.0
        elif state == "cover" and cold + _EPS >= return_persist_s:
            state = "play"
            covers.append((float(opened), moment))
            opened = None
    if opened is not None and previous is not None:
        covers.append((opened, previous + 1.0))
    return covers, eligible_flags


def coarse_onsets(db: np.ndarray, frame_s: float, origin: float) -> list[float]:
    """Availability times of an 18 dB drop against the previous 2 seconds.

    `db[i]` is the frame starting at `origin + i * frame_s`. The onset is
    available at the end of that frame. Frames before the past window emit
    nothing.
    """
    values = np.asarray(db, dtype=np.float64)
    if frame_s <= 0:
        raise ValueError("frame length must be positive")
    past_n = int(round(PAST_S / frame_s))
    if past_n < 1 or len(values) <= past_n:
        return []
    windows = np.lib.stride_tricks.sliding_window_view(values, past_n)
    median = np.median(windows, axis=1)
    # median[j] summarizes values[j:j+past_n]. The decision frame is j+past_n,
    # and it is not inside that summary.
    decision_index = np.arange(past_n, past_n + len(median))
    decision_index = decision_index[: len(values) - past_n]
    median = median[: len(decision_index)]
    decision = values[decision_index]
    hot = np.isfinite(median) & (median >= PAST_FLOOR_DB) & (decision <= median - DROP_DB)
    previous = np.concatenate(([False], hot[:-1]))
    starts = np.flatnonzero(hot & ~previous)
    ends = origin + (decision_index[starts] + 1) * frame_s
    return [float(moment) for moment in ends]
