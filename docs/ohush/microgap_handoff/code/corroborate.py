"""Independent -80 dB check and a format receipt for the three closed sessions.

ffmpeg is not installed on this machine, so this is not an ffmpeg log.
The rule is the one the handoff named for a coarse check, implemented in
NumPy: 30 ms RMS at or below -80 dBFS, kept when the run lasts at least
30 ms. One setting. It is not selected as a mute threshold.

The 5 ms census is not rerun and not retuned.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import soundfile as sf

from experiments.broadcast_intelligence.batch1 import RECORDINGS, commercials, coverage, read_span
from experiments.microgap_census.scan import CLOSED, EDGE_S, PROGRAM_CLEAR_S, WITHIN_CLEAR_S, near
from hush.audio import find_session, load_session

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "docs/ohush/research/MICROGAP_CENSUS_001"
SR = 48000
WIN_S = 0.03
WIN = int(SR * WIN_S)
THRESHOLD_DB = -80.0


def window_db(audio: np.ndarray) -> np.ndarray:
    usable = (len(audio) // WIN) * WIN
    if usable < WIN:
        return np.empty(0, dtype=np.float64)
    paired = audio[:usable].astype(np.float64).reshape(-1, WIN, audio.shape[1])
    mono = paired.mean(axis=2)
    rms = np.sqrt(np.mean(mono * mono, axis=1))
    return 20.0 * np.log10(np.maximum(rms, 1e-12))


def runs(levels: np.ndarray, t0: float) -> list[dict]:
    below = levels <= THRESHOLD_DB
    if not np.any(below):
        return []
    padded = np.concatenate(([False], below, [False]))
    changes = np.diff(padded.astype(np.int8))
    starts = np.flatnonzero(changes == 1)
    ends = np.flatnonzero(changes == -1)
    return [
        {
            "start": round(t0 + int(start) * WIN_S, 3),
            "end": round(t0 + int(end) * WIN_S, 3),
            "duration": round((int(end) - int(start)) * WIN_S, 3),
        }
        for start, end in zip(starts, ends)
    ]


def format_rows(session: str, t0: float, t1: float) -> dict:
    folder = find_session(RECORDINGS, session)
    meta = load_session(folder)
    rows = []
    for chunk in meta["chunks"]:
        c0 = float(chunk["start_elapsed_seconds"])
        c1 = float(chunk["end_elapsed_seconds"])
        if c1 <= t0 or c0 >= t1:
            continue
        path = folder / chunk["file"]
        info = sf.info(str(path))
        expected = int(round((c1 - c0) * SR))
        rows.append(
            {
                "file": chunk["file"],
                "start_s": c0,
                "end_s": c1,
                "samplerate": info.samplerate,
                "channels": info.channels,
                "subtype": info.subtype,
                "frames": info.frames,
                "expected_frames_from_session_json": expected,
                "frame_delta": int(info.frames) - expected,
            }
        )
    bad = [row for row in rows if row["samplerate"] != SR or row["channels"] != 2 or abs(row["frame_delta"]) > 2]
    return {
        "session": session,
        "sample_rate_hz": meta["sample_rate_hz"],
        "channels": meta["channels"],
        "chunks_overlapping_closed_coverage": len(rows),
        "chunks_in_session": len(meta["chunks"]),
        "format_ok": not bad,
        "mismatches": bad,
        "chunks": rows,
    }


def main() -> None:
    spans = [span for span in coverage() if span["session"] in CLOSED]
    pods_by: dict[str, list] = {}
    for row in commercials(spans):
        pods_by.setdefault(row["session"], []).append((float(row["start_seconds"]), float(row["end_seconds"])))
    formats = []
    scored = []
    for session in CLOSED:
        span = next(row for row in spans if row["session"] == session)
        t0, t1 = float(span["from_seconds"]), float(span["to_seconds"])
        print(f"format+silence {session}", flush=True)
        formats.append(format_rows(session, t0, t1))
        folder = find_session(RECORDINGS, session)
        meta = load_session(folder)
        parts = []
        cursor = t0
        while cursor < t1 - 1e-6:
            stop = min(t1, cursor + 30.0)
            parts.append(window_db(read_span(folder, meta, cursor, stop)))
            cursor = stop
        levels = np.concatenate(parts)
        events = [event for event in runs(levels, t0) if event["start"] >= t0 + EDGE_S and event["end"] <= t1 - EDGE_S]
        pods = pods_by.get(session, [])
        commercial = sum(end - start for start, end in pods)
        program = (t1 - t0) - commercial
        program_events = []
        within_events = []
        for event in events:
            mid = 0.5 * (event["start"] + event["end"])
            if any(start + WITHIN_CLEAR_S <= mid <= end - WITHIN_CLEAR_S for start, end in pods):
                within_events.append(event)
            elif all(mid < start - PROGRAM_CLEAR_S or mid > end + PROGRAM_CLEAR_S for start, end in pods):
                program_events.append(event)
        recall = {}
        for window in (0.25, 0.5, 1.0, 2.0, 5.0):
            recall[str(window)] = {
                "starts_descriptive": sum(near(start, events, window, False) for start, _end in pods),
                "starts_causal": sum(near(start, events, window, True) for start, _end in pods),
                "ends_descriptive": sum(near(end, events, window, False) for _start, end in pods),
                "ends_causal": sum(near(end, events, window, True) for _start, end in pods),
            }
        scored.append(
            {
                "session": session,
                "threshold_db": THRESHOLD_DB,
                "window_s": WIN_S,
                "minimum_duration_s": WIN_S,
                "events": len(events),
                "program_events_per_hour": round(len(program_events) / (program / 3600.0), 2) if program else None,
                "within_break_per_hour": round(len(within_events) / (commercial / 3600.0), 2) if commercial else None,
                "starts": len(pods),
                "recall": recall,
            }
        )
        print(f"  events {len(events)} program/h {scored[-1]['program_events_per_hour']}", flush=True)
    payload = {
        "system": "microgap_corroboration_001",
        "ffmpeg_binary": None,
        "ffmpeg_note": "ffmpeg was not on PATH. This is a separate 30 ms RMS run at -80 dBFS, the coarse setting named in the handoff. It is not an ffmpeg log and not a selected threshold.",
        "mute_policy": False,
        "october_used": False,
        "holdouts_opened": False,
        "formats": formats,
        "silence": scored,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "corroboration.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT / 'corroboration.json'}", flush=True)


if __name__ == "__main__":
    main()
