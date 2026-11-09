"""NFL75 scoring rules. Synthetic timelines, plus the Prime champion on gold.

Gold is read and not written. Sealed holdouts are not opened. No detector is trained.
"""

from __future__ import annotations

import unittest

from experiments.measurement.metrics import Interval, Span, TimelineError

from experiments.nfl75.causal import prefix_invariant, stamp_ok
from experiments.nfl75.diagnose import bottleneck, oracle_playback
from experiments.nfl75.inventory import HOLDOUTS, TRUTH_PATH, active_intervals, coverage_by_session
from experiments.nfl75.score import (
    ScoreError,
    always_play,
    judge,
    playback_from_decisions,
    score_product,
)


def _ad(start: float, end: float) -> Interval:
    return Interval(start, end, "commercial", "mute", "certain")


class ScoreRuleTests(unittest.TestCase):
    def test_late_return_is_hidden_football(self):
        scored = score_product(
            (0, 200),
            [_ad(50, 100)],
            [
                Span(0, 90, "program"),
                Span(90, 112, "covered"),
                Span(112, 200, "program"),
            ],
            session="synthetic",
        )
        self.assertAlmostEqual(scored["commercial_covered_s"], 10)
        self.assertAlmostEqual(scored["program_covered_s"], 12)
        self.assertEqual(scored["false_mute_episodes"], 1)
        self.assertAlmostEqual(scored["longest_false_mute_s"], 12)
        self.assertAlmostEqual(scored["breaks"][0]["start_delay_s"], 40)
        self.assertAlmostEqual(scored["breaks"][0]["late_return_s"], 12)
        self.assertIn("href", scored["episodes"][0]["clip"])
        self.assertFalse(scored["acceptance"]["pass"])

    def test_one_second_unmute_does_not_split_a_long_hide(self):
        # 6s + 6s with a 1s heard gap. Unmerged, each piece is under 10s.
        scored = score_product(
            (0, 12000),
            [_ad(11000, 12000)],
            [
                Span(0, 100, "program"),
                Span(100, 106, "covered"),
                Span(106, 107, "program"),
                Span(107, 113, "covered"),
                Span(113, 12000, "program"),
            ],
        )
        self.assertEqual(scored["false_mute_episodes"], 1)
        self.assertAlmostEqual(scored["longest_false_mute_s"], 12)
        self.assertAlmostEqual(scored["program_covered_s"], 12)
        self.assertGreaterEqual(scored["longest_false_mute_s"], 10)
        self.assertFalse(scored["acceptance"]["pass"])

    def test_gap_over_two_seconds_stays_two_episodes(self):
        scored = score_product(
            (0, 400),
            [_ad(300, 400)],
            [
                Span(0, 10, "program"),
                Span(10, 16, "covered"),
                Span(16, 19.1, "program"),
                Span(19.1, 25.1, "covered"),
                Span(25.1, 400, "program"),
            ],
        )
        self.assertEqual(scored["false_mute_episodes"], 2)
        self.assertAlmostEqual(scored["longest_false_mute_s"], 6)

    def test_exact_two_second_gap_merges(self):
        scored = score_product(
            (0, 400),
            [_ad(300, 400)],
            [
                Span(0, 10, "program"),
                Span(10, 14, "covered"),
                Span(14, 16, "program"),
                Span(16, 20, "covered"),
                Span(20, 400, "program"),
            ],
        )
        self.assertEqual(scored["false_mute_episodes"], 1)
        self.assertAlmostEqual(scored["longest_false_mute_s"], 8)
        self.assertAlmostEqual(scored["episodes"][0]["heard_gap_s"], 2)

    def test_missing_playback_is_not_a_success(self):
        scored = score_product(
            (0, 100),
            [_ad(10, 40)],
            [Span(0, 10, "program"), Span(40, 100, "program")],
        )
        self.assertGreater(scored["commercial_missing_s"], 0)
        self.assertIsNone(scored["commercial_coverage"])
        self.assertFalse(scored["evaluable"])
        self.assertFalse(scored["acceptance"]["pass"])

    def test_unsure_is_excluded_and_reported(self):
        scored = score_product(
            (0, 100),
            [_ad(40, 70), Interval(10, 20, "commercial", "mute", "unsure")],
            always_play((0, 100)),
        )
        self.assertAlmostEqual(scored["commercial_s"], 30)
        self.assertAlmostEqual(scored["unsure_s"], 10)
        self.assertAlmostEqual(scored["commercial_coverage"], 0)
        self.assertEqual(scored["false_mute_episodes"], 0)

    def test_overlapping_commercials_are_rejected(self):
        with self.assertRaises(TimelineError):
            score_product((0, 100), [_ad(10, 40), _ad(30, 50)], always_play((0, 100)))

    def test_capture_gap_inside_coverage_is_rejected(self):
        with self.assertRaises(TimelineError):
            score_product((0, 100), [_ad(10, 40)], always_play((0, 100)), capture_gaps=[(0, 5)])

    def test_engine_clock_is_rejected(self):
        with self.assertRaises(ScoreError):
            playback_from_decisions(
                (0, 100),
                [{"available_at": 10, "evidence_through": 10, "action": "cover", "clock": "engine"}],
            )

    def test_lookahead_stamp_is_rejected(self):
        with self.assertRaises(ScoreError):
            playback_from_decisions(
                (0, 100),
                [{"available_at": 10, "evidence_through": 18, "action": "cover", "clock": "capture"}],
            )

    def test_timestamp_outside_coverage_is_rejected(self):
        with self.assertRaises(ScoreError):
            playback_from_decisions(
                (0, 100),
                [{"available_at": 1000, "evidence_through": 1000, "action": "cover", "clock": "capture"}],
            )

    def test_program_mark_does_not_erase_a_commercial_inside_it(self):
        scored = score_product(
            (0, 200),
            [
                Interval(0, 200, "program", "play", "certain"),
                _ad(50, 80),
            ],
            [Span(0, 50, "program"), Span(50, 80, "covered"), Span(80, 200, "program")],
        )
        self.assertAlmostEqual(scored["commercial_covered_s"], 30)
        self.assertAlmostEqual(scored["program_covered_s"], 0)
        self.assertEqual(scored["false_mute_episodes"], 0)
        self.assertAlmostEqual(scored["commercial_coverage"], 1)

    def test_thresholds_are_strict(self):
        good = {
            "oracle": False,
            "evaluable": True,
            "blockers": [],
            "commercial_coverage": 0.75,
            "false_mutes_per_hour": 0.99,
            "longest_false_mute_s": 9.99,
            "program_hidden_per_hour": 4.99,
        }
        self.assertTrue(judge(good)["pass"])
        for key, value in (
            ("commercial_coverage", 0.7499),
            ("false_mutes_per_hour", 1.0),
            ("longest_false_mute_s", 10.0),
            ("program_hidden_per_hour", 5.0),
        ):
            bad = dict(good)
            bad[key] = value
            self.assertFalse(judge(bad)["pass"], key)

    def test_oracle_cannot_pass_even_when_the_seconds_would(self):
        scored = score_product(
            (0, 200),
            [_ad(50, 100)],
            [Span(0, 50, "program"), Span(50, 100, "covered"), Span(100, 200, "program")],
            oracle=True,
        )
        self.assertAlmostEqual(scored["commercial_coverage"], 1)
        self.assertEqual(scored["false_mute_episodes"], 0)
        self.assertFalse(scored["acceptance"]["pass"])
        self.assertTrue(any("oracle" in reason for reason in scored["acceptance"]["reasons"]))


