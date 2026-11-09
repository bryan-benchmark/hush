"""One minute of overlapping transcripts, to see if the ledger double-counts.

Window 5 seconds, step 1 second, on the October opening score.
Not a second full-game pass.

    C:\\Python313\\python.exe -m experiments.nfl75.event_overlap
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from experiments.nfl75.event_asr import _block
from hush.audio import find_session, load_session
from ohush_live.football_brain import FootballEngine

REPO = Path(__file__).resolve().parents[2]
SESSION = "hush_20261008_205100"
START = 90.0
END = 140.0


def main() -> None:
    from faster_whisper import WhisperModel

    folder = find_session(REPO / "recordings", SESSION)
    meta = load_session(folder)
    audio = _block(folder, meta, START, END)
    model = WhisperModel("base.en", device="cpu", compute_type="int8")
    engine = FootballEngine()
    rows = []
    cursor = START
    while cursor + 5.0 <= END + 1e-6:
        a0 = int(round((cursor - START) * 16000))
        piece = audio[a0 : a0 + 80000]
        t0 = time.perf_counter()
        segments, _info = model.transcribe(piece, language="en", vad_filter=False, beam_size=1)
        text = " ".join(segment.text for segment in segments).strip()
        process = time.perf_counter() - t0
        chunk = {"t0": cursor, "t1": cursor + 5.0, "available_t": cursor + 5.0 + process, "text": text}
        events, _state = engine.observe(chunk)
        rows.append({"t0": cursor, "process_s": round(process, 3), "text": text, "events": [event["kind"] for event in events]})
        cursor += 1.0
    out = REPO / "docs" / "ohush" / "research" / "NFL_EVENT_ENGINE_001" / "overlap_sample.json"
    out.write_text(
        json.dumps({"session": SESSION, "start_s": START, "end_s": END, "duplicates_suppressed": engine.duplicates, "chunks": rows}, indent=2),
        encoding="utf-8",
    )
    print("duplicates", engine.duplicates, "chunks", len(rows))


if __name__ == "__main__":
    main()
