"""Exp003b trigger causality. The commercial ledger is not used."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from hush.frozen_identity import (  # noqa: E402
    FREEZE_EXCLUDE_S,
    FREEZE_SPAN_S,
    HITS_REQUIRED,
    MIN_HISTORY_S,
    REFRACTORY_S,
    cloud_distance,
    exceed_mask,
    freeze_times,
    reference_bounds,
    reference_mask,
)


def _quiet_then_spike(n: int = 800, spike_at: int = 700) -> tuple[np.ndarray, np.ndarray]:
    ends = np.arange(n, dtype=np.float64)
    scores = np.full(n, 0.05)
    scores[spike_at : spike_at + 3] = 0.9
    return ends, scores


class Trigger(unittest.TestCase):
    def test_a_single_spike_does_not_freeze(self):
        ends, scores = _quiet_then_spike()
        scores[700:703] = 0.05
        scores[700] = 0.9
        hits = exceed_mask(ends, scores)
        self.assertTrue(hits[700])
        self.assertEqual(freeze_times(ends, hits), [])

    def test_three_hits_in_five_seconds_freeze_once(self):
        ends, scores = _quiet_then_spike()
        hits = exceed_mask(ends, scores)
        fired = freeze_times(ends, hits)
        self.assertEqual(fired, [702.0])

    def test_history_shorter_than_five_minutes_cannot_hit(self):
        ends = np.arange(MIN_HISTORY_S - 1, dtype=np.float64)
        scores = np.full(ends.shape, 0.05)
        scores[-3:] = 0.9
        self.assertFalse(np.any(exceed_mask(ends, scores)))

    def test_refractory_suppresses_a_second_burst(self):
        ends, scores = _quiet_then_spike(n=900)
        scores[702 + int(REFRACTORY_S) - 10 : 702 + int(REFRACTORY_S) - 7] = 0.9
        fired = freeze_times(ends, exceed_mask(ends, scores))
        self.assertEqual(len(fired), 1)
        scores[800:803] = 2.0
        fired = freeze_times(ends, exceed_mask(ends, scores))
        self.assertEqual(fired, [702.0, 802.0])

    def test_future_scores_do_not_move_an_earlier_freeze(self):
        ends, scores = _quiet_then_spike()
        fired = freeze_times(ends, exceed_mask(ends, scores))
        scores[710:] = 5.0
        later = freeze_times(ends, exceed_mask(ends, scores))
        self.assertEqual(later[0], fired[0])
        self.assertEqual(fired, [702.0])

    def test_a_score_equal_to_its_history_does_not_exceed_it(self):
        ends = np.arange(400, dtype=np.float64)
        scores = np.full(ends.shape, 0.2)
        self.assertFalse(np.any(exceed_mask(ends, scores)))

    def test_frozen_window_excludes_the_final_30_seconds(self):
        start, stop = reference_bounds(500.0)
        self.assertAlmostEqual(stop, 500.0 - FREEZE_EXCLUDE_S)
        self.assertAlmostEqual(start, stop - FREEZE_SPAN_S)
        ends = np.arange(200, 520, dtype=np.float64)
        chosen = ends[reference_mask(ends, 500.0)]
        self.assertLessEqual(float(chosen.max()), 470.0)
        self.assertGreater(float(chosen.min()), 290.0)
        self.assertNotIn(490.0, set(chosen.tolist()))
        self.assertNotIn(500.0, set(chosen.tolist()))

    def test_distance_uses_only_the_reference_rows(self):
        reference = np.zeros((20, 4))
        reference[:, 0] = 1.0
        current = np.array([[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]])
        distances, baseline = cloud_distance(current, reference)
        self.assertAlmostEqual(float(distances[0]), 0.0)
        self.assertAlmostEqual(float(distances[1]), 1.0)
        self.assertAlmostEqual(baseline, 0.0)
        reference_changed = reference.copy()
        reference_changed[:, 1] = 3.0
        again, _ = cloud_distance(current, reference)
        np.testing.assert_allclose(again, distances)


if __name__ == "__main__":
    unittest.main()
