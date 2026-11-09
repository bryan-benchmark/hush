"""Name a labeled clip. The 0.25 line stays frozen. No mute rule is built here.

Enrollment and the probe are different clips. A cross-tape probe uses only
earlier games. A same-game probe uses other clips from that game and leaves
the probe itself out. Five-second identity is not invented past a three-second
owner mark. A cosine under 0.25 is unknown, not a guess.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from hush.speaker_memory import MATCH_COSINE

TNF = (
    "Al Michaels",
    "Kirk Herbstreit",
    "Clarissa Thompson",
    "Ryan Fitzpatrick",
    "Andrew Whitworth",
    "Tony Gonzalez",
)
KEEP = ("clear", "laugh", "loud", "crowd", "song")
DURATIONS = (1.0, 2.0, 3.0)
_EPS = 1e-9


def session_stamp(session: str) -> str:
    _hush, day, clock = session.split("_")
    return day + clock


def identify(scores: dict[str, float], line: float = MATCH_COSINE) -> dict:
    """Nearest enrolled voice. Below the frozen line the name is withheld."""
    if line != MATCH_COSINE:
        raise ValueError("the speaker line stays at the published 0.25")
    finite = {name: float(value) for name, value in scores.items() if value == value}
    if not finite:
        return {"accepted": None, "rank1": None, "best": None, "second": None}
    ordered = sorted(finite.items(), key=lambda item: item[1], reverse=True)
    rank1, best = ordered[0]
    second = ordered[1][1] if len(ordered) > 1 else None
    accepted = rank1 if best + _EPS >= line else None
    return {
        "accepted": accepted,
        "rank1": rank1,
        "best": best,
        "second": second,
    }


def enrollment_rows(
    rows: list[dict],
    test_session: str,
    *,
    cross_tape: bool,
    clean: bool,
    exclude_ids: set[str],
) -> list[dict]:
    """References allowed to form a prototype for one probe."""
    chosen = []
    for row in rows:
        if row["id"] in exclude_ids:
            continue
        if row.get("who") not in TNF:
            continue
        condition = row.get("condition")
        if clean:
            if condition != "clear":
                continue
        elif condition not in KEEP:
            continue
        other = row["session"]
        if cross_tape:
            if session_stamp(other) >= session_stamp(test_session):
                continue
        elif other != test_session:
            continue
        chosen.append(row)
    return chosen


def probe_bucket(row: dict, enrolled_names: set[str]) -> str:
    """How a labeled clip is allowed to count. Songs are not correct-ID trials."""
    who = row.get("who") or ""
    condition = row.get("condition") or ""
    if who and who not in TNF:
        return "other_show"
    if condition == "song":
        return "song"
    if condition == "not_them" or not who:
        return "not_them" if condition == "not_them" else "unnamed"
    if condition == "skip":
        return "skip"
    if who not in enrolled_names:
        return "not_enrolled"
    if condition == "clear":
        return "clear"
    if condition in ("crowd", "loud", "laugh"):
        return "noisy"
    return "other"


def outcome(label: str, accepted: str | None, rank1: str | None, bucket: str) -> str:
    if bucket in ("not_them", "other_show", "not_enrolled"):
        if accepted is None:
            return "rejected"
        return "false_match"
    if bucket not in ("clear", "noisy"):
        return "not_scored"
    if rank1 is None and accepted is None:
        return "no_enrollment"
    if accepted == label:
        return "correct"
    if accepted is None:
        return "missed"
    return "wrong_person"


def tally(records: list[dict]) -> dict:
    """Counts for one bucket. Rates are left as counts so a small n stays visible."""
    counts: dict[str, int] = {}
    cosines: list[float] = []
    others: list[float] = []
    for row in records:
        counts[row["outcome"]] = counts.get(row["outcome"], 0) + 1
        if row.get("true_cosine") is not None:
            cosines.append(float(row["true_cosine"]))
        if row.get("best_other") is not None:
            others.append(float(row["best_other"]))
    return {
        "n": len(records),
        "outcomes": counts,
        "median_true_cosine": _median(cosines),
        "median_best_other": _median(others),
    }


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2
