"""Name the game seconds the trained head already scores as ads.

Zero is the head's own midpoint. It is not a cutoff fit on October.
Listening notes stay blank, and no new model is started.
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
from tools.gpu_lab.splits import CONTROL, DEVELOP

MODULE = Path(__file__)
PROBE_ID = "program_names"
QUESTION = "Which AudioSet names sit on game seconds the trained head scores above zero?"
WINDOW_S = 10.0
TOP_NAMES = 8
SPEECH_RANK_FOLDER = "20261023T043553Z_speech_rank"
SPEECH_RANK_SHA256 = "543acadd66206d4e2ab838e69ca4fcc337009048789af28837196f696a818466"
AST_RANKING_FOLDER = "20261023T004935Z_ranking"
AST_RANKING_SHA256 = "477406f08d314fb0d9e26cda97ba48b58997a4a27323b5ffdca82336560c6153"


def top_counts(indexes: np.ndarray, names: list[str], limit: int = TOP_NAMES) -> list[dict]:
    if len(indexes) == 0:
        return []
    counts = np.bincount(indexes.astype(np.int64), minlength=len(names))
    order = np.argsort(counts)[::-1]
    rows = []
    for index in order:
        if int(counts[index]) == 0 or len(rows) >= limit:
            break
        rows.append(
            {
                "class": names[int(index)],
                "n": int(counts[index]),
                "fraction": round(float(counts[index]) / len(indexes), 6),
            }
        )
    return rows


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
        "split": "program seconds with logistic decision_function above 0, versus at or below 0",
        "zero_is": "the trained head's own midpoint, not a cutoff fit on October",
        "top_names": TOP_NAMES,
        "october_may_choose_cutoff": False,
        "notes_filled": False,
        "one_named_sound_started": False,
        "compared_with": [
            {"probe_id": "speech_rank", "folder": SPEECH_RANK_FOLDER, "result_sha256": SPEECH_RANK_SHA256},
            {"probe_id": "ranking", "folder": AST_RANKING_FOLDER, "result_sha256": AST_RANKING_SHA256},
        ],
    }
    folder = open_probe(PROBE_ID, QUESTION, parameters, MODULE)
    _cited(root, SPEECH_RANK_FOLDER, SPEECH_RANK_SHA256)
    ranking = _cited(root, AST_RANKING_FOLDER, AST_RANKING_SHA256)
    cited_auc = {(row["window_s"], row["session"]): row["auc"] for row in ranking["rows"] if row["window_s"] == WINDOW_S}
    model, names, torch = _head()
    _path, head = load_head(WINDOW_S, root)
    rows = []
    for session in BRIDGE:
        cached = load_cache(session, WINDOW_S, root)
        labels = cached["label"].astype(np.int8)
        scores = logits_for(head, cached["emb"])
        overall = _auc(labels, scores)
        overall_rounded = None if overall is None else round(overall, 6)
        if overall_rounded != cited_auc.get((WINDOW_S, session)):
            raise RuntimeError(f"{session} logistic auc {overall_rounded} does not match the ranking receipt")
        winner = _probabilities(cached["emb"], model, torch).argmax(axis=1)
        program = labels == 0
        above = program & (scores > 0)
        below = program & (scores <= 0)
        commercial = labels == 1
        above_names = top_counts(winner[above], names)
        row = {
            "session": session,
            "role": _role(session),
            "program_n": int(program.sum()),
            "program_above_zero_n": int(above.sum()),
            "program_above_zero_fraction": round(float(above.sum()) / program.sum(), 6) if program.any() else None,
            "program_above_zero": above_names,
            "program_at_or_below_zero": top_counts(winner[below], names),
            "commercial_n": int(commercial.sum()),
            "commercial_above_zero_fraction": round(float(((commercial) & (scores > 0)).sum()) / commercial.sum(), 6) if commercial.any() else None,
        }
        rows.append(row)
        lead = above_names[0]["class"] if above_names else None
        print(f"  {session} program above zero {row['program_above_zero_fraction']} lead {lead}", flush=True)
    develop = [row for row in rows if row["role"] == "develop" and row["program_above_zero"]]
    one_name = bool(develop) and all(row["program_above_zero"][0]["fraction"] == 1.0 for row in develop)
    result = {
        "probe_id": PROBE_ID,
        "finetuned": False,
        "rows": rows,
        "one_named_sound": one_name,
        "one_named_sound_started": False,
        "october_may_choose_cutoff": False,
        "speech_rank_result_sha256": SPEECH_RANK_SHA256,
        "ast_ranking_result_sha256": AST_RANKING_SHA256,
        "control_session": CONTROL[0],
        "develop_sessions": list(DEVELOP),
    }
    finish_probe(folder, PROBE_ID, QUESTION, parameters, result, MODULE)
    return result
