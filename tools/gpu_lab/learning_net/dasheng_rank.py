"""Rank each game with a frozen Dasheng-base encoder.

The encoder is not fine-tuned. Each decision at time t uses audio [t-window, t)
and stores the mean of that window's tokens. A logistic head is fit on the
three training games only. October is described and does not choose a cutoff.
"""

from __future__ import annotations

import json
import os
import sys
from importlib.metadata import version
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression

from experiments.ledger import RECORDINGS, sha256_file, sha256_text
from tools.gpu_lab.audio_load import clip_window, load_coverage
from tools.gpu_lab.decisions import decision_times, label_action
from tools.gpu_lab.eligibility import build_masks
from tools.gpu_lab.embed import sessions_for_embed
from tools.gpu_lab.ladder import pairs
from tools.gpu_lab.learning_net.data import BRIDGE
from tools.gpu_lab.learning_net.log import finish_probe, open_probe
from tools.gpu_lab.prepare import DATA_ROOT
from tools.gpu_lab.splits import CALIBRATE, CONTROL, DEVELOP, HOLDOUTS, TRAIN, WINDOW_S

_SRC = Path(__file__).resolve().parents[3] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from hush.audio import find_session

MODULE = Path(__file__)
PROBE_ID = "dasheng_ranking"
QUESTION = "On frozen Dasheng-base vectors, do commercial seconds rank above program seconds inside each later game?"
ENCODER_ID = "dasheng_base"
CHECKPOINT = "https://zenodo.org/records/11511780/files/dasheng_base.pt?download=1"
EMBEDDING = "mean of encoder tokens over the past window"
BATCH = 16
AST_RANKING_FOLDER = "20261023T004935Z_ranking"
AST_RANKING_SHA256 = "477406f08d314fb0d9e26cda97ba48b58997a4a27323b5ffdca82336560c6153"


def cache_root(root: Path = DATA_ROOT) -> Path:
    return root / "embeddings_dasheng_base"


def cache_path(session: str, window_s: float, root: Path = DATA_ROOT, cache_name: str = "embeddings_dasheng_base") -> Path:
    return root / cache_name / session / f"w{int(window_s)}.npz"


def mean_tokens(tokens: np.ndarray) -> np.ndarray:
    if tokens.ndim != 3:
        raise ValueError(f"expected a batch of token sequences, got shape {tokens.shape}")
    return tokens.mean(axis=1)


def _sidecar(path: Path) -> dict | None:
    meta = path.with_suffix(".json")
    if not path.is_file() or not meta.is_file():
        return None
    return json.loads(meta.read_text(encoding="utf-8"))


def _write_cache(path: Path, times: list[float], emb: np.ndarray, labels: np.ndarray, sidecar: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".partial")
    with partial.open("wb") as handle:
        np.savez(handle, t=np.asarray(times, dtype=np.float32), emb=emb, label=labels)
    os.replace(partial, path)
    meta = path.with_suffix(".json")
    temporary = meta.with_name(meta.name + ".tmp")
    temporary.write_text(json.dumps(sidecar, indent=2, sort_keys=True), encoding="utf-8", newline="\n")
    os.replace(temporary, meta)


def _encode(model, device, clips: list[np.ndarray]) -> np.ndarray:
    import torch

    batch = torch.from_numpy(np.stack(clips)).to(device)
    tokens = model(batch)
    return mean_tokens(tokens.float().cpu().numpy()).astype(np.float16)


