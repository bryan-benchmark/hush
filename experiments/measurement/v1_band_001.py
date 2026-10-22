"""What a lower fingerprint count would cover on the frozen queries.

Count 200 is the published line. 150 and 100 are read off this same ledger
after the fact. They are not a new line, and this does not mute.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "docs/ohush/research/V1_BAND_001"
COMMERCIAL_S = 17648.4
LINES = (200, 150, 100)


def load() -> tuple[dict[str, list[tuple[float, float]]], dict[str, list[dict]]]:
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
    for rows in decisions.values():
        rows.sort(key=lambda row: row["available_at"])
    return pods, decisions


def overlap(spans: list[tuple[float, float]], window: tuple[float, float]) -> float:
    total = 0.0
    left, right = window
    for start, end in spans:
        lo, hi = max(start, left), min(end, right)
        if hi > lo:
            total += hi - lo
    return total


def covers_for(rows: list[dict], count: int) -> list[tuple[float, float]]:
    spans = []
    for index, row in enumerate(rows):
        start = float(row["available_at"])
        end = float(rows[index + 1]["available_at"]) if index + 1 < len(rows) else start
        if row["score"] >= count and not row.get("same_session"):
            spans.append((start, end))
    return spans


def main() -> None:
    pods, decisions = load()
    summary = []
    for count in LINES:
        commercial = 0.0
        program = 0.0
        incidents = 0
        pods_hit = 0
        for session, rows in decisions.items():
            covers = covers_for(rows, count)
            if not covers:
                continue
            here = pods[session]
            for start, end in here:
                inside = overlap(covers, (start, end))
                commercial += inside
                if inside > 0:
                    pods_hit += 1
            for start, end in covers:
                cursor = start
                for pod_start, pod_end in sorted(here):
                    if pod_end <= cursor or pod_start >= end:
                        continue
                    if pod_start > cursor:
                        program += min(pod_start, end) - cursor
                        incidents += 1
                    cursor = max(cursor, pod_end)
                if cursor < end:
                    program += end - cursor
                    incidents += 1
        broken = program > 0
        summary.append(
            {
                "count": count,
                "published": count == 200,
                "commercial_s": round(commercial, 3),
                "program_s": round(program, 3),
                "incidents": incidents,
                "pods_hit": pods_hit,
                "broken": broken,
                "percentage": None if broken else round(100.0 * commercial / COMMERCIAL_S, 3),
            }
        )
    payload = {
        "system": "v1_band_001",
        "mute_policy": False,
        "installed": False,
        "note": "150 and 100 were read off this ledger. They were not a predeclared line.",
        "lines": summary,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
