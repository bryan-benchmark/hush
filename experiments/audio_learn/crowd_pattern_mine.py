"""Mine patterns in acoustic receipts. Expand the sample. Try stereo and low-band.

Does not train. Writes ranked separators to acoustic_receipts/patterns.json.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from experiments.ledger import RECORDINGS
from hush.audio import analysis_pieces, find_session, load_session, read_stereo, resample_concat
from tools.gpu_lab.audio_load import TARGET_SR
from tools.gpu_lab.splits import HOLDOUTS

OUT = Path(r"C:\OHushData\gpu_lab\audio_learn\acoustic_receipts")
FROZEN = Path(r"C:\OHushData\gpu_lab\audio_learn\predictions\frozen")

# Broader set: more live TN, more desk FP, more ad TP from gold breaks.
CASES = [
    ("live_a", "hush_20260924_220624", 1208.0, "succeed_play"),
    ("live_b", "hush_20261008_205100", 2508.0, "succeed_play"),
    ("live_c", "hush_20260924_220624", 800.0, "succeed_play"),
    ("live_d", "hush_20260924_220624", 2500.0, "succeed_play"),
    ("live_e", "hush_20261008_205100", 1500.0, "succeed_play"),
    ("live_f", "hush_20261008_205100", 3500.0, "succeed_play"),
    ("live_g", "hush_20260924_220624", 1800.0, "succeed_play"),
    ("live_h", "hush_20261008_205100", 5500.0, "succeed_play"),
    ("desk_odell_m", "hush_20260924_220624", 7065.0, "fail_mute_program"),
    ("desk_odell_o", "hush_20260924_220624", 7035.0, "fail_mute_program"),
    ("desk_whit", "hush_20260924_220624", 7422.0, "fail_mute_program"),
    ("desk_palmer", "hush_20260924_220624", 6194.0, "fail_mute_program"),
    ("desk_injury", "hush_20260924_220624", 6280.0, "fail_mute_program"),
    ("desk_hl", "hush_20260924_220624", 5040.0, "fail_mute_program"),
    ("desk_welcome", "hush_20261008_205100", 3440.0, "fail_mute_program"),
    ("desk_7492", "hush_20260924_220624", 7500.0, "fail_mute_program"),
    ("desk_6315", "hush_20260924_220624", 6325.0, "fail_mute_program"),
    ("ad_chilis", "hush_20260924_220624", 2990.0, "succeed_mute_ad"),
    ("ad_amex", "hush_20261008_205100", 3405.0, "succeed_mute_ad"),
    ("ad_dk", "hush_20261008_205100", 168.0, "succeed_mute_ad"),
    ("ad_hot24", "hush_20260924_220624", 4355.0, "succeed_mute_ad"),
    ("ad_hot08", "hush_20261008_205100", 160.0, "succeed_mute_ad"),
    ("ad_mid24", "hush_20260924_220624", 950.0, "succeed_mute_ad"),
    ("ad_mid08", "hush_20261008_205100", 500.0, "succeed_mute_ad"),
    ("ad_late24", "hush_20260924_220624", 5450.0, "succeed_mute_ad"),
]


def _stereo(session: str, start: float, end: float) -> np.ndarray:
    if session in HOLDOUTS:
        raise RuntimeError(session)
    folder = find_session(RECORDINGS, session)
    meta = load_session(folder)
    pieces = analysis_pieces(folder, meta, start, end)
    parts = [read_stereo(piece) for piece in pieces]
    # each part (n, 2); resample_concat expects list of arrays
    left = resample_concat([p[:, 0] for p in parts], up=1, down=3)
    right = resample_concat([p[:, 1] for p in parts], up=1, down=3)
    n = min(len(left), len(right), int(round((end - start) * TARGET_SR)))
    return np.stack([left[:n], right[:n]], axis=1).astype(np.float64)


def _frames(x: np.ndarray, frame=320, hop=160):
    if len(x) < frame:
        return np.zeros((0, frame))
    n = 1 + (len(x) - frame) // hop
    out = np.zeros((n, frame))
    for i in range(n):
        out[i] = x[i * hop : i * hop + frame]
    return out


def _power(frame: np.ndarray) -> np.ndarray:
    return np.abs(np.fft.rfft(frame * np.hanning(len(frame)))) ** 2 + 1e-12


def measures(stereo: np.ndarray) -> dict:
    left, right = stereo[:, 0], stereo[:, 1]
    mono = 0.5 * (left + right)
    mid = mono
    side = 0.5 * (left - right)
    frames = _frames(mono)
    rms = np.sqrt(np.mean(frames**2, axis=1) + 1e-12)
    q = frames[rms <= np.percentile(rms, 30)]
    freqs = np.fft.rfftfreq(frames.shape[1], d=1 / TARGET_SR)
    qp = np.mean([_power(f) for f in q], axis=0) if len(q) else _power(frames[0])
    fp = np.mean([_power(f) for f in frames], axis=0)
    crowd = (freqs >= 200) & (freqs <= 2500)
    low = freqs < 150
    speech = (freqs >= 300) & (freqs <= 3400)
    high = freqs >= 4000
    very_low = freqs < 80
    side_frames = _frames(side)
    mid_frames = _frames(mid)
    side_e = float(np.mean(side_frames**2))
    mid_e = float(np.mean(mid_frames**2)) + 1e-12
    # quiet-frame side energy share — ambience often wider
    q_idx = rms <= np.percentile(rms, 30)
    if q_idx.any() and len(side_frames) == len(frames):
        quiet_side = float(np.mean(side_frames[q_idx] ** 2) / (np.mean(mid_frames[q_idx] ** 2) + 1e-12))
    else:
        quiet_side = side_e / mid_e
    floor = float(np.percentile(rms, 30))
    return {
        "floor_db": round(20 * np.log10(floor + 1e-9), 2),
        "quiet_crowd": round(float(qp[crowd].sum() / qp.sum()), 4),
        "quiet_low": round(float(qp[low].sum() / qp.sum()), 4),
        "quiet_very_low": round(float(qp[very_low].sum() / qp.sum()), 4),
        "quiet_speech": round(float(qp[speech].sum() / qp.sum()), 4),
        "flatness": round(float(np.exp(np.mean(np.log(fp))) / (np.mean(fp) + 1e-12)), 5),
        "centroid": round(float((freqs * fp).sum() / fp.sum()), 1),
        "high_ratio": round(float(fp[high].sum() / fp.sum()), 4),
        "mid_ratio": round(float(fp[(freqs >= 500) & (freqs <= 2000)].sum() / fp.sum()), 4),
        "side_mid": round(side_e / mid_e, 4),
        "quiet_side_mid": round(quiet_side, 4),
        "crest": round(float(np.percentile(rms, 95) / (float(np.mean(rms)) + 1e-12)), 3),
        "mod": round(float(np.std(rms) / (float(np.mean(rms)) + 1e-12)), 3),
        "floor_over_rms": round(floor / (float(np.mean(rms)) + 1e-12), 3),
        # composite candidates
        "crowd_x_side": round(float(qp[crowd].sum() / qp.sum()) * quiet_side, 4),
        "crowd_minus_low": round(float(qp[crowd].sum() / qp.sum()) - float(qp[low].sum() / qp.sum()), 4),
        "live_score": round(
            float(qp[crowd].sum() / qp.sum()) * 0.6
            + min(quiet_side, 1.0) * 0.3
            + (1.0 if float((freqs * fp).sum() / fp.sum()) > 900 else 0.0) * 0.1,
            4,
        ),
    }


def frozen_p(session: str, t: float) -> float | None:
    path = FROZEN / f"{session}.npz"
    if not path.is_file():
        return None
    data = np.load(path)
    i = int(np.argmin(np.abs(data["t"] - t)))
    if abs(float(data["t"][i]) - t) > 1:
        return None
    return round(float(data["p"][i]), 4)


def overlap_score(a: list[float], b: list[float]) -> dict:
    """How cleanly A is above B (or vice versa)."""
    a = np.asarray(a, float)
    b = np.asarray(b, float)
    # best threshold maximizing (correct A-high + correct B-low) / n
    candidates = np.unique(np.concatenate([a, b]))
    best = None
    for thr in candidates:
        for high_is_a in (True, False):
            if high_is_a:
                ok = int((a >= thr).sum() + (b < thr).sum())
            else:
                ok = int((a < thr).sum() + (b >= thr).sum())
            acc = ok / (len(a) + len(b))
            row = {
                "thr": float(thr),
                "high_group": "first" if high_is_a else "second",
                "accuracy": round(acc, 4),
                "overlap": round(float(max(0, min(a.max(), b.max()) - max(a.min(), b.min()))), 4)
                if a.max() >= b.min() and b.max() >= a.min()
                else 0.0,
                "first_range": [round(float(a.min()), 4), round(float(a.max()), 4)],
                "second_range": [round(float(b.min()), 4), round(float(b.max()), 4)],
            }
            if best is None or row["accuracy"] > best["accuracy"]:
                best = row
    return best


def main() -> None:
    from experiments.measurement.metrics import target_commercials
    from experiments.nfl75.inventory import active_intervals

    ads_by = {s: target_commercials(active_intervals(s)) for s in {c[1] for c in CASES}}
    rows = []
    for case_id, session, t, outcome in CASES:
        in_ad = any(a0 <= t < a1 for a0, a1 in ads_by[session])
        if outcome == "succeed_mute_ad" and not in_ad:
            print(f"skip {case_id}: not inside gold ad", flush=True)
            continue
        if outcome != "succeed_mute_ad" and in_ad:
            print(f"skip {case_id}: inside gold ad but marked program", flush=True)
            continue
        p = frozen_p(session, t)
        stereo = _stereo(session, t - 8.0, t)
        m = measures(stereo)
        rows.append({"id": case_id, "session": session, "t": t, "outcome": outcome, "frozen_p": p, "in_gold_ad": in_ad, **m})
        print(
            f"{case_id:14} {outcome:20} p={p} crowd={m['quiet_crowd']:.3f} "
            f"low={m['quiet_low']:.3f} side={m['quiet_side_mid']:.3f} "
            f"cent={m['centroid']:.0f} live_score={m['live_score']:.3f}",
            flush=True,
        )

    features = [
        "quiet_crowd",
        "quiet_low",
        "quiet_very_low",
        "quiet_speech",
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
        "crowd_x_side",
        "crowd_minus_low",
        "live_score",
    ]
    groups = {
        "succeed_play": [r for r in rows if r["outcome"] == "succeed_play"],
        "fail_mute_program": [r for r in rows if r["outcome"] == "fail_mute_program"],
        "succeed_mute_ad": [r for r in rows if r["outcome"] == "succeed_mute_ad"],
    }
    pairs = [
        ("succeed_play", "fail_mute_program"),
        ("succeed_play", "succeed_mute_ad"),
        ("fail_mute_program", "succeed_mute_ad"),
    ]
    ranked = {}
    for g0, g1 in pairs:
        key = f"{g0}_vs_{g1}"
        scored = []
        for feat in features:
            a = [r[feat] for r in groups[g0]]
            b = [r[feat] for r in groups[g1]]
            sep = overlap_score(a, b)
            scored.append({"feature": feat, **sep})
        scored.sort(key=lambda r: (-r["accuracy"], r["overlap"]))
        ranked[key] = scored

    # show perfect or near-perfect separators
    print("\n=== TOP SEPARATORS ===", flush=True)
    for key, scored in ranked.items():
        print(key, flush=True)
        for row in scored[:5]:
            print(
                f"  {row['feature']:18} acc={row['accuracy']:.3f} thr={row['thr']} "
                f"high={row['high_group']} ranges {row['first_range']} vs {row['second_range']} "
                f"overlap={row['overlap']}",
                flush=True,
            )

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "patterns.json").write_text(
        json.dumps({"rows": rows, "ranked": ranked}, indent=2),
        encoding="utf-8",
    )
    print("wrote", OUT / "patterns.json", flush=True)


if __name__ == "__main__":
    main()
