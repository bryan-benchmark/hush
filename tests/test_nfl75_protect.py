"""A current announcer match vetoes. Silence and old memory do not."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from experiments.nfl75.protect import (
    FRESH_S,
    covers_protected,
    fresh_cosine,
    memory_max,
    show_memory_would_protect,
    unprotected_covers,
)
from hush.speaker_memory import MATCH_COSINE
from hush.voice_floor import FLOOR


def _pair(scores: list[float]) -> tuple[list[float], list[float]]:
    return [float(index) for index in range(len(scores))], scores


class ProtectTests(unittest.TestCase):
    def test_published_lines_stay_put(self):
        self.assertEqual(MATCH_COSINE, 0.25)
        self.assertEqual(FLOOR, 0.10)
        self.assertEqual(FRESH_S, 1.0)

    def test_silence_does_not_veto_the_rolling_mean(self):
        times, scores = _pair([5.0] * 10)
        plain = unprotected_covers(times, scores, window=10, start_line=0.0)
        guarded = covers_protected(times, scores, [], [], window=10, start_line=0.0)
        self.assertEqual(plain, [(9.0, 10.0)])
        self.assertEqual(guarded, plain)

    def test_a_current_match_blocks_the_open(self):
        times, scores = _pair([5.0] * 12)
        guarded = covers_protected(
            times,
            scores,
            [9.0],
            [0.40],
            window=10,
            start_line=0.0,
        )
        self.assertNotEqual(guarded[0][0], 9.0)
        self.assertEqual(guarded, [(11.0, 12.0)])

    def test_a_weak_match_does_not_block(self):
        times, scores = _pair([5.0] * 10)
        guarded = covers_protected(times, scores, [9.0], [0.24], window=10, start_line=0.0)
        self.assertEqual(guarded, [(9.0, 10.0)])

    def test_a_match_during_a_cover_restores_immediately(self):
        scores = [5.0] * 13
        times, values = _pair(scores)
        plain = unprotected_covers(times, values, window=10, start_line=0.0)
        guarded = covers_protected(times, values, [12.0], [0.30], window=10, start_line=0.0)
        self.assertEqual(plain[0][0], 9.0)
        self.assertEqual(guarded, [(9.0, 12.0)])

    def test_memory_from_ten_seconds_ago_does_not_veto(self):
        times, scores = _pair([5.0] * 20)
        self.assertIsNone(fresh_cosine([0.0], [0.90], 10.0))
        self.assertAlmostEqual(memory_max([0.0], [0.90], 10.0), 0.90)
        self.assertTrue(show_memory_would_protect(0.90))
        guarded = covers_protected(times, scores, [0.0], [0.90], window=10, start_line=0.0)
        self.assertEqual(guarded[0][0], 9.0)

    def test_a_future_window_cannot_protect_the_present(self):
        times, scores = _pair([5.0] * 12)
        guarded = covers_protected(times, scores, [11.0], [0.80], window=10, start_line=0.0)
        self.assertEqual(guarded[0][0], 9.0)
        self.assertIsNone(fresh_cosine([11.0], [0.80], 9.0))

    def test_the_thirty_second_memory_is_not_the_current_gate(self):
        times, scores = _pair([5.0] * 12)
        current = covers_protected(times, scores, [0.0], [0.12], window=10, start_line=0.0)
        memory = covers_protected(
            times, scores, [0.0], [0.12], window=10, start_line=0.0, rule="memory"
        )
        self.assertEqual(current[0][0], 9.0)
        self.assertEqual(memory, [])

    def test_an_unenrolled_window_does_not_veto(self):
        times, scores = _pair([5.0] * 10)
        guarded = covers_protected(times, scores, [9.0], [float("nan")], window=10, start_line=0.0)
        self.assertEqual(guarded, [(9.0, 10.0)])

    def test_a_five_second_hold_keeps_the_same_match_longer(self):
        times, scores = _pair([5.0] * 16)
        guarded = covers_protected(
            times, scores, [9.0], [0.40], window=10, start_line=0.0, hold_s=5
        )
        self.assertEqual(guarded, [(15.0, 16.0)])

    def test_a_later_match_refreshes_the_hold(self):
        times, scores = _pair([5.0] * 20)
        guarded = covers_protected(
            times, scores, [9.0, 12.0], [0.40, 0.40], window=10, start_line=0.0, hold_s=3
        )
        self.assertEqual(guarded, [(16.0, 20.0)])

    def test_rearm_refuses_the_same_hot_run(self):
        times, scores = _pair([5.0] * 16)
        guarded = covers_protected(
            times, scores, [9.0], [0.40], window=10, start_line=0.0, rearm=True
        )
        self.assertEqual(guarded, [])

    def test_rearm_accepts_a_fresh_crossing(self):
        scores = [5.0] * 5 + [-1.0] * 4 + [5.0] * 5
        times, values = _pair(scores)
        guarded = covers_protected(
            times, values, [3.0], [0.40], window=4, start_line=0.0, hold_s=1, rearm=True
        )
        self.assertEqual(guarded, [(9.0, 14.0)])

    def test_a_voice_before_the_mean_exists_does_not_disarm(self):
        times, scores = _pair([5.0] * 12)
        guarded = covers_protected(
            times, scores, [0.0], [0.90], window=10, start_line=0.0, rearm=True
        )
        self.assertEqual(guarded[0][0], 9.0)

    def test_a_blocked_recross_does_not_leave_the_run_armed(self):
        scores = [5.0] * 5 + [-1.0] * 4 + [5.0] * 8
        times, values = _pair(scores)
        guarded = covers_protected(
            times,
            values,
            [3.0, 9.0],
            [0.40, 0.40],
            window=4,
            start_line=0.0,
            hold_s=1,
            rearm=True,
        )
        self.assertEqual(guarded, [])

    def test_releasing_a_cover_waits_for_a_new_cross(self):
        times, scores = _pair([5.0] * 16)
        held = covers_protected(times, scores, [12.0], [0.30], window=10, start_line=0.0)
        rearmed = covers_protected(
            times, scores, [12.0], [0.30], window=10, start_line=0.0, rearm=True
        )
        self.assertEqual(held, [(9.0, 12.0), (14.0, 16.0)])
        self.assertEqual(rearmed, [(9.0, 12.0)])

    def test_windows_must_be_in_order(self):
        with self.assertRaises(ValueError):
            covers_protected([0.0, 1.0], [0.0, 0.0], [2.0, 1.0], [0.0, 0.0], window=1, start_line=5.0)


if __name__ == "__main__":
    unittest.main()
