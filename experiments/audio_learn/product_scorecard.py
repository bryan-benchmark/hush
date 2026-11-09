"""Product scorecard: play broadcast / mute non_broadcast.

Every keep/reject must use these cells. Original gold is diagnostic only.
Writes raw receipts so the grade cannot hide scrap inside desk FP.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from experiments.audio_learn.controller import decisions
from experiments.audio_learn.splits import EVAL
from experiments.audio_learn.studio_fit import CONTROLLER, DESK_SPANS, _overlap
from experiments.measurement.metrics import Interval
from experiments.nfl75.inventory import coverage_by_session, excluded_ranges, wall_gaps
from experiments.nfl75.score import playback_from_decisions, score_product

DATA = Path(r"C:\OHushData\gpu_lab\audio_learn")
FROZEN = DATA / "predictions" / "frozen"
LABELS = DATA / "broadcast_labels" / "labels_accepted.jsonl"
OUT = DATA / "product_scorecard"

FOCUS = {
    "hush_20260924_220624": {
        "odell": (7035.0, 7095.2),
        "whitworth": (7406.8, 7436.2),
        "palmer": (6180.7, 6207.8),
        "chilis": (2969.8, 3006.5),
    },
    "hush_20261008_205100": {
        "amex": (3384.3, 3437.1),
        "welcome_back": (3437.1, 3443.0),
    },
}


def load_accepted() -> list[dict]:
    return [json.loads(line) for line in LABELS.read_text(encoding="utf-8").splitlines() if line]


def non_broadcast_intervals(session: str, accepted: list[dict] | None = None) -> list[Interval]:
    accepted = accepted if accepted is not None else load_accepted()
    rows = [r for r in accepted if r["session"] == session and r["bucket"] == "non_broadcast"]
    return [
        Interval(
            start=float(r["start_s"]),
            end=float(r["end_s"]),
            event_class="commercial",
            desired_action="mute",
            confidence=str(r.get("confidence") or "high"),
        )
        for r in rows
    ]


def broadcast_rows(session: str, accepted: list[dict] | None = None) -> list[dict]:
    accepted = accepted if accepted is not None else load_accepted()
    return [r for r in accepted if r["session"] == session and r["bucket"] == "broadcast"]


def _ol(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def _playback_spans(session: str, times: np.ndarray, probs: np.ndarray):
    coverage = coverage_by_session()[session]
    rows = decisions(times.tolist(), probs.tolist(), **CONTROLLER)
    return playback_from_decisions(coverage, rows)


def score_product_ontology(session: str, times: np.ndarray, probs: np.ndarray, accepted: list[dict] | None = None) -> dict:
    """Score mute against non_broadcast; peel false-mute seconds into cells."""
    accepted = accepted if accepted is not None else load_accepted()
    intervals = non_broadcast_intervals(session, accepted)
    coverage = coverage_by_session()[session]
    spans = _playback_spans(session, times, probs)
    scored = score_product(
        coverage,
        intervals,
        spans,
        session=session,
        excluded_ranges=excluded_ranges(session, intervals),
        wall_gap_s=wall_gaps().get(session, 0.0),
        audio_present=True,
    )
    brows = broadcast_rows(session, accepted)
    desks = DESK_SPANS.get(session, [])
    cells = {
        "desk_s": 0.0,
        "show_return_s": 0.0,
        "other_broadcast_s": 0.0,
        "unlabeled_program_s": 0.0,
    }
    episode_receipts = []
    for ep in scored["episodes"]:
        a0, a1 = float(ep["start_s"]), float(ep["end_s"])
        dur = float(ep["duration_s"])
        desk_ol = sum(_ol(a0, a1, x, y) for x, y in desks)
        ret_ol = sum(
            _ol(a0, a1, float(r["start_s"]), float(r["end_s"]))
            for r in brows
            if r.get("kind") == "show_return"
        )
        other_ol = sum(
            _ol(a0, a1, float(r["start_s"]), float(r["end_s"]))
            for r in brows
            if r.get("kind") != "show_return"
        )
        # prefer desk attribution when both
        desk_part = min(dur, desk_ol)
        rem = max(0.0, dur - desk_part)
        ret_part = min(rem, ret_ol)
        rem2 = max(0.0, rem - ret_part)
        # other broadcast not already in desk
        other_part = min(rem2, max(0.0, other_ol - desk_ol))
        unlab = max(0.0, rem2 - other_part)
        cells["desk_s"] += desk_part
        cells["show_return_s"] += ret_part
        cells["other_broadcast_s"] += other_part
        cells["unlabeled_program_s"] += unlab
        episode_receipts.append(
            {
                "session": session,
                "start_s": round(a0, 3),
                "end_s": round(a1, 3),
                "dur_s": round(dur, 3),
                "desk_s": round(desk_part, 3),
                "show_return_s": round(ret_part, 3),
                "other_broadcast_s": round(other_part, 3),
                "unlabeled_program_s": round(unlab, 3),
            }
        )
    focus = {}
    for name, bounds in FOCUS.get(session, {}).items():
        focus[name] = round(_overlap(spans, [bounds]), 3)
    focus["named_desk_list_s"] = round(_overlap(spans, desks), 3)
    return {
        "session": session,
        "controller": CONTROLLER,
        "non_broadcast_coverage": scored.get("commercial_coverage"),
        "non_broadcast_covered_s": round(float(scored.get("commercial_covered_s") or 0), 3),
        "non_broadcast_s": round(float(scored.get("commercial_s") or 0), 3),
        "broadcast_muted_s": round(float(scored.get("program_covered_s") or 0), 3),
        "false_mute_episodes": scored.get("false_mute_episodes"),
        "longest_false_mute_s": scored.get("longest_false_mute_s"),
        "cells": {k: round(v, 3) for k, v in cells.items()},
        "focus": focus,
        "episodes": episode_receipts,
    }


def aggregate(games: list[dict]) -> dict:
    cov = sum(g["non_broadcast_covered_s"] for g in games)
    tot = sum(g["non_broadcast_s"] for g in games)
    cells = {"desk_s": 0.0, "show_return_s": 0.0, "other_broadcast_s": 0.0, "unlabeled_program_s": 0.0}
    focus = {}
    for g in games:
        for k in cells:
            cells[k] += g["cells"][k]
        focus[g["session"]] = g["focus"]
    return {
        "non_broadcast_coverage": round(cov / tot, 4) if tot else None,
        "non_broadcast_covered_s": round(cov, 1),
        "non_broadcast_s": round(tot, 1),
        "broadcast_muted_s": round(sum(g["broadcast_muted_s"] for g in games), 1),
        "false_mute_episodes": sum(float(g["false_mute_episodes"] or 0) for g in games),
        "longest_false_mute_s": max(float(g["longest_false_mute_s"] or 0) for g in games),
        "cells": {k: round(v, 1) for k, v in cells.items()},
        "focus": focus,
    }


def score_run(name: str, probs_by_session: dict[str, tuple[np.ndarray, np.ndarray]], out_dir: Path) -> dict:
    """probs_by_session: session -> (times, probs). Writes raw receipts under out_dir/name/."""
    accepted = load_accepted()
    dest = out_dir / name
    dest.mkdir(parents=True, exist_ok=True)
    games = []
    for session, (times, probs) in probs_by_session.items():
        game = score_product_ontology(session, times, probs, accepted)
        games.append(game)
        (dest / f"{session}.json").write_text(json.dumps(game, indent=2), encoding="utf-8")
        with (dest / f"{session}_episodes.jsonl").open("w", encoding="utf-8") as fh:
            for ep in game["episodes"]:
                fh.write(json.dumps(ep) + "\n")
    agg = aggregate(games)
    report = {"run": name, "controller": CONTROLLER, "aggregate": agg, "games": games}
    (dest / "aggregate.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\n=== PRODUCT CARD {name} ===", flush=True)
    print(json.dumps(agg, indent=2), flush=True)
    return report


def load_frozen_probs(sessions: tuple[str, ...] = EVAL) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    out = {}
    for session in sessions:
        pred = np.load(FROZEN / f"{session}.npz")
        out[session] = (pred["t"], pred["p"].astype(np.float64))
    return out


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    score_run("frozen_baseline", load_frozen_probs(), OUT)


if __name__ == "__main__":
    main()
