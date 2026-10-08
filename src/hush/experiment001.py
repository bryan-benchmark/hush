"""Experiment 001: are commercial breaks visible from acoustics alone?

The first run writes unlabeled scores. It does not read the truth ledger.
"""

from __future__ import annotations

import os

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")
os.environ.setdefault(
    "MPLCONFIGDIR",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".mplconfig")),
)

import argparse
import json
import platform
import subprocess
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from hush.audio import (
    RAW_SR,
    analysis_pieces,
    find_session,
    load_session,
    read_stereo,
    resample_concat,
    write_mono_wav,
)
from hush.change import EXPERIMENT_SPEC_VERSION, PARAMS as CHANGE_PARAMS
from hush.change import compute_change_scores
from hush.features import FEATURE_SCHEMA_VERSION, PARAMS as FEATURE_PARAMS
from hush.features import HOP_S, WIN_S, add_trailing_means, mono_features, stereo_production

MONO_SR = 16000
REPO_ROOT = Path(__file__).resolve().parents[2]


def _pkg(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:
        return "not-installed"


def _git_sha(root: Path) -> str | None:
    probe = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if probe.returncode != 0 or probe.stdout.strip() != "true":
        return None
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True)
    return head.stdout.strip()


def _prepare(session_dir: Path, meta: dict, t0: float, t1: float, derived_wav: Path) -> tuple[np.ndarray, dict[str, np.ndarray], list[dict]]:
    pieces = analysis_pieces(session_dir, meta, t0, t1)
    mono_parts: list[np.ndarray] = []
    stereo_parts: dict[str, list[np.ndarray]] = {}
    carry = np.zeros((0, 2), dtype=np.float32)
    carry_origin = t0
    covered_until = t0
    for piece in pieces:
        print(f"reading {piece['file']} {piece['session_start_seconds']:.1f}..{piece['session_end_seconds']:.1f}", flush=True)
        stereo = read_stereo(piece)
        mono_parts.append(stereo.mean(axis=1))
        if carry.shape[0]:
            buf = np.concatenate([carry, stereo], axis=0)
            origin = carry_origin
        else:
            buf = stereo
            origin = piece["session_start_seconds"]
        produced = stereo_production(buf, RAW_SR, origin)
        keep = (produced["timestamp_seconds"] > covered_until + 1e-9) & (
            produced["timestamp_seconds"] <= piece["session_end_seconds"] + 1e-9
        )
        for key, values in produced.items():
            stereo_parts.setdefault(key, []).append(np.asarray(values)[keep])
        tail = int(round(WIN_S * RAW_SR))
        if stereo.shape[0] >= tail:
            carry = stereo[-tail:].copy()
            carry_origin = piece["session_end_seconds"] - WIN_S
        else:
            carry = stereo.copy()
            carry_origin = piece["session_start_seconds"]
        covered_until = piece["session_end_seconds"]
        del stereo, buf
    print("resampling one continuous 48 kHz mono stream", flush=True)
    mono16 = np.asarray(resample_concat(mono_parts, up=1, down=3), dtype=np.float32)
    expected = int(round((t1 - t0) * MONO_SR))
    if abs(len(mono16) - expected) > 1:
        raise RuntimeError(f"resampled length {len(mono16)} != {expected}")
    if len(mono16) != expected:
        mono16 = mono16[:expected]
    del mono_parts
    write_mono_wav(derived_wav, mono16, MONO_SR)
    stereo_cols = {key: np.concatenate(parts) for key, parts in stereo_parts.items()}
    return mono16, stereo_cols, pieces


def _merge(mono_cols: dict[str, np.ndarray], stereo_cols: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    if len(mono_cols["timestamp_seconds"]) != len(stereo_cols["timestamp_seconds"]):
        raise RuntimeError(
            f"mono windows {len(mono_cols['timestamp_seconds'])} != stereo windows {len(stereo_cols['timestamp_seconds'])}"
        )
    if not np.allclose(mono_cols["timestamp_seconds"], stereo_cols["timestamp_seconds"], atol=1e-6):
        raise RuntimeError("mono and stereo timestamps do not match")
    merged = dict(mono_cols)
    for key in ("lr_correlation", "side_mid_ratio", "interchannel_db"):
        merged[key] = stereo_cols[key]
    return merged


def _robust(y: np.ndarray) -> np.ndarray:
    y = np.asarray(y, dtype=np.float64)
    finite = y[np.isfinite(y)]
    if finite.size == 0:
        return np.zeros_like(y)
    med = float(np.median(finite))
    q1, q3 = np.percentile(finite, [25, 75])
    iqr = float(q3 - q1)
    if not np.isfinite(iqr) or iqr < 1e-12:
        return np.zeros_like(y)
    return (y - med) / iqr


def _plot_series(path: Path, minutes: np.ndarray, series: list[tuple[str, np.ndarray]], title: str) -> None:
    fig, ax = plt.subplots(figsize=(14, 5))
    for label, values in series:
        ax.plot(minutes, _robust(values), linewidth=0.8, label=label)
    ax.set_xlabel("minutes")
    ax.set_ylabel("robust units (median / IQR, display only)")
    ax.set_title(title)
    ax.legend(loc="upper right", fontsize=8, ncol=2)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=120)
    plt.close(fig)