class OracleSplitTests(unittest.TestCase):
    def test_late_start_and_late_return_split(self):
        coverage = (0, 400)
        ads = [_ad(100, 200)]
        playback = [Span(0, 120, "program"), Span(120, 210, "covered"), Span(210, 400, "program")]
        joint = score_product(coverage, ads, playback)
        endings = score_product(
            coverage, ads, oracle_playback(coverage, playback, [(100, 200)], "perfect_endings"), oracle=True
        )
        starts = score_product(
            coverage, ads, oracle_playback(coverage, playback, [(100, 200)], "perfect_starts"), oracle=True
        )
        self.assertAlmostEqual(joint["commercial_missed_s"], 20)
        self.assertAlmostEqual(joint["program_covered_s"], 10)
        self.assertAlmostEqual(endings["program_covered_s"], 0)
        self.assertAlmostEqual(endings["commercial_missed_s"], 20)
        self.assertAlmostEqual(starts["commercial_missed_s"], 0)
        self.assertAlmostEqual(starts["program_covered_s"], 10)
        ranked = bottleneck(joint, endings, starts)
        self.assertEqual(ranked["primary"], "both")
        self.assertFalse(ranked["deployable"])

    def test_early_let_go_is_a_return_miss(self):
        coverage = (0, 400)
        playback = [Span(0, 110, "program"), Span(110, 150, "covered"), Span(150, 400, "program")]
        joint = score_product(coverage, [_ad(100, 200)], playback)
        endings = score_product(
            coverage,
            [_ad(100, 200)],
            oracle_playback(coverage, playback, [(100, 200)], "perfect_endings"),
            oracle=True,
        )
        self.assertAlmostEqual(joint["commercial_covered_s"], 40)
        self.assertAlmostEqual(endings["commercial_covered_s"], 90)

    def test_mid_game_false_mute_survives_both_oracles(self):
        coverage = (0, 400)
        playback = [Span(0, 300, "program"), Span(300, 306, "covered"), Span(306, 400, "program")]
        ads = [(100, 160)]
        self.assertEqual(oracle_playback(coverage, playback, ads, "perfect_endings")[1].start, 300)
        self.assertEqual(oracle_playback(coverage, playback, ads, "perfect_starts")[1].start, 300)

    def test_champion_never_covers_so_the_bottleneck_is_the_start(self):
        coverage = (0, 200)
        playback = always_play(coverage)
        joint = score_product(coverage, [_ad(50, 100)], playback)
        endings = score_product(
            coverage, [_ad(50, 100)], oracle_playback(coverage, playback, [(50, 100)], "perfect_endings"), oracle=True
        )
        starts = score_product(
            coverage, [_ad(50, 100)], oracle_playback(coverage, playback, [(50, 100)], "perfect_starts"), oracle=True
        )
        ranked = bottleneck(joint, endings, starts)
        self.assertEqual(ranked["primary"], "start")
        self.assertAlmostEqual(joint["commercial_coverage"], 0)
        self.assertEqual(joint["false_mute_episodes"], 0)


