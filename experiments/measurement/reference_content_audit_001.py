"""REFERENCE-CONTENT-AUDIT-001. Not a mute.

Pairs the audio a fingerprint match points at. Does not rebuild the library,
change a count, or edit gold. Reviewer labels are left empty.
"""

from __future__ import annotations

import csv
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "experiments/broadcast_intelligence/third_party/audfprint"))
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))

from experiments.broadcast_intelligence.batch1 import commercials, coverage, load_catalog, read_span  # noqa: E402
from experiments.broadcast_intelligence.known_ad_fingerprint import (  # noqa: E402
    HOP,
    TARGET_SR,
    best_match,
    build_index,
    fingerprint,
    frame_of,
    to_11025,
    window_hashes,
)
from hush.audio import find_session, load_session  # noqa: E402

OUT = REPO / "docs/ohush/research/REFERENCE_CONTENT_AUDIT_001"
CLIPS = OUT / "clips"
DECISIONS = REPO / "docs/ohush/research/UNIVERSAL_V1/decisions.jsonl"
TOP5_CSV = REPO / "docs/ohush/research/POD_REMOVAL_001/top_5_changed_queries.csv"
INCIDENTS = REPO / "docs/ohush/research/VOICE_ERROR_RECEIPT_002/queries.jsonl"
SPEECH = REPO / "docs/ohush/research/UNIVERSAL_V4_SPEECH_001"
HOLDOUTS = {"hush_20260917_205513", "hush_20260920_200635"}
BLOCK_S = 90.0
TAIL_S = 2.0
QUERY_S = 5.0
HOP_S = HOP / TARGET_SR
LAG_S = 2.0
SR = 48000

TOP5 = (
    ("hush_20260913_210542", 9680.140),
    ("hush_20260909_213047", 2514.392),
    ("hush_20260909_213047", 1074.332),
    ("hush_20260909_213047", 6074.159),
    ("hush_20260924_220624", 3496.442),
)


def near(left: float, right: float, tol: float = 0.02) -> bool:
    return abs(float(left) - float(right)) < tol


def pearson(left: np.ndarray, right: np.ndarray) -> float | None:
    n = min(left.size, right.size)
    if n < 16:
        return None
    a = left[:n].astype(np.float64)
    b = right[:n].astype(np.float64)
    a = a - a.mean()
    b = b - b.mean()
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0:
        return None
    return round(float(np.dot(a, b) / denom), 4)


def channel(audio: np.ndarray, index: int) -> np.ndarray:
    return resample_poly(audio[:, index].astype(np.float64), 147, 640)


def sliding_abs(query: np.ndarray, longer: np.ndarray) -> tuple[float | None, float | None, int | None]:
    q = query.astype(np.float64)
    q = q - q.mean()
    qn = float(np.linalg.norm(q))
    if qn == 0 or longer.size < q.size:
        return None, None, None
    numer = np.correlate(longer.astype(np.float64), q, mode="valid")
    n = q.size
    c1 = np.cumsum(np.insert(longer.astype(np.float64), 0, 0.0))
    c2 = np.cumsum(np.insert(longer.astype(np.float64) ** 2, 0, 0.0))
    total = c1[n:] - c1[:-n]
    energy = c2[n:] - c2[:-n]
    var = np.maximum(energy - (total * total) / n, 0.0)
    denom = qn * np.sqrt(var)
    corr = np.divide(numer, denom, out=np.zeros_like(numer), where=denom > 1e-8)
    peak = int(np.argmax(corr))
    trough = int(np.argmin(corr))
    best = peak if corr[peak] >= abs(float(corr[trough])) else trough
    return round(float(corr[peak]), 4), round(float(corr[trough]), 4), best


def text_between(rows: list[dict], t0: float, t1: float) -> str | None:
    parts = []
    for row in rows:
        if float(row["t1"]) <= t0 or float(row["t0"]) >= t1:
            continue
        text = (row.get("text") or "").strip()
        if text:
            parts.append(text)
    return " ".join(parts) if parts else None


