"""Corrections stay reports. A missing speaker does not start an automatic cover."""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

from ohush_live.gate import ListenerGate
from ohush_live.session_report import build_report, correction_row
from ohush_live.sports_daemon import SportsSession


def hot():
    return {"strong_departure": True, "departure": 0.4, "strong_return": False, "return": 0.2}


def gate():
    rate = 48000
    beds = {
        "wednesday_night": np.full((rate, 2), 16000, dtype=np.int16),
        "silence": np.zeros((rate, 2), dtype=np.int16),
    }
    made = ListenerGate(beds, np.zeros((100, 2), dtype=np.int16), prime_frames=2048, rate=rate)
    made.auto = True
    made.mode = "program"
    return made, rate


class CorrectionTests(unittest.TestCase):
    def test_a_boundary_mark_stamps_the_recording_clock_and_leaves_the_speakers(self):
        made, rate = gate()
        with TemporaryDirectory() as folder:
            session = SportsSession(Path(folder))
            try:
                session.samples = rate * 90
                session.label(made, "commercial", "left the game", None)
                session.label(made, "program", "show is back", None)
                self.assertEqual(made.mode, "program")
                rows = [json.loads(line) for line in Path(folder, "labels.jsonl").read_text(encoding="utf-8").splitlines()]
                self.assertEqual([row["verdict"] for row in rows], ["commercial", "program"])
                self.assertEqual([row["t"] for row in rows], [90.0, 90.0])
                self.assertEqual(rows[0]["note"], "left the game")
                self.assertFalse(rows[0]["scientific_authority"])
                self.assertEqual(rows[0]["dataset_role"], "live_dev")
                self.assertEqual(session.snapshot(made)["last_label"]["verdict"], "program")
                self.assertFalse(session.snapshot(made)["last_label"]["scientific_authority"])
            finally:
                session.close()

    def test_a_missed_ad_is_not_a_label_and_does_not_change_the_speakers(self):
        made, rate = gate()
        with TemporaryDirectory() as folder:
            session = SportsSession(Path(folder))
            try:
                session.samples = rate * 40
                session.live["open_chunk"] = "audio_0001.wav"
                session.families = {"speaker": hot(), "audio": hot(), "semantic": None}
                session.human(made, "missed_ad")
                self.assertEqual(made.mode, "program")
                rows = [json.loads(line) for line in Path(folder, "corrections.jsonl").read_text(encoding="utf-8").splitlines()]
                self.assertEqual(rows[0]["kind"], "missed_ad")
                self.assertFalse(rows[0]["ground_truth"])
                self.assertEqual(rows[0]["audio_ref"]["t0"], 25.0)
                self.assertEqual(rows[0]["audio_ref"]["t1"], 50.0)
                self.assertEqual(rows[0]["audio_ref"]["chunk"], "audio_0001.wav")
            finally:
                session.close()

    def test_show_the_game_does_not_cover_the_same_break_again(self):
        made, rate = gate()
        with TemporaryDirectory() as folder:
            session = SportsSession(Path(folder))
            try:
                session.families = {"speaker": hot(), "audio": hot(), "semantic": None}
                for _ in range(3):
                    session.samples += rate
                    session.tick(made)
                self.assertEqual(session.machine.state, "MUTED")
                session.human(made, "play")
                for _ in range(4):
                    session.samples += rate
                    session.tick(made)
                self.assertEqual(session.machine.state, "PLAY")
                self.assertTrue(made._pending_program or made.mode == "program")
                self.assertFalse(made.mode == "replacement" and not made._pending_program)
            finally:
                session.close()

    def test_a_missing_speaker_does_not_start_an_automatic_cover(self):
        made, rate = gate()
        with TemporaryDirectory() as folder:
            session = SportsSession(Path(folder))
            try:
                session.families = {"speaker": None, "audio": hot(), "semantic": None}
                for _ in range(6):
                    session.samples += rate
                    session.tick(made)
                self.assertEqual(made.mode, "program")
                self.assertFalse(made._pending_program)
                session.decision_mode = "audio_only"
                for _ in range(4):
                    session.samples += rate
                    session.tick(made)
                self.assertEqual(session.machine.state, "MUTED")
            finally:
                session.close()

    def test_the_report_counts_reports_and_refuses_to_call_them_labels(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "session.json").write_text(
                json.dumps({"show": "Panthers at Packers", "service": "Prime", "broadcast": "live", "gaps": []}),
                encoding="utf-8",
            )
            (root / "corrections.jsonl").write_text(
                json.dumps(correction_row(
                    12.0,
                    "muted_show",
                    hearing="REPLACEMENT",
                    auto=True,
                    decision_mode="two_family",
                    families={},
                    shadow=None,
                    lag_ms=40.0,
                    chunk="audio_0002.wav",
                    machine="MUTED",
                    speaker_ready=True,
                    departure_votes=2,
                ))
                + "\n",
                encoding="utf-8",
            )
            (root / "decisions.jsonl").write_text(
                json.dumps({"t": 12.0, "state": "REPLACEMENT_TO_PROGRAM", "decision_source": "human", "noop": False}) + "\n",
                encoding="utf-8",
            )
            report = build_report(root)
            self.assertEqual(report["muted_show"], 1)
            self.assertEqual(report["manual_returns"], 1)
            self.assertFalse(report["ground_truth"])
            self.assertEqual(report["show"], "Panthers at Packers")


if __name__ == "__main__":
    unittest.main()
