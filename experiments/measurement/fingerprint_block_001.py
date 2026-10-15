"""FINGERPRINT-BLOCK-001, part 1. Not a mute.

The published reader starts each 90-second block with no audio before the cut.
This compares that read with a 45-second grid shift, a hop-aligned lead, and
one uninterrupted read of the same window. It also replaces audio after a
query's decision time to see whether the fingerprint already used it.

Count 10 is not changed. Block-start queries are not discarded.
"""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
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
from experiments.universal_v1.replay import COUNT_ABLATION, COUNT_V1  # noqa: E402
from hush.audio import RAW_SR, find_session, load_session  # noqa: E402

DECISIONS = REPO / "docs/ohush/research/UNIVERSAL_V1/decisions.jsonl"
OUT = REPO / "docs/ohush/research/FINGERPRINT_BLOCK_001"
RECORDINGS = REPO / "recordings"
HOLDOUTS = ("hush_20260917_205513", "hush_20260920_200635")
AFTERNOON = "hush_20261011_135700"
BLOCK_S = 90.0
QUERY_S = 5.0
TAIL_S = 2.0
HOP = 256
LEAD_HOPS = 86
LONG_HOPS = 1938


def hop_seconds(hops: int) -> float:
    return hops * HOP / TARGET_SR


def on_block(instant: float, origin: float, shift: float = 0.0) -> bool:
    relative = instant - (origin + shift)
    if relative < -1e-6:
        return False
    remainder = relative % BLOCK_S
    return remainder < 1e-3 or BLOCK_S - remainder < 1e-3


def block_of(instant: float, origin: float, shift: float = 0.0) -> float:
    base = origin + shift
    return base + np.floor((instant - base) / BLOCK_S + 1e-9) * BLOCK_S


def as_set(frames: np.ndarray, hashes: np.ndarray) -> set[tuple[int, int]]:
    return set(zip(frames.astype(int).tolist(), hashes.astype(int).tolist()))


def jaccard(left: set, right: set) -> float | None:
    if not left and not right:
        return None
    return round(len(left & right) / len(left | right), 4)


def extract(session: dict, read0: float, read1: float, keep0: float, keep1: float, replace_after: float | None = None) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    audio = read_span(session["dir"], session["meta"], read0, read1)
    if replace_after is not None:
        keep = int(round((replace_after - read0) * RAW_SR))
        keep = min(max(keep, 0), audio.shape[0])
        rest = audio[keep:]
        if rest.size:
            rms = float(np.sqrt(np.mean(np.square(rest), dtype=np.float64)))
            rng = np.random.default_rng(1)
            audio = np.array(audio, copy=True)
            audio[keep:] = rng.normal(0.0, max(rms, 1e-4), size=rest.shape)
    frames, hashes, dts = fingerprint(to_11025(audio), frame_of(read0))
    f0, f1 = frame_of(keep0), frame_of(keep1)
    keep = (frames >= f0) & ((frames + dts.astype(np.int32)) < f1)
    return frames[keep], hashes[keep], dts[keep]


def ref_window(session: dict, pod0: float, pod1: float, cov0: float, cov1: float, cache: dict) -> tuple[np.ndarray, np.ndarray]:
    frames, hashes, dts = [], [], []
    cursor = block_of(pod0, cov0)
    while cursor < pod1 - 1e-6:
        take = min(BLOCK_S, cov1 - cursor)
        key = (session["id"], round(cursor, 3))
        if key not in cache:
            cache[key] = extract(session, cursor, min(cov1, cursor + take + TAIL_S), cursor, cursor + take)
            print(f"  ref {session['id']} {cursor:.0f}", flush=True)
        block_frames, block_hashes, block_dts = cache[key]
        frames.append(block_frames)
        hashes.append(block_hashes)
        dts.append(block_dts)
        cursor += BLOCK_S
    if not frames:
        return np.zeros(0, np.int32), np.zeros(0, np.int32)
    return window_hashes(np.concatenate(frames), np.concatenate(hashes), np.concatenate(dts), pod0, pod1)


def score_against(frames: np.ndarray, hashes: np.ndarray, ref_frames: np.ndarray, ref_hashes: np.ndarray) -> dict:
    index = build_index([{"id": 0, "frames": ref_frames, "hashes": ref_hashes}])
    return best_match(frames, hashes, index, np.ones(1, dtype=bool))


