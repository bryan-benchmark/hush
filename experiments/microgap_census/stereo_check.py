"""Read-only stereo check of the already defined -85 dB runs.

The mute census is not rescored. Thresholds are not changed. This asks
whether a run that is quiet after averaging left and right is also quiet
in each channel. Opposite-phase channels can cancel in that average.
"""

from __future__ import annotations

import json

import numpy as np

from experiments.broadcast_intelligence.batch1 import commercials, coverage
from experiments.microgap_census.scan import CLOSED, EDGE_S, OUT, WIN, runs_from_db

THRESHOLD = -85.0


def channel_windows(audio: np.ndarray) -> dict[str, np.ndarray]:
    usable = (len(audio) // WIN) * WIN
    paired = audio[:usable].astype(np.float64).reshape(-1, WIN, audio.shape[1])
    left = paired[:, :, 0]
    right = paired[:, :, 1]
    mono = 0.5 * (left + right)

    def db(values: np.ndarray) -> np.ndarray:
        rms = np.sqrt(np.mean(values * values, axis=1))
        return 20.0 * np.log10(np.maximum(rms, 1e-12))

    energy = 20.0 * np.log10(np.maximum(np.sqrt(np.mean((left * left + right * right) / 2.0, axis=1)), 1e-12))
    left0 = left - left.mean(axis=1, keepdims=True)
    right0 = right - right.mean(axis=1, keepdims=True)
    denom = np.sqrt(np.mean(left0 * left0, axis=1) * np.mean(right0 * right0, axis=1))
    corr = np.mean(left0 * right0, axis=1) / np.maximum(denom, 1e-12)
    return {"mono": db(mono), "left": db(left), "right": db(right), "energy": energy, "corr": corr}


def summarize(rows: list[dict]) -> dict:
    if not rows:
        return {"n": 0}
    both_quiet = [row for row in rows if row["left_db"] <= THRESHOLD and row["right_db"] <= THRESHOLD]
    one_sided = [row for row in rows if row not in both_quiet]
    either_loud = sum(row["left_db"] > -40.0 or row["right_db"] > -40.0 for row in rows)
    cancel = sum(row["energy_db"] > -50.0 and row["energy_db"] - row["mono_db"] >= 20.0 and row["corr"] < -0.5 for row in rows)
    corr = np.array([row["corr"] for row in rows])
    gap = np.array([row["energy_db"] - row["mono_db"] for row in rows])
    louder = np.array([max(row["left_db"], row["right_db"]) for row in one_sided]) if one_sided else np.empty(0)
    return {
        "n": len(rows),
        "both_channels_at_or_below_minus_85": len(both_quiet),
        "either_channel_above_minus_40": either_loud,
        "cancellation_shaped": cancel,
        "median_correlation": round(float(np.median(corr)), 3),
        "median_energy_minus_mono_db": round(float(np.median(gap)), 1),
        "one_sided_n": len(one_sided),
        "one_sided_louder_channel_median_db": None if louder.size == 0 else round(float(np.median(louder)), 1),
        "one_sided_louder_channel_p90_db": None if louder.size == 0 else round(float(np.percentile(louder, 90)), 1),
    }


def main() -> None:
    spans = [span for span in coverage() if span["session"] in CLOSED]
    pods_by: dict[str, list] = {}
    for row in commercials(spans):
        pods_by.setdefault(row["session"], []).append((float(row["start_seconds"]), float(row["end_seconds"])))
    sessions = []
    for session in CLOSED:
        span = next(row for row in spans if row["session"] == session)
        t0, t1 = float(span["from_seconds"]), float(span["to_seconds"])
        print(f"stereo {session}", flush=True)
        from experiments.broadcast_intelligence.batch1 import RECORDINGS, read_span
        from hush.audio import find_session, load_session

        folder = find_session(RECORDINGS, session)
        meta = load_session(folder)
        parts = []
        cursor = t0
        while cursor < t1 - 1e-6:
            stop = min(t1, cursor + 30.0)
            parts.append(channel_windows(read_span(folder, meta, cursor, stop)))
            cursor = stop
        mono = np.concatenate([part["mono"] for part in parts])
        left = np.concatenate([part["left"] for part in parts])
        right = np.concatenate([part["right"] for part in parts])
        energy = np.concatenate([part["energy"] for part in parts])
        corr = np.concatenate([part["corr"] for part in parts])
        events = [
            event
            for event in runs_from_db(mono, t0, THRESHOLD)
            if event["start"] >= t0 + EDGE_S and event["end"] <= t1 - EDGE_S
        ]
        pods = pods_by.get(session, [])
        grouped = {"all": [], "program": [], "near_start": []}
        for event in events:
            i0 = int(round((event["start"] - t0) / 0.005))
            i1 = int(round((event["end"] - t0) / 0.005))
            i1 = max(i0 + 1, min(len(mono), i1))
            quiet = i0 + int(np.argmin(mono[i0:i1]))
            mid = 0.5 * (event["start"] + event["end"])
            row = {
                "mono_db": round(float(mono[quiet]), 1),
                "left_db": round(float(left[quiet]), 1),
                "right_db": round(float(right[quiet]), 1),
                "energy_db": round(float(energy[quiet]), 1),
                "corr": round(float(corr[quiet]), 3),
            }
            grouped["all"].append(row)
            if all(mid < start - 2.0 or mid > end + 2.0 for start, end in pods):
                grouped["program"].append(row)
            if any(abs(mid - start) <= 1.0 for start, _end in pods):
                grouped["near_start"].append(row)
        sessions.append(
            {
                "session": session,
                "threshold_db": THRESHOLD,
                "window_s": 0.005,
                "definition": "Same mono average as scan.py. Measures are taken at the quietest mono window inside each run.",
                "runs": len(events),
                "all": summarize(grouped["all"]),
                "program": summarize(grouped["program"]),
                "within_1s_of_a_start": summarize(grouped["near_start"]),
            }
        )
        print(f"  runs {len(events)} both_quiet {sessions[-1]['all']['both_channels_at_or_below_minus_85']}", flush=True)
    payload = {
        "system": "microgap_stereo_check_001",
        "mute_rescored": False,
        "thresholds_changed": False,
        "october_used": False,
        "holdouts_opened": False,
        "cancellation_shaped_means": "At the quietest mono window, stereo energy is above -50 dB, at least 20 dB louder than the mono average, and correlation is below -0.5.",
        "sessions": sessions,
    }
    (OUT / "stereo_check.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT / 'stereo_check.json'}", flush=True)


if __name__ == "__main__":
    main()
