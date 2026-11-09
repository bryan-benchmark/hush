"""Hysteresis controller. The operating point is chosen on the calibration game only."""

from __future__ import annotations

from experiments.audio_learn.splits import (
    OFF_STREAKS,
    OFF_THRESHOLDS,
    ON_STREAKS,
    ON_THRESHOLDS,
)
from experiments.nfl75.score import ScoreError, playback_from_decisions, score_product


def decisions(
    times: list[float],
    probabilities: list[float],
    on: float,
    off: float,
    on_streak: int,
    off_streak: int,
) -> list[dict]:
    """Cover after `on_streak` hot decisions. Return after `off_streak` cold ones.

    The action at time t may use probabilities at t and earlier. It does not
    use a later probability, and it does not cover audio from before t.
    """
    if off >= on:
        raise ValueError("the return threshold must sit below the cover threshold")
    if on_streak < 1 or off_streak < 1:
        raise ValueError("streaks must be at least one decision")
    if len(times) != len(probabilities):
        raise ValueError("each decision needs one probability")
    state = "play"
    hot = 0
    cold = 0
    rows = []
    previous = None
    for moment, probability in zip(times, probabilities):
        moment = float(moment)
        probability = float(probability)
        if previous is not None and moment <= previous:
            raise ValueError("decision time did not advance")
        previous = moment
        if state == "play":
            hot = hot + 1 if probability >= on else 0
            if hot >= on_streak:
                state = "cover"
                cold = 0
        else:
            cold = cold + 1 if probability <= off else 0
            if cold >= off_streak:
                state = "play"
                hot = 0
        rows.append(
            {
                "clock": "capture",
                "available_at": moment,
                "evidence_through": moment,
                "action": "cover" if state == "cover" else "play",
                "probability": probability,
            }
        )
    return rows


def grid() -> list[dict]:
    rows = []
    for on in ON_THRESHOLDS:
        for off in OFF_THRESHOLDS:
            if off >= on:
                continue
            for on_streak in ON_STREAKS:
                for off_streak in OFF_STREAKS:
                    rows.append(
                        {
                            "on": on,
                            "off": off,
                            "on_streak": on_streak,
                            "off_streak": off_streak,
                        }
                    )
    return rows


def assignment_pass(metrics: dict, recovery: float) -> bool:
    coverage = metrics.get("commercial_coverage")
    rate = metrics.get("false_mutes_per_hour")
    longest = metrics.get("longest_false_mute_s")
    if not metrics.get("evaluable"):
        return False
    if coverage is None or coverage < 0.75:
        return False
    if rate is None or rate >= 1.0:
        return False
    if longest is None or longest >= 10.0:
        return False
    if recovery < 1.0:
        return False
    return True


def recovery_rate(spans, coverage_end: float) -> float:
    covers = [span for span in spans if span.state == "covered"]
    if not covers:
        return 1.0
    recovered = sum(1 for span in covers if span.end < coverage_end - 1e-3)
    return recovered / len(covers)


def select_controller(coverage: tuple[float, float], intervals, times, probabilities, wall_gap_s: float, excluded) -> dict:
    """Pick one predeclared setting from the calibration game.

    Passing the assignment gate wins, and among passers the higher commercial
    coverage wins. If none pass, the published choice is the one with the
    shortest longest false mute, then the lower false-mute rate, then the
    higher coverage. A higher cover threshold breaks remaining ties.
    """
    ranked = []
    for setting in grid():
        rows = decisions(list(times), list(probabilities), **setting)
        try:
            spans = playback_from_decisions(coverage, rows)
        except ScoreError as exc:
            raise RuntimeError(f"controller produced an illegal timeline: {exc}") from exc
        scored = score_product(
            coverage,
            intervals,
            spans,
            session="calibration",
            excluded_ranges=excluded,
            wall_gap_s=wall_gap_s,
            audio_present=True,
        )
        recovery = recovery_rate(spans, coverage[1])
        ranked.append(
            {
                **setting,
                "commercial_coverage": scored["commercial_coverage"],
                "false_mutes_per_hour": scored["false_mutes_per_hour"],
                "longest_false_mute_s": scored["longest_false_mute_s"],
                "program_hidden_per_hour": scored["program_hidden_per_hour"],
                "false_mute_episodes": scored["false_mute_episodes"],
                "recovery": recovery,
                "assignment_pass": assignment_pass(scored, recovery),
                "nfl75_pass": bool(scored["acceptance"]["pass"]) and recovery >= 1.0,
            }
        )
    if not ranked:
        raise RuntimeError("the controller grid is empty")

    def sort_key(row: dict) -> tuple:
        coverage_value = -1.0 if row["commercial_coverage"] is None else float(row["commercial_coverage"])
        rate = 1e9 if row["false_mutes_per_hour"] is None else float(row["false_mutes_per_hour"])
        longest = 1e9 if row["longest_false_mute_s"] is None else float(row["longest_false_mute_s"])
        if row["assignment_pass"]:
            return (0, -coverage_value, rate, longest, -row["on"], row["off"])
        return (1, longest, rate, -coverage_value, -row["on"], row["off"])

    ranked.sort(key=sort_key)
    return {
        "chosen": ranked[0],
        "grid": ranked,
        "rule": "assignment gate, then coverage; else shortest false mute",
    }
