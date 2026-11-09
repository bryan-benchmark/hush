"""Load one coverage span as 16 kHz mono. Holdouts are refused."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from experiments.ledger import RECORDINGS
from hush.audio import analysis_pieces, find_session, load_session, read_stereo, resample_concat

from tools.gpu_lab.splits import HOLDOUTS

TARGET_SR = 16000


def load_coverage(session: str, start: float, end: float) -> np.ndarray:
    if session in HOLDOUTS:
        raise RuntimeError(f"refusing sealed holdout {session}")
    folder = find_session(RECORDINGS, session)
    meta = load_session(folder)
    pieces = analysis_pieces(folder, meta, start, end)
    missing = [piece["file"] for piece in pieces if not piece["path"].is_file()]
    if missing:
        raise RuntimeError(f"{session} is missing {missing[0]}")
    parts = [read_stereo(piece).mean(axis=1) for piece in pieces]
    audio = np.asarray(resample_concat(parts, up=1, down=3), dtype=np.float32)
    expected = int(round((end - start) * TARGET_SR))
    if abs(len(audio) - expected) > 8:
        raise RuntimeError(f"{session} resampled to {len(audio)} samples, expected {expected}")
    if len(audio) < expected:
        audio = np.pad(audio, (0, expected - len(audio)))
    return audio[:expected]


def clip_window(audio: np.ndarray, origin: float, t: float, window_s: float) -> np.ndarray:
    """Audio for [t - window, t), with t measured on the session clock."""
    end = int(round((t - origin) * TARGET_SR))
    start = end - int(round(window_s * TARGET_SR))
    if start < 0 or end > len(audio):
        raise RuntimeError(f"window {t - window_s:.3f}..{t:.3f} leaves the loaded audio")
    return np.ascontiguousarray(audio[start:end])
