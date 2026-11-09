"""Rolling 60 percent is not a consecutive hold. Gold is not an input."""

from __future__ import annotations

import unittest

from experiments.nfl75.accumulate import (
    ACCUMULATED_FRACTION,
    covers_accumulated,
    support_by_break,
    window_row,
)
from experiments.nfl75.persist import covers_from_scores

LINE = 8.285
HOT = 13.0
COLD = -1.0


def _pair(scores: list[float]) -> tuple[list[float], list[float]]:
    return [float(index) for index in range(len(scores))], scores


class AccumulateTests(unittest.TestCase):
    def test_twelve_of_twenty_covers_without_ten_consecutive(self):
        scores = [COLD if index % 3 == 0 else HOT for index in range(20)]
        self.assertGreaterEqual(sum(score >= LINE for score in scores), 12)
        self.assertLess(max(
            sum(1 for _ in group)
            for group in "".join("H" if score >= LINE else "." for score in scores).split(".")
            if group
        ), 10)
        times, values = _pair(scores)
        self.assertEqual(
            covers_from_scores(times, values, persist_s=10, start_line=LINE, return_line=0.0),
            [],
        )
        covers = covers_accumulated(times, values, window=20, line=LINE)
        self.assertEqual(covers, [(19.0, 20.0)])
        self.assertEqual(ACCUMULATED_FRACTION, 0.60)

    def test_six_of_twenty_does_not_cover(self):
        scores = [HOT] * 6 + [COLD] * 14
        times, values = _pair(scores)
        self.assertEqual(covers_accumulated(times, values, window=20, line=LINE), [])

    def test_a_short_prefix_cannot_fill_a_twenty_second_window(self):
        times, values = _pair([HOT] * 12)
        self.assertEqual(covers_accumulated(times, values, window=20, line=LINE), [])
        self.assertIsNone(window_row(times, values, 11, 20, LINE))

    def test_three_seconds_at_the_logistic_boundary_return(self):
        scores = [COLD if index % 3 == 0 else HOT for index in range(20)]
        scores.extend([HOT] * 4)
        scores.extend([COLD] * 3)
        times, values = _pair(scores)
        covers = covers_accumulated(times, values, window=20, line=LINE)
        self.assertEqual(covers[0], (19.0, 26.0))

    def test_football_before_the_break_is_not_support(self):
        scores = [HOT] * 20 + [COLD] * 10
        times, values = _pair(scores)
        rows = support_by_break(times, values, [(20.0, 30.0)], window=20, line=LINE)
        self.assertEqual(rows[0]["delay_s"], 0.0)
        self.assertFalse(rows[0]["within"]["30"])

    def test_later_scores_do_not_move_the_earlier_cover(self):
        early = [COLD if index % 3 == 0 else HOT for index in range(20)]
        times, values = _pair(early)
        first = covers_accumulated(times, values, window=20, line=LINE)
        times, values = _pair(early + [COLD] * 10)
        second = covers_accumulated(times, values, window=20, line=LINE)
        self.assertEqual(first[0][0], second[0][0])


if __name__ == "__main__":
    unittest.main()
