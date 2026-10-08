"""Capture-time session identity."""

from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from recorder import CATALOG_COLUMNS, capture_identity, upsert_session_catalog  # noqa: E402
from hush.session_catalog import COLUMNS  # noqa: E402


class CaptureIdentity(unittest.TestCase):
    def test_a_recording_names_type_delivery_service_and_show(self):
        row = capture_identity("scripted", "streaming", "Hulu", "The Bear")
        self.assertEqual(row["content_type"], "scripted")
        self.assertEqual(row["delivery"], "streaming")
        self.assertEqual(row["network_or_service"], "Hulu")
        self.assertEqual(row["show"], "The Bear")
        self.assertTrue(row["one_program"])
        self.assertTrue(row["identity_recorded_at_capture"])

    def test_missing_service_or_show_is_rejected(self):
        with self.assertRaises(RuntimeError):
            capture_identity("sports", "streaming", "  ", "TNF")
        with self.assertRaises(RuntimeError):
            capture_identity("sports", "streaming", "Prime", "")
        with self.assertRaises(RuntimeError):
            capture_identity("commercial", "linear", "NBC", "Tonight")

    def test_multi_program_is_written_into_the_note(self):
        row = capture_identity("scripted", "linear", "NBC", "unknown", one_program=False)
        self.assertIn("More than one program", row["notes"])

    def test_catalog_upsert_keeps_other_sessions(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "SESSION_CATALOG.csv"
            identity = capture_identity("sports", "streaming", "Prime", "TNF")
            upsert_session_catalog(path, "hush_20261008_201500", "2026-10-08T20:15:00-04:00", identity)
            other = capture_identity("scripted", "linear", "NBC", "The Office")
            upsert_session_catalog(path, "hush_20261009_200000", "2026-10-09T20:00:00-04:00", other, duration_s="3600.0")
            upsert_session_catalog(path, "hush_20261008_201500", "2026-10-08T20:15:00-04:00", identity, duration_s="7200.0")
            with path.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual([row["session_id"] for row in rows], ["hush_20261008_201500", "hush_20261009_200000"])
            self.assertEqual(rows[0]["duration_s"], "7200.0")
            self.assertEqual(rows[0]["network_or_service"], "Prime")
            self.assertEqual(list(rows[0].keys()), list(CATALOG_COLUMNS))
            self.assertEqual(list(CATALOG_COLUMNS), list(COLUMNS))


if __name__ == "__main__":
    unittest.main()
