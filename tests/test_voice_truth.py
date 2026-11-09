"""The entry guard reads three names, and it leaves an open mute alone."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from experiments.nfl75.mean import covers_from_mean
from experiments.nfl75.voice_truth import (
    ALLOW,
    FRESH_S,
    MARGIN,
    candidate_rows,
    entry_guard_covers,
    owner_names,
    qualify,
)


class VoiceTruthTests(unittest.TestCase):
    def test_the_declared_names_and_gaps(self):
        self.assertEqual(ALLOW, ("Al Michaels", "Kirk Herbstreit", "Clarissa Thompson"))
        self.assertEqual(MARGIN, 0.15)
        self.assertEqual(FRESH_S, 1.0)

    def test_whitworth_and_a_thin_gap_do_not_qualify(self):
        self.assertIsNone(qualify({"Andrew Whitworth": 0.70, "Tony Gonzalez": 0.10}))
        self.assertIsNone(qualify({"Al Michaels": 0.40, "Kirk Herbstreit": 0.30}))
        found = qualify({"Kirk Herbstreit": 0.55, "Al Michaels": 0.10})
        self.assertEqual(found["name"], "Kirk Herbstreit")

    def test_a_fresh_michaels_window_blocks_the_open_only(self):
        times = [0.0, 1.0, 2.0, 3.0, 4.0]
        scores = [1.0, 1.0, 1.0, 1.0, 1.0]
        bare = covers_from_mean(times, scores, window=1, start_line=0.5)
        guarded = entry_guard_covers(times, scores, [0.0], window=1, start_line=0.5, return_persist_s=10.0)
        self.assertEqual(bare[0][0], 0.0)
        self.assertGreater(guarded[0][0], 0.0)

    def test_an_open_mute_is_not_released_by_a_later_match(self):
        times = [0.0, 1.0, 2.0, 3.0]
        scores = [1.0, 1.0, 1.0, 1.0]
        guarded = entry_guard_covers(times, scores, [1.0], window=1, start_line=0.5, return_persist_s=10.0)
        self.assertEqual(guarded[0][0], 0.0)
        self.assertGreater(guarded[0][1], 1.0)

    def test_no_qualifying_window_matches_the_frozen_mean(self):
        times = [float(item) for item in range(6)]
        scores = [0.0, 1.0, 1.0, 0.0, 0.0, 0.0]
        bare = covers_from_mean(times, scores, window=1, start_line=0.5, return_persist_s=2.0)
        guarded = entry_guard_covers(times, scores, [], window=1, start_line=0.5, return_persist_s=2.0)
        self.assertEqual(guarded, bare)

    def test_the_candidate_seconds_leave_whitworth_out(self):
        rows = [
            _ignore("Al Michaels", 0.60, 0.10, 10.0),
            _ignore("Kirk Herbstreit", 0.60, 0.10, 8.0),
            _ignore("Clarissa Thompson", 0.60, 0.10, 6.0),
            _ignore("Andrew Whitworth", 0.50, 0.20, 7.0),
            _ignore("Andrew Whitworth", 0.26, 0.12, 16.0),
        ]
        found = candidate_rows(rows)
        self.assertEqual(found["episodes"], 3)
        self.assertEqual(found["seconds"], 24.0)
        self.assertEqual(found["wide_other"], [{"name": "Andrew Whitworth", "seconds": 7.0}])
        self.assertEqual(found["thin"], [{"name": "Andrew Whitworth", "seconds": 16.0}])
        self.assertFalse(found["identity_verified"])

    def test_the_blind_list_leaves_eval_sealed(self):
        research = Path(__file__).resolve().parents[1] / "docs" / "ohush" / "research"
        blind = json.loads((research / "OHUSH_VOICE_TRUTH_002" / "blind.json").read_text(encoding="utf-8"))
        queue = [
            json.loads(line)
            for line in (research / "OHUSH_VOICE_FN_ATOMIC_001" / "queue.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        sealed = {row["id"] for row in queue if row["split"] == "eval"}
        shown = {row["id"] for row in blind}
        self.assertEqual(len(blind), 25)
        self.assertFalse(sealed & shown)
        self.assertNotIn("cited_name", blind[0])
        self.assertNotIn("why_queued", blind[0])

    def test_owner_names_keep_a_mixed_box_mixed(self):
        self.assertEqual(owner_names("al michaels + whistle"), ["Al Michaels"])
        self.assertEqual(owner_names("ryan fits"), ["Ryan Fitzpatrick"])
        self.assertEqual(owner_names("clarisssa thompson"), ["Clarissa Thompson"])
        self.assertEqual(owner_names("clarrisa thompson"), ["Clarissa Thompson"])
        self.assertEqual(owner_names("TNF gang ryan F, sherman, whit, thompson all talknig"), [])


def _ignore(name, cosine, second, duration):
    return {
        "split": "dev",
        "kind": "decision_ignored_match",
        "cited_name": name,
        "cited_cosine": cosine,
        "second_cosine": second,
        "focus_start_s": 0.0,
        "focus_end_s": duration,
    }
