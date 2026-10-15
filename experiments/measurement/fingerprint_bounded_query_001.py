"""FINGERPRINT-BOUNDED-QUERY-001. Not a mute.

Each decision fingerprints only the five-second query plus the two seconds
already received before it. No sample after the query is read. The published
reference library, counts, gold, and holdouts stay as they are.

Gates run in order. A failed causality or known-ad gate stops the ledger.
"""

from __future__ import annotations

import json
import subprocess
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
    HOP,
    TARGET_SR,
    allow_mask,
    best_match,
    build_index,
    fingerprint,
    frame_of,
    to_11025,
    window_hashes,
)
from experiments.universal_v1.replay import (  # noqa: E402
    COUNT_ABLATION,
    COUNT_V1,
    REDZONE,
    STREAM_HOP_S,
    actions_for,
    build_refs,
    score_group,
)
from hush.audio import find_session, load_session  # noqa: E402

OUT = REPO / "docs/ohush/research/FINGERPRINT_BOUNDED_QUERY_001"
DECISIONS = REPO / "docs/ohush/research/UNIVERSAL_V1/decisions.jsonl"
HOLDOUTS = {"hush_20260917_205513", "hush_20260920_200635"}
LEAD_S = 2.0
QUERY_S = 5.0
FUTURE_S = 8.0
BLOCK_S = 90.0
TAIL_S = 2.0
HOP_LEAD_S = 86 * HOP / TARGET_SR
AFTERNOON = "hush_20261011_135700"
FALSE_QUERIES = (2700.0, 2790.0, 2880.0, 3960.0, 4050.0, 4140.0, 4230.0, 4320.0, 4500.0, 4590.0, 4680.0, 4770.0, 4860.0)
CONTROLS = (
    ("hush_20261008_205100", 145.0, 272, "hush_20260924_220624", 234.244),
    ("hush_20261008_205100", 150.0, 223, "hush_20260924_220624", 234.244),
    ("hush_20261008_205100", 155.0, 260, "hush_20260924_220624", 234.244),
    ("hush_20261008_205100", 160.0, 242, "hush_20260924_220624", 234.244),
    ("hush_20261012_204200", 5085.0, 208, "hush_20260914_212529", 6852.564),
)


def pairs(frames: np.ndarray, hashes: np.ndarray) -> set[tuple[int, int]]:
    if frames.size == 0:
        return set()
    return set(zip(frames.astype(int).tolist(), hashes.astype(int).tolist()))


def jaccard(left: set, right: set) -> float | None:
    union = left | right
    if not union:
        return None
    return round(len(left & right) / len(union), 4)


def resampler_delay_s() -> float:
    impulse = np.zeros((48000, 2), dtype=np.float64)
    impulse[24000, :] = 1.0
    output = to_11025(impulse)
    expected = 24000 * 147 / 640
    delay = float(np.argmax(np.abs(output)) - expected) / TARGET_SR
    return round(delay, 6)


def read_audio(bag: dict, start: float, end: float) -> np.ndarray:
    cov0, cov1 = bag["coverage"]
    start = max(cov0, start)
    end = min(cov1, end)
    return read_span(bag["dir"], bag["meta"], start, end)


def query_hashes(bag: dict, t0: float, lead_s: float, end: float | None = None) -> tuple[np.ndarray, np.ndarray, float, float]:
    """Fingerprint audio that ends at the query. Returns hashes inside the query."""
    cov0, _cov1 = bag["coverage"]
    origin = max(cov0, t0 - lead_s)
    stop = t0 + QUERY_S if end is None else end
    audio = read_audio(bag, origin, stop)
    started = time.perf_counter()
    frames, hashes, dts = fingerprint(to_11025(audio), frame_of(origin))
    kept_f, kept_h = window_hashes(frames, hashes, dts, t0, t0 + QUERY_S)
    return kept_f, kept_h, time.perf_counter() - started, origin


