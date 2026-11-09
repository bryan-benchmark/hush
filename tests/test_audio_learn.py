"""Causal windows and the declared split. No game audio and no training."""

from __future__ import annotations

import unittest

import numpy as np

from experiments.audio_learn.controller import decisions
from experiments.audio_learn.splits import CALIBRATE, EVAL, TRAIN, assert_split
from experiments.audio_learn.windows import lookback_bounds, pack_past_window
from tools.gpu_lab.splits import HOLDOUTS


class SplitTests(unittest.TestCase):
    def test_games_do_not_leak_across_roles(self):
        assert_split()
        self.assertIn("hush_20261008_205100", EVAL)
        self.assertIn("hush_20260924_220624", EVAL)
        self.assertNotIn("hush_20261008_205100", TRAIN)
        self.assertNotIn("hush_20260924_220624", TRAIN)
        self.assertNotIn(CALIBRATE[0], TRAIN)
        self.assertTrue(set(HOLDOUTS).isdisjoint(set(TRAIN + CALIBRATE + EVAL)))


class WindowTests(unittest.TestCase):
    def test_future_samples_are_not_copied(self):
        sr = 16000
        audio = np.zeros(8 * sr, dtype=np.float32)
        audio[4 * sr :] = 9.0
        packed = pack_past_window(audio, 0.0, 4.0, window_s=4.0, context_s=10.0, sr=sr)
        self.assertEqual(packed.shape, (10 * sr,))
        self.assertTrue(np.all(packed == 0.0))
        audio[: 4 * sr] = 0.25
        packed = pack_past_window(audio, 0.0, 4.0, window_s=4.0, context_s=10.0, sr=sr)
        self.assertTrue(np.all(packed[-4 * sr :] == 0.25))
        self.assertTrue(np.all(packed[: 6 * sr] == 0.0))

    def test_lookback_stops_at_a_gap(self):
        times = np.asarray([0.0, 0.25, 0.50, 2.00, 2.25], dtype=np.float64)
        start, end = lookback_bounds(times, 4, 16, 0.25)
        self.assertEqual((start, end), (3, 5))


class ControllerTests(unittest.TestCase):
    def test_later_probability_does_not_change_an_earlier_action(self):
        times = [1.0, 1.25, 1.5, 1.75]
        early = decisions(times, [0.1, 0.95, 0.95, 0.95], on=0.8, off=0.2, on_streak=2, off_streak=2)
        changed = decisions(times, [0.1, 0.95, 0.95, 0.0], on=0.8, off=0.2, on_streak=2, off_streak=2)
        self.assertEqual([row["action"] for row in early[:3]], [row["action"] for row in changed[:3]])
        self.assertEqual(early[2]["action"], "cover")
        self.assertTrue(all(row["evidence_through"] <= row["available_at"] for row in early))


if __name__ == "__main__":
    unittest.main()
