"""Football events from a causal transcript, then a watch that can mute.

The patterns were taken from the event list in OHUSH_NFL75_EVENT_FIRST_001
before this module was run on the Prime tapes. A chunk that repeats the
previous chunk is ignored. A game event in the same chunk as a replay,
a hypothetical, or a look back does not open a watch.

A watch stays open while the announcer keeps talking. It does not mute
by itself. A mute needs the watch, the frozen commercial score, and a
booth voice that is not in the current second. A booth return consumes
the watch. A two-minute warning is a game event, not a two-minute mute.
"""

from __future__ import annotations

import re

from experiments.nfl75.accumulate import _advance
from experiments.nfl75.persist import HOLE_S, RETURN_PERSIST_S, _EPS

# How long the broadcast may keep talking before the handoff. One value
# per event. Not searched.
HORIZON_S = {
    "touchdown": 90.0,
    "field_goal": 90.0,
    "field_goal_miss": 45.0,
    "fumble": 45.0,
    "interception": 45.0,
    "punt": 45.0,
    "kickoff": 45.0,
    "timeout": 45.0,
    "two_minute_warning": 60.0,
    "injury": 45.0,
    "challenge": 60.0,
    "quarter_end": 60.0,
    "halftime": 90.0,
    "overtime": 60.0,
    "handoff": 20.0,
    "short_break": 20.0,
}
EXPECTATION = {
    "touchdown": "long_after_sequence",
    "field_goal": "long_after_sequence",
    "field_goal_miss": "unknown",
    "fumble": "unknown",
    "interception": "unknown",
    "punt": "unknown",
    "kickoff": "unknown",
    "timeout": "unknown",
    "two_minute_warning": "long",
    "injury": "unknown",
    "challenge": "unknown",
    "quarter_end": "long",
    "halftime": "halftime",
    "overtime": "unknown",
    "handoff": "imminent",
    "short_break": "short",
}
# These do not open a watch. They are marked on the timeline.
RETURN_LANGUAGE = ("welcome back", "and we're back", "we're back", "back here")
LOOKBACK = (
    "last week",
    "last year",
    "last season",
    "years ago",
    "a year ago",
    "remember when",
    "used to",
    "coming off",
    "replay",
    "highlight",
)
HYPOTHETICAL = (
    "would have",
    "would've",
    "could have",
    "could've",
    "might have",
    "almost",
    "nearly",
)
FRESH_BOOTH_S = 1.0


def normalize(text: str) -> str:
    return " ".join(text.lower().replace("-", " ").split())


def _has(text: str, phrase: str) -> bool:
    return phrase in text


def _word(text: str, word: str) -> bool:
    return re.search(rf"\b{re.escape(word)}\b", text) is not None


def extract_events(text: str, previous_text: str = "") -> list[dict]:
    """Events in one chunk. `status` is live or uncertain. Gold is unused."""
    folded = normalize(text)
    if not folded:
        return []
    if folded == normalize(previous_text):
        return []
    lookback = any(_has(folded, phrase) for phrase in LOOKBACK)
    hypothetical = any(_has(folded, phrase) for phrase in HYPOTHETICAL)
    found: list[dict] = []

    def add(kind: str, *, live: bool) -> None:
        if any(row["kind"] == kind for row in found):
            return
        status = "live" if live and not lookback and not hypothetical else "uncertain"
        if kind in ("handoff", "short_break", "return"):
            status = "live" if live else "uncertain"
        found.append({"kind": kind, "status": status, "expectation": EXPECTATION.get(kind, "unknown")})

    if _word(folded, "touchdown"):
        negated = _has(folded, "no touchdown") or _has(folded, "not a touchdown")
        add("touchdown", live=not negated)
    if _has(folded, "field goal") and _has(folded, "no good"):
        add("field_goal_miss", live=True)
    elif _has(folded, "field goal") and _word(folded, "good"):
        add("field_goal", live=True)
    if _word(folded, "fumble") or _word(folded, "fumbled"):
        add("fumble", live=True)
    if _word(folded, "intercepted") or _word(folded, "interception"):
        add("interception", live=True)
    if _word(folded, "punt") or _word(folded, "punted") or _word(folded, "punting"):
        add("punt", live=True)
    if _has(folded, "kickoff") or _has(folded, "kick off"):
        add("kickoff", live=True)
    if _has(folded, "two minute warning"):
        add("two_minute_warning", live=True)
    if any(
        _has(folded, phrase)
        for phrase in (
            "end of the quarter",
            "end of the half",
            "end of quarter",
            "quarter is over",
            "end of the first",
            "end of the second",
            "end of the third",
            "end of the fourth",
        )
    ):
        add("quarter_end", live=True)
    if _has(folded, "halftime") or _has(folded, "half time"):
        add("halftime", live=True)
    if _word(folded, "overtime"):
        add("overtime", live=True)
    if _word(folded, "injured") or _word(folded, "injury") or _has(folded, "hurt on the play"):
        add("injury", live=True)
    if _word(folded, "challenge") or _has(folded, "under review"):
        add("challenge", live=True)
    if _called_timeout(folded):
        add("timeout", live=True)
    if _short_break(folded):
        add("short_break", live=True)
    elif _handoff(folded):
        add("handoff", live=True)
    elif _return_line(folded):
        add("return", live=True)
    return found


