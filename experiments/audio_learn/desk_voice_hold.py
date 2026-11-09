"""Narrow desk-voice veto on frozen mute — Odell-class probe.

Cast-wide nanmax (voice_hold) freed desks but burned coverage. Atomic Odell
windows fire Whitworth / Clarissa / Gonzalez, not the booth cast. This card
scores name subsets only: force p=0 when a selected enroll cosine is hot,
else frozen. No threshold fit. Live path untouched.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from experiments.audio_learn.studio_fit import CONTROLLER, DESK_SPANS, _overlap, _score_array
from experiments.measurement.metrics import Interval
from experiments.nfl75.inventory import active_intervals

ECAPA = Path(r"c:\Users\faceo\Projects\ohush\docs\ohush\research\NFL75_PROTECT_001\cache")
FROZEN = Path(r"C:\OHushData\gpu_lab\audio_learn\predictions\frozen")
REVIEWED = Path(r"c:\Users\faceo\Projects\ohush\docs\ohush\research\OHUSH_STUDIO_HEAD_001\reviewed_boundaries.json")
OUT = Path(r"C:\OHushData\gpu_lab\audio_learn\desk_voice_hold")
NAMES = ["Al Michaels", "Kirk Herbstreit", "Clarissa Thompson", "Andrew Whitworth", "Tony Gonzalez"]
LINE = 0.25
HOLD_S = 1.0
FOCUS = {
    "hush_20260924_220624": {
        "palmer": (6180.7, 6207.8),
        "injury": (6267.8, 6287.2),
        "odell": (7035.0, 7095.2),
        "whitworth": (7406.8, 7436.2),
    },
    "hush_20261008_205100": {
        "welcome_back": (3437.1, 3443.0),
    },
}
SESSIONS = ("hush_20260924_220624", "hush_20261008_205100")
PANELS = {
    "frozen": None,
    "whitworth_only": ["Andrew Whitworth"],
    "desk_panel": ["Andrew Whitworth", "Tony Gonzalez"],
    "clarissa_only": ["Clarissa Thompson"],
    "desk_plus_clarissa": ["Andrew Whitworth", "Tony Gonzalez", "Clarissa Thompson"],
    "booth_cast": ["Al Michaels", "Kirk Herbstreit", "Clarissa Thompson"],
    "all_five": list(NAMES),
}


def _hot_ends(session: str, allow: list[str]) -> np.ndarray:
    data = np.load(ECAPA / f"{session}.npz")
    ends = data["end"]
    people = data["people"]
    order = np.argsort(ends)
    ends = ends[order]
    people = people[order]
    idx = [NAMES.index(name) for name in allow]
    with np.errstate(invalid="ignore"):
        best = np.nanmax(people[:, idx], axis=1)
    hot = np.isfinite(best) & (best >= LINE)
    return ends[hot]


def _veto(times: np.ndarray, probabilities: np.ndarray, hot_ends: np.ndarray, hold_s: float) -> np.ndarray:
    right = np.searchsorted(hot_ends, times, side="right")
    left = np.searchsorted(hot_ends, times - hold_s, side="left")
    out = np.array(probabilities, dtype=np.float64, copy=True)
    out[right > left] = 0.0
    return out


def _round(row: dict) -> dict:
    kept = {}
    for key in (
        "commercial_coverage",
        "commercial_covered_s",
        "commercial_s",
        "program_covered_s",
        "false_mute_episodes",
        "false_mutes_per_hour",
        "longest_false_mute_s",
        "recovery",
        "desk_span_covered_s",
    ):
        value = row[key]
        kept[key] = None if value is None else round(float(value), 4)
    delays = [item["start_delay_s"] for item in row["breaks"] if item["start_delay_s"] is not None]
    kept["median_start_delay_s"] = None if not delays else round(float(np.median(delays)), 3)
    kept["breaks_missed"] = sum(1 for item in row["breaks"] if item["missed_break"])
    kept["longest_episodes"] = row["longest_episodes"]
    return kept


def _reviewed_intervals(session: str) -> list[Interval]:
    extra = json.loads(REVIEWED.read_text(encoding="utf-8"))["commercials"]
    intervals = list(active_intervals(session))
    for row in extra:
        if row["session"] != session:
            continue
        intervals.append(
            Interval(
                start=float(row["start_s"]),
                end=float(row["end_s"]),
                event_class="commercial",
                desired_action="mute",
                confidence="reviewed",
            )
        )
    return intervals


def _focus(session: str, times: np.ndarray, probabilities: np.ndarray) -> dict:
    from experiments.audio_learn.controller import decisions
    from experiments.nfl75.inventory import coverage_by_session
    from experiments.nfl75.score import playback_from_decisions

    coverage = coverage_by_session()[session]
    spans = playback_from_decisions(coverage, decisions(times.tolist(), probabilities.tolist(), **CONTROLLER))
    found = {}
    for name, bounds in FOCUS.get(session, {}).items():
        found[name] = round(_overlap(spans, [bounds]), 3)
    found["named_desk_list_s"] = round(_overlap(spans, DESK_SPANS.get(session, [])), 3)
    return found


def _agg(games: list[dict]) -> dict:
    cov_s = sum(g["commercial_covered_s"] for g in games)
    com_s = sum(g["commercial_s"] for g in games)
    return {
        "commercial_coverage": round(cov_s / com_s, 4) if com_s else None,
        "commercial_covered_s": round(cov_s, 1),
        "program_covered_s": round(sum(g["program_covered_s"] for g in games), 1),
        "false_mute_episodes": sum(g["false_mute_episodes"] for g in games),
        "longest_false_mute_s": max(g["longest_false_mute_s"] for g in games),
        "desk_span_covered_s": round(sum(g["desk_span_covered_s"] for g in games), 1),
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    report = {"line": LINE, "hold_s": HOLD_S, "controller": CONTROLLER, "panels": {}, "runs": {}}
    for panel, allow in PANELS.items():
        games = []
        reviewed_games = []
        focus = {}
        hot_counts = {}
        for session in SESSIONS:
            prediction = np.load(FROZEN / f"{session}.npz")
            times = prediction["t"]
            scores = prediction["p"].astype(np.float64)
            if allow is not None:
                hot = _hot_ends(session, allow)
                hot_counts[session] = int(hot.size)
                scores = _veto(times, scores, hot, HOLD_S)
            else:
                hot_counts[session] = 0
            games.append(_round(_score_array(session, times, scores)))
            games[-1]["session"] = session
            reviewed_games.append(_round(_score_array(session, times, scores, _reviewed_intervals(session))))
            reviewed_games[-1]["session"] = session
            focus[session] = _focus(session, times, scores)
        report["panels"][panel] = allow
        report["runs"][panel] = {
            "hot_window_ends": hot_counts,
            "original_gold": games,
            "reviewed_boundaries": reviewed_games,
            "focus_covered_s": focus,
            "aggregate": _agg(games),
        }
        print(panel, "AGG", report["runs"][panel]["aggregate"], flush=True)
        print("  focus", focus, flush=True)
    (OUT / "result.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("wrote", OUT / "result.json", flush=True)


if __name__ == "__main__":
    main()
