"""Lock the mute rule on ESPN, then score October without refitting it."""

from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np

from tools.gpu_lab.decisions import lock_threshold, playback_from_scores, pod_losses, program_incidents
from tools.gpu_lab.eligibility import build_masks
from tools.gpu_lab.embed import MODEL_ID, cache_path
from tools.gpu_lab.ladder import pairs, score_mask
from tools.gpu_lab.prepare import DATA_ROOT
from tools.gpu_lab.splits import CALIBRATE, CONTROL, DEVELOP, TRAIN, WINDOW_S
from tools.gpu_lab.train import model_path


def _load_rows(session: str, window_s: float, root: Path) -> tuple[np.ndarray, np.ndarray]:
    data = np.load(cache_path(session, window_s, root))
    return data["t"].astype(np.float64), data["emb"].astype(np.float32)


def _replay(mask: dict, window_s: float, head, threshold: float, root: Path) -> dict:
    times, vectors = _load_rows(mask["session"], window_s, root)
    scores = head.predict_proba(vectors)[:, 1]
    coverage = pairs(mask, "coverage")[0]
    playback = playback_from_scores(coverage, times.tolist(), scores.tolist(), threshold)
    scored = score_mask(mask, playback)
    pods = pod_losses(pairs(mask, "verified_commercial"), playback)
    incidents = program_incidents(pairs(mask, "verified_program"), playback)
    return {"score": scored, "pods": pods, "incidents": incidents, "playback_spans": len(playback)}


def _sum_causes(pods: list[dict]) -> dict[str, float]:
    totals = {"missed": 0.0, "late_start": 0.0, "early_unmute": 0.0}
    for row in pods:
        totals["missed"] += row["missed_s"]
        totals["late_start"] += row["late_start_s"]
        totals["early_unmute"] += row["early_unmute_s"]
    return {key: round(value, 3) for key, value in totals.items()}


def score_all(root: Path = DATA_ROOT) -> dict:
    masks = {row["session"]: row for row in build_masks(list(TRAIN + CALIBRATE + DEVELOP + CONTROL))}
    windows = []
    for window in WINDOW_S:
        head = joblib.load(model_path(window, root))
        calibrate = masks[CALIBRATE[0]]
        times, vectors = _load_rows(calibrate["session"], window, root)
        scores = head.predict_proba(vectors)[:, 1]
        locked = lock_threshold(calibrate, times.tolist(), scores.tolist())
        choice = locked["locked"]
        least_cut = min(locked["curve"], key=lambda row: (row["program_cut_s"], -row["commercial_held_s"]))
        entry = {
            "window_s": window,
            "model": MODEL_ID,
            "calibration": {
                "session": calibrate["session"],
                "locked": choice,
                "unbroken_points": locked["unbroken_points"],
                "least_program_cut": least_cut,
            },
            "development": None,
            "control": None,
        }
        if choice is not None:
            threshold = choice["threshold"]
            develop_rows = []
            for session in DEVELOP:
                replay = _replay(masks[session], window, head, threshold, root)
                develop_rows.append(
                    {
                        "session": session,
                        "score": replay["score"],
                        "causes": _sum_causes(replay["pods"]),
                        "examples": _examples(session, replay),
                        "incidents": replay["incidents"],
                    }
                )
            control = _replay(masks[CONTROL[0]], window, head, threshold, root)
            entry["development"] = develop_rows
            entry["control"] = {
                "session": CONTROL[0],
                "score": control["score"],
                "incidents": control["incidents"],
            }
        windows.append(entry)
    selected = _select(windows)
    report = {
        "id": "BRIDGE0_AST",
        "model": MODEL_ID,
        "selected_window_s": None if selected is None else selected["window_s"],
        "selection_rule": "highest commercial seconds held on the ESPN calibration broadcast among rules with zero program seconds",
        "windows": [
            {
                "window_s": row["window_s"],
                "calibration": row["calibration"],
                "development": _public_development(row["development"]),
                "control": None
                if row["control"] is None
                else {"session": row["control"]["session"], "score": row["control"]["score"]},
            }
            for row in windows
        ],
        "selected": None if selected is None else _public_development(selected["development"]),
        "v1_baseline": {"commercial_held_s": 25.0, "program_cut_s": 0.0, "corpus": "all football"},
    }
    path = root / "bridge0_result.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    detail_path = root / "bridge0_detail.json"
    detail_path.write_text(json.dumps({"windows": windows}, indent=2), encoding="utf-8")
    print(f"wrote {path}", flush=True)
    return {"report": report, "detail": {"windows": windows}}


def _select(windows: list[dict]) -> dict | None:
    candidates = [row for row in windows if row["calibration"]["locked"] is not None]
    if not candidates:
        return None
    return max(candidates, key=lambda row: row["calibration"]["locked"]["commercial_held_s"])


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


def _public_development(rows: list[dict] | None) -> dict | None:
    if rows is None:
        return None
    held = sum(row["score"]["commercial_held_s"] for row in rows)
    heard = sum(row["score"]["commercial_heard_s"] for row in rows)
    cut = sum(row["score"]["program_cut_s"] for row in rows)
    incidents = sum(row["score"]["false_cover_incidents"] for row in rows)
    broken = any(row["score"]["broken"] for row in rows) or cut > 0
    target = held + heard
    causes = {"missed": 0.0, "late_start": 0.0, "early_unmute": 0.0}
    for row in rows:
        for key in causes:
            causes[key] += row["causes"][key]
    return {
        "broken": broken,
        "commercial_held_s": round(held, 3),
        "commercial_heard_s": round(heard, 3),
        "commercial_target_s": round(target, 3),
        "held_fraction": None if broken or target <= 0 else round(held / target, 6),
        "program_cut_s": round(cut, 3),
        "false_cover_incidents": incidents,
        "causes": {key: round(value, 3) for key, value in causes.items()},
        "sessions": [
            {"session": row["session"], "score": row["score"], "causes": row["causes"]} for row in rows
        ],
    }
