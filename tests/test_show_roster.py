"""Show booths stay on their own broadcasts. No audio."""

import unittest

from hush.show_roster import decide, membership, roster


class ShowRosterTests(unittest.TestCase):
    def test_redzone_does_not_consider_tirico(self):
        self.assertEqual(roster("redzone"), ("Scott Hanson",))
        self.assertNotIn("Mike Tirico", roster("redzone"))
        self.assertNotIn("Scott Hanson", roster("snf"))
        self.assertNotIn("Joe Buck", roster("snf"))
        self.assertNotIn("Al Michaels", roster("mnf"))

    def test_redzone_stays_play_until_five_minutes(self):
        fresh = decide("redzone", 0)
        self.assertEqual(fresh["commercial_rules"], "off")
        self.assertAlmostEqual(fresh["membership"], 1.0)
        late = decide("redzone", 299)
        self.assertEqual(late["commercial_rules"], "off")
        self.assertGreater(late["membership"], 0)
        gone = decide("redzone", 300)
        self.assertEqual(gone["commercial_rules"], "no_show")
        self.assertEqual(gone["membership"], 0.0)

    def test_a_game_show_keeps_commercial_rules_while_its_booth_is_present(self):
        state = decide("snf", 10)
        self.assertEqual(state["commercial_rules"], "on")
        self.assertEqual(state["roster"], ("Mike Tirico", "Cris Collinsworth"))
        self.assertEqual(decide("mnf", 0)["roster"], ("Joe Buck", "Troy Aikman"))
        self.assertEqual(decide("tnf", 0)["roster"], ("Al Michaels", "Kirk Herbstreit"))

    def test_five_minutes_lets_the_show_go_without_muting(self):
        for show in ("snf", "mnf", "tnf", "college_saturday", "redzone"):
            state = decide(show, None)
            self.assertEqual(state["commercial_rules"], "no_show")
            self.assertFalse(state["on_show"])
        self.assertEqual(membership(150), 0.5)


if __name__ == "__main__":
    unittest.main()
