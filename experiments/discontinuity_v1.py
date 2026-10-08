"""discontinuity_v1: break-start detector from temporal transition clusters.

Hypothesis
----------
legacy_v0 often senses transitions *inside* commercial breaks but treats each
peak as an independent IN. V1 keeps dense transition events (no top_k=6, no
25s NMS), scores whether a peak is the *start* of a break-like cluster, and
proposes that first plausible boundary.

Reuses legacy frame features (RMS / jump / flux / silence / composite). Does
not modify discontinuity_legacy_v0, acquisition, OUT logic, or gold.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

DETECTOR_ID = "discontinuity_v1"
FEATURE_SCHEMA = "break_cluster_v1_1"
SR = 48000.0

# Explicit, receipted. Not tuned against gold labels in secret.
PARAMS = {
    "detector_id": DETECTOR_ID,
    "feature_schema": FEATURE_SCHEMA,
    "hop_s": 0.125,
    # Stage 1 — transition events
    "shoulder_s": 2.0,
    "min_peak_score": 1.0,
    "strong_peak_score": 5.0,
    "near_silence_db": -45.0,
    # Stage 2 — windows for context
    "windows_s": (30.0, 60.0, 120.0),
    # Stage 3 — break-start score (deterministic, receipted weights)
    "w_boundary": 0.5,
    "w_future_minus_past_60": 2.0,
    "w_future_strong_60": 1.0,
    "w_future_silence_60": 0.75,
    "w_cluster_first": 2.5,
    "w_already_inside": 3.0,
    "w_no_future_60": 4.0,
    "propose_threshold": 4.0,
    # Separation between proposed *break starts* (not ad cuts)
    "break_min_gap_s": 90.0,
    # Cluster membership for "already inside" / rank
    "cluster_link_s": 45.0,
    "cluster_max_span_s": 240.0,
}


def local_maxima(scores: np.ndarray) -> np.ndarray:
    """Indices of strict local maxima (score[i] > score[i-1] and score[i] > score[i+1])."""
    if scores.size < 3:
        return np.array([], dtype=np.int64)
    left = scores[1:-1] > scores[:-2]
    right = scores[1:-1] > scores[2:]
    return np.flatnonzero(left & right).astype(np.int64) + 1


def collapse_shoulders(
    times: np.ndarray,
    scores: np.ndarray,
    peak_idx: np.ndarray,
    shoulder_s: float,
) -> np.ndarray:
    """Keep the highest peak in each shoulder_s neighborhood (greedy by score)."""
    if peak_idx.size == 0:
        return peak_idx
    order = peak_idx[np.argsort(scores[peak_idx])[::-1]]
    kept: list[int] = []
    kept_t: list[float] = []
    for idx in order:
        t = float(times[int(idx)])
        if any(abs(t - kt) < shoulder_s for kt in kept_t):
            continue
        kept.append(int(idx))
        kept_t.append(t)
    kept.sort(key=lambda i: float(times[i]))
    return np.asarray(kept, dtype=np.int64)


def transition_events_from_trace(trace: dict, params: dict | None = None) -> list[dict]:
    """Stage 1: local maxima → shoulder collapse → transition events."""
    p = {**PARAMS, **(params or {})}
    times = np.asarray(trace["session_sample_index"], dtype=np.float64) / SR
    scores = np.asarray(trace["composite_score"], dtype=np.float64)
    peaks = local_maxima(scores)
    peaks = peaks[scores[peaks] >= float(p["min_peak_score"])]
    peaks = collapse_shoulders(times, scores, peaks, float(p["shoulder_s"]))

    rms = np.asarray(trace["rms_db"], dtype=np.float64)
    flux_z = np.asarray(trace["flux_z"], dtype=np.float64)
    jump_z = np.asarray(trace["jump_z"], dtype=np.float64)
    silence = np.asarray(trace["silence_bonus"], dtype=np.float64)
    near = np.asarray(trace["near_silence"], dtype=np.uint8)
    frame = np.asarray(trace["frame_index"], dtype=np.int64)
    sample = np.asarray(trace["session_sample_index"], dtype=np.int64)

    events = []
    for i in peaks:
        events.append(
            {
                "elapsed_seconds": float(times[i]),
                "frame_index": int(frame[i]),
                "session_sample_index": int(sample[i]),
                "boundary_score": float(scores[i]),
                "rms_db": float(rms[i]),
                "flux_z": float(flux_z[i]),
                "jump_z": float(jump_z[i]),
                "silence_bonus": float(silence[i]),
                "near_silence": bool(near[i]),
                "strong": float(scores[i]) >= float(p["strong_peak_score"]),
            }
        )
    return events


def _count_in_window(times: np.ndarray, scores: np.ndarray, near: np.ndarray, t: float, lo: float, hi: float, strong: float):
    mask = (times > t + lo) & (times <= t + hi) if hi > 0 else (times >= t + lo) & (times < t + hi)
    # for past windows lo,hi negative: e.g. lo=-60, hi=0 → times in [t-60, t)
    if lo < 0 or hi <= 0:
        mask = (times >= t + lo) & (times < t + (0.0 if hi == 0 else hi))
        if hi == 0:
            mask = (times >= t + lo) & (times < t)
    n = int(np.count_nonzero(mask))
    if n == 0:
        return {"n": 0, "sum_score": 0.0, "max_score": 0.0, "n_strong": 0, "n_near_silence": 0}
    sel_s = scores[mask]
    sel_n = near[mask]
    return {
        "n": n,
        "sum_score": float(sel_s.sum()),
        "max_score": float(sel_s.max()),
        "n_strong": int(np.count_nonzero(sel_s >= strong)),
        "n_near_silence": int(np.count_nonzero(sel_n)),
    }


def attach_context(events: list[dict], params: dict | None = None) -> list[dict]:
    """Stage 2: temporal context. No gold labels."""
    p = {**PARAMS, **(params or {})}
    if not events:
        return []
    times = np.asarray([e["elapsed_seconds"] for e in events], dtype=np.float64)
    scores = np.asarray([e["boundary_score"] for e in events], dtype=np.float64)
    near = np.asarray([1 if e["near_silence"] else 0 for e in events], dtype=np.int8)
    strong = float(p["strong_peak_score"])
    link = float(p["cluster_link_s"])
    max_span = float(p["cluster_max_span_s"])

    # Forward-linked clusters: chain events within link seconds, span capped.
    cluster_id = np.full(len(events), -1, dtype=np.int64)
    cluster_rank = np.zeros(len(events), dtype=np.int64)
    cid = 0
    i = 0
    while i < len(events):
        start_t = times[i]
        j = i
        while j + 1 < len(events) and (times[j + 1] - times[j]) <= link and (times[j + 1] - start_t) <= max_span:
            j += 1
        for r, k in enumerate(range(i, j + 1)):
            cluster_id[k] = cid
            cluster_rank[k] = r + 1
        cid += 1
        i = j + 1

    enriched = []
    for idx, ev in enumerate(events):
        t = float(times[idx])
        ctx = {
            "cluster_id": int(cluster_id[idx]),
            "cluster_rank": int(cluster_rank[idx]),
            "cluster_size": int(np.count_nonzero(cluster_id == cluster_id[idx])),
        }
        for w in p["windows_s"]:
            w = float(w)
            past = _count_in_window(times, scores, near, t, -w, 0.0, strong)
            fut = _count_in_window(times, scores, near, t, 0.0, w, strong)
            # fix future window: (t, t+w]
            fut_mask = (times > t) & (times <= t + w)
            if np.any(fut_mask):
                fs = scores[fut_mask]
                fn = near[fut_mask]
                fut = {
                    "n": int(fut_mask.sum()),
                    "sum_score": float(fs.sum()),
                    "max_score": float(fs.max()),
                    "n_strong": int(np.count_nonzero(fs >= strong)),
                    "n_near_silence": int(np.count_nonzero(fn)),
                }
            else:
                fut = {"n": 0, "sum_score": 0.0, "max_score": 0.0, "n_strong": 0, "n_near_silence": 0}
            past_mask = (times >= t - w) & (times < t)
            if np.any(past_mask):
                ps = scores[past_mask]
                pn = near[past_mask]
                past = {
                    "n": int(past_mask.sum()),
                    "sum_score": float(ps.sum()),
                    "max_score": float(ps.max()),
                    "n_strong": int(np.count_nonzero(ps >= strong)),
                    "n_near_silence": int(np.count_nonzero(pn)),
                }
            else:
                past = {"n": 0, "sum_score": 0.0, "max_score": 0.0, "n_strong": 0, "n_near_silence": 0}
            ctx[f"prev_{int(w)}s"] = past
            ctx[f"next_{int(w)}s"] = fut
            ctx[f"density_delta_{int(w)}s"] = fut["n"] - past["n"]

        # time to next few events
        later = times[times > t]
        for k in range(1, 4):
            ctx[f"dt_next_{k}"] = float(later[k - 1] - t) if later.size >= k else None

        row = {**ev, "context": ctx}
        enriched.append(row)
    return enriched


def break_start_score(event: dict, params: dict | None = None) -> dict:
    """Stage 3: deterministic break-start score with receipted components."""
    p = {**PARAMS, **(params or {})}
    ctx = event["context"]
    boundary = float(event["boundary_score"])
    next60 = ctx["next_60s"]
    prev60 = ctx["prev_60s"]
    density_delta = float(ctx["density_delta_60s"])
    cluster_first = 1.0 if int(ctx["cluster_rank"]) == 1 else 0.0
    # Already inside: many transitions in the past minute relative to the future
    already_inside = 1.0 if prev60["n"] >= 2 and prev60["n"] >= next60["n"] else 0.0
    if prev60["n"] >= 3 and density_delta <= 0:
        already_inside = 1.0
    no_future = 1.0 if next60["n"] == 0 else 0.0

    components = {
        "boundary": float(p["w_boundary"]) * boundary,
        "future_minus_past_60": float(p["w_future_minus_past_60"]) * density_delta,
        "future_strong_60": float(p["w_future_strong_60"]) * float(next60["n_strong"]),
        "future_silence_60": float(p["w_future_silence_60"]) * float(next60["n_near_silence"]),
        "cluster_first": float(p["w_cluster_first"]) * cluster_first,
        "already_inside_penalty": -float(p["w_already_inside"]) * already_inside,
        "no_future_penalty": -float(p["w_no_future_60"]) * no_future,
    }
    total = float(sum(components.values()))
    return {
        "break_start_score": total,
        "components": components,
        "flags": {
            "cluster_first": bool(cluster_first),
            "already_inside": bool(already_inside),
            "no_future_60": bool(no_future),
            "density_delta_60s": density_delta,
        },
    }


def propose_break_starts(events: list[dict], params: dict | None = None) -> tuple[list[dict], list[dict]]:
    """Score every transition; keep break starts above threshold with break_min_gap_s."""
    p = {**PARAMS, **(params or {})}
    scored = []
    for ev in events:
        receipt = break_start_score(ev, p)
        scored.append({**ev, **receipt})

    order = sorted(scored, key=lambda e: (-float(e["break_start_score"]), float(e["elapsed_seconds"])))
    keeps: list[dict] = []
    suppressed: list[dict] = []
    gap = float(p["break_min_gap_s"])
    thr = float(p["propose_threshold"])

    for row in order:
        if float(row["break_start_score"]) < thr:
            suppressed.append({**row, "action": "reject", "reason": "below_threshold"})
            continue
        blocker = None
        for k in keeps:
            if abs(float(row["elapsed_seconds"]) - float(k["elapsed_seconds"])) < gap:
                blocker = k
                break
        if blocker is not None:
            suppressed.append(
                {
                    **row,
                    "action": "suppress",
                    "reason": "break_min_gap",
                    "winning_elapsed_seconds": blocker["elapsed_seconds"],
                }
            )
            continue
        keeps.append({**row, "action": "keep", "reason": "break_start"})

    keeps.sort(key=lambda e: float(e["elapsed_seconds"]))
    return keeps, suppressed


def load_session_events_from_traces(trace_dir: Path, params: dict | None = None) -> list[dict]:
    """Build session-ordered transition events from a legacy run's npz traces."""
    all_events: list[dict] = []
    for npz in sorted(trace_dir.glob("audio_*.npz")):
        z = np.load(npz, allow_pickle=True)
        trace = {k: z[k] for k in z.files}
        for ev in transition_events_from_trace(trace, params):
            ev["file"] = npz.name.replace(".npz", ".wav")
            all_events.append(ev)
    all_events.sort(key=lambda e: float(e["elapsed_seconds"]))
    return attach_context(all_events, params)
