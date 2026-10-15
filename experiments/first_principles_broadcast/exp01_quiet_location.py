"""Where the quiet frame sits relative to a gold boundary.

This does not change the EXP-01 detector or its gate. It only locates the
minimum 10 ms frame in the half-second on either side of each boundary, and
it counts how often ordinary program windows reach -60 dB.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from experiments.broadcast_intelligence.batch1 import SR, commercials, coverage, load_catalog, read_span
from hush.audio import find_session, load_session

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "docs/ohush/research/FIRST_PRINCIPLES_BROADCAST_V2/EXP_01_MICRO_PRODUCTION_CUTS"
RECORDINGS = REPO / "recordings"
REDZONE = "hush_20260913_150934"
HOP = 480


def db_frames(audio: np.ndarray) -> np.ndarray:
    usable = (len(audio) // HOP) * HOP
    frames = audio[:usable].reshape(-1, HOP, 2).astype(np.float64)
    mono = np.mean(((frames[:, :, 0] + frames[:, :, 1]) * 0.5) ** 2, axis=1)
    return 20.0 * np.log10(np.sqrt(np.maximum(mono, 0.0)) + 1e-12)


def main() -> None:
    catalog = load_catalog()
    spans = coverage()
    rows = commercials(spans)
    sessions = {}
    for span in spans:
        sid = span["session"]
        if sid in sessions:
            continue
        folder = find_session(RECORDINGS, sid)
        info = catalog.get(sid, {})
        sessions[sid] = {
            "dir": folder,
            "meta": load_session(folder),
            "coverage": (float(span["from_seconds"]), float(span["to_seconds"])),
            "content": info.get("content_type") or "",
        }
    pods = {sid: [] for sid in sessions}
    for row in rows:
        pods[row["session"]].append((float(row["start_seconds"]), float(row["end_seconds"])))

    located = []
    for row in rows:
        sid = row["session"]
        if sessions[sid]["content"] != "sports" or sid == REDZONE:
            continue
        for kind, stamp in (("start", float(row["start_seconds"])), ("end", float(row["end_seconds"]))):
            try:
                audio = read_span(sessions[sid]["dir"], sessions[sid]["meta"], stamp - 0.5, stamp + 0.5)
            except RuntimeError:
                located.append({"kind": kind, "missing": True})
                continue
            values = db_frames(audio)
            if values.size < 80:
                located.append({"kind": kind, "missing": True})
                continue
            # Frame i covers [stamp-0.5 + i*0.01, ...).
            offset = (np.arange(values.size) + 0.5) * 0.01 - 0.5
            finite = np.isfinite(values)
            if not finite.any():
                located.append({"kind": kind, "missing": True})
                continue
            index = int(np.argmin(np.where(finite, values, 0.0)))
            before = values[(offset < 0) & finite]
            after = values[(offset >= 0) & finite]
            located.append({
                "kind": kind,
                "min_offset_s": round(float(offset[index]), 3),
                "min_db": round(float(values[index]), 2),
                "frames_le_m60_before": int(np.sum(before <= -60)),
                "frames_le_m60_after": int(np.sum(after <= -60)),
            })

    controls = []
    for sid, bag in sessions.items():
        if bag["content"] != "sports" or sid == REDZONE:
            continue
        cov0, cov1 = bag["coverage"]
        t = cov0 + 30.0
        while t + 0.5 < cov1:
            if any(start - 20 <= t <= end + 20 for start, end in pods[sid]):
                t += 30.0
                continue
            try:
                audio = read_span(bag["dir"], bag["meta"], t, t + 0.5)
            except RuntimeError:
                t += 30.0
                continue
            values = db_frames(audio)
            if np.isfinite(values).any():
                controls.append(float(np.min(values[np.isfinite(values)])))
            t += 30.0

    def pack(kind: str) -> dict:
        rows_here = [row for row in located if row.get("kind") == kind and not row.get("missing")]
        offsets = np.array([row["min_offset_s"] for row in rows_here])
        return {
            "n": len(rows_here),
            "min_before_boundary": int(np.sum(offsets < 0)),
            "min_after_boundary": int(np.sum(offsets >= 0)),
            "offset_p50": None if offsets.size == 0 else round(float(np.median(offsets)), 3),
            "le_m60_before": sum(1 for row in rows_here if row["frames_le_m60_before"] > 0),
            "le_m60_after": sum(1 for row in rows_here if row["frames_le_m60_after"] > 0),
            "le_m60_either": sum(1 for row in rows_here if row["frames_le_m60_before"] or row["frames_le_m60_after"]),
        }

    payload = {
        "starts": pack("start"),
        "ends": pack("end"),
        "program_half_seconds": {
            "n": len(controls),
            "min_db_p50": None if not controls else round(float(np.median(controls)), 2),
            "le_m60": sum(1 for value in controls if value <= -60),
        },
    }
    (OUT / "quiet_location.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
