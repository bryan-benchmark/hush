"""A late cosine is not a match at the open, and a low cosine is not a name."""

from __future__ import annotations

import unittest

from experiments.nfl75.voice_fn import MATCH, classify_episode


def _window(start, end, **scores):
    return {"start": start, "end": end, "scores": scores}


class VoiceFnTests(unittest.TestCase):
    def test_line_stays_put(self):
        self.assertEqual(MATCH, 0.25)

    def test_a_match_in_the_opening_second_is_a_decision_failure(self):
        found = classify_episode(
            10.0,
            20.0,
            [_window(8.2, 10.0, **{"Al Michaels": 0.61, "Kirk Herbstreit": 0.11})],
            8.0,
        )
        self.assertEqual(found["kind"], "decision_ignored_match")
        self.assertFalse(found["identity_verified"])
        self.assertEqual(found["cited_name"], "Al Michaels")

    def test_a_match_after_the_open_is_late(self):
        found = classify_episode(
            9156.0,
            9169.0,
            [
                _window(9154.0, 9156.0, **{"Clarissa Thompson": 0.14, "Andrew Whitworth": 0.09}),
                _window(9160.0, 9162.0, **{"Andrew Whitworth": 0.70, "Al Michaels": 0.12}),
            ],
            10.0,
        )
        self.assertEqual(found["kind"], "delayed_recognition")
        self.assertEqual(found["available_at_s"], 9162.0)
        self.assertEqual(found["seconds_after_open"], 6.0)

    def test_speech_under_the_line_is_not_called_a_missing_detector(self):
        found = classify_episode(
            6266.0,
            6292.0,
            [_window(6266.0, 6268.0, **{"Andrew Whitworth": 0.18, "Tony Gonzalez": 0.08})],
            20.0,
        )
        self.assertEqual(found["kind"], "below_line")
        self.assertEqual(found["cited_cosine"], 0.18)

    def test_no_window_and_no_speech_is_the_detector(self):
        found = classify_episode(100.0, 104.0, [], 0.0)
        self.assertEqual(found["kind"], "no_speech_detected")

    def test_speech_with_no_window_is_not_blamed_on_silence(self):
        found = classify_episode(100.0, 110.0, [], 4.0)
        self.assertEqual(found["kind"], "speech_without_embedding_window")

    def test_a_score_that_finishes_after_the_mute_does_not_count(self):
        found = classify_episode(
            5574.0,
            5578.0,
            [_window(5577.5, 5579.5, **{"Clarissa Thompson": 0.47, "Andrew Whitworth": 0.08})],
            3.5,
        )
        self.assertEqual(found["kind"], "speech_without_embedding_window")
        self.assertIsNone(found["available_at_s"])

    def test_windows_with_no_scores_are_a_missing_reference(self):
        found = classify_episode(64.0, 73.0, [_window(64.5, 66.5, **{})], 6.8)
        self.assertEqual(found["kind"], "missing_reference")
