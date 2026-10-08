#!/usr/bin/env python3
"""causal_onset_probe_v1 — past + current only.

Hypothesis under test
---------------------
Commercial INs leave a distinctive *causal* signature (current acoustics +
past transition intensity) that can rank true onsets above isolated program
transitions — without any future evidence.

Forbidden
---------
next_*, future peaks, future silence, episode scores that use future windows.

Allowed
-------
boundary_score, jump_z, flux_z, near_silence, rms_db,
past transition / strong / silence rates over 5/15/30/60s.

Does not modify V1.1, truth, OUT, or holdouts. No ML.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

import ledger
import discontinuity_v1_1 as v11

PROBE_ID = "causal_onset_probe_v1"
# Past-only windows (includes a short 5s window V1.1 did not archive)
PAST_WINDOWS = (5.0, 15.0, 30.0, 60.0)
STRONG = float(v11.PARAMS["strong_peak_score"])
MIN_OBS = float(v11.PARAMS["min_obs_s"])


def load_truth(session: str, cov_from: float, cov_to: float) -> list[dict]:
    truth = [
        t
        for t in ledger.resolve_ledger(ledger.read_jsonl(ledger.TRUTH_PATH), "gold_id")
        if t.get("event", "ad_break") == "ad_break"
        and t["session"] == session
        and cov_from <= float(t["start_seconds"]) < cov_to
        and t.get("event_class") == "commercial"
        and t.get("desired_action") == "mute"
        and t.get("confidence") != "unsure"
    ]
    truth.sort(key=lambda t: float(t["start_seconds"]))
    return truth


def load_transitions(v11_run: str, session: str, cov_from: float, cov_to: float) -> list[dict]:
    path = ledger.RUNS / v11_run / "transitions" / session / "transitions.jsonl"
    rows = ledger.read_jsonl(path)
    return [e for e in rows if cov_from <= float(e["elapsed_seconds"]) < cov_to]


def attach_causal_context(events: list[dict], session_start: float, session_end: float) -> list[dict]:
    """Past-only rolling intensity. Future keys are never written."""
    if not events:
        return []
    times = np.asarray([e["elapsed_seconds"] for e in events], dtype=np.float64)
    scores = np.asarray([e["boundary_score"] for e in events], dtype=np.float64)
    near = np.asarray([1 if e["near_silence"] else 0 for e in events], dtype=np.int8)

    out = []
    for idx, ev in enumerate(events):
        t = float(times[idx])
        causal: dict = {
            "boundary_score": float(ev["boundary_score"]),
            "jump_z": float(ev.get("jump_z") or 0.0),
            "flux_z": float(ev.get("flux_z") or 0.0),
            "rms_db": float(ev.get("rms_db") or 0.0),
            "near_silence": bool(ev.get("near_silence")),
            "strong": bool(ev.get("strong")),
            "silence_bonus": float(ev.get("silence_bonus") or 0.0),
        }
        eligible = True
        for w in PAST_WINDOWS:
            past = v11._window_stats(
                times,
                scores,
                near,
                t,
                float(w),
                future=False,
                strong=STRONG,
                session_start=session_start,
                session_end=session_end,
            )
            past_s = v11._window_stats(
                times,
                scores,
                near,
                t,
                float(w),
                future=False,
                strong=STRONG,
                session_start=session_start,
                session_end=session_end,
                score_floor=STRONG,
            )
            wi = int(w)
            causal[f"past_n_{wi}s"] = past["n"]
            causal[f"past_rate_{wi}s"] = past["rate"]
            causal[f"past_mass_rate_{wi}s"] = past["mass_rate"]
            causal[f"past_strong_n_{wi}s"] = past_s["n"]
            causal[f"past_strong_rate_{wi}s"] = past_s["rate"]
            causal[f"past_silence_n_{wi}s"] = past["n_near_silence"]
            causal[f"past_silence_rate_{wi}s"] = past["silence_rate"]
            causal[f"past_obs_{wi}s"] = past["obs_s"]
            causal[f"past_complete_{wi}s"] = past["complete"]
            if past["obs_s"] < min(MIN_OBS, float(w)):
                eligible = False
        # Seconds since previous transition (0 if first)
        if idx == 0:
            causal["gap_from_prev_s"] = None
        else:
            causal["gap_from_prev_s"] = float(times[idx] - times[idx - 1])
        causal["eligible"] = eligible and (t - session_start >= MIN_OBS)
        causal["session_edge"] = (t - session_start < 60.0) or (session_end - t < 60.0)
        out.append({**ev, "causal": causal})
    return out


FEATURE_KEYS = [
    "boundary_score",
    "jump_z",
    "flux_z",
    "rms_db",
    "near_silence",
    "silence_bonus",
    "gap_from_prev_s",
    "past_rate_5s",
    "past_rate_15s",
    "past_rate_30s",
    "past_rate_60s",
    "past_strong_rate_5s",
    "past_strong_rate_15s",
    "past_strong_rate_30s",
    "past_strong_rate_60s",
    "past_silence_rate_15s",
    "past_silence_rate_30s",
    "past_silence_rate_60s",
    "past_n_30s",
    "past_strong_n_30s",
]


def feature_vector(causal: dict) -> dict:
    row = {}
    for k in FEATURE_KEYS:
        v = causal.get(k)
        if k == "near_silence":
            row[k] = 1.0 if v else 0.0
        elif v is None:
            row[k] = float("nan")
        else:
            row[k] = float(v)
    return row


def label_transitions(events: list[dict], truth: list[dict]) -> list[dict]:
    """true_onset | inside_break | near_return | program."""
    labeled = []
    for ev in events:
        t = float(ev["elapsed_seconds"])
        role = "program"
        gold_id = None
        gold_delta = None
        for g in truth:
            gin = float(g["start_seconds"])
            gout = float(g["end_seconds"])
            if abs(t - gin) <= 2.0:
                role = "true_onset"
                gold_id = g["gold_id"]
                gold_delta = t - gin
                break
            if gin < t < gout:
                role = "inside_break"
                gold_id = g["gold_id"]
                break
            if abs(t - gout) <= 20.0:
                role = "near_return"
                gold_id = g["gold_id"]
                break
        labeled.append({**ev, "role": role, "gold_id": gold_id, "gold_delta": gold_delta})
    return labeled


def oracle_true_onsets(events: list[dict], truth: list[dict]) -> list[dict]:
    """One nearest transition per gold IN (regardless of ±2s)."""
    picks = []
    for g in truth:
        gin = float(g["start_seconds"])
        best = min(events, key=lambda e: abs(float(e["elapsed_seconds"]) - gin))
        delta = float(best["elapsed_seconds"]) - gin
        picks.append(
            {
                **best,
                "role": "true_onset_oracle",
                "gold_id": g["gold_id"],
                "gold_in": gin,
                "gold_delta": delta,
            }
        )
    return picks


def summarize_group(rows: list[dict], keys: list[str]) -> dict:
    out = {}
    for k in keys:
        vals = []
        for r in rows:
            v = r["causal"].get(k) if "causal" in r else None
            if k == "near_silence":
                vals.append(1.0 if (r.get("causal") or {}).get("near_silence") else 0.0)
                continue
            if v is None:
                continue
            try:
                fv = float(v)
            except (TypeError, ValueError):
                continue
            if np.isfinite(fv):
                vals.append(fv)
        if not vals:
            out[k] = {"n": 0}
            continue
        arr = np.asarray(vals, dtype=np.float64)
        out[k] = {
            "n": int(arr.size),
            "mean": float(arr.mean()),
            "median": float(np.median(arr)),
            "p25": float(np.percentile(arr, 25)),
            "p75": float(np.percentile(arr, 75)),
        }
    return out


def overlap_score(true_stats: dict, prog_stats: dict) -> list[dict]:
    """How much do distributions overlap? Simple median-gap / pooled IQR."""
    rows = []
    for k in FEATURE_KEYS:
        t = true_stats.get(k) or {}
        p = prog_stats.get(k) or {}
        if t.get("n", 0) < 3 or p.get("n", 0) < 3:
            continue
        gap = abs(float(t["median"]) - float(p["median"]))
        iqr_t = float(t["p75"]) - float(t["p25"])
        iqr_p = float(p["p75"]) - float(p["p25"])
        pooled = 0.5 * (iqr_t + iqr_p) + 1e-9
        # Also fraction of program above/below true median direction
        rows.append(
            {
                "feature": k,
                "true_median": t["median"],
                "program_median": p["median"],
                "true_mean": t["mean"],
                "program_mean": p["mean"],
                "median_gap": gap,
                "separation_iqr": gap / pooled,
                "true_p25_p75": [t["p25"], t["p75"]],
                "program_p25_p75": [p["p25"], p["p75"]],
                "iqr_overlap": not (t["p75"] < p["p25"] or p["p75"] < t["p25"]),
            }
        )
    rows.sort(key=lambda r: -r["separation_iqr"])
    return rows


def rank_oracle_vs_local_program(
    events: list[dict],
    truth: list[dict],
    score_fn,
    local_radius_s: float = 90.0,
) -> list[dict]:
    """For each gold: rank of oracle transition among local program+onset candidates
    using a causal score. Inside-break / near-return excluded from competitors.
    """
    results = []
    for g in truth:
        gin = float(g["start_seconds"])
        gout = float(g["end_seconds"])
        oracle = min(events, key=lambda e: abs(float(e["elapsed_seconds"]) - gin))
        oracle_t = float(oracle["elapsed_seconds"])
        local: list[dict] = []
        for e in events:
            t = float(e["elapsed_seconds"])
            if abs(t - gin) > local_radius_s:
                continue
            # Competitors are program-side only; always keep the oracle itself.
            if e is not oracle and gin < t < gout:
                continue
            if e is not oracle and not (e.get("causal") or {}).get("eligible", True):
                continue
            local.append(e)
        if oracle not in local:
            local.append(oracle)
        scored = []
        for e in local:
            s = score_fn(e["causal"])
            scored.append((s, float(e["elapsed_seconds"]), e))
        scored.sort(key=lambda r: (-r[0], abs(r[1] - gin)))
        rank = next(i for i, (_, t, _) in enumerate(scored, 1) if abs(t - oracle_t) < 1e-9)
        results.append(
            {
                "gold_in": gin,
                "oracle_s": oracle_t,
                "oracle_delta_s": oracle_t - gin,
                "n_local": len(local),
                "rank": rank,
                "top_s": scored[0][1],
                "top_score": scored[0][0],
                "oracle_score": next(s for s, t, _ in scored if abs(t - oracle_t) < 1e-9),
                "top_is_oracle": rank == 1,
            }
        )
    return results


def score_boundary(c: dict) -> float:
    return float(c["boundary_score"])


def score_silence_boundary(c: dict) -> float:
    return float(c["boundary_score"]) + (3.0 if c.get("near_silence") else 0.0)


def score_quiet_past(c: dict) -> float:
    """Prefer audible boundary after a quieter past (program-like → break)."""
    past = float(c.get("past_strong_rate_30s") or 0.0)
    return float(c["boundary_score"]) - 40.0 * past + (2.0 if c.get("near_silence") else 0.0)


def score_handcrafted(c: dict) -> float:
    """Receipted causal probe score — not tuned, just the obvious combination."""
    return (
        0.5 * float(c["boundary_score"])
        + 0.25 * float(c.get("jump_z") or 0.0)
        + 0.25 * float(c.get("flux_z") or 0.0)
        + (2.0 if c.get("near_silence") else 0.0)
        - 30.0 * float(c.get("past_strong_rate_30s") or 0.0)
        - 15.0 * float(c.get("past_rate_30s") or 0.0)
        + 10.0 * float(c.get("past_silence_rate_30s") or 0.0)
    )


def score_gap_and_quiet5(c: dict) -> float:
    """Uses the two population separators (larger prev-gap, emptier past 5s)."""
    gap = c.get("gap_from_prev_s")
    gap = 0.0 if gap is None else float(gap)
    return gap - 20.0 * float(c.get("past_rate_5s") or 0.0) + 0.3 * float(c["boundary_score"])


def render_md(payload: dict) -> str:
    sep = payload["separation"]
    lines = [
        "# Causal onset probe v1",
        "",
        f"Probe: `{PROBE_ID}` · transitions from `{payload['transitions_run']}`",
        f"Session `{payload['session']}` · gold `{payload['gold']}`",
        "",
        "Future evidence is **forbidden**. Features are current acoustics + past "
        "transition intensity only.",
        "",
        "## Cohorts",
        "",
        f"- true_onset (transition within ±2s of gold IN): **{payload['counts']['true_onset']}**",
        f"- program (outside breaks, not near OUT): **{payload['counts']['program']}**",
        f"- inside_break (excluded from separation): {payload['counts']['inside_break']}",
        f"- near_return (excluded): {payload['counts']['near_return']}",
        "",
        "## Feature table — TRUE IN vs PROGRAM",
        "",
        "| feature | true median | program median | median gap | sep/IQR | IQR overlap? |",
        "|---|---:|---:|---:|---:|:---:|",
    ]
    for r in sep:
        lines.append(
            f"| `{r['feature']}` | {r['true_median']:.3f} | {r['program_median']:.3f} | "
            f"{r['median_gap']:.3f} | {r['separation_iqr']:.2f} | "
            f"{'yes' if r['iqr_overlap'] else 'NO'} |"
        )

    lines += [
        "",
        "## Ranking probes (local ±90s, causal scores only)",
        "",
        "For each gold IN: rank of the oracle nearest-transition among eligible "
        "local non-inside-break candidates.",
        "",
    ]
    for name, block in payload["ranking"].items():
        n_top = sum(1 for r in block if r["top_is_oracle"])
        lines.append(f"### `{name}` — oracle ranked #1 for {n_top}/{len(block)}")
        lines.append("")
        lines.append("| gold IN | oracle Δ | rank / n | top t |")
        lines.append("|---:|---:|---:|---:|")
        for r in block:
            lines.append(
                f"| {r['gold_in']:.1f} | {r['oracle_delta_s']:+.3f} | "
                f"{r['rank']}/{r['n_local']} | {r['top_s']:.3f} |"
            )
        lines.append("")

    lines += [
        "## Verdict",
        "",
        payload["verdict"],
        "",
        "## What this does / does not claim",
        "",
        "- Does **not** claim a shipping causal detector.",
        "- Does claim whether handcrafted past+current features contain enough "
        "information to prefer true INs over isolated program edits.",
        "- V1.1 remains the offline teacher (future context allowed).",
        "",
    ]
    return "\n".join(lines)


def decide_verdict(sep: list[dict], ranking: dict) -> str:
    """Local ranking is decisive. Global median gaps are hints only."""
    strong = [r for r in sep if (not r["iqr_overlap"]) or r["separation_iqr"] >= 1.0]
    best_name = None
    best_top = -1
    best_n = 1
    for name, block in ranking.items():
        n_top = sum(1 for r in block if r["top_is_oracle"])
        if n_top > best_top:
            best_top = n_top
            best_name = name
            best_n = len(block) or 1
    rate = best_top / best_n

    # Population separators that fail local ranking are noted but not "promising"
    if rate >= 0.5:
        return (
            f"PROMISING_CAUSAL — best causal score `{best_name}` ranks oracle #1 "
            f"for {best_top}/{best_n} gold INs; {len(strong)} features show "
            "population separation. Deterministic causal v2 is worth attempting before ML."
        )
    if rate >= 0.35 or len(strong) >= 2:
        return (
            f"WEAK_CAUSAL — population hints exist ({len(strong)} non-overlapping/"
            f"strong features: {', '.join(r['feature'] for r in strong[:4])}), "
            f"but best local ranking (`{best_name}`) is only {best_top}/{best_n} top-1. "
            "Handcrafted past+current evidence does not yet reliably identify which "
            "audible transition is the commercial IN. Probe further combinations "
            "before declaring another evidence channel mandatory."
        )
    return (
        f"INSUFFICIENT_CAUSAL — true INs and program transitions are not rankable "
        f"with current causal features (best `{best_name}` top-1 = {best_top}/{best_n}). "
        "This is the evidence threshold for considering another channel "
        "(fingerprint / small classifier), not for abandoning structure or V1.1 as teacher."
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--v11-run", default="20260921T173219Z_discontinuity_v1_1")
    ap.add_argument("--gold", default="GOLD_DEV_V1")
    args = ap.parse_args()

    manifest = ledger.load_gold_manifest(args.gold)
    ranges = [r for r in (manifest.get("coverage") or []) if r.get("fully_annotated")]
    session = ranges[0]["session"]
    cov_from = float(ranges[0]["from_seconds"])
    cov_to = float(ranges[0]["to_seconds"])

    truth = load_truth(session, cov_from, cov_to)
    raw = load_transitions(args.v11_run, session, cov_from, cov_to)
    # session end from last transition or coverage
    session_end = max(cov_to, max(float(e["elapsed_seconds"]) for e in raw) + 1.0)
    events = attach_causal_context(raw, cov_from, session_end)
    labeled = label_transitions(events, truth)

    true_rows = [e for e in labeled if e["role"] == "true_onset"]
    # Prefer oracle picks (one per gold) for the TRUE cohort summary
    oracle = oracle_true_onsets(events, truth)
    program = [e for e in labeled if e["role"] == "program" and (e.get("causal") or {}).get("eligible")]
    # Cap program sample for stability? Use all eligible — forensic honesty.
    counts = {
        "true_onset": len(true_rows),
        "true_onset_oracle": len(oracle),
        "program": len(program),
        "inside_break": sum(1 for e in labeled if e["role"] == "inside_break"),
        "near_return": sum(1 for e in labeled if e["role"] == "near_return"),
        "all": len(labeled),
    }

    true_stats = summarize_group(oracle, FEATURE_KEYS)
    prog_stats = summarize_group(program, FEATURE_KEYS)
    separation = overlap_score(true_stats, prog_stats)

    ranking = {
        "boundary_only": rank_oracle_vs_local_program(events, truth, score_boundary),
        "boundary_plus_silence": rank_oracle_vs_local_program(events, truth, score_silence_boundary),
        "quiet_past": rank_oracle_vs_local_program(events, truth, score_quiet_past),
        "gap_and_quiet5": rank_oracle_vs_local_program(events, truth, score_gap_and_quiet5),
        "handcrafted": rank_oracle_vs_local_program(events, truth, score_handcrafted),
    }
    verdict = decide_verdict(separation, ranking)

    # Per-gold causal feature dump for the oracle transition
    per_gold = []
    for o in oracle:
        per_gold.append(
            {
                "gold_id": o["gold_id"],
                "gold_in": o["gold_in"],
                "oracle_s": float(o["elapsed_seconds"]),
                "delta_s": o["gold_delta"],
                "causal": feature_vector(o["causal"]),
            }
        )

    payload = {
        "probe_id": PROBE_ID,
        "gold": args.gold,
        "session": session,
        "transitions_run": args.v11_run,
        "forbidden": ["next_*", "future_strong", "future_silence", "episode_score"],
        "allowed": FEATURE_KEYS,
        "counts": counts,
        "true_stats": true_stats,
        "program_stats": prog_stats,
        "separation": separation,
        "ranking": ranking,
        "per_gold_oracle": per_gold,
        "verdict": verdict,
    }

    stamp = ledger.run_id_stamp()
    out_json = ledger.ROOT / "experiments" / "reports" / f"causal_onset_probe_{stamp}_{args.gold}.json"
    out_md = ledger.ROOT / "experiments" / "reports" / f"causal_onset_probe_{stamp}_{args.gold}.md"
    out_json.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    out_md.write_text(render_md(payload), encoding="utf-8")
    best_rank_name = max(
        ranking.keys(),
        key=lambda n: sum(1 for r in ranking[n] if r["top_is_oracle"]),
    )
    best_top1 = sum(1 for r in ranking[best_rank_name] if r["top_is_oracle"])
    print(
        json.dumps(
            {
                "report_md": str(out_md),
                "counts": counts,
                "top_separators": [
                    {
                        "feature": r["feature"],
                        "sep": round(r["separation_iqr"], 2),
                        "overlap": r["iqr_overlap"],
                        "true_median": round(r["true_median"], 3),
                        "program_median": round(r["program_median"], 3),
                    }
                    for r in separation[:8]
                ],
                "best_local_ranker": best_rank_name,
                "best_top1": best_top1,
                "handcrafted_top1": sum(1 for r in ranking["handcrafted"] if r["top_is_oracle"]),
                "verdict": verdict,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
