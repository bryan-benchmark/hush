"""A later head: compare this second with the recent audio of the same game.

The absolute ESPN cutoff sits above that game and below program audio on the
training broadcasts. This score is the logit minus a past quantile from the
broadcast being played. The current second is not part of the reference.
Memory and quantile are locked on ESPN. October is scored after that choice.
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
    relative_excess,
)
from tools.gpu_lab.eligibility import build_masks
from tools.gpu_lab.embed import MODEL_ID
from tools.gpu_lab.ladder import pairs, score_mask
from tools.gpu_lab.prepare import DATA_ROOT
from tools.gpu_lab.score import _load_rows, _public_development, _sum_causes
from tools.gpu_lab.splits import CALIBRATE, CONTROL, DEVELOP, WINDOW_S
from tools.gpu_lab.train import model_path

MEMORY_S = (60, 180, 600)
QUANTILES = (0.50, 0.90, 0.99)


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


def _logits(head, vectors) -> list[float]:
    return head.decision_function(vectors).tolist()


def score_relative(root: Path = DATA_ROOT) -> dict:
    sessions = list(CALIBRATE + DEVELOP + CONTROL)
    masks = {row["session"]: row for row in build_masks(sessions)}
    cached: dict[tuple[float, str], tuple[list[float], list[float]]] = {}
    for window in WINDOW_S:
        head = joblib.load(model_path(window, root))
        for session in sessions:
            times, vectors = _load_rows(session, window, root)
            cached[(window, session)] = (times.tolist(), _logits(head, vectors))

    candidates = []
    for window in WINDOW_S:
        calibrate = masks[CALIBRATE[0]]
        times, logits = cached[(window, CALIBRATE[0])]
        for memory in MEMORY_S:
            for quantile in QUANTILES:
                excess = relative_excess(times, logits, memory, quantile)
                locked = lock_threshold(calibrate, times, excess)
                candidates.append(
                    {
                        "window_s": window,
                        "memory_s": memory,
                        "quantile": quantile,
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
                    f"window {window:.0f}s memory {memory}s q {quantile:.2f}  "
                    f"ESPN ads {held}  program {program}",
                    flush=True,
                )

    viable = [row for row in candidates if row["calibration"]["locked"] is not None]
    selected = None if not viable else max(viable, key=lambda row: row["calibration"]["locked"]["commercial_held_s"])
    if selected is not None:
        choice = selected["calibration"]["locked"]
        threshold = choice["threshold"]
        window = selected["window_s"]
        memory = selected["memory_s"]
        quantile = selected["quantile"]
        develop_rows = []
        for session in DEVELOP:
            mask = masks[session]
            times, logits = cached[(window, session)]
            replay = _replay_scores(mask, times, relative_excess(times, logits, memory, quantile), threshold)
            develop_rows.append(
                {
                    "session": session,
                    "score": replay["score"],
                    "causes": _sum_causes(replay["pods"]),
                    "examples": _examples(session, replay),
                    "incidents": replay["incidents"],
                }
            )
        times, logits = cached[(window, CONTROL[0])]
        control = _replay_scores(
            masks[CONTROL[0]],
            times,
            relative_excess(times, logits, memory, quantile),
            threshold,
        )
        selected["development"] = develop_rows
        selected["control"] = {"session": CONTROL[0], "score": control["score"], "incidents": control["incidents"]}

    report = {
        "id": "BRIDGE2_RELATIVE",
        "model": MODEL_ID,
        "rejected_heads": [
            "absolute one-second logistic probability, Bridge 0",
            "two-second sustained probability, Bridge 1",
        ],
        "selected_window_s": None if selected is None else selected["window_s"],
        "selected_memory_s": None if selected is None else selected["memory_s"],
        "selected_quantile": None if selected is None else selected["quantile"],
        "selection_rule": (
            "highest commercial seconds held on the ESPN calibration broadcast "
            "among past-quantile logit gaps with zero program seconds"
        ),
        "candidates": [
            {
                "window_s": row["window_s"],
                "memory_s": row["memory_s"],
                "quantile": row["quantile"],
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
    path = root / "bridge2_result.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    detail = root / "bridge2_detail.json"
    detail.write_text(json.dumps({"selected": selected, "candidates": candidates}, indent=2), encoding="utf-8")
    print(f"wrote {path}", flush=True)
    return {
        "report": {
            "selected_window_s": report["selected_window_s"],
            "selected": report["selected"],
        },
        "detail": {"windows": [] if selected is None else [selected]},
    }