def _called_timeout(text: str) -> bool:
    if not _word(text, "timeout") and not _has(text, "time out"):
        return False
    inventory = any(
        _has(text, phrase)
        for phrase in ("timeouts left", "timeouts remaining", "no timeouts", "out of timeouts", "without a timeout")
    )
    called = any(
        _has(text, phrase)
        for phrase in (
            "takes a timeout",
            "take a timeout",
            "takes their timeout",
            "called a timeout",
            "calls a timeout",
            "called timeout",
            "uses a timeout",
            "uses his timeout",
            "uses their timeout",
            "timeout on the field",
            "a timeout",
        )
    )
    if called:
        return True
    if inventory:
        return False
    return _word(text, "timeout") or _has(text, "time out")


def _short_break(text: str) -> bool:
    return any(
        _has(text, phrase)
        for phrase in ("back in 30", "back in thirty", "in 30 seconds", "in thirty seconds")
    )


def _handoff(text: str) -> bool:
    return any(
        _has(text, phrase)
        for phrase in (
            "we'll be right back",
            "we will be right back",
            "be right back",
            "when we come back",
            "after these messages",
            "these messages",
            "we'll take a break",
            "we will take a break",
            "take a break",
            "going to break",
            "back after this",
        )
    )


def _return_line(text: str) -> bool:
    if _short_break(text):
        return False
    return any(_has(text, phrase) for phrase in RETURN_LANGUAGE)


def watches_from_events(events: list[dict]) -> list[dict]:
    """One watch per live event. The clock starts when the transcript is ready."""
    rows = []
    for event in events:
        if event.get("status") != "live":
            continue
        kind = event["kind"]
        if kind not in HORIZON_S:
            continue
        opened = float(event["available_t"])
        rows.append(
            {
                "kind": kind,
                "open_s": opened,
                "close_s": opened + HORIZON_S[kind],
                "said_s": float(event["t0"]),
                "expectation": event.get("expectation", "unknown"),
                "text": event.get("text", ""),
            }
        )
    return rows


def _booth_now(match_ends: list[float], moment: float) -> bool:
    import bisect

    lo = bisect.bisect_right(match_ends, moment - FRESH_BOOTH_S)
    hi = bisect.bisect_right(match_ends, moment + _EPS)
    return hi > lo


def _watch_open(watches: list[dict], moment: float, consumed_before: float) -> bool:
    for watch in watches:
        if watch["open_s"] <= consumed_before + _EPS:
            continue
        if watch["open_s"] - _EPS <= moment < watch["close_s"]:
            return True
    return False


def covers_from_events(
    times: list[float],
    scores: list[float],
    means: list[float | None],
    match_ends: list[float],
    watches: list[dict],
    *,
    start_line: float,
    return_line: float = 0.0,
    return_persist_s: float = RETURN_PERSIST_S,
) -> tuple[list[tuple[float, float]], list[bool]]:
    """Mute only inside a watch, and only when the score is hot and the booth is quiet.

    The watch is not cancelled because a booth match is still arriving.
    A booth match that ends a cover consumes every watch that had already opened.
    """
    if len(times) != len(scores) or len(times) != len(means):
        raise ValueError("each second needs a score and a mean")
    ordered = sorted(watches, key=lambda row: row["open_s"])
    state = "play"
    cold = 0.0
    previous: float | None = None
    opened: float | None = None
    consumed_before = -1.0
    covers: list[tuple[float, float]] = []
    flags: list[bool] = []
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
        hot = mean is not None and float(mean) >= start_line
        booth = _booth_now(match_ends, moment)
        watching = _watch_open(ordered, moment, consumed_before)
        eligible = watching and hot and not booth
        flags.append(watching)
        if state == "cover" and booth:
            state = "play"
            covers.append((float(opened), moment))
            opened = None
            consumed_before = moment
        elif state == "cover" and not watching:
            state = "play"
            covers.append((float(opened), moment))
            opened = None
        elif state == "play" and eligible:
            state = "cover"
            opened = moment
            cold = 0.0
        elif state == "cover" and cold + _EPS >= return_persist_s:
            state = "play"
            covers.append((float(opened), moment))
            opened = None
    if opened is not None and previous is not None:
        covers.append((opened, previous + 1.0))
    return covers, flags
