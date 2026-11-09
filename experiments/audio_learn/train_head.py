"""Train the causal head on cached embeddings. Prime and ESPN are refused."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

from experiments.audio_learn.extract import load_cache
from experiments.audio_learn.head import CausalHead, save_head
from experiments.audio_learn.splits import (
    CALIBRATE,
    EVAL,
    HIDDEN,
    HOP_S,
    SEED,
    SEQUENCE,
    TRAIN,
    assert_split,
)
from experiments.audio_learn.windows import consecutive_end_indices
from tools.gpu_lab.splits import HOLDOUTS

EPOCHS = 8
PER_CLASS = 4000
BATCH = 64


def _indexes(caches: list[dict]) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    commercial = []
    program = []
    for cache_index, cache in enumerate(caches):
        for end in consecutive_end_indices(cache["t"], SEQUENCE, HOP_S):
            label = int(cache["label"][end])
            if label == 1:
                commercial.append((cache_index, end))
            elif label == 0:
                program.append((cache_index, end))
    if not commercial or not program:
        raise RuntimeError("the training games need both commercial and program sequences")
    return commercial, program


def _batch(caches: list[dict], picks: list[tuple[int, int]], device: torch.device) -> tuple[torch.Tensor, torch.Tensor]:
    dim = caches[0]["emb"].shape[1]
    waves = np.zeros((len(picks), SEQUENCE, dim), dtype=np.float32)
    labels = np.full((len(picks), SEQUENCE), -1, dtype=np.int8)
    for row, (cache_index, end) in enumerate(picks):
        cache = caches[cache_index]
        left = end - SEQUENCE + 1
        waves[row] = cache["emb"][left : end + 1]
        labels[row] = cache["label"][left : end + 1]
    return torch.from_numpy(waves).to(device), torch.from_numpy(labels).to(device)


def train_head(paths: list[Path], out: Path, sessions: tuple[str, ...] = TRAIN) -> dict:
    assert_split()
    if any(session in EVAL or session in CALIBRATE or session in HOLDOUTS for session in sessions):
        raise RuntimeError("the head fit was handed a calibration, Prime, or sealed game")
    if list(sessions) != list(TRAIN):
        raise RuntimeError("this proof fits the head on the declared training games only")
    if not torch.cuda.is_available():
        raise RuntimeError("head training needs the CUDA device")
    device = torch.device("cuda")
    caches = [load_cache(path) for path in paths]
    commercial, program = _indexes(caches)
    head = CausalHead(caches[0]["emb"].shape[1], HIDDEN).to(device)
    optimizer = torch.optim.AdamW(head.parameters(), lr=1e-3, weight_decay=1e-4)
    rng = np.random.default_rng(SEED)
    history = []
    for epoch in range(EPOCHS):
        order_c = commercial.copy()
        order_p = program.copy()
        rng.shuffle(order_c)
        rng.shuffle(order_p)
        count = min(PER_CLASS, len(order_c), len(order_p))
        picks = order_c[:count] + order_p[:count]
        rng.shuffle(picks)
        total = 0.0
        seen = 0
        head.train()
        for start in range(0, len(picks), BATCH):
            batch = picks[start : start + BATCH]
            waves, labels = _batch(caches, batch, device)
            optimizer.zero_grad(set_to_none=True)
            logits = head(waves)
            mask = labels >= 0
            if int(mask.sum()) == 0:
                continue
            loss = F.binary_cross_entropy_with_logits(logits[mask], labels[mask].float())
            loss.backward()
            optimizer.step()
            total += float(loss.detach()) * int(mask.sum())
            seen += int(mask.sum())
        mean = total / seen if seen else None
        history.append(mean)
        print(f"head epoch {epoch + 1}/{EPOCHS} loss {mean:.4f} sequences {count * 2}", flush=True)
    head.eval()
    save_head(out, head)
    return {
        "epochs": EPOCHS,
        "per_class": PER_CLASS,
        "sequence": SEQUENCE,
        "hidden": HIDDEN,
        "commercial_sequences": len(commercial),
        "program_sequences": len(program),
        "loss": history,
        "checkpoint": str(out),
    }
