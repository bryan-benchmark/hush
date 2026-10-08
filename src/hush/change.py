"""Unsupervised change scores. Online scores use only rows at or before t.

Foote columns are the exception: they look 5 s ahead and are named ``foote_*``.
The frozen baseline is pre-registered in ``PARAMS``. Do not retune it on labels.
"""

from __future__ import annotations

import numpy as np
from scipy.spatial.distance import cdist

from hush.features import HOP_S, N_MFCC

EXPERIMENT_SPEC_VERSION = "exp001-v1"
STD_FLOOR = 1e-6
Z_CLIP = 8.0
LUFS_FLOOR = -70.0
MIN_BASELINE_S = 20.0
RECENT_S = 5.0
CONTEXTS_S = (30.0, 60.0, 120.0)
ENERGY_CONTEXT_S = 60.0
MAHAL_CONTEXTS_S = (60.0, 120.0)
MAHAL_EVERY_S = 1.0
SHRINK = 0.2

# Frozen-reference diagnostic. These constants are part of exp001-v1.
ARM_S = 180.0
THRESHOLD_S = 600.0
THRESHOLD_EXCLUDE_S = 30.0
THRESHOLD_MAD = 5.0
FREEZE_HOLD_S = 8.0
FROZEN_CLOUD_S = 60.0
FROZEN_GAP_S = 5.0
RELEASE_FRACTION = 0.5
RELEASE_HOLD_S = 10.0
MIN_FREEZE_S = 15.0
REFRACTORY_S = 20.0

DISTANCE_COLUMNS = [
    "rms_dbfs",
    "crest",
    "zcr",
    "spec_centroid",
    "spec_bandwidth",
    "spec_rolloff",
    "spec_flatness",
    "spec_flux",
    "onset_mean",
    "silence_fraction",
    "short_term_lufs",
    "lufs_var_15s",
    *[f"mfcc_{i:02d}" for i in range(N_MFCC)],
]
MFCC_COLUMNS = [f"mfcc_{i:02d}" for i in range(N_MFCC)]
SPECTRAL_COLUMNS = ["spec_centroid", "spec_bandwidth", "spec_rolloff", "spec_flatness", "spec_flux"]

PARAMS = {
    "experiment_spec_version": EXPERIMENT_SPEC_VERSION,
    "std_floor": STD_FLOOR,
    "z_abs_clip": Z_CLIP,
    "symkl_variance_floor_in_z_space": 1.0,
    "lufs_floor_for_distance_only": LUFS_FLOOR,
    "min_baseline_s": MIN_BASELINE_S,
    "recent_s": RECENT_S,
    "contexts_s": list(CONTEXTS_S),
    "energy_context_s": ENERGY_CONTEXT_S,
    "energy_distance": "Szekely, pairwise L2, diagonal excluded",
    "mahal_contexts_s": list(MAHAL_CONTEXTS_S),
    "mahal_every_s": MAHAL_EVERY_S,
    "mahal_shrink_toward_diag": SHRINK,
    "cosine": "both means divided by baseline std; means are not removed",
    "foote": "non-causal, 5 s after the timestamp; scale from the past 5 s only",
    "arm_s": ARM_S,
    "threshold": (
        f"median + {THRESHOLD_MAD} * raw MAD of euclid_60 over the trailing {THRESHOLD_S}s, "
        f"excluding the last {THRESHOLD_EXCLUDE_S}s. Until {THRESHOLD_S}s exists, use the shorter available history."
    ),
    "freeze_hold_s": FREEZE_HOLD_S,
    "frozen_cloud": f"({FROZEN_CLOUD_S + FROZEN_GAP_S} s, {FROZEN_GAP_S} s] before freeze",
    "release_fraction": RELEASE_FRACTION,
    "release_hold_s": RELEASE_HOLD_S,
    "min_freeze_s": MIN_FREEZE_S,
    "refractory_s": REFRACTORY_S,
    "distance_columns": DISTANCE_COLUMNS,
}


