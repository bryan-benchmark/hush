"""Step D: splice by frozen confusion, not by ear.

Strata from tandem npz (crowd/low/speech on every hop):
  FP_desk   = named desk & frozen p >= 0.9
  TP_ad     = gold ad & frozen p >= 0.9
  FP_other  = other program & frozen p >= 0.9
  TN_prog   = other program & frozen p < 0.5

Then full measures_ext on a stratified sample of each.
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

from experiments.audio_learn.crowd_pattern_mine import _stereo, overlap_score
from experiments.audio_learn.desk_ad_mine import measures_ext
from experiments.audio_learn.studio_fit import DESK_SPANS
from experiments.measurement.metrics import target_commercials
from experiments.nfl75.inventory import active_intervals

TANDEM = Path(r"C:\OHushData\gpu_lab\audio_learn\tandem_latch")
FROZEN = Path(r"C:\OHushData\gpu_lab\audio_learn\predictions\frozen")
OUT = Path(r"C:\OHushData\gpu_lab\audio_learn\acoustic_receipts\confusion_strata")
SESSIONS = ("hush_20260924_220624", "hush_20261008_205100")
SAMPLE_N = 40
SEED = 7


def _in(t: float, spans) -> bool:
    return any(a0 <= t < a1 for a0, a1 in spans)


def collect_hops():
    rng = np.random.default_rng(SEED)
    buckets = {"FP_desk": [], "TP_ad": [], "FP_other": [], "TN_prog": []}
    band_stats = {k: {"crowd": [], "low": [], "speech": []} for k in buckets}
    for session in SESSIONS:
        d = np.load(TANDEM / f"{session}_tandem.npz")
        t = d["t"]
        crowd = d["quiet_crowd"]
        low = d["quiet_low"]
        speech = d["quiet_speech"]
        p = np.load(FROZEN / f"{session}.npz")["p"]
        ads = target_commercials(active_intervals(session))
        desks = DESK_SPANS.get(session, [])
        for i in range(len(t)):
            tt = float(t[i])
            pp = float(p[i])
            in_ad = _in(tt, ads)
            in_desk = _in(tt, desks)
            if in_desk and pp >= 0.9:
                key = "FP_desk"
            elif in_ad and pp >= 0.9:
                key = "TP_ad"
            elif (not in_ad) and (not in_desk) and pp >= 0.9:
                key = "FP_other"
            elif (not in_ad) and (not in_desk) and pp < 0.5:
                key = "TN_prog"
            else:
                continue
            buckets[key].append((session, tt, pp, float(crowd[i]), float(low[i]), float(speech[i])))
            band_stats[key]["crowd"].append(float(crowd[i]))
            band_stats[key]["low"].append(float(low[i]))
            band_stats[key]["speech"].append(float(speech[i]))

    summary = {}
    for key, hops in buckets.items():
        c = np.asarray(band_stats[key]["crowd"])
        lo = np.asarray(band_stats[key]["low"])
        sp = np.asarray(band_stats[key]["speech"])
        summary[key] = {
            "n": len(hops),
            "quiet_crowd": {
                "median": round(float(np.median(c)), 4) if len(c) else None,
                "p10": round(float(np.percentile(c, 10)), 4) if len(c) else None,
                "p90": round(float(np.percentile(c, 90)), 4) if len(c) else None,
                "frac_ge_0.70": round(float((c >= 0.70).mean()), 4) if len(c) else None,
            },
            "quiet_low": {
                "median": round(float(np.median(lo)), 4) if len(lo) else None,
                "p10": round(float(np.percentile(lo, 10)), 4) if len(lo) else None,
                "p90": round(float(np.percentile(lo, 90)), 4) if len(lo) else None,
                "frac_ge_0.45": round(float((lo >= 0.45).mean()), 4) if len(lo) else None,
            },
            "quiet_speech": {
                "median": round(float(np.median(sp)), 4) if len(sp) else None,
                "p10": round(float(np.percentile(sp, 10)), 4) if len(sp) else None,
                "p90": round(float(np.percentile(sp, 90)), 4) if len(sp) else None,
            },
            "dry_and_vlowish": round(
                float(((lo >= 0.45) & (c <= 0.40)).mean()), 4
            )
            if len(c)
            else None,
            "live_tandem": round(
                float(((c >= 0.70) & (lo <= 0.05) & (sp >= 0.80)).mean()), 4
            )
            if len(c)
            else None,
        }
        print(f"{key:10} n={len(hops):6d} {summary[key]}", flush=True)

    # rule audit on full hop set: dry desk force-play candidate
    print("\n=== FULL-TAPE rule audit (tandem bands) ===", flush=True)
    rules = {
        "low>=0.45 & crowd<=0.40": lambda c, lo, sp: (lo >= 0.45) & (c <= 0.40),
        "low>=0.50 & crowd<=0.35": lambda c, lo, sp: (lo >= 0.50) & (c <= 0.35),
        "vlowish_proxy low>=0.40 & crowd<=0.35": lambda c, lo, sp: (lo >= 0.40) & (c <= 0.35),
        "live tandem": lambda c, lo, sp: (c >= 0.70) & (lo <= 0.05) & (sp >= 0.80),
    }
    rule_audit = {}
    for name, pred in rules.items():
        hits = {}
        for key, hops in buckets.items():
            if not hops:
                hits[key] = {"n": 0, "hit": 0, "frac": None}
                continue
            arr = np.array([[h[3], h[4], h[5]] for h in hops])
            mask = pred(arr[:, 0], arr[:, 1], arr[:, 2])
            hits[key] = {"n": len(hops), "hit": int(mask.sum()), "frac": round(float(mask.mean()), 4)}
        rule_audit[name] = hits
        print(name, hits, flush=True)

    # stratified sample for full measures
    samples = {}
    for key, hops in buckets.items():
        if not hops:
            samples[key] = []
            continue
        idx = rng.choice(len(hops), size=min(SAMPLE_N, len(hops)), replace=False)
        samples[key] = [hops[i] for i in sorted(idx)]
    return buckets, summary, rule_audit, samples


def measure_samples(samples):
    rows = []
    for key, hops in samples.items():
        for session, t, p, crowd, low, speech in hops:
            try:
                stereo = _stereo(session, t - 8.0, t)
                m = measures_ext(stereo)
            except Exception as exc:  # noqa: BLE001
                rows.append(
                    {
                        "stratum": key,
                        "session": session,
                        "t": t,
                        "frozen_p": p,
                        "error": str(exc),
                    }
                )
                continue
            row = {
                "stratum": key,
                "session": session,
                "t": t,
                "frozen_p": round(p, 4),
                "npz_crowd": round(crowd, 4),
                "npz_low": round(low, 4),
                "npz_speech": round(speech, 4),
                **m,
            }
            rows.append(row)
            print(
                f"{key:10} {session[-6:]} t={t:8.1f} p={p:.3f} "
                f"vlow={m['quiet_very_low']:.3f} low={m['quiet_low']:.3f} "
                f"crowd={m['quiet_crowd']:.3f} dry={m['dry_score']:.3f}",
                flush=True,
            )
    return rows


def rank_sample(rows):
    feats = [
        "quiet_very_low",
        "quiet_low",
        "quiet_crowd",
        "quiet_speech",
        "dry_score",
        "talk_frac",
        "speech_std",
        "vlow_minus_crowd",
        "low_minus_crowd",
        "quiet_side_mid",
        "crest",
        "mod",
    ]
    desk = [r for r in rows if r.get("stratum") == "FP_desk" and "error" not in r]
    ad = [r for r in rows if r.get("stratum") == "TP_ad" and "error" not in r]
    scored = []
    for feat in feats:
        sep = overlap_score([r[feat] for r in desk], [r[feat] for r in ad])
        scored.append({"feature": feat, **sep})
    scored.sort(key=lambda r: (-r["accuracy"], r["overlap"]))
    print("\n=== SAMPLE ranked FP_desk vs TP_ad ===", flush=True)
    for row in scored[:10]:
        print(
            f"  {row['feature']:18} acc={row['accuracy']:.3f} thr={row['thr']} "
            f"high={row['high_group']} desk{row['first_range']} ad{row['second_range']} ov={row['overlap']}",
            flush=True,
        )
    return scored


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    print("=== D1 full-tape tandem strata ===", flush=True)
    buckets, summary, rule_audit, samples = collect_hops()
    print("\n=== D2 full measures on stratified sample ===", flush=True)
    rows = measure_samples(samples)
    ranked = rank_sample(rows)

    # sample AND
    desk = [r for r in rows if r.get("stratum") == "FP_desk" and "error" not in r]
    ad = [r for r in rows if r.get("stratum") == "TP_ad" and "error" not in r]
    print("\n=== SAMPLE AND FP_desk vs TP_ad ===", flush=True)
    and_rows = []
    for name, pred in [
        ("vlow>=0.40 & crowd<=0.35", lambda r: r["quiet_very_low"] >= 0.40 and r["quiet_crowd"] <= 0.35),
        ("dry>=0.60", lambda r: r["dry_score"] >= 0.60),
        ("low>=0.50 & crowd<=0.35", lambda r: r["quiet_low"] >= 0.50 and r["quiet_crowd"] <= 0.35),
        ("vlow>=0.35 & talk<=0.30", lambda r: r["quiet_very_low"] >= 0.35 and r["talk_frac"] <= 0.30),
    ]:
        d_hit = sum(1 for r in desk if pred(r))
        a_hit = [r for r in ad if pred(r)]
        rec = {"rule": name, "desk_hit": d_hit, "desk_n": len(desk), "ad_hit": len(a_hit), "ad_n": len(ad),
               "ad_ts": [(r["session"], r["t"]) for r in a_hit[:8]]}
        and_rows.append(rec)
        print(f"{name:30} desk {d_hit}/{len(desk)} ad {len(a_hit)}/{len(ad)}", flush=True)

    payload = {
        "contrast": "frozen_confusion_strata",
        "summary_full_tape": summary,
        "rule_audit_full_tape": rule_audit,
        "ranked_sample_desk_vs_ad": ranked,
        "and_sample": and_rows,
        "sample_rows": rows,
        "sample_n_per_stratum": SAMPLE_N,
    }
    (OUT / "result.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    with (OUT / "sample_rows.jsonl").open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")
    # compact hop counts only for raw full tape (too big to dump every hop)
    counts = {k: len(v) for k, v in buckets.items()}
    (OUT / "hop_counts.json").write_text(json.dumps({"counts": counts, "summary": summary}, indent=2), encoding="utf-8")
    print("wrote", OUT / "result.json", flush=True)
    print("wrote", OUT / "sample_rows.jsonl", flush=True)


if __name__ == "__main__":
    main()
