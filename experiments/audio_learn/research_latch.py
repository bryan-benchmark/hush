"""Accepted research latches on the product scorecard.

KEEP stack (receipts 2026-11-09):
  1) cooldown_8s after accepted non_broadcast ends
  2) cover-only voice OR:
       Clarissa Thompson margin>=0.10
       OR Andrew Whitworth margin>=0.15
       OR James Palmer margin>=0.15
       OR Ryan Fitzpatrick margin>=0.15
     Clarissa/Whit: odell_residual/asymmetric
     Palmer: palmer_cover_latch enroll 6220–6235 (before injury)
     Fitz: fitz_cover_latch (deep 6599 + Oct clear enroll); Odell −10s; cum cov −1.92pt

REJECT:
  whitworth anytime; equal-margin whit∪clarissa m0.10; Gonzalez alone / m0.15 on stack;
  Palmer enroll from 6180 intro (not Palmer to ECAPA);
  Al Michaels m0.15 on full stack (cum cov −2.71pt > 0.02);
  Fitz m0.10 on stack (cum cov −2.05pt > 0.02)

Research playback only. Does not touch ohush_live.
Palmer/Fitz cosines live in side caches (not the 5-name ECAPA people matrix).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from experiments.audio_learn.boundary_recovery import apply_cooldown
from experiments.audio_learn.controller import decisions
from experiments.audio_learn.desk_voice_hold import ECAPA, HOLD_S, LINE, NAMES
from experiments.audio_learn.product_scorecard import DATA, load_accepted
from experiments.audio_learn.studio_fit import CONTROLLER

COOLDOWN_S = 8.0
VOICE_PANELS = (
    ("Clarissa Thompson", 0.10),
    ("Andrew Whitworth", 0.15),
)
PALMER_MARGIN = 0.15
FITZ_MARGIN = 0.15
PALMER_CACHE = DATA / "palmer_cover_latch"
FITZ_CACHE = DATA / "fitz_cover_latch"
STATUS = "KEEP_RESEARCH_STACK"
RECEIPTS = (
    Path(r"C:\OHushData\gpu_lab\audio_learn\product_latch_card\KEEP_REJECT.md"),
    Path(r"C:\OHushData\gpu_lab\audio_learn\odell_cover_cast\KEEP_REJECT.md"),
    Path(r"C:\OHushData\gpu_lab\audio_learn\odell_residual\KEEP_REJECT.md"),
    Path(r"C:\OHushData\gpu_lab\audio_learn\odell_residual\asymmetric\SUMMARY.json"),
    Path(r"C:\OHushData\gpu_lab\audio_learn\palmer_cover_latch\KEEP_REJECT.md"),
    Path(r"C:\OHushData\gpu_lab\audio_learn\fitz_cover_latch\KEEP_REJECT.md"),
    Path(r"C:\OHushData\gpu_lab\audio_learn\research_stack_verify\extra_voice_probe\KEEP_REJECT.md"),
)


def non_broadcast_ends(session: str) -> list[tuple[float, float]]:
    accepted = load_accepted()
    return [
        (float(r["start_s"]), float(r["end_s"]))
        for r in accepted
        if r["session"] == session and r["bucket"] == "non_broadcast"
    ]


def _voice_hot_ends(session: str, name: str, margin: float) -> np.ndarray:
    path = ECAPA / f"{session}.npz"
    if not path.is_file():
        return np.array([], dtype=float)
    data = np.load(path)
    ends = data["end"]
    people = data["people"]
    order = np.argsort(ends)
    ends = ends[order]
    people = people[order]
    wi = NAMES.index(name)
    w = people[:, wi].astype(np.float64)
    mask = np.ones(people.shape[1], dtype=bool)
    mask[wi] = False
    with np.errstate(invalid="ignore"):
        others = np.nanmax(people[:, mask], axis=1)
    hot = np.isfinite(w) & (w >= LINE) & ((w - np.nan_to_num(others, nan=-1.0)) >= margin)
    return ends[hot]


def _side_hot_ends(session: str, cache: Path, key: str, margin: float) -> np.ndarray:
    path = cache / f"{session}_{key}.npz"
    if not path.is_file():
        return np.array([], dtype=float)
    data = np.load(path)
    ends = data["end"]
    score = data[key].astype(np.float64)
    people5 = data["people5"].astype(np.float64)
    order = np.argsort(ends)
    ends = ends[order]
    score = score[order]
    people5 = people5[order]
    with np.errstate(invalid="ignore"):
        rival = np.nanmax(people5, axis=1)
    hot = np.isfinite(score) & (score >= LINE) & ((score - np.nan_to_num(rival, nan=-1.0)) >= margin)
    return ends[hot]


def _panel_hot_ends(session: str) -> np.ndarray:
    parts = [_voice_hot_ends(session, name, margin) for name, margin in VOICE_PANELS]
    parts.append(_side_hot_ends(session, PALMER_CACHE, "palmer", PALMER_MARGIN))
    parts.append(_side_hot_ends(session, FITZ_CACHE, "fitz", FITZ_MARGIN))
    parts = [p for p in parts if p.size]
    if not parts:
        return np.array([], dtype=float)
    return np.unique(np.concatenate(parts))


def apply_research_latch(
    session: str,
    times: np.ndarray,
    probs: np.ndarray,
    *,
    with_voice: bool = True,
) -> np.ndarray:
    """Cooldown_8s, then cover-only Clarissa∪Whitworth∪Palmer∪Fitz asymmetric margins."""
    out = apply_cooldown(times, np.asarray(probs, dtype=np.float64), non_broadcast_ends(session), COOLDOWN_S)
    if not with_voice:
        return out
    rows = decisions(times.tolist(), out.tolist(), **CONTROLLER)
    covering = np.array([r["action"] == "cover" for r in rows], dtype=bool)
    hot = _panel_hot_ends(session)
    right = np.searchsorted(hot, times, side="right")
    left = np.searchsorted(hot, times - HOLD_S, side="left")
    out = np.array(out, dtype=np.float64, copy=True)
    out[covering & (right > left)] = 0.0
    return out
