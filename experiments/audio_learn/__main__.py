"""Run OHUSH_AUDIO_LEARNING_001.

    .\\.venv\\Scripts\\python.exe -m experiments.audio_learn
"""

from __future__ import annotations

import json

import numpy as np
import torch

from experiments.audio_learn.encoder import DATA_ROOT, checkpoint_sha, embed_numpy, load_encoder
from experiments.audio_learn.evaluate import REPORT_DIR, run_evaluation
from experiments.audio_learn.extract import cache_path, extract_sessions, stamp_for
from experiments.audio_learn.finetune import finetune
from experiments.audio_learn.report import write_report
from experiments.audio_learn.splits import CALIBRATE, EVAL, SR, TRAIN, assert_split
from experiments.audio_learn.train_head import train_head
from experiments.audio_learn.windows import pack_past_window
from experiments.ledger import sha256_file


def _smoke() -> None:
    if not torch.cuda.is_available():
        raise SystemExit("CUDA is not available")
    device = torch.device("cuda")
    model = load_encoder(device)
    audio = np.random.default_rng(0).normal(0, 0.02, size=12 * SR).astype(np.float32)
    past = pack_past_window(audio, 0.0, 4.0)
    future = audio.copy()
    future[4 * SR :] = 3.0
    past_again = pack_past_window(future, 0.0, 4.0)
    if not np.array_equal(past, past_again):
        raise SystemExit("a window copied audio from after the decision")
    embedded = embed_numpy(model, device, np.stack([past, past_again]))
    if not np.allclose(embedded[0], embedded[1], atol=1e-5):
        raise SystemExit("the encoder changed when future audio changed")
    if not np.isfinite(embedded).all():
        raise SystemExit("the encoder returned a non-finite embedding")
    print(f"smoke ok embed_dim={embedded.shape[1]}", flush=True)
    del model
    torch.cuda.empty_cache()


def _cache_rows(kind: str, sessions) -> list[dict]:
    rows = []
    for session in sessions:
        meta = json.loads(cache_path(kind, session).with_suffix(".json").read_text(encoding="utf-8"))
        rows.append(
            {
                "session": session,
                "commercial_rows": meta["commercial_rows"],
                "program_rows": meta["program_rows"],
                "excluded_rows": meta["excluded_rows"],
                "n": meta["n"],
            }
        )
    return rows


def main() -> None:
    assert_split()
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    _smoke()
    pretrained = checkpoint_sha()
    sessions = list(TRAIN + CALIBRATE + EVAL)
    frozen_stamp = stamp_for(None, pretrained)
    print("extract frozen", flush=True)
    extract_sessions(sessions, "frozen", None, frozen_stamp)
    frozen_head = DATA_ROOT / "checkpoints" / "frozen_head.pt"
    print("train frozen head", flush=True)
    frozen_train = train_head([cache_path("frozen", session) for session in TRAIN], frozen_head)
    encoder_path = DATA_ROOT / "checkpoints" / "finetuned_encoder.pt"
    print("finetune tail", flush=True)
    finetune_receipt = finetune(encoder_path)
    tuned_stamp = stamp_for(encoder_path, pretrained)
    print("extract finetuned", flush=True)
    extract_sessions(sessions, "finetuned", encoder_path, tuned_stamp)
    tuned_head = DATA_ROOT / "checkpoints" / "finetuned_head.pt"
    print("train finetuned head", flush=True)
    tuned_train = train_head([cache_path("finetuned", session) for session in TRAIN], tuned_head)
    print("evaluate", flush=True)
    metrics = run_evaluation(frozen_head, tuned_head)
    inventory = {
        "model": "frame_mn10",
        "checkpoint_sha256": pretrained,
        "frozen_head": str(frozen_head),
        "frozen_head_sha256": sha256_file(frozen_head),
        "finetuned_encoder": str(encoder_path),
        "finetuned_encoder_sha256": sha256_file(encoder_path),
        "finetuned_head": str(tuned_head),
        "finetuned_head_sha256": sha256_file(tuned_head),
        "caches": _cache_rows("frozen", sessions),
        "frozen_train": frozen_train,
        "finetune": finetune_receipt,
        "tuned_train": tuned_train,
    }
    path = write_report(inventory, metrics)
    print(path, flush=True)
    print(metrics["recommendation"], flush=True)


if __name__ == "__main__":
    main()
