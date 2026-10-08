"""Experiment 001 causality and seam-safe resampling."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np
from scipy.signal import resample_poly

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from hush.audio import resample_concat  # noqa: E402
from hush.change import DISTANCE_COLUMNS, compute_change_scores  # noqa: E402
from hush.features import mono_features  # noqa: E402


class ContinuousResample(unittest.TestCase):
    def test_concat_matches_full_and_per_chunk_does_not(self):
        sr = 48000
        n = sr * 2
        t = np.arange(n) / sr
        x = np.sin(2 * np.pi * 440 * t).astype(np.float64)
        split = sr
        full = resample_poly(x, up=1, down=3, window=("kaiser", 5.0), padtype="constant")
        continuous = resample_concat([x[:split], x[split:]])
        np.testing.assert_allclose(continuous, full, atol=1e-6)
        indep = np.concatenate(
            [
                resample_poly(x[:split], up=1, down=3, window=("kaiser", 5.0), padtype="constant"),
                resample_poly(x[split:], up=1, down=3, window=("kaiser", 5.0), padtype="constant"),
            ]
        )
        boundary = split // 3
        self.assertFalse(
            np.allclose(indep[boundary - 80 : boundary + 80], full[boundary - 80 : boundary + 80], atol=1e-4)
        )


class AvailabilityTime(unittest.TestCase):
    def test_click_on_the_boundary_is_not_in_the_earlier_window(self):
        sr = 16000
        y = np.zeros(12 * sr, dtype=np.float32)
        y[10 * sr] = 1.0
        cols = mono_features(y, sr)
        by_t = {round(float(t), 3): float(p) for t, p in zip(cols["timestamp_seconds"], cols["peak"])}
        self.assertLess(by_t[10.0], 0.1)
        self.assertGreater(by_t[10.5], 0.9)
        self.assertGreater(by_t[11.0], 0.9)
        self.assertTrue(np.allclose(cols["timestamp_seconds"], cols["window_end_seconds"]))
        self.assertTrue(np.allclose(cols["window_end_seconds"] - cols["window_start_seconds"], 1.0))

    def test_future_audio_does_not_change_past_scores(self):
        sr = 16000
        rng = np.random.default_rng(0)
        y = rng.normal(0, 0.05, size=45 * sr).astype(np.float32)
        y2 = y.copy()
        cut = 40 * sr
        y2[cut:] = rng.normal(0, 0.8, size=y2.shape[0] - cut).astype(np.float32)
        a = mono_features(y, sr)
        b = mono_features(y2, sr)
        past = a["timestamp_seconds"] <= 40.0
        for key, values in a.items():
            if values.dtype.kind not in "fc":
                continue
            np.testing.assert_allclose(values[past], b[key][past], equal_nan=True, err_msg=key)
        scores_a = compute_change_scores(a)
        scores_b = compute_change_scores(b)
        for key in ("euclid_30", "euclid_60", "cosine_60", "symkl_60", "energy_distance_60s"):
            np.testing.assert_allclose(scores_a[key][past], scores_b[key][past], equal_nan=True, err_msg=key)
        self.assertTrue(np.isfinite(scores_a["euclid_30"][a["timestamp_seconds"] == 36.0]).all())


class FrozenReference(unittest.TestCase):
    def test_freeze_follows_a_sustained_shift_and_ignores_the_future(self):
        n = 560
        timestamps = 1.0 + np.arange(n) * 0.5
        rng = np.random.default_rng(1)
        base = rng.normal(scale=0.05, size=(n, len(DISTANCE_COLUMNS)))
        jump = int(np.where(np.isclose(timestamps, 250.0))[0][0])
        shifted = base.copy()
        shifted[jump:] += 6.0
        edited = shifted.copy()
        edited[int(np.where(np.isclose(timestamps, 275.0))[0][0]) + 1 :] += 20.0

        def pack(matrix):
            cols = {name: matrix[:, i] for i, name in enumerate(DISTANCE_COLUMNS)}
            cols["timestamp_seconds"] = timestamps
            cols["onset_density"] = np.ones(n)
            cols["rhythm_mod_hz"] = np.ones(n)
            return cols

        first = compute_change_scores(pack(shifted))
        second = compute_change_scores(pack(edited))
        past = timestamps <= 275.0
        np.testing.assert_allclose(first["euclid_60"][past], second["euclid_60"][past], equal_nan=True)
        np.testing.assert_array_equal(first["baseline_state"][past], second["baseline_state"][past])
        frozen_t = timestamps[first["baseline_state"] == "frozen"]
        self.assertGreater(frozen_t.size, 0)
        self.assertGreaterEqual(float(frozen_t[0]), 250.0)
        self.assertLess(float(frozen_t[0]), 270.0)


if __name__ == "__main__":
    unittest.main()
