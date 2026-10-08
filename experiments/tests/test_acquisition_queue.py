"""Acquisition classes and a review queue that is one item per event."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "experiments"))

import acquisition  # noqa: E402
import datasets  # noqa: E402
import review_queue  # noqa: E402


class AcquisitionClass(unittest.TestCase):
    def test_transient_is_not_a_commercial_score(self):
        verdict = acquisition.classify_chunk({
            "duration_seconds": 900,
            "near_silence_fraction": 0.999,
            "digital_zero_fraction": 0.2,
            "rms_max_db": -36,
            "rms_p95_db": -120,
            "clipping_fraction": 0,
            "longest_flatline_seconds": 10,
        })
        self.assertFalse(verdict["eligible_for_detection"])
        self.assertEqual(verdict["reason"], "mostly_silence_plus_transient")

    def test_full_silence(self):
        verdict = acquisition.classify_chunk({
            "duration_seconds": 900,
            "near_silence_fraction": 1,
            "digital_zero_fraction": 1,
            "rms_max_db": -120,
            "rms_p95_db": -120,
            "clipping_fraction": 0,
            "longest_flatline_seconds": 900,
        })
        self.assertEqual(verdict["reason"], "digital_silence")

    def test_valid_tv(self):
        verdict = acquisition.classify_chunk({
            "duration_seconds": 900,
            "near_silence_fraction": 0.02,
            "digital_zero_fraction": 0,
            "rms_max_db": -8,
            "rms_p95_db": -18,
            "clipping_fraction": 0,
            "longest_flatline_seconds": 0.2,
        })
        self.assertTrue(verdict["eligible_for_detection"])
        self.assertEqual(verdict["reason"], "valid_tv_audio")


class QueueShape(unittest.TestCase):
    def test_diverse_keeps_skip_shoulders_and_holdouts(self):
        self.assertFalse(datasets.reviewable("hush_20260920_200635"))
        self.assertTrue(datasets.reviewable("hush_20260912_215850"))
        self.assertEqual(datasets.role_of("hush_20260912_215850"), "dev")
        self.assertTrue(datasets.reviewable("hush_20260914_212529"))
        rows = [
            {"session": "hush_20260914_212529", "file": "a.wav", "elapsed_seconds": 10, "score": 20, "proposal_id": "a"},
            {"session": "hush_20260914_212529", "file": "a.wav", "elapsed_seconds": 10.125, "score": 19, "proposal_id": "b"},
            {"session": "hush_20260914_212529", "file": "a.wav", "elapsed_seconds": 400, "score": 9, "proposal_id": "c"},
            {"session": "hush_20260909_213047", "file": "a.wav", "elapsed_seconds": 50, "score": 8, "proposal_id": "d"},
        ]
        picked = review_queue.highest_diverse_keeps(rows, n=4, per_session=2)
        ids = [p["proposal_id"] for p in picked]
        self.assertEqual(ids, ["a", "c", "d"])

    def test_manifests_agree_on_session_role(self):
        import json
        from pathlib import Path

        gold = Path(__file__).resolve().parents[1] / "gold"
        holdout = json.loads((gold / "HOLDOUT_V1.json").read_text())
        for row in holdout["reserved_sessions"]:
            self.assertEqual(datasets.role_of(row["session"]), row["role"])
        for row in holdout["removed_from_holdout"]:
            self.assertEqual(datasets.role_of(row["session"]), row["now"])
        fixtures = json.loads((gold / "ACQUISITION_FIXTURES_V1.json").read_text())
        dead = [c for c in fixtures["clips"] if c["session"] == "hush_20260912_215850"]
        self.assertGreater(len(dead), 0)
        self.assertTrue(all(c["audio_present"] is False for c in dead))
        self.assertEqual(datasets.role_of("hush_20260912_215850"), "dev")

    def test_min_gap_queue_is_one_peak_per_winner(self):
        selections = []
        proposals = {}
        for i, t in enumerate([11291.375, 11291.5, 11291.625, 11291.875, 11320.0]):
            pid = f"p{i}"
            proposals[pid] = {
                "proposal_id": pid,
                "session": "hush_20260914_212529",
                "file": "audio_0001.wav",
                "elapsed_seconds": t,
                "score": 50 - i,
            }
            selections.append({
                "stage": "in",
                "action": "suppress",
                "reason": "min_gap",
                "proposal_id": pid,
                "winning_proposal_id": "winner",
                "gap_seconds": abs(t - 11291.75),
                "session": "hush_20260914_212529",
                "file": "audio_0001.wav",
            })
        items = review_queue.meaningful_suppressions(selections, proposals, eligible=None, n=8)
        self.assertEqual(len(items), 1)
        self.assertGreaterEqual(items[0]["gap_seconds"], 1.0)
        self.assertEqual(items[0]["elapsed_seconds"], 11320.0)


if __name__ == "__main__":
    unittest.main()
