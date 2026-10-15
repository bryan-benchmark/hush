"""SPRINT-90-10 comparison. No new matcher and no continuation rule.

Reads the published decisions and the three rematch files already written by
the reference-pod runs. Scores count 10, each removal, and the frozen voice
guard on the same clock. Does not retune, edit gold, or open a holdout.
"""

from __future__ import annotations

import csv
import hashlib
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
    COUNT_V1,
    HOLDOUTS,
    REDZONE,
    inside,
    load_decisions,
    protection_for,
)
from experiments.universal_v1.replay import actions_for, cover_spans, intersect, overlap, subtract  # noqa: E402
from experiments.universal_v4.speaker_enrollment import person_name  # noqa: E402

OUT = REPO / "docs/ohush/research/SPRINT_90_10_001"
POD = REPO / "docs/ohush/research/POD_REMOVAL_001"
DECISIONS = REPO / "docs/ohush/research/UNIVERSAL_V1/decisions.jsonl"
EXP = REPO / "experiments/exp002"
HOLE_COMMERCIAL_S = 5.0


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def apply_patch(decisions: dict[str, list[dict]], path: Path, expected: int) -> dict[str, list[dict]]:
    changed = {}
    with path.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            changed[(row["session"], round(float(row["query_t0"]), 3))] = row
    if len(changed) != expected:
        raise SystemExit(f"{path.name} has {len(changed)} rows, expected {expected}")
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
        raise SystemExit(f"{path.name} did not land on published queries")
    return rewritten


def enroll(ads: dict) -> tuple[list[dict], dict, dict[str, set[str]]]:
    labeled = []
    for row in latest_names():
        labeled.extend(spans_from(row))
    homes: dict[str, set[str]] = defaultdict(set)
    windows = {}
    for path in sorted(EXP.iterdir()):
        if not (path / "speaker_segments.parquet").exists():
            continue
        if path.name in HOLDOUTS:
            raise SystemExit("refusing a sealed holdout")
        windows[path.name] = load_windows(path.name)
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
            homes[name].add(sid)
    if len(enrolled) != 94:
        raise SystemExit(f"expected 94 enrollment windows, found {len(enrolled)}")
    return enrolled, windows, homes


def premature(actions, pods: list[tuple[float, float]]) -> tuple[int, float]:
    incidents = 0
    seconds = 0.0
    for start, end in pods:
        saw = False
        letting = False
        for left, right, action, _reason in actions:
            lo, hi = max(left, start), min(right, end)
            if hi <= lo:
                continue
            if action == "cover":
                saw = True
                letting = False
            elif saw:
                if not letting:
                    incidents += 1
                    letting = True
                seconds += hi - lo
    return incidents, seconds


def score_population(name: str, sessions: dict, ads: dict, decisions: dict, windows: dict, enrolled: list[dict], homes: dict, use_guard: bool, count: int) -> dict:
    rows_out = []
    program_tenths = commercial_tenths = 0.0
    incidents = 0
    worst = 0.0
    premature_n = 0
    premature_s = 0.0
    same_program = cross_program = same_ad = cross_ad = 0.0
    for sid, bag in sessions.items():
        football = bag["content"] == "sports" and sid != REDZONE
        zone = sid == REDZONE
        if name == "football" and not football:
            continue
        if name == "redzone" and not zone:
            continue
        cov0, cov1 = bag["coverage"]
        program = subtract([(cov0, cov1)], ads[sid])
        decision_rows = decisions.get(sid, [])
        actions = actions_for(bag, decision_rows, count)
        covers = cover_spans(actions)
        if use_guard and sid in windows:
            guards = protection_for(sid, windows[sid], enrolled, cov1)
            for guard in guards:
                piece = [(guard["start"], guard["end"])]
                program_piece = overlap(program, intersect(covers, piece))
                ad_piece = overlap(ads[sid], intersect(covers, piece))
                if sid in homes[guard["name"]]:
                    same_program += program_piece
                    same_ad += ad_piece
                else:
                    cross_program += program_piece
                    cross_ad += ad_piece
            covers = subtract(covers, [(row["start"], row["end"]) for row in guards])
            actions = rebuild_actions(actions, covers, cov0, cov1)
        pieces = intersect(covers, program)
        program_here = overlap(program, covers)
        commercial_here = overlap(ads[sid], covers)
        worst_here = max((end - start for start, end in pieces), default=0.0)
        let_n, let_s = premature(actions, ads[sid])
        program_tenths += round(program_here, 1)
        commercial_tenths += round(commercial_here, 1)
        incidents += len(pieces)
        worst = max(worst, worst_here)
        premature_n += let_n
        premature_s += let_s
        rows_out.append({
            "population": name,
            "session": sid,
            "network": bag["network"],
            "commercial_seconds_covered": round(commercial_here, 1),
            "program_seconds_covered": round(program_here, 1),
            "false_mute_incidents": len(pieces),
            "worst_interruption_s": round(worst_here, 1),
            "premature_release_incidents": let_n,
            "commercial_seconds_after_premature_release": round(let_s, 1),
        })
    return {
        "program_s": round(program_tenths, 1),
        # The 5-second read hole sits inside count-10 commercial covers and outside v1's 25 seconds.
        "commercial_s": round(
            commercial_tenths - (HOLE_COMMERCIAL_S if name == "football" and commercial_tenths > 100 else 0.0),
            1,
        ),
        "incidents": incidents,
        "worst_interruption_s": round(worst, 1),
        "premature_release_incidents": premature_n,
        "commercial_seconds_after_premature_release": round(premature_s, 1),
        "same_recording_program_s": round(same_program, 3),
        "cross_recording_program_s": round(cross_program, 3),
        "same_recording_commercial_s": round(same_ad, 3),
        "cross_recording_commercial_s": round(cross_ad, 3),
        "sessions": rows_out,
    }