class PrefixTests(unittest.TestCase):
    def test_past_only_hopper_matches_on_the_prefix(self):
        def decide(samples, sr=1.0):
            hop = 5.0
            rows = []
            t = hop
            while t <= (len(samples) / sr) + 1e-9:
                window = samples[int((t - hop) * sr) : int(t * sr)]
                rows.append(
                    {
                        "available_at": t,
                        "evidence_through": t,
                        "score": float(sum(window) / len(window)),
                    }
                )
                t += hop
            return rows

        audio = [0.0] * 60 + [1.0] * 60
        cut = 30
        result = prefix_invariant(decide(audio), decide(audio[:cut]), cut)
        self.assertTrue(result["pass"])
        self.assertGreater(result["prefix_decisions_ready"], 0)

    def test_reading_the_buffer_tail_is_not_prefix_invariant(self):
        def decide(samples):
            rows = []
            t = 5.0
            while t <= len(samples) + 1e-9:
                rows.append(
                    {
                        "available_at": t,
                        "evidence_through": t,
                        "score": float(samples[-1]),
                    }
                )
                t += 5.0
            return rows

        audio = [0.0] * 30 + [1.0] * 30
        result = prefix_invariant(decide(audio), decide(audio[:30]), 30)
        self.assertFalse(result["pass"])

    def test_stamp_order_is_necessary_and_not_sufficient(self):
        self.assertIsNone(
            stamp_ok(
                {
                    "query_t0": 0,
                    "query_t1": 5,
                    "sample_max_consumed_at": 13,
                    "available_at": 13,
                    "decision_effective_at": 13,
                }
            )
        )
        self.assertIsNotNone(
            stamp_ok(
                {
                    "query_t0": 0,
                    "query_t1": 5,
                    "sample_max_consumed_at": 4,
                    "available_at": 5,
                }
            )
        )


class GoldChampionTests(unittest.TestCase):
    def test_sealed_sessions_are_absent_from_the_ledger(self):
        text = TRUTH_PATH.read_text(encoding="utf-8")
        for session in HOLDOUTS:
            self.assertNotIn(session, text)
        self.assertTrue(HOLDOUTS.isdisjoint(coverage_by_session()))

    def test_prime_champion_covers_no_advertising_and_no_football(self):
        span = coverage_by_session()["hush_20261008_205100"]
        intervals = active_intervals("hush_20261008_205100")
        scored = score_product(span, intervals, always_play(span), session="hush_20261008_205100")
        self.assertAlmostEqual(scored["commercial_s"], 2642.1, places=1)
        self.assertEqual(len(scored["breaks"]), 23)
        self.assertEqual(scored["commercial_covered_s"], 0)
        self.assertEqual(scored["false_mute_episodes"], 0)
        self.assertTrue(scored["evaluable"])
        self.assertFalse(scored["acceptance"]["pass"])
        self.assertFalse(scored["oracle"])

    def test_inventory_seconds_cover_each_annotated_span(self):
        from experiments.nfl75.inventory import build_inventory

        inventory = build_inventory()
        self.assertEqual(inventory["active_marks"], 177)
        football = 0.0
        for row in inventory["annotated"]:
            parts = row["commercial_s"] + row["program_s"] + row["unsure_s"] + row["excluded_unmarked_s"]
            self.assertAlmostEqual(parts, row["coverage_s"], places=2, msg=row["session"])
            if row["broadcaster"] != "Hulu":
                football += row["commercial_s"]
        self.assertAlmostEqual(football, 17648.4, places=1)


if __name__ == "__main__":
    unittest.main()
