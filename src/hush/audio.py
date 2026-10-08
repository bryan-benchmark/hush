"""Load raw chunks as one PCM stream and resample once.

``resample_poly`` rings at the ends of the array it is given. Resampling each
900 s file on its own and concatenating the results plants those rings on the
chunk seams. This module concatenates the selected samples first.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

RAW_SR = 48000
N_CHANNELS = 2


def find_session(recordings_root: Path, session_id: str) -> Path:
    matches = sorted(recordings_root.glob(f"*/{session_id}"))
    if len(matches) != 1:
        raise RuntimeError(f"expected one session directory for {session_id}, found {matches}")
    return matches[0]


def load_session(session_dir: Path) -> dict:
    path = session_dir / "session.json"
    meta = json.loads(path.read_text(encoding="utf-8"))
    if int(meta["sample_rate_hz"]) != RAW_SR:
        raise RuntimeError(f"expected {RAW_SR} Hz, got {meta['sample_rate_hz']}")
    if int(meta["channels"]) != N_CHANNELS:
        raise RuntimeError(f"expected stereo, got {meta['channels']} channels")
    return meta


def analysis_pieces(session_dir: Path, meta: dict, t0: float, t1: float) -> list[dict]:
    """Chunk slices that cover ``[t0, t1)`` in session seconds, in file order."""
    if t1 <= t0:
        raise RuntimeError(f"empty analysis range {t0}..{t1}")
    pieces = []
    for chunk in meta["chunks"]:
        c0 = float(chunk["start_elapsed_seconds"])
        c1 = float(chunk["end_elapsed_seconds"])
        if c1 <= t0 or c0 >= t1:
            continue
        path = session_dir / chunk["file"]
        info = sf.info(str(path))
        if info.samplerate != RAW_SR or info.channels != N_CHANNELS:
            raise RuntimeError(f"unexpected wav format: {path} {info.samplerate} Hz {info.channels} ch")
        take0 = max(t0, c0)
        take1 = min(t1, c1)
        frame0 = int(round((take0 - c0) * RAW_SR))
        frame1 = int(round((take1 - c0) * RAW_SR))
        if frame0 < 0 or frame1 > info.frames or frame1 <= frame0:
            raise RuntimeError(
                f"slice {frame0}:{frame1} outside {path} ({info.frames} frames) "
                f"for session {take0:.3f}..{take1:.3f}"
            )
        pieces.append(
            {
                "file": chunk["file"],
                "path": path,
                "chunk_start_seconds": c0,
                "chunk_end_seconds": c1,
                "file_frames": int(info.frames),
                "read_start_frame": frame0,
                "read_stop_frame": frame1,
                "session_start_seconds": take0,
                "session_end_seconds": take1,
                "n_samples": frame1 - frame0,
            }
        )
    if not pieces:
        raise RuntimeError(f"no chunks cover {t0}..{t1} in {session_dir}")
    expected = int(round((t1 - t0) * RAW_SR))
    got = sum(p["n_samples"] for p in pieces)
    if got != expected:
        raise RuntimeError(f"analysis sample count {got} != {expected} for {t0}..{t1}")
    cursor = t0
    for piece in pieces:
        if abs(piece["session_start_seconds"] - cursor) > 1e-9:
            raise RuntimeError(f"gap before {piece['file']} at {piece['session_start_seconds']} (expected {cursor})")
        cursor = piece["session_end_seconds"]
    if abs(cursor - t1) > 1e-9:
        raise RuntimeError(f"pieces end at {cursor}, expected {t1}")
    return pieces


def read_stereo(piece: dict) -> np.ndarray:
    audio, sr = sf.read(
        str(piece["path"]),
        start=piece["read_start_frame"],
        stop=piece["read_stop_frame"],
        dtype="float32",
        always_2d=True,
    )
    if sr != RAW_SR or audio.shape[1] != N_CHANNELS or audio.shape[0] != piece["n_samples"]:
        raise RuntimeError(f"read mismatch for {piece['file']}: {audio.shape} @ {sr}")
    return audio


def resample_concat(parts: list[np.ndarray], up: int = 1, down: int = 3) -> np.ndarray:
    """Resample one concatenated stream. Do not resample ``parts`` separately."""
    if not parts:
        raise RuntimeError("no audio to resample")
    stream = parts[0] if len(parts) == 1 else np.concatenate(parts)
    return resample_poly(stream, up=up, down=down, window=("kaiser", 5.0), padtype="constant")


def write_mono_wav(path: Path, audio: np.ndarray, sr: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), np.asarray(audio, dtype=np.float32), sr, subtype="PCM_16")
