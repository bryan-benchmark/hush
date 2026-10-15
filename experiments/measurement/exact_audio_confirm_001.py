"""EXACT_AUDIO_CONFIRM_001. Not a mute.

Asks whether a waveform correlation, computed from audio already in hand,
can separate audfprint copies from landmark collisions.

The acceptance correlation is the midpoint of the empty gap in the 29 saved
pair measurements. It is not fit to gold. Gold is used only after the
decisions exist, to score them, and to name the reference pods the published
reader already enrolled.

Does not change counts, gold, holdouts, playback, or the published decisions.
"""

from __future__ import annotations

import csv
import hashlib
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

from experiments.broadcast_intelligence.batch1 import commercials, coverage  # noqa: E402
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
from experiments.broadcast_intelligence.batch1 import read_span  # noqa: E402
from experiments.measurement.reference_content_audit_001 import (  # noqa: E402
    QUERY_S,
    align_pair,
)
from experiments.universal_v1.replay import (  # noqa: E402
    COUNT_ABLATION,
    REDZONE,
    actions_for,
    score_group,
)
from hush.audio import analysis_pieces, find_session, load_session  # noqa: E402

PAIRS = REPO / "docs/ohush/research/REFERENCE_CONTENT_AUDIT_001/reference_content_review.jsonl"
DECISIONS = REPO / "docs/ohush/research/UNIVERSAL_V1/decisions.jsonl"
DECISIONS_SHA = "08b1b8d9a56c33681b493dff1d3337951ac9a51b812c83d2e6009afdefb86713"
OUT = REPO / "docs/ohush/research/EXACT_AUDIO_CONFIRM_001"
HOLDOUTS = {"hush_20260917_205513", "hush_20260920_200635"}
PUBLISHED_HOLES_S = 275.0
PUBLISHED_COMMERCIAL_COVERED_S = 3903.2
PUBLISHED_PROGRAM_S = 432.1
PUBLISHED_INCIDENTS = 72
PUBLISHED_WORST_S = 25.1
PUBLISHED_REDZONE_S = 10.0

# Midpoint of the empty gap between 0.7383 and 0.9021 in the saved 29 pairs.
# Written here before the count-10 ledger is scored. Not moved afterward.
CONFIRM_MIN = 0.85
GAP_BELOW = 0.7383
GAP_ABOVE = 0.9021
# Stop rules, also written before the ledger score.
RETAINED_COMMERCIAL_RETIRE_BELOW = 0.5
REMAINING_PROGRAM_RETIRE_AT = 0.5


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_pairs() -> list[dict]:
    rows = []
    for line in PAIRS.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    if len(rows) != 29:
        raise SystemExit(f"expected 29 pairs, found {len(rows)}")
    return rows


def waveform_bucket(correlation: float, half_second: float | None) -> str:
    piece = abs(half_second or 0.0)
    if correlation >= CONFIRM_MIN:
        return "waveform_copy"
    if correlation < 0.15 and piece < 0.30:
        return "unrelated_collision"
    if piece >= 0.90:
        return "partial_copy"
    return "ambiguous"


def inventory(pairs: list[dict]) -> dict:
    values = sorted(float(row["best_positive_within_2s"]) for row in pairs)
    below = [value for value in values if value < CONFIRM_MIN]
    above = [value for value in values if value >= CONFIRM_MIN]
    if not below or not above:
        raise SystemExit("the 29 pairs do not form two correlation groups")
    if round(max(below), 4) != GAP_BELOW or round(min(above), 4) != GAP_ABOVE:
        raise SystemExit(
            f"correlation gap moved: {max(below):.4f} .. {min(above):.4f}, expected {GAP_BELOW} .. {GAP_ABOVE}"
        )
    buckets = defaultdict(list)
    for row in pairs:
        bucket = waveform_bucket(
            float(row["best_positive_within_2s"]),
            row.get("best_half_second_correlation"),
        )
        buckets[bucket].append(row["pair_id"])
        if row.get("reviewer_label") is not None:
            raise SystemExit(f"{row['pair_id']} already has a reviewer label; this pass must not depend on one")
    copies = [row for row in pairs if float(row["best_positive_within_2s"]) >= CONFIRM_MIN]
    collisions = [row for row in pairs if waveform_bucket(float(row["best_positive_within_2s"]), row.get("best_half_second_correlation")) == "unrelated_collision"]
    return {
        "pairs": len(pairs),
        "confirm_min": CONFIRM_MIN,
        "gap_below": max(below),
        "gap_above": min(above),
        "buckets": {key: value for key, value in sorted(buckets.items())},
        "copies_kept": len(copies),
        "collisions": len(collisions),
        "copies_rejected": 0,
        "collisions_accepted": 0,
        "reviewer_labels_present": 0,
        "ambiguous_left_for_a_human": buckets.get("ambiguous", []) + buckets.get("partial_copy", []),
    }


