"""Causal acoustic features for Experiment 001.

A row stamped at ``timestamp_seconds`` uses audio that has already ended.
``timestamp_seconds`` is the window end, not the window start. STFT and onset
frames use ``center=False``. Rolling summaries are trailing-only.
"""

from __future__ import annotations

import os

_numba_cache = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".numba_cache"))
os.makedirs(_numba_cache, exist_ok=True)
os.environ.setdefault("NUMBA_CACHE_DIR", _numba_cache)

import numpy as np
import pyloudnorm
from numpy.lib.stride_tricks import sliding_window_view

WIN_S = 1.0
HOP_S = 0.5
N_FFT = 512
STFT_HOP = 160
N_MFCC = 13
SILENCE_DBFS = -45.0
MOMENTARY_S = 0.4
SHORT_TERM_S = 3.0
LUFS_OFFSET = -0.691
RHYTHM_S = 8.0
MOD_HZ_LO = 0.5
MOD_HZ_HI = 4.0

FEATURE_SCHEMA_VERSION = "exp001-features-v1"

PARAMS = {
    "feature_schema_version": FEATURE_SCHEMA_VERSION,
    "win_s": WIN_S,
    "hop_s": HOP_S,
    "n_fft": N_FFT,
    "stft_hop": STFT_HOP,
    "stft_center": False,
    "onset_center": False,
    "n_mfcc": N_MFCC,
    "rolloff": 0.85,
    "silence_dbfs": SILENCE_DBFS,
    "momentary_s": MOMENTARY_S,
    "short_term_s": SHORT_TERM_S,
    "lufs_definition": "ungated K-weighted power, pyloudnorm K-weighting filters",
    "rhythm_s": RHYTHM_S,
    "modulation_hz": [MOD_HZ_LO, MOD_HZ_HI],
    "onset_peak": "causal: strength[i] > strength[i-1] and strength[i] > strength[i-2]",
    "timestamp": "window_end_seconds",
}


def window_grid(n_samples: int, sr: int, origin_s: float = 0.0) -> dict:
    """Half-open windows ``[start, end)`` whose end is the availability time."""
    win = int(round(WIN_S * sr))
    hop = int(round(HOP_S * sr))
    if n_samples < win:
        raise RuntimeError(f"audio shorter than one window: {n_samples} samples at {sr} Hz")
    n_win = 1 + (n_samples - win) // hop
    idx = np.arange(n_win, dtype=np.int64)
    start = idx * hop
    end = start + win
    if int(end[-1]) > n_samples:
        raise RuntimeError("window grid ran past the audio")
    window_end = origin_s + WIN_S + idx.astype(np.float64) * HOP_S
    window_start = window_end - WIN_S
    return {
        "win": win,
        "hop": hop,
        "n_win": n_win,
        "start_sample": start,
        "end_sample": end,
        "window_start_seconds": window_start,
        "window_end_seconds": window_end,
        "timestamp_seconds": window_end.copy(),
    }


def _trailing_mean(x: np.ndarray, n: int) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    out = np.full(x.shape, np.nan, dtype=np.float64)
    if n <= 0 or x.shape[0] < n:
        return out
    finite = np.isfinite(x)
    filled = np.where(finite, x, 0.0)
    c = np.cumsum(filled, axis=0)
    k = np.cumsum(finite.astype(np.int64), axis=0)
    total = c[n - 1 :].copy()
    count = k[n - 1 :].copy()
    total[1:] -= c[: -n]
    count[1:] -= k[: -n]
    means = np.full(total.shape, np.nan, dtype=np.float64)
    ok = count == n
    means[ok] = total[ok] / n
    out[n - 1 :] = means
    return out


