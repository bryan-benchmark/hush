"""The football ledger records events and does not mute."""

from __future__ import annotations

import unittest

from ohush_live.football_brain import FootballEngine, interpret
from ohush_live.football_llm import events_from_payload, ground_events


def _chunk(t0: float, text: str, process: float = 0.3, span: float = 5.0) -> dict:
    return {"t0": t0, "t1": t0 + span, "available_t": t0 + span + process, "text": text}


class InterpretTests(unittest.TestCase):
    def test_live_touchdown(self):
        self.assertEqual(interpret("Touchdown, Buffalo!")[0]["status"], "live")

    def test_hypothetical_stays_uncertain(self):
        row = interpret("That could've been a touchdown.")[0]
        self.assertEqual(row["kind"], "TOUCHDOWN")
        self.assertEqual(row["status"], "uncertain")

    def test_a_what_if_does_not_score(self):
        self.assertEqual(interpret("I'm worried if they score a touchdown.")[0]["status"], "uncertain")

    def test_a_stat_line_is_not_a_new_score(self):
        self.assertEqual(interpret("49 yards and a touchdown for Kailin.")[0]["status"], "uncertain")

    def test_replay_stays_uncertain(self):
        self.assertEqual(interpret("Let's look at that touchdown again.")[0]["status"], "uncertain")

    def test_timeouts_left_is_not_a_stoppage(self):
        self.assertEqual(interpret("They have three timeouts left."), [])

    def test_thirty_seconds_is_a_duration(self):
        row = interpret("We'll be back in 30 seconds.")[0]
        self.assertEqual(row["kind"], "BREAK_DURATION_ANNOUNCED")
        self.assertEqual(row["detail"], "30")

    def test_two_minute_warning_is_not_a_two_minute_mute(self):
        kinds = [row["kind"] for row in interpret("Here is the two-minute warning.")]
        self.assertEqual(kinds, ["TWO_MINUTE_WARNING"])


