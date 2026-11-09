"""Side-by-side: Odell-class desk vs dry VO ads vs live control.

Same 8s window measures, frozen p, train embedding NN, voice, AudioSet if present.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from experiments.audio_learn.crowd_bed_receipts import _measures
from experiments.audio_learn.extract import load_cache
from experiments.audio_learn.splits import TRAIN
from tools.gpu_lab.audio_load import load_coverage

DATA = Path(r"C:\OHushData\gpu_lab\audio_learn")
FROZEN = DATA / "predictions" / "frozen"
EMB = DATA / "embeddings" / "frozen"
ECAPA = Path(r"c:\Users\faceo\Projects\ohush\docs\ohush\research\NFL75_PROTECT_001\cache")
AS_WATCH = DATA / "acoustic_receipts" / "audioset_strata" / "full_watch.jsonl"
OUT = DATA / "acoustic_receipts" / "desk_vs_dry_ad_sidebyside"
NAMES = ["Al Michaels", "Kirk Herbstreit", "Clarissa Thompson", "Andrew Whitworth", "Tony Gonzalez"]

WINDOWS = [
    ("odell_onset", "hush_20260924_220624", 7035.0, 8.0, "desk"),
    ("odell_mid", "hush_20260924_220624", 7065.0, 8.0, "desk"),
    ("whitworth_mid", "hush_20260924_220624", 7422.0, 8.0, "desk"),
    ("chilis_vo", "hush_20260924_220624", 2990.0, 8.0, "dry_ad"),
    ("amex_vo", "hush_20261008_205100", 3405.0, 8.0, "dry_ad"),
    ("draftkings_vo", "hush_20261008_205100", 168.0, 8.0, "dry_ad"),
    ("ad_hot_interior", "hush_20260924_220624", 4355.0, 8.0, "dry_ad"),
    ("live_control", "hush_20260924_220624", 1208.0, 8.0, "live"),
]


def _protos(rng: np.random.Generator):
    comm, prog = [], []
    for session in TRAIN[:3]:
        path = EMB / f"{session}.npz"
        if not path.is_file():
            continue
        cache = load_cache(path)
        lab = np.asarray(cache["label"])
        vec = np.asarray(cache["emb"], dtype=np.float32)
        for label, bucket in ((1, comm), (0, prog)):
            idx = np.flatnonzero(lab == label)
            if idx.size == 0:
                continue
            take = idx if idx.size <= 150 else rng.choice(idx, 150, replace=False)
            bucket.append(vec[take])
    c = np.concatenate(comm)
    p = np.concatenate(prog)
    c /= np.linalg.norm(c, axis=1, keepdims=True) + 1e-9
    p /= np.linalg.norm(p, axis=1, keepdims=True) + 1e-9
    return c, p


def _nn(vec, c, p):
    v = vec.astype(np.float32)
    v = v / (np.linalg.norm(v) + 1e-9)
    cos_c = float(np.max(c @ v))
    cos_p = float(np.max(p @ v))
    return cos_c, cos_p, cos_c - cos_p


def _frozen_p(session: str, t: float) -> float:
    data = np.load(FROZEN / f"{session}.npz")
    i = int(np.argmin(np.abs(data["t"] - t)))
    return float(data["p"][i])


def _voice(session: str, t: float):
    path = ECAPA / f"{session}.npz"
    if not path.is_file():
        return None, None
    data = np.load(path)
    ended = np.flatnonzero(data["end"] <= t + 1e-9)
    if ended.size == 0:
        return None, None
    i = int(ended[-1])
    scores = {
        name: float(data["people"][i, slot])
        for slot, name in enumerate(NAMES)
        if np.isfinite(data["people"][i, slot])
    }
    if not scores:
        return None, None
    best = max(scores, key=scores.get)
    return best, round(scores[best], 3)


def _audioset_at(session: str, t: float) -> dict | None:
    if not AS_WATCH.is_file():
        return None
    best = None
    best_dt = 1e9
    for line in AS_WATCH.read_text(encoding="utf-8").splitlines():
        if not line:
            continue
        row = json.loads(line)
        if row.get("session") != session:
            continue
        dt = abs(float(row["t"]) - t)
        if dt < best_dt:
            best_dt = dt
            best = row
    if best is None or best_dt > 1.0:
        return None
    return {
        "speech": round(float(best["p_Speech"]), 4),
        "music": round(float(best["p_Music"]), 4),
        "sm": round(float(best["speech_minus_music"]), 4),
        "crowd_as": round(float(best.get("p_Crowd") or 0), 4),
        "as_dt": round(best_dt, 3),
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(0)
    c_proto, p_proto = _protos(rng)
    rows = []
    for wid, session, t, hor, kind in WINDOWS:
        audio = load_coverage(session, t - hor, t)
        m = _measures(audio)
        cache = load_cache(EMB / f"{session}.npz")
        ti = int(np.argmin(np.abs(cache["t"] - t)))
        cos_c, cos_p, margin = _nn(cache["emb"][ti], c_proto, p_proto)
        best, vcos = _voice(session, t)
        as_row = _audioset_at(session, t)
        row = {
            "id": wid,
            "kind": kind,
            "session": session,
            "t": t,
            "horizon_s": hor,
            "frozen_p": round(_frozen_p(session, t), 4),
            "nn_commercial": round(cos_c, 4),
            "nn_program": round(cos_p, 4),
            "nn_margin": round(margin, 4),
            "nn_says": "commercial" if margin >= 0 else "program",
            "voice_best": best,
            "voice_cos": vcos,
            "audioset": as_row,
            **m,
        }
        rows.append(row)

    print(
        f"{'id':16} {'kind':7} {'p':6} {'nn_m':7} {'nn':10} "
        f"{'crowd':6} {'floor':7} {'flat':6} {'high':6} {'mid':6} {'mod':5} "
        f"{'SM':7} {'voice':14} {'vcos':5}"
    )
    for r in rows:
        as_row = r.get("audioset") or {}
        sm = as_row.get("sm")
        sm_s = "  n/a" if sm is None else f"{sm:+6.3f}"
        vcos = r["voice_cos"]
        vcos_s = "  n/a" if vcos is None else f"{vcos:5.2f}"
        print(
            f"{r['id']:16} {r['kind']:7} {r['frozen_p']:6.3f} {r['nn_margin']:+7.3f} {r['nn_says']:10} "
            f"{r['quiet_crowd_band_share']:6.3f} {r['floor_db']:7.1f} {r['flatness']:6.4f} "
            f"{r['high_ratio']:6.3f} {r['mid_ratio']:6.3f} {r['rms_modulation']:5.2f} "
            f"{sm_s} {(r['voice_best'] or '-'):14} {vcos_s}"
        )

    feats = [
        "frozen_p",
        "nn_margin",
        "quiet_crowd_band_share",
        "floor_db",
        "flatness",
        "high_ratio",
        "mid_ratio",
        "rms_modulation",
        "crest",
    ]
    print("\nMEAN by kind")
    print(f"{'feat':24} {'desk':>8} {'dry_ad':>8} {'live':>8} {'desk-ad':>8}")
    for feat in feats:
        means = {}
        for kind in ("desk", "dry_ad", "live"):
            group = [r[feat] for r in rows if r["kind"] == kind]
            means[kind] = float(np.mean(group)) if group else float("nan")
        print(
            f"{feat:24} {means['desk']:8.3f} {means['dry_ad']:8.3f} {means['live']:8.3f} "
            f"{means['desk'] - means['dry_ad']:+8.3f}"
        )

    (OUT / "rows.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print("wrote", OUT / "rows.json")


if __name__ == "__main__":
    main()