def stereo_production(stereo: np.ndarray, sr: int, origin_s: float) -> dict[str, np.ndarray]:
    """L/R correlation, side-to-mid energy, interchannel level. Same grid as mono."""
    if stereo.ndim != 2 or stereo.shape[1] != 2:
        raise RuntimeError(f"expected stereo (n, 2), got {stereo.shape}")
    grid = window_grid(stereo.shape[0], sr, origin_s)
    left = sliding_window_view(np.ascontiguousarray(stereo[:, 0]), grid["win"])[:: grid["hop"]]
    right = sliding_window_view(np.ascontiguousarray(stereo[:, 1]), grid["win"])[:: grid["hop"]]
    if left.shape[0] != grid["n_win"]:
        raise RuntimeError("stereo window count does not match the grid")
    corr = np.empty(grid["n_win"], dtype=np.float64)
    side_mid = np.empty(grid["n_win"], dtype=np.float64)
    ild = np.empty(grid["n_win"], dtype=np.float64)
    batch = 256
    for s in range(0, grid["n_win"], batch):
        e = min(s + batch, grid["n_win"])
        left64 = left[s:e].astype(np.float64)
        right64 = right[s:e].astype(np.float64)
        l0 = left64 - left64.mean(axis=1, keepdims=True)
        r0 = right64 - right64.mean(axis=1, keepdims=True)
        denom = np.sqrt(np.sum(l0 * l0, axis=1) * np.sum(r0 * r0, axis=1))
        corr_b = np.full(e - s, np.nan, dtype=np.float64)
        ok = denom > 1e-12
        corr_b[ok] = np.sum(l0[ok] * r0[ok], axis=1) / denom[ok]
        mid = 0.5 * (left64 + right64)
        side = 0.5 * (left64 - right64)
        side_mid[s:e] = np.sum(side * side, axis=1) / (np.sum(mid * mid, axis=1) + 1e-12)
        l_rms = np.sqrt(np.mean(left64 * left64, axis=1) + 1e-18)
        r_rms = np.sqrt(np.mean(right64 * right64, axis=1) + 1e-18)
        corr[s:e] = corr_b
        ild[s:e] = 20.0 * np.log10(l_rms / r_rms)
    return {
        "window_start_seconds": grid["window_start_seconds"],
        "window_end_seconds": grid["window_end_seconds"],
        "timestamp_seconds": grid["timestamp_seconds"],
        "lr_correlation": corr,
        "side_mid_ratio": side_mid,
        "interchannel_db": ild,
    }


def _k_weight(y: np.ndarray, sr: int) -> np.ndarray:
    meter = pyloudnorm.Meter(sr)
    weighted = np.asarray(y, dtype=np.float64)
    for stage in meter._filters.values():
        weighted = stage.apply_filter(weighted)
    return weighted


def _lufs_from_power(power: np.ndarray) -> np.ndarray:
    out = np.full(power.shape, np.nan, dtype=np.float64)
    ok = np.isfinite(power) & (power > 1e-20)
    out[ok] = LUFS_OFFSET + 10.0 * np.log10(power[ok])
    return out


def _window_mean_square(cumsum_sq: np.ndarray, end_sample: np.ndarray, n: int) -> np.ndarray:
    out = np.full(end_sample.shape, np.nan, dtype=np.float64)
    e = end_sample.astype(np.int64)
    ok = e >= n
    e_ok = e[ok]
    prev = np.zeros(e_ok.shape, dtype=np.float64)
    has_prev = e_ok - n > 0
    prev[has_prev] = cumsum_sq[e_ok[has_prev] - n - 1]
    out[ok] = (cumsum_sq[e_ok - 1] - prev) / n
    return out


