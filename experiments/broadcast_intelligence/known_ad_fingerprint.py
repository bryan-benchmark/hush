"""KNOWN_AD_FINGERPRINT_001.

Spectral-landmark fingerprints from audfprint (Dan Ellis), using the
parameters in searching_for_ads.md except where noted.

Frozen before any match is read:

- Sample rate 11025, mono mix, density 100 peaks/s, match window 2 frames.
- Reference shifts stay at 1. The ad note also builds the reference with
  shifts 4; that multiplier is not applied here. A 50 ms shift is tested
  later as a robustness probe, not as a second matcher.
- Published acceptance count is 200 common landmarks, the ad-search bar.
- Short-query counts 5, 10, 20, 50 and 200 are all scored. The operating
  count is chosen on ESPN only: the smallest count whose 5-second program
  probes produce at most 1 false identification per probed program hour
  under the leave-one-recording library. If none does, the operating count
  stays 200.
- A query of duration W uses only landmarks whose anchor and second peak
  both lie inside the query. Later audio is not hashed into that query.
- Oracle library: other recordings' commercial pods. It can see future games.
- Chronological library: earlier recordings, plus earlier finished pods in
  the same recording. The current pod is never a reference for itself.
- A match to commercial-region audio is a known-content hit, not a named
  creative. Individual ads are not labeled.
- Program probes are 5 seconds long, every 10 seconds, at least 20 seconds
  from a pod. The independent stream uses the same 5-second query every 5
  seconds.
- PASS if, on football other than ESPN and RedZone, the operating count
  under the chronological library recognizes at least one of the DSP-missed
  starts within 5 seconds, keeps program false IDs at or below 1 per probed
  hour, and beats RedZone's false-ID rate on pod openings.
- FAIL if no predeclared count both stays within 1 false ID per probed
  program hour on the evaluation games and recognizes any evaluation pod
  opening within 10 seconds.
- Otherwise INCONCLUSIVE.

No live mute, no gold edit, no holdout.
"""

from __future__ import annotations

import csv
import hashlib
import json
import resource
import sys
import time
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy.signal import resample_poly

import audfprint_analyze as afp

from experiments.broadcast_intelligence.batch1 import commercials, coverage, load_catalog, read_span
from hush.audio import find_session, load_session

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "docs/ohush/research/KNOWN_AD_FINGERPRINT_001"
RECORDINGS = REPO / "recordings"
EPISODES = REPO / "docs/ohush/research/CANDIDATE_VERIFICATION_001/episodes.csv"
DEV = "hush_20260914_212529"
REDZONE = "hush_20260913_150934"
TARGET_SR = 11025
HOP = 256
MATCH_WIN = 2
DENSITY = 100.0
COUNTS = (5, 10, 20, 50, 200)
PUBLISHED_COUNT = 200
DURATIONS = (1, 2, 3, 5, 10)
STREAM_HOP_S = 5.0
PROGRAM_HOP_S = 10.0
FA_BUDGET = 1.0


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def to_11025(audio: np.ndarray) -> np.ndarray:
    mono = 0.5 * (audio[:, 0].astype(np.float64) + audio[:, 1].astype(np.float64))
    return resample_poly(mono, 147, 640).astype(np.float64)


def frame_of(seconds: float) -> int:
    return int(round(seconds * TARGET_SR / HOP))


