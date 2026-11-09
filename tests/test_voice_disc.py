"""The margin and the cohort formula stay fixed. They do not learn a line."""

from __future__ import annotations

import unittest

import numpy as np

from experiments.nfl75.voice_disc import MARGIN, margin_decision, max_over_references, symmetric_snorm


class VoiceDiscTests(unittest.TestCase):
    def test_margin_is_the_declared_gap(self):
        self.assertEqual(MARGIN, 0.15)

    def test_a_high_cosine_with_a_close_runner_up_stays_unknown(self):
        found = margin_decision({"Andrew Whitworth": 0.67, "Tony Gonzalez": 0.59})
        self.assertIsNone(found["accepted"])
        self.assertEqual(found["reason"], "thin_margin")
        self.assertEqual(found["rank1"], "Andrew Whitworth")

    def test_a_separated_cosine_above_the_line_keeps_the_name(self):
        found = margin_decision({"Kirk Herbstreit": 0.55, "Al Michaels": 0.10})
        self.assertEqual(found["accepted"], "Kirk Herbstreit")
        self.assertEqual(found["reason"], "separated")

    def test_a_wide_gap_under_the_line_is_still_unknown(self):
        found = margin_decision({"Kirk Herbstreit": 0.20, "Al Michaels": 0.01})
        self.assertIsNone(found["accepted"])
        self.assertEqual(found["reason"], "below_line")

    def test_max_over_references_uses_the_nearest_clip(self):
        probe = np.asarray([1.0, 0.0], dtype=np.float32)
        scores = max_over_references(
            probe,
            {
                "Al Michaels": [np.asarray([0.6, 0.8], dtype=np.float32), np.asarray([1.0, 0.0], dtype=np.float32)],
            },
        )
        self.assertAlmostEqual(scores["Al Michaels"], 1.0)

    def test_symmetric_snorm_is_zero_at_the_cohort_center(self):
        found = symmetric_snorm(0.2, [0.1, 0.3], [0.0, 0.4])
        self.assertAlmostEqual(found, 0.0)

    def test_symmetric_snorm_rises_when_the_trial_clears_both_cohorts(self):
        found = symmetric_snorm(0.5, [0.1, 0.3], [0.0, 0.2])
        self.assertAlmostEqual(found, 3.5)
