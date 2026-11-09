"""Draw the first eight break-logger waves the way the desk draws them."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.hush.audio import analysis_pieces, find_session, load_session, read_stereo  # noqa: E402

RECORDINGS = REPO / "recordings"
QUEUE = REPO / "docs" / "ohush" / "research" / "BREAK_LISTEN_001" / "queue.jsonl"
OUT = REPO / "docs" / "ohush" / "research" / "BREAK_LISTEN_001" / "first8.png"
SR = 48000


def load(row: dict) -> np.ndarray:
    folder = find_session(RECORDINGS, row["session"])
    meta = load_session(folder)
    t0 = float(row["play_start"])
    t1 = t0 + float(row["duration"])
    parts = [read_stereo(piece) for piece in analysis_pieces(folder, meta, t0, t1)]
    audio = parts[0] if len(parts) == 1 else np.concatenate(parts)
    return audio[:, 0]


def envelope(samples: np.ndarray, columns: int = 840) -> tuple[np.ndarray, np.ndarray]:
    edges = np.linspace(0, len(samples), columns + 1).astype(int)
    lows = np.empty(columns)
    highs = np.empty(columns)
    for i in range(columns):
        chunk = samples[edges[i] : edges[i + 1]]
        lows[i] = float(chunk.min()) if len(chunk) else 0.0
        highs[i] = float(chunk.max()) if len(chunk) else 0.0
    return lows, highs


def main() -> None:
    rows = [json.loads(line) for line in QUEUE.read_text(encoding="utf-8").splitlines() if line.strip()][:8]
    fig, axes = plt.subplots(8, 1, figsize=(14, 16), sharex=False)
    notes = []
    for ax, row in zip(axes, rows):
        samples = load(row)
        lows, highs = envelope(samples)
        xs = np.linspace(0, row["duration"], len(highs))
        ax.fill_between(xs, lows, highs, color="#d7c6f5", linewidth=0)
        ax.axvline(row["mark_s"], color="#7dffb3", linewidth=1.5)
        ax.set_ylim(-1, 1)
        ax.set_xlim(0, row["duration"])
        ax.set_facecolor("#1a1024")
        kind = "start" if ":start:" in row["id"] else "return"
        ax.set_ylabel(kind, color="white")
        ax.tick_params(colors="white")
        for spine in ax.spines.values():
            spine.set_color("#3a2a4a")
        hop = int(0.05 * SR)
        peaks = []
        for i in range(0, len(samples) - hop, hop):
            peaks.append(float(np.max(np.abs(samples[i : i + hop]))))
        peaks = np.asarray(peaks)
        db = 20 * np.log10(np.maximum(peaks, 1e-8))
        mark = int(round(row["mark_s"] / 0.05))
        before = db[max(0, mark - 40) : mark]
        after = db[mark : mark + 40]
        stall = bool(np.any(db < -60))
        notes.append(
            {
                "id": row["id"],
                "mark_s": row["mark_s"],
                "before_median_db": round(float(np.median(before)), 1) if len(before) else None,
                "after_median_db": round(float(np.median(after)), 1) if len(after) else None,
                "min_db": round(float(db.min()), 1),
                "min_at_s": round(float(np.argmin(db) * 0.05), 2),
                "stall_under_minus_60": stall,
            }
        )
    fig.tight_layout()
    fig.savefig(OUT, dpi=120, facecolor="#120818")
    print(json.dumps({"png": str(OUT), "notes": notes}, indent=2), flush=True)


if __name__ == "__main__":
    main()
