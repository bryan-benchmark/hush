"""Sports gate, chunks, and manual latch. No microphones and no experiment files."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

from ohush_live.chunk_uploader import cp_command, verified
from ohush_live.chunks import ChunkWriter
from ohush_live.gate import ListenerGate
from ohush_live.sounds import make_beds, make_earcon
from ohush_live.sports import AutoLatch, ReturnHint, decision_row
from ohush_live.state import Machine


class SportsTests(unittest.TestCase):
    def test_replacement_does_not_change_what_was_captured(self):
        beds = make_beds(use_recordings=False)
        gate = ListenerGate(beds, make_earcon(), prime_frames=64)
        original = np.full((256, 2), 1000, dtype=np.int16)
        gate.push(original.copy())
        gate.play_replacement()
        heard = np.zeros((128, 2), dtype=np.int16)
        gate.render(heard)
        self.assertFalse(np.array_equal(heard, original[:128]))
        self.assertTrue(np.array_equal(original, np.full((256, 2), 1000, dtype=np.int16)))

    def test_silence_bed_is_silent_and_stadium_is_not(self):
        beds = make_beds(use_recordings=False)
        self.assertEqual(int(np.max(np.abs(beds["silence"]))), 0)
        self.assertGreater(int(np.max(np.abs(beds["stadium"]))), 100)
        self.assertLess(int(np.max(np.abs(beds["stadium"]))), 2500)
        self.assertFalse(np.array_equal(beds["stadium"], beds["rain"]))
        self.assertFalse(np.array_equal(beds["pink"], beds["brown"]))
        self.assertIn("fireplace", beds)

    def test_program_passthrough_after_prime(self):
        beds = make_beds(use_recordings=False)
        gate = ListenerGate(beds, make_earcon(), prime_frames=32)
        tone = np.full((80, 2), 400, dtype=np.int16)
        gate.push(tone)
        out = np.zeros((32, 2), dtype=np.int16)
        gate.render(out)
        self.assertTrue(np.all(out == 400))

    def test_closed_chunk_is_not_the_open_file(self):
        with TemporaryDirectory() as tmp:
            folder = Path(tmp)
            writer = ChunkWriter(folder, frames_per_chunk=10)
            first = writer.write(np.zeros(10 * 2, dtype=np.int16).tobytes())
            self.assertEqual(len(first), 1)
            self.assertTrue(first[0].name.endswith("audio_0001.wav"))
            self.assertNotEqual(writer.path, first[0])
            self.assertIsNone(writer.close())

    def test_manual_play_holds_through_the_current_break(self):
        latch = AutoLatch()
        latch.human_play()
        self.assertFalse(latch.allow_auto_mute(2))
        self.assertFalse(latch.allow_auto_mute(2))
        self.assertFalse(latch.allow_auto_mute(0))
        self.assertTrue(latch.allow_auto_mute(2))

    def test_hint_does_not_unmute(self):
        machine = Machine()
        machine.state = "MUTED"
        hint = ReturnHint()
        self.assertFalse(hint.update(True, 1, 1))
        self.assertFalse(hint.update(True, 1, 1))
        self.assertTrue(hint.update(True, 1, 1))
        self.assertEqual(machine.state, "MUTED")

    def test_decision_is_not_science(self):
        row = decision_row(1.5, "PROGRAM_TO_REPLACEMENT", "auto", {"speaker": None, "audio": None, "semantic": None}, "stadium", False)
        self.assertFalse(row["scientific_authority"])
        self.assertFalse(row["allowed_to_change_exp001_005"])
        self.assertEqual(row["dataset_role"], "live_dev")
        self.assertEqual(row["replacement"], "stadium")

    def test_uploader_command_does_not_delete(self):
        command = cp_command(Path("audio_0001.wav"), "gs://bucket/live/s/audio_0001.wav", "abc")
        self.assertNotIn("--delete-unmatched-destination-objects", command)
        self.assertTrue(verified({"metadata": {"sha256": "abc"}, "size": "10"}, "abc", 10))
        self.assertFalse(verified({"metadata": {"sha256": "nope"}, "size": "10"}, "abc", 10))


if __name__ == "__main__":
    unittest.main()
