"""Live frame_mn10 + frozen GRU head for home-prod mute.

Reads float32 mono at 16 kHz on stdin. Writes one JSON object per line.
Uses the locked 0.90/0.50 × 8/2 controller from the kept research stack.
"""

from __future__ import annotations

import json
import os
import sys
import time
from collections import deque
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from ohush_live.research_muter import (  # noqa: E402
    CACHE,
    CONTEXT_S,
    HEAD,
    HOP_S,
    SEQUENCE,
    SR,
    WEIGHTS,
    WINDOW_S,
    LiveController,
    assets_ready,
)


def _device():
    import torch

    if torch.cuda.is_available():
        return torch.device("cuda")
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        # Smoke one tiny op; fall back to CPU if MPS is flaky for STFT/mel.
        try:
            x = torch.zeros(1, device="mps")
            _ = (x + 1).cpu()
            return torch.device("mps")
        except Exception:
            return torch.device("cpu")
    return torch.device("cpu")


def main() -> None:
    ok, detail = assets_ready()
    if not ok:
        print(json.dumps({"family": "research", "available": False, "error": detail}), flush=True)
        return

    import torch

    import experiments.audio_learn.encoder as encoder_mod
    from experiments.audio_learn.encoder import last_frame, load_encoder
    from experiments.audio_learn.head import load_head

    torch.set_num_threads(1)
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    os.environ.setdefault("MKL_NUM_THREADS", "1")
    torch.set_grad_enabled(False)

    device = _device()
    encoder_mod.WEIGHTS = WEIGHTS
    try:
        encoder = load_encoder(device)
        head = load_head(HEAD, device)
    except Exception as exc:
        print(json.dumps({"family": "research", "available": False, "error": str(exc)}), flush=True)
        return

    window_n = int(round(WINDOW_S * SR))
    context_n = int(round(CONTEXT_S * SR))
    hop_n = int(round(HOP_S * SR))
    ring = np.zeros(0, dtype=np.float32)
    seen = 0
    next_end = WINDOW_S
    embeds: deque[np.ndarray] = deque(maxlen=SEQUENCE)
    controller = LiveController()

    print(
        json.dumps(
            {
                "family": "research",
                "available": True,
                "device": str(device),
                "controller": {
                    "on": controller.on,
                    "off": controller.off,
                    "on_streak": controller.on_streak,
                    "off_streak": controller.off_streak,
                    "cooldown_s": controller.cooldown_s,
                },
                "weights": str(WEIGHTS),
                "head": str(HEAD),
            }
        ),
        flush=True,
    )

    while True:
        block = sys.stdin.buffer.read(hop_n * 4)
        if not block:
            return
        samples = np.frombuffer(block, dtype=np.float32).copy()
        ring = np.concatenate([ring, samples])
        seen += samples.size
        now = seen / SR
        if now + 1e-9 < next_end or ring.size < window_n:
            continue

        ctx = np.zeros(context_n, dtype=np.float32)
        ctx[-window_n:] = ring[-window_n:]
        t0 = time.perf_counter()
        try:
            with torch.inference_mode():
                wave = torch.from_numpy(ctx[None, :]).to(device)
                emb = last_frame(encoder, wave).float().cpu().numpy()[0]
                embeds.append(emb)
                seq = np.zeros((1, SEQUENCE, emb.shape[0]), dtype=np.float32)
                chunk = np.stack(list(embeds))
                seq[0, -len(chunk) :] = chunk
                logit = head(torch.from_numpy(seq).to(device))[:, -1]
                probability = float(torch.sigmoid(logit).cpu())
        except Exception as exc:
            print(
                json.dumps(
                    {
                        "family": "research",
                        "available": False,
                        "error": str(exc),
                        "t": round(next_end, 3),
                    }
                ),
                flush=True,
            )
            return
        latency_ms = (time.perf_counter() - t0) * 1000.0
        decision = controller.step(next_end, probability)
        covering = decision["action"] == "cover"
        print(
            json.dumps(
                {
                    "family": "research",
                    "t": round(next_end, 3),
                    "probability": round(probability, 4),
                    "action": decision["action"],
                    "transition": decision["transition"],
                    "force_play": decision["force_play"],
                    "departure": round(probability, 4),
                    "strong_departure": covering,
                    "return": round(1.0 - probability, 4),
                    "strong_return": not covering,
                    "latency_ms": round(latency_ms, 1),
                    "device": str(device),
                }
            ),
            flush=True,
        )
        next_end += HOP_S
        # Keep a little past audio; drop the rest.
        keep = window_n + hop_n * 4
        if ring.size > keep:
            ring = ring[-keep:]


if __name__ == "__main__":
    main()
