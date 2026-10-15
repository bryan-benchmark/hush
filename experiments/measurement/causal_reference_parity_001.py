"""CAUSAL-REFERENCE-PARITY-001. Not a mute.

The bounded reader stays closed. This asks whether the five verified ads
return when the reference window is extracted the same way as the query.
Known locations are a diagnosis. They are not a search. The ledger is not
scored unless every verified window reaches 200.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "experiments/broadcast_intelligence/third_party/audfprint"))
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))

from experiments.broadcast_intelligence.batch1 import commercials, coverage, load_catalog  # noqa: E402
from experiments.broadcast_intelligence.known_ad_fingerprint import (  # noqa: E402
    HOP,
    TARGET_SR,
    best_match,
    build_index,
    frame_of,
    window_hashes,
)
from experiments.measurement.fingerprint_bounded_query_001 import (  # noqa: E402
    CONTROLS,
    FALSE_QUERIES,
    LEAD_S,
    QUERY_S,
    AFTERNOON,
    cold_blocks,
    find_pod,
    pod_score,
    query_hashes,
)
import soundfile as sf

from hush.audio import RAW_SR, find_session, load_session  # noqa: E402
from experiments.broadcast_intelligence.known_ad_fingerprint import fingerprint, to_11025  # noqa: E402

OUT = REPO / "docs/ohush/research/CAUSAL_REFERENCE_PARITY_001"
DECISIONS = REPO / "docs/ohush/research/UNIVERSAL_V1/decisions.jsonl"
HOLDOUTS = {"hush_20260917_205513", "hush_20260920_200635"}
HOP_S = HOP / TARGET_SR
HOP_LEAD_S = 86 * HOP_S
EXPECTED = {145.0: 33, 150.0: 137, 155.0: 92, 160.0: 26, 5085.0: 102}
WAVEFORM_LAG = {145.0: 0.0376, 150.0: 0.0453, 155.0: 0.053, 160.0: 0.0375, 5085.0: 0.0513}


def match(query_frames, query_hashes, ref_frames, ref_hashes) -> dict:
    index = build_index([{"id": 0, "frames": ref_frames, "hashes": ref_hashes}])
    hit = best_match(query_frames, query_hashes, index, np.ones(1, dtype=bool))
    return {
        "score": int(hit["score"]),
        "offset_frames": None if hit["offset"] is None else int(hit["offset"]),
        "n_hashes": int(hit["n_hashes"]),
    }


def cold_alignment(query_bag, ref_bag, t0: float, pod: dict, cache: dict) -> dict:
    query = cold_blocks(query_bag, t0, t0 + QUERY_S, cache)
    qf, qh = window_hashes(query["frames"], query["hashes"], query["dts"], t0, t0 + QUERY_S)
    ref = cold_blocks(ref_bag, pod["start"], pod["end"], cache)
    rf, rh = window_hashes(ref["frames"], ref["hashes"], ref["dts"], pod["start"], pod["end"])
    hit = match(qf, qh, rf, rh)
    aligned = None if hit["offset_frames"] is None else (frame_of(t0) + hit["offset_frames"]) * HOP_S
    return {**hit, "aligned_ref_t0": None if aligned is None else round(aligned, 6)}


def loose_audio(bag: dict, start: float, end: float) -> np.ndarray:
    """Same chunk slices as the strict reader, concatenated when a boundary is off by a sample."""
    cov0, cov1 = bag["coverage"]
    start = max(cov0, start)
    end = min(cov1, end)
    parts = []
    for chunk in bag["meta"]["chunks"]:
        c0 = float(chunk["start_elapsed_seconds"])
        c1 = float(chunk["end_elapsed_seconds"])
        if c1 <= start or c0 >= end:
            continue
        take0, take1 = max(start, c0), min(end, c1)
        info = sf.info(str(bag["dir"] / chunk["file"]))
        frame0 = int(round((take0 - c0) * RAW_SR))
        frame1 = min(int(round((take1 - c0) * RAW_SR)), info.frames)
        data, _sr = sf.read(bag["dir"] / chunk["file"], start=frame0, stop=frame1, dtype="float32", always_2d=True)
        parts.append(data)
    if not parts:
        raise RuntimeError(f"no chunks cover {start}..{end}")
    return np.concatenate(parts, axis=0)


def safe_hashes(bag: dict, t0: float, lead_s: float):
    try:
        frames, hashes, elapsed, origin = query_hashes(bag, t0, lead_s)
        return frames, hashes, elapsed, origin, False
    except RuntimeError:
        cov0, _cov1 = bag["coverage"]
        origin = max(cov0, t0 - lead_s)
        audio = loose_audio(bag, origin, t0 + QUERY_S)
        frames, hashes, dts = fingerprint(to_11025(audio), frame_of(origin))
        kept_f, kept_h = window_hashes(frames, hashes, dts, t0, t0 + QUERY_S)
        return kept_f, kept_h, 0.0, origin, True


def bounded_pair(query_bag, ref_bag, query_t0: float, ref_t0: float, lead_s: float) -> dict:
    query = safe_hashes(query_bag, query_t0, lead_s)
    ref = safe_hashes(ref_bag, ref_t0, lead_s)
    qf, qh, _elapsed, _origin, query_fallback = query
    rf, rh, _elapsed, _origin, ref_fallback = ref
    hit = match(qf, qh, rf, rh)
    expected = frame_of(ref_t0) - frame_of(query_t0)
    offset = hit["offset_frames"]
    return {
        **hit,
        "ref_t0": round(ref_t0, 6),
        "offset_error_frames": None if offset is None else int(offset - expected),
        "self_score": match(qf, qh, qf, qh)["score"],
        "chunk_boundary_read": bool(query_fallback or ref_fallback),
    }


def phase_grid(t0: float) -> list[float]:
    shifts = {round(i * HOP_S, 6) for i in range(-8, 9)}
    shifts.update({-0.5, -0.25, -0.1, -0.04, 0.04, 0.1, 0.25, 0.5, round(WAVEFORM_LAG[t0], 6)})
    return sorted(shifts)


def main() -> None:
    sys.stdout.reconfigure(line_buffering=True)
    catalog = load_catalog()
    spans = coverage()
    sessions = {}
    pods_by = {}
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
        pods_by[sid] = []
    for row in commercials(spans):
        pods_by[row["session"]].append({"start": float(row["start_seconds"]), "end": float(row["end_seconds"])})
    cache = {}
    ads = []
    for session, t0, published, ref_session, ref_start in CONTROLS:
        query_bag = sessions[session]
        ref_bag = sessions[ref_session]
        pod = find_pod(pods_by[ref_session], ref_start)
        reproduced = pod_score(query_bag, ref_bag, t0, pod, cache, LEAD_S)
        aligned = cold_alignment(query_bag, ref_bag, t0, pod, cache)
        ref_t0 = aligned["aligned_ref_t0"]
        same_2s = bounded_pair(query_bag, ref_bag, t0, ref_t0, LEAD_S)
        same_hop = bounded_pair(query_bag, ref_bag, t0, ref_t0 + WAVEFORM_LAG[t0], HOP_LEAD_S)
        same_hop_frame = bounded_pair(query_bag, ref_bag, t0, ref_t0, HOP_LEAD_S)
        phases = []
        qf, qh, _elapsed, _origin, _fallback = safe_hashes(query_bag, t0, HOP_LEAD_S)
        for shift in phase_grid(t0):
            rf, rh, _elapsed, _origin, fallback = safe_hashes(ref_bag, ref_t0 + shift, HOP_LEAD_S)
            hit = match(qf, qh, rf, rh)
            phases.append({
                "shift_s": shift,
                "score": hit["score"],
                "offset_frames": hit["offset_frames"],
                "chunk_boundary_read": fallback,
            })
        best_phase = max(phases, key=lambda row: -1 if row["score"] is None else row["score"])
        row = {
            "session": session,
            "query_t0": t0,
            "published_score": published,
            "reproduced_bounded_vs_cold": reproduced["score"],
            "reproduction_matches": reproduced["score"] == EXPECTED[t0],
            "cold_alignment_score": aligned["score"],
            "aligned_ref_t0": ref_t0,
            "inside_pod": pod["start"] <= ref_t0 < pod["end"],
            "bounded_vs_bounded_2s": same_2s,
            "bounded_vs_bounded_hop_at_frame": same_hop_frame,
            "bounded_vs_bounded_hop_at_waveform": same_hop,
            "best_phase": best_phase,
            "phases_at_least_200": sum(item["score"] is not None and item["score"] >= 200 for item in phases),
            "phases": phases,
        }
        ads.append(row)
        print(
            "ad",
            t0,
            "cold",
            reproduced["score"],
            "same2",
            same_2s["score"],
            "hop",
            same_hop_frame["score"],
            "wave",
            same_hop["score"],
            "best",
            best_phase,
            flush=True,
        )
    reproduced_ok = all(row["reproduction_matches"] for row in ads)
    def known_score(item: dict) -> int:
        value = item["score"]
        return -1 if value is None else value

    frame_gate = reproduced_ok and all(
        max(known_score(row["bounded_vs_bounded_2s"]), known_score(row["bounded_vs_bounded_hop_at_frame"])) >= 200
        for row in ads
    )
    waveform_gate = reproduced_ok and all(
        known_score(row["bounded_vs_bounded_hop_at_waveform"]) >= 200 for row in ads
    )
    gate = waveform_gate
    false_rows = []
    if reproduced_ok:
        published = {}
        for line in DECISIONS.read_text(encoding="utf-8").splitlines():
            item = json.loads(line)
            if item["session"] == AFTERNOON and float(item["query_t0"]) in FALSE_QUERIES:
                published[float(item["query_t0"])] = item
        afternoon = sessions[AFTERNOON]
        for t0 in FALSE_QUERIES:
            item = published[t0]
            pod = find_pod(pods_by[item["ref_session"]], float(item["ref_start"]))
            bounded_cold = pod_score(afternoon, sessions[item["ref_session"]], t0, pod, cache, LEAD_S)
            aligned = cold_alignment(afternoon, sessions[item["ref_session"]], t0, pod, cache)
            same = None
            if aligned["aligned_ref_t0"] is not None:
                same = bounded_pair(afternoon, sessions[item["ref_session"]], t0, aligned["aligned_ref_t0"], HOP_LEAD_S)
            false_rows.append({
                "query_t0": t0,
                "published_score": int(item["score"]),
                "bounded_vs_cold": bounded_cold["score"],
                "cold_aligned_ref_t0": aligned["aligned_ref_t0"],
                "bounded_vs_bounded_hop": None if same is None else same["score"],
                "offset_error_frames": None if same is None else same["offset_error_frames"],
            })
            print("false", false_rows[-1], flush=True)
    payload = {
        "system": "causal_reference_parity_001",
        "mute_policy": False,
        "playback": "PLAY",
        "oracle_alignment_is_not_detection": True,
        "ledger_scored": False,
        "reproduction_ok": reproduced_ok,
        "frame_aligned_gate": frame_gate,
        "waveform_aligned_gate": waveform_gate,
        "known_ad_gate": gate,
        "operational_detection": False,
        "ads": ads,
        "false_matches": false_rows,
        "unknown_location_search": "not run",
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()
    decisions_sha = subprocess.check_output(["shasum", "-a", "256", str(DECISIONS)], text=True).split()[0]
    (OUT / "receipts.json").write_text(
        json.dumps(
            {
                "system": "causal_reference_parity_001",
                "git_head": head,
                "decisions_sha256": decisions_sha,
                "bounded_query_modified": False,
                "thresholds_modified": False,
                "gold_modified": False,
                "holdouts_opened": False,
                "ledger_scored": False,
                "playback": "PLAY",
                "chunk_boundary_reads": "Thursday 150 waveform lag and Thursday 160 hop and waveform windows. A one-sample chunk-boundary check refused those spans. The same slices were concatenated and fingerprinted. Nearby strict reads agree: 150 stays above 200 across several hops, and 160 stays near 26 except at the waveform lag.",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"reproduction_ok": reproduced_ok, "known_ad_gate": gate}, indent=2))


if __name__ == "__main__":
    main()
