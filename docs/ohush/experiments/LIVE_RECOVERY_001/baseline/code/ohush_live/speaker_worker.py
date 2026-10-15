"""Exp002-style speaker continuity for OHUSH_LIVE_V0.

Reads float32 mono at 16 kHz on stdin. Model files go under ohush_live/cache,
never under experiments/.
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

CACHE = REPO / "ohush_live" / "cache"
os.environ.setdefault("HF_HOME", str(CACHE / "hf"))
os.environ.setdefault("HUGGINGFACE_HUB_CACHE", str(CACHE / "hf" / "hub"))
os.environ.setdefault("TORCH_HOME", str(CACHE / "torch"))

from hush.speaker_memory import (  # noqa: E402
    CONTINUITY_WINDOW_S,
    DROP_MIN,
    DROP_WINDOW_S,
    EMBED_WIN_S,
    EMBEDDING_MODEL_ID,
    MATCH_COSINE,
    OnlineSpeakerMemory,
    RETURN_EVENT_MIN,
    SR,
    VAD_MIN_SILENCE_MS,
    VAD_MIN_SPEECH_MS,
    VAD_SPEECH_PAD_MS,
    VAD_THRESHOLD,
)
from ohush_live.policy import SPEAKER_DROP, SPEAKER_RETURN  # noqa: E402


def main() -> None:
    import torch
    from silero_vad import get_speech_timestamps, load_silero_vad
    from speechbrain.inference.speaker import EncoderClassifier

    torch.set_num_threads(4)
    torch.set_grad_enabled(False)
    torch.backends.nnpack.set_flags(False)
    vad = load_silero_vad()
    savedir = CACHE / "spkrec-ecapa-voxceleb"
    savedir.mkdir(parents=True, exist_ok=True)
    encoder = EncoderClassifier.from_hparams(
        source=EMBEDDING_MODEL_ID,
        savedir=str(savedir),
        run_opts={"device": "cpu"},
    )
    memory = OnlineSpeakerMemory()
    history: list[dict] = []
    continuity_hist: list[tuple[float, float]] = []
    buf = np.zeros(0, dtype=np.float32)
    seen = 0
    hop = SR
    win = int(EMBED_WIN_S * SR)
    print(json.dumps({"family": "speaker", "available": True, "match_cosine": MATCH_COSINE}), flush=True)
    while True:
        block = sys.stdin.buffer.read(hop * 4)
        if not block:
            return
        samples = np.frombuffer(block, dtype=np.float32).copy()
        buf = np.concatenate([buf, samples])
        seen += samples.size
        now = seen / SR
        if buf.size < win:
            continue
        frame = buf[-win:]
        speech = _speech_seconds(vad, frame)
        if speech < 0.5:
            print(
                json.dumps(
                    {
                        "family": "speaker",
                        "t": round(now, 3),
                        "departure": None,
                        "strong_departure": False,
                        "return": 0.0,
                        "strong_return": False,
                        "speech": False,
                    }
                ),
                flush=True,
            )
            buf = buf[-win * 4 :]
            continue
        start = now - EMBED_WIN_S
        emb = _embed(encoder, frame)
        row = memory.observe(emb, start, now)
        history.append(row)
        cont = _continuity(history, now)
        continuity_hist.append((now, cont if cont is not None else float("nan")))
        prior = [value for t, value in continuity_hist if now - DROP_WINDOW_S <= t < now - 1e-6 and np.isfinite(value)]
        drop = None
        strong = False
        if cont is not None and prior:
            drop = max(prior) - cont
            strong = drop + 1e-9 >= max(DROP_MIN, SPEAKER_DROP)
        ret = float(row["program_speaker_return_score"])
        print(
            json.dumps(
                {
                    "family": "speaker",
                    "t": round(now, 3),
                    "departure": None if drop is None else round(drop, 4),
                    "strong_departure": bool(strong),
                    "return": round(ret, 4),
                    "strong_return": ret + 1e-9 >= max(RETURN_EVENT_MIN, SPEAKER_RETURN),
                    "speech": True,
                    "continuity": None if cont is None else round(cont, 4),
                }
            ),
            flush=True,
        )
        if buf.size > win * 8:
            buf = buf[-win * 4 :]


def _speech_seconds(vad, frame: np.ndarray) -> float:
    import torch

    stamps = get_speech_timestamps(
        torch.from_numpy(frame),
        vad,
        threshold=VAD_THRESHOLD,
        sampling_rate=SR,
        min_speech_duration_ms=VAD_MIN_SPEECH_MS,
        min_silence_duration_ms=VAD_MIN_SILENCE_MS,
        speech_pad_ms=VAD_SPEECH_PAD_MS,
        return_seconds=True,
    )
    return float(sum(float(item["end"]) - float(item["start"]) for item in stamps))


def _embed(encoder, frame: np.ndarray) -> np.ndarray:
    import torch

    with torch.inference_mode():
        batch = torch.from_numpy(frame.astype(np.float32)[None, :])
        encoded = encoder.encode_batch(batch, normalize=False)
        arr = encoded.detach().float().cpu().numpy()
        arr = np.squeeze(arr)
    return np.asarray(arr, dtype=np.float64)


def _continuity(history: list[dict], now: float) -> float | None:
    chunk = [row for row in history if now - CONTINUITY_WINDOW_S <= row["window_end"] <= now + 1e-6]
    if not chunk:
        return None
    return float(
        np.mean(
            [
                (row["similarity_to_best_known"] or 0.0) if row["speaker_is_recurring"] else 0.0
                for row in chunk
            ]
        )
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"family": "speaker", "available": False, "error": str(exc)}), flush=True)
        raise
