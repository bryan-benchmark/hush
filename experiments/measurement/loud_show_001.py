"""Clips for the show seconds that already score like an ad.

Music and Speech, two NBC games only. A second is included when it is
entirely program, its lookback has no labeled commercial, and its score
is at or above that name's commercial median. Three seconds already
heard are left out. Neighbors within 8 seconds share one clip. Scores
stay in the key. The logger does not show them. Gold is not edited.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SOURCE = REPO / "docs" / "ohush" / "research" / "SUPERVISED_NAME_SCORES_001" / "results.json"
OUT = REPO / "docs" / "ohush" / "research" / "LOUD_SHOW_001"
PAD = 8.0
GAP = 8.0
HEARD = {
    ("hush_20260913_210542", 1020.0),
    ("hush_20260913_210542", 1124.0),
    ("hush_20260913_210542", 11133.0),
}
NAMES = {
    "hush_20260909_213047": "Sept 9 NBC",
    "hush_20260913_210542": "Sept 13 NBC",
}


def main() -> None:
    payload = json.loads(SOURCE.read_text(encoding="utf-8"))
    rows = []
    for name in ("Music", "Speech"):
        for row in payload["names"][name]["show_seconds_at_or_above_commercial_median"]:
            key = (row["session"], float(row["t"]))
            if key in HEARD:
                continue
            rows.append({**row, "name": name, "t": float(row["t"])})
    rows.sort(key=lambda row: (row["session"], row["t"]))
    clusters: list[list[dict]] = []
    for row in rows:
        if clusters and row["session"] == clusters[-1][-1]["session"] and row["t"] - clusters[-1][-1]["t"] <= GAP:
            clusters[-1].append(row)
        else:
            clusters.append([row])
    clusters.sort(key=lambda group: max(float(row["score"]) for row in group), reverse=True)
    queue = []
    key = []
    for group in clusters:
        loudest = max(group, key=lambda row: float(row["score"]))
        start = max(0.0, min(float(row["t"]) for row in group) - PAD)
        end = max(float(row["t"]) for row in group) + PAD
        game = NAMES.get(loudest["session"], loudest["session"])
        clip_id = f"{loudest['session']}:{loudest['t']:.0f}"
        queue.append(
            {
                "id": clip_id,
                "session": loudest["session"],
                "play_start": round(start, 3),
                "duration": round(end - start, 3),
                "mark_s": round(float(loudest["t"]) - start, 3),
                "caption": f"{game}. The green line is the moment. What is playing, and would you leave it on?",
            }
        )
        key.append(
            {
                "id": clip_id,
                "seconds": [
                    {"t": row["t"], "name": row["name"], "score": row["score"]}
                    for row in group
                ],
            }
        )
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "queue.jsonl").write_text("".join(json.dumps(row) + "\n" for row in queue), encoding="utf-8")
    (OUT / "key.jsonl").write_text("".join(json.dumps(row) + "\n" for row in key), encoding="utf-8")
    print(json.dumps({"clips": len(queue), "seconds": len(rows), "first": queue[0]["id"]}), flush=True)


if __name__ == "__main__":
    main()
