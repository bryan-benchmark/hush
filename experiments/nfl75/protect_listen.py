"""Transcribe the oracle false-mute clips. Not a mute model.

    C:\\Python313\\python.exe -m experiments.nfl75.protect_listen
"""

from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MANIFEST = REPO / "docs" / "ohush" / "research" / "NFL75_PROTECT_001" / "clips" / "manifest.json"
OUT = REPO / "docs" / "ohush" / "research" / "NFL75_PROTECT_001" / "transcripts.jsonl"


def main() -> None:
    import soundfile as sf
    from faster_whisper import WhisperModel

    rows = json.loads(MANIFEST.read_text(encoding="utf-8"))
    model = WhisperModel("base", device="cpu", compute_type="int8", cpu_threads=2)
    with OUT.open("w", encoding="utf-8") as handle:
        for row in rows:
            audio, _sr = sf.read(str(REPO / row["wav"]), dtype="float32")
            segments, _info = model.transcribe(audio, language="en", vad_filter=False)
            text = " ".join(segment.text.strip() for segment in segments).strip()
            record = {**row, "transcript": text}
            handle.write(json.dumps(record) + "\n")
            handle.flush()
            print(f"{row['session'][-6:]} {row['episode']:02d} {text[:120]}", flush=True)


if __name__ == "__main__":
    main()
