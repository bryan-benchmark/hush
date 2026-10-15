"""Universal v1: first causal play/cover timeline.

Frozen before this run is scored. This is a research replay. It does not
change live output, gold, holdouts, or the completed lane reports.

Admitted action, one independent path:
  A 5-second chronological audfprint query, published count 200.
  The query uses only landmarks inside its own window. The reference
  library is gold commercial intervals from earlier recordings only.
  Enrollment is label-informed. The decision time is not: the action
  changes when the query ends, and it applies to audio after that instant.

Not admitted, and why:
  Count 10 is scored from the same queries as an ablation. It is not the
  baseline. ESPN already selected it, and it missed the false-ID budget.
  DSP episodes are written on the receipt and cannot cover by themselves.
  The 40 ms dip gate was not met, and its episode times were not kept.
  Handoff phrases were transcribed only beside gold marks, so a full-timeline
  use would be aimed by the label.

Missing fingerprint evidence stays play. It is not evidence that the
program has returned. A low score is not a program detection.

Enhanced context is not in this script. No feed was aligned.
"""

from __future__ import annotations

import csv
import json
import resource
import sys
import time
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "experiments/broadcast_intelligence/third_party/audfprint"))
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))

import numpy as np

from experiments.broadcast_intelligence.batch1 import commercials, coverage, load_catalog, read_span
from experiments.broadcast_intelligence.known_ad_fingerprint import (
    PUBLISHED_COUNT,
    STREAM_HOP_S,
    allow_mask,
    best_match,
    build_index,
    fingerprint,
    frame_of,
    to_11025,
    window_hashes,
)
from hush.audio import find_session, load_session

RECORDINGS = REPO / "recordings"
OUT = REPO / "docs/ohush/research/UNIVERSAL_V1"
EPISODES = REPO / "docs/ohush/research/CONTINUOUS_DSP_001/episodes.csv"
REDZONE = "hush_20260913_150934"
COUNT_V1 = PUBLISHED_COUNT
COUNT_ABLATION = 10
PROGRAM_SECONDS_PUBLISHED = 18.73 * 3600.0


def subtract(base: list[tuple[float, float]], cuts: list[tuple[float, float]]) -> list[tuple[float, float]]:
    parts = list(base)
    for cut0, cut1 in cuts:
        nxt = []
        for left, right in parts:
            if cut1 <= left or cut0 >= right:
                nxt.append((left, right))
                continue
            if left < cut0:
                nxt.append((left, min(cut0, right)))
            if cut1 < right:
                nxt.append((max(cut1, left), right))
        parts = [(left, right) for left, right in nxt if right - left > 1e-9]
    return parts


def overlap(left: list[tuple[float, float]], right: list[tuple[float, float]]) -> float:
    total = 0.0
    for a0, a1 in left:
        for b0, b1 in right:
            total += max(0.0, min(a1, b1) - max(a0, b0))
    return total


def intersect(left: list[tuple[float, float]], right: list[tuple[float, float]]) -> list[tuple[float, float]]:
    pieces = []
    for a0, a1 in left:
        for b0, b1 in right:
            lo, hi = max(a0, b0), min(a1, b1)
            if hi > lo:
                pieces.append((lo, hi))
    return merge(pieces)


def merge(spans: list[tuple[float, float]]) -> list[tuple[float, float]]:
    ordered = sorted((left, right) for left, right in spans if right > left)
    if not ordered:
        return []
    out = [list(ordered[0])]
    for left, right in ordered[1:]:
        if left <= out[-1][1] + 1e-6:
            out[-1][1] = max(out[-1][1], right)
        else:
            out.append([left, right])
    return [(left, right) for left, right in out]


def load_dsp() -> dict[str, set[int]]:
    on: dict[str, set[int]] = defaultdict(set)
    with EPISODES.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["feature"] != "or":
                continue
            start, end = int(row["t_start"]), int(row["t_end"])
            for second in range(start, end + 1):
                on[row["session"]].add(second)
    return on


