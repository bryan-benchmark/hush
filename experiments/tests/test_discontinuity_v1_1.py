"""Tests for discontinuity_v1_1 episode vs localization split."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "experiments"))

import discontinuity_v1_1 as v11  # noqa: E402


def _ev(t, score, sil=False):
    return {
        "elapsed_seconds": float(t),
        "boundary_score": float(score),
        "near_silence": sil,
        "rms_db": -30.0,
        "flux_z": 2.0,
        "jump_z": 2.0,
        "silence_bonus": 0.5 if sil else 0.0,
        "frame_index": int(t * 8),
        "session_sample_index": int(t * 48000),
        "file": "audio_0001.wav",
        "strong": score >= 5,
    }


class EpisodeLocalize(unittest.TestCase):
    def test_session_edge_not_eligible(self):
        # Busy future, empty past only because t is near 0
        events = [_ev(1.0, 3.0)] + [_ev(5 + i * 3, 6.0) for i in range(8)]
        enriched = v11.attach_rolling_intensity(events, 0.0, 900.0)
        first = enriched[0]
        self.assertFalse(first["context"]["eligible"])
        ep = v11.episode_score(first)
        self.assertFalse(ep["actionable"])

    def test_localize_picks_regime_change_not_loudest(self):
        # Sparse weak program peaks, then strong dense break; loudest is mid-break.
        raw = (
            [_ev(100 + i * 25, 2.0) for i in range(4)]
            + [_ev(200.0, 5.2, sil=True)]
            + [_ev(208 + i * 10, 7.0 + (i == 3) * 3, sil=True) for i in range(6)]
        )
        enriched = v11.attach_rolling_intensity(raw, 0.0, 900.0)
        anchor = max(
            (e for e in enriched if e["boundary_score"] >= 5),
            key=lambda e: e["boundary_score"],
        )
        anchor = {**anchor, "episode_score": 10.0}
        loc = v11.localize_onset(anchor, enriched)
        onset_t = float(loc["onset"]["elapsed_seconds"])
        self.assertLess(onset_t, float(anchor["elapsed_seconds"]))
        self.assertGreaterEqual(onset_t, 195.0)


if __name__ == "__main__":
    unittest.main()