def _plot_overall(path: Path, minutes: np.ndarray, scores: dict[str, np.ndarray]) -> None:
    fig, axes = plt.subplots(2, 1, figsize=(14, 8), sharex=True)
    causal = [
        ("euclid 30s", scores["euclid_30"]),
        ("euclid 60s", scores["euclid_60"]),
        ("euclid 120s", scores["euclid_120"]),
        ("cosine 60s", scores["cosine_60"]),
        ("mahal 60s", scores["mahal_60"]),
        ("symKL 60s", scores["symkl_60"]),
        ("energy 60s", scores["energy_distance_60s"]),
        ("frozen euclid", scores["frozen_euclid"]),
    ]
    for label, values in causal:
        axes[0].plot(minutes, _robust(values), linewidth=0.8, label=label)
    axes[0].set_ylabel("robust units")
    axes[0].set_title("causal change scores (no commercial labels)")
    axes[0].legend(loc="upper right", fontsize=7, ncol=4)
    axes[1].plot(minutes, _robust(scores["foote_novelty"]), linewidth=0.8, label="foote novelty (uses future)")
    axes[1].plot(minutes, _robust(scores["foote_cosine_distance"]), linewidth=0.8, label="foote cosine (uses future)")
    axes[1].set_xlabel("minutes")
    axes[1].set_ylabel("robust units")
    axes[1].set_title("non-causal diagnostic")
    axes[1].legend(loc="upper right", fontsize=8)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=120)
    plt.close(fig)


def _top_events(timestamps: np.ndarray, values: np.ndarray, gap_s: float, k: int = 20) -> list[dict]:
    order = np.argsort(np.where(np.isfinite(values), values, -np.inf))[::-1]
    chosen: list[int] = []
    for idx in order:
        if not np.isfinite(values[idx]):
            break
        t = float(timestamps[idx])
        if any(abs(t - float(timestamps[j])) < gap_s for j in chosen):
            continue
        chosen.append(int(idx))
        if len(chosen) >= k:
            break
    return [
        {"timestamp_seconds": float(timestamps[i]), "score": float(values[i])}
        for i in chosen
    ]


def _frozen_intervals(timestamps: np.ndarray, state: np.ndarray) -> list[dict]:
    intervals = []
    start = None
    for t, name in zip(timestamps, state):
        if name == "frozen" and start is None:
            start = float(t)
        elif name != "frozen" and start is not None:
            intervals.append({"start_seconds": start, "end_seconds": float(t)})
            start = None
    if start is not None:
        intervals.append({"start_seconds": start, "end_seconds": float(timestamps[-1])})
    return intervals


def _seam_hits(events: list[dict], seams: list[float], radius_s: float = 2.0) -> list[dict]:
    hits = []
    for event in events:
        t = event["timestamp_seconds"]
        near = [s for s in seams if abs(t - s) <= radius_s]
        if near:
            hits.append({**event, "seams": near})
    return hits


