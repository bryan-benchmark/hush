"""Veto the frozen mute with a voice window that has already ended.

The match is the published ECAPA cosine, 0.25, from the NFL75_PROTECT_001
cache. A window ending at T can affect a decision only at T or later. The
current rule is the one-second hop: T protects through T+1. The tail rule
protects through T+2. No threshold is fit. Prime is a regression read.

The frozen checkpoint and the live television are not touched.
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
OUT = Path(r"C:\OHushData\gpu_lab\audio_learn\voice_hold")
LINE = 0.25
HOLDS = {"current_1s": 1.0, "tail_2s": 2.0}
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


def _hot_ends(session: str) -> np.ndarray:
    data = np.load(ECAPA / f"{session}.npz")
    with np.errstate(invalid="ignore"):
        best = np.nanmax(data["people"], axis=1)
    ends = data["end"]
    order = np.argsort(ends)
    ends = ends[order]
    best = best[order]
    hot = np.isfinite(best) & (best >= LINE)
    return ends[hot]


def _veto(times: np.ndarray, probabilities: np.ndarray, hot_ends: np.ndarray, hold_s: float) -> np.ndarray:
    """Zero a probability when a hot window ended inside (t - hold, t]."""
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


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    report = {"line": LINE, "controller": CONTROLLER, "holds_s": HOLDS, "runs": {}}
    for name, hold in (("frozen", None), *HOLDS.items()):
        games = []
        reviewed_games = []
        focus = {}
        for session in SESSIONS:
            prediction = np.load(FROZEN / f"{session}.npz")
            times = prediction["t"]
            scores = prediction["p"].astype(np.float64)
            if hold is not None:
                scores = _veto(times, scores, _hot_ends(session), hold)
            games.append(_round(_score_array(session, times, scores)))
            games[-1]["session"] = session
            reviewed_games.append(_round(_score_array(session, times, scores, _reviewed_intervals(session))))
            reviewed_games[-1]["session"] = session
            focus[session] = _focus(session, times, scores)
        report["runs"][name] = {"original_gold": games, "reviewed_boundaries": reviewed_games, "focus_covered_s": focus}
        print(name, flush=True)
        for game in games:
            print(
                f"  {game['session']} coverage {game['commercial_coverage']:.3f} "
                f"program {game['program_covered_s']:.1f}s "
                f"rate {game['false_mutes_per_hour']:.2f}/h "
                f"longest {game['longest_false_mute_s']:.1f}s "
                f"delay {game['median_start_delay_s']}",
                flush=True,
            )
        print("  focus", focus, flush=True)
    (OUT / "result.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("wrote", OUT / "result.json", flush=True)


if __name__ == "__main__":
    main()
