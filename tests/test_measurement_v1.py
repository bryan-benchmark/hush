"""Synthetic proofs of the interval metrics. No recordings, no detectors.

The closed-gold check replays the four published degenerate policies. It reads
the truth ledger and does not write it.
"""

from __future__ import annotations

import json
import unittest
from collections import defaultdict
from pathlib import Path

from experiments.measurement.metrics import Interval, Span, TimelineError, score_timeline

REPO = Path(__file__).resolve().parents[1]

PRESERVED_KEYS = (
    "coverage_s",
    "target_commercial_s",
    "program_s",
    "unsure_s",
    "commercial_heard_s",
    "commercial_covered_s",
    "commercial_covered_fraction",
    "program_covered_s",
    "program_covered_per_hour",
    "false_cover_incidents",
    "false_returns_inside_commercials",
    "starts",
    "starts_missed",
    "start_delay_median_s",
    "start_delay_p95_s",
    "unscorable_s",
)


class MeasurementTests(unittest.TestCase):
    def test_never_cover_hears_every_commercial_second(self):
        intervals = [
            Interval(10, 40, "commercial", "mute", "certain"),
            Interval(100, 130, "network_promo", "play", "certain"),
        ]
        playback = [Span(0, 200, "program")]
        scored = score_timeline((0, 200), intervals, playback)
        self.assertEqual(scored["commercial_heard_s"], 30)
        self.assertEqual(scored["commercial_covered_s"], 0)
        self.assertEqual(scored["program_covered_s"], 0)
        self.assertEqual(scored["starts_missed"], 1)
        self.assertEqual(scored["false_returns_inside_commercials"], 0)

    def test_always_cover_hides_program_and_promo(self):
        intervals = [Interval(10, 40, "commercial", "mute", "certain")]
        playback = [Span(0, 200, "covered")]
        scored = score_timeline((0, 200), intervals, playback)
        self.assertEqual(scored["commercial_covered_fraction"], 1)
        self.assertEqual(scored["program_covered_s"], 170)
        self.assertEqual(scored["false_cover_incidents"], 1)
        self.assertEqual(scored["start_delay_median_s"], 0)

    def test_unsure_is_excluded_from_both_targets(self):
        intervals = [Interval(10, 40, "commercial", "mute", "unsure")]
        playback = [Span(0, 50, "program")]
        scored = score_timeline((0, 50), intervals, playback)
        self.assertEqual(scored["target_commercial_s"], 0)
        self.assertEqual(scored["unsure_s"], 30)
        self.assertEqual(scored["program_s"], 20)
        self.assertEqual(scored["commercial_heard_s"], 0)

    def test_false_return_is_an_uncover_inside_a_pod(self):
        intervals = [Interval(0, 60, "commercial", "mute", "certain")]
        playback = [
            Span(0, 10, "covered"),
            Span(10, 12, "program"),
            Span(12, 60, "covered"),
        ]
        scored = score_timeline((0, 60), intervals, playback)
        self.assertEqual(scored["false_returns_inside_commercials"], 1)
        self.assertEqual(scored["commercial_heard_s"], 2)
        self.assertAlmostEqual(scored["start_delay_median_s"], 0)

    def test_gap_in_playback_is_unscorable(self):
        intervals = [Interval(0, 10, "commercial", "mute", "certain")]
        playback = [Span(0, 4, "covered")]
        scored = score_timeline((0, 10), intervals, playback)
        self.assertEqual(scored["commercial_covered_s"], 4)
        self.assertEqual(scored["commercial_missing_s"], 6)
        self.assertEqual(scored["program_missing_s"], 0)
        self.assertEqual(scored["unscorable_s"], 6)
        self.assertEqual(scored["observed_fraction"], 0.4)
        self._assert_conserved(scored)

    def test_overlapping_playback_states_are_rejected(self):
        intervals = [Interval(0, 30, "commercial", "mute", "certain")]
        playback = [Span(0, 30, "program"), Span(10, 20, "covered")]
        with self.assertRaises(TimelineError):
            score_timeline((0, 30), intervals, playback)

    def test_unsorted_playback_is_rejected(self):
        intervals = [Interval(0, 30, "commercial", "mute", "certain")]
        playback = [Span(10, 18, "covered"), Span(0, 8, "covered")]
        with self.assertRaisesRegex(TimelineError, "backwards"):
            score_timeline((0, 30), intervals, playback)

    def test_commercial_crossing_coverage_is_rejected(self):
        intervals = [Interval(0, 40, "commercial", "mute", "certain")]
        playback = [Span(10, 30, "covered")]
        with self.assertRaisesRegex(TimelineError, "coverage boundary"):
            score_timeline((10, 30), intervals, playback)

    def test_program_context_may_contain_a_commercial(self):
        intervals = [
            Interval(0, 50, "program", "play", "certain"),
            Interval(20, 40, "commercial", "mute", "certain"),
        ]
        playback = [Span(0, 50, "program")]
        scored = score_timeline((0, 50), intervals, playback)
        self.assertEqual(scored["target_commercial_s"], 20)
        self.assertEqual(scored["program_s"], 30)
        self.assertEqual(scored["program_context_s"], 50)
        self.assertEqual(scored["program_context_overlap_commercial_s"], 20)
        self.assertEqual(scored["starts"], 1)
        self._assert_conserved(scored)

    def test_overlapping_commercials_are_rejected(self):
        intervals = [
            Interval(0, 30, "commercial", "mute", "certain"),
            Interval(20, 40, "commercial", "mute", "certain"),
        ]
        playback = [Span(0, 50, "program")]
        with self.assertRaisesRegex(TimelineError, "overlap"):
            score_timeline((0, 50), intervals, playback)

    def test_commercial_overlap_stays_visible_when_a_program_mark_sits_between(self):
        intervals = [
            Interval(0, 100, "commercial", "mute", "certain"),
            Interval(10, 20, "program", "play", "certain"),
            Interval(60, 90, "commercial", "mute", "certain"),
        ]
        playback = [Span(0, 100, "program")]
        with self.assertRaisesRegex(TimelineError, "overlap"):
            score_timeline((0, 100), intervals, playback)

    def test_overlapping_program_identities_are_rejected(self):
        intervals = [
            Interval(0, 40, "program", "play", "certain"),
            Interval(20, 50, "program", "play", "certain"),
        ]
        playback = [Span(0, 50, "program")]
        with self.assertRaisesRegex(TimelineError, "program marks"):
            score_timeline((0, 50), intervals, playback)

    def test_a_show_change_is_not_a_commercial_boundary(self):
        intervals = [
            Interval(0, 30, "program", "play", "certain"),
            Interval(30, 50, "program", "play", "certain"),
        ]
        playback = [Span(0, 50, "program")]
        scored = score_timeline((0, 50), intervals, playback)
        self.assertEqual(scored["starts"], 0)
        self.assertEqual(scored["target_commercial_s"], 0)
        self.assertEqual(scored["program_context_marks"], 2)
        self._assert_conserved(scored)

    def test_capture_gap_inside_coverage_is_rejected(self):
        intervals = [Interval(0, 10, "commercial", "mute", "certain")]
        playback = [Span(0, 30, "program")]
        with self.assertRaisesRegex(TimelineError, "capture gap"):
            score_timeline((0, 30), intervals, playback, capture_gaps=[(40, 50), (10, 12)])

    def test_capture_gap_outside_coverage_is_not_scored_as_program(self):
        intervals = [Interval(0, 10, "commercial", "mute", "certain")]
        playback = [Span(0, 30, "covered")]
        scored = score_timeline((0, 30), intervals, playback, capture_gaps=[(100, 160)])
        self.assertEqual(scored["capture_gap_s"], 60)
        self.assertEqual(scored["coverage_s"], 30)
        self._assert_conserved(scored)

    def test_unknown_playback_state_is_rejected(self):
        intervals = [Interval(0, 10, "commercial", "mute", "certain")]
        playback = [Span(0, 10, "muted")]
        with self.assertRaisesRegex(TimelineError, "unknown state"):
            score_timeline((0, 10), intervals, playback)

    def test_clock_reset_is_rejected(self):
        intervals = [Interval(0, 30, "commercial", "mute", "certain")]
        playback = [Span(0, 10, "covered"), Span(5, 8, "program")]
        with self.assertRaises(TimelineError):
            score_timeline((0, 30), intervals, playback)

    def test_repeated_cover_cycles_count_each_return(self):
        intervals = [Interval(0, 60, "commercial", "mute", "certain")]
        playback = [
            Span(0, 10, "covered"),
            Span(10, 12, "program"),
            Span(12, 40, "covered"),
            Span(40, 43, "program"),
            Span(43, 60, "covered"),
        ]
        scored = score_timeline((0, 60), intervals, playback)
        self.assertEqual(scored["false_returns_inside_commercials"], 2)
        self.assertEqual(scored["commercial_heard_s"], 5)
        self.assertEqual(scored["commercial_missing_s"], 0)
        self.assertEqual(scored["starts_missed"], 0)
        self._assert_conserved(scored)

    def test_never_caught_break_has_no_start_delay(self):
        intervals = [Interval(10, 40, "commercial", "mute", "certain")]
        playback = [Span(0, 50, "program")]
        scored = score_timeline((0, 50), intervals, playback)
        self.assertEqual(scored["starts_missed"], 1)
        self.assertIsNone(scored["start_delay_median_s"])
        self.assertEqual(scored["commercial_heard_s"], 30)
        self.assertEqual(scored["commercial_covered_s"], 0)
        self.assertEqual(scored["commercial_missing_s"], 0)
        self._assert_conserved(scored)

    def test_closed_gold_degenerate_policies_are_unchanged(self):
        ledger = REPO / "experiments/annotations/truth_events.jsonl"
        rows = []
        for line in ledger.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
        superseded = {row.get("supersedes") for row in rows if row.get("supersedes")}
        active = []
        for row in rows:
            if row.get("retracted") or row.get("event") == "retracted":
                continue
            if row.get("gold_id") in superseded:
                continue
            if "start_seconds" not in row or "end_seconds" not in row:
                continue
            active.append(row)
        by_session = defaultdict(list)
        for row in active:
            by_session[row["session"]].append(row)
        harness = json.loads((REPO / "docs/ohush/research/gold_harness.json").read_text(encoding="utf-8"))
        self.assertEqual(len(harness), 4)
        for row in harness:
            start, end = row["coverage"]
            intervals = [
                Interval(
                    float(event["start_seconds"]),
                    float(event["end_seconds"]),
                    str(event.get("event_class") or ""),
                    str(event.get("desired_action") or ""),
                    str(event.get("confidence") or ""),
                )
                for event in by_session.get(row["session"], [])
                if start <= float(event["start_seconds"]) and float(event["end_seconds"]) <= end + 1e-6
            ]
            never = score_timeline((start, end), intervals, [Span(start, end, "program")])
            always = score_timeline((start, end), intervals, [Span(start, end, "covered")])
            for key in PRESERVED_KEYS:
                self.assertEqual(never[key], row["never_cover"][key], f"{row['session']} never {key}")
                self.assertEqual(always[key], row["always_cover"][key], f"{row['session']} always {key}")
            self.assertEqual(never["commercial_missing_s"], 0)
            self.assertEqual(never["program_missing_s"], 0)
            self.assertEqual(never["observed_fraction"], 1)
            self.assertEqual(always["commercial_missing_s"], 0)
            self.assertEqual(always["program_missing_s"], 0)
            self.assertEqual(always["observed_fraction"], 1)
            self._assert_conserved(never)
            self._assert_conserved(always)

    def test_nine_closed_ranges_accept_program_context(self):
        ledger = REPO / "experiments/annotations/truth_events.jsonl"
        rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines() if line.strip()]
        superseded = {row.get("supersedes") for row in rows if row.get("supersedes")}
        active = [
            row
            for row in rows
            if not row.get("retracted")
            and row.get("event") != "retracted"
            and row.get("gold_id") not in superseded
            and "start_seconds" in row
        ]
        # resolve_ledger keeps the latest row per id. The harness above uses the
        # same superseded-id drop. Duplicate ids would already have failed there.
        coverage = []
        for name in ("GOLD_DATASET_20261013.json", "GOLD_DEV_V1.json", "GOLD_REPLICATION_V1.json"):
            doc = json.loads((REPO / "experiments/gold" / name).read_text(encoding="utf-8"))
            coverage.extend(row for row in doc["coverage"] if row.get("fully_annotated"))
        self.assertEqual(len(coverage), 12)
        commercials = [row for row in active if row.get("event_class") == "commercial"]
        programs = [row for row in active if row.get("event_class") == "program"]
        self.assertEqual(len(active), 177)
        self.assertEqual(len(commercials), 166)
        self.assertEqual(len(programs), 11)
        dataset = json.loads((REPO / "experiments/gold/GOLD_DATASET_20261013.json").read_text(encoding="utf-8"))
        self.assertEqual(len(dataset["coverage"]), 9)
        for span in dataset["coverage"]:
            start, end = float(span["from_seconds"]), float(span["to_seconds"])
            intervals = [
                Interval(
                    float(event["start_seconds"]),
                    float(event["end_seconds"]),
                    str(event.get("event_class") or ""),
                    str(event.get("desired_action") or ""),
                    str(event.get("confidence") or ""),
                )
                for event in active
                if event["session"] == span["session"]
            ]
            never = score_timeline((start, end), intervals, [Span(start, end, "program")])
            always = score_timeline((start, end), intervals, [Span(start, end, "covered")])
            self.assertEqual(never["commercial_missing_s"], 0)
            self.assertEqual(always["observed_fraction"], 1)
            self._assert_conserved(never)
            self._assert_conserved(always)
            self.assertGreaterEqual(never["program_s"], 0)

    def _assert_conserved(self, scored: dict) -> None:
        total = (
            scored["unsure_s"]
            + scored["commercial_heard_s"]
            + scored["commercial_covered_s"]
            + scored["commercial_missing_s"]
            + scored["program_heard_s"]
            + scored["program_covered_s"]
            + scored["program_missing_s"]
        )
        self.assertAlmostEqual(total, scored["coverage_s"], places=3)


if __name__ == "__main__":
    unittest.main()
