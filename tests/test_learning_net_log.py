"""The learning-net ledger appends and does not rewrite an earlier line."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from experiments.ledger import sha256_file, sha256_text

from tools.gpu_lab.learning_net import log as netlog
import numpy as np

from tools.gpu_lab.learning_net.close import wave0_reading
from tools.gpu_lab.learning_net.dasheng_close import scale_reading
from tools.gpu_lab.learning_net.game_sounds import class_floors
from tools.gpu_lab.learning_net.program_names import top_counts
from tools.gpu_lab.learning_net.joint_remainder import remainder_indexes
from tools.gpu_lab.learning_net.remainder_place import gap_bin, nearest_commercial
from tools.gpu_lab.learning_net.program_spread import bin_counts, contiguous_runs
from tools.gpu_lab.learning_net.speech_close import speech_reading
from tools.gpu_lab.learning_net.speech_rank import group_floors, group_name
from tools.gpu_lab.learning_net.dasheng_rank import embed_session, mean_tokens
from tools.gpu_lab.learning_net.slot_align import catalog_show, chunk_wall, place_label, select_game, stop_shape, _load_chunks
from tools.gpu_lab.learning_net.slot_place import elapsed_at, end_relation, recover_game_over


class LedgerTests(unittest.TestCase):
    def test_a_second_receipt_keeps_the_first_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = root / "LEDGER.jsonl"
            with patch.object(netlog, "NET_ROOT", root), patch.object(netlog, "LEDGER_PATH", ledger):
                first = root / "one"
                first.mkdir()
                (first / "started.json").write_text(json.dumps({"started_at": "t0"}), encoding="utf-8")
                netlog.finish_probe(first, "ranking", "q", {"n": 1}, {"auc": 0.5}, Path(__file__))
                second = root / "two"
                second.mkdir()
                (second / "started.json").write_text(json.dumps({"started_at": "t1"}), encoding="utf-8")
                netlog.finish_probe(second, "repeat_map", "q2", {"n": 2}, {"copy": 0.1}, Path(__file__))
            lines = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
            self.assertEqual([line["probe_id"] for line in lines], ["ranking", "repeat_map"])
            self.assertEqual(lines[0]["parameters"], {"n": 1})
            result_path = root / "one" / "result.json"
            self.assertTrue(result_path.is_file())
            self.assertFalse(result_path.with_name("result.json.tmp").exists())
            self.assertEqual(sha256_file(result_path), sha256_text(result_path.read_text(encoding="utf-8")))
            self.assertFalse(b"\r\n" in result_path.read_bytes())


class Wave0ReadingTests(unittest.TestCase):
    def test_a_later_game_below_the_pre_october_floor_opens_one_row(self):
        ranking = {
            "rows": [
                {"window_s": 2.0, "role": "train", "session": "train", "auc": 0.95},
                {"window_s": 2.0, "role": "calibrate", "session": "espn", "auc": 0.96},
                {"window_s": 2.0, "role": "develop", "session": "sunday", "auc": 0.76},
                {"window_s": 2.0, "role": "develop", "session": "thursday", "auc": 0.97},
                {"window_s": 5.0, "role": "train", "session": "train", "auc": 0.95},
                {"window_s": 5.0, "role": "calibrate", "session": "espn", "auc": 0.96},
                {"window_s": 5.0, "role": "develop", "session": "sunday", "auc": 0.97},
                {"window_s": 10.0, "role": "train", "session": "train", "auc": 0.95},
                {"window_s": 10.0, "role": "calibrate", "session": "espn", "auc": 0.96},
                {"window_s": 10.0, "role": "develop", "session": "sunday", "auc": 0.97},
            ]
        }
        repeat = {
            "copy_bar_cosine": 0.5,
            "october_commercial_copy_fraction": {"copy_fraction": 1.0},
            "october_program_false_copy_fraction": {"copy_fraction": 1.0},
        }
        tags = {"listen": [{"note": None}], "hidden_program_top1": [{"class": "Music", "n": 2}, {"class": "Speech", "n": 1}]}
        boundaries = {
            "edges": {"gap_fraction": 0.7, "median_dip_db": 28.0},
            "program_interior": {"gap_fraction": 0.17, "median_dip_db": 5.0},
            "commercial_interior": {"gap_fraction": 0.4, "median_dip_db": 10.0},
        }
        joint = {
            "threshold": 18.4,
            "october_program_cut_s": 51.0,
            "october_commercial_held_s": 570.0,
            "october_broken": True,
            "control": {"program_cut_s": 0.0},
        }
        reading = wave0_reading(ranking, repeat, tags, boundaries, joint)
        self.assertEqual(reading["opened"], ["dasheng_base_ranking"])
        self.assertFalse(reading["wave1_started"])
        self.assertFalse(reading["need_json_rewritten"])
        self.assertEqual(reading["later_games_below_pre_october_floor"], ["sunday"])

    def test_equal_ranking_and_a_clean_copy_bar_would_open_two_rows(self):
        ranking = {
            "rows": [
                {"window_s": window, "role": role, "session": role, "auc": 0.95}
                for window in (2.0, 5.0, 10.0)
                for role in ("train", "calibrate", "develop")
            ]
        }
        repeat = {
            "copy_bar_cosine": 0.5,
            "october_commercial_copy_fraction": {"copy_fraction": 0.8},
            "october_program_false_copy_fraction": {"copy_fraction": 0.0},
        }
        tags = {"listen": [{"note": "song"}], "hidden_program_top1": [{"class": "Music", "n": 2}, {"class": "Speech", "n": 1}]}
        boundaries = {
            "edges": {"gap_fraction": 0.7, "median_dip_db": 28.0},
            "program_interior": {"gap_fraction": 0.17, "median_dip_db": 5.0},
            "commercial_interior": {"gap_fraction": 0.4, "median_dip_db": 10.0},
        }
        joint = {
            "threshold": 18.4,
            "october_program_cut_s": 0.0,
            "october_commercial_held_s": 100.0,
            "october_broken": False,
            "control": {"program_cut_s": 0.0},
        }
        reading = wave0_reading(ranking, repeat, tags, boundaries, joint)
        self.assertEqual(reading["opened"], ["stay_on_these_vectors", "copy_matcher"])
        self.assertIsNone(reading["one_next_build"])


class DashengCacheTests(unittest.TestCase):
    def test_mean_tokens_averages_each_clip(self):
        tokens = np.array([[[0.0, 2.0], [2.0, 4.0]], [[1.0, 1.0], [3.0, 3.0]]], dtype=np.float32)
        averaged = mean_tokens(tokens)
        self.assertEqual(averaged.shape, (2, 2))
        self.assertTrue(np.allclose(averaged[0], [1.0, 3.0]))

    def test_a_game_under_the_floor_does_not_open_another_encoder(self):
        reading = scale_reading(
            {
                "later_games_below_pre_october_floor": ["sunday"],
                "ranking_against_pre_october_floor": [
                    {
                        "window_s": 2.0,
                        "pre_october_floor_auc": 0.98,
                        "october_below_pre_october_floor": [
                            {"session": "sunday", "auc": 0.69, "dasheng_base_auc": 0.74, "ast_auc": 0.76}
                        ],
                    }
                ],
            }
        )
        self.assertFalse(reading["larger_encoder_lifted_every_later_game"])
        self.assertIsNone(reading["one_next_build"])
        self.assertFalse(reading["larger_model_started"])


class GameSoundFloorTests(unittest.TestCase):
    def test_a_later_game_under_the_class_floor_is_listed(self):
        rows = [
            {"session": "train", "role": "train", "classes": [{"class": "Music", "auc": 0.9}]},
            {"session": "sunday", "role": "develop", "classes": [{"class": "Music", "auc": 0.6}]},
            {"session": "thursday", "role": "develop", "classes": [{"class": "Music", "auc": 0.91}]},
        ]
        reading = class_floors(rows, "Music")
        self.assertEqual(reading["pre_october_floor_auc"], 0.9)
        self.assertEqual(reading["october_below_pre_october_floor"], [{"session": "sunday", "auc": 0.6}])


class SpeechGroupTests(unittest.TestCase):
    def test_only_music_and_speech_keep_their_names(self):
        self.assertEqual(group_name("Music"), "Music")
        self.assertEqual(group_name("Speech"), "Speech")
        self.assertEqual(group_name("Whoosh, swoosh, swish"), "other")

    def test_a_speech_group_under_the_floor_is_listed(self):
        rows = [
            {"session": "train", "role": "train", "auc_by_group": {"Speech": 0.9}},
            {"session": "sunday", "role": "develop", "auc_by_group": {"Speech": 0.7}},
        ]
        reading = group_floors(rows, "Speech")
        self.assertEqual(reading["october_below_pre_october_floor"], [{"session": "sunday", "auc": 0.7}])

    def test_speech_that_ranks_cleaner_than_music_keeps_the_word_model_shut(self):
        reading = speech_reading(
            [
                {"session": "sunday", "role": "develop", "auc_by_group": {"Speech": 0.82, "Music": 0.73}},
                {"session": "thursday", "role": "develop", "auc_by_group": {"Speech": 0.98, "Music": 0.85}},
            ]
        )
        self.assertFalse(reading["speech_to_text_opened"])
        self.assertFalse(reading["speech_to_text_started"])


class ProgramNameTests(unittest.TestCase):
    def test_top_counts_use_the_rows_they_are_given(self):
        counts = top_counts(np.array([1, 1, 0]), ["Silence", "Music"], limit=2)
        self.assertEqual(counts[0], {"class": "Music", "n": 2, "fraction": round(2 / 3, 6)})
        self.assertEqual(top_counts(np.array([], dtype=np.int64), ["Music"]), [])


class ProgramSpreadTests(unittest.TestCase):
    def test_a_gap_splits_two_stretches(self):
        runs = contiguous_runs(np.array([0.0, 1.0, 2.0, 10.0, 11.0]))
        self.assertEqual(len(runs), 2)
        self.assertEqual(runs[0]["n"], 3)
        self.assertEqual(runs[0]["end_seconds"], 3.0)
        self.assertEqual(runs[1]["start_seconds"], 10.0)

    def test_bins_cover_the_broadcast_span(self):
        self.assertEqual(bin_counts(np.array([0.0, 0.5, 9.5]), 0.0, 10.0, bins=10), [2, 0, 0, 0, 0, 0, 0, 0, 0, 1])


class JointRemainderTests(unittest.TestCase):
    def test_only_a_high_score_inside_the_game_is_kept(self):
        indexes = remainder_indexes([0.0, 1.0, 5.0], [1.0, 0.2, 5.0], [(0.0, 2.0)], threshold=0.5)
        self.assertEqual(indexes, [0])


class SlotAlignTests(unittest.TestCase):
    def test_a_hole_uses_the_chunk_clock(self):
        chunks = [
            {"start_elapsed_seconds": 0.0, "end_elapsed_seconds": 120.0, "started_at": "2026-10-11T20:43:56-04:00"},
            {"start_elapsed_seconds": 120.0, "end_elapsed_seconds": 500.0, "started_at": "2026-10-11T21:09:07-04:00"},
        ]
        wall = chunk_wall(chunks, 200.0)
        self.assertEqual(wall.hour, 21)
        self.assertEqual(wall.minute, 10)
        self.assertEqual(wall.second, 27)

    def test_the_rulebook_midpoint_splits_a_short_stop_from_a_frozen_one(self):
        self.assertEqual(stop_shape("Timeout", 74.9, 5), "short_stop")
        self.assertEqual(stop_shape("Official Timeout", 75.0, 5), "frozen_clock")
        self.assertEqual(stop_shape("Official Timeout", 200.0, 16), "clock_ran")
        self.assertEqual(stop_shape("Two-minute warning", 10.0, 0), "mandatory_two_minute")
        self.assertEqual(place_label(180.0, "frozen_clock"), "frozen_clock")
        self.assertEqual(place_label(180.1, "frozen_clock"), "beyond_180")

    def test_a_night_show_uses_the_one_late_game_and_an_unnamed_afternoon_does_not(self):
        start = datetime.fromisoformat("2026-10-11T20:43:56-04:00")
        end = start + timedelta(hours=4)
        events = [
            {"id": "1", "name": "CLE @ NYJ", "start": datetime.fromisoformat("2026-10-11T17:00:00+00:00"), "away": "CLE", "home": "NYJ"},
            {"id": "2", "name": "BAL @ ATL", "start": datetime.fromisoformat("2026-10-12T00:20:00+00:00"), "away": "BAL", "home": "ATL"},
            {"id": "3", "name": "OTHER", "start": datetime.fromisoformat("2026-10-12T00:30:00+00:00"), "away": "DAL", "home": "NYG"},
        ]
        one = select_game("Sunday night", events[:2], start, end)
        self.assertEqual(one["event_id"], "2")
        several = select_game("Sunday night", events, start, end)
        self.assertEqual(several["reason"], "several_events")
        afternoon = select_game("Sunday afternoon football", events[:2], datetime.fromisoformat("2026-10-11T13:57:00-04:00"), datetime.fromisoformat("2026-10-11T15:19:00-04:00"))
        self.assertEqual(afternoon["reason"], "unnamed_show")
        jets = select_game(
            "Browns at Jets",
            events[:2],
            datetime.fromisoformat("2026-10-11T12:30:00-04:00"),
            datetime.fromisoformat("2026-10-11T16:00:00-04:00"),
        )
        self.assertEqual(jets["event_id"], "1")

    def test_the_catalog_names_the_opener(self):
        self.assertEqual(catalog_show("hush_20260909_213047"), "Patriots at Seahawks")

    def test_a_sealed_holdout_is_refused(self):
        with self.assertRaises(RuntimeError):
            _load_chunks("hush_20260917_205513")


class SlotPlaceTests(unittest.TestCase):
    def test_elapsed_inverts_the_chunk_clock_and_a_hole_is_not_audio(self):
        chunks = [
            {
                "start_elapsed_seconds": 0.0,
                "end_elapsed_seconds": 120.0,
                "started_at": "2026-10-11T20:43:56-04:00",
                "ended_at": "2026-10-11T20:45:56-04:00",
            },
            {
                "start_elapsed_seconds": 120.0,
                "end_elapsed_seconds": 500.0,
                "started_at": "2026-10-11T21:09:07-04:00",
                "ended_at": "2026-10-11T21:15:27-04:00",
            },
        ]
        wall = chunk_wall(chunks, 200.0)
        self.assertEqual(elapsed_at(chunks, wall)["elapsed_s"], 200.0)
        hole = datetime.fromisoformat("2026-10-11T20:50:00-04:00")
        self.assertEqual(elapsed_at(chunks, hole)["clock"], "in_gap")

    def test_a_mark_past_the_end_of_the_game_is_after_it(self):
        self.assertEqual(end_relation(13.0), "at_game_over")
        self.assertEqual(end_relation(181.0), "after_game")
        breaks = [
            {"feed_kind": "End of Game", "delta_s": -10.0, "wall": "2026-10-09T03:00:00+00:00"},
            {"feed_kind": "End of Game", "delta_s": -400.0, "wall": "2026-10-09T03:06:30+00:00"},
        ]
        recovered = recover_game_over(breaks)
        self.assertTrue(recovered["usable"])
        self.assertLess(recovered["spread_s"], 2.0)


class RemainderPlaceTests(unittest.TestCase):
    def test_a_second_just_after_a_commercial_is_after_it(self):
        place = nearest_commercial(12.0, [(0.0, 10.0), (100.0, 110.0)])
        self.assertEqual(place, {"gap_s": 2.0, "side": "after_commercial"})
        self.assertEqual(gap_bin(2.0), "within_2s")
        self.assertEqual(nearest_commercial(5.0, [(0.0, 10.0)])["side"], "overlaps_commercial")

    def test_embed_refuses_a_sealed_holdout(self):
        with self.assertRaises(RuntimeError):
            embed_session("hush_20260917_205513", 2.0, model=None, device=None)


if __name__ == "__main__":
    unittest.main()
