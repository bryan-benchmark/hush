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
        self.assertGreater(int(np.max(np.abs(beds["stadium"]))), 1000)
        self.assertLess(int(np.max(np.abs(beds["stadium"]))), 30000)
        # Beds share a loudness target so rain/pink are not whisper-quiet vs crowd.
        def _rms(name: str) -> float:
            return float(np.sqrt(np.mean(np.square(beds[name].astype(np.float64) / 32768.0))))

        for name in (
            "hush",
            "neon",
            "charge",
            "volt",
            "drop",
            "stadium",
            "rain",
            "fireplace",
            "pink",
            "brown",
            "ocean",
            "stream",
            "birds",
            "breeze",
            "night",
            "chimes",
            "piano",
            "pad",
            "harp",
            "meadow",
        ):
            self.assertGreater(_rms(name), 0.06, name)
        self.assertFalse(np.array_equal(beds["stadium"], beds["rain"]))
        self.assertFalse(np.array_equal(beds["pink"], beds["brown"]))
        self.assertFalse(np.array_equal(beds["ocean"], beds["pad"]))
        self.assertFalse(np.array_equal(beds["hush"], beds["pink"]))
        self.assertFalse(np.array_equal(beds["neon"], beds["charge"]))
        self.assertFalse(np.array_equal(beds["volt"], beds["drop"]))
        self.assertIn("fireplace", beds)
        self.assertIn("harp", beds)
        self.assertIn("hush", beds)
        self.assertIn("neon", beds)

    def test_program_passthrough_after_prime(self):
        beds = make_beds(use_recordings=False)
        gate = ListenerGate(beds, make_earcon(), prime_frames=32)
        tone = np.full((80, 2), 400, dtype=np.int16)
        gate.push(tone)
        out = np.zeros((32, 2), dtype=np.int16)
        gate.render(out)
        self.assertTrue(np.all(out == 400))

    def test_ring_does_not_grow_past_prime_slack(self):
        beds = make_beds(use_recordings=False)
        gate = ListenerGate(beds, make_earcon(), prime_frames=64)
        block = np.zeros((32, 2), dtype=np.int16)
        out = np.zeros((16, 2), dtype=np.int16)
        for _ in range(40):
            gate.push(block)
            # Output intentionally slower than input.
            if _ % 3 == 0:
                gate.render(out)
        self.assertLessEqual(gate._count, gate._prime + gate._slack)

    def test_closed_chunk_is_not_the_open_file(self):
        with TemporaryDirectory() as tmp:
            folder = Path(tmp)
            writer = ChunkWriter(folder, frames_per_chunk=10)
            first = writer.write(np.zeros(10 * 2, dtype=np.int16).tobytes())
            self.assertEqual(len(first), 1)
            self.assertTrue(first[0].name.endswith("audio_0001.wav"))
            self.assertNotEqual(writer.path, first[0])
            self.assertIsNone(writer.close())

    def test_manual_play_from_cover_holds_until_departure_quiet(self):
        latch = AutoLatch()
        latch.human_play(was_replacement=True)
        self.assertFalse(latch.allow_auto_mute(2))
        self.assertFalse(latch.allow_auto_mute(1))
        self.assertTrue(latch.allow_auto_mute(0))
        self.assertTrue(latch.allow_auto_mute(2))

    def test_manual_play_while_already_on_show_does_not_block_ads(self):
        latch = AutoLatch()
        latch.human_play(was_replacement=False)
        self.assertTrue(latch.allow_auto_mute(1))

    def test_manual_cover_never_blocks_auto_return(self):
        latch = AutoLatch()
        latch.human_mute(was_program=True)
        # Program-like return_votes must still be allowed — this was the stuck-cover bug.
        self.assertTrue(latch.allow_auto_play(1))
        self.assertTrue(latch.allow_auto_play(0))

    def test_cover_crossfades_and_show_returns_quickly(self):
        rate = 48000
        beds = {
            "wednesday_night": np.full((rate, 2), 12000, dtype=np.int16),
            "silence": np.zeros((rate, 2), dtype=np.int16),
        }
        gate = ListenerGate(beds, np.zeros((100, 2), dtype=np.int16), prime_frames=2048, rate=rate)
        tone = np.full((480, 2), 5000, dtype=np.int16)
        gate.push(np.tile(tone, (20, 1)))
        gate.play_replacement()
        early = np.zeros((480, 2), dtype=np.int16)
        gate.render(early)
        self.assertGreater(float(np.mean(early)), 2000)
        block = np.zeros((480, 2), dtype=np.int16)
        for _ in range(80):
            gate.push(tone)
            gate.render(block)
        self.assertGreater(gate._fade_gain, 0.98)
        self.assertEqual(gate.mode, "replacement")
        gate.play_program(prompt=True)
        frames = 0
        while gate.mode != "program" and frames < rate:
            gate.push(tone)
            gate.render(block)
            frames += 480
        self.assertEqual(gate.mode, "program")
        self.assertLess(frames, int(0.45 * rate))
        self.assertGreater(frames, int(0.15 * rate))

    def test_automatic_return_takes_the_longer_fade(self):
        rate = 48000
        beds = {
            "wednesday_night": np.full((rate, 2), 12000, dtype=np.int16),
            "silence": np.zeros((rate, 2), dtype=np.int16),
        }
        gate = ListenerGate(beds, np.zeros((100, 2), dtype=np.int16), prime_frames=2048, rate=rate)
        tone = np.full((480, 2), 5000, dtype=np.int16)
        gate.push(np.tile(tone, (20, 1)))
        gate.play_replacement()
        block = np.zeros((480, 2), dtype=np.int16)
        for _ in range(80):
            gate.push(tone)
            gate.render(block)
        gate.play_program()
        frames = 0
        while gate.mode != "program" and frames < rate * 3:
            gate.push(tone)
            gate.render(block)
            frames += 480
        self.assertEqual(gate.mode, "program")
        self.assertGreater(frames, int(1.3 * rate))
        self.assertLess(frames, int(1.7 * rate))

    def test_repeated_play_commands_do_not_stretch_the_return(self):
        rate = 48000
        beds = {
            "wednesday_night": np.full((rate, 2), 12000, dtype=np.int16),
            "silence": np.zeros((rate, 2), dtype=np.int16),
        }
        gate = ListenerGate(beds, np.zeros((100, 2), dtype=np.int16), prime_frames=2048, rate=rate)
        tone = np.full((480, 2), 8000, dtype=np.int16)
        gate.push(np.tile(tone, (20, 1)))
        gate.play_replacement()
        block = np.zeros((480, 2), dtype=np.int16)
        for _ in range(80):
            gate.push(tone)
            gate.render(block)
        gate.play_program()
        for _ in range(20):
            gate.play_program()
            gate.play_program(prompt=True)
        frames = 0
        while gate.mode != "program" and frames < rate * 3:
            gate.push(tone)
            gate.render(block)
            frames += 480
        self.assertEqual(gate.mode, "program")
        self.assertLess(frames, int(1.7 * rate))
        heard = np.zeros((480, 2), dtype=np.int16)
        gate.push(np.tile(tone, (20, 1)))
        gate.render(heard)
        self.assertGreater(int(np.max(np.abs(heard))), 1000)

    def test_output_clock_restores_television_if_the_controller_stops(self):
        rate = 48000
        beds = {
            "wednesday_night": np.full((rate, 2), 16000, dtype=np.int16),
            "silence": np.zeros((rate, 2), dtype=np.int16),
        }
        gate = ListenerGate(
            beds,
            np.zeros((100, 2), dtype=np.int16),
            prime_frames=2048,
            rate=rate,
            return_s=0.05,
        )
        tone = np.full((480, 2), 9000, dtype=np.int16)
        gate.push(np.tile(tone, (30, 1)))
        gate.play_replacement(fail_open_s=0.2)
        block = np.zeros((480, 2), dtype=np.int16)
        covered = 0
        restored = None
        for step in range(80):
            gate.push(tone)
            gate.render(block)
            covered += 480
            if gate.mode == "program" and restored is None:
                restored = covered
                break
        self.assertIsNotNone(restored)
        self.assertGreater(restored, int(0.2 * rate))
        self.assertLess(restored, int(0.45 * rate))
        self.assertTrue(gate.consume_fail_open())
        gate.push(np.tile(tone, (20, 1)))
        gate.render(block)
        self.assertGreater(int(np.max(np.abs(block))), 1000)

    def test_auto_cover_arms_the_existing_deadline(self):
        from ohush_live.sports_daemon import begin_auto_cover
        from ohush_live.tnf_lab import DEFAULT_FAIL_OPEN_S

        rate = 48000
        beds = {
            "wednesday_night": np.full((rate, 2), 16000, dtype=np.int16),
            "silence": np.zeros((rate, 2), dtype=np.int16),
        }
        gate = ListenerGate(beds, np.zeros((100, 2), dtype=np.int16), prime_frames=2048, rate=rate)
        begin_auto_cover(gate)
        self.assertEqual(gate._fail_open_samples, int(DEFAULT_FAIL_OPEN_S * rate))
        gate.play_replacement()
        self.assertIsNone(gate._fail_open_samples)

    def test_many_cover_cycles_return_the_television_each_time(self):
        rate = 48000
        beds = {
            "wednesday_night": np.full((rate, 2), 14000, dtype=np.int16),
            "silence": np.zeros((rate, 2), dtype=np.int16),
        }
        gate = ListenerGate(
            beds,
            np.zeros((100, 2), dtype=np.int16),
            prime_frames=1024,
            rate=rate,
            cover_s=0.02,
            return_s=0.02,
        )
        tone = np.full((480, 2), 7000, dtype=np.int16)
        block = np.zeros((480, 2), dtype=np.int16)
        gate.push(np.tile(tone, (20, 1)))
        for _ in range(6):
            gate.play_replacement()
            for _ in range(8):
                gate.push(tone)
                gate.render(block)
            self.assertEqual(gate.mode, "replacement")
            self.assertGreater(float(np.mean(np.abs(block))), 1000)
            gate.play_program(prompt=True)
            frames = 0
            while gate.mode != "program" and frames < rate:
                gate.push(tone)
                gate.render(block)
                frames += 480
            self.assertEqual(gate.mode, "program")
            gate.push(np.tile(tone, (8, 1)))
            gate.render(block)
            self.assertGreater(int(np.max(np.abs(block))), 1000)

    def test_output_restore_will_not_cover_the_same_departure(self):
        from ohush_live.sports import AutoLatch

        machine = Machine()
        machine.state = "MUTED"
        machine._muted_at = 0.0
        event = machine.restore_from_output(180.0, {})
        self.assertEqual(event["reason"], "output_fail_open")
        self.assertEqual(event["state_after"], "PLAY")
        self.assertEqual(machine.state, "PLAY")
        latch = AutoLatch()
        latch.human_play(was_replacement=True)
        self.assertFalse(latch.allow_auto_mute(1))
        self.assertTrue(latch.allow_auto_mute(0))
        covered = Machine()
        covered.state = "MUTED"
        covered._human_cover = True
        self.assertIsNone(covered.restore_from_output(180.0, {}))
        self.assertEqual(covered.state, "MUTED")

    def test_fail_open_tick_does_not_cover_again(self):
        from ohush_live.sports_daemon import SportsSession

        rate = 48000
        beds = {
            "wednesday_night": np.full((rate, 2), 16000, dtype=np.int16),
            "silence": np.zeros((rate, 2), dtype=np.int16),
        }
        gate = ListenerGate(beds, np.zeros((100, 2), dtype=np.int16), prime_frames=2048, rate=rate)
        gate.mode = "program"
        gate._fail_open_tripped = True
        hot = {"strong_departure": True, "departure": 1.0, "strong_return": False, "return": 0.0}
        with TemporaryDirectory() as folder:
            session = SportsSession(Path(folder))
            try:
                session.samples = rate * 200
                session.machine.state = "MUTED"
                session.machine._muted_at = 0.0
                session.families = {"speaker": dict(hot), "audio": dict(hot), "semantic": None}
                for _ in range(4):
                    session.tick(gate)
                self.assertEqual(session.machine.state, "PLAY")
                self.assertEqual(gate.mode, "program")
                self.assertFalse(session.latch.allow_auto_mute(1))
            finally:
                session.tnf.close()
                for handle in (session.decisions, session.overrides, session.ratings, session.labels, session.track):
                    handle.close()

    def test_fail_open_releases_when_the_departure_goes_quiet(self):
        from ohush_live.sports_daemon import SportsSession

        rate = 48000
        beds = {
            "wednesday_night": np.full((rate, 2), 16000, dtype=np.int16),
            "silence": np.zeros((rate, 2), dtype=np.int16),
        }
        gate = ListenerGate(beds, np.zeros((100, 2), dtype=np.int16), prime_frames=2048, rate=rate)
        gate.mode = "program"
        gate._fail_open_tripped = True
        hot = {"strong_departure": True, "departure": 1.0, "strong_return": False, "return": 0.0}
        quiet = {"strong_departure": False, "departure": 0.0, "strong_return": False, "return": 0.0}
        with TemporaryDirectory() as folder:
            session = SportsSession(Path(folder))
            try:
                session.samples = rate * 200
                session.machine.state = "MUTED"
                session.machine._muted_at = 0.0
                session.families = {"speaker": dict(hot), "audio": dict(hot), "semantic": None}
                session.tick(gate)
                self.assertEqual(gate.mode, "program")
                session.families = {"speaker": dict(quiet), "audio": dict(quiet), "semantic": None}
                session.tick(gate)
                self.assertFalse(session.latch.suppress_mute)
                session.families = {"speaker": dict(hot), "audio": dict(hot), "semantic": None}
                for _ in range(3):
                    session.tick(gate)
                self.assertEqual(session.machine.state, "MUTED")
                self.assertEqual(gate.mode, "replacement")
                self.assertIsNotNone(gate._fail_open_samples)
            finally:
                session.tnf.close()
                for handle in (session.decisions, session.overrides, session.ratings, session.labels, session.track):
                    handle.close()

    def test_hint_does_not_unmute(self):
        machine = Machine()
        machine.state = "MUTED"
        hint = ReturnHint()
        self.assertFalse(hint.update(True, 1, 1))
        self.assertFalse(hint.update(True, 1, 1))
        self.assertTrue(hint.update(True, 1, 1))
        self.assertEqual(machine.state, "MUTED")

    def test_decision_is_not_science(self):
        row = decision_row(1.5, "PROGRAM_TO_REPLACEMENT", "auto", {"speaker": None, "audio": None, "semantic": None}, "hush", False)
        self.assertFalse(row["scientific_authority"])
        self.assertFalse(row["allowed_to_change_exp001_005"])
        self.assertEqual(row["dataset_role"], "live_dev")
        self.assertEqual(row["replacement"], "hush")

    def test_uploader_command_does_not_delete(self):
        command = cp_command(Path("audio_0001.wav"), "gs://bucket/live/s/audio_0001.wav", "abc")
        self.assertNotIn("--delete-unmatched-destination-objects", command)
        self.assertTrue(verified({"metadata": {"sha256": "abc"}, "size": "10"}, "abc", 10))
        self.assertFalse(verified({"metadata": {"sha256": "nope"}, "size": "10"}, "abc", 10))


if __name__ == "__main__":
    unittest.main()
