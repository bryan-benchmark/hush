"""Ask whether each game's ads and game seconds carry different AudioSet names.

The class list is frozen from the training games. October is described.
No cutoff is chosen, and the listening notes stay blank.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from experiments.ledger import sha256_text
from tools.gpu_lab.embed import MODEL_ID
from tools.gpu_lab.learning_net.data import BRIDGE, load_cache
from tools.gpu_lab.learning_net.log import finish_probe, open_probe
from tools.gpu_lab.learning_net.tags import _head
from tools.gpu_lab.prepare import DATA_ROOT
from tools.gpu_lab.splits import CALIBRATE, CONTROL, DEVELOP, TRAIN

MODULE = Path(__file__)
PROBE_ID = "game_sounds"
QUESTION = "On each game, do commercial seconds and program seconds carry different AudioSet names?"
WINDOW_S = 10.0
TOP_CLASSES = 8
TAGS_FOLDER = "20261023T005224Z_failure_tags"
TAGS_SHA256 = "84b7ebb6eb7b3f4fa06b29b93d7555164fbca11ce77b15adca60f81c9dc6e071"
AST_RANKING_FOLDER = "20261023T004935Z_ranking"
AST_RANKING_SHA256 = "477406f08d314fb0d9e26cda97ba48b58997a4a27323b5ffdca82336560c6153"


def _probabilities(vectors: np.ndarray, model, torch) -> np.ndarray:
    rows = []
    with torch.inference_mode():
        for start in range(0, len(vectors), 1024):
            batch = torch.tensor(vectors[start : start + 1024])
            logits = model.classifier(batch).detach().cpu().numpy()
            logits = logits - logits.max(axis=1, keepdims=True)
            prob = np.exp(logits)
            prob /= prob.sum(axis=1, keepdims=True)
            rows.append(prob)
    return np.concatenate(rows, axis=0) if rows else np.zeros((0, model.config.num_labels))


def _auc(labels: np.ndarray, scores: np.ndarray) -> float | None:
    from sklearn.metrics import roc_auc_score

    keep = labels >= 0
    y = labels[keep]
    if len(np.unique(y)) < 2:
        return None
    return float(roc_auc_score(y, scores[keep]))


def _role(session: str) -> str:
    if session in TRAIN:
        return "train"
    if session in CALIBRATE:
        return "calibrate"
    if session in DEVELOP:
        return "develop"
    return "control"


def _cited(root: Path, folder: str, expected: str) -> dict:
    path = root / "learning_net" / "probes" / folder / "result.json"
    text = path.read_text(encoding="utf-8")
    digest = sha256_text(text)
    if digest != expected:
        raise RuntimeError(f"{folder} hash {digest} does not match {expected}")
    return json.loads(text)


def class_floors(rows: list[dict], class_name: str) -> dict:
    def cell(row: dict) -> float | None:
        return next(item["auc"] for item in row["classes"] if item["class"] == class_name)

    scored = [row for row in rows if row["role"] in ("train", "calibrate") and cell(row) is not None]
    floor = min(cell(row) for row in scored)
    below = [
        {"session": row["session"], "auc": cell(row)}
        for row in rows
        if row["role"] == "develop" and cell(row) is not None and cell(row) < floor
    ]
    return {"class": class_name, "pre_october_floor_auc": floor, "october_below_pre_october_floor": below}


def run(root: Path = DATA_ROOT) -> dict:
    parameters = {
        "model": MODEL_ID,
        "window_s": WINDOW_S,
        "head": "frozen AudioSet classifier applied to cached CLS vectors",
        "class_order": "largest training-game gap, commercial mean minus program mean",
        "top_classes": TOP_CLASSES,
        "october_may_choose_cutoff": False,
        "notes_filled": False,
        "compared_with": [
            {"probe_id": "failure_tags", "folder": TAGS_FOLDER, "result_sha256": TAGS_SHA256},
            {"probe_id": "ranking", "folder": AST_RANKING_FOLDER, "result_sha256": AST_RANKING_SHA256},
        ],
    }
    folder = open_probe(PROBE_ID, QUESTION, parameters, MODULE)
    tags = _cited(root, TAGS_FOLDER, TAGS_SHA256)
    ranking = _cited(root, AST_RANKING_FOLDER, AST_RANKING_SHA256)
    notes_filled = bool(tags["listen"]) and all(row.get("note") for row in tags["listen"])
    logistic_auc = {
        (row["window_s"], row["session"]): row["auc"]
        for row in ranking["rows"]
        if row["window_s"] == WINDOW_S
    }
    model, names, torch = _head()
    packed = {}
    for session in BRIDGE:
        cached = load_cache(session, WINDOW_S, root)
        labels = cached["label"].astype(np.int8)
        usable = labels >= 0
        print(f"  classes {session} {int(usable.sum())}", flush=True)
        packed[session] = {"label": labels, "prob": _probabilities(cached["emb"][usable], model, torch), "keep": usable}

    train_commercial = np.concatenate([packed[session]["prob"][packed[session]["label"][packed[session]["keep"]] == 1] for session in TRAIN])
    train_program = np.concatenate([packed[session]["prob"][packed[session]["label"][packed[session]["keep"]] == 0] for session in TRAIN])
    gap = train_commercial.mean(axis=0) - train_program.mean(axis=0)
    order = list(np.argsort(gap)[::-1][:TOP_CLASSES])
    print(f"  top train class {names[order[0]]}", flush=True)

    rows = []
    for session in BRIDGE:
        labels = packed[session]["label"]
        keep = packed[session]["keep"]
        prob = packed[session]["prob"]
        kept_labels = labels[keep]
        classes = []
        for index in order:
            commercial = kept_labels == 1
            program = kept_labels == 0
            auc = _auc(labels, _scatter(labels, prob[:, index]))
            classes.append(
                {
                    "class": names[index],
                    "commercial_mean": None if not commercial.any() else round(float(prob[commercial, index].mean()), 6),
                    "program_mean": None if not program.any() else round(float(prob[program, index].mean()), 6),
                    "gap": None
                    if not commercial.any() or not program.any()
                    else round(float(prob[commercial, index].mean() - prob[program, index].mean()), 6),
                    "auc": None if auc is None else round(auc, 6),
                }
            )
        top1 = prob.argmax(axis=1) if len(prob) else np.zeros(0, dtype=np.int64)
        rows.append(
            {
                "session": session,
                "role": _role(session),
                "commercial_n": int((kept_labels == 1).sum()),
                "program_n": int((kept_labels == 0).sum()),
                "commercial_top1": _top_share(top1[kept_labels == 1], names) if (kept_labels == 1).any() else None,
                "program_top1": _top_share(top1[kept_labels == 0], names) if (kept_labels == 0).any() else None,
                "ast_logistic_auc": logistic_auc.get((WINDOW_S, session)),
                "classes": classes,
            }
        )
        lead = classes[0]
        print(f"  {session} {lead['class']} auc {lead['auc']} gap {lead['gap']}", flush=True)

    reading = class_floors(rows, names[order[0]])
    result = {
        "probe_id": PROBE_ID,
        "model": MODEL_ID,
        "finetuned": False,
        "class_order": [names[index] for index in order],
        "rows": rows,
        "top_class_against_pre_october_floor": reading,
        "listen_notes_filled": notes_filled,
        "one_named_sound": False,
        "october_may_choose_cutoff": False,
        "failure_tags_result_sha256": TAGS_SHA256,
        "ast_ranking_result_sha256": AST_RANKING_SHA256,
        "control_session": CONTROL[0],
    }
    finish_probe(folder, PROBE_ID, QUESTION, parameters, result, MODULE)
    return result


def _scatter(labels: np.ndarray, kept_scores: np.ndarray) -> np.ndarray:
    scores = np.zeros(len(labels), dtype=np.float64)
    scores[labels >= 0] = kept_scores
    return scores


def _top_share(indexes: np.ndarray, names: list[str]) -> dict:
    if len(indexes) == 0:
        return {"class": None, "n": 0, "fraction": None}
    counts = np.bincount(indexes, minlength=len(names))
    winner = int(counts.argmax())
    return {"class": names[winner], "n": int(counts[winner]), "fraction": round(float(counts[winner]) / len(indexes), 6)}