def _rows(hop: float, seconds: float) -> int:
    n = int(round(seconds / hop))
    if abs(n * hop - seconds) > 1e-9:
        raise RuntimeError(f"{seconds} s is not an integer number of {hop} s hops")
    return n


def _z(block: np.ndarray, mu: np.ndarray, sig: np.ndarray) -> np.ndarray:
    """Baseline standardization. Clip so a constant feature cannot explode the score."""
    scale = np.maximum(sig, STD_FLOOR)
    return np.clip((block - mu) / scale, -Z_CLIP, Z_CLIP)


def _cosine_distance(a: np.ndarray, b: np.ndarray) -> float:
    na = float(np.linalg.norm(a))
    nb = float(np.linalg.norm(b))
    if na < 1e-12 or nb < 1e-12:
        return np.nan
    return float(1.0 - np.dot(a, b) / (na * nb))


def _sym_kl(
    mu_p: np.ndarray,
    var_p: np.ndarray,
    mu_q: np.ndarray,
    var_q: np.ndarray,
    var_floor: float = 1.0,
) -> float:
    # Inputs are already in baseline z-space, where a real feature has variance near 1.
    # A 5 s window of a slow feature would otherwise report variance near 0 and explode the KL.
    vp = np.maximum(var_p, var_floor)
    vq = np.maximum(var_q, var_floor)

    def kl(mu_a, va, mu_b, vb):
        return 0.5 * float(np.sum(np.log(vb / va) + (va + (mu_a - mu_b) ** 2) / vb - 1.0))

    return kl(mu_p, vp, mu_q, vq) + kl(mu_q, vq, mu_p, vp)


def _energy_distance(x: np.ndarray, y: np.ndarray) -> float:
    """Székely energy distance. Zero self-distances are excluded."""
    n = x.shape[0]
    m = y.shape[0]
    if n < 2 or m < 2:
        return np.nan
    dxy = cdist(x, y, metric="euclidean")
    dxx = cdist(x, x, metric="euclidean")
    dyy = cdist(y, y, metric="euclidean")
    cross = float(dxy.mean())
    within_x = float(dxx.sum() / (n * (n - 1)))
    within_y = float(dyy.sum() / (m * (m - 1)))
    return 2.0 * cross - within_x - within_y


def _mean_offdiag_cosine(block: np.ndarray) -> float:
    norms = np.linalg.norm(block, axis=1)
    if np.any(norms < 1e-12):
        keep = norms >= 1e-12
        block = block[keep]
        norms = norms[keep]
    if block.shape[0] < 2:
        return np.nan
    unit = block / norms[:, None]
    sim = unit @ unit.T
    n = sim.shape[0]
    return float((sim.sum() - np.trace(sim)) / (n * (n - 1)))


def _cross_cosine(a: np.ndarray, b: np.ndarray) -> float:
    na = np.linalg.norm(a, axis=1)
    nb = np.linalg.norm(b, axis=1)
    a = a[na >= 1e-12]
    b = b[nb >= 1e-12]
    na = na[na >= 1e-12]
    nb = nb[nb >= 1e-12]
    if a.shape[0] == 0 or b.shape[0] == 0:
        return np.nan
    unit_a = a / na[:, None]
    unit_b = b / nb[:, None]
    return float(np.mean(unit_a @ unit_b.T))


def _finite(block: np.ndarray) -> np.ndarray:
    if block.size == 0:
        return block.reshape(0, block.shape[1] if block.ndim == 2 else 0)
    return block[np.isfinite(block).all(axis=1)]


