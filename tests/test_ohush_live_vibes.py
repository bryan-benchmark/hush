"""VIBE_STARTER_001 — playback library tests. No detector changes."""

from __future__ import annotations

import os
import unittest

import numpy as np

from ohush_live.gate import ListenerGate
from ohush_live.sounds import make_earcon
from ohush_live.vibes.catalog import DEFAULT_VIBE, TRACKS, resolve_vibe_track, vibe_bed_names
from ohush_live.vibes.loader import PROCESSED, available_replacements, load_vibe_beds
from ohush_live.vibes.prepare import TARGET_RMS, _normalize_rms


class VibeCatalogTests(unittest.TestCase):
    def test_default_is_wednesday_night(self):
        self.assertEqual(DEFAULT_VIBE, "wednesday_night")
        self.assertEqual(resolve_vibe_track("wednesday_night"), "wednesday_night")

    def test_missing_bed_raises(self):
        with self.assertRaises(KeyError):
            resolve_vibe_track("not_a_vibe")


class VibePrepareTests(unittest.TestCase):
    def test_normalize_rms_no_clip(self):
        rng = np.random.default_rng(0)
        audio = rng.normal(0, 0.5, size=(48000, 2))
        out = _normalize_rms(audio)
        rms = float(np.sqrt(np.mean(np.square(out))))
        peak = float(np.max(np.abs(out)))
        self.assertLess(abs(rms - TARGET_RMS), 0.03)
        self.assertLessEqual(peak, 0.901)


@unittest.skipUnless(
    (PROCESSED / "wednesday_night.wav").is_file(),
    "processed vibes missing — run python -m ohush_live.vibes.prepare",
)
class VibePlaybackTests(unittest.TestCase):
    def test_all_catalog_tracks_processed(self):
        for name in TRACKS:
            self.assertTrue((PROCESSED / f"{name}.wav").is_file(), name)

    def test_load_and_switch_vibes(self):
        beds = load_vibe_beds(require_all=True)
        gate = ListenerGate(beds, make_earcon(), prime_frames=64)
        self.assertEqual(gate.replacement, "wednesday_night")
        gate.set_replacement("friends_over")
        self.assertEqual(gate.replacement, "friends_over")
        gate.set_replacement("silence")
        out = np.zeros((256, 2), dtype=np.int16)
        gate.play_replacement()
        gate.render(out)
        self.assertEqual(int(np.max(np.abs(out))), 0)

    def test_missing_file_set_replacement(self):
        beds = load_vibe_beds(require_all=True)
        gate = ListenerGate(beds, make_earcon(), prime_frames=64)
        with self.assertRaises(KeyError):
            gate.set_replacement("does_not_exist")

    def test_loop_boundary_continuous(self):
        beds = load_vibe_beds(require_all=True)
        gate = ListenerGate(beds, make_earcon(), prime_frames=64)
        gate.set_replacement("rainy_night")
        gate.play_replacement()
        # Drain fade-in.
        buf = np.zeros((512, 2), dtype=np.int16)
        for _ in range(30):
            gate.render(buf)
        bed = beds["rainy_night"]
        gate._pos = len(bed) - 100
        gate.render(buf)
        self.assertGreater(int(np.max(np.abs(buf))), 0)

    def test_rapid_cover_show_preserves_position(self):
        beds = load_vibe_beds(require_all=True)
        gate = ListenerGate(beds, make_earcon(), prime_frames=64)
        gate.set_replacement("wednesday_night")
        program = np.full((4000, 2), 500, dtype=np.int16)
        gate.push(program)
        out = np.zeros((256, 2), dtype=np.int16)
        gate.play_replacement()
        for _ in range(20):
            gate.render(out)
        pos = gate._pos
        gate.play_program()
        for _ in range(30):
            gate.render(out)
            gate.push(program[:512])
        self.assertEqual(gate.mode, "program")
        gate.play_replacement()
        # Position may advance during fade-out, but Cover must not restart at 0.
        self.assertNotEqual(gate._pos, 0)
        self.assertGreaterEqual(gate._pos, pos)

    def test_volume_adjustment(self):
        beds = load_vibe_beds(require_all=True)
        gate = ListenerGate(beds, make_earcon(), prime_frames=64)
        gate.set_replacement("wednesday_night")
        gate.play_replacement()
        out = np.zeros((1024, 2), dtype=np.int16)
        for _ in range(30):
            gate.render(out)
        gate.set_volume(0.2)
        quiet = []
        for _ in range(10):
            gate.render(out)
            quiet.append(float(np.mean(np.abs(out))))
        gate.set_volume(1.0)
        loud = []
        for _ in range(10):
            gate.render(out)
            loud.append(float(np.mean(np.abs(out))))
        self.assertLess(np.mean(quiet), np.mean(loud))

    def test_experiment_flag_lists_vibes(self):
        prev = os.environ.get("OHUSH_VIBES_EXPERIMENT")
        try:
            os.environ["OHUSH_VIBES_EXPERIMENT"] = "1"
            from ohush_live.sports import active_default_replacement, active_replacements

            self.assertEqual(active_default_replacement(), "wednesday_night")
            names = active_replacements()
            self.assertIn("wednesday_night", names)
            self.assertIn("silence", names)
            self.assertTrue(set(available_replacements()).issubset(set(names) | {"silence"}))
        finally:
            if prev is None:
                os.environ.pop("OHUSH_VIBES_EXPERIMENT", None)
            else:
                os.environ["OHUSH_VIBES_EXPERIMENT"] = prev

    def test_flag_off_keeps_neon_only(self):
        prev = os.environ.get("OHUSH_VIBES_EXPERIMENT")
        try:
            os.environ["OHUSH_VIBES_EXPERIMENT"] = "0"
            from importlib import reload
            import ohush_live.sports as sports

            reload(sports)
            self.assertEqual(sports.active_default_replacement(), "neon")
            self.assertEqual(sports.active_replacements(), ("silence", "neon"))
        finally:
            if prev is None:
                os.environ.pop("OHUSH_VIBES_EXPERIMENT", None)
            else:
                os.environ["OHUSH_VIBES_EXPERIMENT"] = prev


if __name__ == "__main__":
    unittest.main()
