"""Exp003b: freeze a pre-departure program cloud.

The trigger is a local percentile of the Exp003 score, not an absolute
distance and not the 94th percentile from the Exp003 overlay. Constants
below were written before this run's ledger was opened.
"""

from __future__ import annotations

import numpy as np

EXPERIMENT_SPEC_VERSION = "exp003b-v1"
FEATURE_SCHEMA_VERSION = "exp003b-frozen-program-v1"

PERCENTILE = 99.0
HISTORY_S = 600.0
MIN_HISTORY_S = 300.0
HITS_REQUIRED = 3
HITS_WINDOW = 5
REFRACTORY_S = 60.0
FREEZE_EXCLUDE_S = 30.0
FREEZE_SPAN_S = 180.0

PARAMS = {
    "percentile": PERCENTILE,
    "history_s": HISTORY_S,
    "min_history_s": MIN_HISTORY_S,
    "hits_required": HITS_REQUIRED,
    "hits_window": HITS_WINDOW,
    "refractory_s": REFRACTORY_S,
    "freeze_exclude_s": FREEZE_EXCLUDE_S,
    "freeze_span_s": FREEZE_SPAN_S,
}


def exceed_mask(ends: np.ndarray, scores: np.ndarray) -> np.ndarray:
    """True where this score is above the 99th percentile of its own prior history.

    History is defined scores with window_end in (t-600, t). The current
    score is not in that pool. A hit also requires a defined score at least
    300 s earlier inside that pool.
    """
    ends = np.asarray(ends, dtype=np.float64)
    scores = np.asarray(scores, dtype=np.float64)
    hits = np.zeros(len(ends), dtype=bool)
    for index, t in enumerate(ends):
        if not np.isfinite(scores[index]):
            continue
        lo = int(np.searchsorted(ends, t - HISTORY_S, side="right"))
        hist_scores = scores[lo:index]
        hist_ends = ends[lo:index]
        defined = np.isfinite(hist_scores)
        if not np.any(defined):
            continue
        oldest = float(hist_ends[defined][0])
        if oldest > t - MIN_HISTORY_S:
            continue
        threshold = float(np.percentile(hist_scores[defined], PERCENTILE))
        hits[index] = bool(scores[index] > threshold)
    return hits


def freeze_times(ends: np.ndarray, hits: np.ndarray) -> list[float]:
    """Fire when 3 of the last 5 consecutive seconds are hits, then wait 60 s."""
    ends = np.asarray(ends, dtype=np.float64)
    hits = np.asarray(hits, dtype=bool)
    fired: list[float] = []
    last = -np.inf
    span = HITS_WINDOW - 1
    for index, t in enumerate(ends):
        if index < span or t < last + REFRACTORY_S:
            continue
        if float(ends[index] - ends[index - span]) > span + 0.01:
            continue
        if int(hits[index - span : index + 1].sum()) >= HITS_REQUIRED:
            fired.append(float(t))
            last = float(t)
    return fired


def reference_bounds(trigger_s: float) -> tuple[float, float]:
    """Half-open (T-210, T-30] in the same end-time convention as Exp003."""
    stop = trigger_s - FREEZE_EXCLUDE_S
    start = stop - FREEZE_SPAN_S
    return start, stop


def reference_mask(ends: np.ndarray, trigger_s: float) -> np.ndarray:
    start, stop = reference_bounds(trigger_s)
    ends = np.asarray(ends, dtype=np.float64)
    return (ends > start) & (ends <= stop)


def cloud_distance(current: np.ndarray, reference: np.ndarray) -> tuple[np.ndarray, float]:
    """1 - cosine to the mean of the reference, matching Exp003.

    Returns distances for each current row, and the median of the reference
    rows' own distances to that mean.
    """
    if reference.ndim != 2 or reference.shape[0] == 0:
        raise RuntimeError("frozen reference is empty")
    centroid = reference.mean(axis=0)
    norm = np.linalg.norm(centroid)
    if norm == 0.0 or not np.isfinite(norm):
        raise RuntimeError("frozen centroid has zero norm")
    unit = centroid / norm
    current_d = 1.0 - current @ unit
    reference_d = 1.0 - reference @ unit
    return current_d, float(np.median(reference_d))
