"""OHUSH_LIVE_V0 state machine. No audio, no experiment files.

Spec (audit 2026-10-08): knowing booth identities ≠ believing they are talking.
Protect verified booth speech + bounded outro hold only.
"""

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
    def test_one_family_yes_one_no_does_not_mute(self):
        machine = Machine()
        families = {
            "audio": reading(0.3, True),
            "speaker": reading(0.1, False),
            "semantic": None,
        }
        # Non-booth speaker with no strong_departure is ignored for depart.
        for t in range(1, 4):
            self.assertIsNone(machine.step(t, 1.0, families))
        event = machine.step(4, 1.0, families)
        self.assertEqual(event["state_after"], "MUTED")
        self.assertEqual(event["reason"], "solo_audio_depart")

    def test_enrolled_show_over_0_10_blocks_solo_audio_and_returns(self):
        machine = Machine()
        speaker = reading(0.0, False)
        speaker["speech"] = True
        speaker["enroll_rolling_max"] = 0.12
        families = {"audio": reading(0.3, True), "speaker": speaker, "semantic": None}
        for t in range(1, 6):
            self.assertIsNone(machine.step(t, 1.0, families))
        self.assertEqual(machine.state, "PLAY")
        machine.state = "MUTED"
        machine._muted_at = 0.0
        event = machine.step(10, 1.0, families)
        self.assertEqual(event["state_after"], "PLAY")
        self.assertEqual(event["reason"], "show_floor")
        speaker["enroll_rolling_max"] = 0.05
        fresh = Machine()
        event = None
        for t in range(1, 5):
            event = fresh.step(t, 1.0, families)
        self.assertEqual(event["state_after"], "MUTED")

    def test_two_families_mute_after_persist(self):
        machine = Machine()
        families = {
            "audio": reading(0.25, True),
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

    def test_solo_audio_mutes_when_others_unavailable(self):
        """Ad2-class: audio strong, speaker/semantic null → product may cover."""
        machine = Machine()
        families = {
            "audio": reading(0.3, True),
            "speaker": None,
            "semantic": None,
        }
        for t in range(1, 4):
            self.assertIsNone(machine.step(t, 1.0, families))
        event = machine.step(4, 1.0, families)
        self.assertIsNotNone(event)
        self.assertEqual(event["state_after"], "MUTED")
        self.assertEqual(event["reason"], "solo_audio_depart")

    def test_solo_audio_uses_score_even_if_flag_false(self):
        """Audio score at/above AUDIO_STRONG mutes even when the worker flag lags."""
        machine = Machine()
        families = {
            "audio": reading(0.23, False),
            "speaker": None,
            "semantic": None,
        }
        for t in range(1, 4):
            self.assertIsNone(machine.step(t, 1.0, families))
        event = machine.step(4, 1.0, families)
        self.assertIsNotNone(event)
        self.assertEqual(event["state_after"], "MUTED")

    def test_higher_cover_line_ignores_a_mild_score(self):
        """A chosen 0.30 line must not cover just because the worker flag is on."""
        machine = Machine()
        machine.audio_strong = 0.30
        families = {
            "audio": reading(0.23, True),
            "speaker": None,
            "semantic": None,
        }
        for t in range(1, 8):
            self.assertIsNone(machine.step(t, 1.0, families))
        self.assertEqual(machine.state, "PLAY")

    def test_booth_talking_blocks_solo_audio_mute(self):
        """Verified announcer speaking — do not cover on audio alone."""
        machine = Machine()
        families = {
            "audio": reading(0.3, True),
            "speaker": {
                "departure": 0.02,
                "strong_departure": False,
                "return": 0.0,
                "strong_return": False,
                "speech": True,
                "recurring": True,
                "booth_present": True,
                "similarity_to_booth": 0.8,
                "cluster_id": "c0001",
                "continuity": 0.3,
            },
            "semantic": None,
        }
        for t in range(1, 12):
            self.assertIsNone(machine.step(t, 1.0, families))
        self.assertEqual(machine.state, "PLAY")

    def test_booth_locked_alone_does_not_block_solo_audio_mute(self):
        """Remembered announcer IDs must never veto commercial detection."""
        machine = Machine()
        families = {
            "audio": reading(0.3, True),
            "speaker": {
                "departure": None,
                "strong_departure": False,
                "return": 0.0,
                "strong_return": False,
                "speech": False,
                "recurring": False,
                "booth_present": False,
                "booth_locked": True,
                "continuity": None,
            },
            "semantic": None,
        }
        for t in range(1, 4):
            self.assertIsNone(machine.step(t, 1.0, families))
        event = machine.step(4, 1.0, families)
        self.assertIsNotNone(event)
        self.assertEqual(event["state_after"], "MUTED")
        self.assertEqual(event["reason"], "solo_audio_depart")

    def test_empty_placeholder_families_do_not_block_solo_audio(self):
        machine = Machine()
        empty = reading(None, False, None, False)
        families = {
            "audio": reading(0.3, True),
            "speaker": empty,
            "semantic": empty,
        }
        for t in range(1, 4):
            self.assertIsNone(machine.step(t, 1.0, families))
        event = machine.step(4, 1.0, families)
        self.assertEqual(event["state_after"], "MUTED")
        self.assertEqual(event["reason"], "solo_audio_depart")

    def test_solo_speaker_does_not_mute(self):
        machine = Machine()
        families = {
            "audio": None,
            "speaker": reading(0.5, True),
            "semantic": None,
        }
        for t in range(1, 12):
            self.assertIsNone(machine.step(t, 1.0, families))
        self.assertEqual(machine.state, "PLAY")

    def test_unrecognized_speaker_does_not_block_audio_return(self):
        """A voice that is not the enrolled booth cannot veto a restore.

        College football, 17 October, t=83–89: audio strong_return was already
        true while Herbstreit (cluster c0005, similarity about 0) was still
        talking. He counted as a second family and the unmute never fired.
        """
        machine = Machine()
        mute = {
            "audio": reading(0.35, True),
            "speaker": None,
            "semantic": None,
        }
        for t in range(1, 5):
            machine.step(t, 1.0, mute)
        self.assertEqual(machine.state, "MUTED")
        herbstreit = {
            "audio": reading(0.02, False, 0.02, True),
            "speaker": {
                "departure": 0.0,
                "strong_departure": False,
                "return": 0.0,
                "strong_return": False,
                "speech": True,
                "booth_present": False,
                "similarity_to_booth": -0.03,
                "cluster_id": "c0005",
            },
            "semantic": None,
        }
        # muted_at=4, hold 6s → open at t=10; solo play persist 3s → t=12.
        for t in range(5, 12):
            self.assertIsNone(machine.step(t, 1.0, herbstreit))
        event = machine.step(12, 1.0, herbstreit)
        self.assertIsNotNone(event)
        self.assertEqual(event["state_after"], "PLAY")
        self.assertEqual(event["reason"], "solo_audio_return")

    def test_speaker_return_still_lifts_cover(self):
        machine = Machine()
        mute = {
            "audio": reading(0.25, True),
            "speaker": reading(0.4, True),
            "semantic": None,
        }
        machine.step(1, 1.0, mute)
        machine.step(2, 1.0, mute)
        machine.step(3, 1.0, mute)
        self.assertEqual(machine.state, "MUTED")
        both = {
            "audio": reading(0.05, False, 0.05, True),
            "speaker": reading(0.1, False, 0.4, True),
            "semantic": None,
        }
        for t in range(4, 9):
            self.assertIsNone(machine.step(t, 1.0, both))
        event = machine.step(9, 1.0, both)
        self.assertIsNotNone(event)
        self.assertEqual(event["state_after"], "PLAY")
        self.assertEqual(event["reason"], "speaker_return")

    def test_solo_audio_return_after_hold(self):
        machine = Machine()
        mute = {
            "audio": reading(0.3, True),
            "speaker": None,
            "semantic": None,
        }
        for t in range(1, 5):
            machine.step(t, 1.0, mute)
        self.assertEqual(machine.state, "MUTED")
        back = {
            "audio": reading(0.05, False, 0.05, True),
            "speaker": None,
            "semantic": None,
        }
        # muted_at=4, hold 6s → open at t=10; solo play persist 3s → t=12.
        for t in range(5, 12):
            self.assertIsNone(machine.step(t, 1.0, back))
        event = machine.step(12, 1.0, back)
        self.assertIsNotNone(event)
        self.assertEqual(event["state_after"], "PLAY")
        self.assertEqual(event["reason"], "solo_audio_return")

    def test_al_michaels_booth_voice_returns_immediately(self):
        """Verified booth (Al) always lifts cover — even during mute hold."""
        machine = Machine()
        mute = {
            "audio": reading(0.3, True),
            "speaker": None,
            "semantic": None,
        }
        for t in range(1, 5):
            machine.step(t, 1.0, mute)
        self.assertEqual(machine.state, "MUTED")
        voice = {
            "audio": reading(0.25, True, 0.25, False),
            "speaker": {
                "departure": 0.05,
                "strong_departure": False,
                "return": 0.0,
                "strong_return": False,
                "speech": True,
                "recurring": False,
                "booth_present": True,
                "similarity_to_booth": 0.81,
                "cluster_id": "c0001",
            },
            "semantic": None,
        }
        event = machine.step(5, 1.0, voice)
        self.assertIsNotNone(event)
        self.assertEqual(event["state_after"], "PLAY")
        self.assertEqual(event["reason"], "booth_voice")

    def test_verified_similarity_returns(self):
        """Prototype match at SPEAKER_BOOTH_MATCH lifts cover."""
        machine = Machine()
        mute = {
            "audio": reading(0.3, True),
            "speaker": None,
            "semantic": None,
        }
        for t in range(1, 5):
            machine.step(t, 1.0, mute)
        self.assertEqual(machine.state, "MUTED")
        voice = {
            "audio": reading(0.25, True, 0.25, False),
            "speaker": {
                "departure": 0.05,
                "strong_departure": False,
                "return": 0.0,
                "strong_return": False,
                "speech": True,
                "recurring": False,
                "booth_present": False,
                "booth_locked": True,
                "similarity_to_booth": 0.72,
                "cluster_id": "c0099",
            },
            "semantic": None,
        }
        event = machine.step(5, 1.0, voice)
        self.assertIsNotNone(event)
        self.assertEqual(event["state_after"], "PLAY")
        self.assertEqual(event["reason"], "booth_voice")

    def test_generic_continuity_does_not_return_as_booth(self):
        """Audit repro: continuity 0.14 + recurring must NOT un-mute into an ad."""
        machine = Machine()
        mute = {
            "audio": reading(0.3, True),
            "speaker": None,
            "semantic": None,
        }
        for t in range(1, 5):
            machine.step(t, 1.0, mute)
        self.assertEqual(machine.state, "MUTED")
        fake = {
            "audio": reading(0.30, True, 0.30, False),
            "speaker": {
                "departure": 0.05,
                "strong_departure": False,
                "return": 0.0,
                "strong_return": False,
                "speech": True,
                "recurring": True,
                "booth_present": False,
                "booth_locked": True,
                "continuity": 0.14,
                "similarity_to_booth": 0.10,
                "cluster_id": "c0099",
            },
            "semantic": None,
        }
        for t in range(5, 20):
            self.assertIsNone(machine.step(t, 1.0, fake))
        self.assertEqual(machine.state, "MUTED")

    def test_al_outro_hold_blocks_mute_through_bumper_gap(self):
        """Bounded booth_present linger (no speech) through outro handoff."""
        machine = Machine()
        families = {
            "audio": reading(0.3, True),
            "speaker": {
                "departure": None,
                "strong_departure": False,
                "return": None,
                "strong_return": False,
                "speech": False,
                "recurring": False,
                "booth_present": True,
                "booth_locked": True,
                "continuity": None,
            },
            "semantic": None,
        }
        for t in range(1, 14):
            self.assertIsNone(machine.step(t, 1.0, families))
        self.assertEqual(machine.state, "PLAY")

    def test_low_similarity_flag_does_not_uncover_or_veto(self):
        """run29 t≈221 shape: booth_present true, similarity 0.15, foreign cluster."""
        machine = Machine()
        machine.manual(0.0, "mute", {"audio": None, "speaker": None, "semantic": None})
        bad = {
            "audio": reading(0.234, True, 0.234, False),
            "speaker": {
                "departure": 0.0,
                "strong_departure": False,
                "return": 0.0,
                "strong_return": False,
                "speech": True,
                "recurring": False,
                "booth_present": True,
                "booth_locked": True,
                "booth_ids": ["c0001", "c0002", "c0004", "c0005"],
                "similarity_to_booth": 0.148,
                "cluster_id": "c0013",
            },
            "semantic": None,
        }
        for t in range(1, 8):
            self.assertIsNone(machine.step(float(t), 1.0, bad))
        self.assertEqual(machine.state, "MUTED")
        fresh = Machine()
        for t in range(1, 4):
            self.assertIsNone(fresh.step(float(t), 1.0, bad))
        event = fresh.step(4.0, 1.0, bad)
        self.assertEqual(event["state_after"], "MUTED")
        self.assertEqual(event["reason"], "solo_audio_depart")

    def test_human_cover_holds_through_one_verified_booth_tick(self):
        machine = Machine()
        machine.manual(0.0, "mute", {"audio": None, "speaker": None, "semantic": None})
        voice = {
            "audio": reading(0.318, True, 0.318, False),
            "speaker": {
                "departure": 0.05,
                "strong_departure": False,
                "return": 1.0,
                "strong_return": True,
                "speech": True,
                "recurring": True,
                "booth_present": True,
                "similarity_to_booth": 0.705,
                "cluster_id": "c0010",
                "booth_ids": ["c0001", "c0002", "c0003", "c0004"],
            },
            "semantic": None,
        }
        self.assertIsNone(machine.step(1.0, 1.0, voice))
        self.assertIsNone(machine.step(2.0, 1.0, voice))
        self.assertEqual(machine.state, "MUTED")
        event = machine.step(3.0, 1.0, voice)
        self.assertIsNotNone(event)
        self.assertEqual(event["reason"], "booth_voice")
        self.assertEqual(machine.state, "PLAY")

    def test_trusted_cluster_without_similarity_still_returns_on_auto_cover(self):
        """Explicit remaining trust: no similarity field, cluster listed in booth_ids."""
        machine = Machine()
        mute = {
            "audio": reading(0.3, True),
            "speaker": None,
            "semantic": None,
        }
        for t in range(1, 5):
            machine.step(t, 1.0, mute)
        self.assertEqual(machine.state, "MUTED")
        voice = {
            "audio": reading(0.25, True, 0.25, False),
            "speaker": {
                "departure": 0.05,
                "strong_departure": False,
                "return": 0.0,
                "strong_return": False,
                "speech": True,
                "booth_present": True,
                "cluster_id": "c0001",
                "booth_ids": ["c0001", "c0002"],
            },
            "semantic": None,
        }
        event = machine.step(5, 1.0, voice)
        self.assertIsNotNone(event)
        self.assertEqual(event["reason"], "booth_voice")

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
