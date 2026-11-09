"""E3: pyin voicing + multi-horizon on frozen confusion strata.

piptrack saturated (~1.0 everywhere). This uses librosa.pyin with voiced
probability, plus 2s / 8s / 20s horizons. Same FP_desk vs TP_ad contrast.
Frozen / live untouched.
"""

from __future__ import annotations

import json
import warnings
from pathlib import Path

import librosa
import numpy as np

from experiments.audio_learn.crowd_pattern_mine import _stereo, overlap_score
from experiments.audio_learn.studio_fit import DESK_SPANS
from experiments.measurement.metrics import target_commercials
from experiments.nfl75.inventory import active_intervals
from tools.gpu_lab.audio_load import TARGET_SR

TANDEM = Path(r"C:\OHushData\gpu_lab\audio_learn\tandem_latch")
FROZEN = Path(r"C:\OHushData\gpu_lab\audio_learn\predictions\frozen")
OUT = Path(r"C:\OHushData\gpu_lab\audio_learn\acoustic_receipts\voicing_strata")
SESSIONS = ("hush_20260924_220624", "hush_20261008_205100")
SAMPLE_N = 40
SEED = 17
HORIZONS = (2.0, 8.0, 20.0)


def _in(t: float, spans) -> bool:
    return any(a0 <= t < a1 for a0, a1 in spans)


def collect_samples():
    rng = np.random.default_rng(SEED)
    buckets = {"FP_desk": [], "TP_ad": [], "FP_other": [], "TN_prog": []}
    for session in SESSIONS:
        t = np.load(TANDEM / f"{session}_tandem.npz")["t"]
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
            buckets[key].append((session, tt, pp))
    samples = {}
    for key, hops in buckets.items():
        idx = rng.choice(len(hops), size=min(SAMPLE_N, len(hops)), replace=False)
        samples[key] = [hops[i] for i in sorted(idx)]
        print(f"{key} full={len(hops)} sample={len(samples[key])}", flush=True)
    return buckets, samples


def voicing_measures(mono: np.ndarray) -> dict:
    mono = np.ascontiguousarray(mono, dtype=np.float64)
    peak = float(np.max(np.abs(mono)) + 1e-12)
    y = mono / max(peak, 1e-3)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        f0, voiced_flag, voiced_probs = librosa.pyin(
            y,
            fmin=70,
            fmax=400,
            sr=TARGET_SR,
            frame_length=1024,
            hop_length=256,
            fill_na=np.nan,
        )
    voiced_probs = np.asarray(voiced_probs, dtype=np.float64)
    voiced_flag = np.asarray(voiced_flag, dtype=bool)
    f0 = np.asarray(f0, dtype=np.float64)
    if voiced_probs.size == 0:
        return {
            "voiced_prob_mean": 0.0,
            "voiced_prob_p50": 0.0,
            "voiced_prob_p90": 0.0,
            "voiced_frac_0.5": 0.0,
            "voiced_frac_0.7": 0.0,
            "f0_med": 0.0,
            "f0_std": 0.0,
            "f0_range": 0.0,
            "f0_stability": 0.0,
        }
    vp = voiced_probs[np.isfinite(voiced_probs)]
    f0v = f0[np.isfinite(f0)]
    # stability: inverse of relative frame-to-frame f0 jump on voiced frames
    if f0v.size >= 3:
        diffs = np.abs(np.diff(f0v))
        f0_stability = float(1.0 / (1.0 + np.median(diffs) / (np.median(f0v) + 1e-9)))
        f0_range = float(np.percentile(f0v, 90) - np.percentile(f0v, 10))
    else:
        f0_stability = 0.0
        f0_range = 0.0
    return {
        "voiced_prob_mean": round(float(np.mean(vp)), 4) if vp.size else 0.0,
        "voiced_prob_p50": round(float(np.median(vp)), 4) if vp.size else 0.0,
        "voiced_prob_p90": round(float(np.percentile(vp, 90)), 4) if vp.size else 0.0,
        "voiced_frac_0.5": round(float((vp >= 0.5).mean()), 4) if vp.size else 0.0,
        "voiced_frac_0.7": round(float((vp >= 0.7).mean()), 4) if vp.size else 0.0,
        "f0_med": round(float(np.median(f0v)), 1) if f0v.size else 0.0,
        "f0_std": round(float(np.std(f0v)), 1) if f0v.size else 0.0,
        "f0_range": round(f0_range, 1),
        "f0_stability": round(f0_stability, 4),
        "pyin_voiced_frac": round(float(np.mean(voiced_flag)), 4),
    }


