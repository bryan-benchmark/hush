"""Per-game ranking of commercial seconds against program seconds.

The score is ROC AUC on the logistic logit. Probability would rank the same
seconds. No threshold is chosen.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from sklearn.metrics import roc_auc_score

from tools.gpu_lab.learning_net.data import BRIDGE, input_hashes, load_cache, load_head, logits_for
from tools.gpu_lab.learning_net.log import finish_probe, open_probe
from tools.gpu_lab.prepare import DATA_ROOT
from tools.gpu_lab.splits import CALIBRATE, CONTROL, DEVELOP, TRAIN, WINDOW_S

MODULE = Path(__file__)
PROBE_ID = "ranking"
QUESTION = "Inside each game, do commercial seconds rank above program seconds, and does a longer window rank them more cleanly?"


def _auc(labels: np.ndarray, scores: np.ndarray) -> float | None:
    keep = labels >= 0
    y = labels[keep]
    if len(np.unique(y)) < 2:
        return None
    return float(roc_auc_score(y, scores[keep]))


def run(root: Path = DATA_ROOT) -> dict:
    parameters = {
        "windows_s": list(WINDOW_S),
        "score": "logistic decision_function, higher means more commercial",
        "seconds": "label 1 commercial against label 0 program; excluded seconds omitted",
        "october_may_describe": True,
        "october_may_choose_cutoff": False,
        "sessions": BRIDGE,
    }
    folder = open_probe(PROBE_ID, QUESTION, parameters, MODULE)
    rows = []
    for window in WINDOW_S:
        _path, head = load_head(window, root)
        for session in BRIDGE:
            cached = load_cache(session, window, root)
            scores = logits_for(head, cached["emb"])
            labels = cached["label"]
            auc = _auc(labels, scores)
            role = "train" if session in TRAIN else "calibrate" if session in CALIBRATE else "develop" if session in DEVELOP else "control"
            rows.append(
                {
                    "window_s": window,
                    "session": session,
                    "role": role,
                    "commercial_n": int((labels == 1).sum()),
                    "program_n": int((labels == 0).sum()),
                    "auc": None if auc is None else round(auc, 6),
                }
            )
            print(f"  w{window:.0f} {session} auc {rows[-1]['auc']}", flush=True)
    develop = [row for row in rows if row["role"] == "develop" and row["auc"] is not None]
    by_window = {}
    for window in WINDOW_S:
        cells = [row["auc"] for row in develop if row["window_s"] == window]
        lowest = min(cells) if cells else None
        by_window[str(window)] = {"lowest_october_auc": lowest, "games": len(cells)}
    result = {
        "probe_id": PROBE_ID,
        "inputs": {str(window): input_hashes(window, BRIDGE, root) for window in WINDOW_S},
        "rows": rows,
        "october_by_window": by_window,
        "control_session": CONTROL[0],
    }
    finish_probe(folder, PROBE_ID, QUESTION, parameters, result, MODULE)
    return result