def embed_session(
    session: str,
    window_s: float,
    model,
    device,
    root: Path = DATA_ROOT,
    batch: int = BATCH,
    encoder_id: str = ENCODER_ID,
    checkpoint: str = CHECKPOINT,
    cache_name: str = "embeddings_dasheng_base",
) -> Path:
    if session in HOLDOUTS:
        raise RuntimeError(f"refusing sealed holdout {session}")
    mask = next(row for row in build_masks([session]) if row["session"] == session)
    coverage = pairs(mask, "coverage")[0]
    folder = find_session(RECORDINGS, session)
    session_hash = sha256_file(folder / "session.json")
    path = cache_path(session, window_s, root, cache_name)
    existing = _sidecar(path)
    if (
        existing
        and existing.get("session_json_sha256") == session_hash
        and existing.get("model") == encoder_id
        and existing.get("embedding") == EMBEDDING
        and existing.get("finetuned") is False
    ):
        print(f"cached {session} window {window_s:.0f}s", flush=True)
        return path
    times = decision_times(coverage[0], coverage[1], window_s)
    labels = np.asarray([label_action(mask, t) for t in times], dtype=np.int8)
    print(f"load {session} {coverage[1] - coverage[0]:.0f}s", flush=True)
    audio = load_coverage(session, coverage[0], coverage[1])
    vectors = []
    for start in range(0, len(times), batch):
        clips = [clip_window(audio, coverage[0], t, window_s) for t in times[start : start + batch]]
        vectors.append(_encode(model, device, clips))
        if start % (batch * 20) == 0:
            print(f"  {session} w{window_s:.0f} {start}/{len(times)}", flush=True)
    emb = np.concatenate(vectors, axis=0)
    _write_cache(
        path,
        times,
        emb,
        labels,
        {
            "checkpoint": checkpoint,
            "embedding": EMBEDDING,
            "finetuned": False,
            "model": encoder_id,
            "n": len(times),
            "session": session,
            "session_json_sha256": session_hash,
            "window_s": window_s,
        },
    )
    print(f"wrote {path} ({len(times)} decisions)", flush=True)
    return path


def embed_all(model, device, root: Path = DATA_ROOT, batch: int = BATCH, encoder_id: str = ENCODER_ID, checkpoint: str = CHECKPOINT, cache_name: str = "embeddings_dasheng_base") -> None:
    import torch

    for window in WINDOW_S:
        for session in sessions_for_embed():
            with torch.inference_mode():
                embed_session(session, window, model, device, root, batch, encoder_id, checkpoint, cache_name)


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


def _load_ast_rows(root: Path) -> list[dict]:
    path = root / "learning_net" / "probes" / AST_RANKING_FOLDER / "result.json"
    text = path.read_text(encoding="utf-8")
    digest = sha256_text(text)
    if digest != AST_RANKING_SHA256:
        raise RuntimeError(f"AST ranking hash {digest} does not match {AST_RANKING_SHA256}")
    return json.loads(text)["rows"]


def _fit_head(window_s: float, root: Path, cache_name: str = "embeddings_dasheng_base"):
    vectors = []
    labels = []
    for session in TRAIN:
        data = np.load(cache_path(session, window_s, root, cache_name))
        keep = data["label"] >= 0
        vectors.append(data["emb"][keep].astype(np.float32))
        labels.append(data["label"][keep])
    x = np.concatenate(vectors)
    y = np.concatenate(labels)
    head = LogisticRegression(max_iter=2000, class_weight="balanced")
    head.fit(x, y)
    return head, {
        "window_s": window_s,
        "rows": int(len(y)),
        "commercial_rows": int((y == 1).sum()),
        "program_rows": int((y == 0).sum()),
        "train_accuracy": round(float(head.score(x, y)), 4),
        "finetuned_encoder": False,
    }


