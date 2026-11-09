"""Acoustic receipts: succeed vs fail windows, same cheap measures.

Crowd-bed proxy: RMS of the quietest 30% of 20 ms frames (the floor under speech).
Music/bright proxy: high-band ratio and spectral flatness on the full window.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from tools.gpu_lab.audio_load import load_coverage

SR = 16000
OUT = Path(r"C:\OHushData\gpu_lab\audio_learn\acoustic_receipts")
FROZEN = Path(r"C:\OHushData\gpu_lab\audio_learn\predictions\frozen")

# outcome: succeed_play | fail_mute_program | succeed_mute_ad
CASES = [
    ("live_tn_24", "hush_20260924_220624", 1208.0, 8.0, "succeed_play", "live play frozen leaves on"),
    ("live_tn_08", "hush_20261008_205100", 2508.0, 8.0, "succeed_play", "live play frozen leaves on"),
    ("live_tn_24b", "hush_20260924_220624", 800.0, 8.0, "succeed_play", "live early low p"),
    ("live_tn_24c", "hush_20260924_220624", 2500.0, 8.0, "succeed_play", "live mid-game low p"),
    ("live_tn_08b", "hush_20261008_205100", 1500.0, 8.0, "succeed_play", "live mid-game low p"),
    ("live_tn_08c", "hush_20261008_205100", 3500.0, 8.0, "succeed_play", "live after Amex window low p"),
    ("odell_fp_mid", "hush_20260924_220624", 7065.0, 8.0, "fail_mute_program", "Odell desk mid"),
    ("odell_fp_on", "hush_20260924_220624", 7035.0, 8.0, "fail_mute_program", "Odell mute open"),
    ("whit_fp_mid", "hush_20260924_220624", 7422.0, 8.0, "fail_mute_program", "Whitworth desk mid"),
    ("palmer_fp_mid", "hush_20260924_220624", 6194.0, 8.0, "fail_mute_program", "Palmer report"),
    ("injury_fp", "hush_20260924_220624", 6280.0, 8.0, "fail_mute_program", "injury desk"),
    ("highlights_fp", "hush_20260924_220624", 5040.0, 8.0, "fail_mute_program", "halftime highlights"),
    ("chilis_tp", "hush_20260924_220624", 2990.0, 8.0, "succeed_mute_ad", "Chili's spot"),
    ("amex_tp", "hush_20261008_205100", 3405.0, 8.0, "succeed_mute_ad", "Amex / platinum"),
    ("draftkings_tp", "hush_20261008_205100", 168.0, 8.0, "succeed_mute_ad", "DraftKings"),
    ("ad_hot_24", "hush_20260924_220624", 4355.0, 8.0, "succeed_mute_ad", "hot ad break interior"),
    ("ad_hot_08", "hush_20261008_205100", 160.0, 8.0, "succeed_mute_ad", "early ad interior"),
    ("welcome_fp", "hush_20261008_205100", 3440.0, 8.0, "fail_mute_program", "welcome back after Amex"),
]


def _frames(audio: np.ndarray, frame: int = 320, hop: int = 160) -> np.ndarray:
    if len(audio) < frame:
        return np.zeros((0, frame), dtype=np.float64)
    n = 1 + (len(audio) - frame) // hop
    out = np.zeros((n, frame), dtype=np.float64)
    for i in range(n):
        out[i] = audio[i * hop : i * hop + frame]
    return out


def _spectrum(frame: np.ndarray) -> np.ndarray:
    windowed = frame * np.hanning(len(frame))
    spec = np.fft.rfft(windowed)
    power = np.abs(spec) ** 2 + 1e-12
    return power


def _measures(audio: np.ndarray) -> dict:
    audio = np.asarray(audio, dtype=np.float64)
    frames = _frames(audio)
    if len(frames) == 0:
        return {}
    rms = np.sqrt(np.mean(frames**2, axis=1) + 1e-12)
    floor = float(np.percentile(rms, 30))
    peak = float(np.percentile(rms, 95))
    # quiet frames: bottom 30% by RMS — bed under speech
    quiet = frames[rms <= np.percentile(rms, 30)]
    quiet_power = np.mean([_spectrum(f) for f in quiet], axis=0) if len(quiet) else _spectrum(frames[0])
    freqs = np.fft.rfftfreq(frames.shape[1], d=1.0 / SR)
    # crowd-ish band often 200–2500 Hz broadband under speech
    band = (freqs >= 200) & (freqs <= 2500)
    high = freqs >= 4000
    mid = (freqs >= 500) & (freqs <= 2000)
    quiet_crowd = float(quiet_power[band].sum() / quiet_power.sum())
    quiet_floor_db = 20.0 * np.log10(floor + 1e-9)
    full_power = np.mean([_spectrum(f) for f in frames], axis=0)
    flatness = float(
        np.exp(np.mean(np.log(full_power))) / (np.mean(full_power) + 1e-12)
    )
    centroid = float((freqs * full_power).sum() / full_power.sum())
    high_ratio = float(full_power[high].sum() / full_power.sum())
    mid_ratio = float(full_power[mid].sum() / full_power.sum())
    crest = float(peak / (float(np.mean(rms)) + 1e-12))
    # modulation: std of frame RMS / mean — speech is choppy; crowd bed is steadier floor
    mod = float(np.std(rms) / (float(np.mean(rms)) + 1e-12))
    return {
        "rms": round(float(np.mean(rms)), 5),
        "floor_rms": round(floor, 5),
        "floor_db": round(quiet_floor_db, 2),
        "quiet_crowd_band_share": round(quiet_crowd, 4),
        "flatness": round(flatness, 5),
        "centroid_hz": round(centroid, 1),
        "high_ratio": round(high_ratio, 4),
        "mid_ratio": round(mid_ratio, 4),
        "crest": round(crest, 3),
        "rms_modulation": round(mod, 3),
        "peak_rms": round(peak, 5),
    }


def _frozen_p(session: str, t: float) -> float | None:
    path = FROZEN / f"{session}.npz"
    if not path.is_file():
        return None
    data = np.load(path)
    i = int(np.argmin(np.abs(data["t"] - t)))
    if abs(float(data["t"][i]) - t) > 1.0:
        return None
    return round(float(data["p"][i]), 4)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for case_id, session, t, horizon, outcome, note in CASES:
        audio = load_coverage(session, t - horizon, t)
        m = _measures(audio)
        row = {
            "id": case_id,
            "session": session,
            "t": t,
            "horizon_s": horizon,
            "outcome": outcome,
            "note": note,
            "frozen_p": _frozen_p(session, t),
            **m,
        }
        rows.append(row)
        print(
            f"{case_id:16} {outcome:20} p={row['frozen_p']} "
            f"floor_db={row['floor_db']:6.1f} crowd_share={row['quiet_crowd_band_share']:.3f} "
            f"flat={row['flatness']:.4f} high={row['high_ratio']:.3f} mod={row['rms_modulation']:.3f}",
            flush=True,
        )
    (OUT / "rows.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")

    def group(key: str) -> list[dict]:
        return [r for r in rows if r["outcome"] == key]

    summary = {}
    for key in ("succeed_play", "fail_mute_program", "succeed_mute_ad"):
        g = group(key)
        summary[key] = {
            "n": len(g),
            "floor_db_median": round(float(np.median([r["floor_db"] for r in g])), 2),
            "floor_db_min": round(float(min(r["floor_db"] for r in g)), 2),
            "floor_db_max": round(float(max(r["floor_db"] for r in g)), 2),
            "quiet_crowd_share_median": round(float(np.median([r["quiet_crowd_band_share"] for r in g])), 4),
            "flatness_median": round(float(np.median([r["flatness"] for r in g])), 5),
            "high_ratio_median": round(float(np.median([r["high_ratio"] for r in g])), 4),
            "modulation_median": round(float(np.median([r["rms_modulation"] for r in g])), 3),
            "frozen_p_median": round(float(np.median([r["frozen_p"] for r in g if r["frozen_p"] is not None])), 4),
        }
    (OUT / "summary.json").write_text(json.dumps({"summary": summary, "rows": rows}, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)
    print("wrote", OUT, flush=True)


if __name__ == "__main__":
    main()
