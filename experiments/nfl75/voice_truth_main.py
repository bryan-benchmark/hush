"""Causal entry guard for three names. Labels stay empty. Nothing is deployed.

    py -3.13 -m experiments.nfl75.voice_truth_main

The guard blocks a new mute for one second after a finished Michaels,
Herbstreit, or Thompson window whose runner-up is at least 0.15 behind.
It does not release a mute. Path B waits for the blind labels.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from experiments.nfl75.inventory import excluded_ranges, wall_gaps
from experiments.nfl75.mean import PRIME_SESSIONS
from experiments.nfl75.pause_trust import commercial_given_back
from experiments.nfl75.pause_trust_main import _labels, _metrics
from experiments.nfl75.persist import _logits, nbc_lines
from experiments.nfl75.promo_class import load_overlay
from experiments.nfl75.protect import unprotected_covers
from experiments.nfl75.score import playback_from_covers, score_product
from experiments.nfl75.voice_truth import candidate_rows, entry_guard_covers, qualify
from tools.gpu_lab.splits import HOLDOUTS

REPO = Path(__file__).resolve().parents[2]
RESEARCH = REPO / "docs" / "ohush" / "research"
QUEUE = RESEARCH / "OHUSH_VOICE_FN_ATOMIC_001" / "queue.jsonl"
CACHE = RESEARCH / "NFL75_PROTECT_001" / "cache"
MEAN = RESEARCH / "NFL75_MEAN_001" / "results.json"
BOOTH = RESEARCH / "NFL75_BOOTH_HOLD_001" / "results.json"
OUT = RESEARCH / "OHUSH_VOICE_TRUTH_002"
FAILURES = (
    "fn0001",
    "fn0006",
    "fn0008",
    "fn0009",
    "fn0010",
    "fn0011",
    "fn0025",
    "fn0054",
    "fn0007",
    "fn0023",
)


def _queue() -> list[dict]:
    return [json.loads(line) for line in QUEUE.read_text(encoding="utf-8").splitlines() if line.strip()]


def _commercial_rows(rows: list[dict]) -> list[dict]:
    chosen = []
    for row in rows:
        number = int(row["id"][2:])
        if row.get("kind") == "commercial_match" and row.get("split") == "dev" and 101 <= number <= 119:
            chosen.append(row)
    return chosen


def _blind(rows: list[dict]) -> list[dict]:
    failures = {row["id"]: row for row in rows}
    ordered = []
    for clip_id in FAILURES:
        row = failures.get(clip_id)
        if row is None or row.get("split") != "dev":
            raise RuntimeError(f"{clip_id} is not a development clip")
        ordered.append(row)
    ordered.extend(_commercial_rows(rows))
    blind = []
    for row in ordered:
        if row.get("split") == "eval":
            raise RuntimeError(f"refusing to open sealed {row['id']}")
        blind.append(
            {
                "id": row["id"],
                "session": row["session"],
                "wav": row["wav"],
                "clip_start_s": row["clip_start_s"],
                "clip_end_s": row["clip_end_s"],
            }
        )
    return blind


def _guard_ends(session: str) -> tuple[list[str], list[float], list[dict]]:
    receipt = json.loads((CACHE / f"{session}.json").read_text(encoding="utf-8"))
    names = list(receipt["names"])
    bundle = np.load(CACHE / f"{session}.npz")
    ends = np.asarray(bundle["end"], dtype=np.float64)
    people = np.asarray(bundle["people"], dtype=np.float64)
    qualify_ends = []
    passed = []
    for index, end in enumerate(ends):
        scores = {}
        for slot, name in enumerate(names):
            value = float(people[index, slot])
            if value == value:
                scores[name] = value
        found = qualify(scores)
        if found is None:
            continue
        qualify_ends.append(float(end))
        passed.append({"end_s": round(float(end), 3), **{key: round(found[key], 4) if key != "name" else found[key] for key in found}})
    return names, qualify_ends, passed


def _run(head, session: str, window: int, line: float, overlay) -> dict:
    if session in HOLDOUTS or session not in PRIME_SESSIONS:
        raise RuntimeError(f"refusing {session}")
    _names, qualify_ends, _passed = _guard_ends(session)
    times, scores, _ignored = _logits(head, session)
    clock = [float(moment) for moment in times]
    values = [float(score) for score in scores]
    coverage, intervals, commercials, _program = _labels(session)
    from experiments.nfl75.promo_class import spans_for

    promo = spans_for(overlay, session, "consumer")
    bare = unprotected_covers(clock, values, window=window, start_line=line)
    guarded = entry_guard_covers(clock, values, qualify_ends, window=window, start_line=line)
    rows = {}
    for name, covers in (("unprotected", bare), ("entry_guard", guarded)):
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
        baseline = None if name == "unprotected" else bare
        rows[name] = _metrics(scored, covers, [], promo, commercials, baseline)
    base = rows["unprotected"]
    guard = rows["entry_guard"]
    lost = commercial_given_back(bare, guarded, commercials)
    return {
        "session": session,
        "qualifying_windows": len(qualify_ends),
        "names_read": ["Al Michaels", "Kirk Herbstreit", "Clarissa Thompson"],
        "commercial_given_back": [
            {"start_s": round(start, 3), "end_s": round(end, 3), "seconds": round(end - start, 3)}
            for start, end in lost
        ],
        "unprotected": {key: base[key] for key in _kept()},
        "entry_guard": {key: guard[key] for key in _kept()},
        "programming_recovered_s": round(base["genuine_program_muted_s"] - guard["genuine_program_muted_s"], 3),
        "commercial_given_back_s": guard["commercial_given_back_s"],
        "commercial_newly_muted_s": guard["commercial_newly_muted_s"],
        "coverage_drop": round(base["commercial_coverage"] - guard["commercial_coverage"], 4),
        "identity_verified": False,
    }


def _kept() -> tuple[str, ...]:
    return (
        "commercial_coverage",
        "commercial_covered_s",
        "commercial_heard_s",
        "commercial_s",
        "genuine_program_muted_s",
        "promotional_read_muted_s",
        "program_covered_s",
        "false_mute_episodes",
        "missed_breaks",
        "late_start_s",
        "late_return_s",
        "commercial_given_back_s",
        "commercial_newly_muted_s",
    )


def _ads(rows: list[dict]) -> list[dict]:
    found = []
    for row in _commercial_rows(rows):
        why = row["why_queued"]
        gap = None
        if why.get("cited_cosine") is not None and why.get("second_cosine") is not None:
            gap = round(float(why["cited_cosine"]) - float(why["second_cosine"]), 4)
        passed = qualify(
            {
                why["cited_name"]: why["cited_cosine"],
                why["second_name"] or "other": why["second_cosine"] if why.get("second_cosine") is not None else -1.0,
            }
        )
        found.append(
            {
                "id": row["id"],
                "session": row["session"],
                "focus_start_s": row["focus_start_s"],
                "focus_end_s": row["focus_end_s"],
                "cited_name": why.get("cited_name"),
                "cited_cosine": why.get("cited_cosine"),
                "second_name": why.get("second_name"),
                "second_cosine": why.get("second_cosine"),
                "gap": gap,
                "passes_guard": passed is not None,
                "speaker_verified": False,
            }
        )
    return found


def main() -> None:
    frozen = json.loads(MEAN.read_text(encoding="utf-8"))["frozen"]
    window = int(frozen["window_s"])
    line = float(frozen["start_line"])
    if window != 10 or abs(line - 0.1632588496059179) > 0:
        raise RuntimeError("refusing a mean other than the frozen 10-second line")
    rows = _queue()
    accounting = candidate_rows(
        [
            {
                "split": row["split"],
                "kind": row["kind"],
                "session": row["session"],
                "cited_name": row["why_queued"].get("cited_name"),
                "cited_cosine": row["why_queued"].get("cited_cosine"),
                "second_cosine": row["why_queued"].get("second_cosine"),
                "focus_start_s": row["focus_start_s"],
                "focus_end_s": row["focus_end_s"],
            }
            for row in rows
        ]
    )
    ads = _ads(rows)
    blind = _blind(rows)
    if any(row["split"] == "eval" for row in rows if row["id"] in {item["id"] for item in blind}):
        raise RuntimeError("an eval clip entered the label set")
    head = nbc_lines()["head"]
    overlay = load_overlay()
    booth = json.loads(BOOTH.read_text(encoding="utf-8"))
    published = {row["session"]: row["policies"]["unprotected"]["actual"] for row in booth["sessions"]}
    sessions = []
    for session in PRIME_SESSIONS:
        payload = _run(head, session, window, line, overlay)
        expected = float(published[session]["commercial_coverage"])
        if abs(payload["unprotected"]["commercial_coverage"] - expected) > 0.0002:
            raise RuntimeError(
                f"{session} unprotected coverage {payload['unprotected']['commercial_coverage']} != {expected}"
            )
        sessions.append(payload)
        print(
            session,
            "recovered",
            payload["programming_recovered_s"],
            "ads back",
            payload["commercial_given_back_s"],
            "coverage",
            payload["entry_guard"]["commercial_coverage"],
        )
    names = RESEARCH / "VOICE_ROSTER_001" / "names.jsonl"
    wanted = {row["id"] for row in blind}
    labeled = 0
    if names.is_file():
        seen = set()
        for line in names.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("id") in wanted:
                seen.add(row["id"])
        labeled = len(seen)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "blind.json").write_text(json.dumps(blind, indent=2), encoding="utf-8")
    document = {
        "experiment": "OHUSH_VOICE_TRUTH_002",
        "deployable": False,
        "television_changed": False,
        "guard_recommended": False,
        "reason": "speaker labels are empty, so a wide gap is not a confirmed person",
        "identity_verified": False,
        "path_b": "not run; speech boundaries are empty",
        "labeled_rows": labeled,
        "eval_rows_opened": 0,
        "accounting": accounting,
        "commercial_sample": {
            "n": len(ads),
            "pass_guard": sum(1 for row in ads if row["passes_guard"]),
            "rows": ads,
            "note": "selected windows, not a rate for whole breaks, and not a verified speaker",
        },
        "fresh_s": 1.0,
        "fresh_s_is": "the second after a finished 2-second window, not a pause hold",
        "sessions": sessions,
        "blind_clips": len(blind),
    }
    (OUT / "results.json").write_text(json.dumps(document, indent=2), encoding="utf-8")
    print("accounting", accounting["episodes"], accounting["seconds"], accounting["by_name"])
    print("ads pass", document["commercial_sample"]["pass_guard"], "of", len(ads))
    print("blind", len(blind), "path_b", document["path_b"])


if __name__ == "__main__":
    main()
