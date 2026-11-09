"""Cache last-frame embeddings. Each stamp uses audio that has already ended."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import torch

from experiments.audio_learn.encoder import DATA_ROOT, embed_numpy, load_encoder
from experiments.audio_learn.splits import (
    CONTEXT_S,
    EVAL,
    HOLDOUTS,
    HOP_S,
    SR,
    WINDOW_S,
    assert_split,
)
from experiments.audio_learn.windows import pack_past_batch
from experiments.ledger import sha256_file
from experiments.nfl75.inventory import coverage_by_session
from tools.gpu_lab.audio_load import load_coverage
from tools.gpu_lab.decisions import decision_times, label_action
from tools.gpu_lab.eligibility import build_masks

BATCH = 16


def cache_path(kind: str, session: str, root: Path = DATA_ROOT) -> Path:
    return root / "embeddings" / kind / f"{session}.npz"


def _sidecar(path: Path) -> dict | None:
    meta = path.with_suffix(".json")
    if path.is_file() and meta.is_file():
        return json.loads(meta.read_text(encoding="utf-8"))
    return None


def extract_sessions(
    sessions: tuple[str, ...] | list[str],
    kind: str,
    weights: Path | None,
    stamp: str,
    root: Path = DATA_ROOT,
    batch: int = BATCH,
) -> list[Path]:
    if not torch.cuda.is_available():
        raise RuntimeError("frame_mn10 extraction needs the CUDA device")
    pending = []
    done = []
    for session in sessions:
        _guard(session, kind)
        path = cache_path(kind, session, root)
        existing = _sidecar(path)
        if existing and existing.get("encoder_stamp") == stamp and existing.get("hop_s") == HOP_S:
            print(f"cached {kind} {session}", flush=True)
            done.append(path)
        else:
            pending.append(session)
    if not pending:
        return done
    device = torch.device("cuda")
    torch.backends.cudnn.benchmark = True
    model = load_encoder(device, weights)
    written = []
    try:
        for session in pending:
            written.append(_extract_loaded(session, kind, stamp, model, device, root, batch))
    finally:
        del model
        torch.cuda.empty_cache()
    return done + written


def _guard(session: str, kind: str) -> None:
    assert_split()
    if session in HOLDOUTS:
        raise RuntimeError(f"refusing sealed holdout {session}")
    if session in EVAL and kind not in ("frozen", "finetuned"):
        raise RuntimeError(f"refusing to embed {session} for {kind}")


def _extract_loaded(session, kind, stamp, model, device, root: Path, batch: int) -> Path:
    _guard(session, kind)
    path = cache_path(kind, session, root)
    mask = next(row for row in build_masks([session]) if row["session"] == session)
    coverage = coverage_by_session()[session]
    times = decision_times(coverage[0], coverage[1], WINDOW_S, HOP_S)
    labels = np.asarray([label_action(mask, t, HOP_S) for t in times], dtype=np.int8)
    print(f"load {session} {coverage[1] - coverage[0]:.0f}s -> {len(times)} decisions", flush=True)
    audio = load_coverage(session, coverage[0], coverage[1])
    parts = []
    for start in range(0, len(times), batch):
        chunk = times[start : start + batch]
        waves = pack_past_batch(audio, coverage[0], chunk, WINDOW_S, CONTEXT_S, SR)
        parts.append(embed_numpy(model, device, waves))
        if start % (batch * 50) == 0:
            print(f"  {session} {start}/{len(times)}", flush=True)
    embedding = np.concatenate(parts, axis=0).astype(np.float16)
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(path, t=np.asarray(times, dtype=np.float64), emb=embedding, label=labels)
    path.with_suffix(".json").write_text(
        json.dumps(
            {
                "session": session,
                "kind": kind,
                "encoder_stamp": stamp,
                "window_s": WINDOW_S,
                "context_s": CONTEXT_S,
                "hop_s": HOP_S,
                "sr": SR,
                "n": len(times),
                "causal": "audio [t-window, t) right-aligned in a 10s buffer; front pad is silence",
                "commercial_rows": int((labels == 1).sum()),
                "program_rows": int((labels == 0).sum()),
                "excluded_rows": int((labels < 0).sum()),
            }
        ),
        encoding="utf-8",
    )
    print(f"wrote {path}", flush=True)
    return path


def extract_session(
    session: str,
    kind: str,
    weights: Path | None,
    stamp: str,
    root: Path = DATA_ROOT,
    batch: int = BATCH,
) -> Path:
    return extract_sessions([session], kind, weights, stamp, root, batch)[0]


def load_cache(path: Path) -> dict:
    data = np.load(path)
    return {
        "t": data["t"].astype(np.float64),
        "emb": data["emb"].astype(np.float32),
        "label": data["label"].astype(np.int8),
        "sha256": sha256_file(path),
    }


def stamp_for(weights: Path | None, pretrained_sha: str) -> str:
    if weights is None:
        return pretrained_sha
    return sha256_file(weights)
