"""BLOCK-START-CONTEXT-001. Not a mute.

The published fingerprint reads each 90-second block with two seconds after
the cut and none before it. This rescores the October 11 afternoon
block-start queries with leading audio, against the same reference pods.
Count 10 is not changed. Block-start queries are not discarded.
"""

from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "experiments/broadcast_intelligence/third_party/audfprint"))
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))

from experiments.broadcast_intelligence.batch1 import commercials, coverage, load_catalog, read_span  # noqa: E402
from experiments.broadcast_intelligence.known_ad_fingerprint import (  # noqa: E402
    MATCH_WIN,
    TARGET_SR,
    best_match,
    build_index,
    fingerprint,
    frame_of,
    to_11025,
    window_hashes,
)
from experiments.universal_v1.replay import COUNT_ABLATION  # noqa: E402
from hush.audio import find_session, load_session  # noqa: E402

DECISIONS = REPO / "docs/ohush/research/UNIVERSAL_V1/decisions.jsonl"
OUT = REPO / "docs/ohush/research/BLOCK_START_CONTEXT_001"
RECORDINGS = REPO / "recordings"
HOLDOUTS = ("hush_20260917_205513", "hush_20260920_200635")
AFTERNOON = "hush_20261011_135700"
BLOCK_S = 90.0
HOP_S = 5.0
TAIL_S = 2.0
# Leading audio in whole analyzer hops, so the fingerprint grid still
# lands on the same samples as the published block read.
LEAD_HOPS = (11, 43, 86)


def on_block_start(instant: float, origin: float) -> bool:
    relative = instant - origin
    if relative < -1e-6:
        return False
    remainder = relative % BLOCK_S
    return remainder < 1e-3 or BLOCK_S - remainder < 1e-3


def block_start(instant: float, origin: float) -> float:
    return origin + np.floor((instant - origin) / BLOCK_S + 1e-9) * BLOCK_S


def hashes_for(session: dict, t0: float, t1: float, keep0: float, keep1: float) -> tuple[np.ndarray, np.ndarray]:
    audio = read_span(session["dir"], session["meta"], t0, t1)
    frames, hashes, dts = fingerprint(to_11025(audio), frame_of(t0))
    return window_hashes(frames, hashes, dts, keep0, keep1)


def ref_hashes(session: dict, pod0: float, pod1: float, cov0: float, cov1: float, cache: dict) -> tuple[np.ndarray, np.ndarray]:
    frames, hashes, dts = [], [], []
    cursor = block_start(pod0, cov0)
    while cursor < pod1 - 1e-6:
        take = min(BLOCK_S, cov1 - cursor)
        key = (session["id"], round(cursor, 3))
        if key not in cache:
            audio = read_span(session["dir"], session["meta"], cursor, min(cov1, cursor + take + TAIL_S))
            cache[key] = fingerprint(to_11025(audio), frame_of(cursor))
            print(f"  ref block {session['id']} {cursor:.0f}", flush=True)
        block_frames, block_hashes, block_dts = cache[key]
        keep = block_frames < frame_of(cursor + take)
        frames.append(block_frames[keep])
        hashes.append(block_hashes[keep])
        dts.append(block_dts[keep])
        cursor += BLOCK_S
    if not frames:
        return np.zeros(0, np.int32), np.zeros(0, np.int32)
    return window_hashes(np.concatenate(frames), np.concatenate(hashes), np.concatenate(dts), pod0, pod1)


def agreeing(query_frames: np.ndarray, query_hashes: np.ndarray, ref_frames: np.ndarray, ref_hashes: np.ndarray, offset: int | None) -> np.ndarray:
    if offset is None or query_frames.size == 0 or ref_frames.size == 0:
        return np.zeros(0, np.int32)
    buckets: dict[int, list[int]] = defaultdict(list)
    for frame, hash_ in zip(ref_frames.tolist(), ref_hashes.tolist()):
        buckets[int(hash_)].append(int(frame))
    chosen = []
    for frame, hash_ in zip(query_frames.tolist(), query_hashes.tolist()):
        hits = buckets.get(int(hash_))
        if not hits:
            continue
        if any(abs((ref_frame - int(frame)) - offset) <= MATCH_WIN for ref_frame in hits):
            chosen.append(int(frame))
    return np.asarray(chosen, dtype=np.int32)