def agreeing(query_frames, query_hashes, ref_frames, ref_hashes, offset) -> list[int]:
    if offset is None or query_frames.size == 0:
        return []
    buckets: dict[int, list[int]] = defaultdict(list)
    for frame, hash_ in zip(ref_frames.tolist(), ref_hashes.tolist()):
        buckets[int(hash_)].append(int(frame))
    chosen = []
    for frame, hash_ in zip(query_frames.tolist(), query_hashes.tolist()):
        hits = buckets.get(int(hash_))
        if hits and any(abs((ref_frame - int(frame)) - offset) <= MATCH_WIN for ref_frame in hits):
            chosen.append(int(frame))
    return chosen


def waveform_correlation(query_session, query_t0, ref_session, ref_t0) -> float | None:
    cov0, cov1 = ref_session["coverage"]
    if ref_t0 < cov0 or ref_t0 + QUERY_S > cov1:
        return None
    left = to_11025(read_span(query_session["dir"], query_session["meta"], query_t0, query_t0 + QUERY_S))
    right = to_11025(read_span(ref_session["dir"], ref_session["meta"], ref_t0, ref_t0 + QUERY_S))
    n = min(left.size, right.size)
    left = left[:n] - np.mean(left[:n])
    right = right[:n] - np.mean(right[:n])
    denom = float(np.linalg.norm(left) * np.linalg.norm(right))
    if denom == 0:
        return None
    return round(float(np.dot(left, right) / denom), 4)


def causality(session: dict, query_t0: float, cov0: float) -> dict:
    """Replace audio after the query and see whether its landmarks change."""
    block = block_of(query_t0, cov0)
    read1 = min(session["coverage"][1], block + BLOCK_S + TAIL_S)
    full_frames, full_hashes, _dts = extract(session, block, read1, query_t0, query_t0 + QUERY_S)
    full = as_set(full_frames, full_hashes)
    short_frames, short_hashes, _dts = extract(session, block, min(read1, query_t0 + QUERY_S + TAIL_S), query_t0, query_t0 + QUERY_S)
    truncation = []
    for extra in (2.0, 5.0):
        frames, hashes, _dts = extract(session, block, min(read1, query_t0 + QUERY_S + extra), query_t0, query_t0 + QUERY_S)
        got = as_set(frames, hashes)
        truncation.append(
            {
                "buffer_ends_after_query_s": extra,
                "hashes": len(got),
                "jaccard_with_full_buffer": jaccard(full, got),
                "identical_to_full_buffer": got == full,
            }
        )
    rows = []
    for lag in (0.0, 0.5, 1.0, 1.5, 2.0, 3.0):
        frames, hashes, _dts = extract(
            session,
            block,
            read1,
            query_t0,
            query_t0 + QUERY_S,
            replace_after=query_t0 + QUERY_S + lag,
        )
        got = as_set(frames, hashes)
        rows.append(
            {
                "real_audio_kept_after_query_s": lag,
                "hashes": len(got),
                "jaccard_with_full_buffer": jaccard(full, got),
                "identical_to_full_buffer": got == full,
            }
        )
    return {
        "query_t0": query_t0,
        "block_start": block,
        "buffer_end": read1,
        "full_buffer_hashes": len(full),
        "buffer_cut_2s_after_query_identical": as_set(short_frames, short_hashes) == full,
        "truncation": truncation,
        "noise_note": "Replacing the rest of the block with noise holds the backward threshold up. The truncation rows are the latency test.",
        "lags": rows,
    }


