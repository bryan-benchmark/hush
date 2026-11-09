"""Short holds of the 0.25 voice match, with and without rearming.

    python -m experiments.nfl75.hold_main

The 10-second mean and the 0.163 line stay frozen. Holds are 1, 3, 5, and
8 seconds after a speaker window ends. Rearm means a voice block or
release cannot be followed by another cover until that mean falls below
0.163 and crosses it again. Oracle rows use gold endings. Gold labels
stay frozen. Sponsor reads stay inside the official false-mute totals.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from experiments.measurement.metrics import program_regions, target_commercials
from experiments.nfl75.diagnose import perfect_endings
from experiments.nfl75.inventory import active_intervals, coverage_by_session, excluded_ranges, wall_gaps
from experiments.nfl75.mean import PRIME_SESSIONS
from experiments.nfl75.persist import _logits, nbc_lines
from experiments.nfl75.protect import covers_protected, unprotected_covers
from experiments.nfl75.score import _with_exclusions, playback_from_covers, score_product
from tools.gpu_lab.splits import HOLDOUTS

REPO = Path(__file__).resolve().parents[2]
MEAN = REPO / "docs" / "ohush" / "research" / "NFL75_MEAN_001" / "results.json"
CACHE = REPO / "docs" / "ohush" / "research" / "NFL75_PROTECT_001" / "cache"
LABELS = REPO / "docs" / "ohush" / "research" / "VOICE_ENROLL_001" / "labels.jsonl"
CATEGORIES = REPO / "docs" / "ohush" / "research" / "NFL75_PROTECT_001" / "categories.json"
TRANSCRIPTS = REPO / "docs" / "ohush" / "research" / "NFL75_PROTECT_001" / "transcripts.jsonl"
OUT = REPO / "docs" / "ohush" / "research" / "NFL75_BOOTH_HOLD_001"
HOLDS = (1, 3, 5, 8)
_EPS = 1e-6


def _round(value, places: int):
    if value is None:
        return None
    return round(float(value), places)


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def _labels(session: str):
    coverage = coverage_by_session()[session]
    intervals = active_intervals(session)
    combined = _with_exclusions(intervals, excluded_ranges(session, intervals))
    return coverage, intervals, target_commercials(intervals), program_regions(coverage, combined)


def _still(parts: list[dict], playback) -> float:
    total = 0.0
    for part in parts:
        for span in playback:
            if span.state != "covered":
                continue
            total += _overlap(part["start_s"], part["end_s"], span.start, span.end)
    return total


def _hearing():
    categories = json.loads(CATEGORIES.read_text(encoding="utf-8"))
    rows = []
    for line in TRANSCRIPTS.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        row["category"] = categories[row["session"]][str(row["episode"])]
        rows.append(row)
    return rows


def _enroll_note(receipt: dict) -> dict:
    stamped = {}
    for line in LABELS.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            stamped[row["id"]] = row.get("at")
    clips = []
    for clip in receipt["enrollment_clips"]:
        clips.append({**clip, "labeled_at": stamped.get(clip.get("id"))})
    sessions = sorted({clip["session"] for clip in clips})
    labeled = sorted(value for value in (clip["labeled_at"] for clip in clips) if value)
    return {
        "names": receipt["names"],
        "windows": receipt["windows"],
        "model": receipt["model"],
        "clips": len(clips),
        "source_sessions": sessions,
        "earliest_available_at": min((float(clip.get("available_at", 0.0)) for clip in clips), default=None),
        "labels_adjudicated": [labeled[0], labeled[-1]] if labeled else [],
        "saved_enroll_tnf_npy_used": receipt["saved_enroll_tnf_npy_used"],
        "song_clips": [clip["id"] for clip in clips if clip.get("condition") == "song"],
    }


def _summary(scored: dict) -> dict:
    return {
        "oracle": scored["oracle"],
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
        "breaks_missed": sum(1 for row in scored["breaks"] if row["missed_break"]),
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


def _fate(baseline: list[dict], playback, current: list[dict]) -> dict:
    eliminated = shortened = untouched = split = 0
    for episode in baseline:
        left = _still(episode["parts"], playback)
        hits = 0
        for other in current:
            if _overlap(episode["start_s"], episode["end_s"], other["start_s"], other["end_s"]) > _EPS:
                hits += 1
        if left <= 0.05:
            eliminated += 1
        elif left + 0.05 < float(episode["duration_s"]):
            shortened += 1
            if hits >= 2:
                split += 1
        else:
            untouched += 1
    recreated = 0
    recreated_s = 0.0
    for episode in current:
        overlap = 0.0
        for prior in baseline:
            overlap += _overlap(episode["start_s"], episode["end_s"], prior["start_s"], prior["end_s"])
        if overlap <= _EPS:
            recreated += 1
            recreated_s += float(episode["duration_s"])
    return {
        "baseline_episodes": len(baseline),
        "episodes": len(current),
        "eliminated": eliminated,
        "shortened": shortened,
        "untouched": untouched,
        "split": split,
        "recreated": recreated,
        "recreated_s": _round(recreated_s, 3),
    }


def _sponsor(hearing: list[dict], playback) -> dict:
    rows = [row for row in hearing if row["category"] == "promo_sponsor"]
    total = 0.0
    still = 0.0
    for row in rows:
        total += float(row["duration_s"])
        still += _still([{"start_s": row["start_s"], "end_s": row["end_s"]}], playback)
    return {
        "episodes": len(rows),
        "seconds_in_official_score": _round(total, 3),
        "seconds_still_muted": _round(still, 3),
    }


def _category(hearing: list[dict], episode: dict) -> str:
    best = None
    name = None
    for row in hearing:
        amount = _overlap(episode["start_s"], episode["end_s"], row["start_s"], row["end_s"])
        if best is None or amount > best:
            best = amount
            name = row["category"]
    if best is None or best <= _EPS:
        return "outside_prior_episodes"
    return name


def _misses(breaks: list[dict], trace: list[dict], line: float, baseline: list[dict]) -> list[dict]:
    found = []
    for row, prior in zip(breaks, baseline):
        if not row["missed_break"]:
            continue
        inside = [item for item in trace if row["start_s"] - _EPS <= item["t"] < row["end_s"] - _EPS]
        below = [
            item for item in inside if item["mean"] is not None and item["mean"] < line
        ]
        reason = (
            "no reset inside the break"
            if not below
            else "the score reset inside the break and the recross did not open a cover"
        )
        found.append(
            {
                "break": row["break"],
                "start_s": row["start_s"],
                "end_s": row["end_s"],
                "reason": reason,
                "unprotected_also_missed": prior["missed_break"],
                "samples": len(inside),
                "samples_below_line": len(below),
            }
        )
    return found


def _largest(episodes: list[dict], hearing: list[dict]) -> list[dict]:
    ordered = sorted(episodes, key=lambda row: float(row["duration_s"]), reverse=True)
    return [
        {
            "start_s": row["start_s"],
            "end_s": row["end_s"],
            "duration_s": row["duration_s"],
            "category": _category(hearing, row),
        }
        for row in ordered[:5]
    ]


def _score_one(coverage, intervals, commercials, covers, session: str, oracle: bool) -> tuple[dict, list]:
    playback_covers = covers
    if oracle:
        playback_covers = perfect_endings(playback_from_covers(coverage, covers), commercials)
    playback = playback_from_covers(coverage, playback_covers)
    scored = score_product(
        coverage,
        intervals,
        playback,
        session=session,
        oracle=oracle,
        audio_present=True,
        wall_gap_s=wall_gaps().get(session, 0.0),
        excluded_ranges=excluded_ranges(session, intervals),
    )
    return _summary(scored), playback


def _policies(head, session: str, window: int, line: float, ends, cosines, hearing: list[dict]) -> dict:
    if session in HOLDOUTS or session not in PRIME_SESSIONS:
        raise RuntimeError(f"refusing {session}")
    times, scores, _ignored = _logits(head, session)
    clock = [float(moment) for moment in times]
    values = [float(score) for score in scores]
    coverage, intervals, commercials, _program = _labels(session)
    specs = [("unprotected", None, False)]
    for hold in HOLDS:
        specs.append((f"hold_{hold}", hold, False))
        specs.append((f"hold_{hold}_rearm", hold, True))
    built = {}
    for name, hold, rearm in specs:
        trace = [] if hold is not None else None
        if hold is None:
            covers = unprotected_covers(clock, values, window=window, start_line=line)
        else:
            covers = covers_protected(
                clock,
                values,
                ends,
                cosines,
                window=window,
                start_line=line,
                hold_s=hold,
                rearm=rearm,
                trace=trace,
            )
        oracle, oracle_play = _score_one(coverage, intervals, commercials, covers, session, True)
        actual, actual_play = _score_one(coverage, intervals, commercials, covers, session, False)
        built[name] = {
            "hold_s": hold,
            "rearm": rearm,
            "oracle": oracle,
            "actual": actual,
            "_oracle_play": oracle_play,
            "_actual_play": actual_play,
            "_trace": trace,
        }
    base_oracle = built["unprotected"]["oracle"]
    base_actual = built["unprotected"]["actual"]
    for name, row in built.items():
        row["oracle_fate"] = _fate(base_oracle["episodes"], row["_oracle_play"], row["oracle"]["episodes"])
        row["actual_fate"] = _fate(base_actual["episodes"], row["_actual_play"], row["actual"]["episodes"])
        row["sponsor_oracle"] = _sponsor(hearing, row["_oracle_play"])
        row["sponsor_actual"] = _sponsor(hearing, row["_actual_play"])
        row["largest_oracle"] = _largest(row["oracle"]["episodes"], hearing)
        row["largest_actual"] = _largest(row["actual"]["episodes"], hearing)
        if row["_trace"] is not None:
            row["missed_because"] = {
                "oracle": _misses(row["oracle"]["breaks"], row["_trace"], line, base_oracle["breaks"]),
                "actual": _misses(row["actual"]["breaks"], row["_trace"], line, base_actual["breaks"]),
            }
        else:
            row["missed_because"] = {"oracle": [], "actual": []}
        for key in ("_oracle_play", "_actual_play", "_trace"):
            del row[key]
    return built


def _audit(hearing: list[dict]) -> list[dict]:
    kept = []
    for row in hearing:
        if row["category"] != "promo_sponsor":
            continue
        kept.append(
            {
                "session": row["session"],
                "episode": row["episode"],
                "start_s": row["start_s"],
                "end_s": row["end_s"],
                "duration_s": row["duration_s"],
                "transcript": row["transcript"][:180],
            }
        )
    return kept


def _clears(row: dict) -> bool:
    coverage = row["commercial_coverage"]
    rate = row["false_mutes_per_hour"]
    longest = row["longest_false_mute_s"]
    hidden = row["program_hidden_per_hour"]
    if None in (coverage, rate, longest, hidden):
        return False
    return coverage >= 0.75 and rate < 1.0 and longest < 10.0 and hidden < 5.0


def main() -> None:
    frozen = json.loads(MEAN.read_text(encoding="utf-8"))["frozen"]
    window = int(frozen["window_s"])
    line = float(frozen["start_line"])
    if window != 10:
        raise RuntimeError("refusing a start window other than the frozen 10-second mean")
    lines = nbc_lines()
    hearing = _hearing()
    sessions = []
    for session in PRIME_SESSIONS:
        path = CACHE / f"{session}.npz"
        if not path.is_file():
            raise SystemExit(f"missing speaker replay {path}")
        bundle = np.load(path)
        receipt = json.loads((CACHE / f"{session}.json").read_text(encoding="utf-8"))
        policies = _policies(
            lines["head"],
            session,
            window,
            line,
            bundle["end"].tolist(),
            bundle["cosine"].tolist(),
            [row for row in hearing if row["session"] == session],
        )
        sessions.append(
            {
                "session": session,
                "development_inspection": True,
                "enrollment": _enroll_note(receipt),
                "policies": policies,
            }
        )
        plain = policies["unprotected"]["oracle"]
        held = policies["hold_1"]["oracle"]
        print(
            session,
            "hold1",
            held["false_mute_episodes"],
            "vs unprotected",
            plain["false_mute_episodes"],
            "coverage",
            policies["hold_8_rearm"]["actual"]["commercial_coverage"],
        )
    names = list(sessions[0]["policies"])
    any_clear = any(
        _clears(session["policies"][name]["oracle"]) and _clears(session["policies"][name]["actual"])
        for session in sessions
        for name in names
    )
    both = any(
        all(
            _clears(session["policies"][name]["oracle"]) and _clears(session["policies"][name]["actual"])
            for session in sessions
        )
        for name in names
    )
    verdict = "KEEP" if both else "REJECT"
    payload = {
        "experiment": "NFL75_BOOTH_HOLD_001",
        "verdict": verdict,
        "deployable": False,
        "automatic_mute": False,
        "any_single_game_clears_both_returns": any_clear,
        "frozen_start": {"window_s": window, "start_line": line, "source": "NFL75_MEAN_001"},
        "holds_s": list(HOLDS),
        "rearm": "after a 0.25 match blocks or releases a cover, the 10-second mean must fall below the frozen line and cross it again",
        "enrollment_limit": (
            "The owner labeled these clips on 2026-10-18, after both Prime games. "
            "October uses September 24 audio only, so the vectors predate October, and the clip choice does not. "
            "September has no earlier TNF enrollment. Its clips are from the same game and start at each clip's end."
        ),
        "sponsor_reads_marked_program": _audit(hearing),
        "gold_labels_changed": False,
        "fit": lines["fit"],
        "sessions": sessions,
        "next_experiment": None
        if verdict == "KEEP"
        else "OHUSH_NFL75_HARDNEG_001: a lightweight veto on the existing AST scores, trained to separate commercials from the football this detector still mutes. Do not sweep another hold.",
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(verdict, OUT / "results.json")


if __name__ == "__main__":
    main()
