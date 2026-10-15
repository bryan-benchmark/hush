"""FINGERPRINT-WARM-CONTEXT-002. Not a mute.

Four readers, same windows, same counts. Cold is the published block start.
Warm reads 86 analyzer hops before the cut and drops hashes from that lead.
The published decisions are not rewritten.
"""

from __future__ import annotations

import csv
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "experiments/broadcast_intelligence/third_party/audfprint"))
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))

from experiments.broadcast_intelligence.batch1 import commercials, coverage, load_catalog, read_span  # noqa: E402
from experiments.broadcast_intelligence.known_ad_fingerprint import (  # noqa: E402
    TARGET_SR,
    best_match,
    fingerprint,
    frame_of,
    to_11025,
    window_hashes,
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

OUT = REPO / "docs/ohush/research/FINGERPRINT_WARM_CONTEXT_002"
PUBLISHED = REPO / "docs/ohush/research/UNIVERSAL_V1/results.json"
DECISIONS = REPO / "docs/ohush/research/UNIVERSAL_V1/decisions.jsonl"
HOLDOUTS = ("hush_20260917_205513", "hush_20260920_200635")
BLOCK_S = 90.0
TAIL_S = 2.0
QUERY_S = 5.0
LEAD_HOPS = 86
LEAD_S = LEAD_HOPS * 256 / TARGET_SR
AFTERNOON = "hush_20261011_135700"
FALSE_QUERIES = (2700.0, 2790.0, 2880.0, 3960.0, 4050.0, 4140.0, 4230.0, 4320.0, 4500.0, 4590.0, 4680.0, 4770.0, 4860.0)


def fingerprint_mode(sessions: dict, warm: bool) -> tuple[dict, list[dict], float, int]:
    landmarks = {}
    holes = []
    missing = 0.0
    bare_starts = 0
    for sid, bag in sessions.items():
        if sid in HOLDOUTS:
            raise SystemExit("refusing a sealed holdout")
        cov0, cov1 = bag["coverage"]
        frames_all, hashes_all, dts_all = [], [], []
        cursor = cov0
        while cursor < cov1 - 0.5:
            take = min(BLOCK_S, cov1 - cursor)
            origin = max(cov0, cursor - LEAD_S) if warm else cursor
            if warm and origin == cursor:
                bare_starts += 1
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
        print(f"  {'warm' if warm else 'cold'} {sid} hashes {landmarks[sid]['frames'].size}", flush=True)
    return landmarks, holes, missing, bare_starts


def delay(rows: list[dict], lag: float) -> list[dict]:
    shifted = []
    for row in rows:
        copied = dict(row)
        copied["available_at"] = round(float(row["available_at"]) + lag, 3)
        shifted.append(copied)
    return shifted


def score_arm(name: str, sessions, pods, holes, rows, count: int) -> dict:
    by_session = defaultdict(list)
    for row in rows:
        by_session[row["session"]].append(row)
    actions = {sid: actions_for(bag, by_session.get(sid, []), count) for sid, bag in sessions.items()}
    group = score_group(name, sessions, pods, holes, actions, count)
    heard = group["commercial_seconds_heard"]
    ad_seconds = round(sum(row["ad_seconds"] for row in group["sessions"]), 1)
    return {
        "commercial_seconds_covered": round(ad_seconds - heard, 1),
        "commercial_seconds_heard": heard,
        "program_seconds_covered": group["program_seconds_covered"],
        "false_cover_incidents": group["false_cover_incidents"],
        "worst_continuous_program_interruption_s": group["worst_continuous_program_interruption_s"],
        "premature_return_incidents": group["premature_return_incidents"],
        "return_delay_s": group["return_delay_s"],
        "pods_with_any_cover": group["pods_with_any_cover"],
        "sessions": group["sessions"],
    }


def lookup(rows: list[dict], session: str, query_t0: float) -> dict | None:
    for row in rows:
        if row["session"] == session and abs(float(row["query_t0"]) - query_t0) < 1e-3:
            return row
    return None


def correlation(query_session, query_t0, ref_session, ref_t0) -> float | None:
    cov0, cov1 = ref_session["coverage"]
    if ref_t0 < cov0 or ref_t0 + QUERY_S > cov1:
        return None
    left = to_11025(read_span(query_session["dir"], query_session["meta"], query_t0, query_t0 + QUERY_S))
    right = to_11025(read_span(ref_session["dir"], ref_session["meta"], ref_t0, ref_t0 + QUERY_S))
    n = min(left.size, right.size)
    left = left[:n] - float(np.mean(left[:n]))
    right = right[:n] - float(np.mean(right[:n]))
    denom = float(np.linalg.norm(left) * np.linalg.norm(right))
    if denom == 0:
        return None
    return round(float(np.dot(left, right) / denom), 4)


def truncation(session: dict, query_t0: float, warm: bool) -> list[dict]:
    cov0, cov1 = session["coverage"]
    block = cov0 + np.floor((query_t0 - cov0) / BLOCK_S + 1e-9) * BLOCK_S
    origin = max(cov0, block - LEAD_S) if warm else block
    full_end = min(cov1, block + BLOCK_S + TAIL_S)
    audio = read_span(session["dir"], session["meta"], origin, full_end)
    frames, hashes, dts = fingerprint(to_11025(audio), frame_of(origin))
    full_f, full_h = window_hashes(frames, hashes, dts, query_t0, query_t0 + QUERY_S)
    full = set(zip(full_f.astype(int).tolist(), full_h.astype(int).tolist()))
    rows = []
    for extra in (0.0, 2.0, 5.0):
        end = min(full_end, query_t0 + QUERY_S + extra)
        short = read_span(session["dir"], session["meta"], origin, end)
        s_frames, s_hashes, s_dts = fingerprint(to_11025(short), frame_of(origin))
        cut_f, cut_h = window_hashes(s_frames, s_hashes, s_dts, query_t0, query_t0 + QUERY_S)
        got = set(zip(cut_f.astype(int).tolist(), cut_h.astype(int).tolist()))
        rows.append(
            {
                "warm": warm,
                "buffer_ends_after_query_s": extra,
                "identical": got == full,
                "jaccard": round(len(got & full) / len(got | full), 4) if got or full else None,
            }
        )
    return rows


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
    afternoon = sessions[AFTERNOON]
    causal = {
        "cold_block_start": truncation(afternoon, 2790.0, warm=False),
        "warm_block_start": truncation(afternoon, 2790.0, warm=True),
        "note": "Past context is audio already received. These rows are how much audio after the query the peak picker still uses.",
    }
    print("causal", json.dumps(causal), flush=True)
    print("fingerprinting cold", flush=True)
    cold_marks, cold_holes, cold_missing, _bare = fingerprint_mode(sessions, warm=False)
    print("fingerprinting warm", flush=True)
    warm_marks, warm_holes, warm_missing, bare_starts = fingerprint_mode(sessions, warm=True)
    cold_refs, cold_index = build_refs(pods, cold_marks)
    warm_refs, warm_index = build_refs(pods, warm_marks)
    arms = {
        "cold_query_cold_reference": (cold_marks, cold_refs, cold_index, cold_holes),
        "warm_query_cold_reference": (warm_marks, cold_refs, cold_index, warm_holes),
        "cold_query_warm_reference": (cold_marks, warm_refs, warm_index, cold_holes),
        "warm_query_warm_reference": (warm_marks, warm_refs, warm_index, warm_holes),
    }
    streamed = {}
    for name, (marks, refs, index, _holes) in arms.items():
        print("querying", name, flush=True)
        streamed[name] = query_stream(sessions, pods, marks, refs, index)
    published = json.loads(PUBLISHED.read_text(encoding="utf-8"))
    populations = ("football", "redzone", "scripted")
    scored = {}
    for name, rows in streamed.items():
        holes = arms[name][3]
        scored[name] = {
            "count_10": {pop: score_arm(pop, sessions, pods, holes, rows, COUNT_ABLATION) for pop in populations},
            "count_200": {pop: score_arm(pop, sessions, pods, holes, rows, COUNT_V1) for pop in populations},
        }
    for lag in (2.0, 5.0):
        causal_rows = delay(streamed["warm_query_warm_reference"], lag)
        scored[f"warm_warm_decision_delayed_{lag:.0f}s"] = {
            "count_10": {
                pop: score_arm(pop, sessions, pods, warm_holes, causal_rows, COUNT_ABLATION) for pop in populations
            }
        }
    cold_foot = scored["cold_query_cold_reference"]["count_10"]["football"]
    reproduction = {
        "program_seconds_covered": cold_foot["program_seconds_covered"],
        "published_program_seconds_covered": published["groups"]["ablation_count_10"]["football"]["program_seconds_covered"],
        "false_cover_incidents": cold_foot["false_cover_incidents"],
        "published_false_cover_incidents": published["groups"]["ablation_count_10"]["football"]["false_cover_incidents"],
        "matches_published": abs(cold_foot["program_seconds_covered"] - 432.1) < 1.0 and cold_foot["false_cover_incidents"] == 72,
    }
    thirteen = []
    for query_t0 in FALSE_QUERIES:
        row = {"query_t0": query_t0}
        for name, rows in streamed.items():
            hit = lookup(rows, AFTERNOON, query_t0)
            row[name] = None if hit is None else int(hit["score"])
        thirteen.append(row)
    controls = []
    seen = set()
    for line in DECISIONS.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row["same_session"] or int(row["score"]) < COUNT_V1 or row["session"] in seen:
            continue
        seen.add(row["session"])
        controls.append(row)
        if len(controls) == 6:
            break
    control_rows = []
    for row in controls:
        query_t0 = float(row["query_t0"])
        bag = cold_marks[row["session"]]
        frames, hashes = window_hashes(bag["frames"], bag["hashes"], bag["dts"], query_t0, query_t0 + QUERY_S)
        earlier = [ref["id"] for ref in cold_refs if ref["session"] < row["session"]]
        allow = np.zeros(len(cold_refs), dtype=bool)
        allow[earlier] = True
        hit = best_match(frames, hashes, cold_index, allow)
        ref = None if hit["ref_id"] is None else cold_refs[hit["ref_id"]]
        aligned = None if hit["offset"] is None else query_t0 + hit["offset"] * 256 / TARGET_SR
        corr = None
        if ref is not None and aligned is not None:
            corr = correlation(sessions[row["session"]], query_t0, sessions[ref["session"]], aligned)
        entry = {
            "session": row["session"],
            "query_t0": query_t0,
            "published_score": int(row["score"]),
            "cold_offset_s": None if aligned is None else round(aligned, 3),
            "audio_correlation": corr,
        }
        for name, rows in streamed.items():
            found = lookup(rows, row["session"], query_t0)
            entry[name] = None if found is None else int(found["score"])
        control_rows.append(entry)
        print("control", entry["session"], entry["published_score"], entry["audio_correlation"], flush=True)
    chunks = afternoon["meta"]["chunks"]
    seams = sorted(float(chunk["start_elapsed_seconds"]) for chunk in chunks)
    on_file_seam = [query for query in FALSE_QUERIES if any(abs(query - seam) < 1e-3 for seam in seams)]
    payload = {
        "system": "fingerprint_warm_context_002",
        "mute_policy": False,
        "playback": "PLAY",
        "frozen_files_modified": False,
        "lead_s": round(LEAD_S, 6),
        "lead_is_past_audio": True,
        "counts_unchanged": {"count_10": COUNT_ABLATION, "count_200": COUNT_V1},
        "holes_s": {"cold": round(cold_missing, 1), "warm": round(warm_missing, 1)},
        "warm_blocks_with_no_preceding_audio": bare_starts,
        "reference_alignment": {
            "nine_matches_near_s": 9809.7,
            "nearest_90s_boundary_s": 9810.0,
            "boundary_multiple": 9810.0 / 90.0,
        },
        "false_queries_on_a_file_chunk_boundary": on_file_seam,
        "reproduction": reproduction,
        "thirteen": thirteen,
        "repeated_content_controls": control_rows,
        "lookahead": causal,
        "arms": {
            name: {
                count: {
                    pop: {key: value for key, value in block.items() if key != "sessions"}
                    for pop, block in counts.items()
                }
                for count, counts in arm.items()
            }
            for name, arm in scored.items()
        },
        "wall_s": round(time.perf_counter() - started, 1),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    with (OUT / "per_session.csv").open("w", encoding="utf-8", newline="") as handle:
        fields = [
            "arm",
            "count",
            "population",
            "session",
            "network",
            "program_seconds_covered",
            "commercial_seconds_covered",
            "false_cover_incidents",
            "worst_program_interruption_s",
            "ad_seconds_heard",
            "unscorable_s",
        ]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for name, arm in scored.items():
            for count, counts in arm.items():
                for pop, block in counts.items():
                    for row in block["sessions"]:
                        writer.writerow(
                            {
                                "arm": name,
                                "count": count,
                                "population": pop,
                                "session": row["session"],
                                "network": row["network"],
                                "program_seconds_covered": row["program_seconds_covered"],
                                "commercial_seconds_covered": round(row["ad_seconds"] - row["ad_seconds_heard"], 1),
                                "false_cover_incidents": row["false_cover_incidents"],
                                "worst_program_interruption_s": row["worst_program_interruption_s"],
                                "ad_seconds_heard": row["ad_seconds_heard"],
                                "unscorable_s": row["unscorable_s"],
                            }
                        )
    print(json.dumps({"reproduction": reproduction, "thirteen": thirteen, "wall_s": payload["wall_s"]}, indent=2))


if __name__ == "__main__":
    main()
