"""discontinuity_v1_1: separate break-episode detection from onset localization.

V1 kept dense transitions (good) and dropped top_k=6 (good), but defined
"clusters" by chaining peaks within 45s — which never separates anything when
median inter-peak gap is ~3s. That made cluster_rank meaningless and forced one
score to answer both "is there a break?" and "when did it start?"

V1.1:
  transitions (same legacy features)
       ↓
  rolling temporal intensity (no linked clusters)
       ↓
  EPISODE DETECT — does this region look break-like?
       ↓
  ONSET LOCALIZE — where did the intensity regime change?
       ↓
  BREAK IN

Partial session windows are rate-normalized / eligibility-gated so missing
history at t≈0 is not treated as "zero past transitions".
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

import discontinuity_v1 as v0

DETECTOR_ID = "discontinuity_v1_1"
FEATURE_SCHEMA = "break_episode_localize_v1_1"
SR = v0.SR

PARAMS = {
    "detector_id": DETECTOR_ID,
    "feature_schema": FEATURE_SCHEMA,
    # Stage 1 — same dense transitions as v1 (no top_k, no 25s NMS)
    "shoulder_s": 2.0,
    "min_peak_score": 1.0,
    "strong_peak_score": 5.0,
    # Rolling intensity windows
    "windows_s": (15.0, 30.0, 60.0),
    # Episode detection (region looks break-like). Receipted, not swept.
    "w_ep_rise_30": 1.0,
    "w_ep_rise_60": 0.5,
    "w_ep_future_strong_30": 0.75,
    "w_ep_future_silence_30": 0.5,
    "w_ep_boundary": 0.15,
    "episode_threshold": 3.0,
    "episode_min_gap_s": 90.0,
    # Partial-window eligibility: need this much observable time
    "min_obs_s": 15.0,
    # Onset localization: search back from episode evidence
    "localize_lookback_s": 60.0,
    "w_loc_rise_30": 1.0,  # applied to rise*30 event units
    "w_loc_silence": 0.5,
    "w_loc_boundary": 0.15,
    "localize_min_rise": 0.5,  # ≥0.5 extra events / 30s (used as rate/30)
    "localize_min_future_rate": 0.0333,  # ≥1 strong event / 30s
    "onset_dedupe_s": 60.0,
}


def _window_stats(
    times: np.ndarray,
    scores: np.ndarray,
    near: np.ndarray,
    t: float,
    duration: float,
    *,
    future: bool,
    strong: float,
    session_start: float,
    session_end: float,
    score_floor: float | None = None,
) -> dict:
    if future:
        lo, hi = t, t + duration
        obs = max(0.0, min(session_end, hi) - t)
        mask = (times > t) & (times <= t + duration)
    else:
        lo, hi = t - duration, t
        obs = max(0.0, t - max(session_start, lo))
        mask = (times >= t - duration) & (times < t)
    if score_floor is not None:
        mask = mask & (scores >= score_floor)
    n = int(np.count_nonzero(mask))
    if n == 0:
        mass = 0.0
        mx = 0.0
        n_strong = 0
        n_sil = 0
    else:
        sel = scores[mask]
        mass = float(sel.sum())
        mx = float(sel.max())
        n_strong = int(np.count_nonzero(sel >= strong))
        n_sil = int(np.count_nonzero(near[mask]))
    rate = (n / obs) if obs > 1e-9 else 0.0
    mass_rate = (mass / obs) if obs > 1e-9 else 0.0
    return {
        "n": n,
        "obs_s": float(obs),
        "rate": float(rate),
        "sum_score": mass,
        "mass_rate": float(mass_rate),
        "max_score": mx,
        "n_strong": n_strong,
        "strong_rate": float(n_strong / obs) if obs > 1e-9 else 0.0,
        "n_near_silence": n_sil,
        "silence_rate": float(n_sil / obs) if obs > 1e-9 else 0.0,
        "complete": bool(obs >= duration - 1e-6),
    }


def attach_rolling_intensity(
    events: list[dict],
    session_start: float,
    session_end: float,
    params: dict | None = None,
) -> list[dict]:
    """Rolling rates. No linked clusters. Partial windows are explicit."""
    p = {**PARAMS, **(params or {})}
    if not events:
        return []
    times = np.asarray([e["elapsed_seconds"] for e in events], dtype=np.float64)
    scores = np.asarray([e["boundary_score"] for e in events], dtype=np.float64)
    near = np.asarray([1 if e["near_silence"] else 0 for e in events], dtype=np.int8)
    strong = float(p["strong_peak_score"])
    min_obs = float(p["min_obs_s"])

    out = []
    for idx, ev in enumerate(events):
        t = float(times[idx])
        ctx: dict = {
            "session_start": session_start,
            "session_end": session_end,
        }
        eligible = True
        for w in p["windows_s"]:
            w = float(w)
            past = _window_stats(
                times, scores, near, t, w, future=False, strong=strong,
                session_start=session_start, session_end=session_end,
            )
            fut = _window_stats(
                times, scores, near, t, w, future=True, strong=strong,
                session_start=session_start, session_end=session_end,
            )
            # Strong-only intensity: program vs break contrast (all-peak rates are ~flat)
            past_s = _window_stats(
                times, scores, near, t, w, future=False, strong=strong,
                session_start=session_start, session_end=session_end, score_floor=strong,
            )
            fut_s = _window_stats(
                times, scores, near, t, w, future=True, strong=strong,
                session_start=session_start, session_end=session_end, score_floor=strong,
            )
            ctx[f"prev_{int(w)}s"] = past
            ctx[f"next_{int(w)}s"] = fut
            ctx[f"rise_{int(w)}s"] = fut["rate"] - past["rate"]
            ctx[f"mass_rise_{int(w)}s"] = fut["mass_rate"] - past["mass_rate"]
            ctx[f"prev_strong_{int(w)}s"] = past_s
            ctx[f"next_strong_{int(w)}s"] = fut_s
            ctx[f"rise_strong_{int(w)}s"] = fut_s["rate"] - past_s["rate"]
            if past["obs_s"] < min_obs or fut["obs_s"] < min_obs:
                eligible = False
        ctx["eligible"] = eligible
        ctx["session_edge"] = (t - session_start < float(p["windows_s"][-1])) or (
            session_end - t < float(p["windows_s"][-1])
        )
        out.append({**ev, "context": ctx})
    return out


def episode_score(event: dict, params: dict | None = None) -> dict:
    """Does the surrounding region look like a commercial-break episode?"""
    p = {**PARAMS, **(params or {})}
    ctx = event["context"]
    if not ctx.get("eligible", False):
        return {
            "episode_score": float("-inf"),
            "components": {},
            "flags": {"eligible": False, "session_edge": ctx.get("session_edge", False)},
            "actionable": False,
        }
    rise30 = float(ctx["rise_strong_30s"]) * 30.0
    rise60 = float(ctx["rise_strong_60s"]) * 60.0
    fut30 = ctx["next_strong_30s"]
    components = {
        "rise_strong_30": float(p["w_ep_rise_30"]) * rise30,
        "rise_strong_60": float(p["w_ep_rise_60"]) * (rise60 / 2.0),
        "future_strong_30": float(p["w_ep_future_strong_30"]) * float(fut30["rate"]) * 30.0,
        "future_silence_30": float(p["w_ep_future_silence_30"]) * float(ctx["next_30s"]["silence_rate"]) * 30.0,
        "boundary": float(p["w_ep_boundary"]) * float(event["boundary_score"]),
    }
    total = float(sum(components.values()))
    return {
        "episode_score": total,
        "components": components,
        "flags": {
            "eligible": True,
            "session_edge": bool(ctx.get("session_edge")),
            "rise_strong_30_events": rise30,
            "rise_strong_60_events": rise60,
        },
        "actionable": total >= float(p["episode_threshold"]),
    }


def localize_onset(
    anchor: dict,
    events: list[dict],
    params: dict | None = None,
) -> dict:
    """Search backward from episode evidence for a regime-change boundary.

    Onset = start of the contiguous elevated-intensity streak that contains the
    anchor — not the strongest jump, and not the earliest rise anywhere in 60s.
    """
    p = {**PARAMS, **(params or {})}
    t_anchor = float(anchor["elapsed_seconds"])
    lookback = float(p["localize_lookback_s"])
    min_future_rate = float(p.get("localize_min_future_rate", 2.0 / 30.0))  # ≥2 events / 30s
    rise_thr = float(p["localize_min_rise"]) / 30.0  # rate units

    window = [
        e
        for e in events
        if (t_anchor - lookback) <= float(e["elapsed_seconds"]) <= t_anchor + 1e-9
    ]
    if not window:
        return {
            "onset": anchor,
            "method": "anchor_fallback",
            "candidates_considered": 0,
            "reason": "empty_lookback",
        }

    def elevated(e: dict) -> bool:
        ctx = e.get("context") or {}
        if not ctx:
            return False
        # Regime uses strong-peak intensity so program vs break can differ.
        fut = ctx.get("next_strong_30s") or {}
        rise = float(ctx.get("rise_strong_30s") or 0.0)
        return float(fut.get("rate") or 0.0) >= min_future_rate or rise >= rise_thr

    # Contiguous elevated streak ending at the event nearest the anchor.
    # Walk backward from the last window event; collect while elevated.
    streak: list[dict] = []
    for e in reversed(window):
        if elevated(e):
            streak.append(e)
        elif streak:
            break
    streak.reverse()

    if streak:
        chosen = streak[0]
        method = "elevated_streak_start"
        loc_score = float((chosen.get("context") or {}).get("rise_strong_30s") or 0.0) * 30.0
        rise_events = loc_score
    else:
        # No elevated streak: pick max strong-regime rise in window (still not max boundary)
        scored = []
        for e in window:
            ctx = e.get("context") or {}
            rise_events = float(ctx.get("rise_strong_30s") or 0.0) * 30.0
            sil = float((ctx.get("next_30s") or {}).get("silence_rate") or 0.0) * 30.0
            loc = (
                float(p["w_loc_rise_30"]) * rise_events
                + float(p["w_loc_silence"]) * sil
                + float(p["w_loc_boundary"]) * float(e["boundary_score"])
            )
            scored.append((loc, rise_events, e))
        if not scored:
            chosen = anchor
            method = "anchor_fallback"
            loc_score = 0.0
            rise_events = 0.0
        else:
            loc_score, rise_events, chosen = max(scored, key=lambda r: r[0])
            method = "max_regime_score"

    return {
        "onset": chosen,
        "method": method,
        "localize_score": float(loc_score),
        "rise_30s": float(rise_events),
        "candidates_considered": len(window),
        "streak_len": len(streak),
        "anchor_elapsed_seconds": t_anchor,
        "anchor_episode_score": float(anchor.get("episode_score", 0.0)),
    }


def detect_episodes(events: list[dict], params: dict | None = None) -> tuple[list[dict], list[dict]]:
    """Score every transition as episode evidence; NMS anchors."""
    p = {**PARAMS, **(params or {})}
    scored = []
    rejected = []
    for ev in events:
        ep = episode_score(ev, p)
        row = {**ev, **ep}
        if not ep.get("actionable"):
            rejected.append({**row, "action": "reject", "reason": "below_episode_threshold_or_ineligible"})
            continue
        scored.append(row)

    order = sorted(scored, key=lambda e: (-float(e["episode_score"]), float(e["elapsed_seconds"])))
    anchors: list[dict] = []
    suppressed: list[dict] = []
    gap = float(p["episode_min_gap_s"])
    for row in order:
        blocker = None
        for a in anchors:
            if abs(float(row["elapsed_seconds"]) - float(a["elapsed_seconds"])) < gap:
                blocker = a
                break
        if blocker is not None:
            suppressed.append(
                {
                    **row,
                    "action": "suppress",
                    "reason": "episode_min_gap",
                    "winning_elapsed_seconds": blocker["elapsed_seconds"],
                }
            )
            continue
        anchors.append({**row, "action": "episode_anchor", "reason": "break_like_region"})
    anchors.sort(key=lambda e: float(e["elapsed_seconds"]))
    return anchors, rejected + suppressed


def propose_break_ins(events: list[dict], params: dict | None = None) -> tuple[list[dict], list[dict], list[dict]]:
    """Episode detect → localize onset → dedupe."""
    p = {**PARAMS, **(params or {})}
    anchors, ep_reject = detect_episodes(events, p)
    proposals = []
    for anchor in anchors:
        loc = localize_onset(anchor, events, p)
        onset = loc["onset"]
        proposals.append(
            {
                **onset,
                "episode_score": float(anchor["episode_score"]),
                "episode_components": anchor.get("components"),
                "episode_flags": anchor.get("flags"),
                "anchor_elapsed_seconds": float(anchor["elapsed_seconds"]),
                "localization": {
                    "method": loc["method"],
                    "localize_score": loc.get("localize_score"),
                    "rise_30s": loc.get("rise_30s"),
                    "candidates_considered": loc["candidates_considered"],
                    "anchor_elapsed_seconds": loc["anchor_elapsed_seconds"],
                    "anchor_episode_score": loc["anchor_episode_score"],
                },
                "action": "keep",
                "reason": "localized_break_onset",
            }
        )

    # Dedupe onsets (two anchors can localize to the same start)
    proposals.sort(key=lambda r: (-float(r["episode_score"]), float(r["elapsed_seconds"])))
    keeps: list[dict] = []
    suppressed: list[dict] = []
    dedupe = float(p["onset_dedupe_s"])
    for row in proposals:
        blocker = None
        for k in keeps:
            if abs(float(row["elapsed_seconds"]) - float(k["elapsed_seconds"])) < dedupe:
                blocker = k
                break
        if blocker is not None:
            suppressed.append(
                {
                    **row,
                    "action": "suppress",
                    "reason": "onset_dedupe",
                    "winning_elapsed_seconds": blocker["elapsed_seconds"],
                }
            )
            continue
        keeps.append(row)
    keeps.sort(key=lambda e: float(e["elapsed_seconds"]))
    return keeps, anchors, ep_reject + suppressed


def load_session_events_from_traces(trace_dir: Path, params: dict | None = None) -> list[dict]:
    p = {**PARAMS, **(params or {})}
    # Reuse v1 peak extraction with v1.1 peak params
    peak_params = {
        "shoulder_s": p["shoulder_s"],
        "min_peak_score": p["min_peak_score"],
        "strong_peak_score": p["strong_peak_score"],
    }
    raw: list[dict] = []
    session_end = 0.0
    for npz in sorted(trace_dir.glob("audio_*.npz")):
        z = np.load(npz, allow_pickle=True)
        trace = {k: z[k] for k in z.files}
        for ev in v0.transition_events_from_trace(trace, {**v0.PARAMS, **peak_params}):
            ev["file"] = npz.name.replace(".npz", ".wav")
            raw.append(ev)
            session_end = max(session_end, float(ev["elapsed_seconds"]))
    raw.sort(key=lambda e: float(e["elapsed_seconds"]))
    if not raw:
        return []
    # Extend session_end slightly past last event using last chunk length estimate
    session_start = 0.0
    # Use last sample index if available
    last = raw[-1]
    session_end = max(session_end, float(last["session_sample_index"]) / SR + 1.0)
    return attach_rolling_intensity(raw, session_start, session_end, p)
