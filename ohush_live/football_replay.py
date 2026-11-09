"""Replay the football ledger on transcripts that are already finished.

    python -m ohush_live.football_replay

The transcript is the causal five-second file from the live-game scope.
This replay does not listen to the television and does not mute.
Commercial labels are read only after the ledger is finished, and only
to say whether an event came before a labeled break.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from experiments.measurement.metrics import target_commercials
from experiments.nfl75.event_asr import SCOPE
from experiments.nfl75.inventory import active_intervals
from ohush_live.football_brain import SCHEMA, FootballEngine

REPO = Path(__file__).resolve().parents[1]
TRANSCRIPTS = REPO / "docs" / "ohush" / "research" / "NFL75_EVENT_FIRST_001" / "asr_chunks.jsonl"
OUT = REPO / "docs" / "ohush" / "research" / "NFL_EVENT_ENGINE_001"


def _chunks(session: str) -> list[dict]:
    rows = []
    for line in TRANSCRIPTS.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("session") == session:
            rows.append(row)
    rows.sort(key=lambda row: (float(row["t0"]), float(row["available_t"])))
    return rows


def _complete(session: str, chunks: list[dict]) -> None:
    if not chunks:
        raise SystemExit(f"{session} has no transcript yet")
    end = SCOPE[session][1]
    if float(chunks[-1]["t1"]) + 1.0 < end:
        raise SystemExit(f"{session} transcript ends at {chunks[-1]['t1']}, scope ends at {end}")


def _lead(events: list[dict], commercials: list[tuple[float, float]]) -> list[dict]:
    rows = []
    live = [event for event in events if event["status"] == "live"]
    for start, end in commercials:
        before = [event for event in live if event["available_t"] <= start and start - 90.0 <= event["audio_t"] <= start]
        latest = max(before, key=lambda event: event["available_t"]) if before else None
        rows.append(
            {
                "start_s": round(start, 3),
                "end_s": round(end, 3),
                "duration_s": round(end - start, 3),
                "event_before": None if latest is None else latest["kind"],
                "lead_s": None if latest is None else round(start - latest["available_t"], 3),
            }
        )
    return rows


def replay_session(session: str, reader=None) -> dict:
    chunks = _chunks(session)
    _complete(session, chunks)
    engine = FootballEngine(reader=reader) if reader is not None else FootballEngine()
    events = []
    states = []
    for chunk in chunks:
        emitted, state = engine.observe(chunk)
        events.extend(emitted)
        if emitted:
            states.append({"audio_t": chunk["t0"], "available_t": chunk["available_t"], **state})
    scope = SCOPE[session]
    intervals = [
        row
        for row in active_intervals(session)
        if row.end > scope[0] and row.start < scope[1]
    ]
    commercials = [
        (max(start, scope[0]), min(end, scope[1]))
        for start, end in target_commercials(intervals)
        if start < scope[1] and end > scope[0] and min(end, scope[1]) - max(start, scope[0]) > 1.0
    ]
    leads = _lead(events, commercials)
    live = [event for event in events if event["status"] == "live"]
    uncertain = [event for event in events if event["status"] != "live"]
    latency = sorted(float(chunk["process_s"]) for chunk in chunks if chunk.get("process_s") is not None)
    def pct(q: float):
        if not latency:
            return None
        return latency[min(len(latency) - 1, int(q * (len(latency) - 1)))]
    return {
        "session": session,
        "schema": SCHEMA,
        "chunks": len(chunks),
        "events": events,
        "states": states,
        "live": len(live),
        "uncertain": len(uncertain),
        "duplicates_suppressed": engine.duplicates,
        "live_by_kind": dict(Counter(event["kind"] for event in live)),
        "uncertain_by_kind": dict(Counter(event["kind"] for event in uncertain)),
        "latency_s": {"median": pct(0.5), "p90": pct(0.9), "max": latency[-1] if latency else None},
        "breaks": len(commercials),
        "breaks_with_a_live_event_in_the_prior_90s": sum(1 for row in leads if row["event_before"]),
        "leads": leads,
        "applied": False,
    }


def main() -> None:
    if not TRANSCRIPTS.is_file():
        raise SystemExit("the causal transcript is not written yet")
    use_model = "--model" in sys.argv
    out = OUT / "model" if use_model else OUT
    out.mkdir(parents=True, exist_ok=True)
    reader = None
    if use_model:
        from ohush_live.football_llm import ModelReader

        reader = ModelReader()
    event_handle = (out / "football_events.jsonl").open("w", encoding="utf-8")
    state_handle = (out / "game_state.jsonl").open("w", encoding="utf-8")
    summary = []
    try:
        for session in SCOPE:
            measured = replay_session(session, reader)
            for event in measured["events"]:
                event_handle.write(json.dumps({"session": session, **event}) + "\n")
            for state in measured["states"]:
                state_handle.write(json.dumps({"session": session, **state}) + "\n")
            public = {key: value for key, value in measured.items() if key not in {"events", "states"}}
            summary.append(public)
            print(session, "live", measured["live"], "uncertain", measured["uncertain"], "dupes", measured["duplicates_suppressed"], flush=True)
    finally:
        event_handle.close()
        state_handle.close()
    (out / "summary.json").write_text(json.dumps({"applied": False, "reader": "qwen2.5:3b" if use_model else "phrases", "sessions": summary}, indent=2), encoding="utf-8")
    print("wrote", out)


if __name__ == "__main__":
    main()
