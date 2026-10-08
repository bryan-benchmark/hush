#!/usr/bin/env python3
"""CLI for discontinuity_legacy_v0. The scorer lives in legacy_detector.py."""

from __future__ import annotations

import argparse
import json
import wave
from pathlib import Path

import numpy as np

from legacy_detector import iter_session_wavs, legacy_candidate_rows, load_pcm16


def export_clip(x: np.ndarray, rate: int, center_s: float, out: Path, radius_s: float = 8.0):
    a = max(0, int((center_s - radius_s) * rate))
    b = min(len(x), int((center_s + radius_s) * rate))
    seg = x[a:b]
    pcm = np.clip(seg * 32767.0, -32768, 32767).astype("<i2")
    out.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--session", default="recordings/2026-08-27/hush_20260827_135935")
    p.add_argument("--top-k-per-chunk", type=int, default=8)
    p.add_argument("--export-clips", action="store_true")
    p.add_argument("--max-chunks", type=int, default=0, help="0 = all chunks")
    args = p.parse_args()

    session = Path(args.session)
    all_rows = legacy_candidate_rows(session, top_k=args.top_k_per_chunk, max_chunks=args.max_chunks)

    out_jsonl = Path("experiments/candidates") / f"{session.name}_candidates.jsonl"
    out_jsonl.parent.mkdir(parents=True, exist_ok=True)
    if args.export_clips:
        by_file: dict[str, list] = {}
        for row in all_rows:
            by_file.setdefault(row["file"], []).append(row)
        wavs = iter_session_wavs(session)
        if args.max_chunks:
            wavs = wavs[: args.max_chunks]
        for wav in wavs:
            rows = by_file.get(wav.name) or []
            if not rows:
                continue
            rate, _ch, _n, x = load_pcm16(wav)
            for row in rows:
                clip_path = (
                    Path("experiments/clips")
                    / session.name
                    / f"{wav.stem}_t{int(row['chunk_elapsed_seconds']):04d}.wav"
                )
                export_clip(x, rate, row["chunk_elapsed_seconds"], clip_path)

    with out_jsonl.open("w", encoding="utf-8") as f:
        for row in all_rows:
            f.write(json.dumps(row) + "\n")
    print(f"Wrote {len(all_rows)} candidates → {out_jsonl}")


if __name__ == "__main__":
    main()
