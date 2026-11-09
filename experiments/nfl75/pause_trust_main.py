"""Causal replay of a pause after a 0.25 match.

    python -m experiments.nfl75.pause_trust_main

The 10-second mean and the cosine stay frozen. Entry candidates do not
release a cover. Release candidates do not add a second rule on top of the
gap that closes the cover. Oracle endings are not used. The live 0.55 booth
is not used. Nothing here is deployed.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from experiments.measurement.metrics import program_regions, target_commercials
from experiments.nfl75.inventory import active_intervals, coverage_by_session, excluded_ranges, wall_gaps
from experiments.nfl75.mean import PRIME_SESSIONS
from experiments.nfl75.pause_trust import (
    COVERAGE_SLACK,
    GAPS,
    commercial_given_back,
    onset_ranges,
    overlap_seconds,
    pause_covers,
    seconds,
)
from experiments.nfl75.persist import _logits, nbc_lines
from experiments.nfl75.promo_class import load_overlay, spans_for
from experiments.nfl75.protect import unprotected_covers
from experiments.nfl75.score import _with_exclusions, playback_from_covers, score_product
from tools.gpu_lab.splits import HOLDOUTS

REPO = Path(__file__).resolve().parents[2]
RESEARCH = REPO / "docs" / "ohush" / "research"
MEAN = RESEARCH / "NFL75_MEAN_001" / "results.json"
BOOTH = RESEARCH / "NFL75_BOOTH_HOLD_001" / "results.json"
CACHE = RESEARCH / "NFL75_PROTECT_001" / "cache"
OUT = RESEARCH / "OHUSH_PAUSE_TRUST_001"
_EPS = 1e-6


def _round(value, places: int):
    if value is None:
        return None
    return round(float(value), places)


def _labels(session: str):
    coverage = coverage_by_session()[session]
    intervals = active_intervals(session)
    combined = _with_exclusions(intervals, excluded_ranges(session, intervals))
    return coverage, intervals, target_commercials(intervals), program_regions(coverage, combined)


def _specs() -> list[tuple[str, str, float, str]]:
    rows = [("unprotected", "none", 0.0, "none")]
    for gap in GAPS:
        label = str(int(gap))
        rows.append((f"entry_{label}", "entry", gap, "always"))
        rows.append((f"entry_{label}_cold", "entry", gap, "while_mean_cold"))
        rows.append((f"release_{label}", "release", gap, "always"))
    rows.append(("mixed_1", "mixed", 1.0, "always"))
    rows.append(("mixed_5", "mixed", 5.0, "always"))
    return rows


def _near(breaks: list[dict], moment: float) -> dict:
    found = min(breaks, key=lambda row: abs(float(row["start_s"]) - moment))
    if abs(float(found["start_s"]) - moment) > 2.0:
        raise RuntimeError(f"no break near {moment}")
    return found


def _cases(session: str, breaks: list[dict]) -> list[dict]:
    if session == "hush_20261008_205100":
        opening = _near(breaks, 1003.0)
        return [
            {"name": "dropped_pass", "start_s": 9156.0, "end_s": 9169.0, "kind": "program"},
            {
                "name": "commercial_start",
                "start_s": float(opening["start_s"]),
                "end_s": float(opening["end_s"]),
                "kind": "break",
                "trace_end_s": float(opening["start_s"]) + 40.0,
            },
            {"name": "amex", "start_s": 3391.0, "end_s": 3447.0, "kind": "promo"},
        ]
    if session == "hush_20260924_220624":
        tail = _near(breaks, 6854.0)
        return [
            {"name": "injury_desk", "start_s": 6266.0, "end_s": 6292.0, "kind": "program"},
            {
                "name": "late_return",
                "start_s": float(tail["start_s"]),
                "end_s": float(tail["end_s"]),
                "kind": "break",
                "trace_end_s": float(tail["end_s"]) + 100.0,
            },
            {"name": "chilis", "start_s": 2978.0, "end_s": 3014.0, "kind": "promo"},
        ]
    raise RuntimeError(session)


def _trace_bounds(case: dict) -> tuple[float, float]:
    start = float(case["start_s"]) - 20.0
    if "trace_end_s" in case:
        return start, float(case["trace_end_s"])
    return start, float(case["end_s"]) + 20.0


def _gold(commercials: list[tuple[float, float]], moment: float) -> str:
    for start, end in commercials:
        if start <= moment < end:
            return "commercial"
    return "program"


def _who(people: np.ndarray, names: list[str], index: int | None) -> str | None:
    if index is None:
        return None
    row = np.asarray(people[index], dtype=np.float64)
    if not np.isfinite(row).any():
        return None
    return names[int(np.nanargmax(row))]


def _score_breaks(scored: dict) -> list[dict]:
    rows = []
    for row in scored["breaks"]:
        delay = row["start_delay_s"]
        rows.append(
            {
                "break": row["break"],
                "start_s": _round(row["start_s"], 3),
                "end_s": _round(row["end_s"], 3),
                "start_delay_s": None if delay is None else _round(delay, 3),
                "covered_s": _round(row["covered_s"], 3),
                "late_return_s": _round(row["late_return_s"], 3),
                "missed_break": row["missed_break"],
            }
        )
    return rows


def _metrics(
    scored: dict,
    covers: list[tuple[float, float]],
    holds: list[tuple[float, float]],
    promo: list[tuple[float, float]],
    commercials: list[tuple[float, float]],
    baseline: list[tuple[float, float]] | None,
) -> dict:
    promo_muted = overlap_seconds(covers, promo)
    lost = [] if baseline is None else commercial_given_back(baseline, covers, commercials)
    gained = [] if baseline is None else commercial_given_back(covers, baseline, commercials)
    onset = overlap_seconds(lost, onset_ranges(commercials))
    delays = [
        float(row["start_delay_s"])
        for row in scored["breaks"]
        if row["start_delay_s"] is not None and float(row["start_delay_s"]) > 1.0
    ]
    late = [float(row["late_return_s"]) for row in scored["breaks"] if float(row["late_return_s"]) > 1.0]
    heard = float(scored["commercial_s"]) - float(scored["commercial_covered_s"])
    return {
        "commercial_coverage": _round(scored["commercial_coverage"], 4),
        "commercial_covered_s": _round(scored["commercial_covered_s"], 3),
        "commercial_heard_s": _round(heard, 3),
        "commercial_s": _round(scored["commercial_s"], 3),
        "genuine_program_muted_s": _round(float(scored["program_covered_s"]) - promo_muted, 3),
        "promotional_read_muted_s": _round(promo_muted, 3),
        "program_covered_s": _round(scored["program_covered_s"], 3),
        "false_mute_episodes": scored["false_mute_episodes"],
        "cover_intervals": len(covers),
        "missed_breaks": sum(1 for row in scored["breaks"] if row["missed_break"]),
        "late_starts": len(delays),
        "late_start_s": _round(sum(delays), 3),
        "late_returns": len(late),
        "late_return_s": _round(sum(late), 3),
        "commercial_given_back_s": _round(seconds(lost), 3),
        "commercial_newly_muted_s": _round(seconds(gained), 3),
        "commercial_lost_to_speaker_s": _round(seconds(lost), 3),
        "commercial_lost_at_onset_10s": _round(onset, 3),
        "commercial_lost_inside_break_s": _round(seconds(lost) - onset, 3),
        "speaker_hold_inside_lost_ads_s": _round(overlap_seconds(holds, lost), 3),
        "breaks": _score_breaks(scored),
        "lost_breaks": [
            {
                "start_s": _round(start, 3),
                "end_s": _round(end, 3),
                "lost_s": _round(end - start, 3),
            }
            for start, end in lost
            if end - start > 0.25
        ],
        "gained_breaks": [
            {
                "start_s": _round(start, 3),
                "end_s": _round(end, 3),
                "gained_s": _round(end - start, 3),
            }
            for start, end in gained
            if end - start > 0.25
        ],
    }


def _check_published(session: str, measured: dict, published: dict) -> None:
    expect = {
        "unprotected": published["unprotected"]["actual"],
        "mixed_1": published["hold_1"]["actual"],
        "mixed_5": published["hold_5"]["actual"],
    }
    for name, row in expect.items():
        got = measured[name]
        if got["false_mute_episodes"] != row["false_mute_episodes"]:
            raise RuntimeError(f"{session} {name} episodes {got['false_mute_episodes']} != {row['false_mute_episodes']}")
        if abs(got["commercial_coverage"] - row["commercial_coverage"]) > 0.00015:
            raise RuntimeError(f"{session} {name} coverage {got['commercial_coverage']} != {row['commercial_coverage']}")
        if abs(got["commercial_covered_s"] - row["commercial_covered_s"]) > 0.05:
            raise RuntimeError(f"{session} {name} covered seconds drifted")
        if abs(got["program_covered_s"] - row["program_covered_s"]) > 0.05:
            raise RuntimeError(f"{session} {name} program seconds drifted")
    release = measured["release_1"]
    mixed = measured["mixed_1"]
    if release["false_mute_episodes"] != mixed["false_mute_episodes"]:
        raise RuntimeError(f"{session} release_1 and mixed_1 diverged")
    if abs(release["commercial_covered_s"] - mixed["commercial_covered_s"]) > 0.05:
        raise RuntimeError(f"{session} release_1 and the published one-second hold diverged")
    if abs(measured["release_5"]["commercial_covered_s"] - measured["mixed_5"]["commercial_covered_s"]) > 0.05:
        raise RuntimeError(f"{session} release_5 and the blind five-second hold diverged")


def _snippet(trace: list[dict], people, names, start: float, end: float) -> list[dict]:
    rows = []
    for row in trace:
        if row["t"] < start - _EPS or row["t"] > end + _EPS:
            continue
        if row["reason"] not in ("opened_on_mean", "speaker_hold", "released_on_match", "returned_on_score"):
            if rows and rows[-1]["reason"] == row["reason"] and row["t"] - rows[-1]["t"] < 4.0:
                continue
        rows.append(
            {
                "t": _round(row["t"], 3),
                "gold_retrospective": row["gold"],
                "score": _round(row["score"], 3),
                "mean": _round(row["mean"], 3),
                "match_cosine": _round(row["match_cosine"], 4),
                "match_age_s": _round(row["match_age_s"], 3),
                "who": _who(people, names, row["match_index"]),
                "protected": row["protected"],
                "state": row["state"],
                "reason": row["reason"],
            }
        )
    return rows[:24]


def _run_session(head, session: str, window: int, line: float, overlay: dict) -> tuple[dict, list[dict]]:
    if session in HOLDOUTS or session not in PRIME_SESSIONS:
        raise RuntimeError(f"refusing {session}")
    path = CACHE / f"{session}.npz"
    bundle = np.load(path)
    receipt = json.loads((CACHE / f"{session}.json").read_text(encoding="utf-8"))
    names = list(receipt["names"])
    people = np.asarray(bundle["people"], dtype=np.float64)
    ends = [float(value) for value in bundle["end"].tolist()]
    cosines = [float(value) for value in bundle["cosine"].tolist()]
    times, scores, _ignored = _logits(head, session)
    clock = [float(moment) for moment in times]
    values = [float(score) for score in scores]
    coverage, intervals, commercials, _program = _labels(session)
    promo = spans_for(overlay, session, "consumer")
    cases = _cases(session, [{"start_s": start, "end_s": end} for start, end in commercials])
    candidates = {}
    traces: dict[str, list[dict]] = {}
    baseline = None
    for name, effect, gap, refresh in _specs():
        trace: list[dict] = []
        if effect == "none":
            covers = unprotected_covers(clock, values, window=window, start_line=line)
            holds = []
            pause_covers(
                clock,
                values,
                [],
                [],
                window=window,
                start_line=line,
                gap_s=0.0,
                effect="entry",
                trace=trace,
            )
        else:
            covers, holds = pause_covers(
                clock,
                values,
                ends,
                cosines,
                window=window,
                start_line=line,
                gap_s=gap,
                effect=effect,
                refresh=refresh,
                trace=trace,
            )
        if name == "unprotected":
            baseline = covers
        playback = playback_from_covers(coverage, covers)
        scored = score_product(
            coverage,
            intervals,
            playback,
            session=session,
            oracle=False,
            audio_present=True,
            wall_gap_s=wall_gaps().get(session, 0.0),
            excluded_ranges=excluded_ranges(session, intervals),
        )
        candidates[name] = _metrics(scored, covers, holds, promo, commercials, None if name == "unprotected" else baseline)
        candidates[name]["effect"] = effect
        candidates[name]["gap_s"] = gap
        candidates[name]["refresh"] = refresh
        candidates[name]["family"] = "baseline" if name == "unprotected" or name.startswith("mixed_") else effect
        for row in trace:
            row["gold"] = _gold(commercials, float(row["t"]))
        traces[name] = trace
        case_rows = {}
        for case in cases:
            muted = overlap_seconds(covers, [(case["start_s"], case["end_s"])])
            entry = {"muted_s": _round(muted, 3)}
            if case["kind"] == "break":
                found = _near(candidates[name]["breaks"], case["start_s"])
                entry["start_delay_s"] = found["start_delay_s"]
                entry["late_return_s"] = found["late_return_s"]
                entry["covered_s"] = found["covered_s"]
                entry["missed_break"] = found["missed_break"]
            case_rows[case["name"]] = entry
        candidates[name]["cases"] = case_rows
    lands = 0
    matches = 0
    cursor = 0
    for end, cosine in zip(ends, cosines):
        if cosine + _EPS < 0.25:
            continue
        matches += 1
        while cursor < len(clock) and clock[cursor] + _EPS < end:
            cursor += 1
        if cursor < len(clock) and abs(clock[cursor] - end) <= 0.05:
            lands += 1
    payload = {
        "session": session,
        "enrollment_names": names,
        "speaker_windows": len(ends),
        "matches_at_or_above_0.25": matches,
        "matches_landing_on_a_decision": lands,
        "cases": [
            {
                "name": case["name"],
                "start_s": case["start_s"],
                "end_s": case["end_s"],
                "kind": case["kind"],
            }
            for case in cases
        ],
        "candidates": candidates,
    }
    lines = []
    quoted = ("unprotected", "entry_5", "entry_5_cold", "release_5", "mixed_1", "mixed_5")
    for case in cases:
        begin, finish = _trace_bounds(case)
        for name in traces:
            for row in traces[name]:
                moment = float(row["t"])
                if moment < begin - _EPS or moment > finish + _EPS:
                    continue
                lines.append(
                    {
                        "session": session,
                        "case": case["name"],
                        "candidate": name,
                        "t": _round(moment, 3),
                        "gold_retrospective": row["gold"],
                        "score": _round(row["score"], 4),
                        "mean": _round(row["mean"], 4),
                        "match_cosine": _round(row["match_cosine"], 4),
                        "match_age_s": _round(row["match_age_s"], 3),
                        "match_end_s": _round(row["match_end_s"], 3),
                        "who": _who(people, names, row["match_index"]),
                        "protected": row["protected"],
                        "state": row["state"],
                        "reason": row["reason"],
                    }
                )
        if "unprotected" in traces:
            payload_cases = payload.setdefault("snippets", {})
            payload_cases[case["name"]] = {
                name: _snippet(traces[name], people, names, begin, finish) for name in quoted if name in traces
            }
    return payload, lines


def _gate(sessions: list[dict]) -> dict:
    eligible = []
    frontier = []
    for name, effect, _gap, _refresh in _specs():
        if effect != "entry":
            continue
        per_tape = []
        ok = True
        combined_drop = 0.0
        for session in sessions:
            base = session["candidates"]["unprotected"]
            row = session["candidates"][name]
            coverage_drop = float(base["commercial_coverage"]) - float(row["commercial_coverage"])
            genuine_drop = float(base["genuine_program_muted_s"]) - float(row["genuine_program_muted_s"])
            combined_drop += genuine_drop
            per_tape.append(
                {
                    "session": session["session"],
                    "coverage": row["commercial_coverage"],
                    "coverage_drop": _round(coverage_drop, 4),
                    "genuine_drop_s": _round(genuine_drop, 3),
                    "within_half_point": coverage_drop <= COVERAGE_SLACK + 1e-9,
                }
            )
            if coverage_drop > COVERAGE_SLACK + 1e-9 or genuine_drop <= 0.5:
                ok = False
        record = {"candidate": name, "combined_genuine_drop_s": _round(combined_drop, 3), "tapes": per_tape}
        frontier.append(record)
        if ok:
            eligible.append(record)
    frontier.sort(key=lambda row: (-row["combined_genuine_drop_s"], row["candidate"]))
    eligible.sort(key=lambda row: (-row["combined_genuine_drop_s"], row["candidate"]))
    winner = eligible[0]["candidate"] if eligible else None
    return {
        "coverage_slack": COVERAGE_SLACK,
        "clock": "causal",
        "eligible_family": "entry",
        "rule": (
            "An entry candidate passes when each tape stays within 0.5 percentage points "
            "of its own unprotected causal coverage and genuine programming muted falls on each tape. "
            "Release and mixed candidates are reported and cannot win this gate."
        ),
        "passes": [row["candidate"] for row in eligible],
        "winner": winner,
        "frontier": frontier,
    }


def main() -> None:
    frozen = json.loads(MEAN.read_text(encoding="utf-8"))["frozen"]
    window = int(frozen["window_s"])
    line = float(frozen["start_line"])
    if window != 10 or abs(line - 0.1632588496059179) > 0:
        raise RuntimeError("refusing a mean other than the frozen 10-second line")
    head = nbc_lines()["head"]
    overlay = load_overlay()
    booth = json.loads(BOOTH.read_text(encoding="utf-8"))
    published = {row["session"]: row["policies"] for row in booth["sessions"]}
    sessions = []
    trace_rows: list[dict] = []
    for session in PRIME_SESSIONS:
        payload, lines = _run_session(head, session, window, line, overlay)
        _check_published(session, payload["candidates"], published[session])
        sessions.append(payload)
        trace_rows.extend(lines)
        base = payload["candidates"]["unprotected"]
        print(session, "baseline", base["commercial_coverage"], "genuine", base["genuine_program_muted_s"])
        for name, _effect, _gap, _refresh in _specs():
            row = payload["candidates"][name]
            print(
                f"  {name:16} cov {row['commercial_coverage']:.4f} "
                f"genuine {row['genuine_program_muted_s']:.1f} "
                f"heard {row['commercial_heard_s']:.1f} "
                f"back {row['commercial_given_back_s']:.1f} "
                f"newmute {row['commercial_newly_muted_s']:.1f} "
                f"onset {row['commercial_lost_at_onset_10s']:.1f} "
                f"inside {row['commercial_lost_inside_break_s']:.1f} "
                f"late {row['late_return_s']:.1f} "
                f"ep {row['false_mute_episodes']} "
                f"miss {row['missed_breaks']} delay {row['late_start_s']:.1f}"
            )
    gate = _gate(sessions)
    OUT.mkdir(parents=True, exist_ok=True)
    document = {
        "experiment": "OHUSH_PAUSE_TRUST_001",
        "verdict": "GATE_MET" if gate["winner"] else "FRONTIER",
        "deployable": False,
        "television_changed": False,
        "thresholds_changed": False,
        "oracle_endings_used": False,
        "live_booth_used": False,
        "frozen": {
            "window_s": window,
            "start_line": line,
            "match_cosine": 0.25,
            "return_line": 0.0,
            "return_persist_s": 3.0,
            "source": "NFL75_MEAN_001",
        },
        "families": {
            "entry": "a match blocks a new mute for the gap and does not release a mute already open",
            "entry_cold": "the entry timer refreshes only while the 10-second mean is below 0.163",
            "release": "a match closes a mute already open and keeps it closed until that same gap ends",
            "mixed": "published hold: blocks the open and releases the cover. Baselines only.",
        },
        "gate": gate,
        "sessions": sessions,
    }
    (OUT / "results.json").write_text(json.dumps(document, indent=2), encoding="utf-8")
    with (OUT / "traces.jsonl").open("w", encoding="utf-8") as handle:
        for row in trace_rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    print("verdict", document["verdict"], "winner", gate["winner"])
    print("wrote", OUT)


if __name__ == "__main__":
    main()
