"""Causal replay rules. No audio and no GPU."""

from __future__ import annotations

import unittest

from tools.gpu_lab.decisions import (
    decision_times,
    label_action,
    lock_threshold,
    playback_from_scores,
    pod_losses,
    program_incidents,
    relative_excess,
    sustained_scores,
    window_bounds,
)
from tools.gpu_lab.splits import HOLDOUTS


class ReplayTests(unittest.TestCase):
    def test_window_ends_when_the_decision_is_available(self):
        start, end = window_bounds(10.0, 2.0)
        self.assertEqual((start, end), (8.0, 10.0))

    def test_first_decision_waits_for_a_full_past_window(self):
        times = decision_times(0.0, 10.0, 2.0)
        self.assertEqual(times[0], 2.0)
        self.assertEqual(times[-1], 9.0)
        self.assertNotIn(1.0, times)

    def test_mixed_second_is_not_a_training_label(self):
        mask = {
            "verified_commercial": [[5.0, 8.5]],
            "verified_program": [[0.0, 5.0], [8.5, 12.0]],
            "excluded": [],
        }
        self.assertEqual(label_action(mask, 4.0), 0)
        self.assertEqual(label_action(mask, 5.0), 1)
        self.assertEqual(label_action(mask, 8.0), -1)

    def test_mute_starts_at_the_decision_and_not_before(self):
        playback = playback_from_scores((0.0, 6.0), [2.0, 3.0, 4.0], [0.1, 0.9, 0.1], 0.5)
        covered = [span for span in playback if span.state == "covered"]
        self.assertEqual([(span.start, span.end) for span in covered], [(3.0, 4.0)])
        self.assertGreaterEqual(covered[0].start, 3.0)

    def test_a_missed_pod_is_not_called_a_late_start(self):
        playback = playback_from_scores((0.0, 10.0), [], [], 0.5)
        rows = pod_losses([(2.0, 5.0)], playback)
        self.assertEqual(rows[0]["cause"], "missed")
        self.assertEqual(rows[0]["missed_s"], 3.0)
        self.assertEqual(rows[0]["late_start_s"], 0.0)

    def test_early_unmute_is_the_commercial_audio_after_the_mute_lets_go(self):
        playback = playback_from_scores((0.0, 10.0), [2.0, 3.0, 4.0], [0.9, 0.1, 0.1], 0.5)
        rows = pod_losses([(2.0, 5.0)], playback)
        self.assertEqual(rows[0]["cause"], "early_unmute")
        self.assertAlmostEqual(rows[0]["late_start_s"], 0.0)
        self.assertAlmostEqual(rows[0]["early_unmute_s"], 2.0)
        self.assertAlmostEqual(rows[0]["held_s"], 1.0)

    def test_program_cut_is_measured_on_the_covered_span(self):
        playback = playback_from_scores((0.0, 5.0), [1.0], [0.9], 0.5)
        incidents = program_incidents([(0.0, 5.0)], playback)
        self.assertEqual(len(incidents), 1)
        self.assertAlmostEqual(incidents[0]["program_s"], 1.0)

    def test_threshold_locks_only_when_the_game_stays_on(self):
        mask = {
            "session": "synthetic",
            "coverage": [[0.0, 10.0]],
            "verified_commercial": [[4.0, 8.0]],
            "verified_program": [[0.0, 4.0], [8.0, 10.0]],
            "excluded": [],
        }
        times = [float(t) for t in range(0, 9)]
        quiet = [0.1] * len(times)
        caught = [0.9 if 4.0 <= t < 8.0 else 0.1 for t in times]
        self.assertIsNone(lock_threshold(mask, times, [0.99] * len(times))["locked"])
        locked = lock_threshold(mask, times, caught)["locked"]
        self.assertIsNotNone(locked)
        self.assertGreater(locked["commercial_held_s"], 0)
        self.assertEqual(locked["program_cut_s"], 0.0)
        quiet_lock = lock_threshold(mask, times, quiet)["locked"]
        self.assertEqual(quiet_lock["commercial_held_s"], 0.0)
        self.assertEqual(quiet_lock["program_cut_s"], 0.0)

    def test_a_one_second_spike_does_not_satisfy_a_two_second_sustain(self):
        times = [1.0, 2.0, 3.0, 4.0]
        scores = sustained_scores(times, [0.1, 0.99, 0.2, 0.99], 2)
        self.assertEqual(scores, [0.0, 0.1, 0.2, 0.2])
        held = sustained_scores(times, [0.2, 0.8, 0.7, 0.9], 2)
        self.assertEqual(held, [0.0, 0.2, 0.7, 0.7])

    def test_relative_excess_uses_only_the_past(self):
        times = [0.0, 1.0, 2.0, 3.0]
        excess = relative_excess(times, [0.0, 0.0, 0.0, 10.0], 3, 0.5)
        self.assertEqual(excess[:3], [-1.0e9, -1.0e9, -1.0e9])
        self.assertAlmostEqual(excess[3], 10.0)
        gapped = relative_excess([0.0, 1.0, 2.0, 10.0], [1.0, 1.0, 1.0, 9.0], 3, 0.5)
        self.assertEqual(gapped[3], -1.0e9)

    def test_holdouts_are_not_embed_sessions(self):
        from tools.gpu_lab.embed import sessions_for_embed

        self.assertTrue(HOLDOUTS.isdisjoint(sessions_for_embed()))


if __name__ == "__main__":
    unittest.main()
