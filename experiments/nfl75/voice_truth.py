"""An entry guard for three names. It does not release a mute, and it does not hold.

A finished window protects the next decision for one second. That is the
existing hop of a 2-second embedding, not a pause. The names are Al Michaels,
Kirk Herbstreit, and Clarissa Thompson. The cosine stays at 0.25 and the
runner-up gap stays at 0.15. Whitworth and Gonzalez do not qualify.
"""

from __future__ import annotations

import bisect
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from experiments.nfl75.accumulate import _advance
from experiments.nfl75.mean import LOGISTIC_RETURN, rolling_means
from experiments.nfl75.persist import HOLE_S, RETURN_PERSIST_S, _EPS
from hush.speaker_memory import MATCH_COSINE

ALLOW = ("Al Michaels", "Kirk Herbstreit", "Clarissa Thompson")
_OWNER_ALIASES = (
    ("al michaels", "Al Michaels"),
    ("kirk herbstreit", "Kirk Herbstreit"),
    ("clarisssa thompson", "Clarissa Thompson"),
    ("clarrisa thompson", "Clarissa Thompson"),
    ("clarissa thompson", "Clarissa Thompson"),
    ("andrew whitworth", "Andrew Whitworth"),
    ("tony gonzalez", "Tony Gonzalez"),
    ("ryan fitzpatrick", "Ryan Fitzpatrick"),
    ("ryan fits", "Ryan Fitzpatrick"),
)


def owner_names(text: str) -> list[str]:
    """Enrolled names the owner actually wrote. A nickname has to be the whole alias."""
    low = " ".join(text.lower().split())
    found = []
    for alias, canon in _OWNER_ALIASES:
        if alias in low and canon not in found:
            found.append(canon)
    return found
MARGIN = 0.15
FRESH_S = 1.0


def qualify(scores: dict[str, float], *, line: float = MATCH_COSINE, margin: float = MARGIN) -> dict | None:
    """A finished window the entry guard is allowed to read. None otherwise."""
    if line != MATCH_COSINE or margin != MARGIN:
        raise ValueError("the line stays at 0.25 and the gap stays at 0.15")
    finite = [(name, float(value)) for name, value in scores.items() if value == value]
    if len(finite) < 2:
        return None
    finite.sort(key=lambda item: item[1], reverse=True)
    name, best = finite[0]
    _other, second = finite[1]
    gap = best - second
    if name not in ALLOW or best + 1e-12 < line or gap + 1e-12 < margin:
        return None
    return {"name": name, "cosine": best, "second": second, "gap": gap}


def candidate_rows(rows: list[dict]) -> dict:
    """Development ignores, split by name. Wide-margin Whitworth stays out."""
    grouped: dict[str, list[float]] = {name: [] for name in ALLOW}
    by_session: dict[str, float] = {}
    wide_other = []
    thin = []
    for row in rows:
        if row.get("split") != "dev" or row.get("kind") != "decision_ignored_match":
            continue
        name = row.get("cited_name")
        cosine = row.get("cited_cosine")
        second = row.get("second_cosine")
        duration = float(row["focus_end_s"]) - float(row["focus_start_s"])
        if cosine is None or second is None:
            continue
        gap = float(cosine) - float(second)
        if gap + 1e-12 < MARGIN:
            thin.append((name, duration))
            continue
        if name in grouped:
            grouped[name].append(duration)
            session = row.get("session") or "unspecified"
            by_session[session] = by_session.get(session, 0.0) + duration
        else:
            wide_other.append((name, duration))
    by_name = []
    for name in ALLOW:
        durations = grouped[name]
        by_name.append(
            {
                "name": name,
                "episodes": len(durations),
                "seconds": round(sum(durations), 3),
            }
        )
    return {
        "by_name": by_name,
        "episodes": sum(row["episodes"] for row in by_name),
        "seconds": round(sum(row["seconds"] for row in by_name), 3),
        "by_session": {key: round(value, 3) for key, value in sorted(by_session.items())},
        "wide_other": [{"name": name, "seconds": round(duration, 3)} for name, duration in wide_other],
        "thin": [{"name": name, "seconds": round(duration, 3)} for name, duration in thin],
        "identity_verified": False,
    }


def entry_guard_covers(
    times: list[float],
    scores: list[float],
    qualify_ends: list[float],
    *,
    window: int,
    start_line: float,
    fresh_s: float = FRESH_S,
    return_line: float = LOGISTIC_RETURN,
    return_persist_s: float = RETURN_PERSIST_S,
) -> list[tuple[float, float]]:
    """Block a new mute when a qualifying window has already finished.

    An open mute keeps the frozen three-second return. A speaker match does
    not close it.
    """
    if fresh_s != FRESH_S:
        raise ValueError("freshness stays at one second")
    if len(times) != len(scores):
        raise ValueError("each second needs one score")
    ends = sorted(float(value) for value in qualify_ends)
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
        slot = bisect.bisect_right(ends, moment + _EPS) - 1
        fresh = slot >= 0 and moment - ends[slot] <= fresh_s + _EPS
        if fresh and ends[slot] > moment + _EPS:
            raise RuntimeError("the guard read a window that had not finished")
        mean = means[index]
        hot = mean is not None and mean >= start_line
        if state == "cover" and cold + _EPS >= return_persist_s:
            state = "play"
            covers.append((float(opened), moment))
            opened = None
        elif state == "play" and hot and not fresh:
            state = "cover"
            opened = moment
            cold = 0.0
    if opened is not None and previous is not None:
        covers.append((opened, previous + 1.0))
    return covers
