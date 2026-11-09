"""Place marked commercial starts on the free ESPN play feed.

The clock is the chunk wall time in session.json. Elapsed time skips holes,
so a start is not session start plus elapsed. The feed is the public ESPN
play list. An official timeout is not labeled as a commercial. A stoppage is
frozen when the game clock stays within 15 seconds and at least 75 seconds of
wall time pass before the next snap. 75 is the midpoint of the rulebook's
30-second timeout and its two-minute timeout. A gold start is on that event
when the wall times are within 180 seconds, the two-minute timeout plus one
minute. Nothing here chooses a cutoff or mutes.
"""

from __future__ import annotations

import csv
import json
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median

from experiments.ledger import RECORDINGS, ROOT, sha256_text
from tools.gpu_lab.ladder import pairs
from tools.gpu_lab.learning_net.data import BRIDGE, bridge_masks
from tools.gpu_lab.learning_net.game_sounds import _role
from tools.gpu_lab.learning_net.log import finish_probe, open_probe
from tools.gpu_lab.prepare import DATA_ROOT
from tools.gpu_lab.splits import CONTROL, HOLDOUTS

MODULE = Path(__file__)
PROBE_ID = "slot_align"
QUESTION = "Do the marked commercial starts land on a free play-feed stoppage, and which kind?"
SHAPE_FOLDER = "20261023T044314Z_gold_shape"
SHAPE_SHA256 = "99fb1e3626941ba770a5a64a54e11bafc79b7ee4240d75c9b756de954424b8cb"
EMPTY_SHOW_FOLDER = "20261023T123935Z_slot_align"
EMPTY_SHOW_SHA256 = "d6f32246ff067883f17d38980c96cde3abf14e48f2443eacb8d8e9f5d6efc5fd"
CATALOG_PATH = ROOT / "experiments" / "SESSION_CATALOG.csv"

MATCH_S = 180
SHORT_WALL_S = 75
HELD_CLOCK_S = 15
LOOKBACK_S = 4 * 3600
SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard?dates={date}"
PLAYS = "https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/events/{event}/competitions/{event}/plays?limit=400"

STOPPAGE_TYPES = frozenset(
    {
        "Official Timeout",
        "Timeout",
        "Two-minute warning",
        "End Period",
        "End of Half",
        "End of Game",
    }
)
NIGHT_SHOWS = frozenset({"mnf", "monday night football", "sunday night"})
NICKNAMES = {
    "patriots": "NE",
    "seahawks": "SEA",
    "cowboys": "DAL",
    "giants": "NYG",
    "falcons": "ATL",
    "packers": "GB",
    "bucs": "TB",
    "buccaneers": "TB",
    "browns": "CLE",
    "jets": "NYJ",
}


def _cited(root: Path) -> None:
    for folder, expected in ((SHAPE_FOLDER, SHAPE_SHA256), (EMPTY_SHOW_FOLDER, EMPTY_SHOW_SHA256)):
        path = root / "learning_net" / "probes" / folder / "result.json"
        digest = sha256_text(path.read_text(encoding="utf-8"))
        if digest != expected:
            raise RuntimeError(f"{folder} hash {digest} does not match {expected}")


def catalog_show(session: str) -> str:
    """Show name from the catalog. Early session files leave this field empty."""
    with CATALOG_PATH.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if row["session_id"] == session:
                return row["show"]
    raise RuntimeError(f"{session} is not in the session catalog")


