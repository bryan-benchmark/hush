#!/usr/bin/env python3
"""Debug queue. Not an evaluation set.

One human item per acoustic event. Holdouts, ignore sessions, and
acquisition fixtures never appear here.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict

import numpy as np

import acquisition
import datasets
import ledger

MIN_GAP_S = 25.0
SHOULDER_S = 3.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--n", type=int, default=8)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    run = ledger.RUNS / args.run
    keeps = [_dev_only(r) for r in ledger.read_jsonl(run / "candidates.jsonl")]
    keeps = [r for r in keeps if r]
    selections = ledger.read_jsonl(run / "selections.jsonl")
    proposals = {p["proposal_id"]: p for p in ledger.read_jsonl(run / "proposals.jsonl")}
    eligible = acquisition.eligible_files(args.run)
    if eligible is not None:
        keeps = [r for r in keeps if (r["session"], r["file"]) in eligible]
    inputs = json.loads((run / "inputs.json").read_text(encoding="utf-8"))
    high = highest_diverse_keeps(keeps, args.n)
    boundary = topk_boundary(run, keeps, selections, args.n)
    gaps = meaningful_suppressions(selections, proposals, eligible, args.n)
    windows = continuous_windows(inputs, keeps, eligible, args.n, args.seed)
    items = high + boundary + gaps + windows
    queue = {
        "purpose": "debug_queue_not_evaluation_set",
        "run_id": args.run,
        "seed": args.seed,
        "excluded_roles": ["holdout", "ignore", "acquisition_fixture"],
        "items": items,
    }
    out = ledger.ROOT / "experiments" / "queues" / f"{args.run}_debug.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(queue, indent=2), encoding="utf-8")
    print(f"wrote {len(items)} items → {out}")
    print(dict(Counter(i["stratum"] for i in items)))


def _dev_only(row: dict) -> dict | None:
    if not datasets.reviewable(row.get("session", "")):
        return None
    return row


def _item(row: dict, stratum: str, **extra) -> dict:
    out = {
        "stratum": stratum,
        "proposal_id": row.get("proposal_id"),
        "session": row.get("session"),
        "file": row.get("file"),
        "elapsed_seconds": row.get("elapsed_seconds"),
        "score": row.get("score"),
        "frame_index": row.get("frame_index"),
        "sample_index": row.get("sample_index"),
        "session_sample_index": row.get("session_sample_index"),
    }
    out.update(extra)
    return out


def highest_diverse_keeps(keeps: list[dict], n: int, per_session: int = 2, min_sep_s: float = MIN_GAP_S) -> list[dict]:
    chosen: list[dict] = []
    counts: Counter[str] = Counter()
    for row in sorted(keeps, key=lambda r: float(r["score"]), reverse=True):
        session = row["session"]
        if counts[session] >= per_session:
            continue
        t = float(row["elapsed_seconds"])
        if any(c["session"] == session and abs(t - float(c["elapsed_seconds"])) < min_sep_s for c in chosen):
            continue
        chosen.append(_item(row, "highest_diverse_keep"))
        counts[session] += 1
        if len(chosen) >= n:
            break
    return chosen


def topk_boundary(run, keeps: list[dict], selections: list[dict], n: int) -> list[dict]:
    """Sixth surviving keep, and the strongest frame top_k kept out."""
    by_chunk: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in keeps:
        by_chunk[(row["session"], row["file"])].append(row)
    ranked: list[tuple[float, dict, dict | None]] = []
    for (session, file), rows in by_chunk.items():
        ordered = sorted(rows, key=lambda r: int((r.get("selection") or {}).get("selection_rank", 0)))
        if len(ordered) < 6:
            continue
        sixth = ordered[5]
        seventh = _hypothetical_seventh(run, session, file, ordered[:6])
        score = float(seventh["score"]) if seventh else -1e9
        ranked.append((score, sixth, seventh))
    ranked.sort(key=lambda t: t[0], reverse=True)
    items = []
    for _score, sixth, seventh in ranked[:n]:
        items.append(_item(sixth, "topk_sixth_keep", selection_rank=5))
        if seventh:
            items.append(seventh)
    return items


def _hypothetical_seventh(run, session: str, file: str, six: list[dict]) -> dict | None:
    trace = run / "traces" / session / f"{Path_stem(file)}.npz"
    if not trace.exists():
        return None
    with np.load(trace) as z:
        score = np.asarray(z["composite_score"], dtype=np.float64)
        hop_s = 0.125
    keep_t = np.asarray([float(r["chunk_elapsed_seconds"]) for r in six], dtype=np.float64)
    times = np.arange(score.size, dtype=np.float64) * hop_s
    order = np.argsort(score)[::-1]
    start = float(six[0]["elapsed_seconds"]) - float(six[0]["chunk_elapsed_seconds"])
    for idx in order:
        t = float(times[int(idx)])
        if np.min(np.abs(keep_t - t)) < MIN_GAP_S:
            continue
        return {
            "stratum": "topk_seventh_blocked",
            "proposal_id": None,
            "session": session,
            "file": file,
            "elapsed_seconds": round(start + t, 3),
            "chunk_elapsed_seconds": round(t, 3),
            "score": round(float(score[int(idx)]), 3),
            "frame_index": int(idx),
            "note": "Highest frame outside 25s of the six keeps. top_k stopped before this.",
        }
    return None


def meaningful_suppressions(selections: list[dict], proposals: dict, eligible: set | None, n: int) -> list[dict]:
    """One suppressed peak per winning keep, ignoring ±0.125s shoulders."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in selections:
        if row.get("stage") != "in" or row.get("action") != "suppress" or row.get("reason") != "min_gap":
            continue
        if not datasets.reviewable(row.get("session", "")):
            continue
        if eligible is not None and (row.get("session"), row.get("file")) not in eligible:
            continue
        gap = float(row.get("gap_seconds") or 0)
        if gap < SHOULDER_S:
            continue
        prop = proposals.get(row.get("proposal_id")) or {}
        if not prop:
            continue
        groups[row["winning_proposal_id"]].append((float(prop.get("score") or 0), gap, prop, row))
    per_winner = []
    for winner, group in groups.items():
        group.sort(key=lambda g: g[0], reverse=True)
        score, gap, prop, row = group[0]
        per_winner.append((score, gap, prop, row, winner))
    # Spread gap distances: take the best of short, mid, and long gaps first.
    bins = [(3.0, 10.0), (10.0, 18.0), (18.0, 25.1)]
    picked = []
    used = set()
    for lo, hi in bins:
        pool = [g for g in per_winner if lo <= g[1] < hi and id(g) not in used]
        pool.sort(key=lambda g: g[0], reverse=True)
        for g in pool[: max(1, n // 3)]:
            picked.append(g)
            used.add(id(g))
    rest = [g for g in per_winner if id(g) not in used]
    rest.sort(key=lambda g: g[0], reverse=True)
    for g in rest:
        if len(picked) >= n:
            break
        picked.append(g)
    items = []
    for score, gap, prop, row, winner in picked[:n]:
        items.append(_item(prop, "min_gap_event", gap_seconds=round(gap, 3), winning_proposal_id=winner))
    items.sort(key=lambda r: float(r["score"] or 0), reverse=True)
    return items


def continuous_windows(inputs: dict, keeps: list[dict], eligible: set | None, n: int, seed: int) -> list[dict]:
    """60–120s spans of valid dev audio. A point sample is not a review."""
    rng = np.random.default_rng(seed)
    keep_times: dict[str, np.ndarray] = defaultdict(list)
    for row in keeps:
        keep_times[row["session"]].append(float(row["elapsed_seconds"]))
    keep_arr = {k: np.asarray(v, dtype=np.float64) for k, v in keep_times.items()}
    candidates = []
    for sess in inputs["sessions"]:
        if sess.get("disposition") != "included":
            continue
        if not datasets.reviewable(sess["session"]):
            continue
        for wav in sess["wavs"]:
            if eligible is not None and (sess["session"], wav["file"]) not in eligible:
                continue
            dur = float(wav["duration_seconds"])
            if dur < 120:
                continue
            candidates.append((sess["session"], wav["file"], float(wav["start_seconds"]), dur))
    rng.shuffle(candidates)
    items = []
    per: Counter[str] = Counter()
    for session, file, start, dur in candidates:
        if per[session] >= 2:
            continue
        length = float(rng.uniform(60, 120))
        offset = float(rng.uniform(0, dur - length))
        abs_start = round(start + offset, 3)
        times = keep_arr.get(session)
        inside = 0
        if times is not None and times.size:
            inside = int(np.sum((times >= abs_start) & (times < abs_start + length)))
        items.append({
            "stratum": "continuous_window",
            "proposal_id": None,
            "session": session,
            "file": file,
            "elapsed_seconds": abs_start,
            "window_start": abs_start,
            "window_duration": round(length, 3),
            "keeps_inside": inside,
            "note": "Listen to the whole window. This is not a negative label.",
        })
        per[session] += 1
        if len(items) >= n:
            break
    return items


def Path_stem(name: str) -> str:
    return name[:-4] if name.endswith(".wav") else name


if __name__ == "__main__":
    main()