def fingerprint(samples: np.ndarray, origin_frame: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    analyzer = afp.Analyzer(density=DENSITY)
    if len(samples) < analyzer.n_fft:
        return np.zeros(0, np.int32), np.zeros(0, np.int32), np.zeros(0, np.int16)
    peaks = analyzer.find_peaks(samples, TARGET_SR)
    landmarks = analyzer.peaks2landmarks(peaks)
    if len(landmarks) == 0:
        return np.zeros(0, np.int32), np.zeros(0, np.int32), np.zeros(0, np.int16)
    packed = np.asarray(landmarks, dtype=np.int32)
    hashes = afp.landmarks2hashes(packed)
    frames = origin_frame + hashes[:, 0].astype(np.int32)
    return frames, hashes[:, 1].astype(np.int32), packed[:, 3].astype(np.int16)


def window_hashes(frames, hashes, dts, t0: float, t1: float) -> tuple[np.ndarray, np.ndarray]:
    f0 = frame_of(t0)
    f1 = frame_of(t1)
    keep = (frames >= f0) & ((frames + dts.astype(np.int32)) < f1)
    return frames[keep], hashes[keep]


def build_index(refs: list[dict]) -> dict[int, np.ndarray]:
    grouped: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for ref in refs:
        for frame, hash_ in zip(ref["frames"].tolist(), ref["hashes"].tolist()):
            grouped[int(hash_)].append((int(ref["id"]), int(frame)))
    return {key: np.asarray(value, dtype=np.int32) for key, value in grouped.items()}


def best_match(frames: np.ndarray, hashes: np.ndarray, index: dict[int, np.ndarray], allow: np.ndarray) -> dict:
    hit_rids = []
    hit_offs = []
    for frame, hash_ in zip(frames.tolist(), hashes.tolist()):
        bucket = index.get(int(hash_))
        if bucket is None:
            continue
        chosen = bucket[allow[bucket[:, 0]]]
        if chosen.size == 0:
            continue
        hit_rids.append(chosen[:, 0])
        hit_offs.append(chosen[:, 1] - int(frame))
    empty = {"score": 0, "ref_id": None, "raw": 0, "n_hashes": int(frames.size), "offset": None}
    if not hit_rids:
        return empty
    rids = np.concatenate(hit_rids)
    offs = np.concatenate(hit_offs)
    order = np.argsort(rids, kind="mergesort")
    rids = rids[order]
    offs = offs[order]
    best_score = 0
    best_id = None
    best_raw = 0
    best_offset = None
    start = 0
    kernel = np.ones(2 * MATCH_WIN + 1, dtype=np.int32)
    while start < rids.size:
        stop = start + 1
        while stop < rids.size and rids[stop] == rids[start]:
            stop += 1
        raw = stop - start
        if raw >= 5:
            local = offs[start:stop]
            shifted = local - int(local.min())
            counts = np.bincount(shifted)
            if counts.size == 1:
                score = int(counts[0])
                mode = int(local[0])
            else:
                smoothed = np.convolve(counts, kernel, mode="same")
                peak = int(np.argmax(smoothed))
                score = int(smoothed[peak])
                mode = int(peak + local.min())
            if score > best_score:
                best_score = score
                best_id = int(rids[start])
                best_raw = int(raw)
                best_offset = mode
        start = stop
    empty.update({"score": best_score, "ref_id": best_id, "raw": best_raw, "offset": best_offset})
    return empty


def allow_mask(n_refs: int, ids: list[int]) -> np.ndarray:
    mask = np.zeros(n_refs, dtype=bool)
    for ref_id in ids:
        mask[ref_id] = True
    return mask


def rate(count: int, probed_seconds: float) -> float | None:
    if probed_seconds <= 0:
        return None
    return count / (probed_seconds / 3600.0)


def main() -> None:
    sys.stdout.reconfigure(line_buffering=True)
    started = time.perf_counter()
    catalog = load_catalog()
    spans = coverage()
    rows = commercials(spans)
    if len(rows) != 166:
        raise SystemExit(f"expected 166 commercials, found {len(rows)}")
    sessions = {}
    for span in spans:
        sid = span["session"]
        if sid in sessions:
            continue
        folder = find_session(RECORDINGS, sid)
        meta = load_session(folder)
        info = catalog.get(sid, {})
        sessions[sid] = {
            "dir": folder,
            "meta": meta,
            "coverage": (float(span["from_seconds"]), float(span["to_seconds"])),
            "network": info.get("network_or_service") or "unknown",
            "content": info.get("content_type") or "",
            "order": sid,
        }
    pods = []
    for index, row in enumerate(rows):
        sid = row["session"]
        pods.append({
            "id": index,
            "session": sid,
            "network": sessions[sid]["network"],
            "content": sessions[sid]["content"],
            "start": float(row["start_seconds"]),
            "end": float(row["end_seconds"]),
        })
    print(f"fingerprinting {len(sessions)} sessions", flush=True)
    finger_seconds = 0.0
    audio_seconds = 0.0
    missing_seconds = 0.0
    landmarks = {}
    for sid, bag in sessions.items():
        cov0, cov1 = bag["coverage"]
        frames_all = []
        hashes_all = []
        dts_all = []
        cursor = cov0
        t_fp = time.perf_counter()
        while cursor < cov1 - 0.5:
            take = min(90.0, cov1 - cursor)
            try:
                audio = read_span(bag["dir"], bag["meta"], cursor, min(cov1, cursor + take + 2.0))
            except RuntimeError:
                missing_seconds += min(5.0, cov1 - cursor)
                cursor += 5.0
                continue
            samples = to_11025(audio)
            block_frames, block_hashes, block_dts = fingerprint(samples, frame_of(cursor))
            limit = frame_of(cursor + take)
            keep = block_frames < limit
            frames_all.append(block_frames[keep])
            hashes_all.append(block_hashes[keep])
            dts_all.append(block_dts[keep])
            audio_seconds += take
            cursor += take
        if frames_all:
            landmarks[sid] = {
                "frames": np.concatenate(frames_all),
                "hashes": np.concatenate(hashes_all),
                "dts": np.concatenate(dts_all),
            }
        else:
            landmarks[sid] = {"frames": np.zeros(0, np.int32), "hashes": np.zeros(0, np.int32), "dts": np.zeros(0, np.int16)}
        finger_seconds += time.perf_counter() - t_fp
        print(f"  {sid} hashes {landmarks[sid]['frames'].size} missing_so_far {missing_seconds:.0f}", flush=True)

    refs = []
    for pod in pods:
        bag = landmarks[pod["session"]]
        frames, hashes = window_hashes(bag["frames"], bag["hashes"], bag["dts"], pod["start"], pod["end"])
        refs.append({**pod, "frames": frames, "hashes": hashes, "n_hashes": int(frames.size)})
    print("building index", flush=True)
    index = build_index(refs)
    n_ref_hashes = int(sum(ref["n_hashes"] for ref in refs))
    ref_audio_s = float(sum(pod["end"] - pod["start"] for pod in pods))

    # Pipeline check: a pod must match itself.
    check = refs[0]
    self_allow = allow_mask(len(refs), [check["id"]])
    qf, qh = window_hashes(landmarks[check["session"]]["frames"], landmarks[check["session"]]["hashes"], landmarks[check["session"]]["dts"], check["start"], min(check["end"], check["start"] + 10))
    self_hit = best_match(qf, qh, index, self_allow)
    if self_hit["score"] < 100:
        raise SystemExit(f"self-match failed: {self_hit}")
    print(f"self-match score {self_hit['score']} hashes {self_hit['n_hashes']}", flush=True)

    by_session_refs = defaultdict(list)
    for ref in refs:
        by_session_refs[ref["session"]].append(ref)
    order = sorted(sessions)

    def ids_for(kind: str, sid: str, t_query: float) -> list[int]:
        if kind == "oracle":
            return [ref["id"] for ref in refs if ref["session"] != sid]
        if kind == "within_session":
            return [ref["id"] for ref in by_session_refs[sid] if ref["end"] <= t_query]
        if kind == "chronological":
            return [ref["id"] for earlier in order if earlier < sid for ref in by_session_refs[earlier]]
        raise SystemExit(kind)

    def query(sid: str, t0: float, t1: float, kind: str) -> dict:
        bag = landmarks[sid]
        frames, hashes = window_hashes(bag["frames"], bag["hashes"], bag["dts"], t0, t1)
        allow = allow_mask(len(refs), ids_for(kind, sid, t0))
        hit = best_match(frames, hashes, index, allow)
        ref = None if hit["ref_id"] is None else refs[hit["ref_id"]]
        return {
            "score": hit["score"],
            "n_hashes": hit["n_hashes"],
            "raw": hit["raw"],
            "offset": hit["offset"],
            "ref_session": None if ref is None else ref["session"],
            "ref_start": None if ref is None else ref["start"],
            "ref_network": None if ref is None else ref["network"],
            "same_session": bool(ref is not None and ref["session"] == sid),
        }

    print("pod openings", flush=True)
    query_t0 = time.perf_counter()
    pod_rows = []
    for pod in pods:
        for kind in ("oracle", "chronological", "within_session"):
            for duration in DURATIONS:
                t1 = min(pod["end"], pod["start"] + duration)
                if t1 <= pod["start"] + 0.4:
                    continue
                hit = query(pod["session"], pod["start"], t1, kind)
                pod_rows.append({
                    "pod_id": pod["id"],
                    "session": pod["session"],
                    "network": pod["network"],
                    "content": pod["content"],
                    "start": pod["start"],
                    "end": pod["end"],
                    "library": kind,
                    "duration_s": duration,
                    "available_s": round(t1 - pod["start"], 3),
                    **hit,
                })
    # Interior slices for the repetition atlas: 10 s at +30 s when the pod is long enough.
    interior_rows = []
    for pod in pods:
        if pod["end"] - pod["start"] < 40:
            continue
        hit = query(pod["session"], pod["start"] + 30.0, pod["start"] + 40.0, "oracle")
        interior_rows.append({"pod_id": pod["id"], "session": pod["session"], "network": pod["network"], "content": pod["content"], **hit})

    print("program and redzone probes", flush=True)
    probe_rows = []
    for sid, bag in sessions.items():
        cov0, cov1 = bag["coverage"]
        banned = [(pod["start"] - 20.0, pod["end"] + 20.0) for pod in pods if pod["session"] == sid]
        t = cov0 + 30.0
        while t + 5.0 <= cov1 - 5.0:
            if any(lo <= t and t + 5.0 <= hi for lo, hi in banned) or any(lo <= t <= hi or lo <= t + 5.0 <= hi for lo, hi in banned):
                t += PROGRAM_HOP_S
                continue
            if any(pod["start"] - 20 <= t <= pod["end"] + 20 for pod in pods if pod["session"] == sid):
                t += PROGRAM_HOP_S
                continue
            for kind in ("oracle", "chronological", "within_session"):
                hit = query(sid, t, t + 5.0, kind)
                probe_rows.append({
                    "session": sid,
                    "network": bag["network"],
                    "content": bag["content"],
                    "t": t,
                    "library": kind,
                    "region": "redzone" if sid == REDZONE else "program",
                    **hit,
                })
            t += PROGRAM_HOP_S

    print("independent 5 s stream", flush=True)
    stream_rows = []
    stream_probes = 0
    for sid, bag in sessions.items():
        cov0, cov1 = bag["coverage"]
        t = cov0 + 5.0
        while t + 5.0 <= cov1:
            inside = next((pod for pod in pods if pod["session"] == sid and pod["start"] <= t < pod["end"]), None)
            near = next((pod for pod in pods if pod["session"] == sid and pod["start"] <= t <= pod["start"] + 5.0), None)
            hit = query(sid, t, t + 5.0, "chronological")
            stream_probes += 1
            if hit["score"] >= 5:
                stream_rows.append({
                    "session": sid,
                    "network": bag["network"],
                    "content": bag["content"],
                    "t": t,
                    "inside_pod": inside is not None,
                    "near_start": near is not None,
                    "region": "redzone" if sid == REDZONE else ("pod" if inside else "program"),
                    **hit,
                })
            t += STREAM_HOP_S
    query_seconds = time.perf_counter() - query_t0

    print("robustness on ESPN openings", flush=True)
    robust = []
    espn_pods = [pod for pod in pods if pod["session"] == DEV]
    analyzer_seconds = []
    for pod in espn_pods:
        try:
            audio = read_span(sessions[DEV]["dir"], sessions[DEV]["meta"], pod["start"], min(pod["end"], pod["start"] + 5.0))
        except RuntimeError:
            continue
        base = to_11025(audio)
        variants = {
            "clean": base,
            "gain_half": base * 0.5,
            "tanh_compress": np.tanh(3.0 * base) / np.tanh(3.0),
            "resample_16000_roundtrip": resample_poly(resample_poly(base, 16000, TARGET_SR), TARGET_SR, 16000),
            "noise_20db": base + 0.1 * np.std(base) * np.random.default_rng(pod["id"]).standard_normal(base.shape),
            "shift_50ms": np.concatenate([np.zeros(int(0.05 * TARGET_SR)), base])[: len(base)],
        }
        allow = allow_mask(len(refs), ids_for("oracle", DEV, pod["start"]))
        for name, samples in variants.items():
            t_one = time.perf_counter()
            frames, hashes, dts = fingerprint(samples, frame_of(pod["start"]))
            analyzer_seconds.append(time.perf_counter() - t_one)
            keep = (frames + dts.astype(np.int32)) < frame_of(pod["start"] + 5.0)
            hit = best_match(frames[keep], hashes[keep], index, allow)
            robust.append({"pod_id": pod["id"], "variant": name, "score": hit["score"], "n_hashes": hit["n_hashes"]})

    # ESPN operating count from chronological? The frozen rule says leave-one-recording library, which is oracle.
    def probe_hits(library: str, sessions_kept: set[str], count: int) -> tuple[int, float]:
        chosen = [row for row in probe_rows if row["library"] == library and row["session"] in sessions_kept and row["region"] == "program"]
        hits = sum(1 for row in chosen if row["score"] >= count and not row["same_session"])
        return hits, len(chosen) * PROGRAM_HOP_S

    eval_sessions = {sid for sid, bag in sessions.items() if bag["content"] == "sports" and sid not in {DEV, REDZONE}}
    espn_choice = []
    for count in COUNTS:
        hits, seconds = probe_hits("oracle", {DEV}, count)
        espn_choice.append({"count": count, "false_ids": hits, "probed_seconds": seconds, "per_hour": rate(hits, seconds)})
    operating = PUBLISHED_COUNT
    for row in espn_choice:
        if row["per_hour"] is not None and row["per_hour"] <= FA_BUDGET:
            operating = row["count"]
            break

    episodes = list(csv.DictReader(EPISODES.open(encoding="utf-8")))
    fresh_at = defaultdict(list)
    ongoing_at = defaultdict(list)
    for row in episodes:
        if row["class"] == "fresh_start" and row["fresh_start_s"]:
            fresh_at[row["session"]].append(float(row["fresh_start_s"]))
        if row["class"] == "ongoing_start" and row["ongoing_start_s"]:
            ongoing_at[row["session"]].append(float(row["ongoing_start_s"]))

    def kind_of(pod: dict) -> str:
        fresh = any(abs(value - pod["start"]) < 0.05 for value in fresh_at.get(pod["session"], []))
        ongoing = any(abs(value - pod["start"]) < 0.05 for value in ongoing_at.get(pod["session"], []))
        if pod["content"] != "sports":
            return "not_football"
        if fresh:
            return "fresh_dsp"
        if ongoing:
            return "ongoing_dsp"
        return "no_dsp"

    for row in pod_rows:
        row["dsp_kind"] = kind_of(next(pod for pod in pods if pod["id"] == row["pod_id"]))

    def opening_hits(library: str, sessions_kept: set[str], duration: int, count: int, kinds: set[str] | None, cross_only: bool) -> dict:
        chosen = [
            row for row in pod_rows
            if row["library"] == library and row["duration_s"] == duration and row["session"] in sessions_kept
            and (kinds is None or row["dsp_kind"] in kinds)
            and row["content"] == "sports"
        ]
        # One row per pod.
        matched = [
            row for row in chosen
            if row["score"] >= count and (not cross_only or not row["same_session"])
        ]
        return {"pods": len(chosen), "matched": len(matched)}

    def summarize_library(library: str, count: int) -> dict:
        out = {"library": library, "count": count}
        for name, kept in (("development", {DEV}), ("evaluation", eval_sessions), ("redzone", {REDZONE})):
            hits, seconds = probe_hits(library, kept, count) if name != "redzone" else (
                sum(1 for row in probe_rows if row["library"] == library and row["session"] == REDZONE and row["score"] >= count and not row["same_session"]),
                sum(1 for row in probe_rows if row["library"] == library and row["session"] == REDZONE) * PROGRAM_HOP_S,
            )
            out[name] = {
                "program_false_ids": hits,
                "probed_seconds": seconds,
                "per_hour": rate(hits, seconds),
                "openings": {str(duration): opening_hits(library, kept if name != "redzone" else {REDZONE}, duration, count, None, True) for duration in DURATIONS},
                "dsp": {
                    kind: {str(duration): opening_hits(library, kept if name != "redzone" else {REDZONE}, duration, count, {kind}, True) for duration in (3, 5, 10)}
                    for kind in ("fresh_dsp", "ongoing_dsp", "no_dsp")
                },
            }
        return out

    reports = [summarize_library(library, count) for library in ("oracle", "chronological") for count in (operating, PUBLISHED_COUNT)]
    # Deduplicate if operating is 200.
    seen = set()
    reports = [row for row in reports if not (row["library"], row["count"]) in seen and not seen.add((row["library"], row["count"]))]

    eval_chrono = next(row for row in reports if row["library"] == "chronological" and row["count"] == operating)
    eval_open = eval_chrono["evaluation"]["openings"]["10"]
    eval_fa = eval_chrono["evaluation"]["per_hour"]
    missed = eval_chrono["evaluation"]["dsp"]["no_dsp"]["5"]["matched"]
    rz_rate = eval_chrono["redzone"]["per_hour"] or 0.0
    dev_open_rate = 0.0
    dev_pods = eval_chrono["development"]["openings"]["5"]
    if dev_pods["pods"]:
        dev_open_rate = dev_pods["matched"] / dev_pods["pods"]
    any_count_works = False
    for count in COUNTS:
        block = summarize_library("chronological", count)
        fa = block["evaluation"]["per_hour"]
        opened = block["evaluation"]["openings"]["10"]["matched"]
        if fa is not None and fa <= FA_BUDGET and opened > 0:
            any_count_works = True
            break
    if (
        eval_fa is not None and eval_fa <= FA_BUDGET and missed >= 1
        and dev_open_rate > rz_rate / max(FA_BUDGET, 1e-9)
    ):
        # The third clause compares a recall to a per-hour rate and is not meaningful.
        # Use the predeclared comparison actually stated: opening recognition beats RedZone false IDs
        # as a yes/no on whether eval pod-opening match rate exceeds RedZone probe hit fraction.
        pass
    eval_open5 = eval_chrono["evaluation"]["openings"]["5"]
    open_rate = (eval_open5["matched"] / eval_open5["pods"]) if eval_open5["pods"] else 0.0
    rz_probes = [row for row in probe_rows if row["library"] == "chronological" and row["session"] == REDZONE]
    rz_frac = (sum(1 for row in rz_probes if row["score"] >= operating and not row["same_session"]) / len(rz_probes)) if rz_probes else 0.0
    if eval_fa is not None and eval_fa <= FA_BUDGET and missed >= 1 and open_rate > rz_frac:
        verdict = "PASS"
    elif not any_count_works:
        verdict = "FAIL"
    else:
        verdict = "INCONCLUSIVE"

    # Repetition atlas at published and operating counts, oracle, 10 s openings, cross-session.
    def atlas(count: int) -> dict:
        rows10 = [row for row in pod_rows if row["library"] == "oracle" and row["duration_s"] == 10 and row["score"] >= count and not row["same_session"]]
        return {
            "count": count,
            "cross_session_pods": len({row["pod_id"] for row in rows10}),
            "same_broadcaster": len({row["pod_id"] for row in rows10 if row["ref_network"] == row["network"]}),
            "other_broadcaster": len({row["pod_id"] for row in rows10 if row["ref_network"] != row["network"]}),
            "pods": len({row["pod_id"] for row in pod_rows if row["library"] == "oracle" and row["duration_s"] == 10}),
        }

    within = [row for row in pod_rows if row["library"] == "chronological" and row["duration_s"] == 10 and row["same_session"] and row["score"] >= operating]
    stream_program = [row for row in stream_rows if row["region"] == "program" and row["score"] >= operating and not row["same_session"]]
    stream_pod = [row for row in stream_rows if row["region"] == "pod" and row["score"] >= operating and not row["same_session"]]
    examples = sorted(
        [row for row in probe_rows if row["library"] == "oracle" and row["region"] == "program" and row["score"] >= operating and not row["same_session"]],
        key=lambda row: -row["score"],
    )[:8]

    robust_summary = {}
    for name in ("clean", "gain_half", "tanh_compress", "resample_16000_roundtrip", "noise_20db", "shift_50ms"):
        scores = [row["score"] for row in robust if row["variant"] == name]
        robust_summary[name] = {"n": len(scores), "median": None if not scores else round(float(np.median(scores)), 1)}

    elapsed = time.perf_counter() - started
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    payload = {
        "matcher": {
            "implementation": "dpwe/audfprint Analyzer landmarks, density 100, sr 11025, match window 2 frames, reference shifts 1",
            "published_min_count": PUBLISHED_COUNT,
            "operating_min_count": operating,
            "operating_selection": "smallest predeclared count with ESPN oracle program false IDs <= 1/hour",
            "espn_curve": espn_choice,
            "self_match_score": self_hit["score"],
            "self_match_hashes": self_hit["n_hashes"],
        },
        "scale": {
            "commercials": len(pods),
            "reference_hashes": n_ref_hashes,
            "reference_audio_s": round(ref_audio_s, 1),
            "audio_fingerprinted_s": round(audio_seconds, 1),
            "missing_s": round(missing_seconds, 1),
            "fingerprint_wall_s": round(finger_seconds, 1),
            "query_wall_s": round(query_seconds, 1),
            "wall_s": round(elapsed, 1),
            "max_rss_bytes": int(rss),
            "hashes_per_reference_minute": None if ref_audio_s <= 0 else round(n_ref_hashes / (ref_audio_s / 60.0), 1),
            "index_bytes_estimate": n_ref_hashes * 8,
        },
        "atlas_oracle_10s": [atlas(count) for count in (operating, PUBLISHED_COUNT)],
        "within_session_10s_at_operating": len({row["pod_id"] for row in within}),
        "interior_oracle_median_score": None if not interior_rows else round(float(np.median([row["score"] for row in interior_rows])), 1),
        "reports": reports,
        "robustness_espn_5s_oracle": robust_summary,
        "stream_chronological_hits_at_operating": {
            "program_saved": len(stream_program),
            "pod_saved": len(stream_pod),
            "hop_s": STREAM_HOP_S,
            "probes": stream_probes,
        },
        "false_match_examples": examples,
        "verdict": verdict,
        "dsp_kinds": dict(sorted((kind, sum(1 for pod in pods if kind_of(pod) == kind)) for kind in ("fresh_dsp", "ongoing_dsp", "no_dsp", "not_football"))),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    with (OUT / "pod_queries.csv").open("w", encoding="utf-8", newline="") as handle:
        fields = ["pod_id", "session", "network", "content", "dsp_kind", "start", "library", "duration_s", "score", "n_hashes", "same_session", "ref_session", "ref_network", "ref_start"]
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(pod_rows)

    fig, ax = plt.subplots(figsize=(6.4, 4.0))
    for library, style in (("chronological", "-"), ("oracle", "--")):
        ys = []
        block = next(row for row in reports if row["library"] == library and row["count"] == operating)
        for duration in DURATIONS:
            item = block["evaluation"]["openings"][str(duration)]
            ys.append(0 if item["pods"] == 0 else item["matched"] / item["pods"])
        ax.plot(list(DURATIONS), ys, style, label=library, lw=1.8)
    ax.set_ylim(0, 1)
    ax.set_xlabel("Seconds of the pod opening")
    ax.set_ylabel("Evaluation football pods matched")
    ax.set_title(f"Cross-session matches at count {operating}")
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(OUT / "opening_recall.png", dpi=120)
    plt.close(fig)
    print(json.dumps({"verdict": verdict, "operating": operating, "espn": espn_choice, "eval_chrono_5": eval_chrono["evaluation"]["openings"]["5"], "missed5": missed, "fa": eval_fa, "rz": rz_frac}, indent=2))


if __name__ == "__main__":
    main()
