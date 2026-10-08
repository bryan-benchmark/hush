"""Experiment 003 causality: the current window is not its own reference."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from hush.program_cloud import (  # noqa: E402
    MEMORY_S,
    MIN_REFERENCE_S,
    WINDOW_S,
    anomaly_scores,
    window_bounds,
)


def _embeddings(n: int, dim: int = 4, shift_at: int | None = None) -> np.ndarray:
    base = np.zeros(dim, dtype=np.float64)
    base[0] = 1.0
    rows = np.repeat(base[None, :], n, axis=0)
    if shift_at is not None:
        rows[shift_at:] = 0.0
        rows[shift_at:, 1] = 1.0
    return rows


class CausalCloud(unittest.TestCase):
    def test_windows_are_ten_seconds_on_a_one_second_grid(self):
        starts, ends = window_bounds(30.0)
        self.assertAlmostEqual(float(starts[0]), 0.0)
        self.assertAlmostEqual(float(ends[0]), WINDOW_S)
        self.assertAlmostEqual(float(ends[1] - ends[0]), 1.0)
        self.assertAlmostEqual(float(ends[-1]), 30.0)

    def test_score_ignores_the_current_window_and_future_windows(self):
        starts, ends = window_bounds(MEMORY_S + MIN_REFERENCE_S + WINDOW_S)
        rows = _embeddings(len(starts), shift_at=len(starts) // 2)
        original = rows.copy()
        scores, counts, _spans = anomaly_scores(starts, ends, rows)
        defined = np.flatnonzero(np.isfinite(scores))
        self.assertGreater(len(defined), 0)
        target = int(defined[len(defined) // 2])
        self.assertNotIn(target, np.flatnonzero(ends <= starts[target] + 1e-9))
        rows[target + 1 :] = 0.0
        rows[target + 1 :, 2] = 1.0
        again, _, _ = anomaly_scores(starts, ends, rows)
        self.assertAlmostEqual(float(again[target]), float(scores[target]))
        self.assertGreater(counts[target], 0)
        self.assertFalse(np.allclose(rows[target + 1], original[target + 1]))

    def test_overlapping_hops_are_outside_the_reference(self):
        starts, ends = window_bounds(MEMORY_S + WINDOW_S)
        rows = _embeddings(len(starts))
        index = len(starts) - 1
        reference = np.flatnonzero((ends <= starts[index] + 1e-9) & (ends > starts[index] - MEMORY_S))
        overlap = float(ends[reference[-1]])
        self.assertLessEqual(overlap, float(starts[index]) + 1e-9)
        self.assertGreater(float(ends[index - 1]), float(starts[index]))

    def test_warmup_stays_null_until_a_minute_of_reference_exists(self):
        starts, ends = window_bounds(MIN_REFERENCE_S + 2 * WINDOW_S)
        scores, _, spans = anomaly_scores(starts, ends, _embeddings(len(starts)))
        early = ends < (WINDOW_S + MIN_REFERENCE_S - 1.0)
        self.assertTrue(np.all(~np.isfinite(scores[early])))
        self.assertTrue(np.isfinite(scores[-1]))
        self.assertGreaterEqual(float(spans[-1]), MIN_REFERENCE_S)

    def test_a_new_direction_is_far_from_an_established_cloud(self):
        starts, ends = window_bounds(MEMORY_S + WINDOW_S)
        rows = _embeddings(len(starts))
        scores, _, _ = anomaly_scores(starts, ends, rows)
        defined = scores[np.isfinite(scores)]
        self.assertLess(float(np.max(defined)), 1e-6)
        rows[-1] = np.array([0.0, 1.0, 0.0, 0.0])
        shifted, _, _ = anomaly_scores(starts, ends, rows)
        self.assertAlmostEqual(float(shifted[-1]), 1.0)


if __name__ == "__main__":
    unittest.main()
