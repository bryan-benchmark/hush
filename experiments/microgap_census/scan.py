"""Absolute near-silence census. Not a mute, and not a retune of Exp001.

Exp001 already scored the 2018 relative short-dip (loud, brief hole, loud
again) and that gate was NOT_MET. This scan asks a different question on
three closed recordings only: how deep is the 5 ms floor, and how often
does an absolute dBFS run sit on a gold boundary versus in the program.

The threshold grid is fixed before the recordings are scored. No row is
selected as an operating point. Holdouts are refused by the gold reader.
October is not read.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from experiments.broadcast_intelligence.batch1 import (
    RECORDINGS,
    commercials,
    coverage,
    load_catalog,
    read_span,
)
from hush.audio import find_session, load_session

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "docs/ohush/research/MICROGAP_CENSUS_001"
SR = 48000
WIN_S = 0.005
WIN = int(SR * WIN_S)
THRESHOLDS_DB = (-120.0, -100.0, -85.0, -70.0, -55.0, -40.0)
WINDOWS_S = (0.25, 0.5, 1.0, 2.0, 5.0)
CLOSED = (
    "hush_20260827_135935",
    "hush_20260914_212529",
    "hush_20260924_220624",
)
EDGE_S = 2.0
PROGRAM_CLEAR_S = 2.0
WITHIN_CLEAR_S = 1.0


def window_db(audio: np.ndarray) -> np.ndarray:
    """5 ms RMS of the two channels averaged, in dBFS. True zero is about -240."""
    usable = (len(audio) // WIN) * WIN
    if usable < WIN:
        return np.empty(0, dtype=np.float64)
    paired = audio[:usable].astype(np.float64).reshape(-1, WIN, audio.shape[1])
    mono = paired.mean(axis=2)
    rms = np.sqrt(np.mean(mono * mono, axis=1))
    return 20.0 * np.log10(np.maximum(rms, 1e-12))


def runs_from_db(levels: np.ndarray, t0: float, threshold: float) -> list[dict]:
    below = levels <= threshold
    if not np.any(below):
        return []
    padded = np.concatenate(([False], below, [False]))
    changes = np.diff(padded.astype(np.int8))
    starts = np.flatnonzero(changes == 1)
    ends = np.flatnonzero(changes == -1)
    events = []
    for start, end in zip(starts, ends):
        events.append(
            {
                "start": round(t0 + start * WIN_S, 3),
                "end": round(t0 + end * WIN_S, 3),
                "duration": round((end - start) * WIN_S, 3),
                "floor_db": round(float(levels[start:end].min()), 1),
            }
        )
    return events


def near(moment: float, events: list[dict], window: float, causal: bool) -> bool:
    for event in events:
        if causal:
            if moment <= event["end"] <= moment + window:
                return True
        elif event["start"] <= moment + window and event["end"] >= moment - window:
            return True
    return False


def score_session(levels: np.ndarray, t0: float, t1: float, pods: list[tuple], seams: list[float]) -> dict:
    duration = t1 - t0
    commercial = sum(end - start for start, end in pods)
    program = duration - commercial
    grid = np.arange(t0 + EDGE_S, t1 - EDGE_S, 30.0)
    program_grid = [
        float(t)
        for t in grid
        if all(t < start - PROGRAM_CLEAR_S or t > end + PROGRAM_CLEAR_S for start, end in pods)
    ]
    boundary_floor = []
    for start, _end in pods:
        i0 = int(round((start - 0.25 - t0) / WIN_S))
        i1 = int(round((start + 0.25 - t0) / WIN_S))
        i0 = max(0, i0)
        i1 = min(len(levels), i1)
        if i1 > i0:
            boundary_floor.append(float(levels[i0:i1].min()))
    program_floor = []
    for moment in program_grid:
        i0 = int(round((moment - t0) / WIN_S))
        i1 = min(len(levels), i0 + int(0.5 / WIN_S))
        if i1 > i0 >= 0:
            program_floor.append(float(levels[i0:i1].min()))
    by_threshold = []
    for threshold in THRESHOLDS_DB:
        events = [
            event
            for event in runs_from_db(levels, t0, threshold)
            if event["start"] >= t0 + EDGE_S and event["end"] <= t1 - EDGE_S
        ]
        program_events = []
        within_events = []
        seam_events = []
        for event in events:
            mid = 0.5 * (event["start"] + event["end"])
            on_seam = any(abs(mid - seam) <= 0.05 for seam in seams)
            if on_seam:
                seam_events.append(event)
            if any(start + WITHIN_CLEAR_S <= mid <= end - WITHIN_CLEAR_S for start, end in pods):
                within_events.append(event)
            elif all(mid < start - PROGRAM_CLEAR_S or mid > end + PROGRAM_CLEAR_S for start, end in pods):
                program_events.append(event)
        recall = {}
        for window in WINDOWS_S:
            recall[str(window)] = {
                "starts_descriptive": sum(near(start, events, window, False) for start, _end in pods),
                "starts_causal": sum(near(start, events, window, True) for start, _end in pods),
                "ends_descriptive": sum(near(end, events, window, False) for _start, end in pods),
                "ends_causal": sum(near(end, events, window, True) for _start, end in pods),
            }
        by_threshold.append(
            {
                "threshold_db": threshold,
                "events": len(events),
                "program_events": len(program_events),
                "program_events_per_hour": round(len(program_events) / (program / 3600.0), 2) if program else None,
                "within_break_events": len(within_events),
                "within_break_per_hour": round(len(within_events) / (commercial / 3600.0), 2) if commercial else None,
                "chunk_seam_events": len(seam_events),
                "median_duration_s": round(float(np.median([event["duration"] for event in events])), 3) if events else None,
                "starts": len(pods),
                "recall": recall,
            }
        )
    return {
        "coverage_s": round(duration, 3),
        "commercial_s": round(commercial, 3),
        "program_s": round(program, 3),
        "pods": len(pods),
        "boundary_min_5ms_db": _spread(boundary_floor),
        "program_min_5ms_db": _spread(program_floor),
        "program_grid_n": len(program_floor),
        "thresholds": by_threshold,
    }


def _spread(values: list[float]) -> dict:
    if not values:
        return {"n": 0}
    arr = np.asarray(values, dtype=np.float64)
    return {
        "n": int(arr.size),
        "median": round(float(np.median(arr)), 1),
        "p10": round(float(np.percentile(arr, 10)), 1),
        "p90": round(float(np.percentile(arr, 90)), 1),
    }


def load_levels(session: str, t0: float, t1: float) -> tuple[np.ndarray, list[float]]:
    folder = find_session(RECORDINGS, session)
    meta = load_session(folder)
    seams = []
    for chunk in meta["chunks"]:
        edge = float(chunk["start_elapsed_seconds"])
        if t0 + 1.0 < edge < t1 - 1.0:
            seams.append(edge)
    parts = []
    cursor = t0
    while cursor < t1 - 1e-6:
        stop = min(t1, cursor + 30.0)
        audio = read_span(folder, meta, cursor, stop)
        parts.append(window_db(audio))
        cursor = stop
    return np.concatenate(parts), seams


def main() -> None:
    catalog = load_catalog()
    spans = [span for span in coverage() if span["session"] in CLOSED]
    pods_by = {}
    for row in commercials(spans):
        if row["session"] not in CLOSED:
            continue
        pods_by.setdefault(row["session"], []).append((float(row["start_seconds"]), float(row["end_seconds"])))
    found = {span["session"] for span in spans}
    missing = [session for session in CLOSED if session not in found]
    if missing:
        raise SystemExit(f"closed coverage missing: {missing}")
    sessions = []
    for session in CLOSED:
        span = next(row for row in spans if row["session"] == session)
        t0, t1 = float(span["from_seconds"]), float(span["to_seconds"])
        info = catalog.get(session, {})
        print(f"reading {session} {t0:.0f}-{t1:.0f}", flush=True)
        levels, seams = load_levels(session, t0, t1)
        scored = score_session(levels, t0, t1, pods_by.get(session, []), seams)
        scored.update(
            {
                "session": session,
                "service": info.get("network_or_service") or "unknown",
                "program": info.get("program") or info.get("show") or "",
                "from_s": t0,
                "to_s": t1,
                "chunk_seams_inside": len(seams),
            }
        )
        sessions.append(scored)
        print(f"  pods {scored['pods']} program floor {scored['program_min_5ms_db']}", flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    payload = {
        "system": "microgap_census_001",
        "mute_policy": False,
        "retunes_exp001": False,
        "october_used": False,
        "holdouts_opened": False,
        "window_s": WIN_S,
        "thresholds_db": list(THRESHOLDS_DB),
        "sessions": sessions,
        "note": "Descriptive overlap can see both sides of a label. Causal credit requires the silence run to finish after the label. No threshold is an operating point.",
    }
    (OUT / "results.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT / 'results.json'}", flush=True)


if __name__ == "__main__":
    main()