def rebuild_actions(actions, covers, cov0: float, cov1: float):
    """Play everywhere the guard removed a cover. Boundaries stay the old ones."""
    rebuilt = []
    for left, right, action, reason in actions:
        if action != "cover":
            rebuilt.append((left, right, action, reason))
            continue
        kept = intersect([(left, right)], covers)
        cursor = left
        for start, end in kept:
            if start > cursor:
                rebuilt.append((cursor, start, "play", "named_program_voice"))
            rebuilt.append((start, end, "cover", reason))
            cursor = end
        if cursor < right:
            rebuilt.append((cursor, right, "play", "named_program_voice"))
    return [(left, right, action, reason) for left, right, action, reason in rebuilt if right > left + 1e-9]


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
    enrolled, windows, homes = enroll(ads)
    variants = {
        "count10": (published, False, COUNT_ABLATION),
        "top1": (apply_patch(published, POD / "top_1_changed_queries.csv", 23), False, COUNT_ABLATION),
        "top5": (apply_patch(published, POD / "top_5_changed_queries.csv", 123), False, COUNT_ABLATION),
        "top10": (apply_patch(published, POD / "top_10_changed_queries.csv", 215), False, COUNT_ABLATION),
        "voice_guard": (published, True, COUNT_ABLATION),
        "v1": (published, False, COUNT_V1),
    }
    payload = {"populations": {}, "hashes": {}}
    session_rows = []
    for label, (decisions, use_guard, count) in variants.items():
        payload["populations"][label] = {}
        for population in ("football", "redzone"):
            scored = score_population(population, sessions, ads, decisions, windows, enrolled, homes, use_guard, count)
            session_rows.extend([{**row, "candidate": label} for row in scored.pop("sessions")])
            payload["populations"][label][population] = scored
    foot = payload["populations"]["count10"]["football"]
    if foot["incidents"] != 72 or abs(foot["program_s"] - 432.1) > 0.05 or abs(foot["commercial_s"] - 3903.2) > 0.05:
        raise SystemExit(f"count 10 football did not reproduce: {foot}")
    if foot["premature_release_incidents"] != 186 or abs(foot["commercial_seconds_after_premature_release"] - 6321.5) > 0.15:
        raise SystemExit(f"premature releases did not reproduce: {foot}")
    if abs(payload["populations"]["top5"]["football"]["program_s"] - 337.3) > 0.15:
        raise SystemExit(f"top five did not reproduce: {payload['populations']['top5']['football']}")
    for path in (
        DECISIONS,
        POD / "top_1_changed_queries.csv",
        POD / "top_5_changed_queries.csv",
        POD / "top_10_changed_queries.csv",
        REPO / "docs/ohush/research/VOICE_ROSTER_001/names.jsonl",
    ):
        payload["hashes"][str(path.relative_to(REPO))] = sha256_file(path)
    payload["continuation"] = "not_opened"
    payload["reason"] = "None of the three changes keeps commercial coverage while clearing most of the 72 incidents."
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "summary.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    with (OUT / "session_comparison.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(session_rows[0]))
        writer.writeheader()
        writer.writerows(session_rows)
    print(json.dumps({label: block["football"] | {"redzone_program_s": payload["populations"][label]["redzone"]["program_s"]} for label, block in ((name, payload["populations"][name]) for name in variants)}, indent=2))


if __name__ == "__main__":
    main()
