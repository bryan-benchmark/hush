"""Tandem live-bed return latch on frozen mute.

Force play only when past-only quiet frames show:
  quiet_crowd >= 0.70 AND quiet_low <= 0.05 AND quiet_speech >= 0.80

Crowd-only already rejected. Frozen checkpoint and live television stay put.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from experiments.audio_learn.studio_fit import CONTROLLER, DESK_SPANS, _overlap, _score_array
from experiments.measurement.metrics import Interval, target_commercials
from experiments.nfl75.inventory import active_intervals, coverage_by_session
from tools.gpu_lab.audio_load import TARGET_SR, load_coverage

FROZEN = Path(r"C:\OHushData\gpu_lab\audio_learn\predictions\frozen")
REVIEWED = Path(r"c:\Users\faceo\Projects\ohush\docs\ohush\research\OHUSH_STUDIO_HEAD_001\reviewed_boundaries.json")
OUT = Path(r"C:\OHushData\gpu_lab\audio_learn\tandem_latch")
CROWD_MIN = 0.70
LOW_MAX = 0.05
SPEECH_MIN = 0.80
HORIZON_S = 8.0
FRAME = 320
HOP = 160
SESSIONS = ("hush_20260924_220624", "hush_20261008_205100")
FOCUS = {
    "hush_20260924_220624": {
        "odell": (7035.0, 7095.2),
        "whitworth": (7406.8, 7436.2),
        "palmer": (6180.7, 6207.8),
        "injury": (6267.8, 6287.2),
    },
    "hush_20261008_205100": {
        "welcome_back": (3437.1, 3443.0),
    },
}


def _frame_bands(mono: np.ndarray):
    mono = np.ascontiguousarray(mono, dtype=np.float64)
    n = 1 + (len(mono) - FRAME) // HOP
    window = np.hanning(FRAME)
    freqs = np.fft.rfftfreq(FRAME, d=1.0 / TARGET_SR)
    crowd = (freqs >= 200) & (freqs <= 2500)
    low = freqs < 150
    speech = (freqs >= 300) & (freqs <= 3400)
    rms = np.empty(n, dtype=np.float64)
    crowd_e = np.empty(n, dtype=np.float64)
    low_e = np.empty(n, dtype=np.float64)
    speech_e = np.empty(n, dtype=np.float64)
    total_e = np.empty(n, dtype=np.float64)
    batch = 8192
    stride = mono.strides[0]
    for start in range(0, n, batch):
        stop = min(start + batch, n)
        count = stop - start
        left = start * HOP
        need = (count - 1) * HOP + FRAME
        view = mono[left : left + need]
        frames = np.lib.stride_tricks.as_strided(
            view, shape=(count, FRAME), strides=(HOP * stride, stride)
        )
        chunk = np.array(frames, dtype=np.float64, copy=True)
        power = np.abs(np.fft.rfft(chunk * window, axis=1)) ** 2 + 1e-12
        rms[start:stop] = np.sqrt(np.mean(chunk**2, axis=1) + 1e-12)
        crowd_e[start:stop] = power[:, crowd].sum(axis=1)
        low_e[start:stop] = power[:, low].sum(axis=1)
        speech_e[start:stop] = power[:, speech].sum(axis=1)
        total_e[start:stop] = power.sum(axis=1)
    ends = (np.arange(n) * HOP + FRAME) / TARGET_SR
    return ends, rms, crowd_e, low_e, speech_e, total_e


def _quiet_shares(ends, rms, band_e, total_e, times):
    right = np.searchsorted(ends, times, side="right")
    left = np.searchsorted(ends, times - HORIZON_S, side="right")
    out = np.zeros(len(times), dtype=np.float64)
    for i, (a, b) in enumerate(zip(left, right)):
        if b <= a:
            continue
        r = rms[a:b]
        quiet = r <= np.percentile(r, 30)
        if not quiet.any():
            continue
        tot = total_e[a:b][quiet].sum()
        out[i] = float(band_e[a:b][quiet].sum() / tot)
    return out


def _round(row: dict) -> dict:
    kept = {}
    for key in (
        "commercial_coverage",
        "commercial_covered_s",
        "commercial_s",
        "program_covered_s",
        "false_mute_episodes",
        "false_mutes_per_hour",
        "longest_false_mute_s",
        "recovery",
        "desk_span_covered_s",
    ):
        value = row[key]
        kept[key] = None if value is None else round(float(value), 4)
    delays = [item["start_delay_s"] for item in row["breaks"] if item["start_delay_s"] is not None]
    kept["median_start_delay_s"] = None if not delays else round(float(np.median(delays)), 3)
    kept["breaks_missed"] = sum(1 for item in row["breaks"] if item["missed_break"])
    kept["longest_episodes"] = row["longest_episodes"]
    return kept


def _reviewed(session: str) -> list[Interval]:
    extra = json.loads(REVIEWED.read_text(encoding="utf-8"))["commercials"]
    intervals = list(active_intervals(session))
    for row in extra:
        if row["session"] != session:
            continue
        intervals.append(
            Interval(
                start=float(row["start_s"]),
                end=float(row["end_s"]),
                event_class="commercial",
                desired_action="mute",
                confidence="reviewed",
            )
        )
    return intervals


def _focus(session: str, times: np.ndarray, scores: np.ndarray) -> dict:
    from experiments.audio_learn.controller import decisions
    from experiments.nfl75.score import playback_from_decisions

    coverage = coverage_by_session()[session]
    spans = playback_from_decisions(coverage, decisions(times.tolist(), scores.tolist(), **CONTROLLER))
    found = {name: round(_overlap(spans, [bounds]), 3) for name, bounds in FOCUS.get(session, {}).items()}
    found["named_desk_list_s"] = round(_overlap(spans, DESK_SPANS.get(session, [])), 3)
    return found


def _latch(session: str, times: np.ndarray, probs: np.ndarray):
    coverage = coverage_by_session()[session]
    print(f"loading audio {session} {coverage[0]}-{coverage[1]}", flush=True)
    mono = load_coverage(session, coverage[0], coverage[1]).astype(np.float64)
    print("frame spectra", flush=True)
    ends, rms, crowd_e, low_e, speech_e, total_e = _frame_bands(mono)
    ends = ends + coverage[0]
    times64 = times.astype(np.float64)
    print(f"quiet shares {len(times)} decisions", flush=True)
    crowd = _quiet_shares(ends, rms, crowd_e, total_e, times64)
    low = _quiet_shares(ends, rms, low_e, total_e, times64)
    speech = _quiet_shares(ends, rms, speech_e, total_e, times64)
    live = (crowd >= CROWD_MIN) & (low <= LOW_MAX) & (speech >= SPEECH_MIN)
    out = np.array(probs, dtype=np.float64, copy=True)
    out[live] = 0.0
    ads = target_commercials(active_intervals(session))
    in_ad = np.array([any(a0 <= float(t) < a1 for a0, a1 in ads) for t in times])
    stats = {
        "decisions": len(times),
        "latched_decisions": int(live.sum()),
        "latched_in_gold_ad": int((live & in_ad).sum()),
        "latched_while_frozen_mute": int((live & (probs >= 0.5)).sum()),
        "crowd_median": round(float(np.median(crowd)), 4),
        "low_median": round(float(np.median(low)), 4),
        "speech_median": round(float(np.median(speech)), 4),
        "live_frac": round(float(live.mean()), 4),
    }
    return out, stats, crowd, low, speech, live


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    report = {
        "rule": {"quiet_crowd_ge": CROWD_MIN, "quiet_low_le": LOW_MAX, "quiet_speech_ge": SPEECH_MIN, "horizon_s": HORIZON_S},
        "controller": CONTROLLER,
        "runs": {},
    }
    for name in ("frozen", "tandem_latch"):
        games = []
        reviewed_games = []
        focus = {}
        latch_stats = {}
        for session in SESSIONS:
            prediction = np.load(FROZEN / f"{session}.npz")
            times = prediction["t"]
            scores = prediction["p"].astype(np.float64)
            if name == "tandem_latch":
                scores, stats, crowd, low, speech, live = _latch(session, times, scores)
                latch_stats[session] = stats
                np.savez(
                    OUT / f"{session}_tandem.npz",
                    t=times,
                    quiet_crowd=crowd,
                    quiet_low=low,
                    quiet_speech=speech,
                    live=live.astype(np.uint8),
                    p_latched=scores,
                )
            games.append(_round(_score_array(session, times, scores)))
            games[-1]["session"] = session
            reviewed_games.append(_round(_score_array(session, times, scores, _reviewed(session))))
            reviewed_games[-1]["session"] = session
            focus[session] = _focus(session, times, scores)
            print(
                f"{name} {session} coverage {games[-1]['commercial_coverage']:.3f} "
                f"program {games[-1]['program_covered_s']:.1f}s "
                f"rate {games[-1]['false_mutes_per_hour']:.2f}/h "
                f"longest {games[-1]['longest_false_mute_s']:.1f}s",
                flush=True,
            )
        report["runs"][name] = {
            "original_gold": games,
            "reviewed_boundaries": reviewed_games,
            "focus_covered_s": focus,
            "latch_stats": latch_stats,
        }
        print(" focus", focus, flush=True)
    for name, block in report["runs"].items():
        cov = sum(g["commercial_covered_s"] for g in block["original_gold"])
        tot = sum(g["commercial_s"] for g in block["original_gold"])
        prog = sum(g["program_covered_s"] for g in block["original_gold"])
        eps = sum(g["false_mute_episodes"] for g in block["original_gold"])
        longest = max(g["longest_false_mute_s"] for g in block["original_gold"])
        block["aggregate"] = {
            "commercial_coverage": round(cov / tot, 4),
            "commercial_covered_s": round(cov, 1),
            "commercial_s": round(tot, 1),
            "program_covered_s": round(prog, 1),
            "false_mute_episodes": eps,
            "longest_false_mute_s": round(longest, 2),
            "desk_span_covered_s": round(
                sum(block["focus_covered_s"][s].get("named_desk_list_s", 0) for s in SESSIONS), 1
            ),
        }
        print("AGG", name, block["aggregate"], flush=True)
    (OUT / "result.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("wrote", OUT / "result.json", flush=True)


if __name__ == "__main__":
    main()
