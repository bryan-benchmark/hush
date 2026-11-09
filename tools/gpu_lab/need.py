"""One next experiment, taken from the replay measurements."""

from __future__ import annotations

import json
from pathlib import Path

from tools.gpu_lab.prepare import DATA_ROOT


def build_need(scored: dict) -> dict:
    report = scored["report"]
    windows = scored["detail"]["windows"]
    selected = next((row for row in windows if row["window_s"] == report["selected_window_s"]), None)
    if selected is None:
        least = min(windows, key=lambda row: row["calibration"]["least_program_cut"]["program_cut_s"])
        point = least["calibration"]["least_program_cut"]
        return {
            "gate": "bridge0",
            "conclusion": "this head hides the calibration game at every threshold",
            "failure": "program_mute",
            "session": least["calibration"]["session"],
            "window_s": least["window_s"],
            "program_cut_s": point["program_cut_s"],
            "commercial_held_s": point["commercial_held_s"],
            "threshold": point["threshold"],
            "hypothesis": "No cutoff on the ESPN broadcast stays off the game.",
            "next_experiment": "Stop this head. Do not tune it on October.",
            "pass_fail": "A later head has zero program seconds on hush_20260914_212529.",
        }
    dev = report["selected"]
    control = selected["control"]["score"]
    causes = dev["causes"]
    if dev["broken"] or control["broken"]:
        examples = _program_examples(selected)
        worst = max(examples, key=lambda row: row.get("program_s", 0), default=None)
        return {
            "gate": "bridge0",
            "conclusion": "the calibration rule hides program audio on a later broadcast",
            "failure": "program_mute",
            "window_s": selected["window_s"],
            "threshold": selected["calibration"]["locked"]["threshold"],
            "development_program_cut_s": dev["program_cut_s"],
            "redzone_program_cut_s": control["program_cut_s"],
            "examples": examples[:5],
            "worst": worst,
            "hypothesis": "The ESPN cutoff does not stay off the game on October or on RedZone.",
            "next_experiment": "Do not promote this rule. A later head must keep both at zero program seconds.",
            "pass_fail": "October development and RedZone each show 0 program seconds at the locked threshold.",
        }
    largest = max(causes, key=causes.get)
    examples = _cause_examples(selected, largest)
    held = dev["commercial_held_s"]
    if held <= 0:
        conclusion = "the head stays off the game and covers no commercial audio"
        nxt = "Stop this head. Play is the better rule."
        test = "A later head covers more than 0 commercial seconds on October with 0 program seconds."
    elif largest == "early_unmute":
        conclusion = "the mute lets go while the commercial continues"
        nxt = "Add a return decision on the same embeddings. Do not add a per-show model."
        test = "Early-unmute seconds on October fall by half, and program seconds stay 0."
    elif largest == "missed":
        conclusion = "whole commercials never cross the locked threshold"
        nxt = "Try a temporal layer on the same embeddings. Do not add a per-show model."
        test = "Missed commercial seconds on October fall by half, and program seconds stay 0."
    else:
        conclusion = "the mute starts after the commercial does"
        nxt = "Compare the shorter past-only windows already cached before adding a new encoder."
        test = "Late-start seconds on October fall, and program seconds stay 0."
    return {
        "gate": "bridge0",
        "conclusion": conclusion,
        "failure": largest,
        "window_s": selected["window_s"],
        "threshold": selected["calibration"]["locked"]["threshold"],
        "commercial_held_s": held,
        "commercial_heard_s": dev["commercial_heard_s"],
        "held_fraction": dev["held_fraction"],
        "program_cut_s": 0,
        "causes_s": causes,
        "examples": examples[:5],
        "hypothesis": f"The largest measured pile is {largest}: {causes[largest]} seconds.",
        "next_experiment": nxt,
        "pass_fail": test,
    }


def _program_examples(selected: dict) -> list[dict]:
    rows = []
    for session_row in selected["development"]:
        for incident in session_row["incidents"]:
            rows.append({"session": session_row["session"], "cause": "program_mute", **incident})
    for incident in selected["control"]["incidents"]:
        rows.append({"session": selected["control"]["session"], "cause": "program_mute", **incident})
    rows.sort(key=lambda row: row["program_s"], reverse=True)
    return rows


def _cause_examples(selected: dict, cause: str) -> list[dict]:
    key = {"missed": "missed_s", "late_start": "late_start_s", "early_unmute": "early_unmute_s"}[cause]
    rows = []
    for session_row in selected["development"]:
        for example in session_row["examples"]:
            if example.get("cause") == cause:
                rows.append(example)
    rows.sort(key=lambda row: row.get(key, 0), reverse=True)
    return rows


def write_need(scored: dict, root: Path = DATA_ROOT) -> Path:
    need = build_need(scored)
    path = root / "NEED.json"
    path.write_text(json.dumps(need, indent=2), encoding="utf-8")
    print(json.dumps(need, indent=2), flush=True)
    print(f"wrote {path}", flush=True)
    return path