def _frame_bank(y: np.ndarray, sr: int) -> dict[str, np.ndarray]:
    if sr != 16000:
        raise RuntimeError(f"mono features expect 16 kHz, got {sr}")
    if len(y) < N_FFT:
        raise RuntimeError("audio shorter than n_fft")
    import librosa

    n_frames = 1 + (len(y) - N_FFT) // STFT_HOP
    centroid = np.empty(n_frames, dtype=np.float64)
    bandwidth = np.empty(n_frames, dtype=np.float64)
    rolloff = np.empty(n_frames, dtype=np.float64)
    flatness = np.empty(n_frames, dtype=np.float64)
    flux = np.full(n_frames, np.nan, dtype=np.float64)
    onset = np.empty(n_frames, dtype=np.float64)
    mfcc = np.empty((n_frames, N_MFCC), dtype=np.float64)
    prev = None
    cursor = 0
    chunk = 4000
    while cursor < n_frames:
        take = min(chunk, n_frames - cursor)
        sample0 = cursor * STFT_HOP
        sample1 = sample0 + (take - 1) * STFT_HOP + N_FFT
        seg = np.ascontiguousarray(y[sample0:sample1], dtype=np.float32)
        spec = np.abs(librosa.stft(seg, n_fft=N_FFT, hop_length=STFT_HOP, center=False))
        if spec.shape[1] != take:
            raise RuntimeError(f"stft produced {spec.shape[1]} frames, expected {take}")
        power = np.square(spec)
        sl = slice(cursor, cursor + take)
        centroid[sl] = librosa.feature.spectral_centroid(S=spec, sr=sr, n_fft=N_FFT, hop_length=STFT_HOP)[0]
        bandwidth[sl] = librosa.feature.spectral_bandwidth(S=spec, sr=sr, n_fft=N_FFT, hop_length=STFT_HOP)[0]
        rolloff[sl] = librosa.feature.spectral_rolloff(
            S=spec, sr=sr, n_fft=N_FFT, hop_length=STFT_HOP, roll_percent=0.85
        )[0]
        flatness[sl] = librosa.feature.spectral_flatness(S=power)[0]
        onset[sl] = librosa.onset.onset_strength(S=spec, sr=sr, hop_length=STFT_HOP, center=False)
        # top_db=None: the default clips against the chunk maximum, which would
        # let later audio in the same block change earlier MFCCs.
        mfcc[sl] = librosa.feature.mfcc(S=librosa.power_to_db(power, ref=1.0, top_db=None), sr=sr, n_mfcc=N_MFCC).T
        mag = spec.astype(np.float64, copy=False)
        if prev is None:
            if take > 1:
                delta = mag[:, 1:] - mag[:, :-1]
                flux[cursor + 1 : cursor + take] = np.sqrt(np.sum(delta * delta, axis=0))
        else:
            first = mag[:, 0] - prev
            flux[cursor] = float(np.sqrt(np.dot(first, first)))
            if take > 1:
                delta = mag[:, 1:] - mag[:, :-1]
                flux[cursor + 1 : cursor + take] = np.sqrt(np.sum(delta * delta, axis=0))
        prev = mag[:, -1].copy()
        cursor += take
    peaks = np.zeros(n_frames, dtype=np.float64)
    if n_frames > 2:
        peaks[2:] = (onset[2:] > onset[1:-1]) & (onset[2:] > onset[:-2])
    avail = (np.arange(n_frames) * STFT_HOP + N_FFT) / float(sr)
    return {
        "avail_s": avail,
        "centroid": centroid,
        "bandwidth": bandwidth,
        "rolloff": rolloff,
        "flatness": flatness,
        "flux": flux,
        "onset": onset,
        "peaks": peaks,
        "mfcc": mfcc,
    }


def _reduce_frames(frame: dict[str, np.ndarray], window_start: np.ndarray, window_end: np.ndarray) -> dict[str, np.ndarray]:
    avail = frame["avail_s"]
    # Frame i is included when window_start < avail <= window_end.
    hi = np.searchsorted(avail, window_end, side="right")
    lo = np.searchsorted(avail, window_start, side="right")
    names = ["centroid", "bandwidth", "rolloff", "flatness", "flux", "onset", "peaks"]
    prefix = {name: np.cumsum(np.nan_to_num(frame[name], nan=0.0)) for name in names}
    pcount = {name: np.cumsum(np.isfinite(frame[name]).astype(np.int64)) for name in names}
    mfcc_c = np.cumsum(frame["mfcc"], axis=0)
    mfcc_c2 = np.cumsum(frame["mfcc"] ** 2, axis=0)
    delta = np.zeros_like(frame["mfcc"])
    delta[1:] = frame["mfcc"][1:] - frame["mfcc"][:-1]
    delta_c = np.cumsum(delta, axis=0)

    def win_sum(c, a, b):
        total = np.zeros((b.shape[0],) + c.shape[1:], dtype=np.float64)
        ok = b > 0
        total[ok] = c[b[ok] - 1]
        prev = a > 0
        total[prev] -= c[a[prev] - 1]
        return total

    def win_count(c, a, b):
        total = np.zeros(b.shape[0], dtype=np.int64)
        ok = b > 0
        total[ok] = c[b[ok] - 1]
        prev = a > 0
        total[prev] -= c[a[prev] - 1]
        return total

    out: dict[str, np.ndarray] = {}
    for name in names:
        total = win_sum(prefix[name], lo, hi)
        count = win_count(pcount[name], lo, hi).astype(np.float64)
        mean = np.full(window_end.shape, np.nan, dtype=np.float64)
        ok = count > 0
        mean[ok] = total[ok] / count[ok]
        out[name] = mean
    out["onset_density"] = out.pop("peaks") * (16000 / STFT_HOP)
    mfcc_sum = win_sum(mfcc_c, lo, hi)
    mfcc_sq = win_sum(mfcc_c2, lo, hi)
    n_mf = win_count(np.cumsum(np.ones(len(avail), dtype=np.int64)), lo, hi).astype(np.float64)
    mfcc_mean = np.full_like(mfcc_sum, np.nan)
    mfcc_std = np.full_like(mfcc_sum, np.nan)
    ok = n_mf > 0
    mfcc_mean[ok] = mfcc_sum[ok] / n_mf[ok, None]
    var = np.full_like(mfcc_sum, np.nan)
    var[ok] = mfcc_sq[ok] / n_mf[ok, None] - mfcc_mean[ok] ** 2
    mfcc_std[ok] = np.sqrt(np.maximum(var[ok], 0.0))
    dsum = win_sum(delta_c, lo, hi)
    dcount = np.maximum(n_mf - 1.0, 0.0)
    mfcc_delta = np.full_like(mfcc_sum, np.nan)
    dok = dcount > 0
    mfcc_delta[dok] = dsum[dok] / dcount[dok, None]
    out["mfcc"] = mfcc_mean
    out["mfcc_std"] = mfcc_std
    out["mfcc_delta"] = mfcc_delta
    return out


