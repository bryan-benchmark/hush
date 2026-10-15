"""EXP-03 announcer handoff language, and the audio-only tokens used by EXP-02.

Phrases were fixed before any transcript was read. A strong phrase is a
segment-closing pattern. A weak phrase is game-state language and is not a
handoff hit. Bare "timeout" is a game-state token, not permission to mute.

Windows are deterministic:
- each commercial start contributes [start-20 s, start+10 s]
- one program control of 20 s per start, placed on a fixed stride and kept
  only when it sits at least 60 s from every pod
- 40 RedZone windows on a fixed stride

No ASR model is fine-tuned. Absence of a phrase is missing evidence, not
evidence that no break is coming.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

from experiments.broadcast_intelligence.batch1 import SR, commercials, coverage, load_catalog, read_span
from hush.audio import find_session, load_session

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "docs/ohush/research/FIRST_PRINCIPLES_BROADCAST_V2/EXP_03_HANDOFF_LANGUAGE"
RECORDINGS = REPO / "recordings"
REDZONE = "hush_20260913_150934"
STRONG = (
    "we'll be right back",
    "we will be right back",
    "be right back",
    "when we come back",
    "after these messages",
    "these messages",
    "commercial break",
    "going to commercial",
    "we'll return",
    "we will return",
    "back after this",
)
WEAK = (
    "two-minute warning",
    "two minute warning",
    "end of the quarter",
    "end of the half",
    "end of quarter",
)
QUARTER = ("first quarter", "second quarter", "third quarter", "fourth quarter", "overtime")


def normalize(text: str) -> str:
    return " ".join(text.lower().replace("-", " ").split())


def phrases_in(text: str, phrases: tuple[str, ...]) -> list[str]:
    folded = normalize(text)
    return [phrase for phrase in phrases if normalize(phrase) in folded]


def main() -> None:
    sys.stdout.reconfigure(line_buffering=True)
    from faster_whisper import WhisperModel

    started = time.perf_counter()
    model = WhisperModel("base.en", device="cpu", compute_type="int8")
    catalog = load_catalog()
    spans = coverage()
    rows = commercials(spans)
    if len(rows) != 166:
        raise SystemExit(f"expected 166 commercials, found {len(rows)}")
    sessions = {}
    for span in spans:
        sid = span["session"]
        if sid in sessions:
            continue
        folder = find_session(RECORDINGS, sid)
        info = catalog.get(sid, {})
        sessions[sid] = {
            "dir": folder,
            "meta": load_session(folder),
            "coverage": (float(span["from_seconds"]), float(span["to_seconds"])),
            "network": info.get("network_or_service") or "unknown",
            "content": info.get("content_type") or "",
        }
    pods: dict[str, list[tuple[float, float]]] = {sid: [] for sid in sessions}
    for row in rows:
        pods[row["session"]].append((float(row["start_seconds"]), float(row["end_seconds"])))

    jobs = []
    for index, row in enumerate(rows):
        sid = row["session"]
        start = float(row["start_seconds"])
        cov0, cov1 = sessions[sid]["coverage"]
        if start - 20.0 >= cov0 and start + 10.0 <= cov1:
            jobs.append({"role": "start", "session": sid, "boundary": start, "t0": start - 20.0, "t1": start + 10.0, "split": 20.0})
        cursor = cov0 + 90.0 + (index * 47) % max(int(cov1 - cov0 - 180), 1)
        placed = None
        for _ in range(24):
            if cursor + 20.0 < cov1 and not any(lo - 60.0 <= cursor <= hi + 60.0 or lo - 60.0 <= cursor + 20.0 <= hi + 60.0 for lo, hi in pods[sid]):
                placed = cursor
                break
            cursor += 17.0
        if placed is not None:
            jobs.append({"role": "control", "session": sid, "boundary": start, "t0": placed, "t1": placed + 20.0, "split": 20.0})
    cov0, cov1 = sessions[REDZONE]["coverage"]
    stride = (cov1 - cov0 - 80.0) / 40.0
    for index in range(40):
        t0 = cov0 + 40.0 + index * stride
        jobs.append({"role": "redzone", "session": REDZONE, "boundary": None, "t0": t0, "t1": t0 + 20.0, "split": 20.0})

    OUT.mkdir(parents=True, exist_ok=True)
    out_path = OUT / "transcripts.jsonl"
    handle = out_path.open("w", encoding="utf-8")
    print(f"transcribing {len(jobs)} windows", flush=True)
    for number, job in enumerate(jobs, start=1):
        bag = sessions[job["session"]]
        try:
            audio = read_span(bag["dir"], bag["meta"], job["t0"], job["t1"])
        except RuntimeError:
            record = {**job, "missing_reason": "audio_unreadable", "words": [], "text": ""}
            handle.write(json.dumps(record) + "\n")
            continue
        mono = 0.5 * (audio[:, 0].astype(np.float64) + audio[:, 1].astype(np.float64))
        samples = resample_poly(mono, 1, 3).astype(np.float32)
        segments, _info = model.transcribe(samples, language="en", word_timestamps=True, vad_filter=False, beam_size=1)
        words = []
        pieces = []
        for segment in segments:
            pieces.append(segment.text)
            for word in segment.words or []:
                words.append({"start": round(float(word.start), 3), "end": round(float(word.end), 3), "text": word.word})
        text = " ".join(pieces).strip()
        pre = " ".join(word["text"] for word in words if word["start"] < job["split"])
        post = " ".join(word["text"] for word in words if word["start"] >= job["split"])
        record = {
            "role": job["role"],
            "session": job["session"],
            "network": bag["network"],
            "content": bag["content"],
            "boundary": job["boundary"],
            "t0": job["t0"],
            "t1": job["t1"],
            "text": text,
            "strong_before": phrases_in(pre, STRONG),
            "strong_after": phrases_in(post, STRONG),
            "weak_before": phrases_in(pre, WEAK),
            "quarter_before": phrases_in(pre, QUARTER),
            "timeout_before": "timeout" in normalize(pre),
            "clock_before": any(token.count(":") == 1 and token.replace(":", "").isdigit() for token in normalize(pre).split()),
            "n_words": len(words),
            "missing_reason": "" if text else "no_speech_or_unrecognized",
        }
        if record["strong_before"]:
            folded = normalize(pre)
            lead = None
            cursor = 0.0
            built = ""
            for word in words:
                if word["start"] >= job["split"]:
                    break
                built = (built + " " + word["text"]).strip()
                if normalize(record["strong_before"][0]) in normalize(built) and lead is None:
                    lead = round(job["split"] - word["start"], 3)
                    break
            record["lead_s"] = lead
        handle.write(json.dumps(record) + "\n")
        if number % 25 == 0:
            print(f"  {number}/{len(jobs)}", flush=True)
            handle.flush()
    handle.close()
    rows_out = [json.loads(line) for line in out_path.read_text(encoding="utf-8").splitlines() if line]
    summary = {"wall_s": round(time.perf_counter() - started, 1), "windows": len(rows_out)}
    for role in ("start", "control", "redzone"):
        chosen = [row for row in rows_out if row["role"] == role and row["content"] == "sports" or (role == "redzone" and row["role"] == "redzone")]
        if role != "redzone":
            chosen = [row for row in rows_out if row["role"] == role and row.get("content") == "sports" and row["session"] != REDZONE]
        summary[role] = {
            "n": len(chosen),
            "strong_before": sum(1 for row in chosen if row.get("strong_before")),
            "strong_after": sum(1 for row in chosen if row.get("strong_after")),
            "weak_before": sum(1 for row in chosen if row.get("weak_before")),
            "quarter": sum(1 for row in chosen if row.get("quarter_before")),
            "timeout": sum(1 for row in chosen if row.get("timeout_before")),
            "clock": sum(1 for row in chosen if row.get("clock_before")),
            "empty": sum(1 for row in chosen if row.get("missing_reason")),
        }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
