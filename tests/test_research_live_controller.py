"""Online research controller: exact 8/2 streaks and causal cooldown."""

from __future__ import annotations

import unittest

from ohush_live.research_muter import LiveController


class LiveControllerTests(unittest.TestCase):
    def test_needs_eight_hot_hops_to_cover(self) -> None:
        ctl = LiveController()
        t = 0.0
        for _ in range(7):
            t += 0.25
            row = ctl.step(t, 0.95)
            self.assertEqual(row["action"], "play")
        t += 0.25
        row = ctl.step(t, 0.95)
        self.assertEqual(row["action"], "cover")
        self.assertTrue(row["transition"])

    def test_two_cold_hops_return_then_force_play_cooldown(self) -> None:
        ctl = LiveController()
        t = 0.0
        for _ in range(8):
            t += 0.25
            ctl.step(t, 0.95)
        self.assertEqual(ctl.state, "cover")
        t += 0.25
        self.assertEqual(ctl.step(t, 0.10)["action"], "cover")
        t += 0.25
        row = ctl.step(t, 0.10)
        self.assertEqual(row["action"], "play")
        self.assertTrue(row["transition"])
        # Causal cooldown: even hot scores stay on play for 8s.
        for _ in range(20):
            t += 0.25
            row = ctl.step(t, 0.99)
            self.assertEqual(row["action"], "play")
            self.assertTrue(row["force_play"])


if __name__ == "__main__":
    unittest.main()
