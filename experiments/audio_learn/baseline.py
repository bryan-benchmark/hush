"""Replay the locked NBC logistic. The lines are not moved."""

from __future__ import annotations

from experiments.measurement.metrics import Span
from experiments.nfl75.persist import PERSIST_SECONDS, _logits, nbc_lines, playback


def locked_lines() -> dict:
    return nbc_lines()


def locked_persist_playback(session: str, coverage: tuple[float, float], lines: dict) -> tuple[list[Span], dict]:
    """10-second hold at the published NBC start line, return at the published clear-program line."""
    head = lines["head"]
    times, scores, _labels = _logits(head, session)
    spans = playback(
        coverage,
        [float(moment) for moment in times],
        [float(score) for score in scores],
        persist_s=PERSIST_SECONDS[0],
        start_line=lines["start_line"],
        return_line=lines["return_line"],
    )
    meta = {
        "name": "locked_nbc_logistic_persist_10s",
        "start_line": lines["start_line"],
        "return_line": lines["return_line"],
        "persist_s": PERSIST_SECONDS[0],
        "return_persist_s": 3.0,
        "fit_sessions": ["hush_20260909_213047", "hush_20260913_210542"],
        "retuned": False,
    }
    return spans, meta