def run(session_id: str, t0: float, t1: float, output: Path, recordings_root: Path) -> None:
    session_dir = find_session(recordings_root, session_id)
    meta = load_session(session_dir)
    output.mkdir(parents=True, exist_ok=True)
    derived = output.parent / "derived" / f"{session_id}_{t0:.0f}_{t1:.0f}_16k_mono.wav"
    mono, stereo_cols, pieces = _prepare(session_dir, meta, t0, t1, derived)
    duration = len(mono) / MONO_SR
    print(f"extracting 16 kHz features, duration {duration:.3f}s", flush=True)
    columns = mono_features(mono, MONO_SR, origin_s=t0)
    del mono
    columns = _merge(columns, stereo_cols)
    add_trailing_means(columns)
    print(f"change scores on {len(columns['timestamp_seconds'])} windows", flush=True)
    scores = compute_change_scores(columns)
    columns.update(scores)
    frame = pd.DataFrame(columns)
    parquet_path = output / "features.parquet"
    frame.to_parquet(parquet_path, index=False)

    minutes = frame["timestamp_seconds"].to_numpy() / 60.0
    plots = output / "plots"
    _plot_overall(plots / "overall_change_scores.png", minutes, scores)
    _plot_series(
        plots / "mfcc_change.png",
        minutes,
        [(f"mfcc euclid {w}", scores[f"mfcc_euclid_{w}"]) for w in (30, 60, 120)],
        "MFCC distribution change",
    )
    _plot_series(
        plots / "loudness_dynamics.png",
        minutes,
        [
            ("rms dBFS", columns["rms_dbfs"]),
            ("momentary LUFS", columns["momentary_lufs"]),
            ("short-term LUFS 3s", columns["short_term_lufs"]),
            ("LUFS var 5s", columns["lufs_var_5s"]),
            ("LUFS var 15s", columns["lufs_var_15s"]),
            ("LUFS shift 60s", scores["lufs_shift_60"]),
        ],
        "Loudness and dynamic range",
    )
    _plot_series(
        plots / "spectral_change.png",
        minutes,
        [(f"spectral euclid {w}", scores[f"spectral_euclid_{w}"]) for w in (30, 60, 120)],
        "Spectral change",
    )
    _plot_series(
        plots / "rhythm_onset_change.png",
        minutes,
        [
            ("onset shift 60s", scores["onset_shift_60"]),
            ("modulation shift 60s", scores["modulation_shift_60"]),
            ("onset density", columns["onset_density"]),
            ("rhythm Hz", columns["rhythm_mod_hz"]),
        ],
        "Rhythm and onset change",
    )
    _plot_series(
        plots / "stereo_production.png",
        minutes,
        [
            ("L/R correlation", columns["lr_correlation"]),
            ("side/mid", columns["side_mid_ratio"]),
            ("interchannel dB", columns["interchannel_db"]),
        ],
        "Stereo production",
    )

    seams = sorted(
        {
            float(piece["chunk_start_seconds"])
            for piece in pieces
            if t0 < float(piece["chunk_start_seconds"]) < t1
        }
    )
    timestamps = frame["timestamp_seconds"].to_numpy()
    causal_top = _top_events(timestamps, scores["euclid_60_median_15"], gap_s=20.0)
    foote_top = _top_events(timestamps, scores["foote_novelty"], gap_s=20.0)
    frozen = _frozen_intervals(timestamps, scores["baseline_state"])
    plot_paths = sorted(str(p) for p in plots.glob("*.png"))
    summary = {
        "experiment_spec_version": EXPERIMENT_SPEC_VERSION,
        "audio_duration_seconds": duration,
        "n_windows": int(len(frame)),
        "timestamp_min": float(timestamps[0]),
        "timestamp_max": float(timestamps[-1]),
        "largest_sustained_change_points": causal_top,
        "top_20_foote_novelty": foote_top,
        "frozen_intervals": frozen,
        "seam_seconds": seams,
        "sustained_events_within_2s_of_a_seam": _seam_hits(causal_top, seams),
        "plot_paths": plot_paths,
        "parquet": str(parquet_path),
        "derived_wav": str(derived),
    }
    (output / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    metadata = {
        "experiment_spec_version": EXPERIMENT_SPEC_VERSION,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "git_commit": _git_sha(REPO_ROOT),
        "python": sys.version,
        "platform": platform.platform(),
        "packages": {
            name: _pkg(name)
            for name in (
                "numpy",
                "scipy",
                "pandas",
                "scikit-learn",
                "librosa",
                "soundfile",
                "matplotlib",
                "pyloudnorm",
                "pyarrow",
            )
        },
        "session_id": session_id,
        "analysis_start_seconds": t0,
        "analysis_end_seconds": t1,
        "analysis_sample_range_48k": {
            "start_inclusive": int(round(t0 * RAW_SR)),
            "stop_exclusive": int(round(t1 * RAW_SR)),
        },
        "resampling": "scipy.signal.resample_poly up=1 down=3 window=(kaiser, 5.0) padtype=constant on one concatenated 48 kHz mono stream. Chunks are not resampled independently.",
        "raw_chunks": [
            {
                "file": piece["file"],
                "file_frames": piece["file_frames"],
                "read_start_frame": piece["read_start_frame"],
                "read_stop_frame": piece["read_stop_frame"],
                "n_samples": piece["n_samples"],
                "session_start_seconds": piece["session_start_seconds"],
                "session_end_seconds": piece["session_end_seconds"],
            }
            for piece in pieces
        ],
        "feature_params": FEATURE_PARAMS,
        "change_params": CHANGE_PARAMS,
        "display_scaling": "plots divide each series by its own full-recording IQR after subtracting the median. Scores in the parquet are not scaled that way.",
        "hop_s": HOP_S,
    }
    (output / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in (
        "audio_duration_seconds",
        "n_windows",
        "largest_sustained_change_points",
        "top_20_foote_novelty",
        "frozen_intervals",
        "sustained_events_within_2s_of_a_seam",
        "plot_paths",
    )}, indent=2))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="OHush experiment 001 acoustic change stream")
    parser.add_argument("--session", default="hush_20260914_212529")
    parser.add_argument("--from-seconds", type=float, default=0.0)
    parser.add_argument("--to-seconds", type=float, default=6899.0)
    parser.add_argument("--output", type=Path, default=Path("experiments/exp001/hush_20260914_212529"))
    parser.add_argument("--recordings-root", type=Path, default=Path("recordings"))
    args = parser.parse_args(argv)
    run(args.session, args.from_seconds, args.to_seconds, args.output, args.recordings_root)


if __name__ == "__main__":
    main()
