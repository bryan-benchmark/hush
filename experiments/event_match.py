"""Event matching and audit math. Collar is an audit parameter, not a detector one."""

from __future__ import annotations

import numpy as np
from scipy.optimize import linear_sum_assignment

COLLARS_S = (0.5, 1.0, 2.0, 5.0)
DEFAULT_COLLAR_S = 2.0
SCORE_SHIFT = 0.5
MOVE_S = 0.25


def match_one_to_one(ref_times: list[float], hyp_times: list[float], collar_s: float):
    """Optimal one-to-one match. Extra hypotheses inside one collar stay unmatched.

    Returns list of (ref_index, hyp_index, signed_error) where
    signed_error = hypothesis - reference.
    """
    n, m = len(ref_times), len(hyp_times)
    if n == 0 or m == 0:
        return []
    big = 1e9
    cost = np.full((n, m), big, dtype=np.float64)
    for i, g in enumerate(ref_times):
        for j, p in enumerate(hyp_times):
            dist = abs(p - g)
            if dist <= collar_s:
                cost[i, j] = dist
    rows, cols = linear_sum_assignment(cost)
    pairs = []
    for i, j in zip(rows, cols):
        if cost[i, j] <= collar_s:
            pairs.append((int(i), int(j), float(hyp_times[j] - ref_times[i])))
    return pairs


def _pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    return float(np.percentile(np.asarray(values, dtype=np.float64), q))


def error_stats(signed: list[float]) -> dict:
    if not signed:
        return {"n": 0, "signed_mean": None, "mae": None, "p50": None, "p95": None}
    arr = np.asarray(signed, dtype=np.float64)
    abs_e = np.abs(arr)
    return {
        "n": int(arr.size),
        "signed_mean": float(arr.mean()),
        "mae": float(abs_e.mean()),
        "p50": float(np.percentile(abs_e, 50)),
        "p95": float(np.percentile(abs_e, 95)),
    }


def prf(tp: int, fp: int, fn: int) -> dict:
    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None
    if precision is None or recall is None or (precision + recall) == 0:
        f1 = None
    else:
        f1 = 2 * precision * recall / (precision + recall)
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def in_coverage(t: float, ranges: list[dict]) -> bool:
    for r in ranges:
        if r.get("fully_annotated") and float(r["from_seconds"]) <= t < float(r["to_seconds"]):
            return True
    return False


def filter_session_ranges(ranges: list[dict], session: str) -> list[dict]:
    return [r for r in ranges if r.get("session") == session and r.get("fully_annotated")]


def score_onset(golds: list[dict], proposals: list[dict], ranges: list[dict], collar_s: float) -> dict:
    """Precision and recall only inside fully_annotated coverage."""
    covered_golds = []
    for g in golds:
        if in_coverage(float(g["start_seconds"]), filter_session_ranges(ranges, g["session"])):
            covered_golds.append(g)
    covered_props = []
    for p in proposals:
        t = float(p["elapsed_seconds"])
        if in_coverage(t, filter_session_ranges(ranges, p["session"])):
            covered_props.append(p)

    by_session: dict[str, dict] = {}
    sessions = {g["session"] for g in covered_golds} | {p["session"] for p in covered_props}
    all_pairs = []
    for session in sorted(sessions):
        gs = [g for g in covered_golds if g["session"] == session]
        ps = [p for p in covered_props if p["session"] == session]
        pairs = match_one_to_one(
            [float(g["start_seconds"]) for g in gs],
            [float(p["elapsed_seconds"]) for p in ps],
            collar_s,
        )
        matched_p = {j for _, j, _ in pairs}
        matched_g = {i for i, _, _ in pairs}
        tp = len(pairs)
        fp = len(ps) - tp
        fn = len(gs) - tp
        signed = [e for _, _, e in pairs]
        by_session[session] = {**prf(tp, fp, fn), "in_error": error_stats(signed)}
        for i, j, err in pairs:
            all_pairs.append({"session": session, "gold": gs[i], "proposal": ps[j], "signed_in_error": err})
        by_session[session]["fp_proposals"] = [ps[j]["proposal_id"] for j in range(len(ps)) if j not in matched_p]
        by_session[session]["fn_gold_ids"] = [gs[i]["gold_id"] for i in range(len(gs)) if i not in matched_g]

    tp = sum(v["tp"] for v in by_session.values())
    fp = sum(v["fp"] for v in by_session.values())
    fn = sum(v["fn"] for v in by_session.values())
    signed = [p["signed_in_error"] for p in all_pairs]
    hours = 0.0
    for r in ranges:
        if r.get("fully_annotated"):
            hours += max(0.0, float(r["to_seconds"]) - float(r["from_seconds"])) / 3600.0
    return {
        "collar_s": collar_s,
        "coverage_hours": hours,
        "gold_count": len(covered_golds),
        "proposal_count": len(covered_props),
        **prf(tp, fp, fn),
        "in_error": error_stats(signed),
        "proposals_per_hour": (len(covered_props) / hours) if hours else None,
        "by_session": {k: {kk: vv for kk, vv in v.items() if kk not in ("fp_proposals", "fn_gold_ids")} for k, v in by_session.items()},
        "pairs": all_pairs,
        "fn_gold_ids": [gid for v in by_session.values() for gid in v["fn_gold_ids"]],
        "fp_proposal_ids": [pid for v in by_session.values() for pid in v["fp_proposals"]],
    }


def diff_keeps(a_rows: list[dict], b_rows: list[dict], collar_s: float = DEFAULT_COLLAR_S) -> dict:
    """Temporal match of kept INs. Proposal ids are not stable across runs."""
    sessions = {r["session"] for r in a_rows} | {r["session"] for r in b_rows}
    both, moved, shifted, removed, added = [], [], [], [], []
    for session in sorted(sessions):
        aa = [r for r in a_rows if r["session"] == session]
        bb = [r for r in b_rows if r["session"] == session]
        pairs = match_one_to_one(
            [float(r["elapsed_seconds"]) for r in aa],
            [float(r["elapsed_seconds"]) for r in bb],
            collar_s,
        )
        matched_a = set()
        matched_b = set()
        for i, j, _err in pairs:
            matched_a.add(i)
            matched_b.add(j)
            left, right = aa[i], bb[j]
            dt = float(right["elapsed_seconds"]) - float(left["elapsed_seconds"])
            ds = float(right["score"]) - float(left["score"])
            rec = {
                "session": session,
                "a_proposal_id": left.get("proposal_id"),
                "b_proposal_id": right.get("proposal_id"),
                "a_seconds": left["elapsed_seconds"],
                "b_seconds": right["elapsed_seconds"],
                "delta_seconds": dt,
                "a_score": left["score"],
                "b_score": right["score"],
                "delta_score": ds,
            }
            if abs(dt) > MOVE_S:
                moved.append(rec)
            elif abs(ds) >= SCORE_SHIFT:
                shifted.append(rec)
            else:
                both.append(rec)
        for i, row in enumerate(aa):
            if i not in matched_a:
                removed.append({"session": session, "proposal_id": row.get("proposal_id"), "seconds": row["elapsed_seconds"], "score": row["score"]})
        for j, row in enumerate(bb):
            if j not in matched_b:
                added.append({"session": session, "proposal_id": row.get("proposal_id"), "seconds": row["elapsed_seconds"], "score": row["score"]})
    return {
        "collar_s": collar_s,
        "kept_in_both": both,
        "moved": moved,
        "score_shifted": shifted,
        "removed": removed,
        "added": added,
    }
