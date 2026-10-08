"""Overlay arithmetic for frozen Exp003 scores. No ledger and no rescoring."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from hush.overlay003 import (  # noqa: E402
    associated,
    latency_to_max,
    percentile_rank,
    window_stats,
)


class OverlayMath(unittest.TestCase):
    def test_percentile_rank_is_the_share_at_or_below(self):
        population = np.array([0.1, 0.2, 0.3, 0.4])
        self.assertAlmostEqual(percentile_rank(0.2, population), 50.0)
        self.assertAlmostEqual(percentile_rank(0.4, population), 100.0)

    def test_post_window_does_not_include_the_pre_break_score(self):
        ends = np.array([10.0, 20.0, 30.0, 40.0])
        scores = np.array([0.1, 0.2, 0.9, 0.3])
        stats = window_stats(ends, scores, 20.0, 40.0, scores)
        self.assertEqual(stats["n"], 2)
        self.assertAlmostEqual(stats["max"], 0.9)
        self.assertAlmostEqual(stats["median"], 0.6)

    def test_latency_is_measured_from_the_boundary_to_the_peak_window_end(self):
        ends = np.arange(1.0, 41.0)
        scores = np.zeros_like(ends)
        scores[24] = 0.8
        self.assertAlmostEqual(latency_to_max(ends, scores, 20.0, 30.0), 5.0)

    def test_a_pod_and_a_nearby_start_count_as_associated(self):
        breaks = [{"start_seconds": 100.0, "end_seconds": 160.0}]
        self.assertTrue(associated(130.0, breaks))
        self.assertTrue(associated(80.0, breaks))
        self.assertFalse(associated(60.0, breaks))
        self.assertFalse(associated(200.0, breaks))


if __name__ == "__main__":
    unittest.main()
