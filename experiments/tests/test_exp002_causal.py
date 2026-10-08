"""Experiment 002 speaker memory: causal, and not tuned on labels."""

from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from hush.speaker_memory import (  # noqa: E402
    MATCH_COSINE,
    OnlineSpeakerMemory,
    build_timeline,
    continuity_drops,
    embedding_windows,
    merge_regions,
    speech_without_recurring_episodes,
)


def _voice(axis: int) -> np.ndarray:
    vec = np.zeros(4, dtype=np.float64)
    vec[axis] = 1.0
    return vec


def _run(specs: list[tuple[float, float, np.ndarray]]) -> list[dict]:
    memory = OnlineSpeakerMemory()
    return [memory.observe(vec, start, end) for start, end, vec in specs]


class FrozenRules(unittest.TestCase):
    def test_published_match_threshold_is_closed_on_the_boundary(self):
        self.assertEqual(MATCH_COSINE, 0.25)
        memory = OnlineSpeakerMemory()
        memory.observe(_voice(0), 0.0, 2.0)
        on_threshold = np.array([MATCH_COSINE, math.sqrt(1.0 - MATCH_COSINE**2), 0.0, 0.0])
        matched = memory.observe(on_threshold, 20.0, 22.0)
        self.assertFalse(matched["speaker_is_novel"])
        self.assertAlmostEqual(matched["similarity_to_best_known"], MATCH_COSINE, places=6)

        fresh = OnlineSpeakerMemory()
        fresh.observe(_voice(0), 0.0, 2.0)
        below = MATCH_COSINE - 0.01
        rejected = np.array([below, math.sqrt(1.0 - below**2), 0.0, 0.0])
        novel = fresh.observe(rejected, 20.0, 22.0)
        self.assertTrue(novel["speaker_is_novel"])
        self.assertEqual(novel["assigned_cluster_id"], "c0002")

    def test_overlap_does_not_double_count_speech(self):
        rows = _run([(0.0, 2.0, _voice(0)), (1.0, 3.0, _voice(0)), (2.0, 4.0, _voice(0))])
        self.assertEqual(rows[0]["cum_after"], 2.0)
        self.assertEqual(rows[1]["cum_after"], 3.0)
        self.assertEqual(rows[2]["cum_after"], 4.0)
        self.assertEqual(rows[2]["occ_after"], 1)
        self.assertFalse(rows[2]["speaker_is_recurring"])
        self.assertEqual(rows[1]["match_decision"], "MATCH")


class Recurrence(unittest.TestCase):
    def test_current_window_cannot_qualify_itself_and_return_needs_a_real_absence(self):
        voice = _voice(0)
        rows = _run(
            [
                (10.0, 12.0, voice),
                (40.0, 42.0, voice),
                (80.0, 82.0, voice),
                (100.0, 102.0, voice),
                (140.0, 142.0, voice),
            ]
        )
        self.assertTrue(rows[0]["speaker_is_novel"])
        self.assertFalse(rows[1]["speaker_is_recurring"])
        self.assertFalse(rows[2]["speaker_is_recurring"])
        self.assertEqual(rows[2]["cluster_occurrence_count"], 2)
        self.assertTrue(rows[2]["recurring_after"])
        self.assertTrue(rows[3]["speaker_is_recurring"])
        self.assertEqual(rows[3]["program_speaker_return_score"], 0.0)
        self.assertGreater(rows[4]["program_speaker_return_score"], 0.0)
        self.assertEqual(rows[4]["assigned_cluster_id"], "c0001")

    def test_later_window_does_not_change_earlier_decisions(self):
        voice = _voice(0)
        other = _voice(1)
        specs = [
            (0.0, 2.0, voice),
            (10.0, 12.0, voice),
            (40.0, 42.0, voice),
            (80.0, 82.0, other),
        ]
        full = _run(specs)
        prefix = _run(specs[:3])
        for earlier, later in zip(prefix, full):
            self.assertEqual(earlier["assigned_cluster_id"], later["assigned_cluster_id"])
            self.assertEqual(earlier["speaker_is_recurring"], later["speaker_is_recurring"])
            self.assertEqual(earlier["cum_after"], later["cum_after"])
            self.assertEqual(earlier["match_decision"], later["match_decision"])


