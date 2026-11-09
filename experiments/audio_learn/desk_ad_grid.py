"""Step A: desk FP vs dry-ad TP time-aligned grid receipts.

Every named desk span + every gold break >= 12s at q1/mid/q3.
Horizons 8s and 20s. Ranked separators + AND candidates.
Frozen / live untouched.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from experiments.audio_learn.crowd_pattern_mine import _stereo, frozen_p, overlap_score
from experiments.audio_learn.desk_ad_mine import measures_ext
from experiments.audio_learn.studio_fit import DESK_SPANS
from experiments.measurement.metrics import target_commercials
from experiments.nfl75.inventory import active_intervals

OUT = Path(r"C:\OHushData\gpu_lab\audio_learn\acoustic_receipts\desk_ad_grid")
SESSIONS = ("hush_20260924_220624", "hush_20261008_205100")
HORIZONS = (8.0, 20.0)
MIN_BREAK_S = 12.0


def desk_probes() -> list[tuple[str, str, float, str]]:
    rows = []
    for session, spans in DESK_SPANS.items():
        if session not in SESSIONS:
            continue
        for i, (a0, a1) in enumerate(spans):
            dur = a1 - a0
            mid = round(0.5 * (a0 + a1), 2)
            rows.append((f"desk_{session[-6:]}_s{i}_mid", session, mid, "desk"))
            if dur >= 8.0:
                onset = round(a0 + 2.0, 2)
                rows.append((f"desk_{session[-6:]}_s{i}_on", session, onset, "desk"))
            if dur >= 16.0:
                late = round(a1 - 2.0, 2)
                rows.append((f"desk_{session[-6:]}_s{i}_late", session, late, "desk"))
    return rows


def ad_probes() -> list[tuple[str, str, float, str]]:
    rows = []
    for session in SESSIONS:
        ads = target_commercials(active_intervals(session))
        for i, (a0, a1) in enumerate(ads):
            if a1 - a0 < MIN_BREAK_S:
                continue
            for frac, tag in ((0.25, "q1"), (0.5, "mid"), (0.75, "q3")):
                t = round(a0 + frac * (a1 - a0), 2)
                if t - 8.0 < a0:
                    continue
                rows.append((f"ad_{session[-6:]}_b{i}_{tag}", session, t, "ad"))
    return rows


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    probes = desk_probes() + ad_probes()
    print(f"probes desk={sum(1 for p in probes if p[3]=='desk')} ad={sum(1 for p in probes if p[3]=='ad')}", flush=True)
    rows = []
    errors = []
    for case_id, session, t, group in probes:
        for horizon in HORIZONS:
            start = t - horizon
            if start < 0:
                errors.append({"id": case_id, "reason": "before_zero", "t": t, "horizon": horizon})
                continue
            try:
                stereo = _stereo(session, start, t)
                m = measures_ext(stereo)
            except Exception as exc:  # noqa: BLE001 — receipt errors stay in file
                errors.append({"id": case_id, "reason": str(exc), "t": t, "horizon": horizon})
                continue
            row = {
                "id": f"{case_id}_h{int(horizon)}",
                "case": case_id,
                "session": session,
                "t": t,
                "horizon_s": horizon,
                "group": group,
                "frozen_p": frozen_p(session, t),
                **m,
            }
            rows.append(row)
            print(
                f"{row['id']:28} {group:4} p={row['frozen_p']} "
                f"vlow={m['quiet_very_low']:.3f} low={m['quiet_low']:.3f} "
                f"crowd={m['quiet_crowd']:.3f} speech={m['quiet_speech']:.3f} "
                f"dry={m['dry_score']:.3f} talk={m['talk_frac']:.3f}",
                flush=True,
            )

    features = [
        "quiet_crowd",
        "quiet_low",
        "quiet_very_low",
        "quiet_speech",
        "quiet_narrow",
        "flatness",
        "centroid",
        "high_ratio",
        "mid_ratio",
        "side_mid",
        "quiet_side_mid",
        "crest",
        "mod",
        "floor_db",
        "floor_over_rms",
        "speech_std",
        "speech_mean",
        "talk_frac",
        "quiet_tilt",
        "low_minus_crowd",
        "vlow_minus_crowd",
        "dry_score",
    ]
    ranked = {}
    for horizon in HORIZONS:
        desk = [r for r in rows if r["group"] == "desk" and r["horizon_s"] == horizon]
        ad = [r for r in rows if r["group"] == "ad" and r["horizon_s"] == horizon]
        scored = []
        for feat in features:
            sep = overlap_score([r[feat] for r in desk], [r[feat] for r in ad])
            scored.append({"feature": feat, "n_desk": len(desk), "n_ad": len(ad), **sep})
        scored.sort(key=lambda r: (-r["accuracy"], r["overlap"]))
        ranked[f"desk_vs_ad_h{int(horizon)}"] = scored
        print(f"\n=== RANKED desk_vs_ad h={horizon}s n_desk={len(desk)} n_ad={len(ad)} ===", flush=True)
        for row in scored[:10]:
            print(
                f"  {row['feature']:18} acc={row['accuracy']:.3f} thr={row['thr']} "
                f"high={row['high_group']} desk{row['first_range']} ad{row['second_range']} "
                f"ov={row['overlap']}",
                flush=True,
            )

    desk8 = [r for r in rows if r["group"] == "desk" and r["horizon_s"] == 8.0]
    ad8 = [r for r in rows if r["group"] == "ad" and r["horizon_s"] == 8.0]
    rules = [
        ("vlow>=0.35", lambda r: r["quiet_very_low"] >= 0.35),
        ("vlow>=0.40", lambda r: r["quiet_very_low"] >= 0.40),
        ("low>=0.45", lambda r: r["quiet_low"] >= 0.45),
        ("vlow>=0.35 & crowd<=0.40", lambda r: r["quiet_very_low"] >= 0.35 and r["quiet_crowd"] <= 0.40),
        ("vlow>=0.40 & crowd<=0.35", lambda r: r["quiet_very_low"] >= 0.40 and r["quiet_crowd"] <= 0.35),
        ("low>=0.50 & crowd<=0.40", lambda r: r["quiet_low"] >= 0.50 and r["quiet_crowd"] <= 0.40),
        ("dry>=0.55", lambda r: r["dry_score"] >= 0.55),
        ("dry>=0.60", lambda r: r["dry_score"] >= 0.60),
        ("dry>=0.65", lambda r: r["dry_score"] >= 0.65),
        ("vlow_minus_crowd>=0.05", lambda r: r["vlow_minus_crowd"] >= 0.05),
        ("vlow_minus_crowd>=0.10", lambda r: r["vlow_minus_crowd"] >= 0.10),
        ("speech<=0.30 & low>=0.45", lambda r: r["quiet_speech"] <= 0.30 and r["quiet_low"] >= 0.45),
        ("talk<=0.25 & vlow>=0.35", lambda r: r["talk_frac"] <= 0.25 and r["quiet_very_low"] >= 0.35),
        ("dry>=0.55 & crowd<=0.40", lambda r: r["dry_score"] >= 0.55 and r["quiet_crowd"] <= 0.40),
        ("dry>=0.60 & speech<=0.35", lambda r: r["dry_score"] >= 0.60 and r["quiet_speech"] <= 0.35),
    ]
    and_rows = []
    print("\n=== AND CANDIDATES h=8s ===", flush=True)
    for name, pred in rules:
        d_hit = [r for r in desk8 if pred(r)]
        a_hit = [r for r in ad8 if pred(r)]
        rec = {
            "rule": name,
            "desk_hit": len(d_hit),
            "desk_n": len(desk8),
            "ad_hit": len(a_hit),
            "ad_n": len(ad8),
            "desk_ids": [r["case"] for r in d_hit],
            "ad_ids": [r["case"] for r in a_hit],
        }
        and_rows.append(rec)
        print(
            f"{name:32} desk {rec['desk_hit']}/{rec['desk_n']} ad {rec['ad_hit']}/{rec['ad_n']}",
            flush=True,
        )
        if a_hit and len(a_hit) <= 6:
            for r in a_hit:
                print(
                    f"  AD LEAK {r['case']} t={r['t']} vlow={r['quiet_very_low']} "
                    f"low={r['quiet_low']} crowd={r['quiet_crowd']} dry={r['dry_score']} p={r['frozen_p']}",
                    flush=True,
                )

    # group medians
    summary = {"n_rows": len(rows), "n_errors": len(errors), "by_group_h8": {}, "by_group_h20": {}}
    for horizon, key in ((8.0, "by_group_h8"), (20.0, "by_group_h20")):
        for group in ("desk", "ad"):
            rs = [r for r in rows if r["group"] == group and r["horizon_s"] == horizon]
            if not rs:
                continue
            summary[key][group] = {
                "n": len(rs),
                "frozen_p_median": round(float(np.median([r["frozen_p"] or 0 for r in rs])), 4),
                **{
                    f: {
                        "median": round(float(np.median([r[f] for r in rs])), 4),
                        "p10": round(float(np.percentile([r[f] for r in rs], 10)), 4),
                        "p90": round(float(np.percentile([r[f] for r in rs], 90)), 4),
                    }
                    for f in (
                        "quiet_very_low",
                        "quiet_low",
                        "quiet_crowd",
                        "quiet_speech",
                        "dry_score",
                        "talk_frac",
                        "vlow_minus_crowd",
                    )
                },
            }

    payload = {
        "contrast": "desk_fp_vs_gold_ad_grid",
        "sessions": list(SESSIONS),
        "horizons": list(HORIZONS),
        "summary": summary,
        "ranked": ranked,
        "and_candidates_h8": and_rows,
        "errors": errors,
        "rows": rows,
    }
    (OUT / "result.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    with (OUT / "rows.jsonl").open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")
    print("wrote", OUT / "result.json", flush=True)
    print("wrote", OUT / "rows.jsonl", flush=True)
    print("summary", json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
