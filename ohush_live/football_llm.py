"""Ask the local instruct model what a finished announcer line means.

The scorekeeper still decides what to keep. A score is kept only when both
numbers are in the line the model was shown. Silence is not sent.

    python -m ohush_live.football_llm

That command reads the lines where the phrase list left the score blank.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

from ohush_live.football_brain import LIVE_KINDS

MODEL = "qwen2.5:3b"
URL = "http://127.0.0.1:11434/api/generate"

_PROMPT = """You extract completed NFL events from one announcer line. Return one JSON object and nothing else.

Most lines contain no event. Use {{"quarter": null, "clock_seconds": null, "events": []}} unless the line states that something finished just now.

Each event quotes the line:
{{"kind": "TOUCHDOWN", "status": "live", "evidence": "exact words copied from the line", "score": null, "team": null, "detail": ""}}

status "live" only when that quote states a completed event happening now.
status "uncertain" for a hypothetical, a future play, a replay, a recap, history, or any doubt.
If you cannot copy the supporting words from the line, emit no event.

A touchdown is live for "touchdown", "he's in", "breaks the plane", or "six points" when the quote says the play just scored.
"They need a touchdown", "a two-touchdown lead", and "touchdown last week" are not a new touchdown.
"I got one" and "the Cowboys jumping off" are not a touchdown.

A timeout is live only when a timeout was just called. "timeouts remaining" and "timeouts left" are not a timeout.

A score is the points on the board now. The quote must say who leads or what the score is.
A yard line, a penalty, "40-5", and a record such as "0 and 5" are not the score.

"back in 30 seconds" is BREAK_DURATION_ANNOUNCED with detail "30".
"two minute warning" is TWO_MINUTE_WARNING. It is not a commercial length.
"back in 2000" is not a break.

Examples:
Line: The Cowboys are on top 10 to 7.
{{"quarter": null, "clock_seconds": null, "events": [{{"kind": "SCORE_UPDATE", "status": "live", "evidence": "on top 10 to 7", "score": [10, 7], "team": "Cowboys", "detail": ""}}]}}
Line: We're back in 30 seconds.
{{"quarter": null, "clock_seconds": null, "events": [{{"kind": "BREAK_DURATION_ANNOUNCED", "status": "live", "evidence": "back in 30 seconds", "score": null, "team": null, "detail": "30"}}]}}
Line: That's the end of the quarter.
{{"quarter": null, "clock_seconds": null, "events": [{{"kind": "QUARTER_END", "status": "live", "evidence": "end of the quarter", "score": null, "team": null, "detail": ""}}]}}
Line: 49 yards and a touchdown for Kailin.
{{"quarter": null, "clock_seconds": null, "events": [{{"kind": "TOUCHDOWN", "status": "uncertain", "evidence": "yards and a touchdown", "score": null, "team": null, "detail": ""}}]}}

kinds: {kinds}

