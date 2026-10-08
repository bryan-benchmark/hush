"""Causal distance from the recent program embedding cloud.

Frozen before any Exp003 label overlay. The reference for a window is audio
that ended before that window started, inside a 180 s memory. The current
window cannot score itself, and overlapping hops are not in its reference.
There is no acceptance threshold and no ad class.
"""

from __future__ import annotations

import numpy as np

EXPERIMENT_SPEC_VERSION = "exp003-v1"
FEATURE_SCHEMA_VERSION = "exp003-program-cloud-v1"
EMBEDDING_MODEL_ID = "qiuqiangkong/panns-cnn14"
CHECKPOINT_NAME = "Cnn14_mAP=0.431.pth"
CHECKPOINT_URL = "https://zenodo.org/record/3987831/files/Cnn14_mAP%3D0.431.pth?download=1"
SR = 32000
WINDOW_S = 10.0
HOP_S = 1.0
MEMORY_S = 180.0
MIN_REFERENCE_S = 60.0
LISTING_GAP_S = 45.0
LISTING_K = 20

PARAMS = {
    "window_s": WINDOW_S,
    "hop_s": HOP_S,
    "memory_s": MEMORY_S,
    "min_reference_s": MIN_REFERENCE_S,
    "listing_gap_s": LISTING_GAP_S,
    "listing_k": LISTING_K,
}


def window_bounds(duration_s: float, origin_s: float = 0.0) -> tuple[np.ndarray, np.ndarray]:
    """Half-open windows of WINDOW_S ending on the hop grid, inside [origin, origin+duration)."""
    if duration_s < WINDOW_S:
        raise RuntimeError(f"audio {duration_s:.3f}s is shorter than the {WINDOW_S:.0f}s window")
    first_end = origin_s + WINDOW_S
    last_end = origin_s + duration_s
    ends = np.arange(first_end, last_end + 1e-9, HOP_S, dtype=np.float64)
    ends = ends[ends <= last_end + 1e-9]
    starts = ends - WINDOW_S
    return starts, ends


def anomaly_scores(starts: np.ndarray, ends: np.ndarray, embeddings: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Cosine distance from each window to the mean of its causal reference.

    Reference rows are those whose window ended at or before this window's
    start, and after start - MEMORY_S. The score is null until that reference
    spans MIN_REFERENCE_S. Returns score, reference count, and reference span.
    """
    starts = np.asarray(starts, dtype=np.float64)
    ends = np.asarray(ends, dtype=np.float64)
    matrix = np.asarray(embeddings, dtype=np.float64)
    if matrix.ndim != 2 or len(starts) != len(ends) or len(starts) != len(matrix):
        raise RuntimeError("starts, ends, and embeddings must describe the same windows")
    if np.any(ends - starts < WINDOW_S - 1e-6):
        raise RuntimeError("a scored window is shorter than the frozen window")
    scores = np.full(len(starts), np.nan, dtype=np.float64)
    counts = np.zeros(len(starts), dtype=np.int32)
    spans = np.full(len(starts), np.nan, dtype=np.float64)
    for index, start in enumerate(starts):
        lo = start - MEMORY_S
        chosen = np.flatnonzero((ends <= start + 1e-9) & (ends > lo))
        counts[index] = int(chosen.size)
        if chosen.size == 0:
            continue
        span = float(ends[chosen[-1]] - ends[chosen[0]])
        spans[index] = span
        if span + 1e-9 < MIN_REFERENCE_S:
            continue
        cloud = matrix[chosen]
        centroid = cloud.mean(axis=0)
        norm = np.linalg.norm(centroid)
        if norm == 0.0 or not np.isfinite(norm):
            continue
        cosine = float(np.dot(matrix[index], centroid / norm))
        scores[index] = 1.0 - cosine
    return scores, counts, spans


def listing_peaks(timestamps: np.ndarray, values: np.ndarray, gap_s: float = LISTING_GAP_S, k: int = LISTING_K) -> list[dict]:
    """Largest defined scores, separated by gap_s. A listing, not a mute rule."""
    order = np.argsort(np.where(np.isfinite(values), values, -np.inf))[::-1]
    chosen: list[int] = []
    for idx in order:
        if not np.isfinite(values[idx]):
            break
        t = float(timestamps[idx])
        if any(abs(t - float(timestamps[j])) < gap_s for j in chosen):
            continue
        chosen.append(int(idx))
        if len(chosen) >= k:
            break
    return [{"timestamp_seconds": float(timestamps[i]), "anomaly": float(values[i])} for i in chosen]