def _rhythm(onset: np.ndarray, peaks: np.ndarray, avail: np.ndarray, window_end: np.ndarray, frame_rate: float) -> tuple[np.ndarray, np.ndarray]:
    mod = np.full(window_end.shape, np.nan, dtype=np.float64)
    rate = np.full(window_end.shape, np.nan, dtype=np.float64)
    lag_lo = int(np.ceil(frame_rate / MOD_HZ_HI))
    lag_hi = int(np.floor(frame_rate / MOD_HZ_LO))
    for i, end in enumerate(window_end):
        hi = int(np.searchsorted(avail, end, side="right"))
        lo = int(np.searchsorted(avail, end - RHYTHM_S, side="right"))
        if hi - lo < int(frame_rate * 4):
            continue
        seg = onset[lo:hi]
        if not np.isfinite(seg).all():
            continue
        seg = seg - seg.mean()
        corr = np.correlate(seg, seg, mode="full")
        pos = corr[len(seg) :]
        if lag_hi >= len(pos) or lag_lo >= len(pos):
            continue
        local = pos[lag_lo : lag_hi + 1]
        if local.size == 0 or not np.isfinite(local).any():
            continue
        lag = int(np.argmax(local)) + lag_lo
        if lag <= 0:
            continue
        mod[i] = frame_rate / lag
        span = float(avail[hi - 1] - avail[lo])
        if span > 0:
            rate[i] = float(np.sum(peaks[lo:hi]) / span)
    return mod, rate


