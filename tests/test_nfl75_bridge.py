"""Replay and live shadow call the same bridge. The gate stays off unless a test turns it on."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

from ohush_live.bridge import BRIDGE, carry_out, live_shadow, replay
from ohush_live.gate import ListenerGate
from ohush_live.shadow import Shadow


def _audio(departure: float) -> dict:
    return {
        "departure": departure,
        "strong_departure": departure >= 0.22,
        "return": 0.0,
        "strong_return": departure <= 0.12,
    }


def _row(
    t: float,
    departure: float,
    *,
    end: float | None = None,
    available: float | None = None,
    raw: dict | None | str = "auto",
) -> dict:
    end = t if end is None else end
    available = t if available is None else available
    body = _audio(departure) if raw == "auto" else raw
    return {
        "audio_time": t,
        "readings": [
            {"family": "audio", "raw": body, "audio_end_s": end, "available_at_s": available},
            {"family": "speaker", "raw": None, "audio_end_s": None, "available_at_s": None},
            {"family": "semantic", "raw": None, "audio_end_s": None, "available_at_s": None},
        ],
    }


def _game_break_game() -> list[dict]:
    rows = [_row(t, 0.05) for t in range(0, 60)]
    rows.extend(_row(t, 0.40) for t in range(60, 180))
    rows.extend(_row(t, 0.05) for t in range(180, 241))
    return rows


def _actions(decisions: list[dict]) -> list[tuple[float, str, str]]:
    return [
        (row["audio_time"], row["action"], row["reason"])
        for row in decisions
        if row["action"] != "NO_CHANGE"
    ]


class ParityTests(unittest.TestCase):
    def test_replay_and_live_shadow_match_on_a_break(self):
        rows = _game_break_game()
        offline = replay(rows)
        live = live_shadow(rows)
        self.assertEqual(offline, live)
        changes = _actions(offline)
        self.assertEqual(changes[0][1], "COVER")
        self.assertEqual(changes[0][2], "solo_audio_depart")
        self.assertEqual(changes[1][1], "PLAY")
        self.assertEqual(changes[1][2], "solo_audio_return")
        self.assertGreater(changes[0][0], 60)
        self.assertGreater(changes[1][0], 180)
        self.assertTrue(all(row["applied"] is False for row in offline))
        self.assertTrue(all(row["automatic_mute_enabled"] is False for row in offline))
        self.assertTrue(all(row["bridge"] == BRIDGE for row in offline))
        self.assertEqual(len({row["configuration_id"] for row in offline}), 1)

    def test_a_prefix_matches_the_same_minutes_inside_the_full_game(self):
        rows = _game_break_game()
        cut = 100
        full = replay(rows)
        prefix = replay([row for row in rows if row["audio_time"] <= cut])
        full_until_cut = [row for row in full if row["audio_time"] <= cut]
        self.assertEqual(prefix, full_until_cut)
        self.assertTrue(any(row["action"] == "COVER" for row in prefix))
        self.assertFalse(any(row["action"] == "PLAY" and row["reason"] == "solo_audio_return" for row in prefix))

    def test_a_score_that_is_not_available_yet_does_not_move_the_cover(self):
        held = [_row(t, 0.05) for t in range(0, 4)]
        held.append(_row(4, 0.40, end=4, available=12))
        early = replay(held)
        self.assertEqual(early[-1]["action"], "NO_CHANGE")
        self.assertEqual(early[-1]["evidence"][0]["status"], "not_yet_available")

        def delayed(t: float, lag: float = 8) -> dict:
            source = t - lag
            if source < 0:
                return _row(t, 0.05)
            departure = 0.40 if 60 <= source < 180 else 0.05
            return _row(t, departure, end=source, available=t)

        plain = _actions(replay(_game_break_game()))
        late = _actions(replay([delayed(t) for t in range(0, 241)]))
        self.assertEqual(late[0][0] - plain[0][0], 8)
        self.assertEqual(late[1][0] - plain[1][0], 8)
        self.assertEqual(plain[0], (63.0, "COVER", "solo_audio_depart"))
        self.assertEqual(plain[1], (182.0, "PLAY", "solo_audio_return"))

    def test_future_audio_in_an_early_row_is_ignored(self):
        rows = _game_break_game()
        leaked = json.loads(json.dumps(rows))
        leaked[10]["readings"].append(
            {
                "family": "audio",
                "raw": _audio(0.99),
                "audio_end_s": 200,
                "available_at_s": 10,
            }
        )
        plain = [(row["audio_time"], row["action"], row["reason"]) for row in replay(rows[:60])]
        leaked_decisions = replay(leaked[:60])
        leaked_id = [(row["audio_time"], row["action"], row["reason"]) for row in leaked_decisions]
        self.assertEqual(plain, leaked_id)
        extra = leaked_decisions[10]["evidence"][-1]
        self.assertEqual(extra["status"], "future_audio")
        self.assertNotEqual(extra["status"], "used")

    def test_gold_and_a_backwards_clock_are_refused(self):
        with self.assertRaises(ValueError):
            replay([{"audio_time": 1, "gold": {"start": 0}, "readings": []}])
        rows = [_row(2, 0.05), _row(1, 0.40)]
        with self.assertRaises(ValueError):
            replay(rows)


class FailOpenTests(unittest.TestCase):
    def test_missing_audio_does_not_count_as_a_commercial(self):
        rows = [_row(t, 0.05) for t in range(0, 60)]
        rows.extend(_row(t, 0.40, raw=None) for t in range(60, 75))
        rows.extend(_row(t, 0.40) for t in range(75, 90))
        changes = _actions(replay(rows))
        self.assertTrue(changes)
        self.assertGreaterEqual(changes[0][0], 75)
        self.assertTrue(all(row["reason"] != "solo_audio_depart" or row["audio_time"] >= 75 for row in replay(rows)))

    def test_stale_evidence_returns_to_play_and_does_not_cover_again_immediately(self):
        rows = [_row(t, 0.40) for t in range(0, 6)]
        covered = replay(rows)
        self.assertEqual(_actions(covered)[-1][1], "COVER")
        stale = _row(20, 0.40, end=0, available=0)
        fresh = _row(21, 0.40)
        shadow = Shadow()
        for row in rows:
            shadow.observe_evidence(row["audio_time"], {"readings": row["readings"]})
        opened = shadow.observe_evidence(stale["audio_time"], {"readings": stale["readings"]})
        self.assertEqual(opened["action"], "PLAY")
        self.assertEqual(opened["reason"], "stale_fail_open")
        nxt = shadow.observe_evidence(fresh["audio_time"], {"readings": fresh["readings"]})
        self.assertEqual(nxt["action"], "NO_CHANGE")

    def test_manual_play_and_reset(self):
        shadow = Shadow()
        for t in range(0, 6):
            row = _row(t, 0.40)
            shadow.observe_evidence(row["audio_time"], {"readings": row["readings"]})
        self.assertEqual(shadow.machine.state, "MUTED")
        manual = shadow.bridge.manual(6, "play")
        self.assertEqual(manual["action"], "PLAY")
        self.assertEqual(manual["reason"], "manual")
        self.assertFalse(manual["applied"])
        held = shadow.observe_evidence(7, {"readings": _row(7, 0.40)["readings"]})
        self.assertEqual(held["action"], "NO_CHANGE")
        shadow.bridge.reset()
        self.assertEqual(shadow.bridge.machine.state, "PLAY")
        self.assertIsNone(shadow.bridge._last_t)

    def test_a_person_cover_stays_up_when_the_score_goes_stale(self):
        shadow = Shadow()
        shadow.bridge.manual(1, "mute")
        stale = _row(20, 0.05, end=0, available=0)
        decision = shadow.observe_evidence(20, {"readings": stale["readings"]})
        self.assertEqual(decision["action"], "NO_CHANGE")
        self.assertEqual(decision["reason"], "human_cover_held")
        self.assertEqual(shadow.bridge.machine.state, "MUTED")


class GateTests(unittest.TestCase):
    def _gate(self) -> ListenerGate:
        rate = 48000
        beds = {
            "wednesday_night": np.full((rate, 2), 16000, dtype=np.int16),
            "silence": np.zeros((rate, 2), dtype=np.int16),
        }
        gate = ListenerGate(beds, np.zeros((100, 2), dtype=np.int16), prime_frames=256, rate=rate)
        gate.auto = False
        return gate

    def test_the_switch_defaults_off_and_the_return_fade_is_one_and_a_half_seconds(self):
        gate = self._gate()
        cover = {"action": "COVER"}
        self.assertFalse(carry_out(gate, cover, enabled=False)["applied"])
        self.assertEqual(gate.mode, "program")
        self.assertTrue(carry_out(gate, cover, enabled=True)["applied"])
        self.assertEqual(gate.mode, "replacement")
        back = carry_out(gate, {"action": "PLAY"}, enabled=True)
        self.assertTrue(back["applied"])
        self.assertEqual(back["return_fade_s"], 1.5)
        self.assertTrue(gate._pending_program)

    def test_the_desk_logs_the_bridge_and_leaves_the_television_on(self):
        rate = 48000
        beds = {
            "wednesday_night": np.full((rate, 2), 16000, dtype=np.int16),
            "silence": np.zeros((rate, 2), dtype=np.int16),
        }
        gate = ListenerGate(beds, np.zeros((100, 2), dtype=np.int16), prime_frames=2048, rate=rate)
        gate.auto = False
        hot = {"strong_departure": True, "departure": 0.4, "strong_return": False, "return": 0.0}
        from ohush_live.sports_daemon import SportsSession

        with TemporaryDirectory() as folder:
            session = SportsSession(Path(folder))
            try:
                session.families = {"speaker": None, "audio": hot, "semantic": None}
                for _ in range(4):
                    session.samples += rate
                    session.tick(gate)
                self.assertEqual(gate.mode, "program")
                rows = [json.loads(line) for line in Path(folder, "bridge.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
                self.assertEqual([row["action"] for row in rows], ["NO_CHANGE", "NO_CHANGE", "NO_CHANGE", "COVER"])
                self.assertTrue(all(row["applied"] is False for row in rows))
                self.assertTrue(all(row["evidence"][0]["status"] == "used" for row in rows))
            finally:
                session.close()


if __name__ == "__main__":
    unittest.main()
