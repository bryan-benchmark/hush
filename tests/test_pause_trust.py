"""Entry and release pauses stay apart. A future window cannot vote."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from experiments.nfl75.pause_trust import (
    COVERAGE_SLACK,
    commercial_given_back,
    pause_covers,
    seconds,
)
from experiments.nfl75.protect import covers_protected, unprotected_covers


def _pair(scores: list[float]) -> tuple[list[float], list[float]]:
    return [float(index) for index in range(len(scores))], scores


class PauseTrustTests(unittest.TestCase):
    def test_gate_is_half_a_point(self):
        self.assertEqual(COVERAGE_SLACK, 0.005)

    def test_no_match_matches_the_unprotected_mean(self):
        times, scores = _pair([5.0] * 12)
        plain = unprotected_covers(times, scores, window=10, start_line=0.0)
        covers, holds = pause_covers(
            times, scores, [], [], window=10, start_line=0.0, gap_s=5.0, effect="entry"
        )
        self.assertEqual(covers, plain)
        self.assertEqual(holds, [])

    def test_mixed_hold_matches_the_published_veto(self):
        times = [float(index) for index in range(40)]
        scores = [0.5 if index % 3 else -1.0 for index in range(40)]
        ends = [5.0, 12.0, 18.0, 25.0]
        cosines = [0.4, 0.1, 0.8, 0.3]
        for gap in (1.0, 5.0):
            mixed, _holds = pause_covers(
                times,
                scores,
                ends,
                cosines,
                window=10,
                start_line=0.0,
                gap_s=gap,
                effect="mixed",
            )
            published = covers_protected(
                times,
                scores,
                ends,
                cosines,
                window=10,
                start_line=0.0,
                hold_s=gap,
            )
            self.assertEqual(mixed, published)

    def test_a_weak_match_does_not_hold(self):
        times, scores = _pair([5.0] * 12)
        covers, _holds = pause_covers(
            times, scores, [9.0], [0.24], window=10, start_line=0.0, gap_s=5.0, effect="entry"
        )
        self.assertEqual(covers, unprotected_covers(times, scores, window=10, start_line=0.0))

    def test_entry_does_not_release_a_cover_already_open(self):
        times, scores = _pair([5.0] * 31)
        entry, _holds = pause_covers(
            times, scores, [15.0], [0.5], window=10, start_line=0.0, gap_s=5.0, effect="entry"
        )
        release, _holds = pause_covers(
            times, scores, [15.0], [0.5], window=10, start_line=0.0, gap_s=5.0, effect="release"
        )
        self.assertEqual(entry, [(9.0, 31.0)])
        self.assertEqual(release, [(9.0, 15.0), (21.0, 31.0)])

    def test_a_match_before_the_open_delays_both_families_the_same_way(self):
        times, scores = _pair([5.0] * 20)
        entry, _holds = pause_covers(
            times, scores, [8.0], [0.5], window=10, start_line=0.0, gap_s=5.0, effect="entry"
        )
        release, _holds = pause_covers(
            times, scores, [8.0], [0.5], window=10, start_line=0.0, gap_s=5.0, effect="release"
        )
        self.assertEqual(entry, [(14.0, 20.0)])
        self.assertEqual(release, entry)

    def test_a_hot_mean_does_not_refresh_a_cold_timer(self):
        times, scores = _pair([5.0] * 16)
        always, _holds = pause_covers(
            times, scores, [9.0], [0.8], window=10, start_line=0.0, gap_s=2.0, effect="entry"
        )
        cold, _holds = pause_covers(
            times,
            scores,
            [9.0],
            [0.8],
            window=10,
            start_line=0.0,
            gap_s=2.0,
            effect="entry",
            refresh="while_mean_cold",
        )
        self.assertEqual(always, [(12.0, 16.0)])
        self.assertEqual(cold, [(9.0, 16.0)])

    def test_matches_during_a_hot_mean_do_not_chain_the_pause(self):
        scores = [-1.0] * 20 + [5.0] * 20
        times, values = _pair(scores)
        ends = [float(index) for index in range(40)]
        cosines = [0.9] * 40
        cold, _holds = pause_covers(
            times,
            values,
            ends,
            cosines,
            window=10,
            start_line=0.0,
            gap_s=3.0,
            effect="entry",
            refresh="while_mean_cold",
        )
        always, _holds = pause_covers(
            times, values, ends, cosines, window=10, start_line=0.0, gap_s=3.0, effect="entry"
        )
        self.assertEqual(cold[0][0], 24.0)
        self.assertEqual(always, [])

    def test_a_future_window_is_invisible(self):
        times, scores = _pair([5.0] * 20)
        trace: list[dict] = []
        pause_covers(
            times,
            scores,
            [15.0],
            [0.9],
            window=10,
            start_line=0.0,
            gap_s=5.0,
            effect="entry",
            trace=trace,
        )
        at_nine = next(row for row in trace if row["t"] == 9.0)
        self.assertFalse(at_nine["protected"])
        self.assertIsNone(at_nine["match_end_s"])
        self.assertEqual(at_nine["reason"], "opened_on_mean")

    def test_prefix_decisions_do_not_move_when_the_tape_is_extended(self):
        scores = [5.0] * 30
        times, values = _pair(scores)
        prefix: list[dict] = []
        full: list[dict] = []
        pause_covers(
            times[:20],
            values[:20],
            [8.0, 25.0],
            [0.6, 0.9],
            window=10,
            start_line=0.0,
            gap_s=3.0,
            effect="entry",
            trace=prefix,
        )
        pause_covers(
            times,
            values,
            [8.0, 25.0],
            [0.6, 0.9],
            window=10,
            start_line=0.0,
            gap_s=3.0,
            effect="entry",
            trace=full,
        )
        self.assertEqual(prefix, full[: len(prefix)])

    def test_commercial_seconds_given_back_are_the_gap_inside_the_ad(self):
        baseline = [(0.0, 20.0)]
        candidate = [(5.0, 20.0)]
        commercials = [(0.0, 30.0)]
        lost = commercial_given_back(baseline, candidate, commercials)
        self.assertEqual(lost, [(0.0, 5.0)])
        self.assertEqual(seconds(lost), 5.0)

    def test_cold_refresh_rejects_a_release(self):
        times, scores = _pair([5.0] * 12)
        with self.assertRaises(ValueError):
            pause_covers(
                times,
                scores,
                [],
                [],
                window=10,
                start_line=0.0,
                gap_s=1.0,
                effect="release",
                refresh="while_mean_cold",
            )
