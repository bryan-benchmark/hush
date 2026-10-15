"""Sitting boundaries. No microphone and no live engine."""

import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from ohush_live.sittings import CONTINUE_WITHIN_S, append_chunk, should_continue


EASTERN = timezone(timedelta(hours=-4))


def _active(folder: Path, when: datetime, **extra) -> dict:
    row = {
        "folder": str(folder),
        "show": "Bucs at Cowboys",
        "service": "Prime Video",
        "content": "sports",
        "last_audio_at": when.isoformat(),
    }
    row.update(extra)
    return row


class SittingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.folder = Path(self.tmp.name) / "hush_20261013_204200"
        self.folder.mkdir()
        (self.folder / "session.json").write_text("{}\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_same_show_within_half_an_hour_continues(self):
        start = datetime(2026, 10, 13, 20, 42, tzinfo=EASTERN)
        now = start + timedelta(minutes=12)
        self.assertTrue(
            should_continue(
                _active(self.folder, start),
                show="Bucs at Cowboys",
                service="Prime Video",
                content="sports",
                now=now,
                fresh=False,
            )
        )

    def test_later_night_is_a_new_session(self):
        start = datetime(2026, 10, 13, 20, 42, tzinfo=EASTERN)
        now = start + timedelta(minutes=31)
        self.assertFalse(
            should_continue(
                _active(self.folder, start),
                show="bucs at cowboys",
                service="Prime Video",
                content="sports",
                now=now,
                fresh=False,
            )
        )
        self.assertEqual(CONTINUE_WITHIN_S, 30 * 60)

    def test_different_name_or_explicit_new_does_not_append(self):
        start = datetime(2026, 10, 13, 20, 42, tzinfo=EASTERN)
        now = start + timedelta(minutes=5)
        self.assertFalse(
            should_continue(
                _active(self.folder, start),
                show="Monday Night Football",
                service="Prime Video",
                content="sports",
                now=now,
                fresh=False,
            )
        )
        self.assertFalse(
            should_continue(
                _active(self.folder, start),
                show="Bucs at Cowboys",
                service="Prime Video",
                content="sports",
                now=now,
                fresh=True,
            )
        )

    def test_pending_folder_is_not_a_sitting(self):
        start = datetime(2026, 10, 13, 20, 42, tzinfo=EASTERN)
        pending = Path(self.tmp.name) / ".pending"
        pending.mkdir()
        (pending / "session.json").write_text("{}\n", encoding="utf-8")
        active = _active(pending, start)
        self.assertFalse(
            should_continue(
                active,
                show="Bucs at Cowboys",
                service="Prime Video",
                content="sports",
                now=start + timedelta(minutes=1),
                fresh=False,
            )
        )

    def test_chunk_timeline_skips_a_hole_and_keeps_audio_order(self):
        meta: dict = {"chunks": [], "gaps": []}
        opened = datetime(2026, 10, 13, 20, 42, tzinfo=EASTERN)
        append_chunk(
            meta,
            file="audio_0001.wav",
            seconds=900,
            opened_at=opened,
            closed_at=opened + timedelta(seconds=900),
        )
        resumed = opened + timedelta(seconds=900, minutes=18)
        append_chunk(
            meta,
            file="audio_0002.wav",
            seconds=120,
            opened_at=resumed,
            closed_at=resumed + timedelta(seconds=120),
        )
        append_chunk(
            meta,
            file="audio_0002.wav",
            seconds=120,
            opened_at=resumed,
            closed_at=resumed + timedelta(seconds=120),
        )
        self.assertEqual(meta["chunks"][0]["start_elapsed_seconds"], 0)
        self.assertEqual(meta["chunks"][1]["start_elapsed_seconds"], 900)
        self.assertEqual(meta["audio_seconds"], 1020)
        self.assertEqual(len(meta["chunks"]), 2)
        self.assertEqual(meta["gaps"][0]["after_elapsed_s"], 900)
        self.assertGreater(meta["gaps"][0]["wall_gap_s"], 60)
        self.assertTrue(meta["label_queue"])


if __name__ == "__main__":
    unittest.main()
