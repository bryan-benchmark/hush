"""LIVE_RECOVERY_001 permanent regression fixtures against the live product Machine."""

from __future__ import annotations

import unittest

from ohush_live.recovery.fixtures import FIXTURES, run_fixture
from ohush_live.state import Machine


class RecoveryFixtureTests(unittest.TestCase):
    def test_all_candidate_expectations(self):
        for name, fix in FIXTURES.items():
            with self.subTest(name):
                result = run_fixture(Machine, fix)
                expect = fix["expect_candidate"]
                self.assertEqual(result["final"], expect["final"], name)
                if expect.get("reason"):
                    self.assertIn(expect["reason"], result["reasons"], name)
                if expect.get("forbid_reason"):
                    self.assertNotIn(expect["forbid_reason"], result["reasons"], name)


if __name__ == "__main__":
    unittest.main()
