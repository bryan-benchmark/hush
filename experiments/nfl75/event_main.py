"""Score an event-first watch on the two Prime development tapes.

    python -m experiments.nfl75.event_main

The transcript has to exist already (`event_asr.py` on Python 3.13). Gold
is used only after the events and the covers exist. The 0.163 line is read
from NFL75_MEAN_001. Nothing is trained.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from experiments.measurement.metrics import Interval, target_commercials
from experiments.nfl75.broadcast_opportunity import booth_cosine, match_times
from experiments.nfl75.diagnose import perfect_endings
from experiments.nfl75.event_asr import SCOPE
from experiments.nfl75.events import EXPECTATION, HORIZON_S, covers_from_events, extract_events, watches_from_events
from experiments.nfl75.inventory import active_intervals, coverage_by_session, excluded_ranges, wall_gaps
from experiments.nfl75.mean import covers_from_mean, product_caps, rolling_means
from experiments.nfl75.persist import RETURN_PERSIST_S, _logits, nbc_lines
from experiments.nfl75.score import playback_from_covers, score_product
from tools.gpu_lab.splits import HOLDOUTS

REPO = Path(__file__).resolve().parents[2]
MEAN = REPO / "docs" / "ohush" / "research" / "NFL75_MEAN_001" / "results.json"
CACHE = REPO / "docs" / "ohush" / "research" / "NFL75_PROTECT_001" / "cache"
ONSETS = REPO / "docs" / "ohush" / "research" / "NFL75_BROADCAST_OPPORTUNITY_001" / "cache"
OUT = REPO / "docs" / "ohush" / "research" / "NFL75_EVENT_FIRST_001"
SHORT_S = 50.0
LONG_S = 90.0


def _round(value, places: int):
    if value is None:
        return None
    return round(float(value), places)


def _clip(intervals, scope):
    start, end = scope
    clipped = []
    for row in intervals:
        left, right = max(row.start, start), min(row.end, end)
        if right - left <= 1e-6:
            continue
        clipped.append(Interval(left, right, row.event_class, row.desired_action, row.confidence))
    return clipped


def _load_chunks(session: str) -> list[dict]:
    path = OUT / "asr_chunks.jsonl"
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("session") == session:
            rows.append(row)
    rows.sort(key=lambda row: float(row["t0"]))
    return rows


def _events(chunks: list[dict]) -> list[dict]:
    found = []
    previous = ""
    for chunk in chunks:
        text = str(chunk.get("text") or "")
        for event in extract_events(text, previous):
            event = dict(event)
            event["t0"] = float(chunk["t0"])
            event["t1"] = float(chunk["t1"])
            event["available_t"] = float(chunk["available_t"])
            event["process_s"] = chunk.get("process_s")
            event["text"] = text
            found.append(event)
        previous = text
    return found


def _hits(watch: dict, commercials: list[tuple[float, float]]) -> list[tuple[float, float]]:
    return [
        (start, end)
        for start, end in commercials
        if watch["open_s"] < end and watch["close_s"] > start
    ]


def _summary(scored: dict) -> dict:
    episodes = sorted(scored["episodes"], key=lambda row: -float(row["duration_s"]))
    return {
        "commercial_coverage": _round(scored["commercial_coverage"], 4),
        "commercial_covered_s": _round(scored["commercial_covered_s"], 3),
        "commercial_s": _round(scored["commercial_s"], 3),
        "false_mute_episodes": scored["false_mute_episodes"],
        "false_mutes_per_hour": _round(scored["false_mutes_per_hour"], 3),
        "longest_false_mute_s": _round(scored["longest_false_mute_s"], 3),
        "program_hidden_per_hour": _round(scored["program_hidden_per_hour"], 3),
        "program_s": _round(scored["program_s"], 3),
        "product_caps": product_caps(scored),
        "coverage_at_least_75": scored["commercial_coverage"] is not None and scored["commercial_coverage"] >= 0.75,
        "breaks": [
            {
                "start_s": _round(row["start_s"], 3),
                "end_s": _round(row["end_s"], 3),
                "covered_s": _round(row["covered_s"], 3),
                "start_delay_s": _round(row["start_delay_s"], 3),
                "late_return_s": _round(row["late_return_s"], 3),
                "missed_break": row["missed_break"],
            }
            for row in scored["breaks"]
        ],
        "longest_episodes": [
            {"start_s": _round(row["start_s"], 3), "end_s": _round(row["end_s"], 3), "duration_s": _round(row["duration_s"], 3)}
            for row in episodes[:8]
        ],
    }


def _score(session, scope, intervals, covers, *, oracle: bool) -> dict:
    playback = playback_from_covers(scope, covers)
    if oracle:
        playback = playback_from_covers(scope, perfect_endings(playback, target_commercials(intervals)))
    return score_product(
        scope,
        intervals,
        playback,
        session=session,
        oracle=oracle,
        audio_present=False,
        wall_gap_s=wall_gaps().get(session, 0.0),
        excluded_ranges=excluded_ranges(session, intervals),
    )


def _booth_name(ends, people, names, t0, t1) -> str | None:
    best_name = None
    best = -1.0
    booth_columns = [index for index, name in enumerate(names) if name in ("Al Michaels", "Kirk Herbstreit")]
    for index, end in enumerate(ends):
        if end < t0 or end > t1:
            continue
        for column in booth_columns:
            value = float(people[index, column])
            if np.isfinite(value) and value >= 0.25 and value > best:
                best = value
                best_name = names[column]
    return best_name


def _duration_bucket(duration: float) -> str:
    if duration < SHORT_S:
        return "short"
    if duration >= LONG_S:
        return "long"
    return "in_between"


def main() -> None:
    if any(session in HOLDOUTS for session in SCOPE):
        raise SystemExit("refusing a sealed holdout")
    chunks_path = OUT / "asr_chunks.jsonl"
    if not chunks_path.is_file():
        raise SystemExit("missing transcripts. Run event_asr.py on Python 3.13.")
    frozen = json.loads(MEAN.read_text(encoding="utf-8"))["frozen"]
    window = int(frozen["window_s"])
    line = float(frozen["start_line"])
    head = nbc_lines()["head"]
    sessions = []
    timeline = []
    for session, scope in SCOPE.items():
        chunks = _load_chunks(session)
        events = _events(chunks)
        watches = watches_from_events(events)
        intervals = _clip(active_intervals(session), scope)
        commercials = target_commercials(intervals)
        times, scores, _labels = _logits(head, session)
        times = [float(moment) for moment in times]
        scores = [float(score) for score in scores]
        means = rolling_means(times, scores, window)
        keep = [index for index, moment in enumerate(times) if scope[0] - 1e-9 <= moment < scope[1] - 1e-9]
        scoped_times = [times[index] for index in keep]
        scoped_scores = [scores[index] for index in keep]
        scoped_means = [means[index] for index in keep]
        bundle = np.load(CACHE / f"{session}.npz")
        receipt = json.loads((CACHE / f"{session}.json").read_text(encoding="utf-8"))
        booth = booth_cosine(bundle["people"], receipt["names"])
        ends = [float(moment) for moment in bundle["end"].tolist()]
        matches = match_times(ends, booth.tolist())
        covers, flags = covers_from_events(
            scoped_times, scoped_scores, scoped_means, matches, watches, start_line=line, return_persist_s=RETURN_PERSIST_S
        )
        causal = _summary(_score(session, scope, intervals, covers, oracle=False))
        oracle = _summary(_score(session, scope, intervals, covers, oracle=True))
        onsets = json.loads((ONSETS / f"{session}_onsets.json").read_text(encoding="utf-8"))["onsets"]
        live = [event for event in events if event["status"] == "live"]
        uncertain = [event for event in events if event["status"] != "live"]
        false_watches = []
        hit_watches = []
        for watch in watches:
            hits = _hits(watch, commercials)
            if hits:
                hit_watches.append(watch)
            else:
                false_watches.append(watch)
        by_kind = Counter(event["kind"] for event in live)
        uncertain_kind = Counter(event["kind"] for event in uncertain)
        break_rows = []
        for start, end in commercials:
            duration = end - start
            predicting = [watch for watch in watches if watch["open_s"] <= start < watch["close_s"]]
            overlapping = [watch for watch in watches if watch["open_s"] < end and watch["close_s"] > start]
            latest = max(predicting, key=lambda watch: watch["open_s"]) if predicting else None
            acoustic = any(start - 10.0 <= float(moment) <= start + 5.0 for moment in onsets) and bool(predicting)
            break_rows.append(
                {
                    "start_s": round(start, 3),
                    "end_s": round(end, 3),
                    "duration_s": round(duration, 3),
                    "bucket": _duration_bucket(duration),
                    "followed_a_live_event": bool(overlapping),
                    "predicted_before_start": latest is not None,
                    "event_kind": None if latest is None else latest["kind"],
                    "expectation": None if latest is None else latest["expectation"],
                    "event_available_s": None if latest is None else round(latest["open_s"], 3),
                    "lead_s": None if latest is None else round(start - latest["open_s"], 3),
                    "said_lead_s": None if latest is None else round(start - latest["said_s"], 3),
                    "acoustic_near_start": acoustic,
                }
            )
        short_calls = [row for row in break_rows if row["event_kind"] == "short_break"]
        long_calls = [row for row in break_rows if row["expectation"] == "long"]
        watch_seconds = sum(1 for flag in flags if flag)
        for event in live:
            if event["kind"] in ("return",):
                continue
            who = _booth_name(ends, bundle["people"], receipt["names"], event["t0"], event["t1"])
            timeline.append(
                {
                    "session": session,
                    "t0": event["t0"],
                    "available_t": round(event["available_t"], 3),
                    "kind": event["kind"],
                    "expectation": event["expectation"],
                    "status": event["status"],
                    "booth": who,
                    "text": event["text"][:180],
                }
            )
        sessions.append(
            {
                "session": session,
                "scope": {"start_s": scope[0], "end_s": scope[1]},
                "chunks": len(chunks),
                "events_live": len(live),
                "events_uncertain": len(uncertain),
                "live_by_kind": dict(by_kind),
                "uncertain_by_kind": dict(uncertain_kind),
                "watches": len(watches),
                "watches_that_hit_a_break": len(hit_watches),
                "false_opportunities": len(false_watches),
                "false_opportunities_by_kind": dict(Counter(watch["kind"] for watch in false_watches)),
                "watch_seconds": watch_seconds,
                "breaks": len(commercials),
                "breaks_followed_by_event_watch": sum(1 for row in break_rows if row["followed_a_live_event"]),
                "breaks_predicted_before_start": sum(1 for row in break_rows if row["predicted_before_start"]),
                "breaks_with_acoustic_near_a_prediction": sum(1 for row in break_rows if row["acoustic_near_start"]),
                "short_language_on_a_break": {
                    "n": len(short_calls),
                    "actually_short": sum(1 for row in short_calls if row["bucket"] == "short"),
                },
                "long_event_on_a_break": {
                    "n": len(long_calls),
                    "actually_long": sum(1 for row in long_calls if row["bucket"] == "long"),
                },
                "break_rows": break_rows,
                "causal": causal,
                "oracle": oracle,
                "horizons_s": HORIZON_S,
                "expectations": EXPECTATION,
            }
        )
        print(
            session,
            "chunks",
            len(chunks),
            "live",
            len(live),
            "watches",
            len(watches),
            "false",
            len(false_watches),
            "predicted",
            sum(1 for row in break_rows if row["predicted_before_start"]),
            "/",
            len(commercials),
            "cov",
            causal["commercial_coverage"],
            "eph",
            causal["false_mutes_per_hour"],
            flush=True,
        )
    kept = all(
        row["causal"]["product_caps"]
        and row["causal"]["coverage_at_least_75"]
        and row["oracle"]["product_caps"]
        and row["oracle"]["coverage_at_least_75"]
        for row in sessions
    )
    payload = {
        "experiment": "NFL75_EVENT_FIRST_001",
        "deployable": False,
        "automatic_mute": False,
        "hardneg_paused": True,
        "absence_residual_paused": True,
        "frozen_start": {"window_s": window, "start_line": line, "source": "NFL75_MEAN_001"},
        "mute_rule": "a live event opens a watch; the watch stays open while the booth keeps talking; mute only when the watch is open, the frozen mean is at or above 0.163, and no booth match ended in the last 1 second",
        "verdict": "KEEP" if kept else "REJECT",
        "sessions": sessions,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (OUT / "events.jsonl").write_text("".join(json.dumps(row) + "\n" for row in timeline), encoding="utf-8")
    print("wrote", OUT / "results.json", payload["verdict"])


if __name__ == "__main__":
    main()
