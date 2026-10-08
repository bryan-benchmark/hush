"""Exp004: commercial-clock structure.

Spot lengths 15/30/60 s and pod lengths 60/90/120/150/180 s are a broadcast
clock, written down before this run's ledger was opened. They are not the
measured lengths of the ESPN pods. The peak rule is a listing, not a mute
threshold, and it is not the Exp003b freeze.
"""

from __future__ import annotations

import numpy as np

EXPERIMENT_SPEC_VERSION = "exp004-v1"
FEATURE_SCHEMA_VERSION = "exp004-temporal-v1"

SEPARATION_S = 10.0
PERCENTILE = 90.0
HISTORY_S = 600.0
MIN_HISTORY_S = 300.0
REFRACTORY_S = 12.0
SPOT_S = (15.0, 30.0, 60.0)
POD_S = (60.0, 90.0, 120.0, 150.0, 180.0)
RETURN_CLOCK_S = (60.0, 90.0, 120.0, 150.0)
TOLERANCE_S = 3.0
GRID_S = 15.0
DROP_SPAN_S = 10.0
RETURN_HORIZON_S = 180.0

PARAMS = {
    "separation_s": SEPARATION_S,
    "percentile": PERCENTILE,
    "history_s": HISTORY_S,
    "min_history_s": MIN_HISTORY_S,
    "refractory_s": REFRACTORY_S,
    "spot_s": list(SPOT_S),
    "pod_s": list(POD_S),
    "return_clock_s": list(RETURN_CLOCK_S),
    "tolerance_s": TOLERANCE_S,
    "grid_s": GRID_S,
    "drop_span_s": DROP_SPAN_S,
    "return_horizon_s": RETURN_HORIZON_S,
}


def jump_score(ends: np.ndarray, embeddings: np.ndarray, separation_s: float = SEPARATION_S) -> np.ndarray:
    """1 - cosine between the window ending at t and the window ending 10 s earlier.

    Those two windows do not overlap. The score at t uses no audio after t.
    """
    ends = np.asarray(ends, dtype=np.float64)
    embeddings = np.asarray(embeddings, dtype=np.float64)
    if embeddings.ndim != 2 or embeddings.shape[0] != ends.size:
        raise RuntimeError("embeddings do not align with window ends")
    jumps = np.full(ends.size, np.nan)
    if ends.size < 2:
        return jumps
    step = float(ends[1] - ends[0])
    lag = int(round(separation_s / step))
    if lag < 1 or abs(lag * step - separation_s) > 1e-6:
        raise RuntimeError(f"{separation_s} s is not an integer number of hops")
    if np.any(np.abs(np.diff(ends) - step) > 1e-6):
        raise RuntimeError("window ends are not a uniform grid")
    current = embeddings[lag:]
    prior = embeddings[:-lag]
    jumps[lag:] = 1.0 - np.sum(current * prior, axis=1)
    return jumps


def exceed_mask(ends: np.ndarray, scores: np.ndarray) -> np.ndarray:
    """True where this jump exceeds the 90th percentile of its prior 10 minutes.

    The current score is not in the pool. At least 5 minutes of defined
    history is required.
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


def peak_times(ends: np.ndarray, scores: np.ndarray, hits: np.ndarray) -> list[float]:
    """A peak starts a high plateau, then the listing waits 12 s.

    The sample must be above the previous one and at least as high as the
    next one, so a flat step still produces one time: the first sample of
    the step.
    """
    ends = np.asarray(ends, dtype=np.float64)
    scores = np.asarray(scores, dtype=np.float64)
    hits = np.asarray(hits, dtype=bool)
    fired: list[float] = []
    last = -np.inf
    for index in range(1, len(ends) - 1):
        t = float(ends[index])
        if t < last + REFRACTORY_S or not hits[index]:
            continue
        if not (np.isfinite(scores[index - 1]) and np.isfinite(scores[index + 1])):
            continue
        if scores[index] > scores[index - 1] and scores[index] >= scores[index + 1]:
            fired.append(t)
            last = t
    return fired


def nearest_mark(duration_s: float, marks: tuple[float, ...]) -> tuple[float, float, bool]:
    mark = min(marks, key=lambda item: (abs(duration_s - item), item))
    error = abs(duration_s - mark)
    return float(mark), float(error), bool(error <= TOLERANCE_S)


def on_spot_clock(gap_s: float) -> bool:
    return nearest_mark(gap_s, SPOT_S)[2]


def gaps(times: list[float]) -> np.ndarray:
    if len(times) < 2:
        return np.array([], dtype=np.float64)
    return np.diff(np.asarray(times, dtype=np.float64))


def grid_residual(offset_s: float, grid_s: float = GRID_S) -> float:
    """Signed distance to the nearest multiple of 15 s. Range is ±7.5 s."""
    nearest = round(offset_s / grid_s) * grid_s
    return float(offset_s - nearest)


def autocorr(scores: np.ndarray, lag: int, mask: np.ndarray | None = None) -> float:
    """Mean product of centered scores, lag seconds apart, on the pairs that exist."""
    values = np.asarray(scores, dtype=np.float64)
    if lag < 1 or lag >= values.size:
        return float("nan")
    chosen = np.isfinite(values) if mask is None else np.asarray(mask, dtype=bool) & np.isfinite(values)
    left = values[:-lag]
    right = values[lag:]
    ok = chosen[:-lag] & chosen[lag:]
    if int(ok.sum()) < 30:
        return float("nan")
    mu = float(np.mean(values[chosen]))
    return float(np.mean((left[ok] - mu) * (right[ok] - mu)))