def find_holes(sessions: dict) -> tuple[list[dict], float]:
    holes = []
    missing = 0.0
    for sid, bag in sessions.items():
        cov0, cov1 = bag["coverage"]
        cursor = cov0
        while cursor < cov1 - 0.5:
            take = min(90.0, cov1 - cursor)
            try:
                analysis_pieces(bag["dir"], bag["meta"], cursor, min(cov1, cursor + take + 2.0))
            except RuntimeError:
                hole = min(5.0, cov1 - cursor)
                holes.append({"session": sid, "start": cursor, "end": cursor + hole})
                missing += hole
                cursor += 5.0
                continue
            cursor += take
    return holes, missing


def commercial_covered(group: dict) -> float:
    return round(sum(row["ad_seconds"] - row["ad_seconds_heard"] for row in group["sessions"]), 1)


def session_landmarks(bag: dict, cache: dict) -> dict:
    """One pass per recording, with the published reader's hole skip.

    The 2 s tail is part of that reader. Reproducing it recovers the saved
    alignment. It does not make the alignment available at the decision time.
    """
    if bag["id"] in cache:
        return cache[bag["id"]]
    cov0, cov1 = bag["coverage"]
    frames, hashes, dts = [], [], []
    cursor = cov0
    while cursor < cov1 - 0.5:
        take = min(90.0, cov1 - cursor)
        try:
            audio = read_span(bag["dir"], bag["meta"], cursor, min(cov1, cursor + take + 2.0))
        except RuntimeError:
            cursor += 5.0
            continue
        block_frames, block_hashes, block_dts = fingerprint(to_11025(audio), frame_of(cursor))
        keep = block_frames < frame_of(cursor + take)
        frames.append(block_frames[keep])
        hashes.append(block_hashes[keep])
        dts.append(block_dts[keep])
        cursor += take
    packed = {
        "frames": np.concatenate(frames) if frames else np.zeros(0, np.int32),
        "hashes": np.concatenate(hashes) if hashes else np.zeros(0, np.int32),
        "dts": np.concatenate(dts) if dts else np.zeros(0, np.int16),
    }
    cache[bag["id"]] = packed
    print(f"landmarks {bag['id']} {packed['frames'].size}", flush=True)
    return packed


def exact_window_score(query_bag, ref_bag, query_t0: float, query_t1: float, pod: dict, cache: dict) -> int | None:
    """Fingerprint only the query audio that has already arrived."""
    try:
        audio = read_span(query_bag["dir"], query_bag["meta"], query_t0, query_t1)
    except RuntimeError:
        return None
    frames, hashes, dts = fingerprint(to_11025(audio), frame_of(query_t0))
    qf, qh = window_hashes(frames, hashes, dts, query_t0, query_t1)
    ref = session_landmarks(ref_bag, cache)
    rf, rh = window_hashes(ref["frames"], ref["hashes"], ref["dts"], pod["start"], pod["end"])
    index = build_index([{"id": 0, "frames": rf, "hashes": rh}])
    allow = np.zeros(1, dtype=bool)
    allow[0] = True
    hit = best_match(qf, qh, index, allow)
    return int(hit["score"])


