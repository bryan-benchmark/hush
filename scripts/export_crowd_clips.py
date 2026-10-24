"""Cut the crowd-label clips and write the queue the public site serves.

Audio is uploaded separately to the private clip bucket. This file does not
upload, and it does not write votes.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
import soundfile as sf

from src.hush.audio import analysis_pieces, find_session, load_session, read_stereo
QUEUE = ROOT / "docs" / "ohush" / "research" / "LOUD_SHOW_001" / "queue.jsonl"
OUT_JSON = ROOT / "apps" / "monitor" / "src" / "data" / "crowdQueue.json"
OUT_DIR = Path(tempfile.gettempdir()) / "ohush-crowd-clips"


def object_name(clip_id: str) -> str:
    return "clips/" + clip_id.replace(":", "_") + ".mp3"


def main() -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise SystemExit("ffmpeg is not on PATH")
    rows = [json.loads(line) for line in QUEUE.read_text(encoding="utf-8").splitlines() if line.strip()]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    items = []
    for clip in rows:
        t0 = float(clip["play_start"])
        t1 = t0 + float(clip["duration"])
        session = find_session(ROOT / "recordings", clip["session"])
        meta = load_session(session)
        pieces = analysis_pieces(session, meta, t0, t1)
        audio = np.concatenate([read_stereo(piece) for piece in pieces], axis=0)
        mono = audio.mean(axis=1).astype(np.float32)
        wav = OUT_DIR / "slice.wav"
        mp3 = OUT_DIR / (clip["id"].replace(":", "_") + ".mp3")
        sf.write(wav, mono, 48000, subtype="PCM_16")
        subprocess.run(
            [ffmpeg, "-y", "-loglevel", "error", "-i", str(wav), "-ac", "1", "-ar", "24000", "-b:a", "64k", str(mp3)],
            check=True,
        )
        items.append(
            {
                "id": clip["id"],
                "session": clip["session"],
                "play_start": clip["play_start"],
                "duration": clip["duration"],
                "mark_s": clip["mark_s"],
                "caption": clip["caption"],
                "object": object_name(clip["id"]),
            }
        )
        print(f"{clip['id']} {mp3.stat().st_size}", flush=True)
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(items, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"clips": len(items), "json": str(OUT_JSON)}))


if __name__ == "__main__":
    main()