def fingerprint_sessions(sessions: dict, spans_by_id: dict) -> tuple[dict, list[dict], float]:
    landmarks = {}
    holes = []
    missing = 0.0
    for sid, bag in sessions.items():
        cov0, cov1 = bag["coverage"]
        frames_all, hashes_all, dts_all = [], [], []
        cursor = cov0
        while cursor < cov1 - 0.5:
            take = min(90.0, cov1 - cursor)
            try:
                audio = read_span(bag["dir"], bag["meta"], cursor, min(cov1, cursor + take + 2.0))
            except RuntimeError:
                hole = min(5.0, cov1 - cursor)
                holes.append({"session": sid, "start": cursor, "end": cursor + hole})
                missing += hole
                cursor += 5.0
                continue
            samples = to_11025(audio)
            block_frames, block_hashes, block_dts = fingerprint(samples, frame_of(cursor))
            limit = frame_of(cursor + take)
            keep = block_frames < limit
            frames_all.append(block_frames[keep])
            hashes_all.append(block_hashes[keep])
            dts_all.append(block_dts[keep])
            cursor += take
        if frames_all:
            landmarks[sid] = {
                "frames": np.concatenate(frames_all),
                "hashes": np.concatenate(hashes_all),
                "dts": np.concatenate(dts_all),
            }
        else:
            landmarks[sid] = {
                "frames": np.zeros(0, np.int32),
                "hashes": np.zeros(0, np.int32),
                "dts": np.zeros(0, np.int16),
            }
        print(f"  {sid} hashes {landmarks[sid]['frames'].size}", flush=True)
    return landmarks, holes, missing


def build_refs(pods: list[dict], landmarks: dict) -> tuple[list[dict], dict]:
    refs = []
    for pod in pods:
        bag = landmarks[pod["session"]]
        frames, hashes = window_hashes(bag["frames"], bag["hashes"], bag["dts"], pod["start"], pod["end"])
        refs.append({**pod, "frames": frames, "hashes": hashes, "n_hashes": int(frames.size)})
    return refs, build_index(refs)


def query_stream(sessions, pods, landmarks, refs, index) -> list[dict]:
    by_session = defaultdict(list)
    for ref in refs:
        by_session[ref["session"]].append(ref)
    order = sorted(sessions)
    rows = []
    for sid in order:
        cov0, cov1 = sessions[sid]["coverage"]
        earlier = [ref["id"] for name in order if name < sid for ref in by_session[name]]
        allow = allow_mask(len(refs), earlier)
        bag = landmarks[sid]
        t = cov0 + STREAM_HOP_S
        while t + STREAM_HOP_S <= cov1:
            frames, hashes = window_hashes(bag["frames"], bag["hashes"], bag["dts"], t, t + STREAM_HOP_S)
            hit = best_match(frames, hashes, index, allow)
            ref = None if hit["ref_id"] is None else refs[hit["ref_id"]]
            rows.append({
                "session": sid,
                "network": sessions[sid]["network"],
                "content": sessions[sid]["content"],
                "query_t0": round(t, 3),
                "query_t1": round(t + STREAM_HOP_S, 3),
                "available_at": round(t + STREAM_HOP_S, 3),
                "score": int(hit["score"]),
                "n_hashes": int(hit["n_hashes"]),
                "ref_session": None if ref is None else ref["session"],
                "ref_start": None if ref is None else round(float(ref["start"]), 3),
                "same_session": bool(ref is not None and ref["session"] == sid),
            })
            t += STREAM_HOP_S
        print(f"  queried {sid}", flush=True)
    return rows


def actions_for(session: dict, decisions: list[dict], count: int) -> list[tuple[float, float, str, str]]:
    cov0, cov1 = session["coverage"]
    if not decisions:
        return [(cov0, cov1, "play", "insufficient_evidence")]
    first = decisions[0]["available_at"]
    spans = [(cov0, first, "play", "insufficient_evidence")]
    for index, row in enumerate(decisions):
        start = row["available_at"]
        end = cov1 if index + 1 == len(decisions) else decisions[index + 1]["available_at"]
        if row["score"] >= count and not row["same_session"]:
            spans.append((start, end, "cover", "positive_commercial_fingerprint"))
        else:
            spans.append((start, end, "play", "insufficient_evidence"))
    return [(left, right, action, reason) for left, right, action, reason in spans if right > left]


