"""Align nflverse play-by-play to the two Prime recordings.

The game clock is not the recording clock. A play is given an audio time
only when the transcript states something that identifies that play.
Everything else stays unaligned. No model is trained. Gold is read after
the alignment, only to see whether a placed play sat before a commercial.

    python -m experiments.nfl75.pbp_align
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from experiments.measurement.metrics import target_commercials
from experiments.nfl75.event_asr import SCOPE
from experiments.nfl75.inventory import active_intervals

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "docs" / "ohush" / "research" / "NFL_PBP_ALIGNMENT_001"
PBP = OUT / "_pbp_2026.csv"
LEDGER = REPO / "docs" / "ohush" / "research" / "NFL_GPU_BRAIN_001" / "football_events.jsonl"
GROUNDED = REPO / "docs" / "ohush" / "research" / "NFL_EVENT_GROUNDING_002F" / "football_events.jsonl"

GAMES = {
    "hush_20261008_205100": {
        "game_id": "2026_05_TB_DAL",
        "label": "Buccaneers at Cowboys",
        "date": "2026-10-08",
        "away": "TB",
        "home": "DAL",
        "show": "Prime Video",
    },
    "hush_20260924_220624": {
        "game_id": "2026_03_ATL_GB",
        "label": "Falcons at Packers",
        "date": "2026-09-24",
        "away": "ATL",
        "home": "GB",
        "show": "Prime Video",
    },
}

# Audio times are recording seconds. Each note says why the play is that moment.
ANCHORS = {
    "hush_20261008_205100": [
        {
            "play_key": "Q1-653-TOUCHDOWN",
            "audio_t": 105.0,
            "confidence": "high",
            "evidence": "Opening-drive touchdown at 105s, before the 51-minute capture gap. First score of the game is J.Williams.",
        },
        {
            "play_key": "Q2-26-FIELD_GOAL_GOOD",
            "audio_t": 2655.0,
            "confidence": "high",
            "evidence": "Transcript at 2655s: 41-yard attempt for Aubrey. That is the only 41-yard Aubrey field goal, and it makes the score 10-7 Dallas.",
        },
        {
            "play_key": "Q3-455-TOUCHDOWN",
            "audio_t": 4790.0,
            "confidence": "high",
            "evidence": "Transcript says Irving for a touchdown at 4790s, which is after the 10-7 field goal. The only Irving touchdown after that score is the third-quarter run.",
        },
    ],
    "hush_20260924_220624": [
        {
            "play_key": "Q3-221-TOUCHDOWN",
            "audio_t": 3390.0,
            "confidence": "medium",
            "evidence": "Robinson for a touchdown at 3390s, and the fourth quarter is not announced until 5035s. The third-quarter scoring run is the Robinson touchdown.",
        }
    ],
}


def _clock(seconds: str) -> str:
    value = int(float(seconds or 0))
    return f"{value // 60:02d}:{value % 60:02d}"


def _kind(row: dict) -> str | None:
    if row.get("touchdown") == "1":
        return "TOUCHDOWN"
    if row.get("field_goal_result") == "made":
        return "FIELD_GOAL_GOOD"
    if row.get("field_goal_result") == "missed":
        return "FIELD_GOAL_MISSED"
    if row.get("extra_point_result") == "good":
        return "EXTRA_POINT"
    if row.get("interception") == "1":
        return "INTERCEPTION"
    if row.get("fumble_lost") == "1":
        return "FUMBLE_LOST"
    if row.get("punt_attempt") == "1":
        return "PUNT"
    if row.get("timeout") == "1":
        return "TIMEOUT"
    if "TWO-POINT CONVERSION ATTEMPT" in (row.get("desc") or ""):
        return "TWO_POINT"
    return None


def _play_key(row: dict, kind: str) -> str:
    clock = int(float(row["quarter_seconds_remaining"] or 0))
    return f"Q{row['qtr']}-{clock}-{kind}"


def load_events() -> dict[str, list[dict]]:
    by_game = {meta["game_id"]: [] for meta in GAMES.values()}
    with PBP.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["game_id"] not in by_game:
                continue
            kind = _kind(row)
            if kind is None:
                continue
            by_game[row["game_id"]].append(
                {
                    "game_id": row["game_id"],
                    "play_key": _play_key(row, kind),
                    "kind": kind,
                    "quarter": int(row["qtr"]),
                    "clock": _clock(row["quarter_seconds_remaining"]),
                    "seconds_remaining": int(float(row["quarter_seconds_remaining"] or 0)),
                    "away_score": int(float(row["total_away_score"] or 0)),
                    "home_score": int(float(row["total_home_score"] or 0)),
                    "description": (row.get("desc") or "").strip(),
                }
            )
    return by_game


def _predictions(path: Path, session: str) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("session") == session and row.get("kind") == "TOUCHDOWN" and row.get("status") == "live":
            rows.append(row)
    return rows


def _near(predictions: list[dict], audio_t: float, window: float = 90.0) -> list[dict]:
    return [row for row in predictions if abs(float(row["audio_t"]) - audio_t) <= window]


def _commercials(session: str) -> list[tuple[float, float]]:
    scope = SCOPE[session]
    intervals = [row for row in active_intervals(session) if row.end > scope[0] and row.start < scope[1]]
    return [
        (max(start, scope[0]), min(end, scope[1]))
        for start, end in target_commercials(intervals)
        if start < scope[1] and end > scope[0] and min(end, scope[1]) - max(start, scope[0]) > 1.0
    ]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    events = load_events()
    ledger = []
    summary = []
    for session, meta in GAMES.items():
        plays = events[meta["game_id"]]
        anchors = {row["play_key"]: row for row in ANCHORS[session]}
        placed = []
        for play in plays:
            anchor = anchors.get(play["play_key"])
            item = dict(play)
            if anchor:
                item.update({"audio_t": anchor["audio_t"], "alignment": anchor["confidence"], "alignment_evidence": anchor["evidence"]})
            else:
                item.update({"audio_t": None, "alignment": "unaligned", "alignment_evidence": ""})
            item["session"] = session
            placed.append(item)
        raw = _predictions(LEDGER, session)
        grounded_path = GROUNDED if GROUNDED.is_file() else None
        grounded = _predictions(grounded_path, session) if grounded_path else []
        high = [row for row in placed if row["kind"] == "TOUCHDOWN" and row["alignment"] == "high"]
        medium = [row for row in placed if row["kind"] == "TOUCHDOWN" and row["alignment"] == "medium"]
        matched_raw = []
        for play in high + medium:
            hits = _near(raw, play["audio_t"])
            matched_raw.append({"play_key": play["play_key"], "audio_t": play["audio_t"], "predictions": len(hits)})
        hit_ids = set()
        for play in high + medium:
            for row in _near(raw, play["audio_t"]):
                hit_ids.add(float(row["audio_t"]))
        commercials = _commercials(session)
        leads = []
        for play in placed:
            if play["audio_t"] is None or play["alignment"] == "unaligned":
                continue
            upcoming = [start for start, _end in commercials if play["audio_t"] <= start <= play["audio_t"] + 180]
            leads.append({"play_key": play["play_key"], "kind": play["kind"], "audio_t": play["audio_t"], "next_break_s": None if not upcoming else round(upcoming[0] - play["audio_t"], 1)})
        record = {
            "session": session,
            "game_id": meta["game_id"],
            "label": meta["label"],
            "pbp_touchdowns": sum(1 for row in plays if row["kind"] == "TOUCHDOWN"),
            "touchdowns_with_an_audio_time": len(high) + len(medium),
            "high_confidence": len(high),
            "medium_confidence": len(medium),
            "ungrounded_live_touchdown_predictions": len(raw),
            "predictions_within_90s_of_a_placed_touchdown": len(hit_ids),
            "placed_touchdowns_with_at_least_one_prediction": sum(1 for row in matched_raw if row["predictions"]),
            "grounded_live_touchdown_predictions": len(grounded),
            "grounded_within_90s": len({float(row["audio_t"]) for play in high + medium for row in _near(grounded, play["audio_t"])}),
            "plays": placed,
            "match": matched_raw,
            "commercial_lead_diagnostic": leads,
        }
        summary.append({key: value for key, value in record.items() if key != "plays"})
        ledger.extend(placed)
        print(session, "td", record["pbp_touchdowns"], "placed", record["touchdowns_with_an_audio_time"], "raw", len(raw), "near", len(hit_ids))
    (OUT / "plays.jsonl").write_text("".join(json.dumps(row) + "\n" for row in ledger), encoding="utf-8")
    (OUT / "summary.json").write_text(json.dumps({"source": "nflverse play_by_play_2026", "trained": False, "sessions": summary}, indent=2), encoding="utf-8")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
