"""Smoke tests for causal_onset_probe_v1 (past-only context)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "experiments"))

import causal_onset_probe as probe  # noqa: E402


def _ev(t, score, sil=False):
    return {
        "elapsed_seconds": float(t),
        "boundary_score": float(score),
        "near_silence": sil,
        "rms_db": -30.0,
        "flux_z": 2.0,
        "jump_z": 1.0,
        "silence_bonus": 0.5 if sil else 0.0,
        "frame_index": int(t * 8),
        "session_sample_index": int(t * 48000),
        "file": "audio_0001.wav",
        "strong": score >= 5,
    }


class CausalPastOnly(unittest.TestCase):
    def test_no_future_keys(self):
        raw = [_ev(100 + i * 4, 2.0 + (i % 3)) for i in range(20)]
        enriched = probe.attach_causal_context(raw, 0.0, 400.0)
        for e in enriched:
            keys = e["causal"].keys()
            self.assertFalse(any(k.startswith("next_") or "future" in k for k in keys))
            self.assertIn("past_rate_5s", keys)
            self.assertIn("past_rate_30s", keys)

    def test_session_edge_ineligible(self):
        raw = [_ev(1.0, 3.0)] + [_ev(5 + i * 3, 2.0) for i in range(10)]
        enriched = probe.attach_causal_context(raw, 0.0, 400.0)
        self.assertFalse(enriched[0]["causal"]["eligible"])


if __name__ == "__main__":
    unittest.main()
