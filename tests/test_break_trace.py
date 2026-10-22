"""The break trace records why it stayed on play. No audio."""

import unittest

from hush.break_trace import SignOff, decide, pattern, sentence


class BreakTraceTests(unittest.TestCase):
    def test_song_under_the_booth_stays_play(self):
        decision = decide(["music_rose"], authorized_cover=False)
        self.assertEqual(decision["action"], "play")
        self.assertIn("song_arrived_under_the_broadcast", decision["candidates"])
        text = sentence(["music_rose"], decision, "Mike Tirico")
        self.assertIn("Play", text)
        self.assertIn("Mike Tirico", text)

    def test_published_fingerprint_is_the_only_cover(self):
        decision = decide(["music_rose"], authorized_cover=True)
        self.assertEqual(decision["action"], "cover")
        self.assertEqual(decision["authorized_by"], "universal_v1_count_200")
        self.assertEqual(decision["blocked"], [])

    def test_sign_off_arms_then_confirms_without_covering(self):
        watcher = SignOff()
        self.assertIsNone(watcher.step(0, 0.1, True, False))
        self.assertEqual(watcher.step(8, 0.8, True, True), "arm")
        self.assertEqual(watcher.step(12, 0.9, False, False), "confirm")
        decision = decide(["booth_left"], authorized_cover=False)
        self.assertEqual(decision["action"], "play")

    def test_quiet_resets_the_sign_off(self):
        watcher = SignOff()
        watcher.step(0, 0.1, True, False)
        watcher.step(8, 0.8, True, True)
        watcher.step(12, 0.1, False, False)
        self.assertEqual(watcher.step(20, 0.8, False, True), "arm")

    def test_patterns(self):
        self.assertEqual(pattern(0.1, True), "booth_over_quiet")
        self.assertEqual(pattern(0.9, True), "booth_over_song")
        self.assertEqual(pattern(0.9, False), "song_without_booth")


if __name__ == "__main__":
    unittest.main()
