"""Batch 1: break clocks, boundary acoustics, and repeated short signatures.

Stereo 48 kHz PCM is the captured format for both the game and the ads.
A sample-rate change is not a feature. Gold is used only to place windows
and to score them. No threshold is searched. No live muter is touched.

Predeclared, before the tables are read back:

- Pod length is the closed commercial interval, not an assumed 15-second spot.
- Fixed timers of 120 s and 135 s are hypotheses, not fitted values.
- A causal acoustic probe waits until 1 s after the boundary and compares that
  second with the 2 s before it. The splice ratio is 3. Other features use the
  95th percentile of program windows from the other recordings.
- A short signature is the L2-normalized log spectrum of 2 s in 24 bands.
  Cosine 0.90 is a near-copy. A motif needs 3 copies. Cross-game claims use
  leave-one-recording-out.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import soundfile as sf
from scipy import signal

from experiments.ledger import GOLD, TRUTH_PATH, read_jsonl, resolve_ledger
from hush.audio import analysis_pieces, find_session, load_session

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "docs/ohush/research/BROADCAST_INTELLIGENCE_001"
RECORDINGS = REPO / "recordings"
HOLDOUTS = {"hush_20260917_205513", "hush_20260920_200635"}
SR = 48000
COPY_COSINE = 0.90
SPLICE_RATIO = 3.0
TIMERS = (120.0, 135.0)
BAND_EDGES = np.geomspace(80.0, 8000.0, 25)


def load_catalog() -> dict[str, dict]:
    rows = {}
    with (REPO / "experiments/SESSION_CATALOG.csv").open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            rows[row["session_id"]] = row
    return rows


def coverage() -> list[dict]:
    spans = []
    for name in ("GOLD_DATASET_20261013.json", "GOLD_DEV_V1.json", "GOLD_REPLICATION_V1.json"):
        doc = json.loads((GOLD / name).read_text(encoding="utf-8"))
        for row in doc["coverage"]:
            if row.get("fully_annotated"):
                spans.append(row)
    return spans


def commercials(spans: list[dict]) -> list[dict]:
    superseded = set()
    raw = read_jsonl(TRUTH_PATH)
    for row in raw:
        if row.get("supersedes"):
            superseded.add(row["supersedes"])
    active = []
    for row in resolve_ledger(raw, "gold_id"):
        if row.get("session") in HOLDOUTS:
            raise SystemExit("refusing a sealed holdout")
        if row.get("retracted") or row.get("event") == "retracted":
            continue
        if row.get("gold_id") in superseded:
            continue
        active.append(row)
    by_session: dict[str, list] = {}
    for span in spans:
        by_session.setdefault(span["session"], []).append(span)
    chosen = []
    for row in active:
        if row.get("event_class") != "commercial" or row.get("desired_action") != "mute":
            continue
        if row.get("confidence") == "unsure":
            continue
        start, end = float(row["start_seconds"]), float(row["end_seconds"])
        spans_here = by_session.get(row["session"], [])
        if not any(start >= float(s["from_seconds"]) - 1e-6 and end <= float(s["to_seconds"]) + 1e-6 for s in spans_here):
            continue
        chosen.append(row)
    chosen.sort(key=lambda row: (row["session"], float(row["start_seconds"])))
    return chosen


def read_span(session_dir: Path, meta: dict, t0: float, t1: float) -> np.ndarray:
    pieces = analysis_pieces(session_dir, meta, t0, t1)
    parts = []
    for piece in pieces:
        audio, _sr = sf.read(
            str(piece["path"]),
            start=piece["read_start_frame"],
            stop=piece["read_stop_frame"],
            dtype="float32",
            always_2d=True,
        )
        parts.append(audio)
    return np.concatenate(parts, axis=0)


def spectrum(mono: np.ndarray) -> np.ndarray:
    window = np.hanning(len(mono))
    mag = np.abs(np.fft.rfft(mono * window))
    return mag


def chroma_signature(mono: np.ndarray) -> np.ndarray:
    """Eight successive 12-bin pitch profiles. A melody can differ where the average spectrum cannot."""
    frame = len(mono) // 8
    rows = []
    for index in range(8):
        piece = mono[index * frame : (index + 1) * frame]
        mag = spectrum(piece)
        freqs = np.fft.rfftfreq(len(piece), 1.0 / SR)
        chroma = np.zeros(12, dtype=np.float64)
        for freq, value in zip(freqs, mag):
            if freq < 80.0 or freq > 5000.0:
                continue
            pitch = int(np.round(12.0 * np.log2(freq / 440.0) + 69.0)) % 12
            chroma[pitch] += float(value)
        norm = np.linalg.norm(chroma)
        rows.append(chroma / norm if norm else chroma)
    vec = np.concatenate(rows)
    norm = np.linalg.norm(vec)
    return vec / norm if norm else vec


def band_signature(mono: np.ndarray) -> np.ndarray:
    mag = spectrum(mono)
    freqs = np.fft.rfftfreq(len(mono), 1.0 / SR)
    values = []
    for lo, hi in zip(BAND_EDGES[:-1], BAND_EDGES[1:]):
        chosen = mag[(freqs >= lo) & (freqs < hi)]
        values.append(float(np.mean(chosen)) if chosen.size else 0.0)
    vec = np.log1p(np.asarray(values, dtype=np.float64))
    norm = np.linalg.norm(vec)
    if norm == 0.0:
        return vec
    return vec / norm


def frame_flux(mono: np.ndarray) -> float:
    if len(mono) < 2048:
        return 0.0
    _freqs, _times, spec = signal.spectrogram(mono, SR, nperseg=1024, noverlap=512, scaling="spectrum")
    spec = np.maximum(spec, 1e-12)
    spec = spec / np.sum(spec, axis=0, keepdims=True)
    delta = np.maximum(spec[:, 1:] - spec[:, :-1], 0.0)
    return float(np.max(np.mean(delta, axis=0)))


def acoustics(audio: np.ndarray) -> dict:
    left = audio[:, 0].astype(np.float64)
    right = audio[:, 1].astype(np.float64)
    mono = 0.5 * (left + right)
    rms = float(np.sqrt(np.mean(mono * mono)) + 1e-12)
    peak = float(np.max(np.abs(mono)) + 1e-12)
    mag = spectrum(mono)
    freqs = np.fft.rfftfreq(len(mono), 1.0 / SR)
    mag = np.maximum(mag, 1e-12)
    centroid = float(np.sum(freqs * mag) / np.sum(mag))
    flatness = float(np.exp(np.mean(np.log(mag))) / np.mean(mag))
    corr = float(np.corrcoef(left, right)[0, 1]) if len(left) > 8 else 0.0
    if not np.isfinite(corr):
        corr = 0.0
    mid = 0.5 * (left + right)
    side = 0.5 * (left - right)
    side_ratio = float(np.mean(side * side) / (np.mean(mid * mid) + 1e-12))
    low = float(np.sum(mag[(freqs >= 80) & (freqs < 250)]))
    midband = float(np.sum(mag[(freqs >= 250) & (freqs < 2000)]))
    high = float(np.sum(mag[(freqs >= 2000) & (freqs < 8000)]))
    total = low + midband + high + 1e-12
    return {
        "rms_db": 20.0 * np.log10(rms),
        "crest": peak / rms,
        "centroid_hz": centroid,
        "flatness": flatness,
        "stereo_corr": corr,
        "side_ratio": side_ratio,
        "high_ratio": high / total,
        "flux": frame_flux(mono),
        "signature": band_signature(mono),
        "chroma": chroma_signature(mono),
    }


def percentile(values: list[float], q: float) -> float:
    if not values:
        return float("nan")
    return float(np.percentile(np.asarray(values, dtype=np.float64), q))


def summarize_durations(rows: list[dict]) -> dict:
    durations = np.asarray([row["duration_s"] for row in rows], dtype=np.float64)
    if durations.size == 0:
        return {"n": 0}
    nearest = {name: int(np.sum(np.abs(durations - timer) <= 7.5)) for name, timer in (("120", 120.0), ("135", 135.0))}
    return {
        "n": int(durations.size),
        "median_s": round(float(np.median(durations)), 3),
        "p10_s": round(float(np.percentile(durations, 10)), 3),
        "p90_s": round(float(np.percentile(durations, 90)), 3),
        "within_7_5s_of_120": nearest["120"],
        "within_7_5s_of_135": nearest["135"],
        "within_7_5s_of_either": int(np.sum(np.minimum(np.abs(durations - 120.0), np.abs(durations - 135.0)) <= 7.5)),
    }


def timer_errors(groups: dict[str, list[dict]]) -> dict:
    """Hypothetical: mute is already on, and a timer unmutes. Not a product policy."""
    out = {}
    for name, timer in (("fixed_120", 120.0), ("fixed_135", 135.0)):
        early = []
        late = []
        for rows in groups.values():
            for row in rows:
                gap = timer - row["duration_s"]
                if gap >= 0:
                    late.append(gap)
                else:
                    early.append(-gap)
        out[name] = {
            "n": sum(len(rows) for rows in groups.values()),
            "early_ad_seconds_if_unmuted_then": round(float(np.sum(early)), 1) if early else 0.0,
            "late_program_seconds_if_still_muted": round(float(np.sum(late)), 1) if late else 0.0,
            "median_abs_error_s": round(float(np.median([abs(timer - row["duration_s"]) for rows in groups.values() for row in rows])), 3),
        }
    running_early = []
    running_late = []
    running_abs = []
    for rows in groups.values():
        seen: list[float] = []
        for row in rows:
            if not seen:
                seen.append(row["duration_s"])
                continue
            pred = float(np.median(seen))
            gap = pred - row["duration_s"]
            running_abs.append(abs(gap))
            if gap >= 0:
                running_late.append(gap)
            else:
                running_early.append(-gap)
            seen.append(row["duration_s"])
    out["within_game_running_median"] = {
        "n_predicted": len(running_abs),
        "early_ad_seconds_if_unmuted_then": round(float(np.sum(running_early)), 1) if running_early else 0.0,
        "late_program_seconds_if_still_muted": round(float(np.sum(running_late)), 1) if running_late else 0.0,
        "median_abs_error_s": None if not running_abs else round(float(np.median(running_abs)), 3),
    }
    return out


def components(cosine: np.ndarray, threshold: float) -> list[list[int]]:
    n = cosine.shape[0]
    seen = np.zeros(n, dtype=bool)
    groups = []
    for index in range(n):
        if seen[index]:
            continue
        stack = [index]
        seen[index] = True
        group = []
        while stack:
            current = stack.pop()
            group.append(current)
            for other in np.flatnonzero(cosine[current] >= threshold):
                if not seen[other]:
                    seen[other] = True
                    stack.append(int(other))
        groups.append(group)
    return groups


def main() -> None:
    catalog = load_catalog()
    spans = coverage()
    rows = commercials(spans)
    if len(rows) != 166:
        raise SystemExit(f"expected 166 target commercials inside coverage, found {len(rows)}")
    prepared = []
    for row in rows:
        info = catalog.get(row["session"], {})
        prepared.append(
            {
                "session": row["session"],
                "network": info.get("network_or_service") or "unknown",
                "content": info.get("content_type") or "",
                "show": info.get("show") or "",
                "start_s": float(row["start_seconds"]),
                "end_s": float(row["end_seconds"]),
                "duration_s": float(row["end_seconds"]) - float(row["start_seconds"]),
                "clock": "capture-order" if row["session"] == "hush_20261008_205100" else "recording",
            }
        )
    football = [row for row in prepared if row["content"] == "sports"]
    by_network: dict[str, list[dict]] = {}
    for row in football:
        by_network.setdefault(row["network"], []).append(row)
    clock = {
        "all_target_commercials": summarize_durations(prepared),
        "football_only": summarize_durations(football),
        "by_network_football": {name: summarize_durations(group) for name, group in sorted(by_network.items())},
        "hypothetical_timer_football_only": timer_errors(by_network),
        "note": "A timer error assumes the mute is already on. It is not a start detector and it is not an authorized unmute rule.",
    }

    sessions = {}
    for span in spans:
        sid = span["session"]
        if sid in sessions:
            continue
        folder = find_session(RECORDINGS, sid)
        meta = load_session(folder)
        if int(meta["sample_rate_hz"]) != SR or int(meta["channels"]) != 2:
            raise SystemExit(f"{sid} is not 48 kHz stereo")
        sessions[sid] = {"dir": folder, "meta": meta, "coverage": (float(span["from_seconds"]), float(span["to_seconds"]))}

    def safe_read(sid: str, t0: float, t1: float) -> np.ndarray | None:
        cov0, cov1 = sessions[sid]["coverage"]
        if t0 < cov0 or t1 > cov1:
            return None
        try:
            return read_span(sessions[sid]["dir"], sessions[sid]["meta"], t0, t1)
        except RuntimeError:
            return None

    boundary_features = []
    signatures = []
    for row in prepared:
        sid = row["session"]
        for kind, origin in (("start", row["start_s"]), ("end", row["end_s"])):
            block = safe_read(sid, origin - 5.0, origin + 2.0)
            if block is None or len(block) < int(6.5 * SR):
                continue
            pre = block[int(3.0 * SR) : int(5.0 * SR)]
            post = block[int(5.0 * SR) : int(6.0 * SR)]
            base = block[int(0.0 * SR) : int(4.5 * SR)]
            pre_a = acoustics(pre)
            post_a = acoustics(post)
            base_flux = acoustics(base)["flux"]
            boundary_features.append(
                {
                    "session": sid,
                    "network": row["network"],
                    "content": row["content"],
                    "kind": kind,
                    "origin_s": origin,
                    "delta_rms_db": post_a["rms_db"] - pre_a["rms_db"],
                    "delta_crest": post_a["crest"] - pre_a["crest"],
                    "delta_centroid": post_a["centroid_hz"] - pre_a["centroid_hz"],
                    "delta_flatness": post_a["flatness"] - pre_a["flatness"],
                    "delta_stereo_corr": post_a["stereo_corr"] - pre_a["stereo_corr"],
                    "delta_side_ratio": post_a["side_ratio"] - pre_a["side_ratio"],
                    "delta_high_ratio": post_a["high_ratio"] - pre_a["high_ratio"],
                    "post_flux": post_a["flux"],
                    "base_flux": base_flux,
                    "splice": bool(base_flux > 0 and post_a["flux"] >= SPLICE_RATIO * base_flux),
                }
            )
            signatures.append(
                {
                    "session": sid,
                    "network": row["network"],
                    "content": row["content"],
                    "kind": kind,
                    "origin_s": origin,
                    "signature": pre_a["signature"],
                    "chroma": pre_a["chroma"],
                    "where": "before_boundary",
                }
            )

    controls = []
    control_signatures = []
    rng = np.random.default_rng(20261013)
    for sid, bag in sessions.items():
        cov0, cov1 = bag["coverage"]
        banned = []
        for row in prepared:
            if row["session"] == sid:
                banned.append((row["start_s"] - 20.0, row["end_s"] + 20.0))
        times = np.arange(cov0 + 30.0, cov1 - 30.0, 45.0)
        times = [float(t) for t in times if not any(lo <= t <= hi for lo, hi in banned)]
        if len(times) > 40:
            times = list(rng.choice(times, size=40, replace=False))
        info = catalog.get(sid, {})
        for origin in times:
            block = safe_read(sid, origin - 5.0, origin + 2.0)
            if block is None or len(block) < int(6.5 * SR):
                continue
            pre = block[int(3.0 * SR) : int(5.0 * SR)]
            post = block[int(5.0 * SR) : int(6.0 * SR)]
            base = block[0 : int(4.5 * SR)]
            pre_a = acoustics(pre)
            post_a = acoustics(post)
            base_flux = acoustics(base)["flux"]
            controls.append(
                {
                    "session": sid,
                    "network": info.get("network_or_service") or "unknown",
                    "delta_rms_db": post_a["rms_db"] - pre_a["rms_db"],
                    "delta_crest": post_a["crest"] - pre_a["crest"],
                    "delta_centroid": post_a["centroid_hz"] - pre_a["centroid_hz"],
                    "delta_flatness": post_a["flatness"] - pre_a["flatness"],
                    "delta_stereo_corr": post_a["stereo_corr"] - pre_a["stereo_corr"],
                    "delta_side_ratio": post_a["side_ratio"] - pre_a["side_ratio"],
                    "delta_high_ratio": post_a["high_ratio"] - pre_a["high_ratio"],
                    "post_flux": post_a["flux"],
                    "base_flux": base_flux,
                    "splice": bool(base_flux > 0 and post_a["flux"] >= SPLICE_RATIO * base_flux),
                }
            )
            control_signatures.append(
                {
                    "session": sid,
                    "network": controls[-1]["network"],
                    "signature": pre_a["signature"],
                    "chroma": pre_a["chroma"],
                }
            )

    start_hits: dict[str, set[tuple[str, float]]] = {name: set() for name in (
        "delta_rms_db",
        "delta_crest",
        "delta_centroid",
        "delta_flatness",
        "delta_stereo_corr",
        "delta_side_ratio",
        "delta_high_ratio",
    )}
    feature_names = (
        "delta_rms_db",
        "delta_crest",
        "delta_centroid",
        "delta_flatness",
        "delta_stereo_corr",
        "delta_side_ratio",
        "delta_high_ratio",
    )
    loo_features = {}
    redzone_false = {name: {"false_hits": 0, "tested": 0} for name in feature_names}
    start_rows = []
    for name in feature_names:
        hits = 0
        tested = 0
        false_hits = 0
        false_tested = 0
        for sid in {row["session"] for row in boundary_features}:
            others = [abs(row[name]) for row in controls if row["session"] != sid]
            if len(others) < 20:
                continue
            level = percentile(others, 95)
            for row in boundary_features:
                if row["session"] != sid or row["kind"] != "start":
                    continue
                tested += 1
                fired = abs(row[name]) >= level
                if fired:
                    hits += 1
                    start_hits[name].add((row["session"], round(row["origin_s"], 3)))
                if name == feature_names[0]:
                    start_rows.append(row)
            for row in controls:
                if row["session"] != sid:
                    continue
                false_tested += 1
                fired = abs(row[name]) >= level
                if fired:
                    false_hits += 1
                if sid == "hush_20260913_150934":
                    redzone_false[name]["tested"] += 1
                    if fired:
                        redzone_false[name]["false_hits"] += 1
        loo_features[name] = {
            "starts_exceeding_other_recordings_program_p95": hits,
            "starts_tested": tested,
            "program_windows_exceeding_same_bar": false_hits,
            "program_windows_tested": false_tested,
            "program_false_fraction": None if false_tested == 0 else round(false_hits / false_tested, 4),
        }
    splice_starts = [row for row in boundary_features if row["kind"] == "start"]
    flat = start_hits["delta_flatness"]
    rms = start_hits["delta_rms_db"]
    centroid = start_hits["delta_centroid"]

    def _ratio(rows: list[dict]) -> dict:
        vals = [row["post_flux"] / row["base_flux"] for row in rows if row.get("base_flux", 0) > 0]
        if not vals:
            return {"n": 0}
        arr = np.asarray(vals, dtype=np.float64)
        return {"n": int(arr.size), "p50": round(float(np.median(arr)), 3), "p90": round(float(np.percentile(arr, 90)), 3)}

    loo_features["overlap"] = {
        "flatness": len(flat),
        "rms": len(rms),
        "centroid": len(centroid),
        "flatness_and_rms": len(flat & rms),
        "flatness_only": len(flat - rms - centroid),
        "rms_only": len(rms - flat - centroid),
        "centroid_only": len(centroid - flat - rms),
        "any_of_three": len(flat | rms | centroid),
    }
    loo_features["flux_ratio_starts"] = _ratio(splice_starts)
    loo_features["flux_ratio_program"] = _ratio(controls)
    redzone_id = "hush_20260913_150934"
    redzone_rows = [row for row in controls if row["session"] == redzone_id]
    redzone_scored = {}
    for name in feature_names:
        others = [abs(row[name]) for row in controls if row["session"] != redzone_id]
        level = percentile(others, 95)
        hits = sum(1 for row in redzone_rows if abs(row[name]) >= level)
        redzone_scored[name] = {
            "false_hits": hits,
            "tested": len(redzone_rows),
            "other_recordings_program_p95": round(float(level), 6),
        }
    import csv
    cnn_rows = []
    with (REPO / "docs/ohush/research/AUDIO_SIGNAL_REPLICATION_001/nbc_breaks.csv").open(encoding="utf-8") as handle:
        cnn_rows = list(csv.DictReader(handle))
    sept9 = []
    for row in start_rows:
        if row["session"] != "hush_20260909_213047" or row["kind"] != "start":
            continue
        key = (row["session"], round(float(row["origin_s"]), 3))
        match = None
        for cnn in cnn_rows:
            if abs(float(cnn["start_s"]) - float(row["origin_s"])) <= 0.05:
                match = cnn
                break
        flags = {name: key in start_hits[name] for name in feature_names}
        sept9.append({
            "start_s": round(float(row["origin_s"]), 3),
            "dsp_flatness": flags["delta_flatness"],
            "dsp_rms": flags["delta_rms_db"],
            "dsp_centroid": flags["delta_centroid"],
            "dsp_any_of_three": flags["delta_flatness"] or flags["delta_rms_db"] or flags["delta_centroid"],
            "cnn_failure": None if match is None else match["failure"],
            "cnn_median_rises": None if match is None else match["median_rises"] == "True",
            "cnn_causal_hit_s": None if match is None or match["first_causal_hit_during_break_s"] == "" else float(match["first_causal_hit_during_break_s"]),
        })
    cnn_causal = [row for row in sept9 if row["cnn_causal_hit_s"] is not None]
    dsp_only = [row for row in sept9 if row["dsp_any_of_three"] and row["cnn_causal_hit_s"] is None]
    cnn_only = [row for row in sept9 if row["cnn_causal_hit_s"] is not None and not row["dsp_any_of_three"]]
    both = [row for row in sept9 if row["dsp_any_of_three"] and row["cnn_causal_hit_s"] is not None]
    forensics = {
        "format": "Every closed session used here is 48 kHz stereo PCM. Commercials are not a different sample rate or codec inside this capture.",
        "causal_rule": "Compare the 1 s after the boundary with the 2 s before it. Available 1 s after the boundary. Splice ratio 3 was not fit.",
        "n_start_windows": len(splice_starts),
        "n_program_windows": len(controls),
        "splice_starts": sum(1 for row in splice_starts if row["splice"]),
        "splice_program_controls": sum(1 for row in controls if row["splice"]),
        "leave_one_recording_features": loo_features,
        "redzone_program_windows": redzone_scored,
        "sept9_nbc_vs_published_cnn14": {
            "note": "Joined to AUDIO_SIGNAL_REPLICATION_001/nbc_breaks.csv by start time. CNN causal hit is the published first exceedance during the break, including hits under 10 s that still contain pre-break audio. This join does not retune either detector.",
            "starts_joined": len(sept9),
            "dsp_any_of_three": sum(1 for row in sept9 if row["dsp_any_of_three"]),
            "cnn_causal_hit_recorded": len(cnn_causal),
            "both": len(both),
            "dsp_only": len(dsp_only),
            "cnn_only": len(cnn_only),
            "neither": sum(1 for row in sept9 if not row["dsp_any_of_three"] and row["cnn_causal_hit_s"] is None),
            "breaks": sept9,
        },
    }

    def motif_report(kind: str, field: str) -> dict:
        grouped: dict[str, list[dict]] = {}
        for row in signatures:
            if row["kind"] == kind and row["content"] == "sports":
                grouped.setdefault(row["network"], []).append(row)
        networks = {}
        for network, items in grouped.items():
            matrix = np.vstack([row[field] for row in items])
            cosine = matrix @ matrix.T
            np.fill_diagonal(cosine, 0.0)
            groups = [group for group in components(cosine, COPY_COSINE) if len(group) >= 3]
            tri = cosine[np.triu_indices(len(items), 1)]
            within_median = None if tri.size == 0 else round(float(np.median(tri)), 4)
            cross = []
            for row in items:
                peers = [control[field] for control in control_signatures if control["session"] == row["session"]]
                if peers:
                    bank = np.vstack(peers)
                    cross.append(float(np.median(bank @ row[field])))
            program_median = None if not cross else round(float(np.median(cross)), 4)
            sessions_in = {row["session"] for row in items}
            loo_hits = 0
            loo_tested = 0
            loo_false = 0
            loo_false_tested = 0
            for sid in sessions_in:
                train = [row for row in items if row["session"] != sid]
                test = [row for row in items if row["session"] == sid]
                if len(train) < 3 or not test:
                    continue
                train_matrix = np.vstack([row[field] for row in train])
                train_cosine = train_matrix @ train_matrix.T
                np.fill_diagonal(train_cosine, 0.0)
                centroids = []
                for group in components(train_cosine, COPY_COSINE):
                    if len(group) < 3:
                        continue
                    centroid = np.mean(train_matrix[group], axis=0)
                    centroids.append(centroid / (np.linalg.norm(centroid) + 1e-12))
                if not centroids:
                    loo_tested += len(test)
                    loo_false_tested += sum(1 for row in control_signatures if row["session"] == sid)
                    continue
                bank = np.vstack(centroids)
                loo_tested += len(test)
                loo_hits += sum(1 for row in test if float(np.max(bank @ row[field])) >= COPY_COSINE)
                held_controls = [row for row in control_signatures if row["session"] == sid]
                loo_false_tested += len(held_controls)
                loo_false += sum(1 for row in held_controls if float(np.max(bank @ row[field])) >= COPY_COSINE)
            networks[network] = {
                "boundaries": len(items),
                "recordings": len(sessions_in),
                "within_recording_motifs_of_at_least_3": len(groups),
                "largest_motif": max((len(group) for group in groups), default=0),
                "median_cosine_among_boundaries": within_median,
                "median_cosine_to_same_recording_program": program_median,
                "leave_one_recording_matches": loo_hits,
                "leave_one_recording_tested": loo_tested,
                "leave_one_recording_program_false_matches": loo_false,
                "leave_one_recording_program_windows": loo_false_tested,
            }
        return networks

    music = {
        "signature": "24 log-frequency bands, 80 Hz to 8 kHz, 2 s immediately before the boundary",
        "near_copy_cosine": COPY_COSINE,
        "average_spectrum_before_starts": motif_report("start", "signature"),
        "average_spectrum_before_ends": motif_report("end", "signature"),
        "chroma_sequence_before_starts": motif_report("start", "chroma"),
        "chroma_sequence_before_ends": motif_report("end", "chroma"),
        "placement": "These windows are placed with the closed boundary. A match in the 2 s before the start is audio that has already played by the labeled IN. It is not proof of a detector that runs without that label.",
    }

    OUT.mkdir(parents=True, exist_ok=True)
    payload = {"clock": clock, "forensics": forensics, "music": music, "n_commercials": len(prepared)}
    (OUT / "batch1_results.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    fig, ax = plt.subplots(figsize=(8, 4))
    for name, group in sorted(by_network.items()):
        ax.hist([row["duration_s"] for row in group], bins=np.arange(0, 360, 15), histtype="step", linewidth=1.6, label=f"{name} ({len(group)})")
    ax.axvline(120, color="#888888", lw=0.8)
    ax.axvline(135, color="#888888", lw=0.8, ls="--")
    ax.set_xlabel("closed commercial interval, seconds")
    ax.set_ylabel("pods")
    ax.set_title("Football pods. Lines mark 2:00 and 2:15.")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(OUT / "break_durations.png", dpi=120)
    plt.close(fig)
    print(json.dumps({
        "football": clock["football_only"],
        "timers": clock["hypothetical_timer_football_only"],
        "splice": forensics["splice_starts"],
        "overlap": forensics["leave_one_recording_features"]["overlap"],
        "chroma_starts": music["chroma_sequence_before_starts"],
    }, indent=2))


if __name__ == "__main__":
    main()
