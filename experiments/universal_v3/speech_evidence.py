"""Full-stream handoff evidence. Not a mute policy.

Phrases are the frozen EXP-03 list. Audio is transcribed in 20-second
chunks in capture order, not in windows aimed at gold. A phrase's spoken
time is the end of the word that completes it. The recognizer can emit
that phrase only at the end of the chunk, which is recorded separately.

Gold is used after the transcripts exist, to count leads and false cues.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import numpy as np
from scipy.signal import resample_poly

from experiments.broadcast_intelligence.batch1 import commercials, coverage, load_catalog, read_span
from experiments.first_principles_broadcast.exp03_handoff_language import STRONG, WEAK, normalize
from hush.audio import find_session, load_session

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "docs/ohush/research/UNIVERSAL_V3_SPEECH_001"
RECORDINGS = REPO / "recordings"
REDZONE = "hush_20260913_150934"
CHUNK_S = 20.0


def completing_hits(words: list[dict], phrases: tuple[str, ...]) -> list[dict]:
    hits = []
    built = ""
    found = set()
    for word in words:
        built = (built + " " + word["text"]).strip()
        folded = normalize(built)
        for phrase in phrases:
            if phrase in found:
                continue
            if normalize(phrase) in folded:
                found.add(phrase)
                hits.append({"phrase": phrase, "spoken_end": word["end"]})
    return hits


def main() -> None:
    sys.stdout.reconfigure(line_buffering=True)
    started = time.perf_counter()
    only = {item for item in os.environ.get("SPEECH_SESSIONS", "").split(",") if item}
    score_only = os.environ.get("SPEECH_SCORE_ONLY") == "1"
    catalog = load_catalog()
    spans = coverage()
    pods = commercials(spans)
    sessions = {}
    for span in spans:
        sid = span["session"]
        info = catalog.get(sid, {})
        if (info.get("content_type") or "") != "sports":
            continue
        folder = find_session(RECORDINGS, sid)
        sessions[sid] = {
            "dir": folder,
            "meta": load_session(folder),
            "coverage": (float(span["from_seconds"]), float(span["to_seconds"])),
            "network": info.get("network_or_service") or "unknown",
        }
    if only:
        sessions = {sid: bag for sid, bag in sessions.items() if sid in only}
    OUT.mkdir(parents=True, exist_ok=True)
    if score_only:
        score(sessions, pods, started)
        return
    from faster_whisper import WhisperModel

    threads = int(os.environ.get("WHISPER_THREADS", "2"))
    model = WhisperModel("base.en", device="cpu", compute_type="int8", cpu_threads=threads)
    path = OUT / os.environ.get("SPEECH_OUT", "chunks.jsonl")
    done = set()
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line:
                row = json.loads(line)
                done.add((row["session"], row["t0"]))
    handle = path.open("a", encoding="utf-8")
    strong_rows = []
    chunks = 0
    for sid, bag in sessions.items():
        cov0, cov1 = bag["coverage"]
        t0 = cov0
        while t0 + 5.0 < cov1:
            t1 = min(cov1, t0 + CHUNK_S)
            if (sid, round(t0, 3)) in done:
                t0 = t1
                continue
            try:
                audio = read_span(bag["dir"], bag["meta"], t0, t1)
            except RuntimeError:
                handle.write(json.dumps({"session": sid, "t0": t0, "t1": t1, "missing": True, "text": ""}) + "\n")
                t0 = t1
                continue
            mono = 0.5 * (audio[:, 0].astype(np.float64) + audio[:, 1].astype(np.float64))
            samples = resample_poly(mono, 1, 3).astype(np.float32)
            segments, _info = model.transcribe(samples, language="en", word_timestamps=True, vad_filter=False, beam_size=1)
            words = []
            pieces = []
            for segment in segments:
                pieces.append(segment.text)
                for word in segment.words or []:
                    words.append({"start": float(word.start), "end": float(word.end), "text": word.word})
            text = " ".join(pieces).strip()
            available = t1
            hits = []
            for hit in completing_hits(words, STRONG):
                spoken = t0 + hit["spoken_end"]
                hits.append({
                    "phrase": hit["phrase"],
                    "spoken_end": round(spoken, 3),
                    "available_at": round(available, 3),
                    "kind": "strong",
                })
            for hit in completing_hits(words, WEAK):
                spoken = t0 + hit["spoken_end"]
                hits.append({
                    "phrase": hit["phrase"],
                    "spoken_end": round(spoken, 3),
                    "available_at": round(available, 3),
                    "kind": "weak",
                })
            record = {"session": sid, "t0": round(t0, 3), "t1": round(t1, 3), "missing": False, "text": text, "hits": hits}
            handle.write(json.dumps(record) + "\n")
            chunks += 1
            if chunks % 20 == 0:
                handle.flush()
                print(f"  {sid} t {t0:.0f} chunks {chunks}", flush=True)
            t0 = t1
        print(f"finished {sid}", flush=True)
        handle.flush()
    handle.close()
    print(f"transcribed {chunks} new chunks into {path.name}", flush=True)


def score(sessions, pods, started: float) -> None:
    # Gold is used only after the transcripts exist. It does not place the chunks.
    football_pods = []
    for row in pods:
        sid = row["session"]
        if sid not in sessions or sid == REDZONE:
            continue
        football_pods.append((sid, float(row["start_seconds"]), float(row["end_seconds"]), sessions[sid]["network"]))
    strong = []
    weak = []
    for path in sorted(OUT.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line:
                continue
            row = json.loads(line)
            for hit in row.get("hits") or []:
                item = {**hit, "session": row["session"]}
                if hit["kind"] == "strong":
                    strong.append(item)
                else:
                    weak.append(item)
    before = []
    causal_before = []
    for sid, start, end, network in football_pods:
        spoken = [hit for hit in strong if hit["session"] == sid and start - 30.0 <= hit["spoken_end"] <= start]
        known = [hit for hit in spoken if hit["available_at"] <= start]
        if spoken:
            before.append({"session": sid, "network": network, "start": start, "spoken_end": spoken[0]["spoken_end"], "available_at": spoken[0]["available_at"], "phrase": spoken[0]["phrase"]})
        if known:
            causal_before.append({"session": sid, "network": network, "start": start, "spoken_end": known[0]["spoken_end"], "available_at": known[0]["available_at"], "phrase": known[0]["phrase"]})
    def away(hit, margin):
        here = [(s, e) for sid, s, e, _n in football_pods if sid == hit["session"]]
        if hit["session"] == REDZONE:
            return True
        return all(hit["spoken_end"] < s - margin or hit["spoken_end"] > e + margin for s, e in here)
    program_false = [hit for hit in strong if hit["session"] != REDZONE and away(hit, 15.0)]
    redzone_strong = [hit for hit in strong if hit["session"] == REDZONE]
    summary = {
        "system": "universal_v3_speech_evidence",
        "mute_policy": False,
        "chunk_s": CHUNK_S,
        "model": "faster-whisper base.en int8 cpu beam 1",
        "football_pods": len(football_pods),
        "strong_events": len(strong),
        "weak_events": len(weak),
        "pods_with_strong_phrase_spoken_in_the_30s_before_the_start": len(before),
        "of_those_known_before_the_start": len(causal_before),
        "strong_events_at_least_15s_from_every_pod": len(program_false),
        "redzone_strong_events": len(redzone_strong),
        "examples_before": before[:20],
        "wall_s": round(time.perf_counter() - started, 1),
    }
    (OUT / "results.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: summary[key] for key in summary if key != "examples_before"}, indent=2))


if __name__ == "__main__":
    main()