def cover_spans(actions) -> list[tuple[float, float]]:
    return [(left, right) for left, right, action, _reason in actions if action == "cover"]


def play_spans(actions) -> list[tuple[float, float]]:
    return [(left, right) for left, right, action, _reason in actions if action == "play"]


def score_group(name: str, sessions: dict, pods: list[dict], holes: list[dict], action_map: dict, count: int) -> dict:
    per_session = []
    pods_hit = 0
    already_covering = 0
    delays = []
    return_delays = []
    premature_incidents = 0
    premature_ad_seconds = 0.0
    censored_returns = 0
    missed_pods = 0
    missed_pod_seconds = 0.0
    for sid, bag in sessions.items():
        if name == "football" and (bag["content"] != "sports" or sid == REDZONE):
            continue
        if name == "redzone" and sid != REDZONE:
            continue
        if name == "scripted" and bag["content"] == "sports":
            continue
        cov0, cov1 = bag["coverage"]
        coverage = [(cov0, cov1)]
        here = [(pod["start"], pod["end"]) for pod in pods if pod["session"] == sid]
        hole_spans = [(row["start"], row["end"]) for row in holes if row["session"] == sid]
        program = subtract(subtract(coverage, here), hole_spans)
        commercial = subtract(here, hole_spans)
        actions = action_map[sid]
        covers = cover_spans(actions)
        plays = play_spans(actions)
        ad_heard = overlap(commercial, plays)
        program_covered = overlap(program, covers)
        incidents = intersect(covers, program)
        worst = max((right - left for left, right in incidents), default=0.0)
        session_pods = [pod for pod in pods if pod["session"] == sid]
        for pod in session_pods:
            window = (pod["start"], pod["end"])
            first = None
            for left, right in covers:
                lo = max(window[0], left)
                if right > lo and lo < window[1]:
                    first = lo
                    break
            length = pod["end"] - pod["start"]
            if first is None:
                missed_pods += 1
                missed_pod_seconds += overlap([window], commercial)
            else:
                pods_hit += 1
                if first <= pod["start"] + 1e-6:
                    already_covering += 1
                delays.append(max(0.0, first - pod["start"]))
            covered_inside = overlap([window], covers) > 0
            play_after = 0.0
            saw_cover = False
            letting_go = False
            for left, right, action, _reason in actions:
                lo, hi = max(left, pod["start"]), min(right, pod["end"])
                if hi <= lo:
                    continue
                if action == "cover":
                    saw_cover = True
                    letting_go = False
                elif saw_cover:
                    if not letting_go:
                        premature_incidents += 1
                        letting_go = True
                    play_after += hi - lo
            premature_ad_seconds += play_after
            if covered_inside:
                holding = any(action == "cover" and left <= pod["end"] - 1e-6 < right for left, right, action, _reason in actions)
                if holding:
                    nxt = next((left for left, _right, action, _reason in actions if action == "play" and left >= pod["end"] - 1e-9), None)
                    if nxt is None:
                        censored_returns += 1
                    else:
                        return_delays.append(nxt - pod["end"])
        per_session.append({
            "session": sid,
            "network": bag["network"],
            "ad_seconds_heard": round(ad_heard, 1),
            "program_seconds_covered": round(program_covered, 1),
            "false_cover_incidents": len(incidents),
            "worst_program_interruption_s": round(worst, 1),
            "ad_seconds": round(overlap(commercial, coverage), 1),
            "program_seconds": round(overlap(program, coverage), 1),
            "unscorable_s": round(sum(right - left for left, right in hole_spans), 1),
        })
    def pct(values: list[float], p: float) -> float | None:
        if not values:
            return None
        ordered = sorted(values)
        index = min(len(ordered) - 1, int(round((len(ordered) - 1) * p)))
        return round(ordered[index], 3)

    heard = sum(row["ad_seconds_heard"] for row in per_session)
    covered = sum(row["program_seconds_covered"] for row in per_session)
    program_seconds = sum(row["program_seconds"] for row in per_session)
    incidents = sum(row["false_cover_incidents"] for row in per_session)
    worst_session = max(per_session, key=lambda row: row["ad_seconds_heard"] + row["program_seconds_covered"], default=None)
    return {
        "population": name,
        "count": count,
        "commercial_seconds_heard": round(heard, 1),
        "program_seconds_covered": round(covered, 1),
        "total_error_seconds": round(heard + covered, 1),
        "false_cover_incidents": incidents,
        "false_cover_incidents_per_program_hour": None if program_seconds <= 0 else round(incidents / (program_seconds / 3600.0), 3),
        "premature_return_incidents": premature_incidents,
        "ad_seconds_heard_after_a_cover_let_go": round(premature_ad_seconds, 1),
        "pods_with_any_cover": pods_hit,
        "pods_already_covered_at_the_gold_start": already_covering,
        "pods_missed": missed_pods,
        "missed_pod_seconds": round(missed_pod_seconds, 1),
        "start_delay_s": {"n": len(delays), "median": pct(delays, 0.5), "p95": pct(delays, 0.95)},
        "return_delay_s": {
            "n": len(return_delays),
            "median": pct(return_delays, 0.5),
            "p95": pct(return_delays, 0.95),
            "still_covering_at_annotation_end": censored_returns,
        },
        "worst_continuous_program_interruption_s": round(max((row["worst_program_interruption_s"] for row in per_session), default=0.0), 1),
        "unscorable_s": round(sum(row["unscorable_s"] for row in per_session), 1),
        "worst_session": worst_session,
        "sessions": per_session,
    }


