"""Unit tests for discontinuity_v1 peak finding and shoulder collapse."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "experiments"))

import discontinuity_v1 as v1  # noqa: E402


class PeakFinding(unittest.TestCase):
    def test_local_maxima_strict(self):
        scores = np.array([0.0, 1.0, 3.0, 2.0, 5.0, 4.0, 0.0], dtype=np.float64)
        peaks = v1.local_maxima(scores)
        self.assertEqual(list(peaks), [2, 4])

    def test_shoulder_collapse_keeps_taller(self):
        times = np.array([0.0, 1.0, 1.5, 10.0], dtype=np.float64)
        scores = np.array([1.0, 5.0, 4.0, 3.0], dtype=np.float64)
        peaks = np.array([1, 2, 3], dtype=np.int64)
        kept = v1.collapse_shoulders(times, scores, peaks, shoulder_s=2.0)
        self.assertEqual(list(kept), [1, 3])

    def test_break_start_prefers_cluster_onset(self):
        # Three transitions: weak start then two strong — early peak should score high.
        events = [
            {"elapsed_seconds": 100.0, "boundary_score": 2.5, "near_silence": True,
             "rms_db": -40.0, "flux_z": 1.0, "jump_z": 1.0, "silence_bonus": 0.5,
             "frame_index": 0, "session_sample_index": 0, "strong": False},
            {"elapsed_seconds": 115.0, "boundary_score": 7.0, "near_silence": False,
             "rms_db": -20.0, "flux_z": 5.0, "jump_z": 4.0, "silence_bonus": 0.0,
             "frame_index": 1, "session_sample_index": 1, "strong": True},
            {"elapsed_seconds": 130.0, "boundary_score": 6.5, "near_silence": True,
             "rms_db": -35.0, "flux_z": 4.0, "jump_z": 3.0, "silence_bonus": 0.5,
             "frame_index": 2, "session_sample_index": 2, "strong": True},
            # Isolated drama later
            {"elapsed_seconds": 400.0, "boundary_score": 9.0, "near_silence": False,
             "rms_db": -15.0, "flux_z": 8.0, "jump_z": 6.0, "silence_bonus": 0.0,
             "frame_index": 3, "session_sample_index": 3, "strong": True},
        ]
        enriched = v1.attach_context(events)
        keeps, _ = v1.propose_break_starts(enriched)
        times = [round(float(k["elapsed_seconds"]), 1) for k in keeps]
        self.assertIn(100.0, times)
        # Isolated strong peak with no future structure should not be kept
        # (or score below the cluster start). At minimum cluster start is proposed.
        start = next(k for k in enriched if k["elapsed_seconds"] == 100.0)
        iso = next(k for k in enriched if k["elapsed_seconds"] == 400.0)
        s_start = v1.break_start_score(start)["break_start_score"]
        s_iso = v1.break_start_score(iso)["break_start_score"]
        self.assertGreater(s_start, s_iso)


if __name__ == "__main__":
    unittest.main()