Previous line: {previous}
Ledger: {ledger}
Line: {line}
"""

_QUARTER_WORD = {1: "first", 2: "second", 3: "third", 4: "fourth"}

BENCH = (
    "Texas the Cowboys on top 10 to 7.",
    "They go on to win 24-16 and get their first win.",
    "Packers with the final score of 35 to 14.",
    "So to the second quarter we go, Falcons up, 10-7.",
    "Falcons leave 17-7 at halftime.",
    "That's what the ball gives up 27-14 at this point.",
    "over six minutes in time possession 34 to 15 favoring Tampa.",
    "Working 24-7 to kill 99.9% of bucks trapped.",
    "traffic and a great drive, but are they going to have to settle for a field goal or can they get a touchdown",
    "The back ends, breaks the plane easy touchdown.",
    "8 for 8 on that opening drive 49 yards and a touchdown for Kailin.",
    "We're back in 30 seconds.",
    "Two minute warning.",
)


def _spoken_number(text: str, number: int) -> bool:
    return re.search(rf"\b{int(number)}\b", text) is not None


def _pair(score, detail: str) -> tuple[int, int] | None:
    if isinstance(score, (list, tuple)) and len(score) == 2:
        try:
            return int(score[0]), int(score[1])
        except (TypeError, ValueError):
            return None
    match = re.fullmatch(r"\s*(\d{1,2})\s*-\s*(\d{1,2})\s*", str(detail or ""))
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2))


def events_from_payload(text: str, payload: dict) -> tuple[list[dict], dict]:
    """Turn one model object into ledger events. Drop a score that was not spoken."""
    facts: dict = {}
    quarter = payload.get("quarter")
    try:
        quarter_n = int(quarter) if quarter is not None else None
    except (TypeError, ValueError):
        quarter_n = None
    folded = text.lower()
    if quarter_n in _QUARTER_WORD and (str(quarter_n) in text or _QUARTER_WORD[quarter_n] in folded):
        facts["quarter"] = quarter_n
    clock = payload.get("clock_seconds")
    try:
        clock_n = int(clock) if clock is not None else None
    except (TypeError, ValueError):
        clock_n = None
    if clock_n is not None and 0 <= clock_n <= 15 * 60:
        if _spoken_number(text, clock_n) or (clock_n == 120 and "two minute" in folded):
            facts["clock_seconds"] = clock_n
    events = []
    for item in payload.get("events") or []:
        if not isinstance(item, dict):
            continue
        kind = item.get("kind")
        if kind not in LIVE_KINDS:
            continue
        status = item.get("status") if item.get("status") in ("live", "uncertain") else "uncertain"
        detail = "" if item.get("detail") is None else str(item.get("detail"))
        evidence = str(item.get("evidence") or "")
        team = item.get("team") if isinstance(item.get("team"), str) and item.get("team") else ""
        if team and team.lower() not in text.lower():
            team = ""
        if kind == "SCORE_UPDATE":
            pair = _pair(item.get("score"), detail or evidence)
            if pair is None or not _spoken_number(text, pair[0]) or not _spoken_number(text, pair[1]):
                continue
            if pair[0] > 99 or pair[1] > 99:
                continue
            detail = f"{pair[0]}-{pair[1]}"
        events.append({"kind": kind, "status": status, "detail": detail, "team": team, "evidence": evidence})
    return ground_events(text, events), facts


_SCORE_WORDS = ("lead", "trail", "ahead", "behind", "score", "on top", "up ", "win")


def ground_events(text: str, events: list[dict]) -> list[dict]:
    """Drop a claim that does not quote the line it came from."""
    folded = " ".join(text.lower().split())
    kept = []
    for event in events:
        evidence = " ".join(str(event.get("evidence") or "").lower().split())
        if not evidence or evidence not in folded:
            continue
        kind = event["kind"]
        if kind == "TOUCHDOWN":
            cues = ("touchdown", "plane", "he's in", "hes in", "six point", "end zone", "in there")
            if not any(cue in evidence for cue in cues):
                continue
            recap = "and a touchdown" in evidence and "for the touchdown" not in evidence and "here's the touchdown" not in evidence
            if recap or any(phrase in evidence for phrase in ("looking for", "need a touchdown", "if they", "if he")):
                event = {**event, "status": "uncertain"}
        if kind == "TIMEOUT":
            if not any(phrase in evidence for phrase in ("timeout", "time out", "time-out")):
                continue
            if any(phrase in evidence for phrase in ("remaining", "left", "timeouts", "time outs")):
                continue
        if kind == "QUARTER_END" and re.search(r"\bquarter\b", evidence) is None and "end of the half" not in evidence:
            continue
        if kind == "CHALLENGE" and not any(phrase in evidence for phrase in ("challenge", "under review")):
            continue
        if kind == "TWO_POINT_CONVERSION" and not any(phrase in evidence for phrase in ("for two", "two point", "two-point")):
            continue
        if kind == "OVERTIME" and "overtime" not in evidence:
            continue
        if kind == "TOUCHDOWN" and any(phrase in evidence for phrase in ("touchdown lead", "touchdown least", "in the touchdown")):
            event = {**event, "status": "uncertain"}
        if kind == "HALFTIME" and not any(phrase in evidence for phrase in ("halftime", "half time", "at the half")):
            continue
        if kind == "TWO_MINUTE_WARNING" and not ("two minute" in evidence and "warning" in evidence):
            continue
        if kind == "BREAK_DURATION_ANNOUNCED":
            if "back in" not in evidence:
                continue
            detail = str(event.get("detail") or "")
            if detail == "30" and "30" not in evidence and "thirty" not in evidence:
                continue
            if "warning" in evidence or "2000" in evidence:
                continue
        if kind == "BROADCAST_SIGNOFF" and not any(
            phrase in evidence for phrase in ("these messages", "be right back", "take a break", "after this")
        ):
            continue
        if kind == "PROGRAM_RETURN":
            if "back in" in evidence or not any(
                phrase in evidence for phrase in ("welcome back", "we're back", "we are back", "back here")
            ):
                continue
        if kind == "SCORE_UPDATE" and not any(word in evidence for word in _SCORE_WORDS):
            continue
        if kind == "INTERCEPTION" and "intercept" not in evidence:
            continue
        if kind == "FUMBLE_RECOVERY" and "fumble" not in evidence:
            continue
        if kind == "PUNT" and "punt" not in evidence:
            continue
        if kind == "KICKOFF" and "kick" not in evidence:
            continue
        if kind == "INJURY" and not any(phrase in evidence for phrase in ("injur", "hurt")):
            continue
        if kind in {"FIELD_GOAL_GOOD", "FIELD_GOAL_MISSED"} and "field goal" not in evidence:
            continue
        kept.append(event)
    return kept


class ModelReader:
    """One local model call per finished line. `replaces_phrases` skips the phrase list."""

    replaces_phrases = True
    facts: dict = {}
    errors: int = 0
    context: str = "none"
    last_infer_s: float = 0.0
    last_events: list = ()
    replay: dict | None = None

    def __call__(self, text: str, previous_text: str = "") -> list[dict]:
        self.facts = {}
        self.last_infer_s = 0.0
        if self.replay is not None:
            self.facts = dict(self.replay.get("facts") or {})
            self.last_infer_s = float(self.replay.get("infer_s") or 0.0)
            self.last_events = list(self.replay.get("events") or [])
            return self.last_events
        if not str(text or "").strip():
            self.last_events = []
            return []
        try:
            payload, self.last_infer_s = _ask(text, previous_text, self.context)
        except (OSError, json.JSONDecodeError, TimeoutError, urllib.error.URLError, ValueError):
            self.errors += 1
            self.last_events = []
            return []
        events, self.facts = events_from_payload(text, payload)
        self.last_events = events
        return events


def _ask(text: str, previous_text: str = "", ledger: str = "none") -> tuple[dict, float]:
    prompt = _PROMPT.format(
        kinds=", ".join(LIVE_KINDS),
        line=text.strip(),
        previous=(previous_text or "none").strip()[:180],
        ledger=(ledger or "none").strip()[:240],
    )
    body = json.dumps(
        {
            "model": MODEL,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "keep_alive": "2h",
            "options": {"temperature": 0, "num_predict": 220},
        }
    ).encode()
    request = urllib.request.Request(URL, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=90) as response:
        raw = json.loads(response.read().decode())
    payload = json.loads(raw.get("response") or "{}")
    if not isinstance(payload, dict):
        raise ValueError("model returned a non-object")
    return payload, float(raw.get("total_duration") or 0) / 1e9


def main() -> None:
    reader = ModelReader()
    for line in BENCH:
        events = reader(line)
        score = [event for event in events if event["kind"] == "SCORE_UPDATE"]
        shown = score or events
        print(line)
        print(" ", json.dumps(shown), reader.facts)
    print("errors", reader.errors)


if __name__ == "__main__":
    main()
