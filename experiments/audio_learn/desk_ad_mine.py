"""Desk vs dry-ad acoustic mine. Not crowd. Looking for a desk-only force-play axis.

Writes ranked separators to acoustic_receipts/desk_ad_patterns.json.
Frozen and live are untouched.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from experiments.audio_learn.crowd_pattern_mine import _frames, _power, _stereo, frozen_p, overlap_score
from tools.gpu_lab.audio_load import TARGET_SR

OUT = Path(r"C:\OHushData\gpu_lab\audio_learn\acoustic_receipts")

# Desk FPs we care about + dry / mid-break ads. Horizons 8s and 20s.
CASES = [
    ("desk_odell_m", "hush_20260924_220624", 7065.0, "desk"),
    ("desk_odell_o", "hush_20260924_220624", 7035.0, "desk"),
    ("desk_whit", "hush_20260924_220624", 7422.0, "desk"),
    ("desk_palmer", "hush_20260924_220624", 6194.0, "desk"),
    ("desk_injury", "hush_20260924_220624", 6280.0, "desk"),
    ("desk_hl", "hush_20260924_220624", 5040.0, "desk"),
    ("desk_welcome", "hush_20261008_205100", 3440.0, "desk"),
    ("desk_7492", "hush_20260924_220624", 7500.0, "desk"),
    ("desk_6315", "hush_20260924_220624", 6325.0, "desk"),
    ("ad_chilis", "hush_20260924_220624", 2990.0, "ad"),
    ("ad_amex", "hush_20261008_205100", 3405.0, "ad"),
    ("ad_dk", "hush_20261008_205100", 168.0, "ad"),
    ("ad_hot24", "hush_20260924_220624", 4355.0, "ad"),
    ("ad_hot08", "hush_20261008_205100", 160.0, "ad"),
    ("ad_mid24", "hush_20260924_220624", 950.0, "ad"),
    ("ad_mid08", "hush_20261008_205100", 500.0, "ad"),
    ("ad_late24", "hush_20260924_220624", 5450.0, "ad"),
    ("ad_q3_24_8", "hush_20260924_220624", 3598.9, "ad"),  # crowd-like twin
    ("ad_q3_08_23", "hush_20261008_205100", 10415.16, "ad"),
]


def measures_ext(stereo: np.ndarray) -> dict:
    left, right = stereo[:, 0], stereo[:, 1]
    mono = 0.5 * (left + right)
    mid = mono
    side = 0.5 * (left - right)
    frames = _frames(mono)
    if len(frames) == 0:
        raise RuntimeError("empty frames")
    rms = np.sqrt(np.mean(frames**2, axis=1) + 1e-12)
    q_idx = rms <= np.percentile(rms, 30)
    q = frames[q_idx]
    freqs = np.fft.rfftfreq(frames.shape[1], d=1 / TARGET_SR)
    qp = np.mean([_power(f) for f in q], axis=0) if len(q) else _power(frames[0])
    fp = np.mean([_power(f) for f in frames], axis=0)
    crowd = (freqs >= 200) & (freqs <= 2500)
    low = freqs < 150
    very_low = freqs < 80
    speech = (freqs >= 300) & (freqs <= 3400)
    narrow = (freqs >= 300) & (freqs <= 1200)
    high = freqs >= 4000
    side_frames = _frames(side)
    mid_frames = _frames(mid)
    side_e = float(np.mean(side_frames**2))
    mid_e = float(np.mean(mid_frames**2)) + 1e-12
    if q_idx.any() and len(side_frames) == len(frames):
        quiet_side = float(np.mean(side_frames[q_idx] ** 2) / (np.mean(mid_frames[q_idx] ** 2) + 1e-12))
    else:
        quiet_side = side_e / mid_e
    floor = float(np.percentile(rms, 30))
    # speech-band steadiness on quiet frames: low variance of speech share => dry VO
    speech_shares = []
    for frame in q if len(q) else frames[:1]:
        pw = _power(frame)
        speech_shares.append(float(pw[speech].sum() / pw.sum()))
    speech_shares = np.asarray(speech_shares)
    # turn-taking proxy: fraction of frames above 2x quiet floor (talk bursts)
    talk = rms > (2.0 * floor)
    # spectral tilt on quiet: low/high
    quiet_tilt = float(qp[low].sum() / (qp[high].sum() + 1e-12))
    return {
        "floor_db": round(20 * np.log10(floor + 1e-9), 2),
        "quiet_crowd": round(float(qp[crowd].sum() / qp.sum()), 4),
        "quiet_low": round(float(qp[low].sum() / qp.sum()), 4),
        "quiet_very_low": round(float(qp[very_low].sum() / qp.sum()), 4),
        "quiet_speech": round(float(qp[speech].sum() / qp.sum()), 4),
        "quiet_narrow": round(float(qp[narrow].sum() / qp.sum()), 4),
        "flatness": round(float(np.exp(np.mean(np.log(fp))) / (np.mean(fp) + 1e-12)), 5),
        "centroid": round(float((freqs * fp).sum() / fp.sum()), 1),
        "high_ratio": round(float(fp[high].sum() / fp.sum()), 4),
        "mid_ratio": round(float(fp[(freqs >= 500) & (freqs <= 2000)].sum() / fp.sum()), 4),
        "side_mid": round(side_e / mid_e, 4),
        "quiet_side_mid": round(quiet_side, 4),
        "crest": round(float(np.percentile(rms, 95) / (float(np.mean(rms)) + 1e-12)), 3),
        "mod": round(float(np.std(rms) / (float(np.mean(rms)) + 1e-12)), 3),
        "floor_over_rms": round(floor / (float(np.mean(rms)) + 1e-12), 3),
        "speech_std": round(float(np.std(speech_shares)), 4),
        "speech_mean": round(float(np.mean(speech_shares)), 4),
        "talk_frac": round(float(talk.mean()), 4),
        "quiet_tilt": round(quiet_tilt, 2),
        "low_minus_crowd": round(float(qp[low].sum() / qp.sum()) - float(qp[crowd].sum() / qp.sum()), 4),
        "vlow_minus_crowd": round(float(qp[very_low].sum() / qp.sum()) - float(qp[crowd].sum() / qp.sum()), 4),
        "dry_score": round(
            float(qp[low].sum() / qp.sum()) * 0.4
            + float(qp[very_low].sum() / qp.sum()) * 0.3
            + (1.0 - min(quiet_side, 1.0)) * 0.2
            + (1.0 - float(qp[crowd].sum() / qp.sum())) * 0.1,
            4,
        ),
    }


def main() -> None:
    rows = []
    for case_id, session, t, group in CASES:
        for horizon in (8.0, 20.0):
            stereo = _stereo(session, t - horizon, t)
            m = measures_ext(stereo)
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
                f"{row['id']:22} {group:4} p={row['frozen_p']} "
                f"vlow={m['quiet_very_low']:.3f} low={m['quiet_low']:.3f} "
                f"crowd={m['quiet_crowd']:.3f} speech={m['quiet_speech']:.3f} "
                f"tilt={m['quiet_tilt']:.1f} talk={m['talk_frac']:.3f} "
                f"dry={m['dry_score']:.3f} side={m['quiet_side_mid']:.3f}",
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
    for horizon in (8.0, 20.0):
        desk = [r for r in rows if r["group"] == "desk" and r["horizon_s"] == horizon]
        ad = [r for r in rows if r["group"] == "ad" and r["horizon_s"] == horizon]
        scored = []
        for feat in features:
            sep = overlap_score([r[feat] for r in desk], [r[feat] for r in ad])
            scored.append({"feature": feat, **sep})
        scored.sort(key=lambda r: (-r["accuracy"], r["overlap"]))
        ranked[f"desk_vs_ad_h{int(horizon)}"] = scored
        print(f"\n=== TOP desk_vs_ad horizon={horizon}s ===", flush=True)
        for row in scored[:8]:
            print(
                f"  {row['feature']:18} acc={row['accuracy']:.3f} thr={row['thr']} "
                f"high={row['high_group']} desk {row['first_range']} ad {row['second_range']} "
                f"overlap={row['overlap']}",
                flush=True,
            )

    # candidate AND rules: desk-high dry markers, ad must miss
    print("\n=== TANDEM desk-force candidates (8s) ===", flush=True)
    desk8 = [r for r in rows if r["group"] == "desk" and r["horizon_s"] == 8.0]
    ad8 = [r for r in rows if r["group"] == "ad" and r["horizon_s"] == 8.0]
    rules = [
        ("vlow>=0.35", lambda r: r["quiet_very_low"] >= 0.35),
        ("low>=0.45", lambda r: r["quiet_low"] >= 0.45),
        ("vlow>=0.35 & crowd<=0.40", lambda r: r["quiet_very_low"] >= 0.35 and r["quiet_crowd"] <= 0.40),
        ("low>=0.45 & crowd<=0.40", lambda r: r["quiet_low"] >= 0.45 and r["quiet_crowd"] <= 0.40),
        ("dry>=0.55", lambda r: r["dry_score"] >= 0.55),
        ("dry>=0.60", lambda r: r["dry_score"] >= 0.60),
        ("vlow_minus_crowd>=0.05", lambda r: r["vlow_minus_crowd"] >= 0.05),
        ("low_minus_crowd>=0.10", lambda r: r["low_minus_crowd"] >= 0.10),
        ("tilt>=20 & crowd<=0.45", lambda r: r["quiet_tilt"] >= 20 and r["quiet_crowd"] <= 0.45),
        ("speech<=0.35 & low>=0.40", lambda r: r["quiet_speech"] <= 0.35 and r["quiet_low"] >= 0.40),
        ("talk<=0.35 & vlow>=0.30", lambda r: r["talk_frac"] <= 0.35 and r["quiet_very_low"] >= 0.30),
    ]
    for name, pred in rules:
        d_hit = sum(1 for r in desk8 if pred(r))
        a_hit = sum(1 for r in ad8 if pred(r))
        print(f"{name:32} desk {d_hit}/{len(desk8)} ad {a_hit}/{len(ad8)}", flush=True)

    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "desk_ad_patterns.json"
    path.write_text(json.dumps({"rows": rows, "ranked": ranked}, indent=2), encoding="utf-8")
    print("wrote", path, flush=True)


if __name__ == "__main__":
    main()
