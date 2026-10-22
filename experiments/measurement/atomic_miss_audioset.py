"""Add the AudioSet speech, music, crowd, and jingle scores to the atomic receipts."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import torch
from scipy.signal import resample_poly

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from experiments.broadcast_intelligence.batch1 import read_span  # noqa: E402
from hush.audio import find_session  # noqa: E402

OUT = REPO / "docs/ohush/research/START_END_001/atomic_receipts.jsonl"
CHECKPOINT = REPO / "experiments/exp003/models/Cnn14_mAP=0.431.pth"
HEADS = {"speech": 0, "singing": 27, "crowd": 69, "music": 137, "background_music": 267, "jingle": 269}


def main():
    torch.backends.nnpack.set_flags(False)
    torch.set_num_threads(4)
    from panns_inference import AudioTagging

    tagger = AudioTagging(checkpoint_path=str(CHECKPOINT), device="cpu")
    rows = [json.loads(line) for line in OUT.read_text().splitlines() if line.strip()]
    cache = {}
    batch, slots = [], []
    for index, row in enumerate(rows):
        atom = row.get("atomic") or {}
        if atom.get("error"):
            continue
        sid = row["session"]
        if sid not in cache:
            folder = find_session(REPO / "recordings", sid)
            cache[sid] = (folder, json.loads((folder / "session.json").read_text()))
        folder, meta = cache[sid]
        audio = read_span(folder, meta, row["start"] - 4, row["start"] + 4).mean(axis=1).astype(np.float32)
        cut = 4 * 48000
        for name, piece in (("before", audio[:cut]), ("after", audio[cut:cut + cut])):
            y = resample_poly(piece, 2, 3).astype(np.float32)
            if len(y) < 320000:
                y = np.pad(y, (0, 320000 - len(y)))
            batch.append(y[:320000])
            slots.append((index, name))
            if len(batch) == 8:
                _score(tagger, rows, slots, batch)
                batch, slots = [], []
    if batch:
        _score(tagger, rows, slots, batch)
    with OUT.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")
    print("scored", len(rows), flush=True)


def _score(tagger, rows, slots, batch):
    clipwise, _embed = tagger.inference(np.stack(batch))
    probs = np.asarray(clipwise)
    for (index, name), prob in zip(slots, probs):
        rows[index]["atomic"][name]["audioset"] = {
            head: round(float(prob[i]), 3) for head, i in HEADS.items()
        }


if __name__ == "__main__":
    main()
