"""The persistence rule is fixed before it sees a game. Gold is not an input."""

from __future__ import annotations

import unittest

from experiments.nfl75.persist import (
    PERSIST_SECONDS,
    PUBLISHED_START_LINE,
    RETURN_PERSIST_S,
    covers_from_scores,
)


START = PUBLISHED_START_LINE
RETURN = 8.285
HOT = 13.0
GAP = 10.0
COLD = 0.0


def _series(pairs: list[tuple[int, float]]) -> tuple[list[float], list[float]]:
    times: list[float] = []
    scores: list[float] = []
    cursor = 0.0
    for count, score in pairs:
        for _ in range(count):
            times.append(cursor)
            scores.append(score)
            cursor += 1.0
    return times, scores


class PersistTests(unittest.TestCase):
    def test_ten_seconds_above_the_line_covers_and_nine_does_not(self):
        times, scores = _series([(9, HOT)])
        self.assertEqual(covers_from_scores(times, scores, persist_s=10, start_line=START, return_line=RETURN), [])
        times, scores = _series([(10, HOT)])
        covers = covers_from_scores(times, scores, persist_s=10, start_line=START, return_line=RETURN)
        self.assertEqual(covers, [(9.0, 10.0)])

    def test_twenty_seconds_ignores_a_fifteen_second_spike(self):
        times, scores = _series([(15, HOT), (5, COLD)])
        self.assertEqual(
            covers_from_scores(times, scores, persist_s=20, start_line=START, return_line=RETURN),
            [],
        )

    def test_the_gap_holds_and_three_program_seconds_return(self):
        times, scores = _series([(10, HOT), (5, GAP), (3, COLD), (2, HOT)])
        covers = covers_from_scores(times, scores, persist_s=10, start_line=START, return_line=RETURN)
        self.assertEqual(covers, [(9.0, 17.0)])
        self.assertEqual(RETURN_PERSIST_S, 3.0)

    def test_a_hole_does_not_count_as_sustained_evidence(self):
        times = [float(t) for t in range(6)] + [20.0, 21.0, 22.0, 23.0]
        scores = [HOT] * 10
        self.assertEqual(
            covers_from_scores(times, scores, persist_s=10, start_line=START, return_line=RETURN),
            [],
        )

    def test_later_audio_does_not_change_the_earlier_cover(self):
        early_t, early_s = _series([(12, HOT)])
        early = covers_from_scores(early_t, early_s, persist_s=10, start_line=START, return_line=RETURN)
        late_t, late_s = _series([(12, HOT), (30, COLD)])
        late = covers_from_scores(late_t, late_s, persist_s=10, start_line=START, return_line=RETURN)
        self.assertEqual(early[0][0], late[0][0])
        self.assertEqual(set(PERSIST_SECONDS), {10.0, 20.0})

    def test_a_backwards_clock_is_refused(self):
        with self.assertRaises(ValueError):
            covers_from_scores([1.0, 0.0], [HOT, HOT], persist_s=10, start_line=START, return_line=RETURN)


if __name__ == "__main__":
    unittest.main()