def harmonicity_proxy(mono: np.ndarray) -> dict:
    """Simple harmonic-to-noise via autocorrelation peak sharpness."""
    mono = np.ascontiguousarray(mono, dtype=np.float64)
    # use middle 1s if long enough
    n = len(mono)
    if n > TARGET_SR:
        mid = n // 2
        chunk = mono[mid - TARGET_SR // 2 : mid + TARGET_SR // 2]
    else:
        chunk = mono
    chunk = chunk - np.mean(chunk)
    if np.allclose(chunk, 0):
        return {"hnr_proxy": 0.0, "ac_peak": 0.0}
    ac = np.correlate(chunk, chunk, mode="full")
    ac = ac[len(ac) // 2 :]
    ac = ac / (ac[0] + 1e-12)
    # search pitch lag 70-400 Hz
    lo = int(TARGET_SR / 400)
    hi = int(TARGET_SR / 70)
    hi = min(hi, len(ac) - 1)
    if hi <= lo:
        return {"hnr_proxy": 0.0, "ac_peak": 0.0}
    seg = ac[lo:hi]
    peak = float(np.max(seg))
    # noise floor around peak
    peak_i = int(np.argmax(seg))
    left = max(0, peak_i - 5)
    right = min(len(seg), peak_i + 6)
    mask = np.ones(len(seg), dtype=bool)
    mask[left:right] = False
    floor = float(np.median(seg[mask])) if mask.any() else 0.0
    hnr = float(peak / (abs(floor) + 1e-3))
    return {"hnr_proxy": round(hnr, 3), "ac_peak": round(peak, 4)}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    buckets, samples = collect_samples()
    rows = []
    for key, hops in samples.items():
        for session, t, p in hops:
            row = {"stratum": key, "session": session, "t": t, "frozen_p": round(float(p), 4)}
            try:
                # load longest once
                stereo = _stereo(session, max(0.0, t - 20.0), t)
                mono_full = 0.5 * (stereo[:, 0] + stereo[:, 1])
                for horizon in HORIZONS:
                    need = int(round(horizon * TARGET_SR))
                    mono = mono_full[-need:] if len(mono_full) >= need else mono_full
                    v = voicing_measures(mono)
                    h = harmonicity_proxy(mono)
                    prefix = f"h{int(horizon)}_"
                    for k, val in {**v, **h}.items():
                        row[prefix + k] = val
                rows.append(row)
                print(
                    f"{key:10} {session[-6:]} t={t:8.1f} "
                    f"h8_v70={row['h8_voiced_frac_0.7']:.2f} h8_vp50={row['h8_voiced_prob_p50']:.2f} "
                    f"h8_f0={row['h8_f0_med']:.0f} h8_stab={row['h8_f0_stability']:.2f} "
                    f"h8_hnr={row['h8_hnr_proxy']:.2f} | "
                    f"h2_v70={row['h2_voiced_frac_0.7']:.2f} h20_v70={row['h20_voiced_frac_0.7']:.2f}",
                    flush=True,
                )
            except Exception as exc:  # noqa: BLE001
                row["error"] = str(exc)
                rows.append(row)
                print(f"{key:10} ERROR {exc}", flush=True)

    feats = []
    for horizon in HORIZONS:
        p = f"h{int(horizon)}_"
        feats.extend(
            [
                p + "voiced_prob_mean",
                p + "voiced_prob_p50",
                p + "voiced_frac_0.5",
                p + "voiced_frac_0.7",
                p + "f0_med",
                p + "f0_std",
                p + "f0_range",
                p + "f0_stability",
                p + "hnr_proxy",
                p + "ac_peak",
                p + "pyin_voiced_frac",
            ]
        )

    desk = [r for r in rows if r.get("stratum") == "FP_desk" and "error" not in r]
    ad = [r for r in rows if r.get("stratum") == "TP_ad" and "error" not in r]
    ranked = []
    for feat in feats:
        a = [r[feat] for r in desk if feat in r]
        b = [r[feat] for r in ad if feat in r]
        if len(a) < 5 or len(b) < 5:
            continue
        sep = overlap_score(a, b)
        ranked.append({"feature": feat, **sep})
    ranked.sort(key=lambda r: (-r["accuracy"], r["overlap"]))
    print("\n=== RANKED FP_desk vs TP_ad ===", flush=True)
    for row in ranked[:15]:
        print(
            f"  {row['feature']:28} acc={row['accuracy']:.3f} thr={row['thr']} "
            f"high={row['high_group']} desk{row['first_range']} ad{row['second_range']} ov={row['overlap']}",
            flush=True,
        )

    summary = {}
    for key in ("FP_desk", "TP_ad", "FP_other", "TN_prog"):
        rs = [r for r in rows if r.get("stratum") == key and "error" not in r]
        summary[key] = {"n": len(rs)}
        for feat in (
            "h8_voiced_frac_0.7",
            "h8_voiced_prob_p50",
            "h8_f0_stability",
            "h8_hnr_proxy",
            "h8_f0_med",
            "h2_voiced_frac_0.7",
            "h20_voiced_frac_0.7",
            "h8_f0_range",
        ):
            vals = [r[feat] for r in rs if feat in r]
            if not vals:
                continue
            summary[key][feat] = {
                "median": round(float(np.median(vals)), 4),
                "p10": round(float(np.percentile(vals, 10)), 4),
                "p90": round(float(np.percentile(vals, 90)), 4),
            }
    print("\n=== MEDIANS ===", flush=True)
    print(json.dumps(summary, indent=2), flush=True)

    print("\n=== AND candidates h8 ===", flush=True)
    and_rows = []
    for name, pred in [
        ("v70>=0.55", lambda r: r.get("h8_voiced_frac_0.7", 0) >= 0.55),
        ("v70>=0.65", lambda r: r.get("h8_voiced_frac_0.7", 0) >= 0.65),
        ("vp50>=0.55", lambda r: r.get("h8_voiced_prob_p50", 0) >= 0.55),
        ("stab>=0.85", lambda r: r.get("h8_f0_stability", 0) >= 0.85),
        ("hnr>=3.0", lambda r: r.get("h8_hnr_proxy", 0) >= 3.0),
        ("v70>=0.55 & stab>=0.80", lambda r: r.get("h8_voiced_frac_0.7", 0) >= 0.55 and r.get("h8_f0_stability", 0) >= 0.80),
        ("v70>=0.55 & hnr>=2.5", lambda r: r.get("h8_voiced_frac_0.7", 0) >= 0.55 and r.get("h8_hnr_proxy", 0) >= 2.5),
        ("h2_v70>=0.60 & h8_v70>=0.55", lambda r: r.get("h2_voiced_frac_0.7", 0) >= 0.60 and r.get("h8_voiced_frac_0.7", 0) >= 0.55),
        ("f0_range<=80 & v70>=0.50", lambda r: r.get("h8_f0_range", 999) <= 80 and r.get("h8_voiced_frac_0.7", 0) >= 0.50),
        ("v70>=0.55 & f0_med>=140 & f0_med<=220", lambda r: r.get("h8_voiced_frac_0.7", 0) >= 0.55 and 140 <= r.get("h8_f0_med", 0) <= 220),
    ]:
        d_hit = sum(1 for r in desk if pred(r))
        a_hit = [r for r in ad if pred(r)]
        rec = {"rule": name, "desk_hit": d_hit, "desk_n": len(desk), "ad_hit": len(a_hit), "ad_n": len(ad)}
        and_rows.append(rec)
        print(f"{name:40} desk {d_hit}/{len(desk)} ad {len(a_hit)}/{len(ad)}", flush=True)

    # also compare TN vs desk for live markers
    tn = [r for r in rows if r.get("stratum") == "TN_prog" and "error" not in r]
    print("\n=== RANKED TN_prog vs FP_desk (live marker check) ===", flush=True)
    ranked_live = []
    for feat in ("h8_voiced_frac_0.7", "h8_voiced_prob_p50", "h8_f0_stability", "h8_hnr_proxy", "h8_f0_range"):
        sep = overlap_score([r[feat] for r in tn], [r[feat] for r in desk])
        ranked_live.append({"feature": feat, **sep})
        print(f"  {feat:28} acc={sep['accuracy']:.3f} thr={sep['thr']} high={sep['high_group']} ov={sep['overlap']}", flush=True)

    payload = {
        "contrast": "pyin_voicing_multihorizon_frozen_confusion",
        "horizons_s": list(HORIZONS),
        "sample_n": SAMPLE_N,
        "full_counts": {k: len(v) for k, v in buckets.items()},
        "summary": summary,
        "ranked_desk_vs_ad": ranked,
        "ranked_live_vs_desk": ranked_live,
        "and_candidates": and_rows,
        "rows": rows,
    }
    (OUT / "result.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    with (OUT / "rows.jsonl").open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")
    print("wrote", OUT / "result.json", flush=True)


if __name__ == "__main__":
    main()
