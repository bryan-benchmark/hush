"""Isolated candidate for FINGERPRINT-BLOCK-001. Not a mute.

Each 90-second block is read with 86 analyzer hops of audio before the cut.
Hashes before the cut are dropped. The published reader and its decisions
are not modified. Count 10 and count 200 are not changed.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "experiments/broadcast_intelligence/third_party/audfprint"))
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))

from experiments.broadcast_intelligence.batch1 import commercials, coverage, load_catalog, read_span  # noqa: E402
from experiments.broadcast_intelligence.known_ad_fingerprint import (  # noqa: E402
    TARGET_SR,
    fingerprint,
    frame_of,
    to_11025,
)
from experiments.universal_v1.replay import (  # noqa: E402
    COUNT_ABLATION,
    COUNT_V1,
    REDZONE,
    actions_for,
    build_refs,
    query_stream,
    score_group,
)
from hush.audio import find_session, load_session  # noqa: E402

OUT = REPO / "docs/ohush/research/FINGERPRINT_BLOCK_001"
PUBLISHED = REPO / "docs/ohush/research/UNIVERSAL_V1/results.json"
HOLDOUTS = ("hush_20260917_205513", "hush_20260920_200635")
BLOCK_S = 90.0
TAIL_S = 2.0
LEAD_HOPS = 86
LEAD_S = LEAD_HOPS * 256 / TARGET_SR
AFTERNOON = "hush_20261011_135700"


def fingerprint_sessions(sessions: dict) -> tuple[dict, list[dict], float]:
    landmarks = {}
    holes = []
    missing = 0.0
    for sid, bag in sessions.items():
        if sid in HOLDOUTS:
            raise SystemExit("refusing a sealed holdout")
        cov0, cov1 = bag["coverage"]
        frames_all, hashes_all, dts_all = [], [], []
        cursor = cov0
        while cursor < cov1 - 0.5:
            take = min(BLOCK_S, cov1 - cursor)
            origin = max(cov0, cursor - LEAD_S)
            try:
                audio = read_span(bag["dir"], bag["meta"], origin, min(cov1, cursor + take + TAIL_S))
            except RuntimeError:
                hole = min(5.0, cov1 - cursor)
                holes.append({"session": sid, "start": cursor, "end": cursor + hole})
                missing += hole
                cursor += 5.0
                continue
            block_frames, block_hashes, block_dts = fingerprint(to_11025(audio), frame_of(origin))
            keep = (block_frames >= frame_of(cursor)) & (block_frames < frame_of(cursor + take))
            frames_all.append(block_frames[keep])
            hashes_all.append(block_hashes[keep])
            dts_all.append(block_dts[keep])
            cursor += take
        landmarks[sid] = {
            "frames": np.concatenate(frames_all) if frames_all else np.zeros(0, np.int32),
            "hashes": np.concatenate(hashes_all) if hashes_all else np.zeros(0, np.int32),
            "dts": np.concatenate(dts_all) if dts_all else np.zeros(0, np.int16),
        }
        print(f"  {sid} hashes {landmarks[sid]['frames'].size}", flush=True)
    return landmarks, holes, missing


def slim(group: dict) -> dict:
    return {
        key: group[key]
        for key in (
            "commercial_seconds_heard",
            "program_seconds_covered",
            "false_cover_incidents",
            "worst_continuous_program_interruption_s",
            "premature_return_incidents",
            "ad_seconds_heard_after_a_cover_let_go",
            "return_delay_s",
            "pods_with_any_cover",
            "pods_missed",
        )
        if key in group
    }


def main() -> None:
    sys.stdout.reconfigure(line_buffering=True)
    started = time.perf_counter()
    catalog = load_catalog()
    spans = coverage()
    raw_pods = commercials(spans)
    sessions = {}
    for span in spans:
        sid = span["session"]
        if sid in HOLDOUTS:
            raise SystemExit("refusing a sealed holdout")
        folder = find_session(REPO / "recordings", sid)
        info = catalog.get(sid, {})
        sessions[sid] = {
            "dir": folder,
            "meta": load_session(folder),
            "coverage": (float(span["from_seconds"]), float(span["to_seconds"])),
            "network": info.get("network_or_service") or "unknown",
            "content": info.get("content_type") or "",
        }
    pods = []
    for index, row in enumerate(raw_pods):
        sid = row["session"]
        pods.append(
            {
                "id": index,
                "session": sid,
                "network": sessions[sid]["network"],
                "content": sessions[sid]["content"],
                "start": float(row["start_seconds"]),
                "end": float(row["end_seconds"]),
            }
        )
    print("fingerprinting with lead", round(LEAD_S, 4), flush=True)
    landmarks, holes, missing = fingerprint_sessions(sessions)
    refs, index = build_refs(pods, landmarks)
    print("querying", flush=True)
    rows = query_stream(sessions, pods, landmarks, refs, index)
    by_session: dict[str, list] = {}
    for row in rows:
        by_session.setdefault(row["session"], []).append(row)
    published = json.loads(PUBLISHED.read_text(encoding="utf-8"))
    populations = {}
    for count, label in ((COUNT_V1, "count_200"), (COUNT_ABLATION, "count_10")):
        actions = {sid: actions_for(bag, by_session.get(sid, []), count) for sid, bag in sessions.items()}
        populations[label] = {}
        for name in ("football", "redzone", "scripted"):
            group = score_group(name, sessions, pods, holes, actions, count)
            before = published["groups"]["v1" if count == COUNT_V1 else "ablation_count_10"][name]
            populations[label][name] = {
                "candidate": slim(group),
                "published": slim(before),
                "program_seconds_recovered": round(before["program_seconds_covered"] - group["program_seconds_covered"], 3),
                "commercial_seconds_no_longer_covered": round(
                    group["commercial_seconds_heard"] - before["commercial_seconds_heard"], 3
                ),
            }
    foot = populations["count_10"]["football"]
    red = populations["count_10"]["redzone"]
    gates = {
        "recover_at_least_50_program_seconds": foot["program_seconds_recovered"] >= 50,
        "sacrifice_at_most_25_commercial_seconds": foot["commercial_seconds_no_longer_covered"] <= 25,
        "no_new_redzone_program_seconds": red["program_seconds_recovered"] >= 0,
    }
    afternoon_block = [
        row
        for row in rows
        if row["session"] == AFTERNOON
        and abs(float(row["query_t0"]) % BLOCK_S) < 1e-3
        and row["score"] >= COUNT_ABLATION
        and not row["same_session"]
    ]
    payload = {
        "system": "fingerprint_block_001_candidate",
        "mute_policy": False,
        "playback": "PLAY",
        "frozen_extractor_modified": False,
        "frozen_decisions_modified": False,
        "correction": "Read 86 analyzer hops before each 90-second block. Drop hashes before the block. Keep the two-second tail.",
        "lead_s": round(LEAD_S, 6),
        "counts_unchanged": {"count_10": COUNT_ABLATION, "count_200": COUNT_V1},
        "holes_s": round(missing, 1),
        "afternoon_block_start_queries_at_least_10": len(afternoon_block),
        "populations": populations,
        "gates": gates,
        "gates_passed": all(gates.values()),
        "wall_s": round(time.perf_counter() - started, 1),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "candidate_ledger.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"gates": gates, "football_10": foot, "redzone_10": red, "wall_s": payload["wall_s"]}, indent=2))


if __name__ == "__main__":
    main()
