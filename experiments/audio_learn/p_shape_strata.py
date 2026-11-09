"""Frozen-p temporal shape on desk FP openings vs ad TP interiors.

Not new audio — the controller already sees p(t). Ask whether the *shape*
of p before/through a mute separates desk errors from gold ads.
Raw receipts. Frozen / live untouched.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from experiments.audio_learn.crowd_pattern_mine import overlap_score
from experiments.audio_learn.studio_fit import DESK_SPANS
from experiments.measurement.metrics import target_commercials
from experiments.nfl75.inventory import active_intervals

FROZEN = Path(r"C:\OHushData\gpu_lab\audio_learn\predictions\frozen")
OUT = Path(r"C:\OHushData\gpu_lab\audio_learn\acoustic_receipts\p_shape_strata")
SESSIONS = ("hush_20260924_220624", "hush_20261008_205100")
# lookback windows in hops (~0.25s) — frozen hop is 0.25s from audio_learn
PRE_S = (2.0, 5.0, 10.0)


def _series(session: str):
    d = np.load(FROZEN / f"{session}.npz")
    return d["t"].astype(np.float64), d["p"].astype(np.float64)


def _window_feats(times: np.ndarray, probs: np.ndarray, t0: float, t1: float) -> dict | None:
    m = (times >= t0) & (times < t1)
    if m.sum() < 4:
        return None
    p = probs[m]
    t = times[m]
    dt = float(np.median(np.diff(t))) if len(t) > 1 else 0.25
    # rise: last - first, and max slope over 1s
    rise = float(p[-1] - p[0])
    # hot run at end: trailing streak p>=0.9
    hot = 0
    for val in p[::-1]:
        if val >= 0.9:
            hot += 1
        else:
            break
    # time from p crossing 0.5 to 0.9 inside window
    cross50 = np.where(p >= 0.5)[0]
    cross90 = np.where(p >= 0.9)[0]
    if len(cross50) and len(cross90) and cross90[0] >= cross50[0]:
        rise_time = float((cross90[0] - cross50[0]) * dt)
    else:
        rise_time = None
    # stability once hot: std of p where p>=0.9
    hot_p = p[p >= 0.9]
    return {
        "n": int(m.sum()),
        "p_start": round(float(p[0]), 4),
        "p_end": round(float(p[-1]), 4),
        "p_mean": round(float(np.mean(p)), 4),
        "p_max": round(float(np.max(p)), 4),
        "p_min": round(float(np.min(p)), 4),
        "rise": round(rise, 4),
        "std": round(float(np.std(p)), 4),
        "hot_run_end": hot,
        "hot_run_s": round(hot * dt, 3),
        "frac_ge_0.9": round(float((p >= 0.9).mean()), 4),
        "frac_ge_0.5": round(float((p >= 0.5).mean()), 4),
        "hot_std": round(float(np.std(hot_p)), 4) if len(hot_p) >= 2 else None,
        "rise_time_0.5_to_0.9": None if rise_time is None else round(rise_time, 3),
        "median_abs_diff": round(float(np.median(np.abs(np.diff(p)))), 4) if len(p) > 1 else 0.0,
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []

    # Desk: probe at span start (mute open) and mid
    for session, spans in DESK_SPANS.items():
        if session not in SESSIONS:
            continue
        times, probs = _series(session)
        for i, (a0, a1) in enumerate(spans):
            mid = 0.5 * (a0 + a1)
            for tag, t in (("onset", a0 + 0.5), ("mid", mid)):
                if not (a0 <= t < a1):
                    continue
                for pre in PRE_S:
                    feats = _window_feats(times, probs, t - pre, t + 0.01)
                    if feats is None:
                        continue
                    # also post 2s into span from this point
                    post = _window_feats(times, probs, t, min(t + 2.0, a1))
                    row = {
                        "group": "desk",
                        "session": session,
                        "span": i,
                        "tag": tag,
                        "t": round(t, 2),
                        "span_start": a0,
                        "span_end": a1,
                        "pre_s": pre,
                        **{f"pre_{k}": v for k, v in feats.items()},
                    }
                    if post:
                        row.update({f"post2_{k}": v for k, v in post.items()})
                    rows.append(row)

    # Ads: every gold break >=12s at q1/mid/q3
    for session in SESSIONS:
        times, probs = _series(session)
        ads = target_commercials(active_intervals(session))
        for i, (a0, a1) in enumerate(ads):
            if a1 - a0 < 12:
                continue
            for frac, tag in ((0.25, "q1"), (0.5, "mid"), (0.75, "q3")):
                t = a0 + frac * (a1 - a0)
                for pre in PRE_S:
                    feats = _window_feats(times, probs, t - pre, t + 0.01)
                    if feats is None:
                        continue
                    post = _window_feats(times, probs, t, min(t + 2.0, a1))
                    row = {
                        "group": "ad",
                        "session": session,
                        "span": i,
                        "tag": tag,
                        "t": round(t, 2),
                        "span_start": a0,
                        "span_end": a1,
                        "pre_s": pre,
                        **{f"pre_{k}": v for k, v in feats.items()},
                    }
                    if post:
                        row.update({f"post2_{k}": v for k, v in post.items()})
                    rows.append(row)

    print(f"rows {len(rows)} desk={sum(1 for r in rows if r['group']=='desk')} ad={sum(1 for r in rows if r['group']=='ad')}", flush=True)

    # rank for each pre horizon, desk onset vs ad mid (fairest: desk opening vs ad interior)
    ranked = {}
    for pre in PRE_S:
        desk = [r for r in rows if r["group"] == "desk" and r["tag"] == "onset" and r["pre_s"] == pre]
        ad = [r for r in rows if r["group"] == "ad" and r["tag"] == "mid" and r["pre_s"] == pre]
        feats = [
            "pre_p_start",
            "pre_p_end",
            "pre_p_mean",
            "pre_rise",
            "pre_std",
            "pre_hot_run_s",
            "pre_frac_ge_0.9",
            "pre_frac_ge_0.5",
            "pre_median_abs_diff",
            "post2_p_mean",
            "post2_std",
            "post2_hot_run_s",
        ]
        scored = []
        for feat in feats:
            a = [r[feat] for r in desk if r.get(feat) is not None]
            b = [r[feat] for r in ad if r.get(feat) is not None]
            if len(a) < 3 or len(b) < 3:
                continue
            sep = overlap_score(a, b)
            scored.append({"feature": feat, "n_desk": len(a), "n_ad": len(b), **sep})
        scored.sort(key=lambda r: (-r["accuracy"], r["overlap"]))
        ranked[f"desk_onset_vs_ad_mid_pre{int(pre)}"] = scored
        print(f"\n=== desk onset vs ad mid pre={pre}s ===", flush=True)
        for row in scored[:8]:
            print(
                f"  {row['feature']:22} acc={row['accuracy']:.3f} thr={row['thr']} "
                f"high={row['high_group']} desk{row['first_range']} ad{row['second_range']} ov={row['overlap']}",
                flush=True,
            )

    # medians
    summary = {}
    for pre in PRE_S:
        for group, tag in (("desk", "onset"), ("desk", "mid"), ("ad", "mid"), ("ad", "q1")):
            rs = [r for r in rows if r["group"] == group and r["tag"] == tag and r["pre_s"] == pre]
            if not rs:
                continue
            key = f"{group}_{tag}_pre{int(pre)}"
            summary[key] = {"n": len(rs)}
            for feat in ("pre_p_start", "pre_p_mean", "pre_rise", "pre_hot_run_s", "pre_std", "pre_frac_ge_0.9", "post2_p_mean"):
                vals = [r[feat] for r in rs if r.get(feat) is not None]
                if not vals:
                    continue
                summary[key][feat] = {
                    "median": round(float(np.median(vals)), 4),
                    "p10": round(float(np.percentile(vals, 10)), 4),
                    "p90": round(float(np.percentile(vals, 90)), 4),
                }
    print("\n=== MEDIANS ===", flush=True)
    print(json.dumps(summary, indent=2), flush=True)

    # AND: sudden rise into desk vs sustained hot ad
    print("\n=== AND desk-onset vs ad-mid pre=5 ===", flush=True)
    desk = [r for r in rows if r["group"] == "desk" and r["tag"] == "onset" and r["pre_s"] == 5.0]
    ad = [r for r in rows if r["group"] == "ad" and r["tag"] == "mid" and r["pre_s"] == 5.0]
    and_rows = []
    for name, pred in [
        ("rise>=0.5", lambda r: (r.get("pre_rise") or 0) >= 0.5),
        ("rise>=0.7", lambda r: (r.get("pre_rise") or 0) >= 0.7),
        ("p_start<=0.3 & p_end>=0.9", lambda r: (r.get("pre_p_start") or 1) <= 0.3 and (r.get("pre_p_end") or 0) >= 0.9),
        ("p_start<=0.5 & rise>=0.4", lambda r: (r.get("pre_p_start") or 1) <= 0.5 and (r.get("pre_rise") or 0) >= 0.4),
        ("hot_run_s<=1.0 & p_end>=0.9", lambda r: (r.get("pre_hot_run_s") or 99) <= 1.0 and (r.get("pre_p_end") or 0) >= 0.9),
        ("hot_run_s>=3.0", lambda r: (r.get("pre_hot_run_s") or 0) >= 3.0),
        ("frac_ge_0.9<=0.3 & p_end>=0.9", lambda r: (r.get("pre_frac_ge_0.9") or 1) <= 0.3 and (r.get("pre_p_end") or 0) >= 0.9),
        ("std>=0.25 & rise>=0.4", lambda r: (r.get("pre_std") or 0) >= 0.25 and (r.get("pre_rise") or 0) >= 0.4),
    ]:
        d_hit = [r for r in desk if pred(r)]
        a_hit = [r for r in ad if pred(r)]
        rec = {
            "rule": name,
            "desk_hit": len(d_hit),
            "desk_n": len(desk),
            "ad_hit": len(a_hit),
            "ad_n": len(ad),
            "desk_spans": [(r["session"], r["span"], r["t"]) for r in d_hit],
            "ad_leaks": [(r["session"], r["span"], r["t"]) for r in a_hit[:8]],
        }
        and_rows.append(rec)
        print(f"{name:40} desk {len(d_hit)}/{len(desk)} ad {len(a_hit)}/{len(ad)}", flush=True)

    payload = {
        "contrast": "frozen_p_shape_desk_vs_ad",
        "pre_s": list(PRE_S),
        "summary": summary,
        "ranked": ranked,
        "and_candidates_pre5": and_rows,
        "rows": rows,
    }
    (OUT / "result.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    with (OUT / "rows.jsonl").open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")
    print("wrote", OUT / "result.json", flush=True)


if __name__ == "__main__":
    main()
