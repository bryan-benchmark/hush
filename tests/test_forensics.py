"""Cause labels for the frozen mean. No tape is required."""

from __future__ import annotations

import unittest

from experiments.nfl75.forensics import assign_cause


class CauseTests(unittest.TestCase):
    def test_a_match_at_the_open_is_a_decision_failure_when_the_mean_ignores_it(self):
        cause = assign_cause(
            {
                "kind": "false_mute",
                "overlay": None,
                "category": "announcer_commentary",
                "fresh": 0.61,
                "fresh_name": "Al Michaels",
                "max_in_episode": 0.61,
                "max_prior_5": 0.61,
                "speech_windows_in_episode": 4,
                "policy_reads_speaker": False,
                "listen_is_opening_only": False,
            }
        )
        self.assertEqual(cause["primary"], "recognized_enrolled_voice_still_muted")
        self.assertEqual(cause["priority"], 1)
        self.assertIn("speaker_not_an_input", cause["contributing"])

    def test_a_match_five_seconds_earlier_is_not_called_a_model_miss(self):
        cause = assign_cause(
            {
                "kind": "false_mute",
                "overlay": None,
                "category": "announcer_commentary",
                "fresh": None,
                "fresh_name": None,
                "max_in_episode": 0.11,
                "max_prior_5": 0.42,
                "speech_windows_in_episode": 2,
                "policy_reads_speaker": False,
                "listen_is_opening_only": False,
            }
        )
        self.assertEqual(cause["primary"], "recognition_not_fresh_at_open")
        self.assertEqual(cause["priority"], 1)

    def test_speech_with_a_weak_cosine_is_an_enrollment_or_model_miss(self):
        cause = assign_cause(
            {
                "kind": "false_mute",
                "overlay": None,
                "category": "announcer_commentary",
                "fresh": 0.08,
                "fresh_name": "Kirk Herbstreit",
                "max_in_episode": 0.08,
                "max_prior_5": 0.09,
                "speech_windows_in_episode": 3,
                "policy_reads_speaker": False,
                "listen_is_opening_only": True,
            }
        )
        self.assertEqual(cause["primary"], "enrolled_voice_not_matched")
        self.assertEqual(cause["priority"], 2)

    def test_a_promotional_read_stays_last_even_when_the_voice_matches(self):
        cause = assign_cause(
            {
                "kind": "false_mute",
                "overlay": "promotional_read",
                "category": "promo_sponsor",
                "fresh": 0.7,
                "fresh_name": "Al Michaels",
                "max_in_episode": 0.7,
                "max_prior_5": 0.7,
                "speech_windows_in_episode": 8,
                "policy_reads_speaker": False,
                "listen_is_opening_only": True,
            }
        )
        self.assertEqual(cause["primary"], "promotional_tradeoff")
        self.assertEqual(cause["priority"], 6)

    def test_a_late_return_is_not_labeled_as_a_missed_voice(self):
        cause = assign_cause({"kind": "late_return", "score_stayed_hot": True})
        self.assertEqual(cause["primary"], "late_return")
        self.assertEqual(cause["priority"], 5)


if __name__ == "__main__":
    unittest.main()
