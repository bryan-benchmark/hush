"""OHUSH_LIVE_V0 state machine. No audio, no experiment files."""

import unittest

from ohush_live.state import Machine


def reading(departure=None, strong_departure=False, ret=None, strong_return=False):
    return {
        "departure": departure,
        "strong_departure": strong_departure,
        "return": ret,
        "strong_return": strong_return,
    }


class StateTests(unittest.TestCase):
    def test_one_family_does_not_mute(self):
        machine = Machine()
        families = {
            "audio": reading(0.3, True),
            "speaker": reading(0.1, False),
            "semantic": None,
        }
        for t in range(1, 12):
            self.assertIsNone(machine.step(t, 1.0, families))
        self.assertEqual(machine.state, "PLAY")

    def test_two_families_mute_after_three_seconds(self):
        machine = Machine()
        families = {
            "audio": reading(0.22, True),
            "speaker": reading(0.4, True),
            "semantic": None,
        }
        self.assertIsNone(machine.step(1, 1.0, families))
        self.assertIsNone(machine.step(2, 1.0, families))
        event = machine.step(3, 1.0, families)
        self.assertEqual(event["state_after"], "MUTED")
        self.assertEqual(event["reason"], "2_of_strong")
        self.assertFalse(event["manual_override"])
        self.assertEqual(machine.state, "MUTED")

    def test_abstain_is_not_a_vote(self):
        machine = Machine()
        families = {
            "audio": reading(0.3, True),
            "speaker": None,
            "semantic": None,
        }
        for t in range(1, 8):
            self.assertIsNone(machine.step(t, 1.0, families))
        self.assertEqual(machine.state, "PLAY")

    def test_return_waits_and_needs_two_families(self):
        machine = Machine()
        mute = {
            "audio": reading(0.22, True),
            "speaker": reading(0.4, True),
            "semantic": None,
        }
        machine.step(1, 1.0, mute)
        machine.step(2, 1.0, mute)
        machine.step(3, 1.0, mute)
        one = {
            "audio": reading(0.05, False, 0.05, True),
            "speaker": reading(0.2, False, 0.0, False),
            "semantic": None,
        }
        for t in range(4, 20):
            self.assertIsNone(machine.step(t, 1.0, one))
        self.assertEqual(machine.state, "MUTED")
        both = {
            "audio": reading(0.05, False, 0.05, True),
            "speaker": reading(0.1, False, 0.4, True),
            "semantic": None,
        }
        self.assertIsNone(machine.step(11, 1.0, both))
        self.assertIsNone(machine.step(12, 1.0, both))
        self.assertIsNone(machine.step(13, 1.0, both))
        self.assertIsNone(machine.step(14, 1.0, both))
        event = machine.step(15, 1.0, both)
        self.assertIsNotNone(event)
        self.assertEqual(event["state_after"], "PLAY")

    def test_manual_play_is_immediate(self):
        machine = Machine()
        families = {
            "audio": reading(0.3, True),
            "speaker": reading(0.4, True),
            "semantic": None,
        }
        machine.step(1, 1.0, families)
        machine.step(2, 1.0, families)
        machine.step(3, 1.0, families)
        event = machine.manual(4, "play", families)
        self.assertEqual(event["state_before"], "MUTED")
        self.assertEqual(event["state_after"], "PLAY")
        self.assertTrue(event["manual_override"])
        self.assertEqual(machine.state, "PLAY")


if __name__ == "__main__":
    unittest.main()
