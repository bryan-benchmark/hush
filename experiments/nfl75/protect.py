"""A current announcer match can veto the frozen rolling-mean mute.

The commercial start is the NFL75_MEAN_001 rule: a 10-second mean at or
above the line frozen on the NBC games. This module does not move that line.

Protection is one published SpeechBrain cosine, 0.25, on a speaker window
that ended within the last second. A missing score does not veto. The
30-second enrolled-show memory is measured apart from the gate. The gate
does not use it.

Nothing here trains a model or moves a speaker.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from experiments.nfl75.accumulate import _advance
from experiments.nfl75.mean import LOGISTIC_RETURN, covers_from_mean, rolling_means
from experiments.nfl75.persist import HOLE_S, RETURN_PERSIST_S, _EPS
from hush.speaker_memory import MATCH_COSINE
from hush.voice_floor import FLOOR, MEMORY_S

# A 2-second embedding hops once a second. Older than that hop is memory.
FRESH_S = 1.0


def _ordered(ends: list[float]) -> None:
    for index in range(1, len(ends)):
        if ends[index] + _EPS < ends[index - 1]:
            raise ValueError("speaker windows are not in time order")


def fresh_cosine(
    ends: list[float],
    cosines: list[float],
    moment: float,
    *,
    fresh_s: float = FRESH_S,
) -> float | None:
    """Highest cosine whose window ended in (moment - fresh_s, moment]."""
    if len(ends) != len(cosines):
        raise ValueError("each speaker window needs one cosine")
    best = None
    for end, score in zip(ends, cosines):
        end = float(end)
        if end > moment + _EPS:
            break
        if moment - end <= fresh_s + _EPS and end <= moment + _EPS:
            value = float(score)
            if not math.isfinite(value):
                continue
            best = value if best is None else max(best, value)
    return best


def memory_max(
    ends: list[float],
    cosines: list[float],
    moment: float,
    *,
    memory_s: float = MEMORY_S,
) -> float | None:
    """Highest cosine in the last 30 seconds. Diagnostic. Not the gate."""
    if len(ends) != len(cosines):
        raise ValueError("each speaker window needs one cosine")
    best = None
    for end, score in zip(ends, cosines):
        end = float(end)
        if end > moment + _EPS:
            break
        if moment - end <= memory_s + _EPS:
            value = float(score)
            if not math.isfinite(value):
                continue
            best = value if best is None else max(best, value)
    return best


def covers_protected(
    times: list[float],
    scores: list[float],
    ends: list[float],
    cosines: list[float],
    *,
    window: int,
    start_line: float,
    line: float = MATCH_COSINE,
    rule: str = "current",
    hold_s: float = FRESH_S,
    rearm: bool = False,
    return_line: float = LOGISTIC_RETURN,
    return_persist_s: float = RETURN_PERSIST_S,
    trace: list | None = None,
) -> list[tuple[float, float]]:
    """Start on the rolling mean. A fresh 0.25 match can block or end a cover.

    `hold_s` is how long that match protects after its window ends. One
    second is the current veto. A window ending at T protects decisions
    from T through T + hold_s. It cannot protect a decision before T.

    `rearm` refuses another cover on the same hot run. After a voice
    blocks an open or releases a cover, the rolling mean has to fall
    below the start line and cross it again. No second line is added.

    `rule="memory"` is the 30-second, 0.10 enrolled-show floor. It is a
    cost measurement. It is not the protective gate.
    """
    if rule not in ("current", "memory"):
        raise ValueError("protection rule must be current or memory")
    if rearm and rule != "current":
        raise ValueError("rearm applies to the current voice hold")
    if hold_s <= 0:
        raise ValueError("hold must be positive")
    if len(times) != len(scores):
        raise ValueError("each second needs one score")
    if len(ends) != len(cosines):
        raise ValueError("each speaker window needs one cosine")
    _ordered(ends)
    means = rolling_means(times, scores, window)
    horizon = MEMORY_S if rule == "memory" else float(hold_s)
    guard = FLOOR if rule == "memory" else line
    state = "play"
    armed = True
    seen_below = False
    cold = 0.0
    previous: float | None = None
    opened: float | None = None
    cursor = 0
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
        while cursor < len(ends) and float(ends[cursor]) < moment - horizon - _EPS:
            cursor += 1
        best = None
        probe = cursor
        while probe < len(ends) and float(ends[probe]) <= moment + _EPS:
            value = float(cosines[probe])
            if math.isfinite(value):
                best = value if best is None else max(best, value)
            probe += 1
        protected = best is not None and best + _EPS >= guard
        mean = means[index]
        hot = mean is not None and mean >= start_line
        if rearm and not armed and mean is not None:
            if mean < start_line:
                seen_below = True
            elif seen_below and hot:
                armed = True
                seen_below = False
        if state == "play" and hot and not protected and (not rearm or armed):
            state = "cover"
            opened = moment
            cold = 0.0
        elif state == "play" and hot and protected and rearm and armed:
            armed = False
            seen_below = False
        elif state == "cover" and protected:
            state = "play"
            covers.append((float(opened), moment))
            opened = None
            if rearm:
                armed = False
                seen_below = False
        elif state == "cover" and cold + _EPS >= return_persist_s:
            state = "play"
            covers.append((float(opened), moment))
            opened = None
        if trace is not None:
            trace.append(
                {
                    "t": moment,
                    "hot": hot,
                    "protected": protected,
                    "armed": armed,
                    "mean": None if mean is None else float(mean),
                }
            )
    if opened is not None and previous is not None:
        covers.append((opened, previous + 1.0))
    return covers


def unprotected_covers(
    times: list[float],
    scores: list[float],
    *,
    window: int,
    start_line: float,
) -> list[tuple[float, float]]:
    """The frozen rolling mean with no football veto."""
    return covers_from_mean(times, scores, window=window, start_line=start_line)


def show_memory_would_protect(rolling: float | None) -> bool:
    """The live 0.10 floor over 30 seconds. Reported, not applied."""
    return rolling is not None and rolling + _EPS >= FLOOR
