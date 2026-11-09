"""Name the game seconds that survive the frozen four-game cutoff.

The threshold is recomputed from the training games and ESPN, then checked
against the joint_rule receipt. October does not move it.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

from experiments.ledger import sha256_text
from tools.gpu_lab.decisions import HOP_S, playback_from_scores, program_incidents, relative_excess
from tools.gpu_lab.ladder import pairs
from tools.gpu_lab.learning_net.data import bridge_masks, load_cache, load_head, logits_for
from tools.gpu_lab.learning_net.game_sounds import _probabilities, _role
from tools.gpu_lab.learning_net.joint_rule import MEMORY_S, QUANTILE, WINDOW_S, _ceiling
from tools.gpu_lab.learning_net.log import finish_probe, open_probe
from tools.gpu_lab.learning_net.program_names import top_counts
from tools.gpu_lab.learning_net.tags import _head
from tools.gpu_lab.prepare import DATA_ROOT
from tools.gpu_lab.splits import CALIBRATE, CONTROL, DEVELOP, TRAIN

MODULE = Path(__file__)
PROBE_ID = "joint_remainder"
QUESTION = "Where are the game seconds the frozen four-game cutoff still hides, and what are they named?"
JOINT_FOLDER = "20261023T005214Z_joint_rule"
JOINT_SHA256 = "cc5dba92c8977562fdd7895cacfefaff0b7c6470c255ea477ee23e42bde265ec"


def overlaps_program(moment: float, program: list[tuple[float, float]], hop_s: float = HOP_S) -> float:
    end = moment + hop_s
    return sum(max(0.0, min(end, stop) - max(moment, start)) for start, stop in program)


def remainder_indexes(times: list[float], scores: list[float], program: list[tuple[float, float]], threshold: float) -> list[int]:
    chosen = []
    for index, (moment, score) in enumerate(zip(times, scores)):
        if score >= threshold and overlaps_program(moment, program) > 1e-9:
            chosen.append(index)
    return chosen


def _cited(root: Path) -> dict:
    path = root / "learning_net" / "probes" / JOINT_FOLDER / "result.json"
    text = path.read_text(encoding="utf-8")
    digest = sha256_text(text)
    if digest != JOINT_SHA256:
        raise RuntimeError(f"{JOINT_FOLDER} hash {digest} does not match {JOINT_SHA256}")
    return json.loads(text)


def run(root: Path = DATA_ROOT) -> dict:
    parameters = {
        "window_s": WINDOW_S,
        "memory_s": MEMORY_S,
        "quantile": QUANTILE,
        "threshold_rule": "recomputed from the training games and ESPN, then checked against joint_rule",
        "october_may_choose_cutoff": False,
        "one_named_sound_started": False,
        "compared_with": {"probe_id": "joint_rule", "folder": JOINT_FOLDER, "result_sha256": JOINT_SHA256},
    }
    folder = open_probe(PROBE_ID, QUESTION, parameters, MODULE)
    cited = _cited(root)
    masks = bridge_masks()
    _path, head = load_head(WINDOW_S, root)
    model, names, torch = _head()
    packed = {}
    ceilings = {}
    for session in list(TRAIN + CALIBRATE + DEVELOP + CONTROL):
        cached = load_cache(session, WINDOW_S, root)
        times = cached["t"].astype(float).tolist()
        scores = relative_excess(times, logits_for(head, cached["emb"]).tolist(), MEMORY_S, QUANTILE)
        packed[session] = (cached, times, scores)
        if session in TRAIN or session in CALIBRATE:
            ceilings[session] = _ceiling(times, scores, pairs(masks[session], "verified_program"))
    threshold = math.nextafter(max(ceilings.values()), math.inf)
    if abs(threshold - cited["threshold"]) > 1e-9:
        raise RuntimeError(f"recomputed threshold {threshold} does not match joint_rule {cited['threshold']}")
    cited_cut = {row["session"]: row["program_cut_s"] for row in cited["october"]}
    cited_cut[cited["control"]["session"]] = cited["control"]["program_cut_s"]
    rows = []
    for session in list(DEVELOP + CONTROL):
        cached, times, scores = packed[session]
        program = pairs(masks[session], "verified_program")
        playback = playback_from_scores(pairs(masks[session], "coverage")[0], times, scores, threshold)
        incidents = program_incidents(program, playback)
        cut = round(sum(row["program_s"] for row in incidents), 3)
        if abs(cut - cited_cut[session]) > 1e-6:
            raise RuntimeError(f"{session} program cut {cut} does not match joint_rule {cited_cut[session]}")
        indexes = remainder_indexes(times, scores, program, threshold)
        winner = []
        if indexes:
            vectors = cached["emb"][np.asarray(indexes)]
            winner = [names[int(index)] for index in _probabilities(vectors, model, torch).argmax(axis=1)]
        seconds = [
            {
                "t": round(times[index], 3),
                "program_overlap_s": round(overlaps_program(times[index], program), 3),
                "score": round(scores[index], 6),
                "class": label,
            }
            for index, label in zip(indexes, winner)
        ]
        rows.append(
            {
                "session": session,
                "role": _role(session),
                "program_cut_s": cut,
                "incidents": incidents,
                "decision_seconds": seconds,
                "names": top_counts(np.array([names.index(label) for label in winner], dtype=np.int64), names) if winner else [],
            }
        )
        print(f"  {session} cut {cut} incidents {len(incidents)} decisions {len(seconds)}", flush=True)
    pooled = [second["class"] for row in rows for second in row["decision_seconds"]]
    one_name = len(set(pooled)) == 1 and len(pooled) > 0
    result = {
        "probe_id": PROBE_ID,
        "threshold": threshold,
        "threshold_matches_joint_rule": True,
        "rows": rows,
        "names": top_counts(np.array([names.index(label) for label in pooled], dtype=np.int64), names) if pooled else [],
        "one_named_sound": one_name,
        "one_named_sound_started": False,
        "october_may_choose_cutoff": False,
        "joint_rule_result_sha256": JOINT_SHA256,
        "october_program_cut_s": cited["october_program_cut_s"],
    }
    finish_probe(folder, PROBE_ID, QUESTION, parameters, result, MODULE)
    return result
