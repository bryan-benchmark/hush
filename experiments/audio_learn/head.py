"""Causal head. A GRU over recent frame embeddings, then one commercial logit."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import torch
import torch.nn as nn

from experiments.audio_learn.splits import HIDDEN, HOP_S, SEQUENCE
from experiments.audio_learn.windows import lookback_bounds


class CausalHead(nn.Module):
    def __init__(self, embed_dim: int, hidden: int = HIDDEN) -> None:
        super().__init__()
        self.embed_dim = embed_dim
        self.hidden = hidden
        self.sequence = SEQUENCE
        self.gru = nn.GRU(embed_dim, hidden, batch_first=True)
        self.fc = nn.Linear(hidden, 1)

    def forward(self, embeddings: torch.Tensor) -> torch.Tensor:
        # embeddings: (batch, time, dim). Time is oldest to newest.
        states, _hidden = self.gru(embeddings)
        return self.fc(states).squeeze(-1)


def load_head(path: Path, device: torch.device) -> CausalHead:
    blob = torch.load(path, map_location="cpu", weights_only=True)
    head = CausalHead(int(blob["embed_dim"]), int(blob["hidden"]))
    head.sequence = int(blob["sequence"])
    head.load_state_dict(blob["state_dict"])
    head.to(device)
    head.eval()
    return head


def save_head(path: Path, head: CausalHead) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(
        {
            "state_dict": head.state_dict(),
            "embed_dim": head.embed_dim,
            "hidden": head.hidden,
            "sequence": head.sequence,
        },
        path,
    )


def probabilities(head: CausalHead, embeddings: np.ndarray, times: np.ndarray, device: torch.device, batch: int = 256) -> np.ndarray:
    """P(commercial) at each stamp, using only that stamp and earlier consecutive stamps."""
    head.eval()
    embeddings = np.asarray(embeddings, dtype=np.float32)
    times = np.asarray(times, dtype=np.float64)
    length = int(head.sequence)
    count, _dim = embeddings.shape
    output = np.empty(count, dtype=np.float32)
    for start in range(0, count, batch):
        stop = min(count, start + batch)
        window = np.zeros((stop - start, length, embeddings.shape[1]), dtype=np.float32)
        for row, index in enumerate(range(start, stop)):
            left, right = lookback_bounds(times, index, length, HOP_S)
            chunk = embeddings[left:right]
            window[row, -len(chunk) :] = chunk
        tensor = torch.from_numpy(window).to(device)
        with torch.inference_mode():
            logit = head(tensor)[:, -1]
            output[start:stop] = torch.sigmoid(logit).float().cpu().numpy()
    return output
