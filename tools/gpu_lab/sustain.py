"""A later head: mute only after several past seconds agree.

Bridge 0's one-second score leaves the ESPN game on and hides later games.
On the training broadcasts the program seconds that clear that cutoff are one
or two seconds long. This head takes the minimum of the last 2, 3, 4, or 5
decision scores, locks the cutoff on ESPN, and does not put the rejected
one-second head back in the contest.
"""

from __future__ import annotations

import json
from pathlib import Path

import joblib

from tools.gpu_lab.decisions import (
    lock_threshold,
    playback_from_scores,
    pod_losses,
    program_incidents,
    sustained_scores,
)
from tools.gpu_lab.eligibility import build_masks
from tools.gpu_lab.embed import MODEL_ID
from tools.gpu_lab.ladder import pairs, score_mask
from tools.gpu_lab.prepare import DATA_ROOT
from tools.gpu_lab.score import _load_rows, _public_development, _sum_causes
from tools.gpu_lab.splits import CALIBRATE, CONTROL, DEVELOP, WINDOW_S
from tools.gpu_lab.train import model_path

SUSTAIN_S = (2, 3, 4, 5)


def _replay_scores(mask: dict, times: list[float], scores: list[float], threshold: float) -> dict:
    coverage = pairs(mask, "coverage")[0]
    playback = playback_from_scores(coverage, times, scores, threshold)
    return {
        "score": score_mask(mask, playback),
        "pods": pod_losses(pairs(mask, "verified_commercial"), playback),
        "incidents": program_incidents(pairs(mask, "verified_program"), playback),
    }


def _examples(session: str, replay: dict) -> list[dict]:
    ranked = sorted(
        replay["pods"],
        key=lambda row: row["missed_s"] + row["late_start_s"] + row["early_unmute_s"],
        reverse=True,
    )
    chosen = []
    for row in ranked[:5]:
        if row["missed_s"] + row["late_start_s"] + row["early_unmute_s"] <= 0:
            continue
        chosen.append({"session": session, **row})
    for incident in replay["incidents"][:3]:
        chosen.append({"session": session, "cause": "program_mute", **incident})
    return chosen


def score_sustained(root: Path = DATA_ROOT) -> dict:
    sessions = list(CALIBRATE + DEVELOP + CONTROL)
    masks = {row["session"]: row for row in build_masks(sessions)}
    cached: dict[tuple[float, str], tuple[list[float], list[float]]] = {}
    for window in WINDOW_S:
        head = joblib.load(model_path(window, root))
        for session in sessions:
            times, vectors = _load_rows(session, window, root)
            scores = head.predict_proba(vectors)[:, 1]
            cached[(window, session)] = (times.tolist(), scores.tolist())

    candidates = []
    for window in WINDOW_S:
        calibrate = masks[CALIBRATE[0]]
        times, scores = cached[(window, CALIBRATE[0])]
        for sustain in SUSTAIN_S:
            sustained = sustained_scores(times, scores, sustain)
            locked = lock_threshold(calibrate, times, sustained)
            candidates.append(
                {
                    "window_s": window,
                    "sustain_s": sustain,
                    "model": MODEL_ID,
                    "calibration": {
                        "session": calibrate["session"],
                        "locked": locked["locked"],
                        "unbroken_points": locked["unbroken_points"],
                    },
                    "development": None,
                    "control": None,
                }
            )
            choice = locked["locked"]
            held = None if choice is None else choice["commercial_held_s"]
            program = None if choice is None else choice["program_cut_s"]
            print(
                f"window {window:.0f}s sustain {sustain}s  "
                f"ESPN ads {held}  program {program}",
                flush=True,
            )

    viable = [row for row in candidates if row["calibration"]["locked"] is not None]
    selected = None if not viable else max(viable, key=lambda row: row["calibration"]["locked"]["commercial_held_s"])
    if selected is not None:
        choice = selected["calibration"]["locked"]
        threshold = choice["threshold"]
        window = selected["window_s"]
        sustain = selected["sustain_s"]
        develop_rows = []
        for session in DEVELOP:
            mask = masks[session]
            times, scores = cached[(window, session)]
            replay = _replay_scores(mask, times, sustained_scores(times, scores, sustain), threshold)
            develop_rows.append(
                {
                    "session": session,
                    "score": replay["score"],
                    "causes": _sum_causes(replay["pods"]),
                    "examples": _examples(session, replay),
                    "incidents": replay["incidents"],
                }
            )
        control_mask = masks[CONTROL[0]]
        times, scores = cached[(window, CONTROL[0])]
        control = _replay_scores(control_mask, times, sustained_scores(times, scores, sustain), threshold)
        selected["development"] = develop_rows
        selected["control"] = {"session": CONTROL[0], "score": control["score"], "incidents": control["incidents"]}

    report = {
        "id": "BRIDGE1_SUSTAIN",
        "model": MODEL_ID,
        "rejected_head": "one-second logistic score, Bridge 0",
        "selected_window_s": None if selected is None else selected["window_s"],
        "selected_sustain_s": None if selected is None else selected["sustain_s"],
        "selection_rule": (
            "highest commercial seconds held on the ESPN calibration broadcast "
            "among 2, 3, 4, and 5 second sustained scores with zero program seconds"
        ),
        "candidates": [
            {
                "window_s": row["window_s"],
                "sustain_s": row["sustain_s"],
                "locked": row["calibration"]["locked"],
            }
            for row in candidates
        ],
        "selected": None if selected is None else _public_development(selected["development"]),
        "control": None
        if selected is None
        else {"session": selected["control"]["session"], "score": selected["control"]["score"]},
        "v1_baseline": {"commercial_held_s": 25.0, "program_cut_s": 0.0, "corpus": "all football"},
    }
    path = root / "bridge1_result.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    detail = root / "bridge1_detail.json"
    detail.write_text(json.dumps({"selected": selected, "candidates": candidates}, indent=2), encoding="utf-8")
    print(f"wrote {path}", flush=True)
    return {
        "report": {
            "selected_window_s": report["selected_window_s"],
            "selected": report["selected"],
        },
        "detail": {"windows": [] if selected is None else [selected]},
    }
