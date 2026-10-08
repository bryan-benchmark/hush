#!/usr/bin/env python3
"""
Second unlabeled experiment: segment-level feature trajectories.

For each 15-min chunk, compute 1-second feature vectors and look for
self-similarity breaks (content bed vs ad bed). Writes a compact NPZ + summary.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from find_candidates import load_pcm16


def sec_features(x: np.ndarray, rate: int):
    # 1-second non-overlapping windows
    n = len(x) // rate
    rows = []
    for i in range(n):
        seg = x[i * rate : (i + 1) * rate]
        rms = float(np.sqrt(np.mean(seg * seg) + 1e-12))
        # simple spectrum bands
        spec = np.abs(np.fft.rfft(seg * np.hanning(len(seg))))
        freqs = np.fft.rfftfreq(len(seg), 1 / rate)
        def bp(a, b):
            m = (freqs >= a) & (freqs < b)
            return float(np.sum(spec[m] ** 2) + 1e-12)
        low = bp(60, 250)
        mid = bp(250, 4000)
        high = bp(4000, 12000)
        tot = low + mid + high
        zcr = float(np.mean(np.abs(np.diff(np.sign(seg))) > 0))
        rows.append([rms, low / tot, mid / tot, high / tot, zcr])
    return np.asarray(rows, dtype=np.float64)


def change_scores(F: np.ndarray, win: int = 5):
    # cosine distance between left and right local means
    scores = np.zeros(len(F))
    for i in range(win, len(F) - win):
        a = F[i - win : i].mean(axis=0)
        b = F[i : i + win].mean(axis=0)
        na = np.linalg.norm(a) + 1e-12
        nb = np.linalg.norm(b) + 1e-12
        scores[i] = 1.0 - float(np.dot(a, b) / (na * nb))
    return scores


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", default="recordings/2026-08-27/hush_20260827_135935")
    ap.add_argument("--max-chunks", type=int, default=4)
    args = ap.parse_args()

    session = Path(args.session)
    wavs = sorted(session.glob("audio_*.wav"))[: args.max_chunks]
    out_dir = Path("experiments/features") / session.name
    out_dir.mkdir(parents=True, exist_ok=True)

    summary = []
    offset = 0.0
    for wav in wavs:
        rate, x = load_pcm16(wav)
        if np.max(np.abs(x)) < 1e-4:
            offset += len(x) / rate
            continue
        F = sec_features(x, rate)
        scores = change_scores(F)
        top = np.argsort(scores)[::-1][:10]
        peaks = [
            {
                "chunk_second": int(i),
                "elapsed_seconds": round(offset + float(i), 3),
                "change_score": round(float(scores[i]), 4),
            }
            for i in top
            if scores[i] > 0
        ]
        np.savez_compressed(out_dir / f"{wav.stem}_sec_features.npz", F=F, scores=scores)
        summary.append({"file": wav.name, "peaks": peaks})
        print(f"{wav.name}: top change at {[p['elapsed_seconds'] for p in peaks[:5]]}")
        offset += len(x) / rate

    out = out_dir / "change_summary.json"
    out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print("Wrote", out)


if __name__ == "__main__":
    main()
