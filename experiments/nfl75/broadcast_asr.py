"""Causal 5-second transcripts for the broadcast-opportunity windows.

Availability is the end of the chunk plus the time the recognizer took.
A 20–30 second retrospective window is not used. Phrases are the frozen
EXP-03 sign-off list and the stoppage list. Nothing is fine-tuned.

    C:\\Python313\\python.exe -m experiments.nfl75.broadcast_asr
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

from experiments.nfl75.broadcast_opportunity import SIGN_OFF, STOPPAGE, phrases_in
from hush.audio import analysis_pieces, find_session, load_session

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "docs" / "ohush" / "research" / "NFL75_BROADCAST_OPPORTUNITY_001"
RECORDINGS = REPO / "recordings"


def _audio(folder, meta, t0: float, t1: float) -> np.ndarray:
    parts = []
    for piece in analysis_pieces(folder, meta, t0, t1):
        audio, _sr = sf.read(
            str(piece["path"]),
            start=piece["read_start_frame"],
            stop=piece["read_stop_frame"],
            dtype="float32",
            always_2d=True,
        )
        parts.append(audio)
    mono = np.mean(np.concatenate(parts, axis=0), axis=1).astype(np.float64)
    return resample_poly(mono, 1, 3).astype(np.float32)


def main() -> None:
    from faster_whisper import WhisperModel

    jobs_doc = json.loads((OUT / "asr_jobs.json").read_text(encoding="utf-8"))
    model = WhisperModel("base.en", device="cpu", compute_type="int8")
    sessions = {}
    rows = []
    phrases = []
    started = time.perf_counter()
    for bag in jobs_doc:
        session = bag["session"]
        if session not in sessions:
            folder = find_session(RECORDINGS, session)
            sessions[session] = (folder, load_session(folder))
        folder, meta = sessions[session]
        print(session, len(bag["jobs"]), flush=True)
        for number, job in enumerate(bag["jobs"], start=1):
            t0 = float(job["t0"])
            t1 = float(job["t1"])
            if t0 < 0 or t1 <= t0:
                continue
            try:
                samples = _audio(folder, meta, t0, t1)
            except RuntimeError as exc:
                rows.append({**job, "session": session, "text": "", "process_s": None, "missing": str(exc)})
                continue
            t_start = time.perf_counter()
            segments, _info = model.transcribe(samples, language="en", vad_filter=False, beam_size=1)
            text = " ".join(segment.text for segment in segments).strip()
            process_s = time.perf_counter() - t_start
            record = {
                "session": session,
                "role": job["role"],
                "t0": t0,
                "t1": t1,
                "boundary": job.get("boundary"),
                "text": text,
                "process_s": round(process_s, 3),
                "available_t": round(t1 + process_s, 3),
                "signoff": phrases_in(text, SIGN_OFF),
                "stoppage": phrases_in(text, STOPPAGE),
            }
            rows.append(record)
            for kind, found in (("signoff", record["signoff"]), ("stoppage", record["stoppage"])):
                if found:
                    phrases.append(
                        {
                            "session": session,
                            "available_t": record["available_t"],
                            "kind": kind,
                            "role": job["role"],
                            "t0": t0,
                            "t1": t1,
                            "boundary": job.get("boundary"),
                            "phrases": found,
                            "process_s": record["process_s"],
                        }
                    )
            if number % 40 == 0:
                print(f"  {number}", flush=True)
    (OUT / "asr_chunks.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    (OUT / "asr_phrases.json").write_text(json.dumps(phrases, indent=2), encoding="utf-8")
    process = [row["process_s"] for row in rows if row.get("process_s")]
    process.sort()
    def pct(q):
        if not process:
            return None
        return process[min(len(process) - 1, int(q * (len(process) - 1)))]
    by_role = {}
    for row in rows:
        role = row.get("role") or "missing"
        bag = by_role.setdefault(role, {"chunks": 0, "signoff": 0, "stoppage": 0})
        bag["chunks"] += 1
        bag["signoff"] += int(bool(row.get("signoff")))
        bag["stoppage"] += int(bool(row.get("stoppage")))
    early = []
    for row in phrases:
        if row["kind"] != "signoff" or row["role"] != "lead" or row.get("boundary") is None:
            continue
        early.append(row["available_t"] <= float(row["boundary"]))
    summary = {
        "chunks": len(rows),
        "wall_s": round(time.perf_counter() - started, 1),
        "process_s": {"median": pct(0.5), "p90": pct(0.9), "max": process[-1] if process else None},
        "by_role": by_role,
        "signoff_events": sum(1 for row in phrases if row["kind"] == "signoff"),
        "stoppage_events": sum(1 for row in phrases if row["kind"] == "stoppage"),
        "lead_signoffs_available_before_boundary": sum(early),
        "lead_signoffs": len(early),
    }
    (OUT / "asr_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
