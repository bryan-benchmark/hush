"""Accuracy ladder for one causal replay.

A muted second of the game breaks the run. A broken run has no accuracy.
On a clean run, corpus accuracy is commercial seconds held divided by the
published football commercial duration. Median delay is reported beside that
fraction and does not replace it.
"""

from __future__ import annotations

from experiments.measurement.metrics import Interval, Span, score_timeline

from tools.gpu_lab.splits import FOOTBALL_COMMERCIAL_S


def delay_ceiling(commercials: list[tuple[float, float]], delay_s: float) -> dict:
    """Coverage if every break is caught after `delay_s` and every return is perfect."""
    if delay_s < 0:
        raise ValueError("delay must be non-negative")
    total = sum(end - start for start, end in commercials)
    heard = sum(min(delay_s, end - start) for start, end in commercials)
    held = total - heard
    return {
        "delay_s": delay_s,
        "commercials": len(commercials),
        "commercial_s": round(total, 3),
        "heard_s": round(heard, 3),
        "held_s": round(held, 3),
        "held_fraction": None if total <= 0 else round(held / total, 6),
    }


def pairs(mask: dict, key: str) -> list[tuple[float, float]]:
    return [(float(start), float(end)) for start, end in mask[key]]


def playback_from_states(spans: list[tuple[float, float, str]]) -> list[Span]:
    return [Span(start=start, end=end, state=state) for start, end, state in spans]


def intervals_from_mask(mask: dict) -> list[Interval]:
    rows = []
    for start, end in pairs(mask, "verified_commercial"):
        rows.append(Interval(start, end, "commercial", "mute", "certain"))
    for start, end in pairs(mask, "verified_program"):
        rows.append(Interval(start, end, "program", "play", "certain"))
    for start, end in pairs(mask, "excluded"):
        rows.append(Interval(start, end, "boundary", "unsure", "unsure"))
    return rows


def score_mask(mask: dict, playback: list[Span]) -> dict:
    coverage = pairs(mask, "coverage")
    if len(coverage) != 1:
        raise RuntimeError(f"{mask['session']} needs one coverage span to score, found {len(coverage)}")
    raw = score_timeline(coverage[0], intervals_from_mask(mask), playback)
    broken = raw["program_covered_s"] > 0
    held = raw["commercial_covered_s"]
    target = raw["target_commercial_s"]
    return {
        "session": mask["session"],
        "broken": broken,
        "accuracy": None if broken or target <= 0 else round(held / target, 6),
        "corpus_accuracy": None if broken else round(held / FOOTBALL_COMMERCIAL_S, 6),
        "commercial_held_s": held,
        "commercial_heard_s": raw["commercial_heard_s"],
        "program_cut_s": raw["program_covered_s"],
        "false_cover_incidents": raw["false_cover_incidents"],
        "start_delay_median_s": raw["start_delay_median_s"],
        "starts": raw["starts"],
        "starts_missed": raw["starts_missed"],
    }


def play_all(mask: dict) -> list[Span]:
    start, end = pairs(mask, "coverage")[0]
    return [Span(start=start, end=end, state="program")]