def match_enrolled(query_bag, ref_bag, query_t0: float, pod: dict, cache: dict) -> dict:
    query = session_landmarks(query_bag, cache)
    qf, qh = window_hashes(query["frames"], query["hashes"], query["dts"], query_t0, query_t0 + QUERY_S)
    ref = session_landmarks(ref_bag, cache)
    rf, rh = window_hashes(ref["frames"], ref["hashes"], ref["dts"], pod["start"], pod["end"])
    index = build_index([{"id": 0, "frames": rf, "hashes": rh}])
    allow = np.zeros(1, dtype=bool)
    allow[0] = True
    hit = best_match(qf, qh, index, allow)
    aligned = None
    if hit["offset"] is not None:
        aligned = (frame_of(query_t0) + int(hit["offset"])) * (HOP / TARGET_SR)
    return {
        "score": int(hit["score"]),
        "aligned_ref_t0": None if aligned is None else round(float(aligned), 6),
    }


def load_decisions() -> list[dict]:
    digest = sha256(DECISIONS)
    if digest != DECISIONS_SHA:
        raise SystemExit("published decisions.jsonl hash changed; refusing to score a different file")
    rows = []
    for line in DECISIONS.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def confirm_hits(sessions: dict, pods_by: dict, decisions: list[dict]) -> list[dict]:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "confirmations.jsonl"
    done = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                done[(row["session"], row["query_t0"], row["ref_session"], row["ref_start"])] = row
    hits = [
        row
        for row in decisions
        if int(row["score"]) >= COUNT_ABLATION and not row["same_session"] and row.get("ref_session")
    ]
    cache: dict = {}
    handle = path.open("a", encoding="utf-8")
    try:
        for index, row in enumerate(hits, start=1):
            key = (row["session"], row["query_t0"], row["ref_session"], row["ref_start"])
            if key in done:
                continue
            if row["session"] in HOLDOUTS or row["ref_session"] in HOLDOUTS:
                raise SystemExit("refusing a sealed holdout")
            if abs(float(row["query_t1"]) - float(row["available_at"])) > 1e-6:
                raise SystemExit(f"query extends past its decision time: {key}")
            if float(row["query_t1"]) - float(row["query_t0"]) > QUERY_S + 1e-6:
                raise SystemExit(f"query is longer than the audio available at the decision: {key}")
            pod = min(
                pods_by[row["ref_session"]],
                key=lambda item: abs(item["start"] - float(row["ref_start"])),
            )
            if abs(pod["start"] - float(row["ref_start"])) > 0.02:
                raise SystemExit(f"no enrolled pod at {row['ref_session']} {row['ref_start']}")
            query_bag = sessions[row["session"]]
            ref_bag = sessions[row["ref_session"]]
            reproduced = match_enrolled(query_bag, ref_bag, float(row["query_t0"]), pod, cache)
            aligned = reproduced["aligned_ref_t0"]
            checked = None
            if aligned is not None:
                checked = align_pair(query_bag, ref_bag, float(row["query_t0"]), float(aligned))
                checked.pop("query_audio", None)
                checked.pop("ref_audio", None)
            correlation = None if checked is None else checked["best_positive_within_2s"]
            score_ok = int(reproduced["score"]) == int(row["score"])
            accepted = bool(score_ok and correlation is not None and float(correlation) >= CONFIRM_MIN)
            saved = {
                "session": row["session"],
                "query_t0": row["query_t0"],
                "query_t1": row["query_t1"],
                "available_at": row["available_at"],
                "published_score": int(row["score"]),
                "reproduced_score": int(reproduced["score"]),
                "score_reproduced": score_ok,
                "ref_session": row["ref_session"],
                "ref_start": row["ref_start"],
                "aligned_ref_t0": aligned,
                "best_positive_within_2s": correlation,
                "best_lag_s": None if checked is None else checked["best_lag_s"],
                "best_half_second_correlation": None if checked is None else checked["best_half_second_correlation"],
                "accepted": accepted,
            }
            handle.write(json.dumps(saved) + "\n")
            handle.flush()
            done[key] = saved
            if index % 25 == 0 or index == len(hits):
                print(f"confirmed {index}/{len(hits)}", flush=True)
    finally:
        handle.close()
    return [done[(row["session"], row["query_t0"], row["ref_session"], row["ref_start"])] for row in hits]