def pipeline_check(rows: list[dict], pods: list[dict]) -> dict:
    """Gold is used only here, after the queries, to compare with the frozen stream counts."""
    program = pod = 0
    for row in rows:
        if row["score"] < COUNT_ABLATION or row["same_session"]:
            continue
        inside = any(pod["session"] == row["session"] and pod["start"] <= row["query_t0"] < pod["end"] for pod in pods)
        if row["session"] == REDZONE:
            continue
        if inside:
            pod += 1
        else:
            program += 1
    return {"program_at_count_10": program, "pod_at_count_10": pod, "frozen_program": 91, "frozen_pod": 813}


def main() -> None:
    sys.stdout.reconfigure(line_buffering=True)
    started = time.perf_counter()
    catalog = load_catalog()
    spans = coverage()
    raw_pods = commercials(spans)
    if len(raw_pods) != 166:
        raise SystemExit(f"expected 166 commercials, found {len(raw_pods)}")
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
    pods = []
    for index, row in enumerate(raw_pods):
        sid = row["session"]
        pods.append({
            "id": index,
            "session": sid,
            "network": sessions[sid]["network"],
            "content": sessions[sid]["content"],
            "start": float(row["start_seconds"]),
            "end": float(row["end_seconds"]),
        })
    print("fingerprinting", flush=True)
    landmarks, holes, missing = fingerprint_sessions(sessions, {})
    refs, index = build_refs(pods, landmarks)
    check = refs[0]
    self_allow = allow_mask(len(refs), [check["id"]])
    frames, hashes = window_hashes(
        landmarks[check["session"]]["frames"],
        landmarks[check["session"]]["hashes"],
        landmarks[check["session"]]["dts"],
        check["start"],
        min(check["end"], check["start"] + 10),
    )
    self_hit = best_match(frames, hashes, index, self_allow)
    if self_hit["score"] < 100:
        raise SystemExit(f"self-match failed: {self_hit}")
    print(f"self-match {self_hit['score']}", flush=True)
    print("streaming", flush=True)
    rows = query_stream(sessions, pods, landmarks, refs, index)
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "decisions.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")
    check_counts = pipeline_check(rows, pods)
    print("pipeline", check_counts, flush=True)
    if check_counts["program_at_count_10"] != 91 or check_counts["pod_at_count_10"] != 813:
        raise SystemExit(f"stream did not reproduce the frozen fingerprint counts: {check_counts}")
    dsp = load_dsp()
    by_session = defaultdict(list)
    for row in rows:
        by_session[row["session"]].append(row)
    action_v1 = {}
    action_10 = {}
    receipt_path = OUT / "receipts.jsonl"
    with receipt_path.open("w", encoding="utf-8") as handle:
        for sid, bag in sessions.items():
            decisions = by_session[sid]
            action_v1[sid] = actions_for(bag, decisions, COUNT_V1)
            action_10[sid] = actions_for(bag, decisions, COUNT_ABLATION)
            cov0 = bag["coverage"][0]
            handle.write(json.dumps({
                "session": sid,
                "t_decision": cov0,
                "action": "play",
                "reason": "insufficient_evidence",
                "fingerprint": None,
                "dsp_or_second_available": False,
                "handoff": "not_on_clock",
                "micro_dip": "not_admitted",
                "count": COUNT_V1,
            }) + "\n")
            for row in decisions:
                second = int(row["available_at"]) - 1
                action = "cover" if row["score"] >= COUNT_V1 and not row["same_session"] else "play"
                reason = "positive_commercial_fingerprint" if action == "cover" else "insufficient_evidence"
                handle.write(json.dumps({
                    "session": sid,
                    "t_decision": row["available_at"],
                    "action": action,
                    "reason": reason,
                    "fingerprint": {
                        "score": row["score"],
                        "n_hashes": row["n_hashes"],
                        "query_t0": row["query_t0"],
                        "query_t1": row["query_t1"],
                        "available_at": row["available_at"],
                        "ref_session": row["ref_session"],
                        "ref_start": row["ref_start"],
                        "threshold": COUNT_V1,
                        "library": "chronological_earlier_recordings",
                    },
                    "dsp_or_second_available": second in dsp.get(sid, set()),
                    "handoff": "not_on_clock",
                    "micro_dip": "not_admitted",
                }) + "\n")
    groups = {}
    for label, actions, count in (
        ("v1", action_v1, COUNT_V1),
        ("ablation_count_10", action_10, COUNT_ABLATION),
    ):
        groups[label] = {
            population: score_group(population, sessions, pods, holes, actions, count)
            for population in ("football", "redzone", "scripted")
        }
    football_ads = sum(pod["end"] - pod["start"] for pod in pods if sessions[pod["session"]]["content"] == "sports" and pod["session"] != REDZONE)
    payload = {
        "system": "universal_v1",
        "architecture": "optical audio only",
        "champion_candidate": False,
        "policy": {
            "count": COUNT_V1,
            "query_s": STREAM_HOP_S,
            "hop_s": STREAM_HOP_S,
            "library": "gold commercials from earlier recordings; current recording excluded",
            "enrollment": "label-informed",
            "decision": "causal; action applies after the query ends",
            "missing_evidence": "play",
            "dsp": "receipt only",
            "handoff": "not_on_clock",
            "micro_dip": "not_admitted",
        },
        "pipeline_check": check_counts,
        "self_match_score": int(self_hit["score"]),
        "football_ad_seconds": round(football_ads, 1),
        "football_program_seconds_published": PROGRAM_SECONDS_PUBLISHED,
        "budget_99_99_seconds": round(0.0001 * (PROGRAM_SECONDS_PUBLISHED + football_ads), 2),
        "groups": groups,
        "holes_s": round(missing, 1),
        "decisions": len(rows),
        "wall_s": round(time.perf_counter() - started, 1),
        "max_rss_bytes": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss),
        "enhanced": {
            "status": "not_measured",
            "accuracy": None,
            "reason": "No game-event feed, schedule, or device metadata was authorized or aligned.",
        },
    }
    (OUT / "results.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"v1_football": groups["v1"]["football"], "ablation_football": groups["ablation_count_10"]["football"]}, indent=2))


if __name__ == "__main__":
    main()
