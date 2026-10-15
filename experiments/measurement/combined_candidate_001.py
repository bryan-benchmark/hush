"""COMBINED-CANDIDATE-001. Shadow only.

Count 10 with the top-five reference pods removed, then the frozen voice
guard on top. The removal comes from the rematch already stored in
POD_REMOVAL_001. The guard uses the October ECAPA pass and cosine 0.25.
Neither threshold moves. Playback stays PLAY.
"""

from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from experiments.broadcast_intelligence.batch1 import commercials, coverage, load_catalog  # noqa: E402
from experiments.measurement.verified_speaker_001 import assign, latest_names, load_windows, spans_from  # noqa: E402
from experiments.measurement.voice_guard_001 import (  # noqa: E402
    COUNT_ABLATION,
    HOLDOUTS,
    REDZONE,
    inside,
    load_decisions,
    protection_for,
)
from experiments.universal_v1.replay import actions_for, cover_spans, intersect, overlap, subtract  # noqa: E402
from experiments.universal_v4.speaker_enrollment import person_name  # noqa: E402
from hush.speaker_memory import MATCH_COSINE  # noqa: E402

OUT = REPO / "docs/ohush/research/COMBINED_CANDIDATE_001"
# One cable read hole adds 5 commercial seconds to the raw interval sum.
# It stays covered in every candidate below, so deltas are unchanged.
HOLE_COMMERCIAL_S = 5.0
CHANGED = REPO / "docs/ohush/research/POD_REMOVAL_001/top_5_changed_queries.csv"
EXP = REPO / "experiments/exp002"


def apply_removal(decisions: dict[str, list[dict]]) -> dict[str, list[dict]]:
    changed = {}
    with CHANGED.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            changed[(row["session"], round(float(row["query_t0"]), 3))] = row
    if len(changed) != 123:
        raise SystemExit(f"expected 123 rematched top-five queries, found {len(changed)}")
    used = set()
    rewritten = {}
    for sid, rows in decisions.items():
        nxt = []
        for row in rows:
            key = (sid, round(float(row["query_t0"]), 3))
            if key not in changed:
                nxt.append(row)
                continue
            used.add(key)
            fresh = dict(row)
            patch = changed[key]
            fresh["score"] = int(patch["new_score"])
            ref = patch["new_ref_session"] or None
            fresh["ref_session"] = ref
            fresh["ref_start"] = None if not patch["new_ref_start"] else float(patch["new_ref_start"])
            fresh["same_session"] = bool(ref is not None and ref == sid)
            nxt.append(fresh)
        rewritten[sid] = nxt
    if used != set(changed):
        raise SystemExit("rematch rows did not land on published queries")
    return rewritten


def enroll(ads: dict) -> tuple[list[dict], dict]:
    labeled = []
    for row in latest_names():
        labeled.extend(spans_from(row))
    voice_sessions = sorted({row["session"] for row in labeled} | {path.name for path in EXP.iterdir() if (path / "speaker_segments.parquet").exists()})
    windows = {}
    for sid in voice_sessions:
        if sid in HOLDOUTS:
            raise SystemExit("refusing a sealed holdout")
        if (EXP / sid / "speaker_segments.parquet").exists():
            windows[sid] = load_windows(sid)
    enrolled = []
    for sid, here_windows in windows.items():
        here = [row for row in labeled if row["session"] == sid and person_name(row)]
        for owned in assign(here_windows, here):
            name = person_name(owned)
            if not name:
                continue
            start = float(here_windows["start"][owned["index"]])
            end = float(here_windows["end"][owned["index"]])
            if inside(ads[sid], (start + end) / 2):
                continue
            enrolled.append({"session": sid, "name": name, "span_end": float(owned["end"]), "vector": owned["vector"]})
    return enrolled, windows


def measure(sessions: dict, ads: dict, decisions: dict, windows: dict, enrolled: list[dict], use_guard: bool) -> dict:
    program_s = commercial_s = 0.0
    incidents = 0
    worst = 0.0
    per_session = []
    for sid, bag in sessions.items():
        if bag["content"] != "sports" or sid == REDZONE:
            continue
        cov0, cov1 = bag["coverage"]
        program = subtract([(cov0, cov1)], ads[sid])
        rows = decisions.get(sid, [])
        covers = cover_spans(actions_for(bag, rows, COUNT_ABLATION))
        if use_guard and sid in windows:
            guards = protection_for(sid, windows[sid], enrolled, cov1)
            covers = subtract(covers, [(row["start"], row["end"]) for row in guards])
        pieces = intersect(covers, program)
        program_here = overlap(program, covers)
        commercial_here = overlap(ads[sid], covers)
        program_s += program_here
        commercial_s += commercial_here
        incidents += len(pieces)
        worst = max(worst, max((end - start for start, end in pieces), default=0.0))
        per_session.append((sid, round(program_here, 1), round(commercial_here, 1), len(pieces)))
    return {
        "program_s": round(program_s, 3),
        "program_s_tenths": round(sum(row[1] for row in per_session), 1),
        "commercial_muted_s": round(commercial_s, 3),
        "commercial_muted_tenths": round(sum(row[2] for row in per_session), 1),
        "incidents": incidents,
        "worst_interruption_s": round(worst, 3),
        "sessions": [{"session": row[0], "program_s": row[1], "commercial_muted_s": row[2], "incidents": row[3]} for row in per_session],
    }


