"""Causal scan for a rise from little music to a song under speech.

Lines are the ones already published in VOICE_OVER_SONG_001. They are not
refit. Gold is not read. Holdouts are not opened. The live gate is not touched.

A 4-second window hops every 4 seconds. The stamp is the end of the window.
Music under 0.30 is low. Music at least 0.70 with speech at least 0.50 is high.
An event fires when a high window is preceded, 8 to 24 seconds earlier, by a
low window that still had speech at least 0.50. One event then stands until
music falls under 0.30 again. That collapse is what keeps a sustained song
from being counted as a new event every window.
"""

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

from experiments.broadcast_intelligence.batch1 import coverage, load_catalog, read_span  # noqa: E402
from hush.audio import find_session  # noqa: E402

OUT = REPO / "docs/ohush/research/SONG_TRANSITION_001"
CHECKPOINT = REPO / "experiments/exp003/models/Cnn14_mAP=0.431.pth"
HOLDOUTS = {"hush_20260917_205513", "hush_20260920_200635"}
WINDOW = 4.0
HOP = 4.0
BATCH = 8


def spans():
    catalog = load_catalog()
    chosen = []
    for row in coverage():
        if not row.get("fully_annotated"):
            continue
        sid = row["session"]
        if sid in HOLDOUTS:
            continue
        cat = catalog.get(sid, {})
        if cat.get("content_type") != "sports":
            continue
        chosen.append(row)
    return chosen


def main():
    torch.backends.nnpack.set_flags(False)
    torch.set_num_threads(4)
    from panns_inference import AudioTagging

    tagger = AudioTagging(checkpoint_path=str(CHECKPOINT), device="cpu")
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "scores.jsonl"
    done = set()
    if path.exists():
        for line in path.read_text().splitlines():
            if not line:
                continue
            row = json.loads(line)
            if row.get("kind") == "session_done":
                done.add(row["session"])
    cache = {}
    handle = path.open("a", encoding="utf-8")
    for span in spans():
        sid = span["session"]
        if sid in done:
            print("skip", sid, flush=True)
            continue
        t0 = float(span["from_seconds"])
        t1 = float(span["to_seconds"])
        if sid not in cache:
            folder = find_session(REPO / "recordings", sid)
            cache[sid] = (folder, json.loads((folder / "session.json").read_text()))
        folder, meta = cache[sid]
        print(f"scan {sid} {t0:.0f}-{t1:.0f}", flush=True)
        cursor = t0
        n = 0
        while cursor + WINDOW <= t1:
            block_end = min(t1, cursor + 120.0)
            try:
                audio = read_span(folder, meta, cursor, block_end).mean(axis=1).astype(np.float32)
            except Exception as exc:
                print("  skip block", round(cursor, 1), exc, flush=True)
                cursor = block_end
                continue
            starts = np.arange(0.0, (block_end - cursor) - WINDOW + 1e-6, HOP)
            batch = []
            stamps = []
            for start in starts:
                a = int(round(start * 48000))
                b = a + int(WINDOW * 48000)
                if b > len(audio):
                    continue
                y = resample_poly(audio[a:b], 2, 3).astype(np.float32)
                if len(y) < 320000:
                    y = np.pad(y, (0, 320000 - len(y)))
                batch.append(y[:320000])
                stamps.append(cursor + start + WINDOW)
                if len(batch) == BATCH:
                    _write(tagger, handle, sid, stamps, batch)
                    n += len(batch)
                    batch, stamps = [], []
            if batch:
                _write(tagger, handle, sid, stamps, batch)
                n += len(batch)
            cursor = block_end
            print(f"  {sid} through {cursor:.0f} windows {n}", flush=True)
        handle.write(json.dumps({"kind": "session_done", "session": sid}) + "\n")
        handle.flush()
    handle.close()
    print("scores", path, flush=True)


def _write(tagger, handle, sid, stamps, batch):
    clipwise, _ = tagger.inference(np.stack(batch))
    probs = np.asarray(clipwise)
    for stamp, p in zip(stamps, probs):
        handle.write(json.dumps({
            "session": sid,
            "t": round(float(stamp), 3),
            "speech": round(float(p[0]), 4),
            "music": round(float(p[137]), 4),
        }) + "\n")
    handle.flush()


if __name__ == "__main__":
    main()
