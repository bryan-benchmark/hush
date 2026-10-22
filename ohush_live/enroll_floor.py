"""Enrolled-show voice for the live return.

The 0.10 floor is the labeled return: the best match to this show's
enrolled voices over the last 30 seconds. It does not start a cover.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np

from hush.voice_floor import MEMORY_S

REPO = Path(__file__).resolve().parents[1]
CACHE = REPO / "ohush_live" / "cache"
LABELS = REPO / "docs/ohush/research/VOICE_ENROLL_001/labels.jsonl"
KEEP = {"clear", "laugh", "loud", "crowd", "song"}
CAST = {
    "snf": ["Mike Tirico", "Cris Collinsworth", "Maria Taylor", "Mike Tomlin"],
    "mnf": ["Joe Buck", "Troy Aikman"],
    "tnf": [
        "Al Michaels",
        "Kirk Herbstreit",
        "Clarissa Thompson",
        "Ryan Fitzpatrick",
        "Andrew Whitworth",
        "Tony Gonzalez",
    ],
}


def show_key(raw: str) -> str:
    text = " ".join(raw.strip().lower().split())
    if text in {"snf", "sunday", "sunday night", "sunday night football", "nbc"}:
        return "snf"
    if text in {"mnf", "monday", "monday night", "monday night football", "espn"}:
        return "mnf"
    if text in {"tnf", "thursday", "thursday night", "prime", "prime video"}:
        return "tnf"
    return text if text in CAST else ""


def cache_path(show: str) -> Path:
    return CACHE / f"enroll_{show}.npy"


def load_matrix(show: str) -> np.ndarray | None:
    key = show_key(show)
    if not key:
        return None
    path = cache_path(key)
    if not path.is_file():
        return None
    matrix = np.load(path)
    if matrix.ndim != 2 or matrix.shape[0] == 0:
        return None
    return matrix


def note(hits: list[tuple[float, float]], now: float, cosine: float) -> float:
    """Highest enrolled match in the last 30 seconds."""
    hits.append((now, cosine))
    keep = [(t, score) for t, score in hits if now - t <= MEMORY_S]
    hits[:] = keep
    return max(score for _, score in hits)


def build(encoder, embed) -> None:
    """Write one prototype matrix per show. embed(frame) returns one vector."""
    from experiments.measurement.voice_enroll_score_001 import clip_16k, prototype

    labels = []
    seen: dict[str, dict] = {}
    for line in LABELS.read_text().splitlines():
        if line.strip():
            row = json.loads(line)
            seen[row["id"]] = row
    for row in seen.values():
        if row.get("condition") in KEEP and row.get("who"):
            labels.append(row)
    grouped: dict[str, list[np.ndarray]] = {}
    for row in labels:
        audio = clip_16k(row["session"], float(row["play_start"]), float(row["duration"]))
        grouped.setdefault(row["who"], []).append(embed(encoder, audio))
    voices = {name: prototype(vectors) for name, vectors in grouped.items()}
    CACHE.mkdir(parents=True, exist_ok=True)
    for show, names in CAST.items():
        rows = [voices[name] for name in names if name in voices]
        if not rows:
            continue
        np.save(cache_path(show), np.stack(rows))
        print(f"enroll {show} {len(rows)} voices", flush=True)


def cosine(matrix: np.ndarray, emb: np.ndarray) -> float:
    unit = emb / max(np.linalg.norm(emb), 1e-12)
    return float(np.max(matrix @ unit))


def main() -> None:
    os.environ.setdefault("HF_HOME", str(CACHE / "hf"))
    os.environ.setdefault("HUGGINGFACE_HUB_CACHE", str(CACHE / "hf" / "hub"))
    os.environ.setdefault("TORCH_HOME", str(CACHE / "torch"))
    from ohush_live.speaker_worker import _embed
    from speechbrain.inference.speaker import EncoderClassifier
    from hush.speaker_memory import EMBEDDING_MODEL_ID

    savedir = CACHE / "spkrec-ecapa-voxceleb"
    savedir.mkdir(parents=True, exist_ok=True)
    encoder = EncoderClassifier.from_hparams(
        source=EMBEDDING_MODEL_ID,
        savedir=str(savedir),
        run_opts={"device": "cpu"},
    )
    build(encoder, _embed)


if __name__ == "__main__":
    main()
