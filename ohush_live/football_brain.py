"""Causal football ledger. It records what the announcers said.

It does not mute, and it does not read commercial labels. A missing score,
clock, team, or timeout count stays missing. The same words in an overlapping
transcript update one event, not two.

A touchdown, the extra point, and the new score are one scoring sequence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

SCHEMA = "ohush_football_brain_v1"
DEDUP_S = 15.0
SEQUENCE_S = 90.0

LIVE_KINDS = (
    "TOUCHDOWN",
    "FIELD_GOAL_GOOD",
    "FIELD_GOAL_MISSED",
    "EXTRA_POINT",
    "TWO_POINT_CONVERSION",
    "INTERCEPTION",
    "FUMBLE_RECOVERY",
    "PUNT",
    "KICKOFF",
    "TIMEOUT",
    "TWO_MINUTE_WARNING",
    "INJURY",
    "CHALLENGE",
    "QUARTER_END",
    "HALFTIME",
    "OVERTIME",
    "SCORE_UPDATE",
    "BROADCAST_SIGNOFF",
    "BREAK_DURATION_ANNOUNCED",
    "PROGRAM_RETURN",
)
LOOKBACK = (
    "last week",
    "last year",
    "last season",
    "last sunday",
    "last night",
    "yesterday",
    "years ago",
    "a year ago",
    "remember when",
    "used to",
    "coming off",
    "replay",
    "highlight",
    "let's look",
    "look at that",
    "what was the",
)
HYPOTHETICAL = (
    "would have",
    "would've",
    "could have",
    "could've",
    "might have",
    "almost",
    "nearly",
    "if they",
    "if he",
    "if we",
    "can they",
    "can he",
    "looking for",
    "go for the",
    "go for a",
    "settle for",
)
SCORE_KINDS = {"TOUCHDOWN", "FIELD_GOAL_GOOD"}
ATTACH_KINDS = {"EXTRA_POINT", "TWO_POINT_CONVERSION", "SCORE_UPDATE"}


def normalize(text: str) -> str:
    return " ".join(text.lower().replace("-", " ").split())


def _has(text: str, phrase: str) -> bool:
    return phrase in text


def _word(text: str, word: str) -> bool:
    return re.search(rf"\b{re.escape(word)}\b", text) is not None


def interpret(text: str, previous_text: str = "") -> list[dict]:
    """Read one finished transcript. Status is live or uncertain.

    `previous_text` is accepted so a caller can pass it, and it is not used
    to drop a later play that happens to be called with the same words.
    Overlap dedup lives on the engine, where the audio times are known.
    """
    del previous_text
    folded = normalize(text)
    if not folded:
        return []
    lookback = any(_has(folded, phrase) for phrase in LOOKBACK)
    hypothetical = any(_has(folded, phrase) for phrase in HYPOTHETICAL)
    found: list[dict] = []

    def add(kind: str, *, live: bool, detail: str = "") -> None:
        if any(row["kind"] == kind for row in found):
            return
        quiet = kind in {"BROADCAST_SIGNOFF", "BREAK_DURATION_ANNOUNCED", "PROGRAM_RETURN"}
        status = "live" if live and (quiet or not lookback and not hypothetical) else "uncertain"
        found.append({"kind": kind, "status": status, "detail": detail})

    if _word(folded, "touchdown"):
        negated = _has(folded, "no touchdown") or _has(folded, "not a touchdown")
        stat_line = "and a touchdown" in folded and "for the touchdown" not in folded
        add("TOUCHDOWN", live=not negated and not stat_line)
    if _has(folded, "field goal") and _has(folded, "no good"):
        add("FIELD_GOAL_MISSED", live=True)
    elif _has(folded, "field goal") and _word(folded, "good"):
        add("FIELD_GOAL_GOOD", live=True)
    if _has(folded, "extra point") or _has(folded, "point after"):
        add("EXTRA_POINT", live=True)
    if _has(folded, "two point") or _has(folded, "going for two"):
        add("TWO_POINT_CONVERSION", live=True)
    if _word(folded, "intercepted") or _word(folded, "interception") or _has(folded, "picks it off"):
        add("INTERCEPTION", live=True)
    if _word(folded, "fumble") or _word(folded, "fumbled"):
        add("FUMBLE_RECOVERY", live=True, detail="recovered" if _word(folded, "recovered") or _word(folded, "recovers") else "")
    if _word(folded, "punt") or _word(folded, "punted"):
        add("PUNT", live=True)
    if _has(folded, "kickoff") or _has(folded, "kick off"):
        add("KICKOFF", live=True)
    if _has(folded, "two minute warning"):
        add("TWO_MINUTE_WARNING", live=True)
    if any(
        _has(folded, phrase)
        for phrase in (
            "end of the quarter",
            "end of the half",
            "end of the first",
            "end of the second",
            "end of the third",
            "end of the fourth",
            "quarter is over",
        )
    ):
        add("QUARTER_END", live=True)
    if _has(folded, "halftime") or _has(folded, "half time"):
        add("HALFTIME", live=True)
    if _word(folded, "overtime"):
        add("OVERTIME", live=True)
    if _word(folded, "injured") or _word(folded, "injury") or _has(folded, "hurt on the play"):
        add("INJURY", live=True)
    if _word(folded, "challenge") or _has(folded, "under review"):
        add("CHALLENGE", live=True)
    if _called_timeout(folded):
        add("TIMEOUT", live=True)
    pair = _score_pair(folded)
    if pair is not None:
        add("SCORE_UPDATE", live=True, detail=f"{pair[0]}-{pair[1]}")
    clock = _clock(folded)
    if _duration(folded):
        add("BREAK_DURATION_ANNOUNCED", live=True, detail=_duration(folded))
    elif _signoff(folded):
        add("BROADCAST_SIGNOFF", live=True)
    elif _return_line(folded):
        add("PROGRAM_RETURN", live=True)
    if clock is not None:
        for row in found:
            row.setdefault("clock_seconds", clock)
    return found


def _called_timeout(text: str) -> bool:
    if not _word(text, "timeout") and "time out" not in text:
        return False
    inventory = any(
        phrase in text
        for phrase in ("timeouts left", "timeouts remaining", "no timeouts", "out of timeouts", "without a timeout")
    )
    called = any(
        phrase in text
        for phrase in (
            "takes a timeout",
            "take a timeout",
            "called a timeout",
            "calls a timeout",
            "called timeout",
            "uses a timeout",
            "timeout on the field",
            "a timeout",
        )
    )
    if called:
        return True
    if inventory:
        return False
    return _word(text, "timeout") or "time out" in text


def _duration(text: str) -> str:
    if any(phrase in text for phrase in ("back in 30", "back in thirty", "in 30 seconds", "in thirty seconds")):
        return "30"
    if any(phrase in text for phrase in ("back in two", "back in 2", "in two minutes")):
        return "120"
    return ""


def _signoff(text: str) -> bool:
    return any(
        phrase in text
        for phrase in (
            "we'll be right back",
            "we will be right back",
            "be right back",
            "when we come back",
            "after these messages",
            "these messages",
            "we'll take a break",
            "take a break",
            "back after this",
        )
    )


def _return_line(text: str) -> bool:
    if _duration(text):
        return False
    return any(phrase in text for phrase in ("welcome back", "and we're back", "we're back", "back here"))


def _score_pair(text: str) -> tuple[int, int] | None:
    if not any(phrase in text for phrase in ("makes it", "the score", "score is", "it's now", "now  ")):
        if "makes it" not in text and "the score" not in text and "score is" not in text and "it's now" not in text:
            return None
    match = re.search(r"\b(\d{1,2})\s*(?:to|-)\s*(\d{1,2})\b", text)
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2))


def _clock(text: str) -> int | None:
    seconds = re.search(r"\b(\d{1,3})\s+seconds left\b", text)
    if seconds:
        return int(seconds.group(1))
    minutes = re.search(r"\b(\d{1,2})\s+minutes left\b", text)
    if minutes:
        return int(minutes.group(1)) * 60
    return None


def _quarter(text: str) -> int | None:
    folded = normalize(text)
    for number, name in ((1, "first"), (2, "second"), (3, "third"), (4, "fourth")):
        if f"{name} quarter" in folded and "end of" not in folded:
            return number
    return None


@dataclass
class GameState:
    quarter: int | None = None
    clock_seconds: int | None = None
    clock_phrase: str | None = None
    score_pair: tuple[int, int] | None = None
    score_phrase: str | None = None
    score_team: str | None = None
    scoring_sequence_id: str | None = None
    last_possession: str | None = None
    last_stoppage: str | None = None
    last_signoff: str | None = None
    phase: str = "play"

    def view(self) -> dict:
        return {
            "quarter": self.quarter,
            "clock_seconds": self.clock_seconds,
            "clock_phrase": self.clock_phrase,
            "score_pair": None if self.score_pair is None else list(self.score_pair),
            "score_phrase": self.score_phrase,
            "score_team": self.score_team,
            "scoring_sequence_id": self.scoring_sequence_id,
            "last_possession": self.last_possession,
            "last_stoppage": self.last_stoppage,
            "last_signoff": self.last_signoff,
            "phase": self.phase,
        }


@dataclass
class FootballEngine:
    """One session. Feed finished chunks in time order."""

    state: GameState = field(default_factory=GameState)
    reader: object = interpret
    duplicates: int = 0
    _last_kind_at: dict[str, float] = field(default_factory=dict)
    _sequence_opened_at: float | None = None
    _sequence_count: int = 0
    _previous_text: str = ""
    _previous_t1: float = -1.0

    def observe(self, chunk: dict) -> tuple[list[dict], dict]:
        text = str(chunk.get("text") or "")
        said = float(chunk["t0"])
        ready = float(chunk["available_t"])
        if said > ready + 1e-6:
            raise ValueError("a transcript cannot be known before its audio ends")
        heard_until = float(chunk["t1"])
        if said < self._previous_t1 and normalize(text) == normalize(self._previous_text):
            self._previous_t1 = heard_until
            return [], self.state.view()
        emitted = []
        model = getattr(self.reader, "replaces_phrases", False)
        if not model:
            clock = _clock(normalize(text))
            if clock is not None:
                self.state.clock_seconds = clock
                self.state.clock_phrase = normalize(text)[:80]
            quarter = _quarter(text)
            if quarter is not None:
                self.state.quarter = quarter
        found = self.reader(text, self._previous_text)
        if model:
            facts = getattr(self.reader, "facts", {}) or {}
            if facts.get("quarter") in (1, 2, 3, 4):
                self.state.quarter = facts["quarter"]
            if facts.get("clock_seconds") is not None:
                self.state.clock_seconds = facts["clock_seconds"]
                self.state.clock_phrase = normalize(text)[:80]
        for raw in found:
            event = self._accept(raw, said, float(chunk["t1"]), ready, text)
            if event is not None:
                emitted.append(event)
        self._previous_text = text
        self._previous_t1 = heard_until
        return emitted, self.state.view()

    def _accept(self, raw: dict, said: float, heard_until: float, ready: float, text: str) -> dict | None:
        kind = raw["kind"]
        if kind not in LIVE_KINDS:
            raise ValueError(kind)
        if raw["status"] != "live":
            return self._row(raw, said, heard_until, ready, text, sequence=None, duplicate=False)
        previous = self._last_kind_at.get(kind)
        if previous is not None and said - previous < DEDUP_S:
            self.duplicates += 1
            return None
        sequence = None
        if kind in SCORE_KINDS and self._sequence_opened_at is not None and said - self._sequence_opened_at <= SEQUENCE_S:
            sequence = self.state.scoring_sequence_id
        elif kind in SCORE_KINDS:
            self._sequence_count += 1
            sequence = f"score-{self._sequence_count}"
            self._sequence_opened_at = said
            self.state.scoring_sequence_id = sequence
            self.state.phase = "scoring"
        elif kind in ATTACH_KINDS and self._sequence_opened_at is not None and said - self._sequence_opened_at <= SEQUENCE_S:
            sequence = self.state.scoring_sequence_id
        elif kind in ATTACH_KINDS:
            sequence = None
        if kind in {"TIMEOUT", "INJURY", "CHALLENGE"}:
            self.state.last_stoppage = kind
            self.state.phase = "stoppage"
        elif kind in {"QUARTER_END", "HALFTIME"}:
            self.state.last_stoppage = kind
            self.state.phase = "period_break"
        elif kind in {"INTERCEPTION", "FUMBLE_RECOVERY", "PUNT", "KICKOFF"}:
            self.state.last_possession = kind
        elif kind == "BROADCAST_SIGNOFF":
            self.state.last_signoff = "signoff"
        elif kind == "BREAK_DURATION_ANNOUNCED":
            self.state.last_signoff = raw.get("detail") or "duration"
        elif kind == "PROGRAM_RETURN":
            self.state.phase = "play"
        elif kind == "TWO_MINUTE_WARNING":
            self.state.clock_seconds = 120
            self.state.clock_phrase = "two minute warning"
            self.state.last_stoppage = kind
        elif kind == "SCORE_UPDATE" and raw.get("detail"):
            left, right = raw["detail"].split("-")
            self.state.score_pair = (int(left), int(right))
            self.state.score_phrase = raw["detail"]
            if raw.get("team"):
                self.state.score_team = str(raw["team"])
        if raw["status"] == "live":
            self._last_kind_at[kind] = said
        return self._row(raw, said, heard_until, ready, text, sequence=sequence, duplicate=False)

    def _row(self, raw, said, heard_until, ready, text, *, sequence, duplicate) -> dict:
        return {
            "schema": SCHEMA,
            "kind": raw["kind"],
            "status": raw["status"],
            "audio_t": round(said, 3),
            "heard_until": round(heard_until, 3),
            "available_t": round(ready, 3),
            "latency_s": round(ready - heard_until, 3),
            "detail": raw.get("detail") or "",
            "evidence": raw.get("evidence") or "",
            "sequence": sequence,
            "duplicate": duplicate,
            "text": text[:180],
        }
