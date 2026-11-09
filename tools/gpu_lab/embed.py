"""Cache frozen AST embeddings for past-only windows.

Shorter than the model's native 10.24 seconds is zero-padded by the feature
extractor. The padding is silence, not future audio. The stored vector is the
CLS token, stamped at the end of the real window.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from experiments.ledger import RECORDINGS, sha256_file
from hush.audio import find_session

from tools.gpu_lab.audio_load import clip_window, load_coverage
from tools.gpu_lab.decisions import decision_times, label_action
from tools.gpu_lab.eligibility import build_masks
from tools.gpu_lab.ladder import pairs
from tools.gpu_lab.prepare import DATA_ROOT
from tools.gpu_lab.splits import CALIBRATE, CONTROL, DEVELOP, HOLDOUTS, TRAIN, WINDOW_S

MODEL_ID = "MIT/ast-finetuned-audioset-10-10-0.4593"
BATCH = 8


def cache_path(session: str, window_s: float, root: Path = DATA_ROOT) -> Path:
    return root / "embeddings" / session / f"w{int(window_s)}.npz"


def sessions_for_embed() -> list[str]:
    return list(TRAIN + CALIBRATE + DEVELOP + CONTROL)


def _sidecar(path: Path) -> dict | None:
    meta = path.with_suffix(".json")
    if not path.is_file() or not meta.is_file():
        return None
    return json.loads(meta.read_text(encoding="utf-8"))


def _encode(model, extractor, device, clips: list[np.ndarray]) -> np.ndarray:
    import torch

    inputs = extractor(clips, sampling_rate=16000, return_tensors="pt", padding=True)
    inputs = {key: value.to(device) for key, value in inputs.items()}
    hidden = model(**inputs).last_hidden_state
    return hidden[:, 0, :].float().cpu().numpy()


def embed_session(session: str, window_s: float, model, extractor, device, root: Path = DATA_ROOT, batch: int = BATCH) -> Path:
    if session in HOLDOUTS:
        raise RuntimeError(f"refusing sealed holdout {session}")
    mask = next(row for row in build_masks([session]) if row["session"] == session)
    coverage = pairs(mask, "coverage")[0]
    folder = find_session(RECORDINGS, session)
    session_hash = sha256_file(folder / "session.json")
    path = cache_path(session, window_s, root)
    existing = _sidecar(path)
    if existing and existing.get("session_json_sha256") == session_hash and existing.get("model") == MODEL_ID:
        print(f"cached {session} window {window_s:.0f}s", flush=True)
        return path
    times = decision_times(coverage[0], coverage[1], window_s)
    labels = np.asarray([label_action(mask, t) for t in times], dtype=np.int8)
    print(f"load {session} {coverage[1] - coverage[0]:.0f}s", flush=True)
    audio = load_coverage(session, coverage[0], coverage[1])
    vectors = []
    for start in range(0, len(times), batch):
        clips = [clip_window(audio, coverage[0], t, window_s) for t in times[start : start + batch]]
        vectors.append(_encode(model, extractor, device, clips))
        if start % (batch * 20) == 0:
            print(f"  {session} w{window_s:.0f} {start}/{len(times)}", flush=True)
    emb = np.concatenate(vectors, axis=0).astype(np.float16)
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(path, t=np.asarray(times, dtype=np.float32), emb=emb, label=labels)
    path.with_suffix(".json").write_text(
        json.dumps(
            {
                "model": MODEL_ID,
                "window_s": window_s,
                "session": session,
                "session_json_sha256": session_hash,
                "n": len(times),
                "embedding": "cls",
            }
        ),
        encoding="utf-8",
    )
    print(f"wrote {path} ({len(times)} decisions)", flush=True)
    return path


def embed_all(root: Path = DATA_ROOT) -> None:
    import torch
    from transformers import AutoFeatureExtractor, AutoModel

    if not torch.cuda.is_available():
        raise SystemExit("CUDA is not available. Bridge 0 embeds on the 4070.")
    device = torch.device("cuda")
    extractor = AutoFeatureExtractor.from_pretrained(MODEL_ID)
    model = AutoModel.from_pretrained(MODEL_ID).to(device).eval()
    for window in WINDOW_S:
        for session in sessions_for_embed():
            with torch.inference_mode():
                embed_session(session, window, model, extractor, device, root)