def main() -> None:
    catalog = load_catalog()
    spans = coverage()
    sessions = {}
    for span in spans:
        sid = span["session"]
        if sid in HOLDOUTS:
            raise SystemExit("refusing a sealed holdout")
        info = catalog.get(sid, {})
        sessions[sid] = {
            "coverage": (float(span["from_seconds"]), float(span["to_seconds"])),
            "network": info.get("network_or_service") or "unknown",
            "content": info.get("content_type") or "",
        }
    ads: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for row in commercials(spans):
        ads[row["session"]].append((float(row["start_seconds"]), float(row["end_seconds"])))
    published = load_decisions()
    removed = apply_removal(published)
    enrolled, windows = enroll(ads)
    if len(enrolled) != 94:
        raise SystemExit(f"expected 94 enrollment windows, found {len(enrolled)}")
    count10 = measure(sessions, ads, published, windows, enrolled, False)
    removal = measure(sessions, ads, removed, windows, enrolled, False)
    guard = measure(sessions, ads, published, windows, enrolled, True)
    both = measure(sessions, ads, removed, windows, enrolled, True)
    if count10["incidents"] != 72 or abs(count10["program_s_tenths"] - 432.1) > 0.05:
        raise SystemExit(f"count 10 did not reproduce: {count10}")
    if abs(removal["program_s_tenths"] - 337.3) > 0.15:
        raise SystemExit(f"top-five removal did not reproduce: {removal}")
    if abs(guard["program_s"] - (432.1 - 132.295)) > 0.2:
        raise SystemExit(f"voice guard did not reproduce: {guard}")

    def delta(row: dict) -> dict:
        return {
            "program_seconds_cleared": round(count10["program_s_tenths"] - row["program_s_tenths"], 1),
            "commercial_seconds_lost": round(count10["commercial_muted_tenths"] - row["commercial_muted_tenths"], 1),
            "incidents_cleared": count10["incidents"] - row["incidents"],
            "program_s": row["program_s_tenths"],
            "commercial_muted_s": round(row["commercial_muted_tenths"] - HOLE_COMMERCIAL_S, 1),
            "incidents": row["incidents"],
            "worst_interruption_s": row["worst_interruption_s"],
        }

    removal_only = delta(removal)
    guard_only = delta(guard)
    combined = delta(both)
    overlap_program = round(removal_only["program_seconds_cleared"] + guard_only["program_seconds_cleared"] - combined["program_seconds_cleared"], 1)
    overlap_commercial = round(removal_only["commercial_seconds_lost"] + guard_only["commercial_seconds_lost"] - combined["commercial_seconds_lost"], 1)
    payload = {
        "system": "combined_candidate_001",
        "mute_policy": False,
        "playback": "PLAY",
        "count": COUNT_ABLATION,
        "voice_line": MATCH_COSINE,
        "selection": "top five pods chosen on this same ledger; exploratory",
        "count10": delta(count10) | {"program_seconds_cleared": 0.0, "commercial_seconds_lost": 0.0, "incidents_cleared": 0},
        "top5_removal": removal_only,
        "voice_guard": guard_only,
        "both": combined,
        "shared_program_seconds": overlap_program,
        "shared_commercial_seconds": overlap_commercial,
        "enrollment_windows": len(enrolled),
    }
    # delta(count10) uses tenths minus tenths = 0. Good.
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    (OUT / "REPORT.md").write_text(render(payload), encoding="utf-8")
    print(json.dumps({"removal": removal_only, "guard": guard_only, "both": combined, "shared_program": overlap_program, "shared_commercial": overlap_commercial}, indent=2))


def render(payload: dict) -> str:
    both = payload["both"]
    lines = [
        "# Combined candidate",
        "",
        "Verdict: the two changes mostly touch different seconds, and the commercial loss stacks. Together they clear 197.3 program seconds and give back 707.5 commercial seconds. That is the opposite of a small commercial cost. Playback stays PLAY.",
        "",
        "Count 10 stays 10. The voice line stays cosine 0.25. The five pods are the ones the accuracy audit associated with 216.2 false program seconds, removed by the rematch already run. The guard is the frozen rule after the October speaker pass.",
        "",
        "| Candidate | Program seconds still covered | Program seconds cleared | Incidents | Commercial seconds muted | Commercial seconds lost | Worst interruption |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    labels = (
        ("Count 10", "count10"),
        ("Top-five pods removed", "top5_removal"),
        ("Voice guard", "voice_guard"),
        ("Both", "both"),
    )
    for label, key in labels:
        row = payload[key]
        lines.append(
            f"| {label} | {row['program_s']:.1f} | {row['program_seconds_cleared']:.1f} | {row['incidents']} | "
            f"{row['commercial_muted_s']:.1f} | {row['commercial_seconds_lost']:.1f} | {row['worst_interruption_s']:.1f} |"
        )
    lines += [
        "",
        f"Of the program seconds cleared by one change or the other, {payload['shared_program_seconds']:.1f} are cleared by both. "
        f"{payload['shared_commercial_seconds']:.1f} commercial seconds are given back by both. "
        f"Together they clear {both['program_seconds_cleared']:.1f} program seconds and give back {both['commercial_seconds_lost']:.1f} commercial seconds. "
        f"{both['incidents']} false-mute incidents remain, and the longest interruption is {both['worst_interruption_s']:.1f} s.",
        "",
        "The pods were chosen on this ledger, so the removal half is a discovery result. No live playback changed.",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    main()
