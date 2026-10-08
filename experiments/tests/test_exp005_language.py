"""Exp005 phrase rules. The commercial ledger is not used."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from hush.language import (  # noqa: E402
    DEPARTURE_PHRASES,
    MATCH_SIMILARITY,
    RETURN_PHRASES,
    find_transitions,
    find_vocabulary,
    normalize_text,
    similarity,
)
from hush.semantic_text import MIN_REFERENCE_S, MIN_WORDS, anomaly_scores  # noqa: E402


def _words(pairs: list[tuple[str, float]]) -> list[dict]:
    return [{"text": text, "start": start, "end": start + 0.3} for text, start in pairs]


class Language(unittest.TestCase):
    def test_phrase_lists_are_the_ones_that_were_written_down(self):
        self.assertEqual(
            DEPARTURE_PHRASES,
            (
                "we'll be right back",
                "we'll be back",
                "stay with us",
                "coming up",
                "after the break",
                "after this",
                "timeout",
                "commercial break",
            ),
        )
        self.assertEqual(
            RETURN_PHRASES,
            (
                "welcome back",
                "we're back",
                "back here",
                "back to",
                "welcome back to",
                "let's get back to",
            ),
        )
        self.assertEqual(MATCH_SIMILARITY, 0.85)

    def test_contractions_and_the_longest_phrase_win(self):
        self.assertEqual(normalize_text("We'll be right back."), "we will be right back")
        hits = find_transitions(_words([
            ("We'll", 0.0),
            ("be", 0.4),
            ("right", 0.8),
            ("back", 1.2),
        ]))
        self.assertEqual([row["phrase"] for row in hits], ["we'll be right back"])
        hits = find_transitions(_words([
            ("welcome", 10.0),
            ("back", 10.4),
            ("to", 10.8),
            ("the", 11.2),
            ("game", 11.6),
        ]))
        self.assertEqual([row["phrase"] for row in hits], ["welcome back to"])

    def test_a_pause_breaks_the_phrase(self):
        hits = find_transitions(_words([
            ("we", 0.0),
            ("will", 0.4),
            ("be", 3.0),
            ("right", 3.4),
            ("back", 3.8),
        ]))
        self.assertEqual(hits, [])

    def test_vocabulary_is_exact_and_does_not_match_a_longer_word(self):
        hits = find_vocabulary(_words([
            ("freedom", 0.0),
            ("and", 1.0),
            ("ask", 2.0),
            ("your", 2.4),
            ("doctor", 2.8),
            ("today", 3.2),
        ]))
        self.assertEqual([row["phrase"] for row in hits], ["ask your doctor"])

    def test_one_character_off_can_match_a_transition_and_not_a_word_inside_another(self):
        self.assertGreaterEqual(similarity("timeouts", "timeout"), MATCH_SIMILARITY)
        hits = find_transitions(_words([("timeouts", 1.0)]))
        self.assertEqual(hits[0]["phrase"], "timeout")
        self.assertEqual(find_vocabulary(_words([("timeouts", 1.0)])), [])

    def test_future_text_does_not_change_an_earlier_semantic_score(self):
        self.assertEqual(MIN_WORDS, 8)
        ends = np.arange(15.0, 120.0, 1.0)
        starts = ends - 15.0
        present = np.ones(len(ends), dtype=bool)
        present[:5] = False
        embeddings = np.zeros((len(ends), 4))
        embeddings[:, 0] = 1.0
        first, _, _ = anomaly_scores(starts, ends, embeddings, present)
        embeddings = embeddings.copy()
        embeddings[-10:, :] = 0.0
        embeddings[-10:, 1] = 1.0
        second, _, _ = anomaly_scores(starts, ends, embeddings, present)
        defined = np.isfinite(first)
        self.assertTrue(np.any(defined))
        self.assertGreater(float(ends[np.flatnonzero(defined)[0]]), MIN_REFERENCE_S)
        shared = defined & np.isfinite(second)
        # The mutated tail can change a score only once it has entered that score's past.
        early = shared & (ends < 100.0)
        self.assertTrue(np.allclose(first[early], second[early]))
