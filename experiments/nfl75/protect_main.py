"""Score the current announcer veto on the frozen rolling mean.

    python -m experiments.nfl75.protect_main

The start line is read from NFL75_MEAN_001. It is not chosen again.
October 8 and September 24 stay development tapes. The 30-second memory
row is a cost measurement, not the gate. Speakers stay put.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from experiments.measurement.metrics import program_regions, target_commercials
from experiments.nfl75.diagnose import perfect_endings
from experiments.nfl75.inventory import active_intervals, coverage_by_session, excluded_ranges, wall_gaps
from experiments.nfl75.mean import PRIME_SESSIONS, product_caps
from experiments.nfl75.persist import WINDOW_S, _logits, nbc_lines
from experiments.nfl75.protect import (
    covers_protected,
    fresh_cosine,
    memory_max,
    show_memory_would_protect,
    unprotected_covers,
)
from experiments.nfl75.score import _with_exclusions, playback_from_covers, score_product
from hush.speaker_memory import MATCH_COSINE
from tools.gpu_lab.splits import HOLDOUTS

REPO = Path(__file__).resolve().parents[2]
MEAN = REPO / "docs" / "ohush" / "research" / "NFL75_MEAN_001" / "results.json"
CACHE = REPO / "docs" / "ohush" / "research" / "NFL75_PROTECT_001" / "cache"
OUT = REPO / "docs" / "ohush" / "research" / "NFL75_PROTECT_001"


def _round(value, places: int):
    if value is None:
        return None
    return round(float(value), places)


def _labels(session: str):
    coverage = coverage_by_session()[session]
    intervals = active_intervals(session)
    combined = _with_exclusions(intervals, excluded_ranges(session, intervals))
    return coverage, intervals, target_commercials(intervals), program_regions(coverage, combined)


def _summary(name: str, scored: dict, *, oracle: bool, diagnostic: bool) -> dict:
    return {
        "name": name,
        "oracle": oracle,
        "diagnostic_only": diagnostic or oracle or not scored["evaluable"],
        "deployable": False,
        "commercial_coverage": _round(scored["commercial_coverage"], 4),
        "commercial_covered_s": _round(scored["commercial_covered_s"], 3),
        "commercial_s": _round(scored["commercial_s"], 3),
        "false_mute_episodes": scored["false_mute_episodes"],
        "false_mutes_per_hour": _round(scored["false_mutes_per_hour"], 3),
        "longest_false_mute_s": _round(scored["longest_false_mute_s"], 3),
        "program_covered_s": _round(scored["program_covered_s"], 3),
        "program_hidden_per_hour": _round(scored["program_hidden_per_hour"], 3),
        "program_s": _round(scored["program_s"], 3),
        "product_caps": product_caps(scored),
        "breaks": [
            {
                "break": row["break"],
                "start_s": _round(row["start_s"], 3),
                "end_s": _round(row["end_s"], 3),
                "start_delay_s": _round(row["start_delay_s"], 3),
                "covered_s": _round(row["covered_s"], 3),
                "late_return_s": _round(row["late_return_s"], 3),
                "missed_break": row["missed_break"],
            }
            for row in scored["breaks"]
        ],
        "episodes": [
            {
                "start_s": _round(row["start_s"], 3),
                "end_s": _round(row["end_s"], 3),
                "duration_s": _round(row["duration_s"], 3),
                "parts": row["parts"],
            }
            for row in scored["episodes"]
        ],
    }


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def _still_covered(episode: dict, playback) -> float:
    total = 0.0
    for part in episode["parts"]:
        for span in playback:
            if span.state != "covered":
                continue
            total += _overlap(part["start_s"], part["end_s"], span.start, span.end)
    return total


def _voice_at(ends, cosines, people, names, moment: float) -> dict:
    fresh = fresh_cosine(ends, cosines, moment)
    remembered = memory_max(ends, cosines, moment)
    who = None
    if fresh is not None:
        best_index = None
        best = None
        for index, (end, score) in enumerate(zip(ends, cosines)):
            if float(end) > moment + 1e-9:
                break
            if moment - float(end) <= 1.0 + 1e-9 and (best is None or float(score) > best):
                best = float(score)
                best_index = index
        if best_index is not None and names:
            row = np.asarray(people[best_index], dtype=np.float64)
            if np.isfinite(row).any():
                who = names[int(np.nanargmax(row))]
    if fresh is None:
        reason = "no speaker window ended in the last second"
    elif fresh < MATCH_COSINE:
        reason = "current cosine is below 0.25"
    else:
        reason = "current enrolled match is at or above 0.25"
    return {
        "fresh_cosine": _round(fresh, 4),
        "memory_max_30s": _round(remembered, 4),
        "memory_would_protect": show_memory_would_protect(remembered),
        "current_would_protect": fresh is not None and fresh + 1e-12 >= MATCH_COSINE,
        "nearest_name": who,
        "reason": reason,
    }


def _latency(before: list[dict], after: list[dict]) -> dict:
    extra = []
    lost = 0
    for left, right in zip(before, after):
        if left["missed_break"]:
            continue
        if right["missed_break"]:
            lost += 1
            continue
        extra.append(float(right["start_delay_s"]) - float(left["start_delay_s"]))
    if not extra:
        return {"breaks_with_both_starts": 0, "breaks_lost": lost, "median_extra_s": None, "mean_extra_s": None}
    ordered = sorted(extra)
    return {
        "breaks_with_both_starts": len(extra),
        "breaks_lost": lost,
        "median_extra_s": round(ordered[len(ordered) // 2], 3),
        "mean_extra_s": round(sum(extra) / len(extra), 3),
    }


def _policy(head, session: str, window: int, line: float, ends, cosines, people, names) -> dict:
    if session in HOLDOUTS or session not in PRIME_SESSIONS:
        raise RuntimeError(f"refusing {session}")
    times, scores, _labels_ignored = _logits(head, session)
    clock = [float(moment) for moment in times]
    values = [float(score) for score in scores]
    coverage, intervals, commercials, _program = _labels(session)
    plain = unprotected_covers(clock, values, window=window, start_line=line)
    current = covers_protected(clock, values, ends, cosines, window=window, start_line=line)
    memory = covers_protected(
        clock, values, ends, cosines, window=window, start_line=line, rule="memory"
    )
    rows = {}
    for name, covers, oracle_flag, diagnostic in (
        ("unprotected_oracle", perfect_endings(playback_from_covers(coverage, plain), commercials), True, True),
        ("unprotected_actual", plain, False, False),
        ("current_oracle", perfect_endings(playback_from_covers(coverage, current), commercials), True, True),
        ("current_actual", current, False, False),
        ("memory_oracle", perfect_endings(playback_from_covers(coverage, memory), commercials), True, True),
        ("memory_actual", memory, False, True),
    ):
        playback = playback_from_covers(coverage, covers)
        scored = score_product(
            coverage,
            intervals,
            playback,
            session=session,
            oracle=oracle_flag,
            audio_present=True,
            wall_gap_s=wall_gaps().get(session, 0.0),
            excluded_ranges=excluded_ranges(session, intervals),
        )
        rows[name] = _summary(name, scored, oracle=oracle_flag, diagnostic=diagnostic)
        rows[name]["playback"] = playback
    base = rows["unprotected_oracle"]["episodes"]
    guarded_playback = rows["current_oracle"]["playback"]
    audited = []
    cleared = shortened = 0
    for episode in base:
        left = _still_covered(episode, guarded_playback)
        voice = _voice_at(ends, cosines, people, names, float(episode["start_s"]))
        if left <= 1e-6:
            fate = "cleared"
            cleared += 1
        elif left + 1e-6 < float(episode["duration_s"]):
            fate = "shortened"
            shortened += 1
        else:
            fate = "untouched"
        audited.append(
            {
                "start_s": episode["start_s"],
                "end_s": episode["end_s"],
                "duration_s": episode["duration_s"],
                "remaining_s": _round(left, 3),
                "fate": fate,
                "voice": voice,
            }
        )
    before = rows["unprotected_oracle"]["commercial_covered_s"]
    after = rows["current_oracle"]["commercial_covered_s"]
    for key in rows:
        rows[key].pop("playback", None)
    return {
        "session": session,
        "development_inspection": True,
        "deployable": False,
        "episodes_oracle": len(base),
        "episodes_cleared": cleared,
        "episodes_shortened": shortened,
        "episodes_untouched": len(base) - cleared - shortened,
        "fraction_episodes_cleared": round(cleared / len(base), 4) if base else None,
        "commercial_seconds_lost_oracle": _round(before - after, 3),
        "latency_oracle": _latency(rows["unprotected_oracle"]["breaks"], rows["current_oracle"]["breaks"]),
        "latency_actual": _latency(rows["unprotected_actual"]["breaks"], rows["current_actual"]["breaks"]),
        "policies": {key: value for key, value in rows.items()},
        "oracle_episodes": audited,
    }


def main() -> None:
    frozen = json.loads(MEAN.read_text(encoding="utf-8"))["frozen"]
    window = int(frozen["window_s"])
    line = float(frozen["start_line"])
    lines = nbc_lines()
    sessions = []
    for session in PRIME_SESSIONS:
        path = CACHE / f"{session}.npz"
        if not path.is_file():
            raise SystemExit(f"missing speaker replay {path}. Run protect_embed.py on Python 3.13.")
        bundle = np.load(path)
        receipt = json.loads((CACHE / f"{session}.json").read_text(encoding="utf-8"))
        measured = _policy(
            lines["head"],
            session,
            window,
            line,
            bundle["end"].tolist(),
            bundle["cosine"].tolist(),
            bundle["people"],
            receipt["names"],
        )
        measured["speaker_replay"] = {
            "model": receipt["model"],
            "windows": receipt["windows"],
            "names": receipt["names"],
            "enrollment_clips": len(receipt["enrollment_clips"]),
            "enrollment_sessions": sorted({row["session"] for row in receipt["enrollment_clips"]}),
            "saved_enroll_tnf_npy_used": receipt["saved_enroll_tnf_npy_used"],
        }
        sessions.append(measured)
        print(
            session,
            "cleared",
            measured["episodes_cleared"],
            "/",
            measured["episodes_oracle"],
            "lost_ad_s",
            measured["commercial_seconds_lost_oracle"],
        )
    payload = {
        "experiment": "NFL75_PROTECT_001",
        "deployable": False,
        "automatic_mute": False,
        "gate": "current ECAPA cosine >= 0.25 within the last 1 second",
        "memory_rule": "30 second rolling max >= 0.10, diagnostic cost only",
        "frozen_start": {"window_s": window, "start_line": line, "source": "NFL75_MEAN_001"},
        "fit": lines["fit"],
        "sessions": sessions,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print("wrote", OUT / "results.json")


if __name__ == "__main__":
    main()
