"""Chronological AST mute. Fit on earlier games, score the next game once.

The vectors are the cached AudioSet AST windows. This script does not
re-embed, does not rewrite NEED.json, and does not change the live mute.
October games are scored with the September rule. They are not used to
move the cutoff. Sealed holdouts are not opened.

The cutoff is one step above the highest score that touches program audio
in the games already fit. A later game that still loses a program second
is a broken run and has no accuracy.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
from sklearn.linear_model import LogisticRegression

from tools.gpu_lab.decisions import playback_from_scores
from tools.gpu_lab.ladder import pairs, score_mask
from tools.gpu_lab.learning_net.data import bridge_masks, load_cache

OUT = REPO / "docs" / "ohush" / "research" / "WALKFORWARD_AST_001"
WINDOW_S = 10.0
REDZONE = "hush_20260913_150934"
FOOTBALL = (
    ("hush_20260909_213047", "Sept 9 NBC"),
    ("hush_20260913_210542", "Sept 13 NBC"),
    ("hush_20260914_212529", "Sept 14 ESPN"),
    ("hush_20260924_220624", "Sept 24 Prime"),
    ("hush_20261008_205100", "Oct 8 Prime Video"),
    ("hush_20261010_222400", "Oct 10 cable"),
    ("hush_20261011_135700", "Oct 11 afternoon"),
    ("hush_20261011_204300", "Oct 11 night"),
    ("hush_20261012_204200", "Oct 12 MNF"),
)
SEPTEMBER = 4


def _fit(sessions: list[str]) -> LogisticRegression:
    vectors = []
    labels = []
    for session in sessions:
        cache = load_cache(session, WINDOW_S)
        keep = cache["label"] >= 0
        vectors.append(cache["emb"][keep])
        labels.append(cache["label"][keep])
    head = LogisticRegression(max_iter=2000, class_weight="balanced")
    head.fit(np.concatenate(vectors), np.concatenate(labels))
    return head


def _scores(head: LogisticRegression, session: str) -> tuple[np.ndarray, np.ndarray]:
    cache = load_cache(session, WINDOW_S)
    logits = np.asarray(head.decision_function(cache["emb"]), dtype=np.float64)
    return cache["t"], logits


def _program_ceiling(mask: dict, times: np.ndarray, scores: np.ndarray) -> float | None:
    program = pairs(mask, "verified_program")
    ceiling = None
    for moment, score in zip(times, scores):
        end = float(moment) + 1.0
        if any(min(end, stop) - max(float(moment), start) > 1e-9 for start, stop in program):
            ceiling = float(score) if ceiling is None else max(ceiling, float(score))
    return ceiling


def _replay(mask: dict, times: np.ndarray, scores: np.ndarray, threshold: float) -> dict:
    coverage = pairs(mask, "coverage")[0]
    playback = playback_from_scores(coverage, times.tolist(), scores.tolist(), threshold)
    scored = score_mask(mask, playback)
    return {
        "session": mask["session"],
        "commercial_held_s": scored["commercial_held_s"],
        "program_cut_s": scored["program_cut_s"],
        "false_cover_incidents": scored["false_cover_incidents"],
        "broken": scored["broken"],
        "accuracy": scored.get("accuracy"),
    }


def main() -> None:
    masks = bridge_masks()
    steps = []
    for index in range(1, len(FOOTBALL)):
        test_id, test_name = FOOTBALL[index]
        # October does not move the cutoff. The fit stays the four September games.
        fit_ids = [sid for sid, _name in FOOTBALL[: min(index, SEPTEMBER)]]
        head = _fit(fit_ids)
        ceilings = []
        for sid in fit_ids:
            times, scores = _scores(head, sid)
            ceilings.append(_program_ceiling(masks[sid], times, scores))
        if any(value is None for value in ceilings):
            raise SystemExit(f"a fit game has no program scores: {fit_ids}")
        ceiling = max(value for value in ceilings if value is not None)
        threshold = math.nextafter(ceiling, math.inf)
        test_times, test_scores = _scores(head, test_id)
        red_times, red_scores = _scores(head, REDZONE)
        step = {
            "test": test_id,
            "test_name": test_name,
            "fit": fit_ids,
            "october_in_fit": False,
            "threshold": threshold,
            "test_score": _replay(masks[test_id], test_times, test_scores, threshold),
            "redzone": _replay(masks[REDZONE], red_times, red_scores, threshold),
        }
        steps.append(step)
        print(
            f"{test_name} held {step['test_score']['commercial_held_s']} "
            f"program {step['test_score']['program_cut_s']} "
            f"redzone program {step['redzone']['program_cut_s']}",
            flush=True,
        )

    clean = [step for step in steps if not step["test_score"]["broken"] and not step["redzone"]["broken"]]
    payload = {
        "id": "WALKFORWARD_AST_001",
        "model": "MIT/ast-finetuned-audioset-10-10-0.4593",
        "window_s": WINDOW_S,
        "head": "logistic regression, class_weight balanced, earlier games only",
        "threshold": "one step above the highest program-overlapping logit in the fit games",
        "october_may_choose_cutoff": False,
        "live_mute_changed": False,
        "steps": steps,
        "steps_with_zero_program_on_the_test_and_redzone": len(clean),
        "v1_baseline_commercial_held_s": 25.0,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT / 'results.json'}", flush=True)


if __name__ == "__main__":
    main()