def _parse(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise RuntimeError(f"clock {value} has no timezone")
    return parsed


def chunk_wall(chunks: list[dict], elapsed_s: float) -> datetime:
    """Wall time of an elapsed second, using the chunk that contains it."""
    ordered = sorted(chunks, key=lambda row: float(row["start_elapsed_seconds"]))
    for chunk in ordered:
        start = float(chunk["start_elapsed_seconds"])
        end = float(chunk["end_elapsed_seconds"])
        if start <= elapsed_s < end or (elapsed_s == end and chunk is ordered[-1]):
            return _parse(chunk["started_at"]) + timedelta(seconds=elapsed_s - start)
    raise RuntimeError(f"elapsed {elapsed_s} is not inside a chunk")


def parse_clock(value: str) -> int:
    minutes, seconds = value.split(":")
    return int(minutes) * 60 + int(seconds)


def stop_shape(kind: str, wall_delta_s: float | None, game_delta_s: float | None) -> str:
    if kind == "Two-minute warning":
        return "mandatory_two_minute"
    if kind == "End Period":
        return "mandatory_quarter_end"
    if kind == "End of Half":
        return "halftime"
    if kind == "End of Game":
        return "game_over"
    if wall_delta_s is None or game_delta_s is None:
        return "no_following_snap"
    if game_delta_s > HELD_CLOCK_S:
        return "clock_ran"
    if wall_delta_s < SHORT_WALL_S:
        return "short_stop"
    return "frozen_clock"


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def classify_plays(plays: list[dict]) -> list[dict]:
    rows = []
    for index, play in enumerate(plays):
        kind = play["type"]
        if kind not in STOPPAGE_TYPES:
            continue
        following = next((item for item in plays[index + 1 :] if item["type"] not in STOPPAGE_TYPES), None)
        wall_delta = None
        game_delta = None
        if following is not None and play.get("wall") is not None and following.get("wall") is not None:
            wall_delta = (following["wall"] - play["wall"]).total_seconds()
            if play.get("period") == following.get("period") and play.get("clock_s") is not None and following.get("clock_s") is not None:
                game_delta = play["clock_s"] - following["clock_s"]
        rows.append(
            {
                "kind": kind,
                "shape": stop_shape(kind, wall_delta, game_delta),
                "period": play.get("period"),
                "clock": play.get("clock"),
                "wall": play.get("wall"),
                "wall_to_next_snap_s": None if wall_delta is None else round(wall_delta, 3),
                "game_clock_to_next_snap_s": None if game_delta is None else round(game_delta, 3),
            }
        )
    return rows


def _night(when: datetime) -> bool:
    hour = when.astimezone(timezone.utc).hour
    return hour >= 23 or hour < 6


def _teams(show: str) -> tuple[str, str] | None:
    text = show.strip().lower()
    if " at " not in text:
        return None
    away, home = text.split(" at ", 1)
    away_abbr = NICKNAMES.get(away.strip())
    home_abbr = NICKNAMES.get(home.strip())
    if away_abbr is None or home_abbr is None:
        return None
    return away_abbr, home_abbr


def select_game(show: str, events: list[dict], recording_start: datetime, recording_end: datetime) -> dict:
    window0 = recording_start - timedelta(seconds=LOOKBACK_S)
    eligible = [event for event in events if window0 <= event["start"] <= recording_end]
    pair = _teams(show)
    if pair is not None:
        away, home = pair
        chosen = [event for event in eligible if event["away"] == away and event["home"] == home]
        reason = "team_names"
    elif show.strip().lower() in NIGHT_SHOWS:
        chosen = [event for event in eligible if _night(event["start"])]
        reason = "night_window"
    else:
        return {"status": "unmatched", "reason": "unnamed_show", "event_id": None, "name": None}
    if len(chosen) == 1:
        event = chosen[0]
        return {"status": "matched", "reason": reason, "event_id": event["id"], "name": event["name"], "start": event["start"]}
    if not chosen:
        return {"status": "unmatched", "reason": "no_event_in_window", "event_id": None, "name": None}
    return {"status": "unmatched", "reason": "several_events", "event_id": None, "name": None, "candidates": [event["name"] for event in chosen]}


def nearest(when: datetime, rows: list[dict], key: str = "wall") -> dict | None:
    usable = [row for row in rows if row.get(key) is not None]
    if not usable:
        return None
    row = min(usable, key=lambda item: abs((item[key] - when).total_seconds()))
    delta = (row[key] - when).total_seconds()
    return {"delta_s": round(delta, 3), "abs_delta_s": round(abs(delta), 3), "row": row}


def place_label(delta_s: float, shape: str) -> str:
    if abs(delta_s) > MATCH_S:
        return "beyond_180"
    return shape


def _get(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": "ohush-slot-align"})
    with urllib.request.urlopen(request, timeout=45) as response:
        return json.loads(response.read().decode("utf-8"))


def _scoreboard_events(dates: list[str]) -> list[dict]:
    events = []
    seen = set()
    for date in dates:
        doc = _get(SCOREBOARD.format(date=date))
        for event in doc.get("events", []):
            if event["id"] in seen:
                continue
            seen.add(event["id"])
            competitors = {row["homeAway"]: row["team"]["abbreviation"] for row in event["competitions"][0]["competitors"]}
            events.append(
                {
                    "id": event["id"],
                    "name": event.get("shortName"),
                    "start": _parse(event["date"]),
                    "away": competitors.get("away"),
                    "home": competitors.get("home"),
                }
            )
    return events


def _plays(event_id: str) -> list[dict]:
    doc = _get(PLAYS.format(event=event_id))
    if int(doc.get("count", len(doc["items"]))) != len(doc["items"]):
        raise RuntimeError(f"{event_id} returned {len(doc['items'])} of {doc.get('count')} plays")
    rows = []
    for item in doc["items"]:
        wall = item.get("wallclock")
        clock = (item.get("clock") or {}).get("displayValue")
        period = (item.get("period") or {}).get("number")
        rows.append(
            {
                "type": (item.get("type") or {}).get("text"),
                "wall": None if wall is None else _parse(wall),
                "clock": clock,
                "clock_s": None if clock is None else parse_clock(clock),
                "period": None if period is None else int(period),
            }
        )
    return rows


def _load_chunks(session: str) -> tuple[list[dict], list]:
    if session in HOLDOUTS:
        raise RuntimeError(f"{session} is sealed")
    matches = sorted(RECORDINGS.glob(f"*/{session}"))
    if len(matches) != 1:
        raise RuntimeError(f"expected one session directory for {session}, found {matches}")
    meta = json.loads((matches[0] / "session.json").read_text(encoding="utf-8"))
    return meta["chunks"], meta.get("gaps") or []


def _summarize(labels: list[str]) -> dict:
    keys = (
        "mandatory_two_minute",
        "mandatory_quarter_end",
        "halftime",
        "frozen_clock",
        "short_stop",
        "clock_ran",
        "no_following_snap",
        "game_over",
        "beyond_180",
    )
    return {key: labels.count(key) for key in keys}


def _session_row(session: str, commercials: list[tuple[float, float]], chunks: list[dict], gaps: list) -> dict:
    role = _role(session)
    show = ""
    recording_start = _parse(chunks[0]["started_at"])
    recording_end = _parse(chunks[-1]["ended_at"])
    base = {
        "session": session,
        "role": role,
        "commercial_n": len(commercials),
        "recording_start": _iso(recording_start),
        "recording_end": _iso(recording_end),
        "wall_gaps": gaps,
        "gold_edited": False,
    }
    if session in CONTROL:
        base.update({"feed_status": "skipped", "reason": "control_is_not_one_game"})
        return base
    show = catalog_show(session)
    dates = [recording_start.date().isoformat().replace("-", "")]
    if recording_start.hour >= 18:
        dates.append((recording_start.date() + timedelta(days=1)).isoformat().replace("-", ""))
    events = _scoreboard_events(dates)
    chosen = select_game(show, events, recording_start, recording_end)
    base.update({"show": show, "feed_status": chosen["status"], "reason": chosen["reason"], "event_id": chosen["event_id"], "event_name": chosen["name"]})
    if chosen["status"] != "matched":
        base["candidates"] = chosen.get("candidates", [])
        return base
    plays = _plays(chosen["event_id"])
    slots = classify_plays(plays)
    placed = []
    labels = []
    for start, _end in commercials:
        wall = chunk_wall(chunks, start)
        found = nearest(wall, slots)
        if found is None:
            label = "no_feed_event"
        else:
            label = place_label(found["delta_s"], found["row"]["shape"])
        labels.append(label)
        placed.append(
            {
                "start_s": round(start, 3),
                "wall": _iso(wall),
                "label": label,
                "delta_s": None if found is None else found["delta_s"],
                "feed_shape": None if found is None else found["row"]["shape"],
                "feed_kind": None if found is None else found["row"]["kind"],
                "feed_clock": None if found is None else found["row"]["clock"],
                "feed_period": None if found is None else found["row"]["period"],
            }
        )
    unmarked = []
    gold_walls = [chunk_wall(chunks, start) for start, _end in commercials]
    for slot in slots:
        if slot["shape"] not in {"frozen_clock", "mandatory_two_minute", "mandatory_quarter_end", "halftime"}:
            continue
        if slot["wall"] is None:
            continue
        found = nearest(slot["wall"], [{"wall": wall} for wall in gold_walls])
        delta = None if found is None else found["delta_s"]
        if delta is None or abs(delta) > MATCH_S:
            unmarked.append(
                {
                    "shape": slot["shape"],
                    "kind": slot["kind"],
                    "period": slot["period"],
                    "clock": slot["clock"],
                    "wall": _iso(slot["wall"]),
                    "nearest_gold_delta_s": delta,
                }
            )
    deltas = [row["delta_s"] for row in placed if row["delta_s"] is not None]
    base.update(
        {
            "feed_event_n": len(plays),
            "slot_n": len(slots),
            "placement": _summarize(labels),
            "median_abs_delta_s": None if not deltas else round(median(abs(value) for value in deltas), 3),
            "breaks": placed,
            "unmarked_slots": unmarked,
        }
    )
    return base


def run(root: Path = DATA_ROOT) -> dict:
    parameters = {
        "clock": "chunk started_at plus the offset into that chunk",
        "match_s": MATCH_S,
        "short_wall_s": SHORT_WALL_S,
        "held_clock_s": HELD_CLOCK_S,
        "lookback_s": LOOKBACK_S,
        "feed": "ESPN public scoreboard and plays, no key",
        "show_source": "experiments/SESSION_CATALOG.csv",
        "corrects_probe": {"probe_id": PROBE_ID, "folder": EMPTY_SHOW_FOLDER, "result_sha256": EMPTY_SHOW_SHA256, "reason": "session.json show is empty on the four early tapes"},
        "october_may_choose_cutoff": False,
        "gold_edited": False,
        "live_mute_changed": False,
        "compared_with": {"probe_id": "gold_shape", "folder": SHAPE_FOLDER, "result_sha256": SHAPE_SHA256},
    }
    folder = open_probe(PROBE_ID, QUESTION, parameters, MODULE)
    _cited(root)
    masks = bridge_masks()
    rows = []
    for session in BRIDGE:
        if session in HOLDOUTS:
            raise RuntimeError(f"{session} is sealed")
        chunks, gaps = _load_chunks(session)
        commercials = pairs(masks[session], "verified_commercial")
        row = _session_row(session, commercials, chunks, gaps)
        rows.append(row)
        print(
            f"  {session} {row.get('feed_status')} {row.get('event_name')} {row.get('placement', row.get('reason'))}",
            flush=True,
        )
    result = {
        "probe_id": PROBE_ID,
        "rows": rows,
        "gold_edited": False,
        "october_may_choose_cutoff": False,
        "live_mute_changed": False,
        "gold_shape_result_sha256": SHAPE_SHA256,
        "corrects_empty_show_sha256": EMPTY_SHOW_SHA256,
    }
    finish_probe(folder, PROBE_ID, QUESTION, parameters, result, MODULE)
    return result
