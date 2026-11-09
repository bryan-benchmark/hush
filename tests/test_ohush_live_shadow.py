"""Shadow watches the live machine and leaves the speakers alone."""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

from ohush_live.gate import ListenerGate
from ohush_live.shadow import Shadow, receipt
from ohush_live.sports_daemon import SportsSession


def hot_audio():
    return {"strong_departure": True, "departure": 0.4, "strong_return": False, "return": 0.0}


class ShadowTests(unittest.TestCase):
    def test_a_would_cover_is_not_applied(self):
        shadow = Shadow()
        families = {"audio": hot_audio(), "speaker": None, "semantic": None}
        event = None
        for t in range(1, 5):
            event = shadow.observe(t, families) or event
        self.assertEqual(event["would"], "cover")
        self.assertFalse(event["applied"])
        self.assertEqual(event["reason"], "solo_audio_depart")
        self.assertEqual(shadow.machine.state, "MUTED")

    def test_the_show_floor_blocks_a_would_cover(self):
        shadow = Shadow()
        speaker = hot_audio()
        speaker["speech"] = True
        speaker["enroll_rolling_max"] = 0.12
        families = {"audio": hot_audio(), "speaker": speaker, "semantic": None}
        for t in range(1, 8):
            self.assertIsNone(shadow.observe(t, families))
        self.assertEqual(shadow.machine.state, "PLAY")
        self.assertIsNone(shadow.pending)

    def test_receipt_counts_would_cover_seconds_and_refuses_an_applied_row(self):
        rows = [
            {"event": "shadow", "would": "cover", "applied": False, "t": 10.0},
            {"event": "shadow_answer", "verdict": "reject", "applied": False, "t": 11.0},
            {"event": "shadow", "would": "return", "applied": False, "t": 40.0},
        ]
        counted = receipt(rows)
        self.assertEqual(counted["would_cover_s"], 30.0)
        self.assertEqual(counted["rejects"], 1)
        self.assertEqual(counted["applied"], 0)
        with self.assertRaises(ValueError):
            receipt([{"event": "shadow", "would": "cover", "applied": True, "t": 1.0}])

    def test_the_desk_logs_a_would_cover_and_the_television_stays_on(self):
        rate = 48000
        beds = {
            "wednesday_night": np.full((rate, 2), 16000, dtype=np.int16),
            "silence": np.zeros((rate, 2), dtype=np.int16),
        }
        gate = ListenerGate(beds, np.zeros((100, 2), dtype=np.int16), prime_frames=2048, rate=rate)
        gate.auto = False
        gate.mode = "program"
        with TemporaryDirectory() as folder:
            session = SportsSession(Path(folder))
            try:
                session.families = {"speaker": None, "audio": hot_audio(), "semantic": None}
                for _ in range(4):
                    session.samples += rate
                    session.tick(gate)
                self.assertEqual(gate.mode, "program")
                self.assertEqual(session.shadow.machine.state, "MUTED")
                session.human(gate, "shadow_reject")
                self.assertEqual(gate.mode, "program")
                text = Path(folder, "shadow.jsonl").read_text(encoding="utf-8")
                rows = [json.loads(line) for line in text.splitlines() if line.strip()]
                self.assertTrue(any(row["event"] == "shadow" and row["would"] == "cover" and row["applied"] is False for row in rows))
                self.assertTrue(any(row["event"] == "shadow_answer" and row["verdict"] == "reject" for row in rows))
            finally:
                session.close()

    def test_silence_with_auto_off_stays_on_the_program(self):
        rate = 48000
        beds = {
            "wednesday_night": np.full((rate, 2), 16000, dtype=np.int16),
            "silence": np.zeros((rate, 2), dtype=np.int16),
        }
        gate = ListenerGate(beds, np.zeros((100, 2), dtype=np.int16), prime_frames=32, rate=rate)
        gate.auto = False
        quiet = {"strong_departure": False, "departure": 0.0, "strong_return": False, "return": 0.0}
        tone = np.zeros((80, 2), dtype=np.int16)
        gate.push(tone)
        out = np.zeros((32, 2), dtype=np.int16)
        gate.render(out)
        self.assertTrue(np.all(out == 0))
        with TemporaryDirectory() as folder:
            session = SportsSession(Path(folder))
            try:
                session.families = {"speaker": quiet, "audio": quiet, "semantic": None}
                for _ in range(6):
                    session.samples += rate
                    session.tick(gate)
                self.assertEqual(gate.mode, "program")
                self.assertEqual(session.shadow.pending, None)
            finally:
                session.close()


if __name__ == "__main__":
    unittest.main()