class Timeline(unittest.TestCase):
    def test_silence_is_not_scored_as_speaker_loss(self):
        timeline = build_timeline([], [], 10.0)
        self.assertTrue(np.all(timeline["speech_state"] == "NO_SPEECH"))
        self.assertTrue(np.all(timeline["speech_but_program_speakers_absent"] == 0))
        self.assertTrue(np.all(np.isnan(timeline["program_speaker_continuity_score"])))
        self.assertTrue(np.all(np.isnan(timeline["recent_recurring_speaker_fraction_15s"])))

    def test_pending_speech_is_not_novel_and_a_completed_novel_window_is(self):
        regions = [(0.0, 2.0)]
        windows = _run([(0.0, 2.0, _voice(0))])
        timeline = build_timeline(regions, windows, 4.0)
        self.assertEqual(timeline["speech_state"][0], "SPEECH_PENDING")
        self.assertEqual(timeline["speech_but_program_speakers_absent"][0], 0)
        self.assertTrue(math.isnan(timeline["program_speaker_continuity_score"][0]))
        self.assertEqual(timeline["speech_state"][1], "SPEECH_NOVEL")
        self.assertEqual(timeline["speech_but_program_speakers_absent"][1], 1)
        self.assertEqual(timeline["program_speaker_continuity_score"][1], 0.0)

    def test_future_windows_do_not_change_the_past_timeline(self):
        voice = _voice(0)
        other = _voice(1)
        specs = [
            (0.0, 2.0, voice),
            (10.0, 12.0, voice),
            (40.0, 42.0, voice),
            (100.0, 102.0, other),
        ]
        rows = _run(specs)
        regions = [(0.0, 2.0), (10.0, 12.0), (40.0, 42.0), (100.0, 102.0)]
        with_future = build_timeline(regions, rows, 50.0)
        prefix = build_timeline(regions, rows[:3], 50.0)
        for key, full in with_future.items():
            past = prefix[key]
            if full.dtype == object:
                self.assertTrue(np.array_equal(full, past), key)
            else:
                np.testing.assert_allclose(full, past, equal_nan=True, err_msg=key)

    def test_episodes_bridge_short_silence_and_stop_at_a_recurring_speaker(self):
        states = [
            "SPEECH_NOVEL",
            "SPEECH_NOVEL",
            "NO_SPEECH",
            "NO_SPEECH",
            "SPEECH_KNOWN_NOT_RECURRING",
            "SPEECH_RECURRING",
            "NO_SPEECH",
            "NO_SPEECH",
            "NO_SPEECH",
            "SPEECH_NOVEL",
        ]
        episodes = speech_without_recurring_episodes(states, bridge_s=5)
        self.assertEqual(episodes[0]["start_seconds"], 0.0)
        self.assertEqual(episodes[0]["end_seconds"], 5.0)
        self.assertEqual(episodes[0]["speech_without_recurring_seconds"], 3)
        self.assertEqual(episodes[1]["start_seconds"], 9.0)
        self.assertEqual(len(episodes), 2)

        split = ["SPEECH_NOVEL"] + ["NO_SPEECH"] * 6 + ["SPEECH_NOVEL"]
        separate = speech_without_recurring_episodes(split, bridge_s=5)
        self.assertEqual(len(separate), 2)

    def test_drop_listing_keeps_one_event_inside_the_refractory(self):
        n = 40
        score = np.array([0.8] * 20 + [0.2] * 20, dtype=np.float64)
        timeline = {
            "timestamp_seconds": np.arange(1, n + 1, dtype=np.float64),
            "program_speaker_continuity_score": score,
        }
        drops = continuity_drops(timeline)
        self.assertEqual(len(drops), 1)
        self.assertAlmostEqual(drops[0]["drop"], 0.6)
        self.assertEqual(drops[0]["timestamp_seconds"], 21.0)


class Windows(unittest.TestCase):
    def test_short_fragments_are_dropped_and_long_regions_hop(self):
        kept = merge_regions([(0.0, 0.4), (5.0, 6.2), (6.0, 16.0)])
        self.assertEqual(kept, [(5.0, 16.0)])
        windows = embedding_windows(kept)
        self.assertGreaterEqual(min(end - start for start, end in windows), 1.0)
        self.assertLessEqual(max(end - start for start, end in windows), 2.0)
        self.assertEqual(windows[0], (5.0, 7.0))
        self.assertTrue(all(end > start for start, end in windows))


if __name__ == "__main__":
    unittest.main()
