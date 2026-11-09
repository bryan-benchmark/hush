"""Promotional-read overlay. Gold is read through the saved score and not written."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from experiments.nfl75.promo_class import (
    BOOTH_PATH,
    audited_seconds,
    load_overlay,
    score_views,
    spans_for,
    subtract_ranges,
    view_metrics,
)


def _episode(start: float, end: float) -> dict:
    return {
        "start_s": start,
        "end_s": end,
        "duration_s": end - start,
        "parts": [{"start_s": start, "end_s": end}],
    }


class PromoClassTests(unittest.TestCase):
    def test_overlay_keeps_every_historical_label_as_program(self):
        overlay = load_overlay()
        self.assertFalse(overlay["gold_labels_changed"])
        self.assertEqual(
            {row["gold_label"] for row in overlay["spans"]},
            {"program"},
        )
        october = audited_seconds(overlay, "hush_20261008_205100", bucket=True)
        september = audited_seconds(overlay, "hush_20260924_220624", bucket=True)
        self.assertAlmostEqual(october, 137.205)
        self.assertAlmostEqual(september, 107.228)
        self.assertAlmostEqual(
            audited_seconds(overlay, "hush_20261008_205100", bucket=False),
            137.205,
        )
        self.assertAlmostEqual(
            audited_seconds(overlay, "hush_20260924_220624", bucket=False),
            47.84,
        )

    def test_consumer_view_drops_a_read_and_keeps_the_desk(self):
        overlay = load_overlay()
        episodes = [
            _episode(3391.0, 3445.0),
            _episode(9156.0, 9169.0),
        ]
        policy = {
            "episodes": episodes,
            "program_s": 1000.0,
            "commercial_coverage": 0.95,
            "commercial_s": 100.0,
            "breaks_missed": 0,
            "breaks": [],
        }
        scored = score_views(overlay, "hush_20261008_205100", policy)
        research = scored["views"]["research"]
        consumer = scored["views"]["consumer"]
        self.assertEqual(research["false_mute_episodes"], 2)
        self.assertEqual(consumer["false_mute_episodes"], 1)
        self.assertAlmostEqual(consumer["program_covered_s"], 13.0)
        desk = next(row for row in scored["program_examples_muted_s"] if row["id"] == "oct_dropped_pass")
        self.assertAlmostEqual(desk["muted_s"], 13.0)
        self.assertEqual(spans_for(overlay, "hush_20261008_205100", "research"), [])

    def test_a_gap_over_two_seconds_splits_after_the_middle_is_removed(self):
        kept = subtract_ranges([(0.0, 30.0)], [(4.0, 8.0)])
        scored = view_metrics([_episode(0.0, 30.0)], 100.0, [(4.0, 8.0)])
        self.assertEqual(kept, [(0.0, 4.0), (8.0, 30.0)])
        self.assertEqual(scored["false_mute_episodes"], 2)
        self.assertAlmostEqual(scored["program_covered_s"], 26.0)

    def test_published_research_score_is_unchanged_before_the_overlay(self):
        overlay = load_overlay()
        booth = json.loads(BOOTH_PATH.read_text(encoding="utf-8"))
        october = next(row for row in booth["sessions"] if row["session"] == "hush_20261008_205100")
        stored = october["policies"]["unprotected"]["oracle"]
        scored = score_views(overlay, october["session"], stored)
        research = scored["views"]["research"]
        consumer = scored["views"]["consumer"]
        self.assertEqual(research["false_mute_episodes"], stored["false_mute_episodes"])
        self.assertAlmostEqual(research["program_covered_s"], stored["program_covered_s"], places=2)
        self.assertEqual(consumer["false_mute_episodes"], stored["false_mute_episodes"] - 5)
        self.assertAlmostEqual(consumer["class_muted_s"], 137.205, places=2)
        dropped = next(row for row in scored["program_examples_muted_s"] if row["id"] == "oct_dropped_pass")
        self.assertGreater(dropped["muted_s"], 0.0)


if __name__ == "__main__":
    unittest.main()
