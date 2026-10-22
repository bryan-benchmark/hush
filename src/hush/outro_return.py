"""Timing for an outro fingerprint, then the broadcaster.

This is a measurement of a path. It does not start a cover. The look opens
two minutes after the outro window has been heard. The broadcaster is the
locked return: a 30-second rolling max at or over 0.10. A show with no
enrolled booth does not enter the path. The look stops 180 seconds after it
opens if the booth has not arrived.
"""

from __future__ import annotations

from bisect import bisect_left
from collections import defaultdict

from hush.voice_floor import FLOOR, MEMORY_S

LOOK_S = 120.0
HORIZON_S = 180.0


def overlap(start: float, end: float, pods: list[tuple[float, float]]) -> float:
    total = 0.0
    for pod_start, pod_end in pods:
        lo = max(start, pod_start)
        hi = min(end, pod_end)
        if hi > lo:
            total += hi - lo
    return total


def union_seconds(
    spans: list[tuple[str, float, float]],
    pods: dict[str, list[tuple[float, float]]],
) -> dict:
    grouped: dict[str, list[list[float]]] = defaultdict(list)
    for session, start, end in spans:
        if end > start:
            grouped[session].append([start, end])
    commercial = program = 0.0
    for session, pieces in grouped.items():
        pieces.sort()
        merged: list[list[float]] = []
        for start, end in pieces:
            if not merged or start > merged[-1][1]:
                merged.append([start, end])
            else:
                merged[-1][1] = max(merged[-1][1], end)
        for start, end in merged:
            ad = overlap(start, end, pods.get(session, []))
            commercial += ad
            program += (end - start) - ad
    return {
        "commercial_s": round(commercial, 3),
        "program_s": round(program, 3),
        "broken": program > 0,
    }


def rolling_maxes(rows: list[dict]) -> list[float | None]:
    scores: list[float | None] = []
    kept: list[tuple[float, float]] = []
    for row in rows:
        t = float(row["t"])
        kept = [(old, score) for old, score in kept if t - old <= MEMORY_S]
        cosine = row.get("cosine")
        if cosine is not None:
            kept.append((t, float(cosine)))
        scores.append(None if not kept else max(score for _, score in kept))
    return scores


def region_at(pods: list[tuple[float, float]], t: float) -> str:
    for start, end in pods:
        if start <= t <= end:
            return "ad"
    return "game"


def _first_from(rows: list[dict], origin: float, ready) -> dict | None:
    times = [float(row["t"]) for row in rows]
    stop = origin + HORIZON_S
    for index in range(bisect_left(times, origin), len(rows)):
        if float(rows[index]["t"]) > stop:
            break
        if ready(index):
            return rows[index]
    return None


def describe_look(rows: list[dict], edges: list[tuple[float, float]], t: float, enrolled: bool) -> dict:
    """Where the two-minute look lands. ``t`` is when the outro window ends."""
    look_at = t + LOOK_S
    found = {
        "look_at": round(look_at, 3),
        "look_region": region_at(edges, look_at),
        "enrolled": enrolled,
        "floor_t": None,
        "floor_roll": None,
        "floor_region": None,
        "line_t": None,
        "line_region": None,
        "cover_end": None,
        "fail_open": False,
    }
    if not enrolled or not rows:
        return found
    floor = _first_from(
        rows,
        look_at,
        lambda index: rows[index].get("roll") is not None and rows[index]["roll"] >= FLOOR,
    )
    line = _first_from(rows, look_at, lambda index: bool(rows[index].get("booth_over_line")))
    if floor is None:
        found["cover_end"] = round(look_at + HORIZON_S, 3)
        found["fail_open"] = True
    else:
        found["floor_t"] = float(floor["t"])
        found["floor_roll"] = floor.get("roll")
        found["floor_region"] = region_at(edges, float(floor["t"]))
        found["cover_end"] = float(floor["t"])
    if line is not None:
        found["line_t"] = float(line["t"])
        found["line_region"] = region_at(edges, float(line["t"]))
    return found
