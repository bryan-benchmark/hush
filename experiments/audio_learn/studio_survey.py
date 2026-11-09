"""Sample training-game program audio and transcribe it.

Prime, ESPN, and sealed tapes are not opened. This finds studio and feature
minutes already labeled program. It does not train.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from experiments.audio_learn.splits import TRAIN, assert_split
from tools.gpu_lab.audio_load import load_coverage

DATA_ROOT = Path(r"C:\OHushData\gpu_lab\audio_learn")

OUT = DATA_ROOT / "studio_survey"
STRIDE_S = 40.0
CLIP_S = 8.0


def _program_times(session: str) -> np.ndarray:
    path = DATA_ROOT / "embeddings" / "frozen" / f"{session}.npz"
    data = np.load(path)
    times = data["t"]
    label = data["label"]
    return times[label == 0]


def sample_times(times: np.ndarray) -> list[float]:
    chosen = []
    last = -1e9
    for moment in times:
        moment = float(moment)
        if moment < CLIP_S:
            continue
        if moment - last >= STRIDE_S:
            chosen.append(moment)
            last = moment
    return chosen


def main() -> None:
    assert_split()
    from faster_whisper import WhisperModel

    OUT.mkdir(parents=True, exist_ok=True)
    model = WhisperModel("base.en", device="cpu", compute_type="int8", cpu_threads=4)
    rows = []
    for session in TRAIN:
        times = _program_times(session)
        picks = sample_times(times)
        print(f"{session} program_hops {len(times)} clips {len(picks)}", flush=True)
        for index, end in enumerate(picks, start=1):
            audio = load_coverage(session, end - CLIP_S, end)
            segments, _info = model.transcribe(audio, vad_filter=True, beam_size=1)
            text = " ".join(segment.text.strip() for segment in segments if segment.text.strip())
            rows.append({"session": session, "end_s": round(end, 3), "text": text})
            if index % 20 == 0:
                print(f"  {index}/{len(picks)}", flush=True)
    path = OUT / "transcripts.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    print(f"wrote {len(rows)} {path}", flush=True)


if __name__ == "__main__":
    main()
