"""Roster reconciliation and the count-10 false-cover ceiling. Not a mute.

names.jsonl is only read. The latest row for a clip is session plus
play_start, because v001 was reused. The 72 football incidents are rebuilt
from the published fingerprint decisions. A named-voice second is the
existing causal ECAPA guard. An embedding window is speech the model
already cut, not proof that a known announcer was talking.
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
from experiments.ledger import resolve_ledger  # noqa: E402
from experiments.measurement.verified_speaker_001 import latest_names, load_windows, spans_from  # noqa: E402
from experiments.measurement.voice_guard_001 import protection_for  # noqa: E402
from experiments.universal_v1.replay import (  # noqa: E402
    COUNT_ABLATION,
    REDZONE,
    actions_for,
    cover_spans,
    intersect,
    overlap,
    subtract,
)
from experiments.universal_v4.speaker_enrollment import person_name  # noqa: E402
from hush.audio import analysis_pieces, find_session, load_session  # noqa: E402
from hush.speaker_memory import MATCH_COSINE  # noqa: E402

NAMES = REPO / "docs/ohush/research/VOICE_ROSTER_001/names.jsonl"
LEDGER = REPO / "docs/ohush/research/UNIVERSAL_V4_SPEAKER_ENROLLMENT_001/verified.jsonl"
DECISIONS = REPO / "docs/ohush/research/UNIVERSAL_V1/decisions.jsonl"
ROSTER_OUT = REPO / "docs/ohush/research/ROSTER_SYNC_001"
CEILING_OUT = REPO / "docs/ohush/research/VOICE_ERROR_CEILING_001"
HOLDOUTS = ("hush_20260917_205513", "hush_20260920_200635")
RECORDINGS = REPO / "recordings"


def sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def clip_key(row: dict) -> str:
    return f"{row.get('session')}|{float(row.get('play_start') or 0):.3f}"


def all_rows() -> list[dict]:
    rows = []
    for line in NAMES.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            if row.get("session") in HOLDOUTS:
                raise SystemExit("refusing a sealed holdout")
            rows.append(row)
    return rows


def latest_by(rows: list[dict], key) -> list[dict]:
    latest: dict[str, dict] = {}
    for row in rows:
        latest[key(row)] = row
    return list(latest.values())


def named_counts(rows: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for row in rows:
        for span in spans_from(row):
            name = person_name(span)
            if name:
                counts[name] += 1
    return dict(sorted(counts.items()))


def read_holes(sessions: dict) -> dict[str, list[tuple[float, float]]]:
    holes: dict[str, list[tuple[float, float]]] = {}
    for sid, bag in sessions.items():
        cov0, cov1 = bag["coverage"]
        found = []
        cursor = cov0
        while cursor < cov1 - 0.5:
            take = min(90.0, cov1 - cursor)
            try:
                analysis_pieces(bag["dir"], bag["meta"], cursor, min(cov1, cursor + take + 2.0))
            except RuntimeError:
                hole = min(5.0, cov1 - cursor)
                found.append((cursor, cursor + hole))
                cursor += 5.0
                continue
            cursor += take
        holes[sid] = found
    return holes


def population(bag: dict, sid: str) -> str:
    if sid == REDZONE:
        return "redzone"
    if bag["content"] == "sports":
        return "football"
    return "scripted"


def main() -> None:
    rows = all_rows()
    by_id = resolve_ledger(rows, "id")
    by_clip = latest_by(rows, clip_key)
    id_keys = {clip_key(row) for row in by_id}
    clip_keys = {clip_key(row) for row in by_clip}
    lost_by_id = [row for row in by_clip if clip_key(row) not in id_keys]
    id_counts = named_counts(by_id)
    clip_counts = named_counts(by_clip)
    roster = {
        "system": "roster_sync_001",
        "mute_policy": False,
        "names_jsonl_rows": len(rows),
        "verified_jsonl_rows": sum(1 for line in LEDGER.read_text(encoding="utf-8").splitlines() if line.strip()) if LEDGER.exists() else 0,
        "latest_by_reused_clip_id": len(by_id),
        "latest_by_session_and_play_start": len(by_clip),
        "clips_hidden_when_latest_id_wins": [
            {"id": row["id"], "session": row["session"], "play_start": row["play_start"], "who": row.get("who")}
            for row in lost_by_id
        ],
        "named_spans_by_id": id_counts,
        "named_spans_by_clip": clip_counts,
        "named_people_by_clip": len(clip_counts),
        "named_span_total_by_clip": sum(clip_counts.values()),
        "annotation_files_rewritten": False,
    }
    ROSTER_OUT.mkdir(parents=True, exist_ok=True)
    (ROSTER_OUT / "reconciled_roster.json").write_text(json.dumps(roster, indent=2) + "\n", encoding="utf-8")

    catalog = load_catalog()
    spans = [span for span in coverage() if span["session"] not in HOLDOUTS]
    sessions = {}
    for span in spans:
        sid = span["session"]
        folder = find_session(RECORDINGS, sid)
        meta = load_session(folder)
        info = catalog.get(sid, {})
        sessions[sid] = {
            "dir": folder,
            "meta": meta,
            "coverage": (float(span["from_seconds"]), float(span["to_seconds"])),
            "network": info.get("network_or_service") or "unknown",
            "content": info.get("content_type") or "",
        }
    ads: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for row in commercials(spans):
        ads[row["session"]].append((float(row["start_seconds"]), float(row["end_seconds"])))
    decisions: dict[str, list[dict]] = defaultdict(list)
    for line in DECISIONS.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row["session"] in HOLDOUTS:
            raise SystemExit("refusing a sealed holdout")
        decisions[row["session"]].append(row)
    holes = read_holes(sessions)
    labeled = []
    for row in latest_names():
        labeled.extend(spans_from(row))
    voice_sessions = []
    windows = {}
    for sid in sorted({row["session"] for row in labeled}):
        try:
            windows[sid] = load_windows(sid)
            voice_sessions.append(sid)
        except FileNotFoundError:
            continue
    enrolled = []
    for sid in voice_sessions:
        here = [row for row in labeled if row["session"] == sid and person_name(row)]
        from experiments.measurement.verified_speaker_001 import assign

        for owned in assign(windows[sid], here):
            name = person_name(owned)
            if not name:
                continue
            win_start = float(windows[sid]["start"][owned["index"]])
            win_end = float(windows[sid]["end"][owned["index"]])
            midpoint = (win_start + win_end) / 2
            if any(left <= midpoint < right for left, right in ads[sid]):
                continue
            enrolled.append({"session": sid, "name": name, "span_end": float(owned["end"]), "vector": owned["vector"]})

    incidents = []
    totals = defaultdict(lambda: {"incidents": 0, "seconds": 0.0, "embedded_speech_s": 0.0, "named_match_s": 0.0, "no_embedding_s": 0.0})
    for sid, bag in sessions.items():
        cov0, cov1 = bag["coverage"]
        program = subtract(subtract([(cov0, cov1)], ads[sid]), holes[sid])
        covers = cover_spans(actions_for(bag, decisions.get(sid, []), COUNT_ABLATION))
        pieces = intersect(covers, program)
        kind = population(bag, sid)
        speech = []
        if sid in windows:
            speech = list(zip(windows[sid]["start"], windows[sid]["end"]))
        guards = protection_for(sid, windows[sid], enrolled, cov1) if sid in windows else []
        guard_spans = [(row["start"], row["end"]) for row in guards]
        for index, (left, right) in enumerate(pieces, start=1):
            duration = right - left
            speech_s = overlap([(left, right)], speech) if speech else 0.0
            named_s = overlap([(left, right)], guard_spans)
            row = {
                "population": kind,
                "session": sid,
                "network": bag["network"],
                "incident": index,
                "start_s": round(left, 3),
                "end_s": round(right, 3),
                "seconds": round(duration, 3),
                "embeddings_on_recording": sid in windows,
                "embedded_speech_s": round(speech_s, 3),
                "causal_named_match_s": round(named_s, 3),
                "oracle_known_announcer": "not_labeled",
            }
            incidents.append(row)
            block = totals[kind]
            block["incidents"] += 1
            block["seconds"] += duration
            block["embedded_speech_s"] += speech_s
            block["named_match_s"] += named_s
            if sid not in windows:
                block["no_embedding_s"] += duration
    summary = {
        "system": "voice_error_ceiling_001",
        "label": "oracle diagnostic is not measured; named-match seconds are the existing causal ECAPA guard",
        "mute_policy": False,
        "match_line": MATCH_COSINE,
        "match_line_fit": False,
        "published_football_program_s": 432.1,
        "published_football_incidents": 72,
        "gate_b_program_seconds": 86.4,
        "populations": {
            name: {key: round(value, 3) if isinstance(value, float) else value for key, value in block.items()}
            for name, block in totals.items()
        },
    }
    CEILING_OUT.mkdir(parents=True, exist_ok=True)
    with (CEILING_OUT / "per_incident.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(incidents[0].keys()))
        writer.writeheader()
        writer.writerows(incidents)
    (CEILING_OUT / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    receipts = {
        "git_head_local": "recorded_by_caller",
        "github_main_seen_by_handoff": "18c7179cfd0df1e4776f0d5b3bc25c30d25e8cff",
        "names_jsonl_sha256": sha256(NAMES),
        "verified_jsonl_sha256": sha256(LEDGER),
        "decisions_jsonl_sha256": sha256(DECISIONS),
        "holdouts_opened": False,
        "annotations_rewritten": False,
    }
    (ROSTER_OUT / "SOURCE_RECEIPTS.json").write_text(json.dumps(receipts, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"roster_people": roster["named_people_by_clip"], "hidden": len(lost_by_id), "populations": summary["populations"]}, indent=2))


if __name__ == "__main__":
    main()
