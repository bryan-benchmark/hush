"""Expert audiology swath on frozen error strata.

What we had not touched yet, now measured on the same FP_desk vs TP_ad contrast:
  - K-weighted loudness (LUFS) + short-term dynamics
  - Voicing / F0 presence (desk VO vs music bed)
  - Harmonic-percussive balance (HPSS)
  - Onset density + spectral flux (ad rhythm / cuts)
  - Bandwidth / rolloff / ZCR

Contrast is frozen confusion, not hand picks. Frozen / live untouched.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import librosa
import numpy as np
import pyloudnorm as pyln

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from experiments.audio_learn.crowd_pattern_mine import _stereo, overlap_score
from experiments.audio_learn.studio_fit import DESK_SPANS
from experiments.measurement.metrics import target_commercials
from experiments.nfl75.inventory import active_intervals
from tools.gpu_lab.audio_load import TARGET_SR

TANDEM = Path(r"C:\OHushData\gpu_lab\audio_learn\tandem_latch")
FROZEN = Path(r"C:\OHushData\gpu_lab\audio_learn\predictions\frozen")
OUT = Path(r"C:\OHushData\gpu_lab\audio_learn\acoustic_receipts\expert_strata")
SESSIONS = ("hush_20260924_220624", "hush_20261008_205100")
SAMPLE_N = 50
SEED = 11
HORIZON = 8.0


def _in(t: float, spans) -> bool:
    return any(a0 <= t < a1 for a0, a1 in spans)


def collect_strata():
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
        if not hops:
            samples[key] = []
            continue
        idx = rng.choice(len(hops), size=min(SAMPLE_N, len(hops)), replace=False)
        samples[key] = [hops[i] for i in sorted(idx)]
        print(f"{key} full={len(hops)} sample={len(samples[key])}", flush=True)
    return buckets, samples


def expert_measures(stereo: np.ndarray) -> dict:
    left, right = stereo[:, 0], stereo[:, 1]
    mono = np.ascontiguousarray(0.5 * (left + right), dtype=np.float64)
    # guard silence
    peak = float(np.max(np.abs(mono)) + 1e-12)
    mono_n = mono / max(peak, 1e-3)

    meter = pyln.Meter(TARGET_SR)  # BS.1770
    try:
        lufs = float(meter.integrated_loudness(mono))
    except Exception:
        lufs = float("nan")
    # short-term-ish blocks ~400ms
    block = int(0.4 * TARGET_SR)
    shorts = []
    for i in range(0, max(len(mono) - block, 1), block):
        chunk = mono[i : i + block]
        if len(chunk) < block // 2:
            continue
        try:
            shorts.append(float(meter.integrated_loudness(chunk)))
        except Exception:
            continue
    shorts = np.asarray(shorts, dtype=np.float64)
    shorts = shorts[np.isfinite(shorts)]
    if len(shorts):
        lra = float(np.percentile(shorts, 95) - np.percentile(shorts, 10))
        short_med = float(np.median(shorts))
        short_std = float(np.std(shorts))
    else:
        lra = short_med = short_std = float("nan")

    rms = float(np.sqrt(np.mean(mono**2) + 1e-12))
    crest = float(peak / (rms + 1e-12))
    # peak to loudness (higher = more compressed toward peaks, or sparse peaks)
    tpl = float(20 * np.log10(peak + 1e-12) - (lufs if np.isfinite(lufs) else -70.0))

    # voicing via piptrack
    pitches, mags = librosa.piptrack(y=mono_n, sr=TARGET_SR, hop_length=160, fmin=70, fmax=400)
    voiced = (pitches > 0) & (mags > np.median(mags) * 1.5)
    voiced_frac = float(voiced.any(axis=0).mean()) if pitches.size else 0.0
    pitch_vals = pitches[voiced]
    f0_med = float(np.median(pitch_vals)) if pitch_vals.size else 0.0
    f0_std = float(np.std(pitch_vals)) if pitch_vals.size else 0.0

    # HPSS
    D = librosa.stft(mono_n, n_fft=1024, hop_length=256)
    H, P = librosa.decompose.hpss(D)
    h_e = float(np.mean(np.abs(H) ** 2) + 1e-12)
    p_e = float(np.mean(np.abs(P) ** 2) + 1e-12)
    hp_ratio = float(h_e / (h_e + p_e))
    perc_ratio = float(p_e / (h_e + p_e))

    onset_env = librosa.onset.onset_strength(y=mono_n, sr=TARGET_SR, hop_length=256)
    onset_rate = float(len(librosa.onset.onset_detect(onset_envelope=onset_env, sr=TARGET_SR, hop_length=256, units="time")) / (len(mono) / TARGET_SR))
    onset_mean = float(np.mean(onset_env))
    onset_std = float(np.std(onset_env))

    # spectral flux
    S = np.abs(librosa.stft(mono_n, n_fft=1024, hop_length=256))
    flux = np.sqrt(np.sum(np.diff(S, axis=1) ** 2, axis=0))
    flux_mean = float(np.mean(flux)) if flux.size else 0.0
    flux_p90 = float(np.percentile(flux, 90)) if flux.size else 0.0

    zcr = float(np.mean(librosa.feature.zero_crossing_rate(mono_n, hop_length=256)))
    rolloff = float(np.mean(librosa.feature.spectral_rolloff(y=mono_n, sr=TARGET_SR, hop_length=256)))
    bandwidth = float(np.mean(librosa.feature.spectral_bandwidth(y=mono_n, sr=TARGET_SR, hop_length=256)))
    flatness = float(np.mean(librosa.feature.spectral_flatness(y=mono_n, hop_length=256)))

    # 3–8 Hz modulation of RMS envelope (syllabic speech vs slower beds)
    frame = 320
    hop = 160
    n = 1 + (len(mono) - frame) // hop
    if n > 16:
        env = np.array([np.sqrt(np.mean(mono[i * hop : i * hop + frame] ** 2) + 1e-12) for i in range(n)])
        env = env - np.mean(env)
        spec = np.abs(np.fft.rfft(env * np.hanning(len(env)))) ** 2
        freqs = np.fft.rfftfreq(len(env), d=hop / TARGET_SR)
        band = (freqs >= 3.0) & (freqs <= 8.0)
        mod_syll = float(spec[band].sum() / (spec.sum() + 1e-12))
    else:
        mod_syll = 0.0

    # stereo correlation / width
    corr = float(np.corrcoef(left, right)[0, 1]) if len(left) > 8 else 1.0
    mid = 0.5 * (left + right)
    side = 0.5 * (left - right)
    width = float(np.mean(side**2) / (np.mean(mid**2) + 1e-12))

    return {
        "lufs": None if not np.isfinite(lufs) else round(lufs, 2),
        "lra_proxy": None if not np.isfinite(lra) else round(lra, 2),
        "short_lufs_med": None if not np.isfinite(short_med) else round(short_med, 2),
        "short_lufs_std": None if not np.isfinite(short_std) else round(short_std, 2),
        "crest": round(crest, 3),
        "true_peak": round(peak, 4),
        "tpl_db": round(tpl, 2),
        "voiced_frac": round(voiced_frac, 4),
        "f0_med": round(f0_med, 1),
        "f0_std": round(f0_std, 1),
        "hp_ratio": round(hp_ratio, 4),
        "perc_ratio": round(perc_ratio, 4),
        "onset_rate": round(onset_rate, 3),
        "onset_mean": round(onset_mean, 4),
        "onset_std": round(onset_std, 4),
        "flux_mean": round(flux_mean, 4),
        "flux_p90": round(flux_p90, 4),
        "zcr": round(zcr, 5),
        "rolloff": round(rolloff, 1),
        "bandwidth": round(bandwidth, 1),
        "spec_flatness": round(flatness, 5),
        "mod_syllabic": round(mod_syll, 4),
        "stereo_corr": round(corr, 4),
        "stereo_width": round(width, 4),
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    buckets, samples = collect_strata()
    rows = []
    for key, hops in samples.items():
        for session, t, p in hops:
            try:
                stereo = _stereo(session, t - HORIZON, t)
                m = expert_measures(stereo)
            except Exception as exc:  # noqa: BLE001
                rows.append({"stratum": key, "session": session, "t": t, "frozen_p": p, "error": str(exc)})
                continue
            row = {"stratum": key, "session": session, "t": t, "frozen_p": round(float(p), 4), **m}
            rows.append(row)
            print(
                f"{key:10} {session[-6:]} t={t:8.1f} LUFS={m['lufs']} "
                f"voice={m['voiced_frac']:.2f} perc={m['perc_ratio']:.2f} "
                f"onset={m['onset_rate']:.2f} flux={m['flux_mean']:.1f} "
                f"mod={m['mod_syllabic']:.2f} width={m['stereo_width']:.2f}",
                flush=True,
            )

    feats = [
        "lufs",
        "lra_proxy",
        "short_lufs_std",
        "crest",
        "tpl_db",
        "voiced_frac",
        "f0_med",
        "f0_std",
        "hp_ratio",
        "perc_ratio",
        "onset_rate",
        "onset_mean",
        "onset_std",
        "flux_mean",
        "flux_p90",
        "zcr",
        "rolloff",
        "bandwidth",
        "spec_flatness",
        "mod_syllabic",
        "stereo_corr",
        "stereo_width",
    ]
    desk = [r for r in rows if r.get("stratum") == "FP_desk" and "error" not in r and r.get("lufs") is not None]
    ad = [r for r in rows if r.get("stratum") == "TP_ad" and "error" not in r and r.get("lufs") is not None]
    ranked = []
    for feat in feats:
        a = [r[feat] for r in desk if r.get(feat) is not None]
        b = [r[feat] for r in ad if r.get(feat) is not None]
        if not a or not b:
            continue
        sep = overlap_score(a, b)
        ranked.append({"feature": feat, **sep})
    ranked.sort(key=lambda r: (-r["accuracy"], r["overlap"]))
    print("\n=== RANKED expert FP_desk vs TP_ad ===", flush=True)
    for row in ranked[:12]:
        print(
            f"  {row['feature']:16} acc={row['accuracy']:.3f} thr={row['thr']} "
            f"high={row['high_group']} desk{row['first_range']} ad{row['second_range']} ov={row['overlap']}",
            flush=True,
        )

    # medians by stratum
    summary = {}
    for key in ("FP_desk", "TP_ad", "FP_other", "TN_prog"):
        rs = [r for r in rows if r.get("stratum") == key and "error" not in r]
        summary[key] = {"n": len(rs)}
        for feat in ("lufs", "voiced_frac", "perc_ratio", "onset_rate", "flux_mean", "mod_syllabic", "stereo_width", "crest", "lra_proxy"):
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

    # AND candidates from top features
    print("\n=== AND candidates ===", flush=True)
    and_rows = []
    rules = []
    if ranked:
        # build a few from top feature directions
        rules = [
            ("voiced_frac>=0.55", lambda r: (r.get("voiced_frac") or 0) >= 0.55),
            ("voiced_frac>=0.60", lambda r: (r.get("voiced_frac") or 0) >= 0.60),
            ("perc_ratio<=0.35", lambda r: (r.get("perc_ratio") or 1) <= 0.35),
            ("onset_rate<=1.5", lambda r: (r.get("onset_rate") or 99) <= 1.5),
            ("mod_syllabic>=0.25", lambda r: (r.get("mod_syllabic") or 0) >= 0.25),
            ("lra_proxy>=8", lambda r: (r.get("lra_proxy") or 0) >= 8),
            ("voiced>=0.55 & perc<=0.40", lambda r: (r.get("voiced_frac") or 0) >= 0.55 and (r.get("perc_ratio") or 1) <= 0.40),
            ("voiced>=0.55 & onset<=2.0", lambda r: (r.get("voiced_frac") or 0) >= 0.55 and (r.get("onset_rate") or 99) <= 2.0),
            ("voiced>=0.55 & mod>=0.20", lambda r: (r.get("voiced_frac") or 0) >= 0.55 and (r.get("mod_syllabic") or 0) >= 0.20),
            ("flux_mean<=30", lambda r: (r.get("flux_mean") or 99) <= 30),
            ("voiced>=0.55 & flux<=40 & perc<=0.45", lambda r: (r.get("voiced_frac") or 0) >= 0.55 and (r.get("flux_mean") or 99) <= 40 and (r.get("perc_ratio") or 1) <= 0.45),
        ]
    for name, pred in rules:
        d_hit = [r for r in desk if pred(r)]
        a_hit = [r for r in ad if pred(r)]
        rec = {
            "rule": name,
            "desk_hit": len(d_hit),
            "desk_n": len(desk),
            "ad_hit": len(a_hit),
            "ad_n": len(ad),
            "ad_leaks": [{"session": r["session"], "t": r["t"], "voiced": r["voiced_frac"], "perc": r["perc_ratio"], "onset": r["onset_rate"]} for r in a_hit[:6]],
        }
        and_rows.append(rec)
        print(f"{name:40} desk {rec['desk_hit']}/{rec['desk_n']} ad {rec['ad_hit']}/{rec['ad_n']}", flush=True)

    payload = {
        "contrast": "expert_audiology_on_frozen_confusion",
        "horizon_s": HORIZON,
        "sample_n": SAMPLE_N,
        "full_counts": {k: len(v) for k, v in buckets.items()},
        "summary": summary,
        "ranked_desk_vs_ad": ranked,
        "and_candidates": and_rows,
        "rows": rows,
        "toolkit_note": [
            "loudness: BS.1770 LUFS + short-term spread (compression / ad brickwall)",
            "voicing: piptrack voiced fraction + F0 (dry VO desk)",
            "HPSS: harmonic vs percussive (music beds / jingles)",
            "onset + flux: cut rate / rhythmic ads",
            "mod_syllabic: 3-8Hz envelope (speech cadence)",
            "stereo width/corr: booth vs wide mix",
        ],
    }
    (OUT / "result.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    with (OUT / "rows.jsonl").open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")
    print("wrote", OUT / "result.json", flush=True)


if __name__ == "__main__":
    main()
