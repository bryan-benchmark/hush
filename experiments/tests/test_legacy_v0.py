"""Freeze discontinuity_legacy_v0 and the audit rules around it."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "experiments"))

import event_match  # noqa: E402
import ledger  # noqa: E402
import legacy_detector as det  # noqa: E402

SESSION = ROOT / "recordings" / "2026-08-27" / "hush_20260827_135935"
GOLDEN = ROOT / "experiments" / "candidates" / "hush_20260827_135935_candidates.jsonl"
BREAK_GOLDEN = ROOT / "experiments" / "candidates" / "hush_20260827_135935_break_108.json"
KEYS = (
    "elapsed_seconds",
    "score",
    "rms_dbfs",
    "loudness_jump_db",
    "flux_z",
    "near_silence",
    "session",
    "file",
    "chunk_elapsed_seconds",
)


class FeatureMatch(unittest.TestCase):
    def test_vectorized_matches_loop(self):
        wav = SESSION / "audio_0001.wav"
        rate, _ch, _n, x = det.load_pcm16(wav)
        sl = x[: int(8 * rate)]
        t0, r0, f0 = det.frame_features_loop(sl, rate)
        t1, r1, f1 = det.frame_features(sl, rate)
        self.assertEqual(len(t0), len(t1))
        self.assertLess(np.max(np.abs(r0 - r1)), 1e-6)
        self.assertLess(np.max(np.abs(f0 - f1)), 1e-6)


class LegacyCandidates(unittest.TestCase):
    def test_matches_historical_top_k_6(self):
        """Closed 15-minute chunks still on disk match the saved file.

        audio_0015.wav is the short final chunk. Its chunk-local z-scores do
        not reproduce the saved rows, so that file is not the audio that
        produced them. The freeze gate is the 14 chunks that still match.
        """
        got = det.legacy_candidate_rows(SESSION, top_k=6)
        golden = [json.loads(line) for line in GOLDEN.read_text().splitlines() if line.strip()]
        closed = [r for r in golden if r["file"] != "audio_0015.wav"]
        got_closed = [r for r in got if r["file"] != "audio_0015.wav"]
        self.assertEqual(len(closed), 84)
        self.assertEqual(len(got_closed), len(closed))
        for i, (a, b) in enumerate(zip(got_closed, closed)):
            for key in KEYS:
                self.assertEqual(a[key], b[key], f"row {i} field {key}")
        last_hist = [r["score"] for r in golden if r["file"] == "audio_0015.wav"]
        last_now = [r["score"] for r in got if r["file"] == "audio_0015.wav"]
        self.assertNotEqual(last_hist, last_now)


class BreakFreeze(unittest.TestCase):
    def test_published_break_108(self):
        result = det.break_at_session_in(SESSION, 108.25)
        golden = json.loads(BREAK_GOLDEN.read_text())
        self.assertEqual(result["published"]["fades"], golden["fades"])
        self.assertEqual(result["published"]["suggested_out"], golden["suggested_out"])
        self.assertEqual(result["published"]["out_candidates"], golden["out_candidates"])
        self.assertEqual(result["window_start"], golden["window_start"])


class EventMatch(unittest.TestCase):
    def test_one_to_one_not_three_true_positives(self):
        pairs = event_match.match_one_to_one([100.0], [99.5, 100.2, 101.0], 2.0)
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0][0], 0)

    def test_outside_collar_unmatched(self):
        pairs = event_match.match_one_to_one([100.0], [103.0], 2.0)
        self.assertEqual(pairs, [])

    def test_recall_refused_without_coverage(self):
        scored = event_match.score_onset(
            [{"gold_id": "g", "session": "s", "start_seconds": 10.0}],
            [{"proposal_id": "p", "session": "s", "elapsed_seconds": 10.0, "score": 1}],
            [],
            2.0,
        )
        self.assertEqual(scored["gold_count"], 0)
        self.assertEqual(scored["proposal_count"], 0)
        self.assertIsNone(scored["recall"])

    def test_coverage_counts_false_negative(self):
        scored = event_match.score_onset(
            [{"gold_id": "g", "session": "s", "start_seconds": 10.0}],
            [],
            [{"session": "s", "from_seconds": 0, "to_seconds": 100, "fully_annotated": True}],
            2.0,
        )
        self.assertEqual(scored["fn"], 1)
        self.assertEqual(scored["tp"], 0)
        self.assertEqual(scored["recall"], 0)

    def test_supersede_drops_old_truth(self):
        rows = [
            {"gold_id": "a", "start_seconds": 1},
            {"gold_id": "b", "start_seconds": 2, "supersedes": "a"},
        ]
        resolved = ledger.resolve_ledger(rows, "gold_id")
        self.assertEqual([r["gold_id"] for r in resolved], ["b"])


if __name__ == "__main__":
    unittest.main()
