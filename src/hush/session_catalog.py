"""Permanent session catalog and one middle listening clip per dev session.

Holdouts named in experiments/gold/HOLDOUT_V1.json are listed and never opened
as audio. Content fields stay blank unless they were already filled in.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import numpy as np
import soundfile as sf

from hush.audio import RAW_SR, analysis_pieces, load_session, read_stereo, write_mono_wav

REPO = Path(__file__).resolve().parents[2]
RECORDINGS = REPO / "recordings"
CATALOG_PATH = REPO / "experiments" / "SESSION_CATALOG.csv"
CLIP_DIR = REPO / "experiments" / "catalog_clips"
CLIP_S = 25.0
MIN_CLIP_S = 20.0
SILENCE_PEAK = 1e-4
SILENCE_SEARCH_S = 600.0
SILENCE_STEP_S = 30.0

COLUMNS = [
    "session_id",
    "date",
    "content_type",
    "delivery",
    "network_or_service",
    "show",
    "notes",
    "started_local",
    "duration_s",
    "role",
]

# Identity only. Clock and duration are filled from session.json on each run.
KNOWN = {
    "hush_20260914_212529": {
        "content_type": "sports",
        "delivery": "linear",
        "network_or_service": "ESPN",
        "show": "MNF",
        "notes": "Monday Night Football on ESPN/ABC, 2026-09-14. Identified from the schedule, not from the listening clip.",
    }
}

IDENTITY = ("content_type", "delivery", "network_or_service", "show", "notes")


def holdout_ids(repo: Path = REPO) -> set[str]:
    """Sessions that must not be opened as audio. The two gold files must agree."""
    gold = repo / "experiments" / "gold"
    reserved = {
        row["session"]
        for row in json.loads((gold / "HOLDOUT_V1.json").read_text(encoding="utf-8"))["reserved_sessions"]
    }
    datasets = json.loads((gold / "DATASETS_V1.json").read_text(encoding="utf-8"))["sessions"]
    marked = {sid for sid, row in datasets.items() if row.get("role") == "holdout"}
    if reserved != marked:
        raise RuntimeError(f"holdout lists disagree: HOLDOUT_V1 {sorted(reserved)} vs DATASETS_V1 {sorted(marked)}")
    return reserved


def list_sessions(recordings_root: Path = RECORDINGS) -> list[Path]:
    return sorted(path for path in recordings_root.glob("*/*") if path.is_dir() and path.name.startswith("hush_"))


def contiguous_runs(chunks: list[dict], present: set[str] | None = None) -> list[tuple[float, float]]:
    """Half-open elapsed spans of chunks that actually exist, split at gaps."""
    runs: list[tuple[float, float]] = []
    ordered = sorted(chunks, key=lambda row: float(row["start_elapsed_seconds"]))
    for chunk in ordered:
        if present is not None and chunk["file"] not in present:
            continue
        start = float(chunk["start_elapsed_seconds"])
        end = float(chunk["end_elapsed_seconds"])
        if end <= start:
            continue
        if runs and start - runs[-1][1] <= 0.05:
            runs[-1] = (runs[-1][0], end)
        else:
            runs.append((start, end))
    return runs


def middle_window(runs: list[tuple[float, float]], clip_s: float = CLIP_S) -> tuple[float, float, str]:
    """A clip near the midpoint of the first-to-last span, inside one run.

    A gap at the midpoint uses the nearest recorded audio. The window never
    crosses a missing stretch.
    """
    if not runs:
        raise RuntimeError("no recorded audio")
    span0 = runs[0][0]
    span1 = runs[-1][1]
    mid = (span0 + span1) / 2.0
    containing = next((run for run in runs if run[0] <= mid <= run[1]), None)
    reason = "geometric middle of the session span"
    if containing is None:
        containing = min(runs, key=lambda run: 0.0 if run[0] <= mid <= run[1] else min(abs(mid - run[0]), abs(mid - run[1])))
        reason = "middle of the session span falls in a gap; nearest recorded audio"
    start, end, placed = _place(containing, mid, clip_s)
    if end - start < MIN_CLIP_S:
        reason += "; recorded run is shorter than 20 s"
    elif placed != "centered":
        reason += "; shifted to stay inside recorded audio"
    return start, end, reason


def _place(run: tuple[float, float], mid: float, clip_s: float) -> tuple[float, float, str]:
    a, b = run
    if b - a <= clip_s:
        return a, b, "whole_run"
    center = min(max(mid, a), b)
    start = center - clip_s / 2.0
    end = center + clip_s / 2.0
    placed = "centered"
    if start < a:
        start, end, placed = a, a + clip_s, "clamped"
    elif end > b:
        start, end, placed = b - clip_s, b, "clamped"
    return start, end, placed


def _present_files(session_dir: Path, chunks: list[dict]) -> set[str]:
    return {chunk["file"] for chunk in chunks if (session_dir / chunk["file"]).is_file()}


def _peak(audio: np.ndarray) -> float:
    if audio.size == 0:
        return 0.0
    return float(np.max(np.abs(audio)))


def _read_span(session_dir: Path, meta: dict, t0: float, t1: float) -> np.ndarray:
    pieces = analysis_pieces(session_dir, meta, t0, t1)
    parts = [read_stereo(piece) for piece in pieces]
    return parts[0] if len(parts) == 1 else np.concatenate(parts)


def audible_window(session_dir: Path, meta: dict, runs: list[tuple[float, float]]) -> tuple[float, float, str, float]:
    """Middle window, stepped away only if that slice is digital silence."""
    t0, t1, reason = middle_window(runs)
    audio = _read_span(session_dir, meta, t0, t1)
    peak = _peak(audio)
    if peak >= SILENCE_PEAK:
        return t0, t1, reason, peak
    span0, span1 = runs[0][0], runs[-1][1]
    mid = (t0 + t1) / 2.0
    step = SILENCE_STEP_S
    while step <= SILENCE_SEARCH_S:
        for center in (mid - step, mid + step):
            if center < span0 or center > span1:
                continue
            try:
                alt0, alt1, alt_reason = middle_window_at(runs, center)
            except RuntimeError:
                continue
            alt = _read_span(session_dir, meta, alt0, alt1)
            alt_peak = _peak(alt)
            if alt_peak >= SILENCE_PEAK:
                return alt0, alt1, f"geometric middle was silent; {alt_reason}", alt_peak
        step += SILENCE_STEP_S
    return t0, t1, reason + "; still silent within 10 min", peak


def middle_window_at(runs: list[tuple[float, float]], center: float, clip_s: float = CLIP_S) -> tuple[float, float, str]:
    """Same placement rule as the session middle, around an explicit center."""
    containing = next((run for run in runs if run[0] <= center <= run[1]), None)
    if containing is None:
        raise RuntimeError(f"center {center} is not inside recorded audio")
    start, end, _placed = _place(containing, center, clip_s)
    return start, end, f"nearest audible audio around {center:.1f} s"


def _row_from_session(session_dir: Path, sealed: set[str]) -> dict[str, str]:
    session_id = session_dir.name
    role = "holdout" if session_id in sealed else "dev"
    if role == "holdout":
        meta = json.loads((session_dir / "session.json").read_text(encoding="utf-8"))
        present = None
    else:
        meta = load_session(session_dir)
        present = _present_files(session_dir, meta["chunks"])
    started = str(meta["started_at"])
    runs = contiguous_runs(meta["chunks"], present)
    duration = sum(end - start for start, end in runs)
    return {
        "session_id": session_id,
        "date": started[:10],
        "content_type": "",
        "delivery": "",
        "network_or_service": "",
        "show": "",
        "notes": "Sealed holdout. No clip exported." if role == "holdout" else "",
        "started_local": started,
        "duration_s": f"{duration:.1f}",
        "role": role,
    }


def _blank(value: str | None) -> bool:
    return value is None or str(value).strip() == ""


def merge_catalog(existing: list[dict[str, str]], fresh: list[dict[str, str]]) -> list[dict[str, str]]:
    """Keep identification cells the user already filled. Refresh clock and duration."""
    prior = {row["session_id"]: row for row in existing}
    merged = []
    for row in fresh:
        kept = dict(row)
        old = prior.get(row["session_id"], {})
        for key in IDENTITY:
            if not _blank(old.get(key)):
                kept[key] = old[key]
            elif _blank(kept.get(key)) and row["session_id"] in KNOWN:
                kept[key] = KNOWN[row["session_id"]][key]
        merged.append(kept)
    return merged


def read_catalog(path: Path = CATALOG_PATH) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_catalog(rows: list[dict[str, str]], path: Path = CATALOG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in COLUMNS})


def export_clip(session_dir: Path, sealed: set[str], clip_dir: Path = CLIP_DIR) -> dict[str, str]:
    session_id = session_dir.name
    if session_id in sealed or any(token in str(session_dir) for token in sealed):
        raise RuntimeError(f"refusing sealed holdout {session_id}")
    meta = load_session(session_dir)
    present = _present_files(session_dir, meta["chunks"])
    runs = contiguous_runs(meta["chunks"], present)
    t0, t1, reason, peak = audible_window(session_dir, meta, runs)
    audio = _read_span(session_dir, meta, t0, t1)
    mono = audio.mean(axis=1) if audio.ndim == 2 else audio
    dest = clip_dir / f"{session_id}.wav"
    write_mono_wav(dest, mono, RAW_SR)
    info = sf.info(str(dest))
    return {
        "session_id": session_id,
        "clip_file": str(dest.relative_to(REPO)),
        "start_elapsed_s": f"{t0:.3f}",
        "end_elapsed_s": f"{t1:.3f}",
        "duration_s": f"{info.duration:.3f}",
        "started_local": str(meta["started_at"]),
        "selection": reason,
        "peak_abs": f"{peak:.6f}",
    }


def write_manifest(rows: list[dict[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "session_id",
        "clip_file",
        "start_elapsed_s",
        "end_elapsed_s",
        "duration_s",
        "started_local",
        "selection",
        "peak_abs",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def build(recordings_root: Path = RECORDINGS, catalog_path: Path = CATALOG_PATH, clip_dir: Path = CLIP_DIR) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    sealed = holdout_ids()
    sessions = list_sessions(recordings_root)
    fresh = [_row_from_session(path, sealed) for path in sessions]
    catalog = merge_catalog(read_catalog(catalog_path), fresh)
    write_catalog(catalog, catalog_path)
    clips = []
    for path in sessions:
        if path.name in sealed:
            continue
        clips.append(export_clip(path, sealed, clip_dir))
    write_manifest(clips, clip_dir / "manifest.csv")
    return catalog, clips


def main() -> None:
    parser = argparse.ArgumentParser(description="Write SESSION_CATALOG.csv and one middle clip per dev session.")
    parser.add_argument("--recordings", type=Path, default=RECORDINGS)
    parser.add_argument("--catalog", type=Path, default=CATALOG_PATH)
    parser.add_argument("--clip-dir", type=Path, default=CLIP_DIR)
    args = parser.parse_args()
    catalog, clips = build(args.recordings, args.catalog, args.clip_dir)
    n_holdout = sum(1 for row in catalog if row["role"] == "holdout")
    print(f"catalog {args.catalog} rows={len(catalog)} holdouts_not_sampled={n_holdout} clips={len(clips)}")


if __name__ == "__main__":
    main()