def waveform_correlation(query_session: dict, query_t0: float, ref_session: dict, ref_t0: float) -> float | None:
    ref_cov0, ref_cov1 = ref_session["coverage"]
    if ref_t0 < ref_cov0 or ref_t0 + HOP_S > ref_cov1:
        return None
    left = to_11025(read_span(query_session["dir"], query_session["meta"], query_t0, query_t0 + HOP_S))
    right = to_11025(read_span(ref_session["dir"], ref_session["meta"], ref_t0, ref_t0 + HOP_S))
    n = min(left.size, right.size)
    if n < TARGET_SR:
        return None
    left = left[:n] - np.mean(left[:n])
    right = right[:n] - np.mean(right[:n])
    denom = float(np.linalg.norm(left) * np.linalg.norm(right))
    if denom == 0:
        return None
    return round(float(np.dot(left, right) / denom), 3)


def edge_ratio(session: dict, query_t0: float) -> dict | None:
    """Peak of the resampled onset versus the same samples taken from a read that started earlier."""
    try:
        cold = to_11025(read_span(session["dir"], session["meta"], query_t0, query_t0 + 1.0))
        warm = to_11025(read_span(session["dir"], session["meta"], query_t0 - 2.0, query_t0 + 1.0))
    except RuntimeError:
        return None
    skip = int(round(2.0 * TARGET_SR))
    if warm.size <= skip + 100 or cold.size < 100:
        return None
    warm = warm[skip:]
    n = min(cold.size, warm.size)
    cold = cold[:n]
    warm = warm[:n]
    edge = int(0.05 * TARGET_SR)
    later = slice(edge, edge + edge)
    def peak(chunk: np.ndarray) -> float:
        return float(np.max(np.abs(chunk))) if chunk.size else 0.0
    return {
        "cold_first_50ms_peak": round(peak(cold[:edge]), 5),
        "warm_first_50ms_peak": round(peak(warm[:edge]), 5),
        "cold_next_50ms_peak": round(peak(cold[later]), 5),
        "correlation_after_50ms": round(float(np.corrcoef(cold[edge:], warm[edge:])[0, 1]), 4),
    }


