"""Session catalog window placement and the holdout seal."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from hush.session_catalog import (  # noqa: E402
    contiguous_runs,
    export_clip,
    holdout_ids,
    merge_catalog,
    middle_window,
)


class WindowPlacement(unittest.TestCase):
    def test_centers_25s_on_the_session_midpoint(self):
        runs = [(0.0, 3600.0)]
        start, end, reason = middle_window(runs)
        self.assertAlmostEqual(start, 1800.0 - 12.5)
        self.assertAlmostEqual(end, 1800.0 + 12.5)
        self.assertIn("geometric middle", reason)

    def test_gap_at_the_middle_uses_nearest_audio_and_does_not_cross(self):
        runs = [(0.0, 1000.0), (2000.0, 3000.0)]
        start, end, reason = middle_window(runs)
        self.assertIn("gap", reason)
        self.assertTrue((end <= 1000.0) or (start >= 2000.0))
        self.assertAlmostEqual(end - start, 25.0)
        self.assertAlmostEqual(end, 1000.0)

    def test_short_run_is_not_padded(self):
        start, end, reason = middle_window([(10.0, 18.0)])
        self.assertEqual((start, end), (10.0, 18.0))
        self.assertIn("shorter than 20 s", reason)

    def test_missing_chunk_file_splits_the_run(self):
        chunks = [
            {"file": "audio_0001.wav", "start_elapsed_seconds": 0.0, "end_elapsed_seconds": 900.0},
            {"file": "audio_0002.wav", "start_elapsed_seconds": 900.0, "end_elapsed_seconds": 1800.0},
            {"file": "audio_0003.wav", "start_elapsed_seconds": 1800.0, "end_elapsed_seconds": 2700.0},
        ]
        runs = contiguous_runs(chunks, present={"audio_0001.wav", "audio_0003.wav"})
        self.assertEqual(runs, [(0.0, 900.0), (1800.0, 2700.0)])


class CatalogMerge(unittest.TestCase):
    def test_filled_identity_survives_a_refresh(self):
        fresh = [
            {
                "session_id": "hush_20260914_212529",
                "date": "2026-09-14",
                "content_type": "",
                "delivery": "",
                "network_or_service": "",
                "show": "",
                "notes": "",
                "started_local": "2026-09-14T21:25:29-04:00",
                "duration_s": "7200.0",
                "role": "dev",
            }
        ]
        existing = [
            {
                "session_id": "hush_20260914_212529",
                "content_type": "sports",
                "delivery": "linear",
                "network_or_service": "ESPN",
                "show": "MNF",
                "notes": "heard the booth",
            }
        ]
        row = merge_catalog(existing, fresh)[0]
        self.assertEqual(row["show"], "MNF")
        self.assertEqual(row["notes"], "heard the booth")
        self.assertEqual(row["duration_s"], "7200.0")

    def test_known_dev_game_fills_only_blank_cells(self):
        fresh = [
            {
                "session_id": "hush_20260914_212529",
                "date": "2026-09-14",
                "content_type": "",
                "delivery": "",
                "network_or_service": "",
                "show": "",
                "notes": "",
                "started_local": "x",
                "duration_s": "1.0",
                "role": "dev",
            }
        ]
        row = merge_catalog([], fresh)[0]
        self.assertEqual(row["show"], "MNF")
        self.assertEqual(row["network_or_service"], "ESPN")


class HoldoutSeal(unittest.TestCase):
    def test_gold_files_name_the_same_two_sessions(self):
        self.assertEqual(holdout_ids(), {"hush_20260917_205513", "hush_20260920_200635"})

    def test_export_refuses_a_holdout_path(self):
        sealed = holdout_ids()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "hush_20260917_205513"
            path.mkdir()
            with self.assertRaises(RuntimeError):
                export_clip(path, sealed, Path(tmp) / "clips")


if __name__ == "__main__":
    unittest.main()
