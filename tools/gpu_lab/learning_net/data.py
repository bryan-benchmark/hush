"""Shared readers for learning-net probes. Holdouts are refused by the mask builder."""

from __future__ import annotations

from pathlib import Path

import joblib
import numpy as np

from experiments.ledger import sha256_file

from tools.gpu_lab.eligibility import build_masks
from tools.gpu_lab.embed import cache_path
from tools.gpu_lab.prepare import DATA_ROOT
from tools.gpu_lab.splits import CALIBRATE, CONTROL, DEVELOP, TRAIN, WINDOW_S
from tools.gpu_lab.train import model_path

BRIDGE = list(TRAIN + CALIBRATE + DEVELOP + CONTROL)


def bridge_masks() -> dict[str, dict]:
    return {row["session"]: row for row in build_masks(BRIDGE)}


def load_cache(session: str, window_s: float, root: Path = DATA_ROOT) -> dict:
    path = cache_path(session, window_s, root)
    data = np.load(path)
    return {
        "path": path,
        "sidecar": path.with_suffix(".json"),
        "t": data["t"].astype(np.float64),
        "emb": data["emb"].astype(np.float32),
        "label": data["label"].astype(np.int8),
    }


def load_head(window_s: float, root: Path = DATA_ROOT):
    path = model_path(window_s, root)
    return path, joblib.load(path)


def logits_for(head, embeddings: np.ndarray) -> np.ndarray:
    return np.asarray(head.decision_function(embeddings), dtype=np.float64)


def input_hashes(window_s: float, sessions: list[str], root: Path = DATA_ROOT) -> dict:
    model = model_path(window_s, root)
    rows = []
    for session in sessions:
        path = cache_path(session, window_s, root)
        rows.append(
            {
                "session": session,
                "npz_sha256": sha256_file(path),
                "sidecar_sha256": sha256_file(path.with_suffix(".json")),
            }
        )
    return {"model_sha256": sha256_file(model), "caches": rows}