def run(root: Path = DATA_ROOT) -> dict:
    import joblib
    import torch
    from dasheng import dasheng_base

    if not torch.cuda.is_available():
        raise SystemExit("CUDA is not available. Dasheng-base ranks on the 4070.")
    parameters = {
        "encoder": ENCODER_ID,
        "package_version": version("dasheng"),
        "checkpoint": CHECKPOINT,
        "embedding": EMBEDDING,
        "finetuned": False,
        "windows_s": list(WINDOW_S),
        "head": "logistic regression, class_weight balanced, training games only",
        "score": "logistic decision_function, higher means more commercial",
        "october_may_describe": True,
        "october_may_choose_cutoff": False,
        "sessions": BRIDGE,
        "compared_with": {"probe_id": "ranking", "folder": AST_RANKING_FOLDER, "result_sha256": AST_RANKING_SHA256},
        "dasheng_12b_started": False,
    }
    folder = open_probe(PROBE_ID, QUESTION, parameters, MODULE)
    device = torch.device("cuda")
    model = dasheng_base().to(device).eval()
    for parameter in model.parameters():
        parameter.requires_grad_(False)
    embed_all(model, device, root)
    del model
    torch.cuda.empty_cache()
    ast_rows = _load_ast_rows(root)
    ast_lookup = {(row["window_s"], row["session"]): row["auc"] for row in ast_rows}
    rows = []
    heads = []
    for window in WINDOW_S:
        head, trained = _fit_head(window, root)
        head_path = folder / f"w{int(window)}.joblib"
        joblib.dump(head, head_path)
        trained["head_sha256"] = sha256_file(head_path)
        heads.append(trained)
        print(f"fit window {window:.0f}s train accuracy {trained['train_accuracy']}", flush=True)
        for session in BRIDGE:
            data = np.load(cache_path(session, window, root))
            labels = data["label"].astype(np.int8)
            scores = np.asarray(head.decision_function(data["emb"].astype(np.float32)), dtype=np.float64)
            auc = _auc(labels, scores)
            rows.append(
                {
                    "window_s": window,
                    "session": session,
                    "role": _role(session),
                    "commercial_n": int((labels == 1).sum()),
                    "program_n": int((labels == 0).sum()),
                    "auc": None if auc is None else round(auc, 6),
                    "ast_auc": ast_lookup.get((window, session)),
                }
            )
            print(f"  w{window:.0f} {session} auc {rows[-1]['auc']} ast {rows[-1]['ast_auc']}", flush=True)
    by_window = []
    weak_sessions: list[str] = []
    for window in WINDOW_S:
        comparable = [row for row in rows if row["window_s"] == window and row["auc"] is not None and row["role"] in ("train", "calibrate")]
        floor = min(row["auc"] for row in comparable)
        below = [
            {"session": row["session"], "auc": row["auc"], "ast_auc": row["ast_auc"]}
            for row in rows
            if row["window_s"] == window and row["role"] == "develop" and row["auc"] is not None and row["auc"] < floor
        ]
        weak_sessions.extend(row["session"] for row in below)
        by_window.append({"window_s": window, "pre_october_floor_auc": floor, "october_below_pre_october_floor": below})
    caches = []
    for window in WINDOW_S:
        for session in BRIDGE:
            path = cache_path(session, window, root)
            caches.append(
                {
                    "window_s": window,
                    "session": session,
                    "npz_sha256": sha256_file(path),
                    "sidecar_sha256": sha256_file(path.with_suffix(".json")),
                }
            )
    result = {
        "probe_id": PROBE_ID,
        "encoder": ENCODER_ID,
        "finetuned": False,
        "heads": heads,
        "rows": rows,
        "ranking_against_pre_october_floor": by_window,
        "later_games_below_pre_october_floor": sorted(set(weak_sessions)),
        "caches": caches,
        "ast_ranking_result_sha256": AST_RANKING_SHA256,
        "control_session": CONTROL[0],
        "dasheng_12b_started": False,
        "october_may_choose_cutoff": False,
    }
    finish_probe(folder, PROBE_ID, QUESTION, parameters, result, MODULE)
    return result


LARGE_PROBE_ID = "dasheng_12b_ranking"
LARGE_QUESTION = "On frozen Dasheng-1.2B vectors, do the later games that Dasheng-base ranked weakly rank any higher?"
LARGE_ENCODER_ID = "dasheng_12B"
LARGE_CHECKPOINT = "https://zenodo.org/records/11511780/files/dasheng_12b.pt?download=1"
LARGE_CACHE = "embeddings_dasheng_12b"
LARGE_BATCH = 2
BASE_RANKING_FOLDER = "20261023T011903Z_dasheng_ranking"
BASE_RANKING_SHA256 = "128ac85b53cb4618215ed17dbd61fe9df57754c0d341329cd7c0a13bc157d18f"


def _load_base_rows(root: Path) -> list[dict]:
    path = root / "learning_net" / "probes" / BASE_RANKING_FOLDER / "result.json"
    text = path.read_text(encoding="utf-8")
    digest = sha256_text(text)
    if digest != BASE_RANKING_SHA256:
        raise RuntimeError(f"Dasheng-base ranking hash {digest} does not match {BASE_RANKING_SHA256}")
    return json.loads(text)["rows"]


