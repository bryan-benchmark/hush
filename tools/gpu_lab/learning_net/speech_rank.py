"""Ask whether speech-named seconds are the ones a game fails to rank.

Groups are Music, Speech, and other. They were named by the game_sounds
receipt before this probe. The score is the existing 10-second logistic.
October is described. No cutoff is chosen.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from experiments.ledger import sha256_text
from tools.gpu_lab.embed import MODEL_ID
from tools.gpu_lab.learning_net.data import BRIDGE, load_cache, load_head, logits_for
from tools.gpu_lab.learning_net.game_sounds import _auc, _probabilities, _role
from tools.gpu_lab.learning_net.log import finish_probe, open_probe
from tools.gpu_lab.learning_net.tags import _head
from tools.gpu_lab.prepare import DATA_ROOT
from tools.gpu_lab.splits import CALIBRATE, CONTROL, DEVELOP, TRAIN

MODULE = Path(__file__)
PROBE_ID = "speech_rank"
QUESTION = "On each game, do ad seconds named Speech rank below ad seconds named Music?"
WINDOW_S = 10.0
NAMED = ("Music", "Speech")
GROUPS = ("Music", "Speech", "other")
SOUNDS_FOLDER = "20261023T043409Z_game_sounds"
SOUNDS_SHA256 = "0ba494285435da08771acaeb248dc929d7e160d939c2cfb9310306956307f0e9"
AST_RANKING_FOLDER = "20261023T004935Z_ranking"
AST_RANKING_SHA256 = "477406f08d314fb0d9e26cda97ba48b58997a4a27323b5ffdca82336560c6153"


def group_name(label: str) -> str:
    if label in NAMED:
        return label
    return "other"


def _summary(scores: np.ndarray, total: int) -> dict:
    if len(scores) == 0:
        return {"n": 0, "fraction": 0.0 if total else None, "median_logit": None, "p10": None, "p90": None}
    return {
        "n": int(len(scores)),
        "fraction": round(float(len(scores) / total), 6) if total else None,
        "median_logit": round(float(np.median(scores)), 6),
        "p10": round(float(np.quantile(scores, 0.10)), 6),
        "p90": round(float(np.quantile(scores, 0.90)), 6),
    }


def _group_auc(labels: np.ndarray, scores: np.ndarray, groups: np.ndarray, wanted: str) -> float | None:
    masked = labels.copy()
    masked[groups != wanted] = -1
    auc = _auc(masked, scores)
    return None if auc is None else round(auc, 6)


def group_floors(rows: list[dict], group: str) -> dict:
    def cell(row: dict) -> float | None:
        return row["auc_by_group"][group]

    scored = [row for row in rows if row["role"] in ("train", "calibrate") and cell(row) is not None]
    floor = None if not scored else min(cell(row) for row in scored)
    below = [
        {"session": row["session"], "auc": cell(row)}
        for row in rows
        if row["role"] == "develop" and cell(row) is not None and floor is not None and cell(row) < floor
    ]
    return {"group": group, "pre_october_floor_auc": floor, "october_below_pre_october_floor": below}


def _cited(root: Path, folder: str, expected: str) -> dict:
    path = root / "learning_net" / "probes" / folder / "result.json"
    text = path.read_text(encoding="utf-8")
    digest = sha256_text(text)
    if digest != expected:
        raise RuntimeError(f"{folder} hash {digest} does not match {expected}")
    return json.loads(text)


def run(root: Path = DATA_ROOT) -> dict:
    parameters = {
        "model": MODEL_ID,
        "window_s": WINDOW_S,
        "groups": list(GROUPS),
        "group_rule": "top AudioSet name is Music or Speech; every other name is other",
        "score": "existing 10s logistic decision_function, higher means more commercial",
        "october_may_choose_cutoff": False,
        "speech_to_text_started": False,
        "compared_with": [
            {"probe_id": "game_sounds", "folder": SOUNDS_FOLDER, "result_sha256": SOUNDS_SHA256},
            {"probe_id": "ranking", "folder": AST_RANKING_FOLDER, "result_sha256": AST_RANKING_SHA256},
        ],
    }
    folder = open_probe(PROBE_ID, QUESTION, parameters, MODULE)
    _cited(root, SOUNDS_FOLDER, SOUNDS_SHA256)
    ranking = _cited(root, AST_RANKING_FOLDER, AST_RANKING_SHA256)
    cited_auc = {(row["window_s"], row["session"]): row["auc"] for row in ranking["rows"] if row["window_s"] == WINDOW_S}
    model, names, torch = _head()
    _path, head = load_head(WINDOW_S, root)
    rows = []
    for session in BRIDGE:
        cached = load_cache(session, WINDOW_S, root)
        labels = cached["label"].astype(np.int8)
        scores = logits_for(head, cached["emb"])
        probabilities = _probabilities(cached["emb"], model, torch)
        groups = np.asarray([group_name(names[int(index)]) for index in probabilities.argmax(axis=1)], dtype=object)
        role_rows = {}
        for kind, code in (("commercial", 1), ("program", 0)):
            chosen = labels == code
            total = int(chosen.sum())
            role_rows[kind] = [
                {"group": name, **_summary(scores[chosen & (groups == name)], total)}
                for name in GROUPS
            ]
        auc_by_group = {name: _group_auc(labels, scores, groups, name) for name in GROUPS}
        overall = _auc(labels, scores)
        overall_rounded = None if overall is None else round(overall, 6)
        if overall_rounded != cited_auc.get((WINDOW_S, session)):
            raise RuntimeError(f"{session} logistic auc {overall_rounded} does not match the ranking receipt")
        rows.append(
            {
                "session": session,
                "role": _role(session),
                "commercial_n": int((labels == 1).sum()),
                "program_n": int((labels == 0).sum()),
                "by_role": role_rows,
                "auc_by_group": auc_by_group,
                "auc": overall_rounded,
            }
        )
        print(
            f"  {session} music {auc_by_group['Music']} speech {auc_by_group['Speech']} other {auc_by_group['other']}",
            flush=True,
        )
    result = {
        "probe_id": PROBE_ID,
        "finetuned": False,
        "rows": rows,
        "floors": {name: group_floors(rows, name) for name in GROUPS},
        "speech_to_text_started": False,
        "october_may_choose_cutoff": False,
        "game_sounds_result_sha256": SOUNDS_SHA256,
        "ast_ranking_result_sha256": AST_RANKING_SHA256,
        "control_session": CONTROL[0],
        "train_sessions": list(TRAIN),
        "calibrate_sessions": list(CALIBRATE),
        "develop_sessions": list(DEVELOP),
    }
    finish_probe(folder, PROBE_ID, QUESTION, parameters, result, MODULE)
    return result
