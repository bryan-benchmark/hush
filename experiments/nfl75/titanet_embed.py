"""Embed the exported owner-mark wavs with pretrained TitaNet-Large.

Run this with the isolated interpreter, never with the SpeechBrain one:

    C:\\OHushData\\titanet-venv\\Scripts\\python.exe experiments/nfl75/titanet_embed.py

The vectors are L2-normalized here so a later dot product is a cosine.
This file does not import SpeechBrain and does not read a mute rule.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "docs" / "ohush" / "research" / "OHUSH_VOICE_DISCRIMINATION_002"
MANIFEST = OUT / "titanet_manifest.json"
MODEL_NAME = "nvidia/speakerverification_en_titanet_large"


def _vector(embedding) -> np.ndarray:
    if hasattr(embedding, "detach"):
        embedding = embedding.detach().float().cpu().numpy()
    vector = np.asarray(embedding, dtype=np.float64).reshape(-1)
    norm = float(np.linalg.norm(vector))
    if norm < 1e-6:
        raise RuntimeError("zero TitaNet embedding")
    return (vector / norm).astype(np.float32)


def main() -> None:
    import nemo.collections.asr as nemo_asr

    rows = json.loads(MANIFEST.read_text(encoding="utf-8"))
    speaker = nemo_asr.models.EncDecSpeakerLabelModel.from_pretrained(MODEL_NAME)
    speaker.eval()
    keys = []
    vectors = []
    for row in rows:
        embedding = speaker.get_embedding(str(REPO / row["wav"]))
        vectors.append(_vector(embedding))
        keys.append(row["key"])
        print(row["key"], flush=True)
    np.savez(OUT / "titanet_embeddings.npz", vector=np.stack(vectors))
    (OUT / "titanet_embeddings.json").write_text(
        json.dumps({"keys": keys, "model": MODEL_NAME}),
        encoding="utf-8",
    )
    print(f"embedded {len(keys)}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
