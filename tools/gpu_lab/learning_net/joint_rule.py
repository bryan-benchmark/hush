"""Score the cutoff that leaves every pre-October game on.

The threshold is recomputed from those four games and then frozen. October
and the zero-ad control are scored once.
"""

from __future__ import annotations

import math
from pathlib import Path

from tools.gpu_lab.decisions import playback_from_scores, pod_losses, program_incidents, relative_excess
from tools.gpu_lab.ladder import pairs, score_mask
from tools.gpu_lab.learning_net.data import bridge_masks, input_hashes, load_cache, load_head, logits_for
from tools.gpu_lab.learning_net.log import finish_probe, open_probe
from tools.gpu_lab.prepare import DATA_ROOT
from tools.gpu_lab.splits import CALIBRATE, CONTROL, DEVELOP, TRAIN

MODULE = Path(__file__)
PROBE_ID = "joint_rule"
QUESTION = "Does the cutoff that leaves every pre-October game on also leave October and the zero-ad control on?"
WINDOW_S = 10.0
MEMORY_S = 180
QUANTILE = 0.5
PLAN_ROUNDED_THRESHOLD = 18.40


def _ceiling(times: list[float], scores: list[float], program: list[tuple[float, float]]) -> float:
    ceiling = None
    for moment, score in zip(times, scores):
        end = moment + 1.0
        if any(min(end, stop) - max(moment, start) > 1e-9 for start, stop in program):
            ceiling = score if ceiling is None else max(ceiling, score)
    if ceiling is None:
        raise RuntimeError("no program seconds to clear")
    return float(ceiling)


def _score_at(mask: dict, times: list[float], scores: list[float], threshold: float) -> dict:
    playback = playback_from_scores(pairs(mask, "coverage")[0], times, scores, threshold)
    scored = score_mask(mask, playback)
    incidents = program_incidents(pairs(mask, "verified_program"), playback)
    causes = {"missed": 0.0, "late_start": 0.0, "early_unmute": 0.0}
    for row in pod_losses(pairs(mask, "verified_commercial"), playback):
        causes["missed"] += row["missed_s"]
        causes["late_start"] += row["late_start_s"]
        causes["early_unmute"] += row["early_unmute_s"]
    return {
        "session": mask["session"],
        "broken": scored["broken"],
        "commercial_held_s": scored["commercial_held_s"],
        "commercial_heard_s": scored["commercial_heard_s"],
        "program_cut_s": scored["program_cut_s"],
        "false_cover_incidents": scored["false_cover_incidents"],
        "causes_s": {key: round(value, 3) for key, value in causes.items()},
        "longest_program_incident_s": None if not incidents else max(row["program_s"] for row in incidents),
    }


def run(root: Path = DATA_ROOT) -> dict:
    parameters = {
        "window_s": WINDOW_S,
        "memory_s": MEMORY_S,
        "quantile": QUANTILE,
        "score": "logit minus the median of the previous 180 decision scores",
        "threshold_rule": "just above the highest program-overlapping score on the three training games and ESPN",
        "plan_rounded_threshold": PLAN_ROUNDED_THRESHOLD,
        "october_may_choose_cutoff": False,
        "allowed_sessions": list(TRAIN + CALIBRATE),
        "test_sessions": list(DEVELOP + CONTROL),
    }
    folder = open_probe(PROBE_ID, QUESTION, parameters, MODULE)
    masks = bridge_masks()
    _path, head = load_head(WINDOW_S, root)
    packed = {}
    ceilings = {}
    for session in list(TRAIN + CALIBRATE + DEVELOP + CONTROL):
        cached = load_cache(session, WINDOW_S, root)
        times = cached["t"].astype(float).tolist()
        scores = relative_excess(times, logits_for(head, cached["emb"]).tolist(), MEMORY_S, QUANTILE)
        packed[session] = (times, scores)
        if session in TRAIN or session in CALIBRATE:
            ceilings[session] = _ceiling(times, scores, pairs(masks[session], "verified_program"))
            print(f"  ceiling {session} {ceilings[session]:.4f}", flush=True)
    threshold = math.nextafter(max(ceilings.values()), math.inf)
    allowed = [_score_at(masks[session], *packed[session], threshold) for session in TRAIN + CALIBRATE]
    october = [_score_at(masks[session], *packed[session], threshold) for session in DEVELOP]
    control = _score_at(masks[CONTROL[0]], *packed[CONTROL[0]], threshold)
    october_program = round(sum(row["program_cut_s"] for row in october), 3)
    october_held = round(sum(row["commercial_held_s"] for row in october), 3)
    result = {
        "probe_id": PROBE_ID,
        "inputs": input_hashes(WINDOW_S, list(TRAIN + CALIBRATE + DEVELOP + CONTROL), root),
        "ceilings": {session: round(value, 6) for session, value in ceilings.items()},
        "threshold": threshold,
        "threshold_rounds_to_plan_value": round(threshold, 2) == PLAN_ROUNDED_THRESHOLD,
        "allowed": allowed,
        "october": october,
        "october_commercial_held_s": october_held,
        "october_program_cut_s": october_program,
        "october_broken": october_program > 0 or any(row["broken"] for row in october),
        "control": control,
    }
    print(
        f"  threshold {threshold:.4f} october ads {october_held} program {october_program} "
        f"control program {control['program_cut_s']}",
        flush=True,
    )
    finish_probe(folder, PROBE_ID, QUESTION, parameters, result, MODULE)
    return result