def cold_blocks(bag: dict, t0: float, t1: float, cache: dict) -> dict:
    cov0, cov1 = bag["coverage"]
    frames, hashes, dts = [], [], []
    cursor = cov0
    while cursor < t1 - 1e-6 and cursor < cov1 - 0.5:
        take = min(BLOCK_S, cov1 - cursor)
        block_end = cursor + take
        if block_end > t0 - 1e-6 and cursor < t1:
            key = (bag["id"], round(cursor, 3))
            if key not in cache:
                audio = read_audio(bag, cursor, min(cov1, block_end + TAIL_S))
                cache[key] = fingerprint(to_11025(audio), frame_of(cursor))
            block_frames, block_hashes, block_dts = cache[key]
            keep = block_frames < frame_of(block_end)
            frames.append(block_frames[keep])
            hashes.append(block_hashes[keep])
            dts.append(block_dts[keep])
        cursor += take
    return {
        "frames": np.concatenate(frames) if frames else np.zeros(0, np.int32),
        "hashes": np.concatenate(hashes) if hashes else np.zeros(0, np.int32),
        "dts": np.concatenate(dts) if dts else np.zeros(0, np.int16),
    }


def pod_score(query_bag, ref_bag, t0: float, pod: dict, cache: dict, lead_s: float) -> dict:
    qf, qh, elapsed, origin = query_hashes(query_bag, t0, lead_s)
    ref = cold_blocks(ref_bag, pod["start"], pod["end"], cache)
    rf, rh = window_hashes(ref["frames"], ref["hashes"], ref["dts"], pod["start"], pod["end"])
    index = build_index([{"id": 0, "frames": rf, "hashes": rh}])
    allow = np.ones(1, dtype=bool)
    hit = best_match(qf, qh, index, allow)
    return {
        "score": int(hit["score"]),
        "n_hashes": int(hit["n_hashes"]),
        "process_s": round(elapsed, 4),
        "lead_clamped": origin > t0 - lead_s + 1e-6,
        "origin": round(origin, 4),
    }


def find_pod(pods: list[dict], start: float) -> dict:
    return min(pods, key=lambda pod: abs(pod["start"] - start))


def causality(bag: dict, t0: float) -> dict:
    origin = max(bag["coverage"][0], t0 - LEAD_S)
    short_f, short_h, _elapsed, _origin = query_hashes(bag, t0, LEAD_S)
    long_audio = read_audio(bag, origin, min(bag["coverage"][1], t0 + QUERY_S + FUTURE_S))
    short_audio = read_audio(bag, origin, t0 + QUERY_S)
    prefix = long_audio[: short_audio.shape[0]]
    same_prefix = bool(np.array_equal(prefix, short_audio))
    long_frames, long_hashes, long_dts = fingerprint(to_11025(long_audio), frame_of(origin))
    long_f, long_h = window_hashes(long_frames, long_hashes, long_dts, t0, t0 + QUERY_S)
    noise = short_audio.copy()
    extra = np.random.default_rng(1).normal(0, 0.01, size=(int(FUTURE_S * 48000), short_audio.shape[1])).astype(np.float32)
    leaked = np.concatenate([noise, extra], axis=0)
    leak_frames, leak_hashes, leak_dts = fingerprint(to_11025(leaked), frame_of(origin))
    leak_f, leak_h = window_hashes(leak_frames, leak_hashes, leak_dts, t0, t0 + QUERY_S)
    short_set = pairs(short_f, short_h)
    return {
        "query_t0": t0,
        "bounded_equals_prefix_of_longer_read": same_prefix,
        "bounded_hashes": len(short_set),
        "jaccard_against_8s_future": jaccard(short_set, pairs(long_f, long_h)),
        "jaccard_against_8s_noise": jaccard(short_set, pairs(leak_f, leak_h)),
        "future_changes_the_hash": short_set != pairs(long_f, long_h) or short_set != pairs(leak_f, leak_h),
    }


def fingerprint_cold(sessions: dict) -> tuple[dict, list[dict], float]:
    landmarks = {}
    holes = []
    missing = 0.0
    for sid, bag in sessions.items():
        cov0, cov1 = bag["coverage"]
        frames_all, hashes_all, dts_all = [], [], []
        cursor = cov0
        while cursor < cov1 - 0.5:
            take = min(BLOCK_S, cov1 - cursor)
            try:
                audio = read_audio(bag, cursor, min(cov1, cursor + take + TAIL_S))
            except RuntimeError:
                hole = min(5.0, cov1 - cursor)
                holes.append({"session": sid, "start": cursor, "end": cursor + hole})
                missing += hole
                cursor += 5.0
                continue
            block_frames, block_hashes, block_dts = fingerprint(to_11025(audio), frame_of(cursor))
            keep = block_frames < frame_of(cursor + take)
            frames_all.append(block_frames[keep])
            hashes_all.append(block_hashes[keep])
            dts_all.append(block_dts[keep])
            cursor += take
        landmarks[sid] = {
            "frames": np.concatenate(frames_all) if frames_all else np.zeros(0, np.int32),
            "hashes": np.concatenate(hashes_all) if hashes_all else np.zeros(0, np.int32),
            "dts": np.concatenate(dts_all) if dts_all else np.zeros(0, np.int16),
        }
        print(f"  cold reference {sid}", flush=True)
    return landmarks, holes, missing