def main() -> None:
    catalog = load_catalog()
    spans = [span for span in coverage() if span["session"] not in HOLDOUTS]
    sessions = {}
    for span in spans:
        sid = span["session"]
        folder = find_session(RECORDINGS, sid)
        info = catalog.get(sid, {})
        sessions[sid] = {
            "id": sid,
            "dir": folder,
            "meta": load_session(folder),
            "coverage": (float(span["from_seconds"]), float(span["to_seconds"])),
            "network": info.get("network_or_service") or "unknown",
        }
    pods = []
    ads: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for row in commercials(spans):
        pod = (float(row["start_seconds"]), float(row["end_seconds"]))
        ads[row["session"]].append(pod)
        pods.append({"session": row["session"], "start": pod[0], "end": pod[1]})
    by_pod = {(row["session"], round(row["start"], 3)): row for row in pods}

    afternoon = sessions[AFTERNOON]
    cov0, cov1 = afternoon["coverage"]
    decisions = []
    for line in DECISIONS.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row["session"] in HOLDOUTS:
            raise SystemExit("refusing a sealed holdout")
        if row["session"] == AFTERNOON:
            decisions.append(row)
    decisions.sort(key=lambda row: row["available_at"])

    targets = []
    controls = []
    for row in decisions:
        query_t0 = float(row["query_t0"])
        if not on_block_start(query_t0, cov0):
            continue
        if row["same_session"] or row["ref_session"] is None:
            continue
        if int(row["score"]) < COUNT_ABLATION:
            continue
        start = float(row["available_at"])
        end = start + HOP_S
        in_ad = any(a0 <= query_t0 < a1 for a0, a1 in ads[AFTERNOON])
        cover_in_program = not any(a0 <= start < a1 for a0, a1 in ads[AFTERNOON])
        item = {
            "query_t0": query_t0,
            "published_score": int(row["score"]),
            "published_hashes": int(row["n_hashes"]),
            "ref_session": row["ref_session"],
            "ref_start": float(row["ref_start"]),
        }
        if cover_in_program and not in_ad:
            item["role"] = "false_program"
            targets.append(item)
        elif in_ad and int(row["score"]) >= 50 and len(controls) < 6:
            item["role"] = "commercial_control"
            controls.append(item)

    cache: dict = {}
    rows_out = []
    for item in targets + controls:
        ref_key = (item["ref_session"], round(item["ref_start"], 3))
        pod = by_pod.get(ref_key)
        if pod is None:
            rows_out.append({**item, "error": "reference pod not found"})
            continue
        ref_session = sessions[pod["session"]]
        ref_cov0, ref_cov1 = ref_session["coverage"]
        print(f"query {item['query_t0']:.0f} {item['role']} -> {pod['session']} {pod['start']:.1f}", flush=True)
        ref_frames, ref_hash = ref_hashes(ref_session, pod["start"], pod["end"], ref_cov0, ref_cov1, cache)
        query_t0 = item["query_t0"]
        cold_frames, cold_hashes, cold_dts = fingerprint(
            to_11025(read_span(afternoon["dir"], afternoon["meta"], query_t0, min(cov1, query_t0 + HOP_S + TAIL_S))),
            frame_of(query_t0),
        )
        cold_frames, cold_hashes = window_hashes(cold_frames, cold_hashes, cold_dts, query_t0, query_t0 + HOP_S)
        index = build_index([{"id": 0, "frames": ref_frames, "hashes": ref_hash}])
        allow = np.ones(1, dtype=bool)
        cold_hit = best_match(cold_frames, cold_hashes, index, allow)
        agreed = agreeing(cold_frames, cold_hashes, ref_frames, ref_hash, cold_hit["offset"])
        origin = frame_of(query_t0)
        relative = (agreed - origin) * (256 / TARGET_SR) if agreed.size else np.zeros(0)
        record = {
            "role": item["role"],
            "query_t0": query_t0,
            "published_score": item["published_score"],
            "cold_score_against_published_ref": cold_hit["score"],
            "cold_offset": cold_hit["offset"],
            "cold_hashes": int(cold_frames.size),
            "agreeing_hashes": int(agreed.size),
            "agreeing_within_0_5s": int(np.sum(relative < 0.5)) if relative.size else 0,
            "agreeing_median_s": None if relative.size == 0 else round(float(np.median(relative)), 3),
            "ref_session": pod["session"],
            "ref_start": pod["start"],
            "ref_end": pod["end"],
        }
        edge = edge_ratio(afternoon, query_t0) if item["role"] == "false_program" and len([row for row in rows_out if row.get("role") == "false_program"]) < 3 else None
        if edge:
            record.update(edge)
        if cold_hit["offset"] is not None:
            shift = cold_hit["offset"] * 256 / TARGET_SR
            record["aligned_ref_s"] = round(query_t0 + shift, 3)
            record["audio_correlation"] = waveform_correlation(
                afternoon, query_t0, ref_session, query_t0 + shift
            )
        for hops in LEAD_HOPS:
            preroll = hops * 256 / TARGET_SR
            t0 = query_t0 - preroll
            frames, hashes, dts = fingerprint(
                to_11025(read_span(afternoon["dir"], afternoon["meta"], t0, min(cov1, query_t0 + HOP_S + TAIL_S))),
                frame_of(t0),
            )
            frames, hashes = window_hashes(frames, hashes, dts, query_t0, query_t0 + HOP_S)
            hit = best_match(frames, hashes, index, allow)
            record[f"score_with_{hops}_hops_lead"] = hit["score"]
        rows_out.append(record)
        print(
            f"  published {item['published_score']} cold {cold_hit['score']} "
            f"hops {record['score_with_11_hops_lead']}/{record['score_with_43_hops_lead']}/{record['score_with_86_hops_lead']} "
            f"corr {record.get('audio_correlation')}",
            flush=True,
        )

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "summary.json").write_text(json.dumps({"rows": rows_out, "mute_policy": False, "count_changed": False}, indent=2) + "\n", encoding="utf-8")
    if rows_out:
        fieldnames: list[str] = []
        seen: set[str] = set()
        for row in rows_out:
            for key in row:
                if key not in seen:
                    seen.add(key)
                    fieldnames.append(key)
        with (OUT / "per_query.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, restval="")
            writer.writeheader()
            writer.writerows(rows_out)
    print(json.dumps(rows_out, indent=2))


if __name__ == "__main__":
    main()
