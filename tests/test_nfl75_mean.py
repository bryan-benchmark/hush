"""The rolling mean is chosen before Prime, and a late return is not the start."""

from __future__ import annotations

import unittest

from experiments.nfl75.mean import (
    PRIME_SESSIONS,
    assert_nbc_only,
    assign_context,
    choose_start,
    covers_from_mean,
    decide,
    false_start_covers,
    oracle_end_covers,
    rolling_means,
    signal_by_break,
)
from experiments.nfl75.persist import FIT


def _pair(scores: list[float]) -> tuple[list[float], list[float]]:
    return [float(index) for index in range(len(scores))], scores


class MeanTests(unittest.TestCase):
    def test_a_short_prefix_has_no_mean_and_does_not_cover(self):
        times, scores = _pair([5.0] * 9)
        self.assertIsNone(rolling_means(times, scores, 10)[-1])
        self.assertEqual(covers_from_mean(times, scores, window=10, start_line=0.0), [])

    def test_the_mean_can_start_when_no_raw_second_is_at_the_old_line(self):
        scores = [1.0] * 10
        times, values = _pair(scores)
        self.assertAlmostEqual(rolling_means(times, values, 10)[-1], 1.0)
        covers = covers_from_mean(times, values, window=10, start_line=0.5)
        self.assertEqual(covers, [(9.0, 10.0)])

    def test_three_raw_seconds_at_or_below_zero_return_while_the_mean_stays_high(self):
        scores = [5.0] * 10 + [-1.0] * 3
        times, values = _pair(scores)
        covers = covers_from_mean(times, values, window=10, start_line=0.0)
        self.assertEqual(covers, [(9.0, 12.0)])

    def test_a_hole_does_not_borrow_scores_from_before_the_hole(self):
        times = [float(index) for index in range(5)] + [float(100 + index) for index in range(10)]
        scores = [9.0] * len(times)
        means = rolling_means(times, scores, 10)
        self.assertIsNone(means[4])
        self.assertIsNotNone(means[-1])
        self.assertAlmostEqual(means[-1], 9.0)

    def test_later_audio_does_not_move_the_earlier_open(self):
        early = [5.0] * 10
        first = covers_from_mean(*_pair(early), window=10, start_line=0.0)
        second = covers_from_mean(*_pair(early + [-1.0] * 5), window=10, start_line=0.0)
        self.assertEqual(first[0][0], second[0][0])

    def test_a_backwards_clock_is_rejected(self):
        with self.assertRaises(ValueError):
            covers_from_mean([0.0, 1.0, 0.5], [1.0, 1.0, 1.0], window=1, start_line=0.0)

    def test_oracle_restores_the_annotated_end_and_keeps_the_prefix(self):
        scores = [5.0] * 10 + [-1.0] * 3
        times, values = _pair(scores)
        # Window 4 opens at t=3, before the ad, and the raw return is after it.
        covers = covers_from_mean(times, values, window=4, start_line=0.0)
        self.assertEqual(covers, [(3.0, 12.0)])
        commercials = [(5.0, 8.0)]
        self.assertEqual(false_start_covers(covers, commercials), [(3.0, 12.0)])
        oracle = oracle_end_covers((0.0, 13.0), covers, commercials)
        # The prefix and the ad share a boundary, so playback is one span
        # that ends at the annotated commercial end.
        self.assertEqual(oracle, [(3.0, 8.0)])

    def test_a_cover_that_misses_every_commercial_stays_under_the_oracle(self):
        times, values = _pair([5.0] * 10)
        covers = covers_from_mean(times, values, window=10, start_line=0.0)
        oracle = oracle_end_covers((0.0, 20.0), covers, [(15.0, 18.0)])
        self.assertEqual(oracle, covers)

    def test_football_before_the_break_is_not_a_detection(self):
        times, values = _pair([5.0] * 4 + [-5.0] * 20)
        means = rolling_means(times, values, 4)
        rows = signal_by_break(times, means, [(10.0, 20.0)], window=4, start_line=0.0)
        self.assertIsNone(rows[0]["delay_s"])

    def test_half_the_window_inside_the_break_credits_the_delay(self):
        times, values = _pair([5.0] * 30)
        means = rolling_means(times, values, 4)
        rows = signal_by_break(times, means, [(10.0, 20.0)], window=4, start_line=0.0)
        self.assertAlmostEqual(rows[0]["delay_s"], 1.0)

    def test_an_open_gap_uses_the_midpoint_and_a_tie_keeps_the_shorter_window(self):
        pooled = {
            10: {"commercial": [10.0] * 20, "program": [0.0] * 20},
            20: {"commercial": [10.0] * 20, "program": [0.0] * 20},
        }
        choice = choose_start(pooled)
        self.assertEqual(choice["window_s"], 10)
        self.assertEqual(choice["placement"], "midpoint_of_commercial_p10_and_program_p90")
        self.assertAlmostEqual(choice["start_line"], 5.0)

    def test_overlap_uses_the_program_tail_and_the_wider_gap_wins(self):
        pooled = {
            10: {"commercial": [0.0] * 20, "program": [0.0] * 20},
            20: {"commercial": [8.0] * 20, "program": [1.0] * 20},
        }
        choice = choose_start(pooled)
        self.assertEqual(choice["window_s"], 20)
        self.assertEqual(choice["placement"], "midpoint_of_commercial_p10_and_program_p90")
        self.assertAlmostEqual(choice["start_line"], 4.5)
        overlap = {
            10: {"commercial": [1.0, 2.0, 3.0] * 8, "program": [1.0, 2.0, 3.0] * 8},
            20: {"commercial": [0.0] * 24, "program": [0.0] * 24},
        }
        fallen = choose_start(overlap)
        self.assertEqual(fallen["placement"], "program_p90_because_the_central_masses_overlap")
        self.assertAlmostEqual(fallen["start_line"], 0.0)

    def test_prime_cannot_choose_the_line(self):
        assert_nbc_only(FIT)
        with self.assertRaises(RuntimeError):
            assert_nbc_only(PRIME_SESSIONS)

    def test_boundary_seconds_are_not_ordinary_football(self):
        commercials = [(100.0, 200.0)]
        self.assertEqual(assign_context(150.0, commercials), {"commercial_interior"})
        self.assertEqual(assign_context(105.0, commercials), {"commercial_edge"})
        self.assertEqual(assign_context(200.0, commercials), {"post_return_30"})
        self.assertEqual(assign_context(80.0, commercials), {"pre_commercial_30"})
        self.assertEqual(assign_context(10.0, commercials), {"ordinary_football"})
        self.assertEqual(
            assign_context(125.0, [(100.0, 120.0), (140.0, 160.0)]),
            {"post_return_30", "pre_commercial_30"},
        )

    def test_the_verdict_follows_the_gates(self):
        clear = {
            "commercial_coverage": 0.80,
            "false_mutes_per_hour": 0.2,
            "longest_false_mute_s": 4.0,
            "program_hidden_per_hour": 1.0,
        }
        short = {**clear, "commercial_coverage": 0.40}
        loose = {**clear, "longest_false_mute_s": 28.0, "program_hidden_per_hour": 40.0}
        both = decide([clear, clear], [clear, clear])
        self.assertEqual(both["verdict"], "KEEP")
        self.assertFalse(both["deployable"])
        returns = decide([clear, clear], [short, short])
        self.assertEqual(returns["start_detector"], "KEEP")
        self.assertEqual(returns["actual_return"], "REJECT")
        self.assertIn("return-to-program", returns["next_change"])
        noisy = decide([loose, loose], [loose, loose])
        self.assertEqual(noisy["start_detector"], "REJECT")
        self.assertIn("protective", noisy["next_change"])
        missed = decide([short, clear], [short, clear])
        self.assertEqual(missed["verdict"], "REJECT")
        self.assertIn("audio representation", missed["next_change"])


if __name__ == "__main__":
    unittest.main()
