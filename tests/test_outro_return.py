"""The two-minute look after an outro. No audio and no mute."""

import unittest

from hush.outro_return import describe_look, rolling_maxes, union_seconds


def row(t: float, cosine: float | None, over: bool = False) -> dict:
    return {"t": t, "cosine": cosine, "booth_over_line": over}


class OutroReturnTests(unittest.TestCase):
    def test_rolling_max_forgets_the_booth_after_thirty_seconds(self):
        rows = [row(0, 0.8), row(4, None), row(120, 0.02)]
        scores = rolling_maxes(rows)
        self.assertEqual(scores[1], 0.8)
        self.assertEqual(scores[2], 0.02)

    def test_look_waits_out_a_long_ad_then_takes_the_booth(self):
        rows = [row(t, 0.04) for t in range(0, 260, 4)]
        rows.append(row(260, 0.4, True))
        for item, score in zip(rows, rolling_maxes(rows)):
            item["roll"] = score
        found = describe_look(rows, [(8.0, 250.0)], 8.0, True)
        self.assertEqual(found["look_region"], "ad")
        self.assertEqual(found["floor_t"], 260.0)
        self.assertEqual(found["floor_region"], "game")
        self.assertFalse(found["fail_open"])

    def test_short_pod_is_already_game_when_the_look_opens(self):
        rows = [row(t, 0.5, True) for t in range(0, 200, 4)]
        for item, score in zip(rows, rolling_maxes(rows)):
            item["roll"] = score
        absent = describe_look(rows, [(10.0, 70.0)], 10.0, False)
        self.assertIsNone(absent["cover_end"])
        found = describe_look(rows, [(10.0, 70.0)], 10.0, True)
        self.assertGreater(found["look_at"], 70.0)
        self.assertEqual(found["look_region"], "game")
        self.assertEqual(found["floor_region"], "game")
        covered = union_seconds([("game", 10.0, found["cover_end"])], {"game": [(10.0, 70.0)]})
        self.assertGreater(covered["program_s"], 0)
        self.assertTrue(covered["broken"])

    def test_overlapping_covers_are_counted_once(self):
        pods = {"s": [(0.0, 100.0)]}
        once = union_seconds([("s", 0.0, 80.0), ("s", 40.0, 90.0)], pods)
        self.assertEqual(once["commercial_s"], 90.0)
        self.assertEqual(once["program_s"], 0.0)
        self.assertFalse(once["broken"])


if __name__ == "__main__":
    unittest.main()
