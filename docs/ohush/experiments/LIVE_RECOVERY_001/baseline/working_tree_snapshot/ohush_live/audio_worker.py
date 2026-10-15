"""Exp003-style audio distance for OHUSH_LIVE_V0.

Reads float32 mono at 32 kHz on stdin. Writes one JSON object per line on stdout.
Does not write into experiments/.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from hush.program_cloud import MEMORY_S, SR, WINDOW_S  # noqa: E402
from ohush_live.policy import AUDIO_MIN_REFERENCE_S, AUDIO_RETURN, AUDIO_STRONG  # noqa: E402

CHECKPOINT = REPO / "experiments" / "exp003" / "models" / "Cnn14_mAP=0.431.pth"


def main() -> None:
    if not CHECKPOINT.is_file():
        print(json.dumps({"family": "audio", "available": False, "error": "checkpoint missing"}), flush=True)
        return
    import torch
    import torch.backends.nnpack as nnpack
    from panns_inference import AudioTagging

    labels_csv = Path.home() / "panns_data" / "class_labels_indices.csv"
    if not labels_csv.is_file() or labels_csv.stat().st_size < 1000:
        import urllib.request

        labels_csv.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(
            "http://storage.googleapis.com/us_audioset/youtube_corpus/v1/csv/class_labels_indices.csv",
            labels_csv,
        )
    nnpack.set_flags(False)
    # One thread — many daemons × 4 threads was jetsamming the MacBook.
    torch.set_num_threads(1)
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    os.environ.setdefault("MKL_NUM_THREADS", "1")
    torch.set_grad_enabled(False)
    tagger = AudioTagging(checkpoint_path=str(CHECKPOINT), device="cpu")
    window = int(WINDOW_S * SR)
    hop = SR
    buf = np.zeros(0, dtype=np.float32)
    embeddings: list[np.ndarray] = []
    ends: list[float] = []
    seen = 0
    next_end = WINDOW_S
    print(json.dumps({"family": "audio", "available": True}), flush=True)
    while True:
        block = sys.stdin.buffer.read(hop * 4)
        if not block:
            return
        buf = np.concatenate([buf, np.frombuffer(block, dtype=np.float32).copy()])
        seen += len(block) // 4
        now = seen / SR
        if now + 1e-6 < next_end or buf.size < window:
            continue
        frame = buf[-window:]
        _clip, embedding = tagger.inference(frame.astype(np.float32)[None, :])
        del _clip
        vec = np.asarray(embedding, dtype=np.float64).reshape(-1)
        norm = np.linalg.norm(vec)
        if norm == 0.0:
            continue
        vec = vec / norm
        embeddings.append(vec)
        ends.append(next_end)
        score = _latest(np.stack(embeddings), np.asarray(ends))
        strong = score is not None and score >= AUDIO_STRONG
        back = score is not None and score <= AUDIO_RETURN
        print(
            json.dumps(
                {
                    "family": "audio",
                    "t": round(next_end, 3),
                    "departure": None if score is None else round(score, 4),
                    "strong_departure": bool(strong),
                    "return": None if score is None else round(score, 4),
                    "strong_return": bool(back),
                }
            ),
            flush=True,
        )
        next_end += 1.0
        if buf.size > window + hop * 2:
            buf = buf[-(window + hop) :]


def _latest(matrix: np.ndarray, ends: np.ndarray) -> float | None:
    start = float(ends[-1] - WINDOW_S)
    lo = start - MEMORY_S
    chosen = np.flatnonzero((ends <= start + 1e-9) & (ends > lo))
    if chosen.size == 0:
        return None
    span = float(ends[chosen[-1]] - ends[chosen[0]])
    if span + 1e-9 < AUDIO_MIN_REFERENCE_S:
        return None
    centroid = matrix[chosen].mean(axis=0)
    norm = np.linalg.norm(centroid)
    if norm == 0.0:
        return None
    return 1.0 - float(np.dot(matrix[-1], centroid / norm))


if __name__ == "__main__":
    main()
