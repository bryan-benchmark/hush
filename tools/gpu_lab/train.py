"""Fit one logistic head per window on the training broadcasts only."""

from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np
from sklearn.linear_model import LogisticRegression

from tools.gpu_lab.embed import cache_path
from tools.gpu_lab.prepare import DATA_ROOT
from tools.gpu_lab.splits import TRAIN, WINDOW_S


def model_path(window_s: float, root: Path = DATA_ROOT) -> Path:
    return root / "models" / f"w{int(window_s)}.joblib"


def load_split(sessions: tuple[str, ...] | list[str], window_s: float, root: Path = DATA_ROOT) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[str]]:
    times = []
    vectors = []
    labels = []
    owners = []
    for session in sessions:
        path = cache_path(session, window_s, root)
        if not path.is_file():
            raise FileNotFoundError(path)
        data = np.load(path)
        keep = data["label"] >= 0
        times.append(data["t"][keep])
        vectors.append(data["emb"][keep].astype(np.float32))
        labels.append(data["label"][keep])
        owners.extend([session] * int(keep.sum()))
    return (
        np.concatenate(times),
        np.concatenate(vectors),
        np.concatenate(labels),
        owners,
    )


def fit_window(window_s: float, root: Path = DATA_ROOT) -> dict:
    _times, vectors, labels, _owners = load_split(TRAIN, window_s, root)
    if len(set(labels.tolist())) < 2:
        raise RuntimeError(f"window {window_s} has only one class in the training broadcasts")
    head = LogisticRegression(max_iter=2000, class_weight="balanced")
    head.fit(vectors, labels)
    path = model_path(window_s, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(head, path)
    trained = int((labels == 1).sum())
    receipt = {
        "window_s": window_s,
        "train_sessions": list(TRAIN),
        "rows": int(len(labels)),
        "commercial_rows": trained,
        "program_rows": int((labels == 0).sum()),
        "train_accuracy": round(float(head.score(vectors, labels)), 4),
    }
    path.with_suffix(".json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    print(
        f"fit window {window_s:.0f}s on {receipt['rows']} seconds "
        f"({receipt['commercial_rows']} commercial) train accuracy {receipt['train_accuracy']}",
        flush=True,
    )
    return receipt


def fit_all(root: Path = DATA_ROOT) -> list[dict]:
    return [fit_window(window, root) for window in WINDOW_S]