def mono_features(y: np.ndarray, sr: int, origin_s: float = 0.0) -> dict[str, np.ndarray]:
    y = np.asarray(y, dtype=np.float32)
    grid = window_grid(len(y), sr, origin_s)
    view = sliding_window_view(np.ascontiguousarray(y), grid["win"])[:: grid["hop"]]
    if view.shape[0] != grid["n_win"]:
        raise RuntimeError("mono window count does not match the grid")
    rms = np.empty(grid["n_win"], dtype=np.float64)
    peak = np.empty(grid["n_win"], dtype=np.float64)
    zcr = np.empty(grid["n_win"], dtype=np.float64)
    silence = np.empty(grid["n_win"], dtype=np.float64)
    sub = int(round(0.050 * sr))
    n_sub = grid["win"] // sub
    batch = 256
    for s in range(0, grid["n_win"], batch):
        e = min(s + batch, grid["n_win"])
        v = view[s:e].astype(np.float64)
        mean_sq = np.mean(v * v, axis=1)
        rms[s:e] = np.sqrt(mean_sq + 1e-18)
        peak[s:e] = np.max(np.abs(v), axis=1)
        signs = np.sign(v)
        signs[signs == 0] = 1.0
        zcr[s:e] = np.mean(np.abs(np.diff(signs, axis=1)) > 0, axis=1)
        sub_v = v[:, : n_sub * sub].reshape(e - s, n_sub, sub)
        sub_rms = np.sqrt(np.mean(sub_v * sub_v, axis=2) + 1e-18)
        silence[s:e] = np.mean(20.0 * np.log10(sub_rms) < SILENCE_DBFS, axis=1)
    crest = peak / np.maximum(rms, 1e-8)

    weighted = _k_weight(y, sr)
    csum = np.cumsum(weighted * weighted)
    momentary = _lufs_from_power(_window_mean_square(csum, grid["end_sample"], int(round(MOMENTARY_S * sr))))
    short_term = _lufs_from_power(_window_mean_square(csum, grid["end_sample"], int(round(SHORT_TERM_S * sr))))
    lufs_var_5 = _trailing_var(momentary, int(round(5.0 / HOP_S)))
    lufs_var_15 = _trailing_var(momentary, int(round(15.0 / HOP_S)))

    frames = _frame_bank(y, sr)
    reduced = _reduce_frames(frames, grid["window_start_seconds"] - origin_s, grid["window_end_seconds"] - origin_s)
    mod_hz, onset_rate = _rhythm(
        frames["onset"], frames["peaks"], frames["avail_s"], grid["window_end_seconds"] - origin_s, sr / STFT_HOP
    )

    columns: dict[str, np.ndarray] = {
        "window_start_seconds": grid["window_start_seconds"],
        "window_end_seconds": grid["window_end_seconds"],
        "timestamp_seconds": grid["timestamp_seconds"],
        "rms": rms,
        "rms_dbfs": 20.0 * np.log10(rms),
        "peak": peak,
        "crest": crest,
        "zcr": zcr.astype(np.float64),
        "spec_centroid": reduced["centroid"],
        "spec_bandwidth": reduced["bandwidth"],
        "spec_rolloff": reduced["rolloff"],
        "spec_flatness": reduced["flatness"],
        "spec_flux": reduced["flux"],
        "onset_mean": reduced["onset"],
        "onset_density": reduced["onset_density"],
        "silence_fraction": silence,
        "momentary_lufs": momentary,
        "short_term_lufs": short_term,
        "lufs_var_5s": lufs_var_5,
        "lufs_var_15s": lufs_var_15,
        "rhythm_mod_hz": mod_hz,
        "onset_rate_8s": onset_rate,
    }
    for i in range(N_MFCC):
        columns[f"mfcc_{i:02d}"] = reduced["mfcc"][:, i]
        columns[f"mfcc_std_{i:02d}"] = reduced["mfcc_std"][:, i]
        columns[f"mfcc_delta_{i:02d}"] = reduced["mfcc_delta"][:, i]
    return columns


def _trailing_var(x: np.ndarray, n: int) -> np.ndarray:
    mean = _trailing_mean(x, n)
    mean_sq = _trailing_mean(np.where(np.isfinite(x), x * x, np.nan), n)
    var = mean_sq - mean**2
    ok = np.isfinite(var)
    var = var.copy()
    var[ok] = np.maximum(var[ok], 0.0)
    return var


ROLL_COLUMNS = [
    "rms",
    "rms_dbfs",
    "peak",
    "crest",
    "zcr",
    "spec_centroid",
    "spec_bandwidth",
    "spec_rolloff",
    "spec_flatness",
    "spec_flux",
    "onset_mean",
    "onset_density",
    "silence_fraction",
    "momentary_lufs",
    "short_term_lufs",
    "lufs_var_5s",
    "lufs_var_15s",
    "rhythm_mod_hz",
    "onset_rate_8s",
    "lr_correlation",
    "side_mid_ratio",
    "interchannel_db",
] + [f"mfcc_{i:02d}" for i in range(N_MFCC)]


def add_trailing_means(columns: dict[str, np.ndarray]) -> None:
    for name in ROLL_COLUMNS:
        if name not in columns:
            continue
        columns[f"{name}_mean_5s"] = _trailing_mean(columns[name], int(round(5.0 / HOP_S)))
        columns[f"{name}_mean_15s"] = _trailing_mean(columns[name], int(round(15.0 / HOP_S)))
