"""Causal transcripts of the live-game scope on the two Prime tapes.

Five-second chunks. A chunk is evidence only after it ends and the
recognizer returns. The scope ends are the postgame closers already
frozen in NFL75_BROADCAST_OPPORTUNITY_001. Gold commercials are not read.

    C:\\Python313\\python.exe -m experiments.nfl75.event_asr
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from hush.audio import analysis_pieces, find_session, load_session

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "docs" / "ohush" / "research" / "NFL75_EVENT_FIRST_001"
RECORDINGS = REPO / "recordings"
# Frozen in BROADCAST_OPPORTUNITY_001 from the EXP-03 postgame closer.
SCOPE = {
    "hush_20261008_205100": (0.0, 9604.933),
    "hush_20260924_220624": (0.0, 5354.826),
}
CHUNK_S = 5.0
BLOCK_S = 30.0


def _block(folder, meta, t0: float, t1: float) -> np.ndarray:
    parts = []
    for piece in analysis_pieces(folder, meta, t0, t1):
        audio, _sr = sf.read(
            str(piece["path"]),
            start=piece["read_start_frame"],
            stop=piece["read_stop_frame"],
            dtype="float32",
            always_2d=True,
        )
        if piece["pad_frames"]:
            audio = np.pad(audio, ((0, int(piece["pad_frames"])), (0, 0)))
        parts.append(audio)
    mono = np.mean(np.concatenate(parts, axis=0), axis=1).astype(np.float64)
    return resample_poly(mono, 1, 3).astype(np.float32)


def _done(path: Path) -> set[tuple[str, float]]:
    found = set()
    if not path.is_file():
        return found
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        found.add((row["session"], round(float(row["t0"]), 3)))
    return found


def main() -> None:
    from faster_whisper import WhisperModel

    OUT.mkdir(parents=True, exist_ok=True)
    dest = OUT / "asr_chunks.jsonl"
    done = _done(dest)
    model = WhisperModel("base.en", device="cpu", compute_type="int8")
    handle = dest.open("a", encoding="utf-8")
    started = time.perf_counter()
    written = 0
    try:
        for session, (scope0, scope1) in SCOPE.items():
            folder = find_session(RECORDINGS, session)
            meta = load_session(folder)
            cursor = scope0
            print(session, "from", len(done), "already stored", flush=True)
            while cursor < scope1 - 0.5:
                block_end = min(scope1, cursor + BLOCK_S)
                try:
                    samples = _block(folder, meta, cursor, block_end)
                except RuntimeError as exc:
                    print("missing", session, cursor, exc, flush=True)
                    cursor = block_end
                    continue
                rate = 16000.0
                local = cursor
                while local + 1.0 < block_end:
                    t1 = min(block_end, local + CHUNK_S)
                    key = (session, round(local, 3))
                    if key in done or t1 - local < 1.0:
                        local = t1
                        continue
                    a0 = int(round((local - cursor) * rate))
                    a1 = int(round((t1 - cursor) * rate))
                    piece = samples[a0:a1]
                    t_start = time.perf_counter()
                    segments, _info = model.transcribe(piece, language="en", vad_filter=False, beam_size=1)
                    text = " ".join(segment.text for segment in segments).strip()
                    process_s = time.perf_counter() - t_start
                    row = {
                        "session": session,
                        "t0": round(local, 3),
                        "t1": round(t1, 3),
                        "text": text,
                        "process_s": round(process_s, 3),
                        "available_t": round(t1 + process_s, 3),
                    }
                    handle.write(json.dumps(row) + "\n")
                    handle.flush()
                    done.add(key)
                    written += 1
                    if written % 60 == 0:
                        print(f"  {session} {local:.0f}s  {written} new  {time.perf_counter() - started:.0f}s", flush=True)
                    local = t1
                cursor = block_end
    finally:
        handle.close()
    print("wrote", written, "chunks in", round(time.perf_counter() - started, 1), "s", flush=True)


if __name__ == "__main__":
    main()