def main() -> None:
    catalog = load_catalog()
    spans = [span for span in coverage() if span["session"] not in HOLDOUTS]
    sessions = {}
    for span in spans:
        sid = span["session"]
        if sid in HOLDOUTS:
            raise SystemExit("refusing a sealed holdout")
        folder = find_session(RECORDINGS, sid)
        info = catalog.get(sid, {})
        sessions[sid] = {
            "id": sid,
            "dir": folder,
            "meta": load_session(folder),
            "coverage": (float(span["from_seconds"]), float(span["to_seconds"])),
            "network": info.get("network_or_service") or "unknown",
            "content": info.get("content_type") or "",
        }
    pods = {
        (row["session"], round(float(row["start_seconds"]), 3)): (
            float(row["start_seconds"]),
            float(row["end_seconds"]),
        )
        for row in commercials(spans)
    }
    afternoon = sessions[AFTERNOON]
    cov0, cov1 = afternoon["coverage"]
    targets = []
    for line in DECISIONS.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row["session"] != AFTERNOON or row["same_session"] or row["ref_session"] is None:
            continue
        query_t0 = float(row["query_t0"])
        if not on_block(query_t0, cov0) or int(row["score"]) < COUNT_ABLATION:
            continue
        start = float(row["available_at"])
        in_program = not any(a0 <= start < a1 for a0, a1 in (pods[key] for key in pods if key[0] == AFTERNOON))
        query_in_ad = any(a0 <= query_t0 < a1 for a0, a1 in (pods[key] for key in pods if key[0] == AFTERNOON))
        if in_program and not query_in_ad:
            targets.append(row)
    print(f"targets {len(targets)}", flush=True)
    cache: dict = {}
    per_query = []
    provenance = []
    for row in targets:
        query_t0 = float(row["query_t0"])
        pod = pods[(row["ref_session"], round(float(row["ref_start"]), 3))]
        ref_session = sessions[row["ref_session"]]
        ref_frames, ref_hashes = ref_window(ref_session, pod[0], pod[1], *ref_session["coverage"], cache)
        cold_f, cold_h, _dts = extract(afternoon, query_t0, min(cov1, query_t0 + QUERY_S + TAIL_S), query_t0, query_t0 + QUERY_S)
        lead = hop_seconds(LEAD_HOPS)
        long = hop_seconds(LONG_HOPS)
        lead_f, lead_h, _dts = extract(afternoon, query_t0 - lead, min(cov1, query_t0 + QUERY_S + TAIL_S), query_t0, query_t0 + QUERY_S)
        long_f, long_h, _dts = extract(afternoon, query_t0 - long, min(cov1, query_t0 + QUERY_S + TAIL_S), query_t0, query_t0 + QUERY_S)
        shifted_origin = block_of(query_t0, cov0, 45.0)
        shift_f, shift_h, _dts = extract(
            afternoon,
            shifted_origin,
            min(cov1, shifted_origin + BLOCK_S + TAIL_S),
            query_t0,
            query_t0 + QUERY_S,
        )
        cold_hit = score_against(cold_f, cold_h, ref_frames, ref_hashes)
        lead_hit = score_against(lead_f, lead_h, ref_frames, ref_hashes)
        long_hit = score_against(long_f, long_h, ref_frames, ref_hashes)
        shift_hit = score_against(shift_f, shift_h, ref_frames, ref_hashes)
        cold_set, lead_set, long_set, shift_set = as_set(cold_f, cold_h), as_set(lead_f, lead_h), as_set(long_f, long_h), as_set(shift_f, shift_h)
        agreed = agreeing(cold_f, cold_h, ref_frames, ref_hashes, cold_hit["offset"])
        origin = frame_of(query_t0)
        if cold_hit["offset"] is not None:
            aligned = query_t0 + cold_hit["offset"] * HOP / TARGET_SR
            correlation = waveform_correlation(afternoon, query_t0, ref_session, aligned)
        else:
            aligned = None
            correlation = None
        per_query.append(
            {
                "role": "published_block_start",
                "query_t0": query_t0,
                "published_score": int(row["score"]),
                "cold_score": cold_hit["score"],
                "lead_2s_score": lead_hit["score"],
                "lead_45s_score": long_hit["score"],
                "shift_45s_score": shift_hit["score"],
                "cold_above_10": cold_hit["score"] >= COUNT_ABLATION,
                "shift_above_10": shift_hit["score"] >= COUNT_ABLATION,
                "lead_above_10": lead_hit["score"] >= COUNT_ABLATION,
                "long_above_10": long_hit["score"] >= COUNT_ABLATION,
                "jaccard_cold_long": jaccard(cold_set, long_set),
                "jaccard_lead_long": jaccard(lead_set, long_set),
                "jaccard_shift_long": jaccard(shift_set, long_set),
                "cold_hashes": len(cold_set),
                "long_hashes": len(long_set),
                "ref_session": row["ref_session"],
                "ref_start": float(row["ref_start"]),
                "aligned_ref_s": None if aligned is None else round(aligned, 3),
                "audio_correlation": correlation,
                "agreeing_hashes": len(agreed),
                "agreeing_median_s": None
                if not agreed
                else round(float(np.median([(frame - origin) * HOP / TARGET_SR for frame in agreed])), 3),
            }
        )
        for frame in agreed:
            provenance.append(
                {
                    "query_t0": query_t0,
                    "seconds_into_query": round((frame - origin) * HOP / TARGET_SR, 4),
                    "ref_session": row["ref_session"],
                    "ref_s": None if cold_hit["offset"] is None else round((frame + cold_hit["offset"]) * HOP / TARGET_SR, 4),
                    "offset_frames": cold_hit["offset"],
                }
            )
        moved_t0 = query_t0 + 45.0
        if moved_t0 + QUERY_S <= cov1:
            moved_f, moved_h, _dts = extract(
                afternoon, moved_t0, min(cov1, moved_t0 + QUERY_S + TAIL_S), moved_t0, moved_t0 + QUERY_S
            )
            moved_hit = score_against(moved_f, moved_h, ref_frames, ref_hashes)
            per_query.append(
                {
                    "role": "shifted_grid_new_block_start",
                    "query_t0": moved_t0,
                    "published_score": "",
                    "cold_score": moved_hit["score"],
                    "lead_2s_score": "",
                    "lead_45s_score": "",
                    "shift_45s_score": "",
                    "cold_above_10": moved_hit["score"] >= COUNT_ABLATION,
                    "shift_above_10": "",
                    "lead_above_10": "",
                    "long_above_10": "",
                    "jaccard_cold_long": "",
                    "jaccard_lead_long": "",
                    "jaccard_shift_long": "",
                    "cold_hashes": int(moved_f.size),
                    "long_hashes": "",
                    "ref_session": row["ref_session"],
                    "ref_start": float(row["ref_start"]),
                    "aligned_ref_s": "",
                    "audio_correlation": "",
                    "agreeing_hashes": "",
                    "agreeing_median_s": "",
                }
            )
        print(
            f"{query_t0:.0f} published {row['score']} cold {cold_hit['score']} "
            f"lead {lead_hit['score']} long {long_hit['score']} shift {shift_hit['score']} "
            f"jaccard lead/long {jaccard(lead_set, long_set)} corr {correlation}",
            flush=True,
        )

    causal = {
        "count_10": COUNT_ABLATION,
        "count_200": COUNT_V1,
        "thresholds_changed": False,
        "note": "Audio after the query is replaced with noise. Identical means the query landmarks did not use that future audio.",
        "block_start_query": causality(afternoon, float(targets[1]["query_t0"]), cov0),
        "interior_query": causality(afternoon, float(targets[1]["query_t0"]) + 20.0, cov0),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "per_query.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(per_query[0].keys()))
        writer.writeheader()
        writer.writerows(per_query)
    with (OUT / "landmark_provenance.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(provenance[0].keys()))
        writer.writeheader()
        writer.writerows(provenance)
    (OUT / "causality_check.json").write_text(json.dumps(causal, indent=2) + "\n", encoding="utf-8")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO).decode().strip()
    receipts = {
        "git_head": head,
        "decisions_sha256": hashlib.sha256(DECISIONS.read_bytes()).hexdigest(),
        "holdouts_opened": False,
        "thresholds_changed": False,
        "extractor_modified": False,
        "block_start_queries": len(targets),
    }
    (OUT / "receipts.json").write_text(json.dumps(receipts, indent=2) + "\n", encoding="utf-8")
    published = [row for row in per_query if row["role"] == "published_block_start"]
    moved = [row for row in per_query if row["role"] == "shifted_grid_new_block_start"]
    print(
        json.dumps(
            {
                "old_still_above_10_when_shifted": sum(1 for row in published if row["shift_above_10"]),
                "old_still_above_10_with_2s_lead": sum(1 for row in published if row["lead_above_10"]),
                "old_still_above_10_with_45s_lead": sum(1 for row in published if row["long_above_10"]),
                "new_block_starts_above_10": sum(1 for row in moved if row["cold_above_10"]),
                "median_jaccard_lead_long": float(np.median([row["jaccard_lead_long"] for row in published])),
                "causal_block": causal["block_start_query"]["lags"],
                "causal_interior": causal["interior_query"]["lags"],
                "tail_irrelevant_block": causal["block_start_query"]["buffer_cut_2s_after_query_identical"],
                "tail_irrelevant_interior": causal["interior_query"]["buffer_cut_2s_after_query_identical"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