def _mahalanobis(z_recent: np.ndarray, z_base: np.ndarray) -> float:
    """Mahalanobis in already-clipped z-space. Shrink covariance toward I."""
    if z_base.shape[0] < 2:
        return np.nan
    cov = np.cov(z_base, rowvar=False)
    if cov.ndim == 0 or not np.isfinite(cov).all():
        cov = np.eye(z_base.shape[1])
    shrunk = (1.0 - SHRINK) * cov + SHRINK * np.eye(cov.shape[0])
    shrunk = shrunk + np.eye(shrunk.shape[0]) * 1e-3
    delta = z_recent.mean(axis=0) - z_base.mean(axis=0)
    solved = np.linalg.solve(shrunk, delta)
    value = float(np.dot(delta, solved))
    if value < 0 or not np.isfinite(value):
        return np.nan
    return float(np.sqrt(value))


def _subspace_euclid(recent: np.ndarray, base: np.ndarray, idx: np.ndarray) -> float:
    b = base[:, idx]
    r = recent[:, idx]
    if b.shape[0] < 2 or r.shape[0] < 1:
        return np.nan
    mu = b.mean(axis=0)
    sig = b.std(axis=0)
    return float(np.linalg.norm(_z(r, mu, sig).mean(axis=0)))


def compute_change_scores(columns: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    hop = HOP_S
    n = len(columns["timestamp_seconds"])
    missing = [name for name in DISTANCE_COLUMNS if name not in columns]
    if missing:
        raise RuntimeError(f"missing distance columns: {missing}")
    x = np.column_stack([columns[name] for name in DISTANCE_COLUMNS]).astype(np.float64)
    lufs_idx = [DISTANCE_COLUMNS.index(name) for name in ("short_term_lufs", "lufs_var_15s")]
    for idx in lufs_idx:
        bad = ~np.isfinite(x[:, idx])
        x[bad, idx] = LUFS_FLOOR

    col = {name: i for i, name in enumerate(DISTANCE_COLUMNS)}
    mfcc_idx = np.array([col[name] for name in MFCC_COLUMNS])
    spec_idx = np.array([col[name] for name in SPECTRAL_COLUMNS])
    lufs_i = col["short_term_lufs"]
    lufs_var_i = col["lufs_var_15s"]

    n_recent = _rows(hop, RECENT_S)
    min_base = _rows(hop, MIN_BASELINE_S)
    context_rows = {w: _rows(hop, w) for w in CONTEXTS_S}
    out: dict[str, np.ndarray] = {}
    for w in CONTEXTS_S:
        tag = int(w)
        for name in (
            "euclid",
            "cosine",
            "symkl",
            "mfcc_euclid",
            "lufs_shift",
            "lufs_var_ratio",
            "spectral_euclid",
            "onset_shift",
            "modulation_shift",
        ):
            out[f"{name}_{tag}"] = np.full(n, np.nan)
    for w in MAHAL_CONTEXTS_S:
        out[f"mahal_{int(w)}"] = np.full(n, np.nan)
    out["energy_distance_60s"] = np.full(n, np.nan)
    out["foote_cosine_distance"] = np.full(n, np.nan)
    out["foote_novelty"] = np.full(n, np.nan)

    mod = columns["rhythm_mod_hz"]
    onset_density = columns["onset_density"]

    for i in range(n):
        r0 = i - n_recent + 1
        r1 = i + 1
        if r0 < 0:
            continue
        recent = _finite(x[r0:r1])
        if recent.shape[0] < n_recent // 2:
            continue
        recent_mean = recent.mean(axis=0)
        for w, n_w in context_rows.items():
            b0 = i - n_w + 1
            b1 = i - n_recent + 1
            if b0 < 0:
                continue
            base = _finite(x[b0:b1])
            if base.shape[0] < min_base:
                continue
            mu = base.mean(axis=0)
            sig = base.std(axis=0)
            z_recent = _z(recent, mu, sig)
            z_base = _z(base, mu, sig)
            scale = np.maximum(sig, STD_FLOOR)
            tag = int(w)
            out[f"euclid_{tag}"][i] = float(np.linalg.norm(z_recent.mean(axis=0) - z_base.mean(axis=0)))
            out[f"cosine_{tag}"][i] = _cosine_distance(recent_mean / scale, mu / scale)
            out[f"symkl_{tag}"][i] = _sym_kl(
                z_recent.mean(axis=0), z_recent.var(axis=0), z_base.mean(axis=0), z_base.var(axis=0)
            )
            out[f"mfcc_euclid_{tag}"][i] = _subspace_euclid(recent, base, mfcc_idx)
            out[f"spectral_euclid_{tag}"][i] = _subspace_euclid(recent, base, spec_idx)
            out[f"lufs_shift_{tag}"][i] = float(abs(recent_mean[lufs_i] - mu[lufs_i]))
            out[f"lufs_var_ratio_{tag}"][i] = float(
                (recent_mean[lufs_var_i] + STD_FLOOR) / (mu[lufs_var_i] + STD_FLOOR)
            )
            if np.isfinite(onset_density[r0:r1]).all() and np.isfinite(onset_density[b0:b1]).all():
                out[f"onset_shift_{tag}"][i] = float(abs(np.mean(onset_density[r0:r1]) - np.mean(onset_density[b0:b1])))
            if np.isfinite(mod[r0:r1]).all() and np.isfinite(mod[b0:b1]).all():
                out[f"modulation_shift_{tag}"][i] = float(abs(np.mean(mod[r0:r1]) - np.mean(mod[b0:b1])))
            if int(w) in {int(v) for v in MAHAL_CONTEXTS_S} and abs(columns["timestamp_seconds"][i] - round(columns["timestamp_seconds"][i])) < 1e-6:
                out[f"mahal_{tag}"][i] = _mahalanobis(z_recent, z_base)
            if w == ENERGY_CONTEXT_S:
                out["energy_distance_60s"][i] = _energy_distance(z_recent, z_base)

        f1 = i + 1
        f2 = i + 1 + n_recent
        if f2 <= n:
            past = _finite(x[r0:r1])
            future = _finite(x[f1:f2])
            if past.shape[0] >= n_recent // 2 and future.shape[0] >= n_recent // 2:
                scale = np.maximum(past.std(axis=0), STD_FLOOR)
                past_s = past / scale
                future_s = future / scale
                out["foote_cosine_distance"][i] = _cosine_distance(past_s.mean(axis=0), future_s.mean(axis=0))
                sim_p = _mean_offdiag_cosine(past_s)
                sim_f = _mean_offdiag_cosine(future_s)
                sim_c = _cross_cosine(past_s, future_s)
                if np.isfinite([sim_p, sim_f, sim_c]).all():
                    out["foote_novelty"][i] = 0.5 * (sim_p + sim_f) - sim_c

    for w in MAHAL_CONTEXTS_S:
        name = f"mahal_{int(w)}"
        filled = out[name].copy()
        last = np.nan
        for i in range(n):
            if np.isfinite(out[name][i]):
                last = out[name][i]
            elif np.isfinite(last):
                filled[i] = last
        out[name] = filled

    _frozen_reference(columns, x, out)
    med_n = _rows(hop, 15.0)
    out["euclid_60_median_15"] = _trailing_median(out["euclid_60"], med_n)
    return out


def _trailing_median(x: np.ndarray, n: int) -> np.ndarray:
    out = np.full(x.shape, np.nan, dtype=np.float64)
    if len(x) < n:
        return out
    view = np.lib.stride_tricks.sliding_window_view(x, n)
    finite = np.isfinite(view).all(axis=1)
    med = np.full(view.shape[0], np.nan)
    if finite.any():
        med[finite] = np.median(view[finite], axis=1)
    out[n - 1 :] = med
    return out


def _frozen_reference(columns: dict[str, np.ndarray], x: np.ndarray, out: dict[str, np.ndarray]) -> None:
    hop = HOP_S
    n = x.shape[0]
    timestamps = columns["timestamp_seconds"]
    euclid = out["euclid_60"]
    frozen_euclid = np.full(n, np.nan)
    frozen_energy = np.full(n, np.nan)
    state = np.array(["rolling"] * n, dtype=object)
    n_recent = _rows(hop, RECENT_S)
    n_cloud = _rows(hop, FROZEN_CLOUD_S + FROZEN_GAP_S)
    n_gap = _rows(hop, FROZEN_GAP_S)
    n_thr = _rows(hop, THRESHOLD_S)
    n_ex = _rows(hop, THRESHOLD_EXCLUDE_S)

    phase = "rolling"
    above = 0.0
    below = 0.0
    refractory_until = -np.inf
    freeze_i = -1
    mu = sig = cloud = None
    euclid_at_freeze = np.nan
    first_finite = np.nan

    for i in range(n):
        t = float(timestamps[i])
        if np.isfinite(euclid[i]) and not np.isfinite(first_finite):
            first_finite = t
        r0 = i - n_recent + 1
        recent = _finite(x[r0:i + 1]) if r0 >= 0 else x[:0]
        if phase == "frozen":
            state[i] = "frozen"
            if mu is not None and recent.shape[0] >= n_recent // 2:
                z_recent = _z(recent, mu, sig)
                z_cloud = _z(cloud, mu, sig)
                frozen_euclid[i] = float(np.linalg.norm(z_recent.mean(axis=0) - z_cloud.mean(axis=0)))
                frozen_energy[i] = _energy_distance(z_recent, z_cloud)
            held = (t - float(timestamps[freeze_i])) >= MIN_FREEZE_S - 1e-9
            if held and np.isfinite(frozen_euclid[i]) and frozen_euclid[i] < RELEASE_FRACTION * euclid_at_freeze:
                below += hop
            else:
                below = 0.0
            if below >= RELEASE_HOLD_S - 1e-9:
                phase = "rolling"
                refractory_until = t + REFRACTORY_S
                above = 0.0
                below = 0.0
                mu = sig = cloud = None
            continue

        state[i] = "rolling"
        if t < refractory_until or not np.isfinite(first_finite) or (t - first_finite) < ARM_S:
            continue
        h0 = max(0, i - n_thr + 1)
        h1 = i - n_ex + 1
        if h1 <= h0:
            continue
        hist = euclid[h0:h1]
        hist = hist[np.isfinite(hist)]
        if hist.size < _rows(hop, MIN_BASELINE_S):
            continue
        med = float(np.median(hist))
        mad = float(np.median(np.abs(hist - med)))
        threshold = med + THRESHOLD_MAD * mad
        if np.isfinite(euclid[i]) and euclid[i] > threshold:
            above += hop
        else:
            above = 0.0
        if above < FREEZE_HOLD_S - 1e-9:
            continue
        c0 = i - n_cloud + 1
        c1 = i - n_gap + 1
        if c0 < 0 or c1 <= c0:
            above = 0.0
            continue
        frozen_cloud = _finite(x[c0:c1])
        if frozen_cloud.shape[0] < _rows(hop, MIN_BASELINE_S):
            above = 0.0
            continue
        mu = frozen_cloud.mean(axis=0)
        sig = frozen_cloud.std(axis=0)
        cloud = frozen_cloud
        if recent.shape[0] < n_recent // 2:
            above = 0.0
            mu = sig = cloud = None
            continue
        z_recent = _z(recent, mu, sig)
        z_cloud = _z(cloud, mu, sig)
        euclid_at_freeze = float(np.linalg.norm(z_recent.mean(axis=0) - z_cloud.mean(axis=0)))
        frozen_euclid[i] = euclid_at_freeze
        frozen_energy[i] = _energy_distance(z_recent, z_cloud)
        phase = "frozen"
        state[i] = "frozen"
        freeze_i = i
        below = 0.0
        above = 0.0

    out["frozen_euclid"] = frozen_euclid
    out["frozen_energy_distance"] = frozen_energy
    out["baseline_state"] = state
