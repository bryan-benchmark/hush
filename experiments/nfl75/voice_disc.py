"""Declared scoring checks. The 0.25 line is not moved, and 0.15 is not searched.

`margin` withholds a name when the runner-up is closer than 0.15. That gap
was fixed before this run from the separation already used to describe a
stable winner. Symmetric s-norm recenters a cosine against other speakers.
It does not receive a new accept line.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from hush.speaker_memory import MATCH_COSINE

from experiments.nfl75.voice_id import identify

# Fixed before any clip in this experiment was counted. Not a sweep.
MARGIN = 0.15


def max_over_references(probe: np.ndarray, grouped: dict[str, list[np.ndarray]]) -> dict[str, float]:
    """Closest single reference, not the average of them."""
    scores = {}
    for name, vectors in grouped.items():
        if not vectors:
            continue
        scores[name] = max(float(probe @ np.asarray(vector, dtype=np.float64)) for vector in vectors)
    return scores


def _mean_std(values: list[float]) -> tuple[float, float]:
    if len(values) < 2:
        raise ValueError("a cohort needs two other-speaker scores")
    array = np.asarray(values, dtype=np.float64)
    sigma = float(array.std())
    if sigma < 1e-6:
        sigma = 1e-6
    return float(array.mean()), sigma


def symmetric_snorm(score: float, enroll_vs_cohort: list[float], test_vs_cohort: list[float]) -> float:
    """Half the sum of the two cohort z-scores. No new threshold lives here."""
    enroll_mean, enroll_std = _mean_std(enroll_vs_cohort)
    test_mean, test_std = _mean_std(test_vs_cohort)
    return 0.5 * ((score - enroll_mean) / enroll_std + (score - test_mean) / test_std)


def margin_decision(scores: dict[str, float], *, line: float = MATCH_COSINE, margin: float = MARGIN) -> dict:
    """Unknown unless the frozen line passes and the runner-up is 0.15 behind."""
    if margin != MARGIN or line != MATCH_COSINE:
        raise ValueError("the margin stays at 0.15 and the line stays at 0.25")
    base = identify(scores, line)
    gap = None
    if base["best"] is not None and base["second"] is not None:
        gap = float(base["best"]) - float(base["second"])
    if base["accepted"] is None:
        reason = "below_line"
        accepted = None
    elif gap is None or gap + 1e-9 < margin:
        reason = "thin_margin"
        accepted = None
    else:
        reason = "separated"
        accepted = base["accepted"]
    return {
        "accepted": accepted,
        "rank1": base["rank1"],
        "best": base["best"],
        "second": base["second"],
        "margin": None if gap is None else gap,
        "reason": reason,
    }