def apply_confirmation(decisions: list[dict], confirmed: dict) -> list[dict]:
    rows = []
    for row in decisions:
        copied = dict(row)
        if int(row["score"]) >= COUNT_ABLATION and not row["same_session"] and row.get("ref_session"):
            key = (row["session"], row["query_t0"], row["ref_session"], row["ref_start"])
            if not confirmed[key]["accepted"]:
                copied["score"] = 0
        rows.append(copied)
    return rows


def actions_by_session(sessions: dict, decisions: list[dict]) -> dict:
    by_session = defaultdict(list)
    for row in decisions:
        by_session[row["session"]].append(row)
    return {
        sid: actions_for(bag, by_session.get(sid, []), COUNT_ABLATION)
        for sid, bag in sessions.items()
    }


def main() -> None:
    sys.stdout.reconfigure(line_buffering=True)
    started = time.perf_counter()
    pairs = load_pairs()
    report = inventory(pairs)
    print(json.dumps({"inventory": report}, indent=2), flush=True)

    catalog_path_sessions = {}
    spans = coverage()
    from experiments.broadcast_intelligence.batch1 import load_catalog

    catalog = load_catalog()
    pods = []
    pods_by = defaultdict(list)
    for span in spans:
        sid = span["session"]
        if sid in HOLDOUTS:
            raise SystemExit("refusing a sealed holdout")
        folder = find_session(REPO / "recordings", sid)
        info = catalog.get(sid, {})
        bag = {
            "id": sid,
            "dir": folder,
            "meta": load_session(folder),
            "coverage": (float(span["from_seconds"]), float(span["to_seconds"])),
            "network": info.get("network_or_service") or "unknown",
            "content": info.get("content_type") or "",
        }
        catalog_path_sessions[sid] = bag
    for row in commercials(spans):
        pod = {"session": row["session"], "start": float(row["start_seconds"]), "end": float(row["end_seconds"])}
        pods.append(pod)
        pods_by[row["session"]].append(pod)

    holes, missing = find_holes(catalog_path_sessions)
    print(f"holes {missing:.1f}s across {len(holes)} spans", flush=True)
    if round(missing, 1) != PUBLISHED_HOLES_S:
        raise SystemExit(f"read-hole mask is {missing:.1f}s, published mask is {PUBLISHED_HOLES_S}s")

    decisions = load_decisions()
    base_actions = actions_by_session(catalog_path_sessions, decisions)
    base_foot = score_group("football", catalog_path_sessions, pods, holes, base_actions, COUNT_ABLATION)
    base_red = score_group("redzone", catalog_path_sessions, pods, holes, base_actions, COUNT_ABLATION)
    base_commercial = commercial_covered(base_foot)
    print(
        f"baseline commercial {base_commercial} program {base_foot['program_seconds_covered']} incidents {base_foot['false_cover_incidents']}",
        flush=True,
    )
    if base_commercial != PUBLISHED_COMMERCIAL_COVERED_S or base_foot["program_seconds_covered"] != PUBLISHED_PROGRAM_S:
        raise SystemExit("count-10 baseline does not match the published ledger; refusing a different mask")
    if base_foot["false_cover_incidents"] != PUBLISHED_INCIDENTS or base_foot["worst_continuous_program_interruption_s"] != PUBLISHED_WORST_S:
        raise SystemExit("count-10 incidents do not match the published ledger")
    if base_red["program_seconds_covered"] != PUBLISHED_REDZONE_S or base_foot["unscorable_s"] != PUBLISHED_HOLES_S:
        raise SystemExit("RedZone or hole total does not match the published ledger")

    saved = confirm_hits(catalog_path_sessions, pods_by, decisions)
    confirmed = {
        (row["session"], row["query_t0"], row["ref_session"], row["ref_start"]): row for row in saved
    }
    # The 29 saved correlations are the feasibility set. Recomputed values must agree.
    pair_checks = []
    for row in pairs:
        key = (row["query_session"], row["query_t0"], row["ref_session"], round(float(row["ref_pod_start"]), 3))
        # decisions store ref_start rounded to 3 decimals; pair file keeps full precision.
        match = None
        for saved_row in saved:
            if (
                saved_row["session"] == row["query_session"]
                and abs(float(saved_row["query_t0"]) - float(row["query_t0"])) < 0.05
                and saved_row["ref_session"] == row["ref_session"]
                and abs(float(saved_row["ref_start"]) - float(row["ref_pod_start"])) < 0.02
            ):
                match = saved_row
                break
        if match is None:
            pair_checks.append({"pair_id": row["pair_id"], "status": "not_in_count_10_ledger"})
            continue
        delta = abs(float(match["best_positive_within_2s"]) - float(row["best_positive_within_2s"]))
        pair_checks.append(
            {
                "pair_id": row["pair_id"],
                "saved_correlation": row["best_positive_within_2s"],
                "recomputed_correlation": match["best_positive_within_2s"],
                "abs_delta": round(delta, 4),
                "published_score": row["published_score"],
                "reproduced_score": match["reproduced_score"],
                "accepted": match["accepted"],
            }
        )
    drifted = [row for row in pair_checks if "abs_delta" in row and row["abs_delta"] > 0.01]
    if drifted:
        raise SystemExit(f"recomputed pair correlations drifted: {drifted[:5]}")
    unmatched_pairs = [row["pair_id"] for row in pair_checks if row.get("status")]

    filtered = apply_confirmation(decisions, confirmed)
    new_actions = actions_by_session(catalog_path_sessions, filtered)
    foot = score_group("football", catalog_path_sessions, pods, holes, new_actions, COUNT_ABLATION)
    red = score_group("redzone", catalog_path_sessions, pods, holes, new_actions, COUNT_ABLATION)
    commercial = commercial_covered(foot)
    retained = commercial / PUBLISHED_COMMERCIAL_COVERED_S
    remaining_program = foot["program_seconds_covered"] / PUBLISHED_PROGRAM_S
    accepted = sum(1 for row in saved if row["accepted"])
    rejected = len(saved) - accepted
    mismatched = sum(1 for row in saved if not row["score_reproduced"])
    count_200 = [
        row
        for row in pairs
        if "count_200" in row["roles"]
    ]
    count_200_kept = 0
    for row in count_200:
        match = next(
            item
            for item in pair_checks
            if item["pair_id"] == row["pair_id"]
        )
        if match["accepted"]:
            count_200_kept += 1

    causal_cache: dict = {}
    causal_clock = []
    for row in count_200:
        pod = min(
            pods_by[row["ref_session"]],
            key=lambda item: abs(item["start"] - float(row["ref_pod_start"])),
        )
        exact = exact_window_score(
            catalog_path_sessions[row["query_session"]],
            catalog_path_sessions[row["ref_session"]],
            float(row["query_t0"]),
            float(row["query_t0"]) + QUERY_S,
            pod,
            causal_cache,
        )
        causal_clock.append(
            {
                "pair_id": row["pair_id"],
                "published_score": row["published_score"],
                "score_from_audio_available_at_decision": exact,
                "recovered": exact == int(row["published_score"]),
            }
        )
    causal_clock_ok = bool(causal_clock) and all(item["recovered"] for item in causal_clock)

    trade_fails = (
        count_200_kept < len(count_200)
        or retained < RETAINED_COMMERCIAL_RETIRE_BELOW
        or remaining_program >= REMAINING_PROGRAM_RETIRE_AT
    )
    if trade_fails or not causal_clock_ok:
        decision = "retire"
    else:
        decision = "propose_bounded_generator"

    reason = []
    if count_200_kept < len(count_200):
        reason.append("confirmation rejected a verified count-200 copy")
    if retained < RETAINED_COMMERCIAL_RETIRE_BELOW:
        reason.append("confirmation gave up at least half of the published commercial seconds")
    if remaining_program >= REMAINING_PROGRAM_RETIRE_AT:
        reason.append("at least half of the published program covers are real repeated audio, which this check keeps")
    if not causal_clock_ok:
        reason.append("audio available at the decision time does not recover the published alignment")
    if not reason and decision == "propose_bounded_generator":
        reason.append("copies stay, collisions drop, and the published program covers fall by more than half")

    payload = {
        "system": "exact_audio_confirm_001",
        "playback": "PLAY",
        "gold_modified": False,
        "counts_modified": False,
        "holdouts_opened": False,
        "universal_v1_modified": False,
        "fingerprint_causal_stream": "closed_fail_not_reopened",
        "confirm_min": CONFIRM_MIN,
        "gap": [GAP_BELOW, GAP_ABOVE],
        "inventory": report,
        "pair_recompute": pair_checks,
        "audit_pairs_not_the_winning_reference": unmatched_pairs,
        "count_200_kept": count_200_kept,
        "count_200_total": len(count_200),
        "causal_clock": causal_clock,
        "causal_clock_ok": causal_clock_ok,
        "hits": len(saved),
        "accepted_hits": accepted,
        "rejected_hits": rejected,
        "score_mismatches": mismatched,
        "holes_s": round(missing, 1),
        "baseline_count_10": {
            "commercial_seconds_covered": base_commercial,
            "program_seconds_covered": base_foot["program_seconds_covered"],
            "false_cover_incidents": base_foot["false_cover_incidents"],
            "worst_continuous_program_interruption_s": base_foot["worst_continuous_program_interruption_s"],
            "redzone_program_seconds_covered": base_red["program_seconds_covered"],
            "unscorable_s": base_foot["unscorable_s"],
        },
        "confirmed_count_10": {
            "commercial_seconds_covered": commercial,
            "commercial_seconds_retained_fraction": round(retained, 4),
            "program_seconds_covered": foot["program_seconds_covered"],
            "program_seconds_avoided": round(PUBLISHED_PROGRAM_S - foot["program_seconds_covered"], 1),
            "program_seconds_remaining_fraction": round(remaining_program, 4),
            "false_cover_incidents": foot["false_cover_incidents"],
            "worst_continuous_program_interruption_s": foot["worst_continuous_program_interruption_s"],
            "redzone_program_seconds_covered": red["program_seconds_covered"],
            "redzone_false_cover_incidents": red["false_cover_incidents"],
            "unscorable_s": foot["unscorable_s"],
            "sessions": foot["sessions"],
        },
        "decision": decision,
        "reason": reason,
        "generator_built": False,
        "diagnostic_not_a_causal_policy": True,
        "wall_s": round(time.perf_counter() - started, 1),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    with (OUT / "pair_inventory.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "pair_id",
                "waveform_bucket",
                "saved_relation",
                "saved_content_class",
                "best_positive_within_2s",
                "best_half_second_correlation",
                "query_seconds_inside_gold_commercial",
                "reviewer_label",
                "confirmation",
            ],
        )
        writer.writeheader()
        for row in pairs:
            correlation = float(row["best_positive_within_2s"])
            writer.writerow(
                {
                    "pair_id": row["pair_id"],
                    "waveform_bucket": waveform_bucket(correlation, row.get("best_half_second_correlation")),
                    "saved_relation": row.get("relation"),
                    "saved_content_class": row.get("content_class"),
                    "best_positive_within_2s": row["best_positive_within_2s"],
                    "best_half_second_correlation": row.get("best_half_second_correlation"),
                    "query_seconds_inside_gold_commercial": row.get("query_seconds_inside_gold_commercial"),
                    "reviewer_label": row.get("reviewer_label"),
                    "confirmation": "keep" if correlation >= CONFIRM_MIN else "reject",
                }
            )
    print(json.dumps({"decision": decision, "reason": reason, "commercial": commercial, "program": foot["program_seconds_covered"]}, indent=2), flush=True)


if __name__ == "__main__":
    main()
