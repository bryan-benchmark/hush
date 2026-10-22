"""The voice floor stays on play. No audio."""

import json
import unittest
from pathlib import Path

from hush.break_trace import decide as trace_decide
from hush.voice_floor import COMMERCIAL_S, FLOOR, GAME_S, MEASURED, RECEIPTS, ROLE, decide

RECEIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "docs/ohush/research/VOICE_FLOOR_001/receipts.jsonl"
)


class VoiceFloorTests(unittest.TestCase):
    def test_the_floor_is_0_10_and_does_not_mute(self):
        self.assertEqual(FLOOR, 0.10)
        self.assertEqual(ROLE, "return")
        held = decide(0.10)
        self.assertTrue(held["show_present"])
        self.assertFalse(held["mute"])
        self.assertFalse(held["starts_commercial"])
        self.assertTrue(held["placeholder"])
        under = decide(0.09)
        self.assertFalse(under["show_present"])
        self.assertFalse(under["mute"])
        self.assertFalse(under["starts_commercial"])
        self.assertEqual(under["reason"], "under 0.10 does not start a commercial")
        self.assertIsNone(decide(None)["show_present"])

    def test_0_15_cuts_the_show_and_0_10_does_not(self):
        by_line = {row["line"]: row for row in MEASURED}
        self.assertEqual(by_line[0.10]["game_off_s"], 4)
        self.assertEqual(by_line[0.15]["game_off_s"], 112)
        self.assertEqual(by_line[0.20]["game_off_s"], 324)
        self.assertGreater(by_line[0.10]["ad_off_s"], 0)
        self.assertLess(by_line[0.10]["ad_off_s"], by_line[0.15]["ad_off_s"])
        self.assertEqual(GAME_S, 67428)
        self.assertEqual(COMMERCIAL_S, 17648.4)

    def test_receipts_match_the_file_and_sum_to_the_measured_seconds(self):
        on_disk = [json.loads(line) for line in RECEIPT_PATH.read_text().splitlines() if line.strip()]
        self.assertEqual(list(RECEIPTS), on_disk)
        for line, seconds in ((0.10, 4), (0.15, 112)):
            total = sum(row["seconds"] for row in RECEIPTS if row["line"] == line)
            self.assertEqual(total, seconds)
        booth = [row for row in RECEIPTS if row["what"] == "booth call"]
        self.assertEqual(len(booth), 1)
        self.assertEqual(booth[0]["line"], 0.20)
        self.assertGreater(booth[0]["peak"], FLOOR)

    def test_the_play_model_asks_the_floor_and_still_cannot_cover(self):
        stayed = trace_decide(["booth_left"], authorized_cover=False, rolling_max=0.12)
        self.assertEqual(stayed["action"], "play")
        self.assertTrue(stayed["voice_floor"]["show_present"])
        self.assertEqual(stayed["voice_floor"]["role"], "return")
        self.assertIn("the show is back over the 0.10 floor", stayed["blocked"])

        quiet = trace_decide([], authorized_cover=False, rolling_max=0.04)
        self.assertEqual(quiet["action"], "play")
        self.assertFalse(quiet["voice_floor"]["mute"])
        self.assertFalse(quiet["voice_floor"]["starts_commercial"])
        self.assertIn("under 0.10 does not start a commercial", quiet["blocked"])

        covered = trace_decide(["booth_left"], authorized_cover=True, rolling_max=0.04)
        self.assertEqual(covered["action"], "cover")
        self.assertEqual(covered["authorized_by"], "universal_v1_count_200")
        self.assertEqual(covered["blocked"], [])
        self.assertFalse(covered["voice_floor"]["mute"])


if __name__ == "__main__":
    unittest.main()
