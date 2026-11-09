"""Eligibility and ladder rules. No recordings and no model."""

from __future__ import annotations

import unittest

from experiments.measurement.metrics import Span

from tools.gpu_lab.eligibility import build_masks, coverage_spans
from tools.gpu_lab.ladder import delay_ceiling, pairs, play_all, score_mask
from tools.gpu_lab.splits import (
    CALIBRATE,
    CONTROL,
    DEVELOP,
    FOOTBALL_COMMERCIAL_S,
    HOLDOUTS,
    OUT_OF_SCOPE,
    TNF,
    TRAIN,
    WINDOW_S,
)


class EligibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.masks = {mask["session"]: mask for mask in build_masks(list(TRAIN + CALIBRATE + DEVELOP + CONTROL + OUT_OF_SCOPE))}

    def test_split_covers_every_annotated_broadcast_once(self):
        assigned = set(TRAIN + CALIBRATE + DEVELOP + CONTROL + OUT_OF_SCOPE)
        annotated = {row["session"] for row in coverage_spans()}
        self.assertEqual(assigned, annotated)
        self.assertTrue(HOLDOUTS.isdisjoint(assigned))

    def test_october_is_not_where_the_rule_is_fit(self):
        self.assertTrue(set(DEVELOP).isdisjoint(TRAIN + CALIBRATE))
        self.assertIn(TNF, DEVELOP)

    def test_football_commercial_seconds_match_the_published_corpus(self):
        football = [self.masks[session] for session in TRAIN + CALIBRATE + DEVELOP]
        total = sum(mask["commercial_s"] for mask in football)
        pods = sum(mask["commercials"] for mask in football)
        self.assertAlmostEqual(total, FOOTBALL_COMMERCIAL_S, delta=0.2)
        self.assertEqual(pods, 136)

    def test_redzone_has_no_commercial_target(self):
        redzone = self.masks[CONTROL[0]]
        self.assertEqual(redzone["commercials"], 0)
        self.assertGreater(redzone["program_s"], 0)

    def test_unmarked_nbc_spot_is_excluded_and_gold_commercials_stay(self):
        nbc = self.masks["hush_20260909_213047"]
        self.assertEqual(len(nbc["probe_gaps"]), 1)
        gap = nbc["probe_gaps"][0]
        self.assertLess(gap["start_seconds"], 240.0)
        self.assertGreater(gap["end_seconds"], 240.0)
        self.assertGreater(gap["end_seconds"] - gap["start_seconds"], 60.0)
        commercials = pairs(nbc, "verified_commercial")
        self.assertFalse(any(start < 240.0 < end for start, end in commercials))
        self.assertAlmostEqual(nbc["commercial_s"], 2849.9, delta=0.2)

    def test_play_is_unbroken_and_holds_nothing(self):
        scored = score_mask(self.masks[TNF], play_all(self.masks[TNF]))
        self.assertFalse(scored["broken"])
        self.assertEqual(scored["commercial_held_s"], 0.0)
        self.assertEqual(scored["accuracy"], 0.0)

    def test_one_program_second_breaks_the_run(self):
        mask = self.masks[TNF]
        program = next(span for span in pairs(mask, "verified_program") if span[1] - span[0] > 3.0)
        cover = (program[0] + program[1]) / 2.0
        c0, c1 = pairs(mask, "coverage")[0]
        playback = [
            Span(start=c0, end=cover, state="program"),
            Span(start=cover, end=cover + 1.0, state="covered"),
            Span(start=cover + 1.0, end=c1, state="program"),
        ]
        scored = score_mask(mask, playback)
        self.assertTrue(scored["broken"])
        self.assertIsNone(scored["accuracy"])
        self.assertGreater(scored["program_cut_s"], 0)

    def test_tnf_window_ceiling_is_below_the_two_second_story(self):
        commercials = pairs(self.masks[TNF], "verified_commercial")
        two = delay_ceiling(commercials, 2.0)
        self.assertEqual(two["commercials"], 23)
        self.assertLess(two["held_fraction"], 0.99)
        for window in WINDOW_S:
            row = delay_ceiling(commercials, window)
            self.assertLessEqual(row["held_fraction"], two["held_fraction"])


if __name__ == "__main__":
    unittest.main()
