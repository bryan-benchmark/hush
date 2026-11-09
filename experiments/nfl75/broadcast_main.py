"""Measure broadcast opportunities on the two Prime development tapes.

    python -m experiments.nfl75.broadcast_main

The rolling mean and the 0.163 line are read from NFL75_MEAN_001. They are
not chosen again. Kickoff is the start of annotated coverage. The live-game
scope ends at the postgame-show closer already transcribed in EXP-03.
Pregame is not separately labeled. Postgame and nightcap after that closer
are outside the scope. Gold does not arm a transition.

Phrase arms are folded in only when the causal ASR file is present. A
missing file leaves B and C unmeasured rather than borrowing the
retrospective 30-second windows.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import numpy as np
import soundfile as sf

from experiments.measurement.metrics import Interval, program_regions, target_commercials
from experiments.nfl75.broadcast_opportunity import (
    ABSENCE_S,
    BOOTH_NAMES,
    DROP_DB,
    FRAME_S,
    MATCH_COSINE,
    NEAR_S,
    OPPORTUNITY_S,
    PAST_FLOOR_DB,
    PAST_S,
    SIGN_OFF,
    STOPPAGE,
    _age_at,
    arms_b,
    arms_c,
    arms_d,
    booth_cosine,
    coarse_onsets,
    covers_opportunity,
    fixed_delay_ceiling,
    match_times,
    normalize,
    other_speech_times,
)
from experiments.nfl75.diagnose import perfect_endings
from experiments.nfl75.inventory import active_intervals, coverage_by_session, excluded_ranges, wall_gaps
from experiments.nfl75.mean import ORDINARY_GAP_S, covers_from_mean, product_caps, rolling_means
from experiments.nfl75.persist import RETURN_PERSIST_S, _logits, nbc_lines
from experiments.nfl75.score import playback_from_covers, score_product
from hush.audio import analysis_pieces, find_session, load_session
from tools.gpu_lab.splits import HOLDOUTS

REPO = Path(__file__).resolve().parents[2]
MEAN = REPO / "docs" / "ohush" / "research" / "NFL75_MEAN_001" / "results.json"
CACHE = REPO / "docs" / "ohush" / "research" / "NFL75_PROTECT_001" / "cache"
PHRASES = REPO / "docs" / "ohush" / "research" / "FIRST_PRINCIPLES_BROADCAST_V2" / "EXP_03_HANDOFF_LANGUAGE" / "transcripts.jsonl"
OUT = REPO / "docs" / "ohush" / "research" / "NFL75_BROADCAST_OPPORTUNITY_001"
RECORDINGS = REPO / "recordings"
SESSIONS = ("hush_20261008_205100", "hush_20260924_220624")
RAW_SR = 48000
CLOSER = "post game show"
DELAYS = (0.0, 20.0, 25.0, 30.0, 40.0)
MODES = ("A", "D", "AD")
PHRASE_MODES = ("B", "C", "ABCD")


def _round(value, places: int):
    if value is None:
        return None
    return round(float(value), places)


def _clip_intervals(intervals: list[Interval], scope: tuple[float, float]) -> list[Interval]:
    start, end = scope
    clipped = []
    for row in intervals:
        left = max(row.start, start)
        right = min(row.end, end)
        if right - left <= 1e-6:
            continue
        clipped.append(Interval(left, right, row.event_class, row.desired_action, row.confidence))
    return clipped


def _scope_end(session: str, rows: list[dict]) -> float:
    hits = []
    for row in rows:
        if row.get("session") != session or row.get("role") != "start":
            continue
        if CLOSER in normalize(str(row.get("text") or "")):
            hits.append(float(row["boundary"]))
    if len(hits) != 1:
        raise RuntimeError(f"{session} has {len(hits)} postgame closers, expected one")
    return hits[0]


def _onsets(session: str, scope: tuple[float, float]) -> list[float]:
    path = OUT / "cache" / f"{session}_onsets.json"
    if path.is_file():
        saved = json.loads(path.read_text(encoding="utf-8"))
        if saved.get("drop_db") == DROP_DB and saved.get("past_s") == PAST_S:
            return [float(moment) for moment in saved["onsets"]]
    folder = find_session(RECORDINGS, session)
    meta = load_session(folder)
    frame = int(round(FRAME_S * RAW_SR))
    pending = np.zeros(0, dtype=np.float64)
    pending_origin = scope[0]
    history = np.zeros(0, dtype=np.float64)
    found: list[float] = []
    for piece in analysis_pieces(folder, meta, scope[0], scope[1]):
        audio, _sr = sf.read(
            str(piece["path"]),
            start=piece["read_start_frame"],
            stop=piece["read_stop_frame"],
            dtype="float32",
            always_2d=True,
        )
        mono = np.mean(audio, axis=1).astype(np.float64)
        if piece["pad_frames"]:
            mono = np.pad(mono, (0, int(piece["pad_frames"])))
        connected = pending.size and abs((pending_origin + len(pending) / RAW_SR) - piece["session_start_seconds"]) <= 0.02
        if pending.size and not connected:
            pending = np.zeros(0, dtype=np.float64)
            history = np.zeros(0, dtype=np.float64)
        origin = pending_origin if pending.size else float(piece["session_start_seconds"])
        stream = np.concatenate([pending, mono]) if pending.size else mono
        usable = (len(stream) // frame) * frame
        if usable:
            frames = stream[:usable].reshape(-1, frame)
            power = np.mean(frames * frames, axis=1)
            db = 10.0 * np.log10(np.maximum(power, 1e-12))
            series = np.concatenate([history, db]) if history.size else db
            series_origin = origin - len(history) * FRAME_S
            for moment in coarse_onsets(series, FRAME_S, series_origin):
                if moment >= origin - 1e-9:
                    found.append(moment)
            history = series[-int(round(PAST_S / FRAME_S)) :]
        pending = stream[usable:]
        pending_origin = origin + usable / RAW_SR
    found = sorted(moment for moment in found if scope[0] <= moment <= scope[1])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "session": session,
                "drop_db": DROP_DB,
                "past_s": PAST_S,
                "past_floor_db": PAST_FLOOR_DB,
                "frame_s": FRAME_S,
                "onsets": [round(moment, 3) for moment in found],
            }
        ),
        encoding="utf-8",
    )
    return found


def _summary(name: str, scored: dict, *, oracle: bool) -> dict:
    episodes = sorted(scored["episodes"], key=lambda row: -float(row["duration_s"]))
    return {
        "name": name,
        "oracle": oracle,
        "diagnostic_only": True,
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
        "program_hours": _round(scored["program_hours"], 4),
        "product_caps": product_caps(scored),
        "coverage_at_least_75": scored["commercial_coverage"] is not None and scored["commercial_coverage"] >= 0.75,
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
        "longest_episodes": [
            {
                "start_s": _round(row["start_s"], 3),
                "end_s": _round(row["end_s"], 3),
                "duration_s": _round(row["duration_s"], 3),
            }
            for row in episodes[:5]
        ],
    }


def _score(session, coverage, intervals, covers, *, oracle: bool) -> dict:
    playback = playback_from_covers(coverage, covers)
    if oracle:
        commercials = target_commercials(intervals)
        playback = playback_from_covers(coverage, perfect_endings(playback, commercials))
    return score_product(
        coverage,
        intervals,
        playback,
        session=session,
        oracle=oracle,
        audio_present=False,
        wall_gap_s=wall_gaps().get(session, 0.0),
        excluded_ranges=excluded_ranges(session, intervals),
    )


def _inside(moment: float, spans: list[tuple[float, float]]) -> bool:
    return any(start <= moment < end for start, end in spans)


def _nearest_break(moment: float, commercials: list[tuple[float, float]]) -> float:
    if not commercials:
        return 1e9
    return min(min(abs(moment - start), abs(moment - end)) for start, end in commercials)


def _edges(times, flags, commercials) -> dict:
    ordinary = []
    boundary = []
    for index, flag in enumerate(flags):
        if not flag or (index and flags[index - 1]):
            continue
        moment = float(times[index])
        if _inside(moment, commercials):
            continue
        distance = _nearest_break(moment, commercials)
        if distance > ORDINARY_GAP_S:
            ordinary.append(round(moment, 3))
        else:
            boundary.append(round(moment, 3))
    return {"ordinary": ordinary, "boundary": boundary}


def _seconds(times, mask, spans) -> float:
    total = 0.0
    for index, moment in enumerate(times):
        if mask[index] and _inside(float(moment), spans):
            total += 1.0
    return total


def _break_timeline(start, end, times, means, flags, match_ends, onsets, line) -> dict:
    age = _age_at(match_ends, start)
    first_eligible = None
    first_hot = None
    for moment, mean, flag in zip(times, means, flags):
        moment = float(moment)
        if moment < start - 60.0 or moment > end + 30.0:
            continue
        if first_hot is None and moment >= start and mean is not None and mean >= line:
            first_hot = moment
        if first_eligible is None and start - 1e-9 <= moment < end and flag:
            first_eligible = moment
    if first_eligible is None:
        reason = "no opportunity while the break is open"
        coverable = 0.0
    else:
        reason = ""
        coverable = max(0.0, end - first_eligible)
    nearby = [round(moment, 3) for moment in onsets if start - 60.0 <= moment <= start + 30.0]
    return {
        "start_s": round(start, 3),
        "end_s": round(end, 3),
        "duration_s": round(end - start, 3),
        "booth_age_at_start_s": None if age is None else round(age, 3),
        "last_booth_s": None if age is None else round(start - age, 3),
        "acoustic_onsets_s": nearby[:8],
        "acoustic_count": len(nearby),
        "mean_hot_s": None if first_hot is None else round(first_hot, 3),
        "eligible_s": None if first_eligible is None else round(first_eligible, 3),
        "coverable_after_eligibility_s": round(coverable, 3),
        "first_30s_has_opportunity": first_eligible is not None and first_eligible <= start + 30.0 + 1e-9,
        "miss_reason": reason,
    }


def _phrases(session: str) -> tuple[list[float], list[float]]:
    path = OUT / "asr_phrases.json"
    if not path.is_file():
        return [], []
    rows = json.loads(path.read_text(encoding="utf-8"))
    signoffs = []
    stoppages = []
    for row in rows:
        if row.get("session") != session:
            continue
        moment = float(row["available_t"])
        if row.get("kind") == "signoff":
            signoffs.append(moment)
        elif row.get("kind") == "stoppage":
            stoppages.append(moment)
    return sorted(signoffs), sorted(stoppages)


def _jobs(session, scope, commercials, ordinary_edges, transcripts) -> list[dict]:
    jobs = []
    for start, end in commercials:
        if end < scope[0] or start > scope[1]:
            continue
        cursor = start - 60.0
        while cursor + 5.0 <= start + 1e-6:
            jobs.append({"role": "lead", "t0": round(cursor, 3), "t1": round(cursor + 5.0, 3), "boundary": round(start, 3)})
            cursor += 5.0
        cursor = start
        while cursor + 5.0 <= start + 10.0 + 1e-6:
            jobs.append({"role": "after", "t0": round(cursor, 3), "t1": round(cursor + 5.0, 3), "boundary": round(start, 3)})
            cursor += 5.0
    for row in transcripts:
        if row.get("session") != session or row.get("role") != "control":
            continue
        t0 = float(row["t0"])
        t1 = float(row["t1"])
        if t0 < scope[0] or t1 > scope[1]:
            continue
        cursor = t0
        while cursor + 5.0 <= t1 + 1e-6:
            jobs.append({"role": "control", "t0": round(cursor, 3), "t1": round(cursor + 5.0, 3), "boundary": row.get("boundary")})
            cursor += 5.0
    for moment in ordinary_edges[:30]:
        jobs.append({"role": "false_arm", "t0": round(moment - 5.0, 3), "t1": round(moment, 3), "boundary": None})
    return jobs


def _clears(row: dict) -> bool:
    return bool(row["product_caps"] and row["coverage_at_least_75"])


def main() -> None:
    if any(session in HOLDOUTS for session in SESSIONS):
        raise SystemExit("refusing a sealed holdout")
    frozen = json.loads(MEAN.read_text(encoding="utf-8"))["frozen"]
    window = int(frozen["window_s"])
    line = float(frozen["start_line"])
    if window != 10:
        raise SystemExit(f"frozen window is {window}, expected 10")
    transcripts = [json.loads(line_text) for line_text in PHRASES.read_text(encoding="utf-8").splitlines() if line_text.strip()]
    lines = nbc_lines()
    head = lines["head"]
    sessions = []
    asr_jobs = []
    phrase_file = (OUT / "asr_phrases.json").is_file()
    for session in SESSIONS:
        if session in HOLDOUTS:
            raise SystemExit(session)
        coverage = coverage_by_session()[session]
        scope = (coverage[0], _scope_end(session, transcripts))
        intervals = active_intervals(session)
        scoped_intervals = _clip_intervals(intervals, scope)
        commercials = target_commercials(scoped_intervals)
        program = program_regions(scope, scoped_intervals)
        times, scores, _labels = _logits(head, session)
        times = [float(moment) for moment in times]
        scores = [float(score) for score in scores]
        means = rolling_means(times, scores, window)
        bundle = np.load(CACHE / f"{session}.npz")
        receipt = json.loads((CACHE / f"{session}.json").read_text(encoding="utf-8"))
        booth = booth_cosine(bundle["people"], receipt["names"])
        ends = [float(moment) for moment in bundle["end"].tolist()]
        matches = match_times(ends, booth.tolist())
        others = other_speech_times(ends, booth.tolist())
        print(f"{session} acoustic", flush=True)
        onsets = _onsets(session, coverage)
        scoped_onsets = [moment for moment in onsets if scope[0] <= moment <= scope[1]]
        signoffs, stoppages = _phrases(session)
        d_arms = arms_d(scoped_onsets, others, matches)
        b_arms = arms_b(signoffs, scoped_onsets)
        c_arms = arms_c(stoppages, d_arms, matches)
        keep = [index for index, moment in enumerate(times) if scope[0] - 1e-9 <= moment < scope[1] - 1e-9]
        scoped_times = [times[index] for index in keep]
        scoped_scores = [scores[index] for index in keep]
        scoped_means = [means[index] for index in keep]
        unprotected = covers_from_mean(
            scoped_times,
            scoped_scores,
            window=window,
            start_line=line,
            return_persist_s=RETURN_PERSIST_S,
        )
        modes = list(MODES)
        if phrase_file:
            modes.extend(PHRASE_MODES)
        policies = {}
        flags_a = None
        for mode in modes:
            covers, flags = covers_opportunity(
                scoped_times,
                scoped_scores,
                scoped_means,
                matches,
                mode=mode,
                d_arms=d_arms,
                b_arms=b_arms,
                c_arms=c_arms,
                start_line=line,
            )
            if mode == "A":
                flags_a = flags
            for oracle in (False, True):
                scored = _score(session, scope, scoped_intervals, covers, oracle=oracle)
                policies[f"{mode}_{'oracle' if oracle else 'causal'}"] = _summary(
                    mode, scored, oracle=oracle
                )
        full = _score(
            session,
            coverage,
            intervals,
            covers_from_mean(times, scores, window=window, start_line=line, return_persist_s=RETURN_PERSIST_S),
            oracle=False,
        )
        ages = [_age_at(matches, moment) for moment in scoped_times]
        absent = [age is not None and age >= ABSENCE_S for age in ages]
        booth_now = [age is not None and age <= 1.0 + 1e-9 for age in ages]
        unknown = [age is None for age in ages]
        edges = _edges(scoped_times, flags_a, commercials)
        timelines = [
            _break_timeline(start, end, scoped_times, scoped_means, flags_a, matches, scoped_onsets, line)
            for start, end in commercials
        ]
        durations = [end - start for start, end in commercials]
        full_commercials = target_commercials(intervals)
        full_durations = [end - start for start, end in full_commercials]
        windows = booth
        finite_windows = int(np.isfinite(windows).sum())
        matched_windows = int(np.nansum(windows >= MATCH_COSINE))
        asr_jobs.append({"session": session, "jobs": _jobs(session, scope, commercials, edges["ordinary"], transcripts)})
        sessions.append(
            {
                "session": session,
                "scope": {
                    "start_s": scope[0],
                    "end_s": round(scope[1], 3),
                    "rule": "coverage start through the EXP-03 postgame-show closer; that closer and everything after it are out of scope",
                    "pregame_labeled": False,
                    "halftime_included": True,
                },
                "denominators": {
                    "full_tape_commercial_s": _round(full["commercial_s"], 3),
                    "full_tape_program_s": _round(full["program_s"], 3),
                    "full_tape_causal_coverage": _round(full["commercial_coverage"], 4),
                    "full_tape_causal_episodes_per_hour": _round(full["false_mutes_per_hour"], 3),
                    "scoped_commercial_s": _round(sum(durations), 3),
                    "scoped_program_s": _round(sum(end - start for start, end in program), 3),
                    "breaks_full": len(full_durations),
                    "breaks_scoped": len(durations),
                },
                "delay_ceiling_scoped": [fixed_delay_ceiling(durations, delay) for delay in DELAYS],
                "delay_ceiling_full_tape": [fixed_delay_ceiling(full_durations, delay) for delay in DELAYS],
                "absence": {
                    "program_seconds_without_booth_for_30s": _seconds(scoped_times, absent, program),
                    "commercial_seconds_without_booth_for_30s": _seconds(scoped_times, absent, commercials),
                    "commercial_seconds_with_booth_in_the_last_1s": _seconds(scoped_times, booth_now, commercials),
                    "commercial_seconds_with_booth_in_the_last_30s": _seconds(
                        scoped_times,
                        [age is not None and age < ABSENCE_S for age in ages],
                        commercials,
                    ),
                    "program_seconds_before_any_booth_match": _seconds(scoped_times, unknown, program),
                    "ordinary_absence_edges": len(edges["ordinary"]),
                    "boundary_absence_edges": len(edges["boundary"]),
                },
                "speaker": {
                    "booth": list(BOOTH_NAMES),
                    "names": receipt["names"],
                    "windows": int(len(ends)),
                    "finite_booth_windows": finite_windows,
                    "booth_match_windows": matched_windows,
                    "other_speech_windows": len(others),
                    "match_line": MATCH_COSINE,
                    "enrollment": receipt.get(
                        "enrollment",
                        "prior-game clips are available from the start; a same-game clip starts at its own end",
                    ),
                    "note": "A finite cosine below 0.25 is speech that is not the booth. A missing cosine is unknown, not absence.",
                },
                "acoustic": {
                    "onsets": len(scoped_onsets),
                    "drop_db": DROP_DB,
                    "past_s": PAST_S,
                    "past_floor_db": PAST_FLOOR_DB,
                    "d_arms": len(d_arms),
                },
                "phrases": {
                    "file_present": phrase_file,
                    "signoff_times": [round(moment, 3) for moment in signoffs],
                    "stoppage_times": [round(moment, 3) for moment in stoppages],
                    "b_arms": len(b_arms),
                    "c_arms": len(c_arms),
                    "signoff_list": list(SIGN_OFF),
                    "stoppage_list": list(STOPPAGE),
                    "near_s": NEAR_S,
                    "opportunity_s": OPPORTUNITY_S,
                },
                "timelines_rule_a": timelines,
                "breaks_with_opportunity_in_first_30s": sum(1 for row in timelines if row["first_30s_has_opportunity"]),
                "breaks_with_no_opportunity": sum(1 for row in timelines if row["eligible_s"] is None),
                "coverable_s_rule_a": round(sum(row["coverable_after_eligibility_s"] for row in timelines), 3),
                "policies": policies,
                "unprotected_scoped_causal": _summary(
                    "unprotected",
                    _score(session, scope, scoped_intervals, unprotected, oracle=False),
                    oracle=False,
                ),
                "unprotected_scoped_oracle": _summary(
                    "unprotected",
                    _score(session, scope, scoped_intervals, unprotected, oracle=True),
                    oracle=True,
                ),
                "ordinary_absence_edges_sample": edges["ordinary"][:12],
            }
        )
        causal = policies["A_causal"]
        print(
            session,
            "scope",
            round(scope[1], 1),
            "A coverage",
            causal["commercial_coverage"],
            "eph",
            causal["false_mutes_per_hour"],
            "D arms",
            len(d_arms),
            flush=True,
        )
    kept = []
    for mode in list(MODES) + (list(PHRASE_MODES) if phrase_file else []):
        rows = []
        for session in sessions:
            for kind in ("oracle", "causal"):
                rows.append(session["policies"][f"{mode}_{kind}"])
        if all(_clears(row) for row in rows):
            kept.append(mode)
    payload = {
        "experiment": "NFL75_BROADCAST_OPPORTUNITY_001",
        "deployable": False,
        "automatic_mute": False,
        "hardneg_paused": True,
        "frozen_start": {"window_s": window, "start_line": line, "source": "NFL75_MEAN_001"},
        "fingerprint": {
            "used": False,
            "why": "The NFL75 fingerprint reader failed prefix invariance. Known-ad matches stay a later conditional check, not a confirmer in this replay.",
        },
        "verdict": "KEEP" if kept else "REJECT",
        "kept_modes": kept,
        "sessions": sessions,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (OUT / "asr_jobs.json").write_text(json.dumps(asr_jobs), encoding="utf-8")
    print("wrote", OUT / "results.json", "verdict", payload["verdict"])


if __name__ == "__main__":
    main()
