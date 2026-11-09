"""Event language and the watch. Gold is not an input."""

from __future__ import annotations

import unittest

from experiments.nfl75.events import covers_from_events, extract_events, watches_from_events


def _hot(n: int, value: float = 5.0):
    times = [float(index) for index in range(n)]
    return times, [value] * n, [value] * n


class ExtractTests(unittest.TestCase):
    def test_touchdown_is_live(self):
        rows = extract_events("And that's a touchdown!")
        self.assertEqual(rows[0]["kind"], "touchdown")
        self.assertEqual(rows[0]["status"], "live")

    def test_hypothetical_touchdown_does_not_go_live(self):
        rows = extract_events("That would have been a touchdown.")
        self.assertEqual(rows[0]["status"], "uncertain")

    def test_replay_does_not_go_live(self):
        rows = extract_events("Look at the replay of that touchdown.")
        self.assertEqual(rows[0]["status"], "uncertain")

    def test_two_minute_warning_is_not_a_duration(self):
        rows = extract_events("Here comes the two-minute warning.")
        kinds = {row["kind"]: row for row in rows}
        self.assertIn("two_minute_warning", kinds)
        self.assertNotIn("short_break", kinds)
        self.assertEqual(kinds["two_minute_warning"]["expectation"], "long")

    def test_thirty_seconds_is_a_short_break(self):
        rows = extract_events("We'll be back in 30 seconds.")
        self.assertEqual(rows[0]["kind"], "short_break")
        self.assertEqual(rows[0]["expectation"], "short")

    def test_handoff_survives_a_hypothetical_word_elsewhere(self):
        rows = extract_events("We'll be right back after these messages.")
        kinds = [row["kind"] for row in rows]
        self.assertIn("handoff", kinds)
        self.assertEqual(rows[0]["status"], "live")

    def test_timeouts_left_is_not_a_called_timeout(self):
        self.assertEqual(extract_events("They have three timeouts left."), [])

    def test_called_timeout_is_live(self):
        rows = extract_events("He takes a timeout with 48 seconds left.")
        self.assertEqual(rows[0]["kind"], "timeout")
        self.assertEqual(rows[0]["status"], "live")

    def test_end_of_the_third_quarter_is_a_quarter_end(self):
        rows = extract_events("That is the end of the third quarter.")
        self.assertEqual(rows[0]["kind"], "quarter_end")
        self.assertEqual(rows[0]["status"], "live")

    def test_repeated_chunk_is_ignored(self):
        self.assertEqual(extract_events("Touchdown!", "Touchdown!"), [])


class WatchTests(unittest.TestCase):
    def test_announcer_keeps_talking_and_the_watch_stays_open(self):
        times, scores, means = _hot(40)
        watches = [{"kind": "touchdown", "open_s": 10.0, "close_s": 100.0, "said_s": 5.0, "expectation": "long_after_sequence"}]
        booth = [float(index) for index in range(21)]
        covers, flags = covers_from_events(times, scores, means, booth, watches, start_line=0.163)
        self.assertTrue(flags[15])
        self.assertEqual(covers, [(21.0, 40.0)])

    def test_event_alone_does_not_mute_a_cold_score(self):
        times, scores, means = _hot(30, value=-2.0)
        watches = [{"kind": "timeout", "open_s": 5.0, "close_s": 50.0, "said_s": 1.0, "expectation": "unknown"}]
        covers, flags = covers_from_events(times, scores, means, [], watches, start_line=0.163)
        self.assertEqual(covers, [])
        self.assertTrue(flags[10])

    def test_booth_return_consumes_the_watch(self):
        times, scores, means = _hot(80)
        watches = [{"kind": "quarter_end", "open_s": 10.0, "close_s": 70.0, "said_s": 8.0, "expectation": "long"}]
        booth = [float(index) for index in range(15)] + [40.0]
        covers, _flags = covers_from_events(times, scores, means, booth, watches, start_line=0.163)
        self.assertEqual(covers, [(15.0, 40.0)])

    def test_a_score_dip_can_reopen_inside_the_same_watch(self):
        times, scores, means = _hot(40)
        for index in (25, 26, 27):
            scores[index] = -1.0
        watches = [{"kind": "handoff", "open_s": 10.0, "close_s": 50.0, "said_s": 9.0, "expectation": "imminent"}]
        covers, _flags = covers_from_events(times, scores, means, [], watches, start_line=0.163)
        self.assertEqual(covers, [(10.0, 27.0), (28.0, 40.0)])

    def test_horizon_comes_from_the_event_kind(self):
        events = [
            {"kind": "short_break", "status": "live", "available_t": 10.0, "t0": 5.0, "expectation": "short", "text": "back in 30 seconds"}
        ]
        rows = watches_from_events(events)
        self.assertEqual(rows[0]["close_s"], 30.0)


if __name__ == "__main__":
    unittest.main()
