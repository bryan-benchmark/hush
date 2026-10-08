"""Exp005C. Causal distance from recent transcript text.

Same shape as Exp003: the reference ended before this window started, inside
a 180 s memory, and the score is null until that reference spans 60 s.
Windows with fewer than 8 ASR words are absent. They are not embedded and
they are not part of anyone's reference. There is no commercial class.
"""

from __future__ import annotations

import numpy as np

EXPERIMENT_SPEC_VERSION = "exp005-v1"
FEATURE_SCHEMA_VERSION = "exp005-semantic-v1"
EMBEDDING_MODEL_ID = "sentence-transformers/all-MiniLM-L6-v2"

WINDOW_S = 15.0
HOP_S = 1.0
MEMORY_S = 180.0
MIN_REFERENCE_S = 60.0
MIN_WORDS = 8

PARAMS = {
    "embedding_model_id": EMBEDDING_MODEL_ID,
    "window_s": WINDOW_S,
    "hop_s": HOP_S,
    "memory_s": MEMORY_S,
    "min_reference_s": MIN_REFERENCE_S,
    "min_words": MIN_WORDS,
    "text": "ASR word texts joined by spaces. Phrase normalization is not applied.",
    "empty_windows": "fewer than 8 words are null and stay out of the reference",
}


def window_bounds(duration_s: float) -> tuple[np.ndarray, np.ndarray]:
    if duration_s < WINDOW_S:
        raise RuntimeError(f"audio {duration_s:.3f}s is shorter than the {WINDOW_S:.0f}s window")
    ends = np.arange(WINDOW_S, duration_s + 1e-9, HOP_S, dtype=np.float64)
    ends = ends[ends <= duration_s + 1e-9]
    return ends - WINDOW_S, ends


def anomaly_scores(
    starts: np.ndarray,
    ends: np.ndarray,
    embeddings: np.ndarray,
    present: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """1 - cosine to the mean of present reference rows. Absent rows are skipped."""
    starts = np.asarray(starts, dtype=np.float64)
    ends = np.asarray(ends, dtype=np.float64)
    matrix = np.asarray(embeddings, dtype=np.float64)
    present = np.asarray(present, dtype=bool)
    if len(starts) != len(ends) or len(starts) != len(matrix) or len(starts) != len(present):
        raise RuntimeError("starts, ends, embeddings, and present must align")
    scores = np.full(len(starts), np.nan, dtype=np.float64)
    counts = np.zeros(len(starts), dtype=np.int32)
    spans = np.full(len(starts), np.nan, dtype=np.float64)
    for index, start in enumerate(starts):
        if not present[index]:
            continue
        chosen = np.flatnonzero(present & (ends <= start + 1e-9) & (ends > start - MEMORY_S))
        counts[index] = int(chosen.size)
        if chosen.size == 0:
            continue
        span = float(ends[chosen[-1]] - ends[chosen[0]])
        spans[index] = span
        if span + 1e-9 < MIN_REFERENCE_S:
            continue
        centroid = matrix[chosen].mean(axis=0)
        norm = np.linalg.norm(centroid)
        if norm == 0.0 or not np.isfinite(norm):
            continue
        scores[index] = 1.0 - float(np.dot(matrix[index], centroid / norm))
    return scores, counts, spans
