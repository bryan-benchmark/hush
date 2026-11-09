"""Causal football ledger from the local model already on this PC.

    python -m ohush_live.gpu_brain

Chunks are read in time order. The model sees one finished line, the previous
line, and the ledger accepted so far. It does not see commercial labels.
A resumed run continues from calls already written. Speakers are not touched.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np
import soundfile as sf

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from experiments.nfl75.event_asr import SCOPE
from hush.audio import analysis_pieces, find_session, load_session
from ohush_live.football_brain import FootballEngine
from ohush_live.football_llm import MODEL, ModelReader
from ohush_live.football_replay import _chunks, _complete

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "docs" / "ohush" / "research" / "NFL_GPU_BRAIN_001"
CALLS = OUT / "calls.jsonl"


def _ledger_line(state: dict) -> str:
    score = "unknown" if not state.get("score_pair") else "-".join(str(n) for n in state["score_pair"])
    team = state.get("score_team") or "unknown"
    return (
        f"quarter={state.get('quarter')} score={score} team={team} "
        f"phase={state.get('phase')} stoppage={state.get('last_stoppage')} "
        f"sequence={state.get('scoring_sequence_id')}"
    )


def _load_calls() -> dict[tuple[str, float], dict]:
    saved = {}
    if not CALLS.is_file():
        return saved
    for line in CALLS.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        saved[(row["session"], float(row["t0"]))] = row
    return saved


def _gpu() -> str:
    try:
        return subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.used,utilization.gpu", "--format=csv,noheader"],
            text=True,
            timeout=10,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return "unavailable"


def _ollama_ps() -> str:
    try:
        return subprocess.check_output(["ollama", "ps"], text=True, timeout=15).strip()
    except (OSError, subprocess.SubprocessError) as exc:
        return str(exc)


def replay() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    saved = _load_calls()
    reader = ModelReader()
    handle = CALLS.open("a", encoding="utf-8")
    summaries = []
    gpu_notes = [_gpu()]
    new_calls = 0
    showed_gpu = False
    try:
        for session in SCOPE:
            chunks = _chunks(session)
            _complete(session, chunks)
            engine = FootballEngine(reader=reader)
            events = []
            states = []
            infer = []
            for index, chunk in enumerate(chunks):
                key = (session, float(chunk["t0"]))
                prior = saved.get(key)
                reader.context = _ledger_line(engine.state.view())
                reader.last_events = []
                reader.last_infer_s = 0.0
                if prior is None:
                    reader.replay = None
                else:
                    reader.replay = prior
                emitted, state = engine.observe(chunk)
                if prior is None and reader.last_infer_s and not showed_gpu:
                    print(_ollama_ps(), flush=True)
                    showed_gpu = True
                if prior is None:
                    row = {
                        "session": session,
                        "t0": float(chunk["t0"]),
                        "t1": float(chunk["t1"]),
                        "available_t": float(chunk["available_t"]),
                        "text": chunk.get("text") or "",
                        "events": reader.last_events,
                        "facts": reader.facts,
                        "infer_s": round(reader.last_infer_s, 3),
                        "errors": reader.errors,
                    }
                    handle.write(json.dumps(row) + "\n")
                    handle.flush()
                    saved[key] = row
                    new_calls += 1
                    if reader.last_infer_s:
                        infer.append(reader.last_infer_s)
                    if new_calls % 25 == 0:
                        print(session, "t", chunk["t0"], "new", new_calls, "infer", row["infer_s"], "gpu", _gpu(), flush=True)
                    if new_calls % 200 == 0:
                        gpu_notes.append(_gpu())
                events.extend(emitted)
                if emitted:
                    states.append({"session": session, "audio_t": chunk["t0"], "available_t": chunk["available_t"], **state})
                if index and index % 400 == 0 and prior is not None:
                    print(session, "replayed", index, flush=True)
            live = [event for event in events if event["status"] == "live"]
            uncertain = [event for event in events if event["status"] != "live"]
            infer.sort()
            summaries.append(
                {
                    "session": session,
                    "chunks": len(chunks),
                    "live": len(live),
                    "uncertain": len(uncertain),
                    "duplicates_suppressed": engine.duplicates,
                    "model_errors": reader.errors,
                    "live_by_kind": dict(Counter(event["kind"] for event in live)),
                    "uncertain_by_kind": dict(Counter(event["kind"] for event in uncertain)),
                    "infer_s": _pct(infer),
                    "slower_than_chunk": sum(1 for value in infer if value > 5.0),
                    "events": [{**event, "session": session} for event in events],
                    "states": states,
                }
            )
            print(session, "live", len(live), "uncertain", len(uncertain), "errors", reader.errors, flush=True)
    finally:
        handle.close()
    _write_outputs(summaries, gpu_notes)
    return {"sessions": [{k: v for k, v in row.items() if k not in {"events", "states"}} for row in summaries]}


def _pct(values: list[float]) -> dict:
    if not values:
        return {"n": 0, "median": None, "p90": None, "max": None}
    def pick(q: float) -> float:
        return round(values[min(len(values) - 1, int(q * (len(values) - 1)))], 3)
    return {"n": len(values), "median": pick(0.5), "p90": pick(0.9), "max": round(values[-1], 3)}


def _write_outputs(summaries: list[dict], gpu_notes: list[str]) -> None:
    events = OUT / "football_events.jsonl"
    states = OUT / "game_state.jsonl"
    with events.open("w", encoding="utf-8") as handle:
        for row in summaries:
            for event in row["events"]:
                handle.write(json.dumps(event) + "\n")
    with states.open("w", encoding="utf-8") as handle:
        for row in summaries:
            for state in row["states"]:
                handle.write(json.dumps(state) + "\n")
    public = []
    for row in summaries:
        public.append({key: value for key, value in row.items() if key not in {"events", "states"}})
    (OUT / "summary.json").write_text(
        json.dumps(
            {
                "applied": False,
                "model": MODEL,
                "gold_read": False,
                "gpu_samples": gpu_notes,
                "ollama_ps": _ollama_ps(),
                "sessions": public,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def clips() -> None:
    """Short review audio for scoring lines, other events, and ordinary talk."""
    events = [json.loads(line) for line in (OUT / "football_events.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    chosen = []
    for event in events:
        if event["kind"] in {"TOUCHDOWN", "FIELD_GOAL_GOOD", "FIELD_GOAL_MISSED", "SCORE_UPDATE", "EXTRA_POINT", "TWO_POINT_CONVERSION"}:
            chosen.append(event)
    for kind in ("TIMEOUT", "INTERCEPTION", "FUMBLE_RECOVERY", "QUARTER_END", "HALFTIME", "TWO_MINUTE_WARNING", "BREAK_DURATION_ANNOUNCED", "BROADCAST_SIGNOFF"):
        taken = 0
        for event in events:
            if event["kind"] == kind and event["status"] == "live":
                chosen.append(event)
                taken += 1
                if taken == 2:
                    break
    folder = OUT / "clips"
    folder.mkdir(parents=True, exist_ok=True)
    index = []
    for event in chosen[:80]:
        name = f"{event['session'][-6:]}_{int(event['audio_t']):05d}_{event['kind']}_{event['status']}.wav"
        _cut(event["session"], float(event["audio_t"]), folder / name)
        index.append({"file": name, "audio_t": event["audio_t"], "kind": event["kind"], "status": event["status"], "text": event.get("text", "")[:180]})
    calls = _load_calls()
    controls = [row for row in calls.values() if not row.get("events") and len(row.get("text") or "") > 60]
    controls.sort(key=lambda row: (row["session"], row["t0"]))
    step = max(1, len(controls) // 6)
    for row in controls[::step][:6]:
        name = f"{row['session'][-6:]}_{int(row['t0']):05d}_CONTROL.wav"
        _cut(row["session"], float(row["t0"]), folder / name)
        index.append({"file": name, "audio_t": row["t0"], "kind": "CONTROL", "status": "", "text": row["text"][:180]})
    (OUT / "clips.jsonl").write_text("".join(json.dumps(row) + "\n" for row in index), encoding="utf-8")
    print("clips", len(index), flush=True)


def _cut(session: str, audio_t: float, dest: Path) -> None:
    session_dir = find_session(REPO / "recordings", session)
    meta = load_session(session_dir)
    pieces = analysis_pieces(session_dir, meta, max(0.0, audio_t - 1.0), audio_t + 5.0)
    audio = []
    for piece in pieces:
        data, _sr = sf.read(str(piece["path"]), start=piece["read_start_frame"], stop=piece["read_stop_frame"], dtype="float32")
        if piece["pad_frames"]:
            data = np.pad(data, ((0, piece["pad_frames"]), (0, 0)))
        audio.append(data)
    sf.write(str(dest), np.concatenate(audio), 48000)


def main() -> None:
    global OUT, CALLS
    if len(sys.argv) > 1:
        OUT = Path(sys.argv[1])
        CALLS = OUT / "calls.jsonl"
    started = time.perf_counter()
    print("model", MODEL, flush=True)
    print(_ollama_ps(), flush=True)
    summary = replay()
    clips()
    print("elapsed_s", round(time.perf_counter() - started, 1), flush=True)
    print(json.dumps(summary, indent=2))
    print("wrote", OUT)


if __name__ == "__main__":
    main()
