"""Replay test: a query cannot use a landmark whose second peak falls at or after the decision time.

Universal v1 calls window_hashes from known_ad_fingerprint. The receipts do not
store peak times, so this test checks that function, which is the gate the
replay uses.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "experiments/broadcast_intelligence/third_party/audfprint"))
sys.path.insert(0, str(REPO))

import numpy as np

from experiments.broadcast_intelligence.known_ad_fingerprint import frame_of, window_hashes


class LandmarkWindowTest(unittest.TestCase):
    def test_second_peak_at_the_decision_time_is_excluded(self):
        t0, t1 = 10.0, 15.0
        f0 = frame_of(t0)
        f1 = frame_of(t1)
        anchor = np.array([f0 + 10, f0 + 10], dtype=np.int32)
        # First landmark ends inside the query. Second ends on the decision frame.
        delta = np.array([5, f1 - (f0 + 10)], dtype=np.int16)
        hashes = np.array([1, 2], dtype=np.int32)
        kept_frames, kept_hashes = window_hashes(anchor, hashes, delta, t0, t1)
        self.assertEqual(kept_hashes.tolist(), [1])
        self.assertTrue(np.all(kept_frames + 5 < f1))

    def test_both_peaks_inside_are_kept(self):
        t0, t1 = 10.0, 15.0
        f0 = frame_of(t0)
        anchor = np.array([f0 + 3], dtype=np.int32)
        delta = np.array([4], dtype=np.int16)
        hashes = np.array([7], dtype=np.int32)
        kept_frames, kept_hashes = window_hashes(anchor, hashes, delta, t0, t1)
        self.assertEqual(kept_hashes.tolist(), [7])
        self.assertLess(int(kept_frames[0] + delta[0]), frame_of(t1))


if __name__ == "__main__":
    unittest.main()