def score_population(name: str, sessions, pods, holes, rows, count: int) -> dict:
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["session"]].append(row)
    actions = {sid: actions_for(bag, grouped.get(sid, []), count) for sid, bag in sessions.items()}
    group = score_group(name, sessions, pods, holes, actions, count)
    heard = group["commercial_seconds_heard"]
    ad_seconds = round(sum(row["ad_seconds"] for row in group["sessions"]), 1)
    return {
        "commercial_seconds_covered": round(ad_seconds - heard, 1),
        "program_seconds_covered": group["program_seconds_covered"],
        "false_cover_incidents": group["false_cover_incidents"],
        "worst_continuous_program_interruption_s": group["worst_continuous_program_interruption_s"],
    }


def main() -> None:
    sys.stdout.reconfigure(line_buffering=True)
    delay_s = resampler_delay_s()
    print("resampler_delay_s", delay_s, flush=True)
    catalog = load_catalog()
    spans = coverage()
    sessions = {}
    pods_by = defaultdict(list)
    for span in spans:
        sid = span["session"]
        if sid in HOLDOUTS:
            raise SystemExit("refusing a sealed holdout")
        folder = find_session(REPO / "recordings", sid)
        info = catalog.get(sid, {})
        sessions[sid] = {
            "id": sid,
            "dir": folder,
            "meta": load_session(folder),
            "coverage": (float(span["from_seconds"]), float(span["to_seconds"])),
            "network": info.get("network_or_service") or "unknown",
            "content": info.get("content_type") or "",
        }
    pods = []
    for index, row in enumerate(commercials(spans)):
        pod = {
            "id": index,
            "session": row["session"],
            "start": float(row["start_seconds"]),
            "end": float(row["end_seconds"]),
            "network": sessions[row["session"]]["network"],
            "content": sessions[row["session"]]["content"],
        }
        pods.append(pod)
        pods_by[row["session"]].append(pod)
    afternoon = sessions[AFTERNOON]
    causal_rows = [
        causality(afternoon, 2790.0),
        causality(afternoon, 2810.0),
        causality(sessions["hush_20261008_205100"], 145.0),
    ]
    for row in causal_rows:
        print("causal", json.dumps(row), flush=True)
    causal_pass = all(row["bounded_equals_prefix_of_longer_read"] for row in causal_rows) and any(
        row["future_changes_the_hash"] for row in causal_rows
    )
    cache = {}
    controls = []
    for session, t0, published, ref_session, ref_start in CONTROLS:
        pod = find_pod(pods_by[ref_session], ref_start)
        hit = pod_score(sessions[session], sessions[ref_session], t0, pod, cache, LEAD_S)
        controls.append({"session": session, "query_t0": t0, "published_score": published, "ref_session": ref_session, **hit})
        print("control", controls[-1], flush=True)
    control_pass = all(row["score"] >= COUNT_V1 for row in controls)
    published = {}
    for line in DECISIONS.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row["session"] == AFTERNOON and float(row["query_t0"]) in FALSE_QUERIES:
            published[float(row["query_t0"])] = row
    collisions = []
    collision_pass = False
    hop_controls = []
    if causal_pass and not control_pass:
        for session, t0, published_score, ref_session, ref_start in CONTROLS:
            pod = find_pod(pods_by[ref_session], ref_start)
            hit = pod_score(sessions[session], sessions[ref_session], t0, pod, cache, HOP_LEAD_S)
            hop_controls.append({"session": session, "query_t0": t0, "published_score": published_score, **hit, "lead_s": round(HOP_LEAD_S, 6)})
            print("hop_control", hop_controls[-1], flush=True)
    ledger = None
    if causal_pass and control_pass:
        print("fingerprinting cold references", flush=True)
        landmarks, holes, missing = fingerprint_cold(sessions)
        refs, index = build_refs(pods, landmarks)
        by_ref = defaultdict(list)
        for ref in refs:
            by_ref[ref["session"]].append(ref)
        order = sorted(sessions)
        earlier = [ref["id"] for name in order if name < AFTERNOON for ref in by_ref[name]]
        allow_afternoon = allow_mask(len(refs), earlier)
        for t0 in FALSE_QUERIES:
            qf, qh, elapsed, origin = query_hashes(afternoon, t0, LEAD_S)
            hit = best_match(qf, qh, index, allow_afternoon)
            ref = None if hit["ref_id"] is None else refs[hit["ref_id"]]
            collisions.append({
                "query_t0": t0,
                "published_score": int(published[t0]["score"]),
                "score": int(hit["score"]),
                "ref_session": None if ref is None else ref["session"],
                "ref_start": None if ref is None else round(float(ref["start"]), 3),
                "process_s": round(elapsed, 4),
                "lead_clamped": origin > t0 - LEAD_S + 1e-6,
            })
            print("collision", collisions[-1], flush=True)
        collision_pass = all(row["score"] < COUNT_ABLATION for row in collisions)
    if causal_pass and control_pass and collision_pass:
        rows = []
        for sid in order:
            cov0, cov1 = sessions[sid]["coverage"]
            earlier = [ref["id"] for name in order if name < sid for ref in by_ref[name]]
            allow = allow_mask(len(refs), earlier)
            t = cov0 + STREAM_HOP_S
            while t + STREAM_HOP_S <= cov1:
                try:
                    qf, qh, elapsed, _origin = query_hashes(sessions[sid], t, LEAD_S)
                except RuntimeError:
                    holes.append({"session": sid, "start": t, "end": t + STREAM_HOP_S})
                    t += STREAM_HOP_S
                    continue
                hit = best_match(qf, qh, index, allow)
                ref = None if hit["ref_id"] is None else refs[hit["ref_id"]]
                rows.append({
                    "session": sid,
                    "query_t0": round(t, 3),
                    "query_t1": round(t + QUERY_S, 3),
                    "available_at": round(t + QUERY_S + max(delay_s, 0.0) + elapsed, 4),
                    "score": int(hit["score"]),
                    "n_hashes": int(hit["n_hashes"]),
                    "ref_session": None if ref is None else ref["session"],
                    "ref_start": None if ref is None else round(float(ref["start"]), 3),
                    "same_session": bool(ref is not None and ref["session"] == sid),
                    "process_s": round(elapsed, 4),
                })
                t += STREAM_HOP_S
            print(f"  bounded {sid}", flush=True)
        ledger = {
            count: {pop: score_population(pop, sessions, pods, holes, rows, threshold) for pop in ("football", "redzone", "scripted")}
            for count, threshold in (("count_10", COUNT_ABLATION), ("count_200", COUNT_V1))
        }
        ledger["holes_s"] = round(sum(row["end"] - row["start"] for row in holes), 1)
        ledger["cold_reference_holes_s"] = round(missing, 1)
    payload = {
        "system": "fingerprint_bounded_query_001",
        "mute_policy": False,
        "playback": "PLAY",
        "lead_s": LEAD_S,
        "query_s": QUERY_S,
        "buffer_ends_at_query_end": True,
        "resampler_delay_s": delay_s,
        "gates": {
            "causality": causal_pass,
            "known_ads": control_pass,
            "block_artifact": collision_pass,
            "ledger_run": ledger is not None,
        },
        "causality": causal_rows,
        "controls": controls,
        "collisions": collisions,
        "hop_aligned_controls_if_gate_2_failed": hop_controls,
        "ledger": ledger,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()
    decisions_sha = subprocess.check_output(["shasum", "-a", "256", str(DECISIONS)], text=True).split()[0]
    (OUT / "receipts.json").write_text(
        json.dumps(
            {
                "system": "fingerprint_bounded_query_001",
                "git_head": head,
                "decisions_sha256": decisions_sha,
                "published_reader_modified": False,
                "thresholds_modified": False,
                "gold_modified": False,
                "holdouts_opened": False,
                "playback": "PLAY",
                "stopped_after": "causality" if not causal_pass else "known_ads" if not control_pass else "block_artifact" if not collision_pass else "ledger",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload["gates"], indent=2))


if __name__ == "__main__":
    main()
