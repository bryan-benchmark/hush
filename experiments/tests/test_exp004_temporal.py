"""Exp004 clock and peak listing. The commercial ledger is not used."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from hush.temporal import (  # noqa: E402
    TOLERANCE_S,
    autocorr,
    exceed_mask,
    gaps,
    grid_residual,
    jump_score,
    nearest_mark,
    on_spot_clock,
    peak_times,
    POD_S,
    SPOT_S,
)


def _blocks(n_blocks: int, length: int = 15, dim: int = 4) -> tuple[np.ndarray, np.ndarray]:
    ends = np.arange(n_blocks * length, dtype=np.float64)
    embeddings = np.zeros((ends.size, dim))
    for block in range(n_blocks):
        embeddings[block * length : (block + 1) * length, block % dim] = 1.0
    return ends, embeddings


class Temporal(unittest.TestCase):
    def test_jump_is_zero_inside_a_block_and_one_across_a_cut(self):
        ends, embeddings = _blocks(4)
        jumps = jump_score(ends, embeddings)
        self.assertTrue(np.allclose(jumps[10:15], 0.0))
        self.assertTrue(np.allclose(jumps[15:25], 1.0))

    def test_a_step_is_listed_once_at_its_start(self):
        ends, embeddings = _blocks(8, length=120)
        jumps = jump_score(ends, embeddings)
        hits = exceed_mask(ends, jumps)
        fired = peak_times(ends, jumps, hits)
        self.assertGreater(len(fired), 2)
        self.assertTrue(all(t % 120 == 0 for t in fired))
        self.assertTrue(all(gap >= 12.0 for gap in gaps(fired)))

    def test_future_jumps_do_not_move_an_earlier_peak(self):
        ends, embeddings = _blocks(8, length=120)
        jumps = jump_score(ends, embeddings)
        fired = peak_times(ends, jumps, exceed_mask(ends, jumps))
        jumps[500:] = 5.0
        later = peak_times(ends, jumps, exceed_mask(ends, jumps))
        self.assertEqual(later[0], fired[0])

    def test_clock_tolerance_is_three_seconds(self):
        self.assertEqual(TOLERANCE_S, 3.0)
        mark, error, hit = nearest_mark(122.0, POD_S)
        self.assertEqual(mark, 120.0)
        self.assertTrue(hit)
        mark, error, hit = nearest_mark(140.0, POD_S)
        self.assertFalse(hit)
        self.assertTrue(on_spot_clock(15.5))
        self.assertFalse(on_spot_clock(20.0))
        self.assertEqual(SPOT_S, (15.0, 30.0, 60.0))

    def test_grid_residual_is_zero_on_a_multiple_of_15(self):
        self.assertAlmostEqual(grid_residual(30.0), 0.0)
        self.assertAlmostEqual(grid_residual(33.0), 3.0)
        self.assertAlmostEqual(abs(grid_residual(7.0)), 7.0)

    def test_autocorr_of_a_15_second_pulse_peaks_at_15(self):
        scores = np.zeros(400)
        scores[::15] = 1.0
        at_15 = autocorr(scores, 15)
        at_7 = autocorr(scores, 7)
        self.assertGreater(at_15, at_7)
