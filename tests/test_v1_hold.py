"""The published fingerprint hold lets go when the song drops. No audio."""

import unittest

from experiments.measurement.v1_hold_001 import hold_until_quiet


class HoldTests(unittest.TestCase):
    def test_a_drop_inside_the_ad_adds_seconds_and_leaves_the_game(self):
        steps = [
            {"t": 150, "music": 0.9},
            {"t": 170, "music": 0.9},
            {"t": 196, "music": 0.07},
        ]
        result = hold_until_quiet(steps, 150.0, 376.9)
        self.assertFalse(result["broken"])
        self.assertEqual(result["program_s"], 0.0)
        self.assertEqual(result["commercial_s"], 46.0)

    def test_a_drop_after_the_game_is_back_is_broken(self):
        steps = [{"t": 400, "music": 0.1}]
        result = hold_until_quiet(steps, 150.0, 376.9)
        self.assertTrue(result["broken"])
        self.assertGreater(result["program_s"], 0)


if __name__ == "__main__":
    unittest.main()