class LedgerTests(unittest.TestCase):
    def test_scoring_sequence_is_one_story(self):
        engine = FootballEngine()
        first, _ = engine.observe(_chunk(10, "Touchdown!"))
        second, _ = engine.observe(_chunk(22, "The extra point is good."))
        third, state = engine.observe(_chunk(30, "The score is 21 to 17."))
        self.assertEqual(first[0]["sequence"], "score-1")
        self.assertEqual(second[0]["sequence"], "score-1")
        self.assertEqual(third[0]["sequence"], "score-1")
        self.assertEqual(state["score_pair"], [21, 17])
        self.assertEqual(state["scoring_sequence_id"], "score-1")

    def test_overlapping_windows_do_not_duplicate(self):
        engine = FootballEngine()
        engine.observe(_chunk(10, "Touchdown!", span=5))
        emitted, _ = engine.observe(_chunk(12, "Touchdown, Buffalo!", span=5))
        self.assertEqual(emitted, [])
        self.assertEqual(engine.duplicates, 1)

    def test_a_repeated_touchdown_stays_in_the_same_sequence(self):
        engine = FootballEngine()
        engine.observe(_chunk(10, "Touchdown!"))
        emitted, state = engine.observe(_chunk(40, "Touchdown, Buffalo!"))
        self.assertEqual(emitted[0]["sequence"], "score-1")
        self.assertEqual(state["scoring_sequence_id"], "score-1")

    def test_a_later_touchdown_is_a_new_sequence(self):
        engine = FootballEngine()
        engine.observe(_chunk(10, "Touchdown!"))
        emitted, state = engine.observe(_chunk(110, "Touchdown!"))
        self.assertEqual(emitted[0]["sequence"], "score-2")
        self.assertEqual(state["scoring_sequence_id"], "score-2")

    def test_hypothetical_does_not_change_the_scorekeeper(self):
        engine = FootballEngine()
        emitted, state = engine.observe(_chunk(10, "That would have been a touchdown."))
        self.assertEqual(emitted[0]["status"], "uncertain")
        self.assertIsNone(state["scoring_sequence_id"])
        self.assertIsNone(state["score_pair"])
        self.assertIsNone(state["clock_seconds"])

    def test_clock_is_only_what_was_said(self):
        engine = FootballEngine()
        _, state = engine.observe(_chunk(10, "Timeout, 48 seconds left."))
        self.assertEqual(state["clock_seconds"], 48)
        self.assertEqual(state["last_stoppage"], "TIMEOUT")

    def test_a_transcript_cannot_arrive_early(self):
        engine = FootballEngine()
        with self.assertRaises(ValueError):
            engine.observe({"t0": 10, "t1": 15, "available_t": 9, "text": "Touchdown!"})

    def test_a_model_score_is_stored_when_both_numbers_were_said(self):
        events, facts = events_from_payload(
            "Texas the Cowboys on top 10 to 7.",
            {"quarter": None, "clock_seconds": None, "events": [{"kind": "SCORE_UPDATE", "status": "live", "score": [10, 7], "team": "Cowboys", "detail": "", "evidence": "Cowboys on top 10 to 7"}]},
        )
        self.assertEqual(events[0]["detail"], "10-7")
        self.assertEqual(events[0]["team"], "Cowboys")
        self.assertEqual(facts, {})

    def test_an_invented_score_is_dropped(self):
        events, _facts = events_from_payload(
            "Texas the Cowboys on top 10 to 7.",
            {"events": [{"kind": "SCORE_UPDATE", "status": "live", "score": [21, 14], "team": "Cowboys"}]},
        )
        self.assertEqual(events, [])

    def test_a_stat_line_touchdown_stays_uncertain(self):
        events = ground_events(
            "49 yards and a touchdown for Kailin.",
            [{"kind": "TOUCHDOWN", "status": "live", "detail": "", "evidence": "yards and a touchdown", "team": ""}],
        )
        self.assertEqual(events[0]["status"], "uncertain")

    def test_i_got_one_is_not_a_touchdown(self):
        events = ground_events(
            "I got one.",
            [{"kind": "TOUCHDOWN", "status": "live", "detail": "", "evidence": "I got one", "team": ""}],
        )
        self.assertEqual(events, [])

    def test_quarterback_is_not_the_end_of_the_quarter(self):
        events = ground_events(
            "a very mobile quarterback",
            [{"kind": "QUARTER_END", "status": "live", "detail": "", "evidence": "mobile quarterback", "team": ""}],
        )
        self.assertEqual(events, [])

    def test_end_of_the_debate_is_not_the_quarter(self):
        events = ground_events(
            "That's the end of the debate.",
            [{"kind": "QUARTER_END", "status": "live", "detail": "", "evidence": "end of the debate", "team": ""}],
        )
        self.assertEqual(events, [])

    def test_a_touchdown_without_a_quote_is_dropped(self):
        events = ground_events(
            "I got one.",
            [{"kind": "TOUCHDOWN", "status": "live", "detail": "", "evidence": "", "team": ""}],
        )
        self.assertEqual(events, [])

    def test_breaks_the_plane_can_be_a_touchdown(self):
        events = ground_events(
            "He breaks the plane. He's in.",
            [{"kind": "TOUCHDOWN", "status": "live", "detail": "", "evidence": "breaks the plane", "team": ""}],
        )
        self.assertEqual(events[0]["kind"], "TOUCHDOWN")

    def test_a_record_is_not_stored_as_the_score(self):
        events = ground_events(
            "you sit there at 0 and 5",
            [{"kind": "SCORE_UPDATE", "status": "live", "detail": "0-5", "evidence": "0 and 5", "team": ""}],
        )
        self.assertEqual(events, [])

    def test_timeouts_remaining_is_not_a_new_timeout(self):
        events = ground_events(
            "Dallas has two timeouts remaining",
            [{"kind": "TIMEOUT", "status": "live", "detail": "", "evidence": "two timeouts remaining", "team": "Dallas"}],
        )
        self.assertEqual(events, [])

    def test_the_ledger_keeps_a_model_score(self):
        class Reader:
            replaces_phrases = True
            facts = {"quarter": 2}

            def __call__(self, text, previous_text=""):
                del text, previous_text
                return [{"kind": "SCORE_UPDATE", "status": "live", "detail": "10-7", "team": "Cowboys"}]

        _events, state = FootballEngine(reader=Reader()).observe(_chunk(10, "Cowboys on top 10 to 7."))
        self.assertEqual(state["score_pair"], [10, 7])
        self.assertEqual(state["score_team"], "Cowboys")
        self.assertEqual(state["quarter"], 2)

    def test_two_engines_fed_the_same_chunks_agree(self):
        chunks = [_chunk(10, "Touchdown!"), _chunk(22, "The extra point is good.")]
        left, right = FootballEngine(), FootballEngine()
        self.assertEqual([left.observe(chunk)[0] for chunk in chunks], [right.observe(chunk)[0] for chunk in chunks])


if __name__ == "__main__":
    unittest.main()