def run_12b(root: Path = DATA_ROOT) -> dict:
    import joblib
    import torch
    from dasheng import dasheng_12B

    if not torch.cuda.is_available():
        raise SystemExit("CUDA is not available. Dasheng-1.2B ranks on the 4070.")
    parameters = {
        "encoder": LARGE_ENCODER_ID,
        "package_version": version("dasheng"),
        "checkpoint": LARGE_CHECKPOINT,
        "embedding": EMBEDDING,
        "finetuned": False,
        "batch": LARGE_BATCH,
        "windows_s": list(WINDOW_S),
        "head": "logistic regression, class_weight balanced, training games only",
        "score": "logistic decision_function, higher means more commercial",
        "october_may_describe": True,
        "october_may_choose_cutoff": False,
        "sessions": BRIDGE,
        "compared_with": [
            {"probe_id": "ranking", "folder": AST_RANKING_FOLDER, "result_sha256": AST_RANKING_SHA256},
            {"probe_id": "dasheng_ranking", "folder": BASE_RANKING_FOLDER, "result_sha256": BASE_RANKING_SHA256},
        ],
    }
    folder = open_probe(LARGE_PROBE_ID, LARGE_QUESTION, parameters, MODULE)
    device = torch.device("cuda")
    model = dasheng_12B().to(device).eval()
    for parameter in model.parameters():
        parameter.requires_grad_(False)
    embed_all(model, device, root, LARGE_BATCH, LARGE_ENCODER_ID, LARGE_CHECKPOINT, LARGE_CACHE)
    del model
    torch.cuda.empty_cache()
    ast_lookup = {(row["window_s"], row["session"]): row["auc"] for row in _load_ast_rows(root)}
    base_lookup = {(row["window_s"], row["session"]): row["auc"] for row in _load_base_rows(root)}
    rows = []
    heads = []
    for window in WINDOW_S:
        head, trained = _fit_head(window, root, LARGE_CACHE)
        head_path = folder / f"w{int(window)}.joblib"
        joblib.dump(head, head_path)
        trained["head_sha256"] = sha256_file(head_path)
        heads.append(trained)
        print(f"fit window {window:.0f}s train accuracy {trained['train_accuracy']}", flush=True)
        for session in BRIDGE:
            data = np.load(cache_path(session, window, root, LARGE_CACHE))
            labels = data["label"].astype(np.int8)
            scores = np.asarray(head.decision_function(data["emb"].astype(np.float32)), dtype=np.float64)
            auc = _auc(labels, scores)
            rows.append(
                {
                    "window_s": window,
                    "session": session,
                    "role": _role(session),
                    "commercial_n": int((labels == 1).sum()),
                    "program_n": int((labels == 0).sum()),
                    "auc": None if auc is None else round(auc, 6),
                    "dasheng_base_auc": base_lookup.get((window, session)),
                    "ast_auc": ast_lookup.get((window, session)),
                }
            )
            print(f"  w{window:.0f} {session} auc {rows[-1]['auc']} base {rows[-1]['dasheng_base_auc']}", flush=True)
    by_window = []
    weak_sessions: list[str] = []
    for window in WINDOW_S:
        comparable = [row for row in rows if row["window_s"] == window and row["auc"] is not None and row["role"] in ("train", "calibrate")]
        floor = min(row["auc"] for row in comparable)
        below = [
            {"session": row["session"], "auc": row["auc"], "dasheng_base_auc": row["dasheng_base_auc"], "ast_auc": row["ast_auc"]}
            for row in rows
            if row["window_s"] == window and row["role"] == "develop" and row["auc"] is not None and row["auc"] < floor
        ]
        weak_sessions.extend(row["session"] for row in below)
        by_window.append({"window_s": window, "pre_october_floor_auc": floor, "october_below_pre_october_floor": below})
    caches = []
    for window in WINDOW_S:
        for session in BRIDGE:
            path = cache_path(session, window, root, LARGE_CACHE)
            caches.append({"window_s": window, "session": session, "npz_sha256": sha256_file(path), "sidecar_sha256": sha256_file(path.with_suffix(".json"))})
    result = {
        "probe_id": LARGE_PROBE_ID,
        "encoder": LARGE_ENCODER_ID,
        "finetuned": False,
        "heads": heads,
        "rows": rows,
        "ranking_against_pre_october_floor": by_window,
        "later_games_below_pre_october_floor": sorted(set(weak_sessions)),
        "caches": caches,
        "dasheng_base_result_sha256": BASE_RANKING_SHA256,
        "ast_ranking_result_sha256": AST_RANKING_SHA256,
        "control_session": CONTROL[0],
        "october_may_choose_cutoff": False,
    }
    finish_probe(folder, LARGE_PROBE_ID, LARGE_QUESTION, parameters, result, MODULE)
    return result
