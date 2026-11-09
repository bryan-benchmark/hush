"""Broadcast-opportunity rules. Gold is not an input."""

from __future__ import annotations

import unittest

import numpy as np

from experiments.nfl75.broadcast_opportunity import (
    ABSENCE_S,
    arms_b,
    arms_c,
    arms_d,
    coarse_onsets,
    covers_opportunity,
    fixed_delay_ceiling,
    phrases_in,
)


def _hot(n: int, value: float = 5.0):
    times = [float(index) for index in range(n)]
    scores = [value] * n
    means = [value] * n
    return times, scores, means


class CeilingTests(unittest.TestCase):
    def test_short_break_is_missed_entirely(self):
        row = fixed_delay_ceiling([120.0, 20.0], 30.0)
        self.assertEqual(row["breaks_reachable"], 1)
        self.assertEqual(row["coverable_s"], 90.0)
        self.assertEqual(row["coverage"], 0.6429)

    def test_zero_delay_covers_every_second(self):
        row = fixed_delay_ceiling([10.0, 10.0], 0.0)
        self.assertEqual(row["coverage"], 1.0)


class ArmTests(unittest.TestCase):
    def test_signoff_alone_does_not_arm(self):
        self.assertEqual(arms_b([15.0], []), [])

    def test_signoff_waits_for_the_acoustic_onset(self):
        self.assertEqual(arms_b([15.0], [17.0]), [17.0])
        self.assertEqual(arms_b([15.0], [14.0]), [15.0])

    def test_timeout_is_not_a_signoff(self):
        self.assertEqual(phrases_in("First down, timeout.", ("timeout",)), ["timeout"])
        self.assertEqual(phrases_in("First down, timeout.", ("we'll be right back",)), [])

    def test_speaker_change_needs_a_recent_booth(self):
        self.assertEqual(arms_d([12.0], [12.0], []), [])
        self.assertEqual(arms_d([12.0], [12.0], [10.0]), [12.0])

    def test_stoppage_alone_does_not_arm(self):
        self.assertEqual(arms_c([15.0], [], []), [])

    def test_stoppage_then_departure_arms_once(self):
        self.assertEqual(arms_c([15.0], [20.0], [10.0]), [20.0])

    def test_booth_between_stoppage_and_departure_cancels(self):
        self.assertEqual(arms_c([15.0], [20.0], [10.0, 18.0]), [])


class CoverTests(unittest.TestCase):
    def test_booth_present_blocks_a_hot_score(self):
        times, scores, means = _hot(30)
        covers, flags = covers_opportunity(
            times, scores, means, times, mode="AD", start_line=0.163
        )
        self.assertEqual(covers, [])
        self.assertFalse(any(flags))

    def test_absence_opens_at_thirty_seconds(self):
        times, scores, means = _hot(81)
        covers, flags = covers_opportunity(
            times, scores, means, [10.0], mode="A", start_line=0.163
        )
        self.assertEqual(covers, [(40.0, 81.0)])
        self.assertFalse(flags[39])
        self.assertTrue(flags[40])

    def test_unknown_booth_is_not_absence(self):
        times, scores, means = _hot(80)
        covers, _flags = covers_opportunity(
            times, scores, means, [], mode="A", start_line=0.163
        )
        self.assertEqual(covers, [])

    def test_booth_return_closes_and_does_not_reopen_on_the_stale_score(self):
        times, scores, means = _hot(71)
        covers, _flags = covers_opportunity(
            times, scores, means, [10.0, 50.0], mode="A", start_line=0.163
        )
        self.assertEqual(covers, [(40.0, 50.0)])

    def test_a_dip_inside_continued_absence_can_reopen(self):
        times, scores, means = _hot(51)
        for index in (45, 46, 47):
            scores[index] = -1.0
        covers, _flags = covers_opportunity(
            times, scores, means, [10.0], mode="A", start_line=0.163
        )
        self.assertEqual(covers, [(40.0, 47.0), (48.0, 51.0)])

    def test_signoff_and_acoustic_override_a_recent_booth(self):
        times, scores, means = _hot(30)
        covers, flags = covers_opportunity(
            times,
            scores,
            means,
            [float(index) for index in range(30)],
            mode="B",
            b_arms=[16.0],
            start_line=0.163,
        )
        self.assertEqual(covers, [(16.0, 17.0)])
        self.assertTrue(flags[16])
        self.assertFalse(flags[17])

    def test_signoff_holds_after_the_booth_stops(self):
        times, scores, means = _hot(25)
        covers, _flags = covers_opportunity(
            times, scores, means, [16.0], mode="B", b_arms=[16.0], start_line=0.163
        )
        self.assertEqual(covers, [(16.0, 25.0)])

    def test_speaker_change_opens_before_thirty_seconds(self):
        times, scores, means = _hot(21)
        opened, _flags = covers_opportunity(
            times, scores, means, [10.0], mode="D", d_arms=[12.0], start_line=0.163
        )
        self.assertEqual(opened, [(12.0, 21.0)])
        absent, _flags = covers_opportunity(
            times, scores, means, [10.0], mode="A", start_line=0.163
        )
        self.assertEqual(absent, [])

    def test_cold_score_does_not_confirm(self):
        times, scores, means = _hot(50, value=-2.0)
        covers, flags = covers_opportunity(
            times, scores, means, [0.0], mode="A", start_line=0.163
        )
        self.assertEqual(covers, [])
        self.assertTrue(flags[int(ABSENCE_S)])


class OnsetTests(unittest.TestCase):
    def test_eighteen_decibel_drop_is_available_at_the_frame_end(self):
        db = np.concatenate([np.full(50, -20.0), np.array([-40.0])])
        self.assertEqual(coarse_onsets(db, 0.04, 0.0), [2.04])

    def test_quiet_past_does_not_onset(self):
        db = np.concatenate([np.full(50, -50.0), np.array([-80.0])])
        self.assertEqual(coarse_onsets(db, 0.04, 0.0), [])

    def test_small_drop_does_not_onset(self):
        db = np.concatenate([np.full(50, -20.0), np.array([-30.0])])
        self.assertEqual(coarse_onsets(db, 0.04, 0.0), [])


if __name__ == "__main__":
    unittest.main()
