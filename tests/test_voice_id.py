"""A labeled clip is named only from other clips, and only at the frozen line."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from experiments.nfl75.voice_id import (
    DURATIONS,
    enrollment_rows,
    identify,
    outcome,
    probe_bucket,
)
from hush.speaker_memory import MATCH_COSINE


def _clip(clip_id, session, who, condition):
    return {"id": clip_id, "session": session, "who": who, "condition": condition}


class VoiceIdTests(unittest.TestCase):
    def test_the_line_stays_at_one_quarter(self):
        self.assertEqual(MATCH_COSINE, 0.25)
        self.assertEqual(DURATIONS, (1.0, 2.0, 3.0))
        named = identify({"Al Michaels": 0.25, "Kirk Herbstreit": 0.24})
        withheld = identify({"Al Michaels": 0.249, "Kirk Herbstreit": 0.1})
        self.assertEqual(named["accepted"], "Al Michaels")
        self.assertIsNone(withheld["accepted"])
        self.assertEqual(withheld["rank1"], "Al Michaels")

    def test_cross_tape_enrollment_excludes_the_probe_game_and_songs_when_clean(self):
        rows = [
            _clip("a", "hush_20260924_220624", "Al Michaels", "clear"),
            _clip("b", "hush_20260924_220624", "Al Michaels", "song"),
            _clip("c", "hush_20261008_205100", "Al Michaels", "clear"),
            _clip("d", "hush_20260909_213047", "Mike Tirico", "clear"),
        ]
        clean = enrollment_rows(
            rows, "hush_20261008_205100", cross_tape=True, clean=True, exclude_ids=set()
        )
        published = enrollment_rows(
            rows, "hush_20261008_205100", cross_tape=True, clean=False, exclude_ids=set()
        )
        self.assertEqual([row["id"] for row in clean], ["a"])
        self.assertEqual([row["id"] for row in published], ["a", "b"])

    def test_same_game_enrollment_leaves_the_probe_out(self):
        rows = [
            _clip("a", "hush_20260924_220624", "Al Michaels", "clear"),
            _clip("b", "hush_20260924_220624", "Kirk Herbstreit", "clear"),
        ]
        chosen = enrollment_rows(
            rows, "hush_20260924_220624", cross_tape=False, clean=True, exclude_ids={"a"}
        )
        self.assertEqual([row["id"] for row in chosen], ["b"])

    def test_a_song_is_not_a_correct_identification_trial(self):
        song = _clip("s", "hush_20261008_205100", "Clarissa Thompson", "song")
        self.assertEqual(probe_bucket(song, {"Clarissa Thompson"}), "song")
        self.assertEqual(outcome("Clarissa Thompson", "Clarissa Thompson", "Clarissa Thompson", "song"), "not_scored")

    def test_an_unenrolled_voice_that_is_named_anyway_is_a_false_match(self):
        self.assertEqual(outcome("Ryan Fitzpatrick", "Al Michaels", "Al Michaels", "not_enrolled"), "false_match")
        self.assertEqual(outcome("Ryan Fitzpatrick", None, "Al Michaels", "not_enrolled"), "rejected")
        self.assertEqual(outcome("Mike Tirico", "Al Michaels", "Al Michaels", "other_show"), "false_match")
        self.assertEqual(outcome("Al Michaels", None, "Al Michaels", "clear"), "missed")
        self.assertEqual(outcome("Al Michaels", "Kirk Herbstreit", "Kirk Herbstreit", "clear"), "wrong_person")
        self.assertEqual(outcome("Al Michaels", "Al Michaels", "Al Michaels", "clear"), "correct")
