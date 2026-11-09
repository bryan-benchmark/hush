"""Past-only windows. A decision at t reads audio from [t - window, t)."""

from __future__ import annotations

import numpy as np

from experiments.audio_learn.splits import CONTEXT_S, HOP_S, SR, WINDOW_S


def pack_past_window(
    audio: np.ndarray,
    origin: float,
    t: float,
    window_s: float = WINDOW_S,
    context_s: float = CONTEXT_S,
    sr: int = SR,
) -> np.ndarray:
    """Right-align [t - window, t) in a context-length buffer.

    Samples at or after t are not copied. The front of the buffer is silence,
    which stands in for audio older than the window, not for audio that has
    not arrived.
    """
    if window_s <= 0 or context_s < window_s:
        raise ValueError("window must be positive and fit in the context")
    end = int(round((t - origin) * sr))
    start = end - int(round(window_s * sr))
    if start < 0 or end > len(audio):
        raise ValueError(f"window ending at {t:.3f} leaves the loaded audio")
    context_n = int(round(context_s * sr))
    window_n = end - start
    buf = np.zeros(context_n, dtype=np.float32)
    buf[-window_n:] = np.asarray(audio[start:end], dtype=np.float32)
    return buf


def pack_past_batch(
    audio: np.ndarray,
    origin: float,
    times: list[float] | np.ndarray,
    window_s: float = WINDOW_S,
    context_s: float = CONTEXT_S,
    sr: int = SR,
) -> np.ndarray:
    context_n = int(round(context_s * sr))
    window_n = int(round(window_s * sr))
    out = np.zeros((len(times), context_n), dtype=np.float32)
    origin_i = int(round(origin * sr))
    # `audio[0]` is the sample at `origin`, so the index is (t - origin) * sr.
    del origin_i
    for row, t in enumerate(times):
        end = int(round((float(t) - origin) * sr))
        start = end - window_n
        if start < 0 or end > len(audio):
            raise ValueError(f"window ending at {float(t):.3f} leaves the loaded audio")
        out[row, -window_n:] = audio[start:end]
    return out


def consecutive_end_indices(times: np.ndarray, length: int, hop_s: float = HOP_S, atol: float = 1e-3) -> list[int]:
    """Ends of length-long runs whose stamps are one hop apart."""
    if length < 1:
        raise ValueError("length must be positive")
    times = np.asarray(times, dtype=np.float64)
    ends = []
    for index in range(length - 1, len(times)):
        window = times[index - length + 1 : index + 1]
        gaps = np.diff(window)
        if gaps.size == 0 or np.all(np.abs(gaps - hop_s) <= atol):
            ends.append(index)
    return ends


def lookback_bounds(times: np.ndarray, index: int, length: int, hop_s: float = HOP_S, atol: float = 1e-3) -> tuple[int, int]:
    """Inclusive start and exclusive end of a causal lookback that does not cross a gap."""
    start = index
    steps = 0
    while start > 0 and steps < length - 1:
        if abs(float(times[start]) - float(times[start - 1]) - hop_s) > atol:
            break
        start -= 1
        steps += 1
    return start, index + 1
