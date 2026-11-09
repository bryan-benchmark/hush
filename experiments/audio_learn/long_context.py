"""One longer causal history on the frozen embeddings.

The published head reads 16 embeddings. Each embedding is 4 seconds, and they
are 0.25 seconds apart, so that head already hears 7.75 seconds. This head
hears 30 seconds: 105 embeddings, still ending at the decision, still with no
future audio. The encoder, the training games, the controller, and the frozen
checkpoint stay as they are.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

from experiments.audio_learn.encoder import DATA_ROOT
from experiments.audio_learn.extract import load_cache
from experiments.audio_learn.head import CausalHead, load_head, probabilities, save_head
from experiments.audio_learn.splits import EVAL, HIDDEN, HOP_S, SEED, TRAIN, WINDOW_S, assert_split
from experiments.audio_learn.studio_fit import _pack, _score_array
from experiments.audio_learn.train_head import BATCH, EPOCHS, PER_CLASS
from experiments.audio_learn.windows import consecutive_end_indices, lookback_bounds

# (105 - 1) hops of 0.25s plus the 4s embedding = 30.0s of audio ending at the decision.
LENGTH = 105
HEAD_PATH = DATA_ROOT / "checkpoints" / "long_context_head.pt"
OUT_DIR = DATA_ROOT / "long_context"
SCENES = (
    ("odell", "hush_20260924_220624", 7035.0, 7095.2),
    ("whitworth", "hush_20260924_220624", 7406.8, 7436.2),
    ("palmer", "hush_20260924_220624", 6180.7, 6207.8),
)


def history_seconds(length: int) -> float:
    return (length - 1) * HOP_S + WINDOW_S


def _indexes(caches: list[dict]) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    commercial = []
    program = []
    for cache_index, cache in enumerate(caches):
        for end in consecutive_end_indices(cache["t"], LENGTH, HOP_S):
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
    waves = np.zeros((len(picks), LENGTH, dim), dtype=np.float32)
    labels = np.full((len(picks), LENGTH), -1, dtype=np.int8)
    for row, (cache_index, end) in enumerate(picks):
        cache = caches[cache_index]
        left = end - LENGTH + 1
        waves[row] = cache["emb"][left : end + 1]
        labels[row] = cache["label"][left : end + 1]
    return torch.from_numpy(waves).to(device), torch.from_numpy(labels).to(device)


def train(out: Path = HEAD_PATH) -> dict:
    assert_split()
    if not torch.cuda.is_available():
        raise RuntimeError("head training needs the CUDA device")
    device = torch.device("cuda")
    caches = [load_cache(DATA_ROOT / "embeddings" / "frozen" / f"{session}.npz") for session in TRAIN]
    commercial, program = _indexes(caches)
    head = CausalHead(caches[0]["emb"].shape[1], HIDDEN).to(device)
    head.sequence = LENGTH
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
            waves, labels = _batch(caches, picks[start : start + BATCH], device)
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
        print(f"long context epoch {epoch + 1}/{EPOCHS} loss {mean:.4f}", flush=True)
    head.eval()
    save_head(out, head)
    return {
        "history_s": history_seconds(LENGTH),
        "published_history_s": history_seconds(16),
        "sequence": LENGTH,
        "epochs": EPOCHS,
        "per_class": PER_CLASS,
        "commercial_sequences": len(commercial),
        "program_sequences": len(program),
        "loss": history,
        "checkpoint": str(out),
    }


def _nearest(times: np.ndarray, scores: np.ndarray, moment: float) -> tuple[float, float]:
    index = int(np.argmin(np.abs(times - moment)))
    return float(times[index]), float(scores[index])


def _scene(name: str, session: str, start: float, end: float, times: np.ndarray, scores: np.ndarray, length: int) -> dict:
    mask = (times >= start) & (times < end)
    chosen = scores[mask]
    points = []
    for fraction in (0.0, 0.25, 0.5, 0.75, 1.0):
        moment = start + (end - start) * fraction
        stamp, probability = _nearest(times, scores, moment)
        index = int(np.argmin(np.abs(times - stamp)))
        left, right = lookback_bounds(times, index, length, HOP_S)
        heard = float(times[right - 1] - times[left]) + WINDOW_S
        points.append(
            {
                "place": ("start", "quarter", "middle", "three_quarter", "end")[int(fraction * 4)],
                "t": round(stamp, 1),
                "p": round(probability, 3),
                "history_s": round(heard, 2),
            }
        )
    return {
        "name": name,
        "session": session,
        "start_s": start,
        "end_s": end,
        "p_median": None if chosen.size == 0 else round(float(np.median(chosen)), 3),
        "p_min": None if chosen.size == 0 else round(float(chosen.min()), 3),
        "share_at_least_0.90": None if chosen.size == 0 else round(float(np.mean(chosen >= 0.90)), 3),
        "points": points,
    }


def score(head_path: Path) -> dict:
    device = torch.device("cuda")
    head = load_head(head_path, device)
    if int(head.sequence) != LENGTH:
        raise RuntimeError("the long-context checkpoint does not carry the 30-second history")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fresh_rows = []
    frozen_rows = []
    scenes = {"frozen": [], "long_context": []}
    for session in EVAL:
        cache = load_cache(DATA_ROOT / "embeddings" / "frozen" / f"{session}.npz")
        scores = probabilities(head, cache["emb"], cache["t"], device)
        np.savez(OUT_DIR / f"{session}.npz", t=cache["t"], p=scores, label=cache["label"])
        fresh_rows.append(_score_array(session, cache["t"], scores))
        prior = np.load(DATA_ROOT / "predictions" / "frozen" / f"{session}.npz")
        frozen_rows.append(_score_array(session, prior["t"], prior["p"]))
        for name, scene_session, start, end in SCENES:
            if scene_session != session:
                continue
            scenes["frozen"].append(_scene(name, session, start, end, prior["t"], prior["p"], 16))
            scenes["long_context"].append(_scene(name, session, start, end, cache["t"], scores, LENGTH))
    return {
        "frozen_on_original_gold": _pack(frozen_rows),
        "long_context_on_original_gold": _pack(fresh_rows),
        "scenes": scenes,
    }


def main() -> None:
    info = train()
    scored = score(Path(info["checkpoint"]))
    payload = {"train": info, "score": scored}
    path = OUT_DIR / "result.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(scored, indent=2), flush=True)


if __name__ == "__main__":
    main()