def load_speech() -> dict[str, list[dict]]:
    by = defaultdict(list)
    for path in sorted(SPEECH.glob("chunks*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            by[row["session"]].append(row)
    for rows in by.values():
        rows.sort(key=lambda row: float(row["t0"]))
    return by


def commercial_overlap(pods: list[dict], t0: float, t1: float) -> float:
    total = 0.0
    for pod in pods:
        left = max(t0, pod["start"])
        right = min(t1, pod["end"])
        if right > left:
            total += right - left
    return total


def cold_blocks(bag: dict, t0: float, t1: float, cache: dict) -> dict:
    cov0, cov1 = bag["coverage"]
    frames, hashes, dts = [], [], []
    cursor = cov0
    while cursor < t1 - 1e-6:
        take = min(BLOCK_S, cov1 - cursor)
        block_end = cursor + take
        if block_end > t0 - 1e-6 and cursor < t1:
            key = (bag["id"], round(cursor, 3))
            if key not in cache:
                audio = read_span(bag["dir"], bag["meta"], cursor, min(cov1, block_end + TAIL_S))
                cache[key] = fingerprint(to_11025(audio), frame_of(cursor))
            block_frames, block_hashes, block_dts = cache[key]
            keep = block_frames < frame_of(block_end)
            frames.append(block_frames[keep])
            hashes.append(block_hashes[keep])
            dts.append(block_dts[keep])
        cursor += take
        if cursor >= cov1 - 0.5:
            break
    return {
        "frames": np.concatenate(frames) if frames else np.zeros(0, np.int32),
        "hashes": np.concatenate(hashes) if hashes else np.zeros(0, np.int32),
        "dts": np.concatenate(dts) if dts else np.zeros(0, np.int16),
    }


def match_pod(query_bag, ref_bag, query_t0: float, pod: dict, cache: dict) -> dict:
    query = cold_blocks(query_bag, query_t0, query_t0 + QUERY_S, cache)
    qf, qh = window_hashes(query["frames"], query["hashes"], query["dts"], query_t0, query_t0 + QUERY_S)
    ref = cold_blocks(ref_bag, pod["start"], pod["end"], cache)
    rf, rh = window_hashes(ref["frames"], ref["hashes"], ref["dts"], pod["start"], pod["end"])
    index = build_index([{"id": 0, "frames": rf, "hashes": rh}])
    allow = np.zeros(1, dtype=bool)
    allow[0] = True
    hit = best_match(qf, qh, index, allow)
    aligned = None
    if hit["offset"] is not None:
        aligned = (frame_of(query_t0) + int(hit["offset"])) * HOP_S
    return {
        "score": int(hit["score"]),
        "n_hashes": int(hit["n_hashes"]),
        "offset_frames": None if hit["offset"] is None else int(hit["offset"]),
        "aligned_ref_t0": None if aligned is None else round(aligned, 6),
        "position_in_pod_s": None if aligned is None else round(aligned - pod["start"], 3),
    }


def read_exact(bag: dict, t0: float, t1: float) -> np.ndarray:
    audio = read_span(bag["dir"], bag["meta"], t0, t1)
    want = int(round((t1 - t0) * SR))
    if audio.shape[0] < want:
        audio = np.pad(audio, ((0, want - audio.shape[0]), (0, 0)))
    return audio[:want]


def align_pair(query_bag, ref_bag, query_t0: float, ref_t0: float) -> dict:
    cov0, cov1 = ref_bag["coverage"]
    query = read_exact(query_bag, query_t0, query_t0 + QUERY_S)
    ref = read_exact(ref_bag, ref_t0, min(cov1, ref_t0 + QUERY_S))
    q_mono = to_11025(query)
    r_mono = to_11025(ref)
    nominal = pearson(q_mono, r_mono)
    channels = {}
    for name, q_idx, r_idx, flip in (
        ("left_left", 0, 0, False),
        ("right_right", 1, 1, False),
        ("left_right", 0, 1, False),
        ("right_left", 1, 0, False),
        ("mono_inverted", None, None, True),
    ):
        if name == "mono_inverted":
            channels[name] = pearson(q_mono, -r_mono)
        else:
            channels[name] = pearson(channel(query, q_idx), channel(ref, r_idx))
    pad_t0 = max(cov0, ref_t0 - LAG_S)
    pad_t1 = min(cov1, ref_t0 + QUERY_S + LAG_S)
    pad = read_exact(ref_bag, pad_t0, pad_t1)
    long_mono = to_11025(pad)
    lag_origin = ref_t0 - pad_t0
    positive, negative, index = sliding_abs(q_mono, long_mono)
    lag_s = None if index is None else round(index / TARGET_SR - lag_origin, 4)
    hop_samples = HOP
    within_hop = None
    within_five = None
    if index is not None:
        center = int(round(lag_origin * TARGET_SR))
        for limit, key in ((hop_samples, "within_one_hop"), (5 * hop_samples, "within_five_hops")):
            lo = max(0, center - limit)
            hi = min(long_mono.size - q_mono.size, center + limit)
            piece_pos, piece_neg, piece_i = sliding_abs(q_mono, long_mono[lo : hi + q_mono.size])
            if piece_i is None:
                continue
            chosen = piece_pos if (piece_pos or -1) >= abs(piece_neg or 0) else piece_neg
            row = {"correlation": chosen, "lag_s": round((lo + piece_i) / TARGET_SR - lag_origin, 4)}
            if key == "within_one_hop":
                within_hop = row
            else:
                within_five = row
    slice_best = None
    slice_at = None
    if long_mono.size > q_mono.size:
        width = int(0.5 * TARGET_SR)
        step = int(0.25 * TARGET_SR)
        for start in range(0, q_mono.size - width, step):
            pos, neg, idx = sliding_abs(q_mono[start : start + width], long_mono)
            chosen = pos if (pos or -1) >= abs(neg or 0) else neg
            if chosen is None:
                continue
            if slice_best is None or abs(chosen) > abs(slice_best):
                slice_best = chosen
                slice_at = None if idx is None else round((start / TARGET_SR), 3)
    mid = 0.5 * (query[:, 0] + query[:, 1])
    side = 0.5 * (query[:, 0] - query[:, 1])
    return {
        "nominal_mono_correlation": nominal,
        "channels_at_nominal": channels,
        "best_positive_within_2s": positive,
        "best_negative_within_2s": negative,
        "best_lag_s": lag_s,
        "within_one_hop": within_hop,
        "within_five_hops": within_five,
        "best_half_second_correlation": slice_best,
        "half_second_starts_at_s": slice_at,
        "query_mid_rms": round(float(np.sqrt(np.mean(mid**2))), 5),
        "query_side_rms": round(float(np.sqrt(np.mean(side**2))), 5),
        "query_audio": query,
        "ref_audio": ref,
    }


def relation(row: dict) -> str:
    values = [row["nominal_mono_correlation"], row["best_positive_within_2s"], abs(row["best_negative_within_2s"] or 0)]
    values += [value for value in row["channels_at_nominal"].values() if value is not None]
    best_full = max(values)
    piece = abs(row["best_half_second_correlation"] or 0)
    if best_full >= 0.5:
        return "same_sound"
    if piece >= 0.5:
        return "shared_fragment"
    if best_full < 0.15 and piece < 0.3:
        return "unrelated_sound"
    return "uncertain"


def main() -> None:
    sys.stdout.reconfigure(line_buffering=True)
    if HOLDOUTS & set():
        raise SystemExit("refusing a sealed holdout")
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
        }
    for row in commercials(spans):
        pods_by[row["session"]].append(
            {"start": float(row["start_seconds"]), "end": float(row["end_seconds"])}
        )
    speech = load_speech()
    top_rows = list(csv.DictReader(TOP5_CSV.open(encoding="utf-8")))
    chosen = []

    def add(role: str, session: str, query_t0: float, ref_session: str, ref_start: float, published_score: int) -> None:
        if session in HOLDOUTS or ref_session in HOLDOUTS:
            raise SystemExit("refusing a sealed holdout")
        pod = next(pod for pod in pods_by[ref_session] if near(pod["start"], ref_start))
        for item in chosen:
            if (
                item["session"] == session
                and near(item["query_t0"], query_t0, 0.05)
                and item["ref_session"] == ref_session
                and near(item["ref_start"], pod["start"])
            ):
                item["roles"].append(role)
                return
        chosen.append(
            {
                "roles": [role],
                "session": session,
                "query_t0": float(query_t0),
                "ref_session": ref_session,
                "ref_start": pod["start"],
                "ref_end": pod["end"],
                "published_score": int(published_score),
            }
        )

    for line in DECISIONS.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row["same_session"] or int(row["score"]) < 200:
            continue
        add("count_200", row["session"], row["query_t0"], row["ref_session"], row["ref_start"], row["score"])
    for ref_session, ref_start in TOP5:
        group = [row for row in top_rows if row["old_ref_session"] == ref_session and near(float(row["old_ref_start"]), ref_start)]
        group.sort(key=lambda row: int(row["old_score"]), reverse=True)
        best = group[0]
        add("top5_highest_score", best["session"], best["query_t0"], ref_session, ref_start, int(best["old_score"]))
        positions = sorted(float(row["old_position_in_pod_s"]) for row in group)
        median = positions[len(positions) // 2]
        closest = min(group, key=lambda row: abs(float(row["old_position_in_pod_s"]) - median))
        if abs(float(closest["old_position_in_pod_s"]) - float(best["old_position_in_pod_s"])) > 10:
            add("top5_median_position", closest["session"], closest["query_t0"], ref_session, ref_start, int(closest["old_score"]))
    replacements = [row for row in top_rows if row["still_at_least_10"] == "True"]
    grouped = defaultdict(list)
    for row in replacements:
        grouped[(row["new_ref_session"], round(float(row["new_ref_start"]), 3))].append(row)
    busiest = max(grouped, key=lambda key: len(grouped[key]))
    for row in sorted(grouped[busiest], key=lambda row: int(row["new_score"]), reverse=True)[:3]:
        add("replacement", row["session"], row["query_t0"], row["new_ref_session"], float(row["new_ref_start"]), int(row["new_score"]))
    for line in INCIDENTS.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row["session"] != "hush_20260913_210542":
            continue
        hop = max(row["hops"], key=lambda item: int(item["score"]))
        add("nbc_false_cover", row["session"], hop["query_t0"], hop["ref_session"], hop["ref_start"], int(hop["score"]))

    cache = {}
    rng = np.random.default_rng(20261015)
    CLIPS.mkdir(parents=True, exist_ok=True)
    results = []
    for index, item in enumerate(chosen, start=1):
        print(f"pair {index} {item['roles'][0]} {item['session']} {item['query_t0']}", flush=True)
        query_bag = sessions[item["session"]]
        ref_bag = sessions[item["ref_session"]]
        pod = {"start": item["ref_start"], "end": item["ref_end"]}
        reproduced = match_pod(query_bag, ref_bag, item["query_t0"], pod, cache)
        aligned = reproduced["aligned_ref_t0"]
        if aligned is None:
            aligned = item["ref_start"]
        checked = align_pair(query_bag, ref_bag, item["query_t0"], aligned)
        query_audio = checked.pop("query_audio")
        ref_audio = checked.pop("ref_audio")
        swap = bool(rng.integers(0, 2))
        pair_id = f"p{index:02d}"
        left_name = "query" if not swap else "reference"
        right_name = "reference" if not swap else "query"
        sf.write(CLIPS / f"{pair_id}a.wav", query_audio if not swap else ref_audio, SR)
        sf.write(CLIPS / f"{pair_id}b.wav", ref_audio if not swap else query_audio, SR)
        query_span = commercial_overlap(pods_by[item["session"]], item["query_t0"], item["query_t0"] + QUERY_S)
        ref_span = commercial_overlap(pods_by[item["ref_session"]], aligned, aligned + QUERY_S)
        row = {
            "pair_id": pair_id,
            "roles": item["roles"],
            "query_session": item["session"],
            "query_network": query_bag["network"],
            "query_t0": item["query_t0"],
            "query_t1": round(item["query_t0"] + QUERY_S, 3),
            "published_score": item["published_score"],
            "ref_session": item["ref_session"],
            "ref_network": ref_bag["network"],
            "ref_pod_start": item["ref_start"],
            "ref_pod_end": item["ref_end"],
            "pod_duration_s": round(item["ref_end"] - item["ref_start"], 3),
            **reproduced,
            "inside_reference_pod": item["ref_start"] - 0.05 <= aligned < item["ref_end"] + 0.05,
            "query_seconds_inside_gold_commercial": round(query_span, 3),
            "reference_seconds_inside_gold_commercial": round(ref_span, 3),
            "query_transcript": text_between(speech.get(item["session"], []), item["query_t0"], item["query_t0"] + QUERY_S),
            "reference_transcript": text_between(speech.get(item["ref_session"], []), aligned, aligned + QUERY_S),
            **checked,
            "relation": relation({**checked, "nominal_mono_correlation": checked["nominal_mono_correlation"], "channels_at_nominal": checked["channels_at_nominal"], "best_positive_within_2s": checked["best_positive_within_2s"], "best_negative_within_2s": checked["best_negative_within_2s"], "best_half_second_correlation": checked["best_half_second_correlation"]}),
            "reviewer_label": None,
            "blind": {"a": left_name, "b": right_name, "a_file": f"clips/{pair_id}a.wav", "b_file": f"clips/{pair_id}b.wav"},
        }
        results.append(row)
        print(
            f"  score {row['score']} pos {row['position_in_pod_s']} mono {row['nominal_mono_correlation']} best2 {row['best_positive_within_2s']} lag {row['best_lag_s']}",
            flush=True,
        )

    OUT.mkdir(parents=True, exist_ok=True)
    fields = [
        "pair_id",
        "roles",
        "query_session",
        "query_t0",
        "published_score",
        "reproduced_score",
        "ref_session",
        "ref_pod_start",
        "aligned_ref_t0",
        "position_in_pod_s",
        "nominal_mono_correlation",
        "best_positive_within_2s",
        "best_lag_s",
        "best_half_second_correlation",
        "relation",
        "query_seconds_inside_gold_commercial",
        "reference_seconds_inside_gold_commercial",
    ]
    with (OUT / "matched_pairs.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in results:
            writer.writerow(
                {
                    "pair_id": row["pair_id"],
                    "roles": "|".join(row["roles"]),
                    "query_session": row["query_session"],
                    "query_t0": row["query_t0"],
                    "published_score": row["published_score"],
                    "reproduced_score": row["score"],
                    "ref_session": row["ref_session"],
                    "ref_pod_start": row["ref_pod_start"],
                    "aligned_ref_t0": row["aligned_ref_t0"],
                    "position_in_pod_s": row["position_in_pod_s"],
                    "nominal_mono_correlation": row["nominal_mono_correlation"],
                    "best_positive_within_2s": row["best_positive_within_2s"],
                    "best_lag_s": row["best_lag_s"],
                    "best_half_second_correlation": row["best_half_second_correlation"],
                    "relation": row["relation"],
                    "query_seconds_inside_gold_commercial": row["query_seconds_inside_gold_commercial"],
                    "reference_seconds_inside_gold_commercial": row["reference_seconds_inside_gold_commercial"],
                }
            )
    review_path = OUT / "reference_content_review.jsonl"
    with review_path.open("w", encoding="utf-8") as handle:
        for row in results:
            handle.write(json.dumps(row) + "\n")
    summary = {
        "pairs": len(results),
        "relation_counts": dict(defaultdict(int, {row["relation"]: 0 for row in results})),
        "count_200": [
            {
                "pair_id": row["pair_id"],
                "query_t0": row["query_t0"],
                "published_score": row["published_score"],
                "reproduced_score": row["score"],
                "aligned_ref_t0": row["aligned_ref_t0"],
                "nominal_mono_correlation": row["nominal_mono_correlation"],
                "best_positive_within_2s": row["best_positive_within_2s"],
                "best_lag_s": row["best_lag_s"],
                "best_half_second_correlation": row["best_half_second_correlation"],
                "channels_at_nominal": row["channels_at_nominal"],
                "relation": row["relation"],
            }
            for row in results
            if "count_200" in row["roles"]
        ],
    }
    for row in results:
        summary["relation_counts"][row["relation"]] = summary["relation_counts"].get(row["relation"], 0) + 1
    (OUT / "alignment_checks.json").write_text(json.dumps({"summary": summary, "pairs": results}, indent=2) + "\n", encoding="utf-8")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()
    decisions_sha = subprocess.check_output(["shasum", "-a", "256", str(DECISIONS)], cwd=REPO, text=True).split()[0]
    (OUT / "receipts.json").write_text(
        json.dumps(
            {
                "system": "reference_content_audit_001",
                "git_head": head,
                "decisions_sha256": decisions_sha,
                "library_rebuilt": False,
                "gold_modified": False,
                "thresholds_modified": False,
                "holdouts_opened": False,
                "playback": "PLAY",
                "pairs": len(results),
                "busiest_replacement": {"session": busiest[0], "pod_start": busiest[1], "queries_at_least_10": len(grouped[busiest])},
                "lag_search_s": LAG_S,
                "transcripts": "existing five-second whisper scan, not a new listen",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
