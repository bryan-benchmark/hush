"""Where the frozen head already calls training-game program a commercial.

Training games only. Used to find studio audio the current fit underweights.
Does not write a new checkpoint.
"""

from __future__ import annotations

import json

import numpy as np
import torch

from experiments.audio_learn.encoder import DATA_ROOT
from experiments.audio_learn.head import load_head, probabilities
from experiments.audio_learn.splits import HOP_S, TRAIN, assert_split

OUT = DATA_ROOT / "studio_survey" / "train_high_program.json"


def runs(times: np.ndarray, mask: np.ndarray) -> list[tuple[float, float, int]]:
    found = []
    idx = np.flatnonzero(mask)
    if len(idx) == 0:
        return found
    start = prev = int(idx[0])
    for raw in idx[1:]:
        i = int(raw)
        if i == prev + 1 and abs(float(times[i]) - float(times[prev]) - HOP_S) < 1e-2:
            prev = i
            continue
        found.append((float(times[start]), float(times[prev]) + HOP_S, prev - start + 1))
        start = prev = i
    found.append((float(times[start]), float(times[prev]) + HOP_S, prev - start + 1))
    return found


def main() -> None:
    assert_split()
    device = torch.device("cuda")
    head = load_head(DATA_ROOT / "checkpoints" / "frozen_head.pt", device)
    rows = []
    for session in TRAIN:
        data = np.load(DATA_ROOT / "embeddings" / "frozen" / f"{session}.npz")
        times = data["t"].astype(np.float64)
        label = data["label"].astype(np.int8)
        scores = probabilities(head, data["emb"].astype(np.float32), times, device)
        program = label == 0
        high = program & (scores >= 0.90)
        mid = program & (scores >= 0.50)
        print(
            session[-6:],
            "program_s",
            round(float(program.sum()) * HOP_S, 1),
            "p>=0.90_s",
            round(float(high.sum()) * HOP_S, 1),
            "p>=0.50_s",
            round(float(mid.sum()) * HOP_S, 1),
            flush=True,
        )
        for start, end, hops in runs(times, high):
            if end - start < 8:
                continue
            rows.append(
                {
                    "session": session,
                    "start_s": round(start, 3),
                    "end_s": round(end, 3),
                    "seconds": round(end - start, 3),
                }
            )
    rows.sort(key=lambda row: row["seconds"], reverse=True)
    OUT.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print("runs>=8s", len(rows), "seconds", round(sum(row["seconds"] for row in rows), 1), flush=True)
    for row in rows[:25]:
        print(f"  {row['session'][-6:]} {row['start_s']:.1f}-{row['end_s']:.1f} {row['seconds']:.1f}s", flush=True)


if __name__ == "__main__":
    main()
