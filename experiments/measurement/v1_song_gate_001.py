"""Keep a high fingerprint only while the song is still playing.

Count 150 was read off this ledger and is not a line. The song line, music
at or above 0.70, is already published. This does not mute.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "docs/ohush/research/V1_SONG_GATE_001"
COMMERCIAL_S = 17648.4
SONG = 0.70


def load() -> tuple[dict, dict, dict]:
    pods: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for line in (REPO / "docs/ohush/research/START_END_001/receipts.jsonl").read_text().splitlines():
        if line.strip():
            row = json.loads(line)
            pods[row["session"]].append((float(row["start"]), float(row["end"])))
    decisions: dict[str, list[dict]] = defaultdict(list)
    for line in (REPO / "docs/ohush/research/UNIVERSAL_V1/decisions.jsonl").read_text().splitlines():
        if line.strip():
            row = json.loads(line)
            if row.get("content") != "scripted" and row["session"] in pods:
                decisions[row["session"]].append(row)
    music: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for line in (REPO / "docs/ohush/research/BREAK_TRACE_001/decisions.jsonl").read_text().splitlines():
        if line.strip():
            row = json.loads(line)
            if row["session"] in pods and row.get("music") is not None:
                music[row["session"]].append((float(row["t"]), float(row["music"])))
    for rows in decisions.values():
        rows.sort(key=lambda row: row["available_at"])
    for rows in music.values():
        rows.sort()
    return pods, decisions, music


def music_at(track: list[tuple[float, float]], t: float) -> float | None:
    found = None
    for when, level in track:
        if when <= t + 0.5:
            found = level
        else:
            break
    return found


def covers_for(rows: list[dict], track: list[tuple[float, float]], count: int, require_song: bool) -> list[tuple[float, float]]:
    spans = []
    for index, row in enumerate(rows):
        start = float(row["available_at"])
        end = float(rows[index + 1]["available_at"]) if index + 1 < len(rows) else start
        if row["score"] < count or row.get("same_session"):
            continue
        if require_song:
            level = music_at(track, start)
            if level is None or level < SONG:
                continue
        spans.append((start, end))
    return spans


def accounted(pods: dict, decisions: dict, music: dict, count: int, require_song: bool) -> dict:
    commercial = 0.0
    program = 0.0
    incidents = 0
    pods_hit = 0
    for session, rows in decisions.items():
        covers = covers_for(rows, music.get(session, []), count, require_song)
        here = pods[session]
        for start, end in here:
            inside = 0.0
            for left, right in covers:
                lo, hi = max(left, start), min(right, end)
                if hi > lo:
                    inside += hi - lo
            commercial += inside
            if inside > 0:
                pods_hit += 1
        for left, right in covers:
            cursor = left
            for start, end in sorted(here):
                if end <= cursor or start >= right:
                    continue
                if start > cursor:
                    program += min(start, right) - cursor
                    incidents += 1
                cursor = max(cursor, end)
            if cursor < right:
                program += right - cursor
                incidents += 1
    broken = program > 0
    return {
        "count": count,
        "require_song": require_song,
        "commercial_s": round(commercial, 3),
        "program_s": round(program, 3),
        "incidents": incidents,
        "pods_hit": pods_hit,
        "broken": broken,
        "percentage": None if broken else round(100.0 * commercial / COMMERCIAL_S, 3),
    }


def main() -> None:
    pods, decisions, music = load()
    lines = [
        accounted(pods, decisions, music, 200, False),
        accounted(pods, decisions, music, 150, False),
        accounted(pods, decisions, music, 150, True),
        accounted(pods, decisions, music, 200, True),
    ]
    payload = {
        "system": "v1_song_gate_001",
        "mute_policy": False,
        "installed": False,
        "song": SONG,
        "note": "Count 150 was read off this ledger. The song line was already published. A cover step counts only when both are true.",
        "lines": lines,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
