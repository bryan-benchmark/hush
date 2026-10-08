"""Draw existing commercial boundaries on Experiment 001. Does not rescore anything."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "experiments"))

import ledger  # noqa: E402

SCORE = "euclid_60"
COLLARS = (2.0, 5.0, 10.0)
FALSE_RADIUS_S = 10.0

SERIES = {
    "overall_change_scores.png": [
        ("euclid 30s", "euclid_30"),
        ("euclid 60s", "euclid_60"),
        ("euclid 120s", "euclid_120"),
        ("cosine 60s", "cosine_60"),
        ("mahal 60s", "mahal_60"),
        ("symKL 60s", "symkl_60"),
        ("energy 60s", "energy_distance_60s"),
        ("frozen euclid", "frozen_euclid"),
    ],
    "mfcc_change.png": [(f"mfcc euclid {w}", f"mfcc_euclid_{w}") for w in (30, 60, 120)],
    "loudness_dynamics.png": [
        ("rms dBFS", "rms_dbfs"),
        ("momentary LUFS", "momentary_lufs"),
        ("short-term LUFS 3s", "short_term_lufs"),
        ("LUFS var 5s", "lufs_var_5s"),
        ("LUFS var 15s", "lufs_var_15s"),
        ("LUFS shift 60s", "lufs_shift_60"),
    ],
    "spectral_change.png": [(f"spectral euclid {w}", f"spectral_euclid_{w}") for w in (30, 60, 120)],
    "rhythm_onset_change.png": [
        ("onset shift 60s", "onset_shift_60"),
        ("modulation shift 60s", "modulation_shift_60"),
        ("onset density", "onset_density"),
        ("rhythm Hz", "rhythm_mod_hz"),
    ],
    "stereo_production.png": [
        ("L/R correlation", "lr_correlation"),
        ("side/mid", "side_mid_ratio"),
        ("interchannel dB", "interchannel_db"),
    ],
}


def commercial_breaks(session: str) -> list[dict]:
    rows = ledger.resolve_ledger(ledger.read_jsonl(ledger.TRUTH_PATH), "gold_id")
    breaks = [
        row
        for row in rows
        if row.get("session") == session
        and row.get("event") == "ad_break"
        and row.get("event_class") == "commercial"
        and row.get("desired_action") == "mute"
        and row.get("confidence") != "unsure"
        and not row.get("retracted")
    ]
    breaks.sort(key=lambda row: float(row["start_seconds"]))
    if not breaks:
        raise RuntimeError(f"no commercial breaks for {session}")
    return breaks


def local_maxima(values: np.ndarray) -> np.ndarray:
    if values.size < 3:
        return np.array([], dtype=np.int64)
    mid = values[1:-1]
    ok = np.isfinite(mid) & np.isfinite(values[:-2]) & np.isfinite(values[2:])
    return np.flatnonzero(ok & (mid > values[:-2]) & (mid > values[2:])).astype(np.int64) + 1


def robust(y: np.ndarray) -> np.ndarray:
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


def window_max(times: np.ndarray, values: np.ndarray, t: float, radius: float) -> float | None:
    chosen = values[np.abs(times - t) <= radius]
    chosen = chosen[np.isfinite(chosen)]
    if chosen.size == 0:
        return None
    return float(np.max(chosen))


def nearest_peak(peak_times: np.ndarray, peak_scores: np.ndarray, t: float) -> tuple[float, float, float]:
    delta = peak_times - t
    idx = int(np.argmin(np.abs(delta)))
    return float(peak_times[idx]), float(delta[idx]), float(peak_scores[idx])


def percentile_among(scores: np.ndarray, value: float) -> float:
    return float(100.0 * np.mean(scores <= value))


def boundary_row(
    kind: str,
    break_index: int,
    boundary: float,
    times: np.ndarray,
    values: np.ndarray,
    state: np.ndarray,
    peak_times: np.ndarray,
    peak_scores: np.ndarray,
) -> dict:
    peak_t, delay, peak_score = nearest_peak(peak_times, peak_scores, boundary)
    nearest_row = int(np.argmin(np.abs(times - boundary)))
    row = {
        "break_index": break_index,
        "boundary": kind,
        "boundary_seconds": boundary,
        "nearest_peak_seconds": peak_t,
        "delay_seconds": delay,
        "peak_score": peak_score,
        "peak_percentile": percentile_among(peak_scores, peak_score),
        "frozen": bool(state[nearest_row] == "frozen"),
        "peak_within_10s": abs(delay) <= FALSE_RADIUS_S,
    }
    for radius in COLLARS:
        row[f"max_score_pm_{int(radius)}s"] = window_max(times, values, boundary, radius)
    return row


def shade(ax, breaks: list[dict]) -> None:
    for i, row in enumerate(breaks):
        start = float(row["start_seconds"]) / 60.0
        end = float(row["end_seconds"]) / 60.0
        ax.axvspan(start, end, color="0.75", alpha=0.35, zorder=0, label="commercial pod" if i == 0 else None)
        ax.axvline(start, color="tab:green", linewidth=0.8, zorder=1, label="break start" if i == 0 else None)
        ax.axvline(end, color="tab:red", linewidth=0.8, linestyle="--", zorder=1, label="break end" if i == 0 else None)


def draw(path: Path, minutes: np.ndarray, frame: pd.DataFrame, breaks: list[dict], series: list[tuple[str, str]], title: str) -> None:
    fig, ax = plt.subplots(figsize=(14, 5))
    shade(ax, breaks)
    for label, column in series:
        ax.plot(minutes, robust(frame[column].to_numpy(dtype=float)), linewidth=0.8, label=label, zorder=2)
    ax.set_xlabel("minutes")
    ax.set_ylabel("robust units (median / IQR, display only)")
    ax.set_title(title)
    ax.legend(loc="upper right", fontsize=7, ncol=3)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=120)
    plt.close(fig)


def draw_overall(path: Path, minutes: np.ndarray, frame: pd.DataFrame, breaks: list[dict]) -> None:
    fig, axes = plt.subplots(2, 1, figsize=(14, 8), sharex=True)
    for ax in axes:
        shade(ax, breaks)
    for label, column in SERIES["overall_change_scores.png"]:
        axes[0].plot(minutes, robust(frame[column].to_numpy(dtype=float)), linewidth=0.8, label=label, zorder=2)
    axes[0].set_ylabel("robust units")
    axes[0].set_title("causal change scores with commercial labels")
    axes[0].legend(loc="upper right", fontsize=7, ncol=4)
    axes[1].plot(minutes, robust(frame["foote_novelty"].to_numpy(dtype=float)), linewidth=0.8, label="foote novelty (uses future)", zorder=2)
    axes[1].plot(
        minutes,
        robust(frame["foote_cosine_distance"].to_numpy(dtype=float)),
        linewidth=0.8,
        label="foote cosine (uses future)",
        zorder=2,
    )
    axes[1].set_xlabel("minutes")
    axes[1].set_ylabel("robust units")
    axes[1].set_title("non-causal diagnostic with commercial labels")
    axes[1].legend(loc="upper right", fontsize=8)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=120)
    plt.close(fig)


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def run(parquet: Path, output: Path, session: str) -> dict:
    frame = pd.read_parquet(parquet)
    breaks = commercial_breaks(session)
    times = frame["timestamp_seconds"].to_numpy(dtype=float)
    values = frame[SCORE].to_numpy(dtype=float)
    state = frame["baseline_state"].to_numpy()
    peak_idx = local_maxima(values)
    peak_times = times[peak_idx]
    peak_scores = values[peak_idx]
    if peak_times.size == 0:
        raise RuntimeError(f"no local maxima in {SCORE}")

    rows = []
    for i, row in enumerate(breaks, start=1):
        pod_times = times[(times >= float(row["start_seconds"])) & (times <= float(row["end_seconds"]))]
        pod_state = state[(times >= float(row["start_seconds"])) & (times <= float(row["end_seconds"]))]
        frozen_in_pod = bool(np.any(pod_state == "frozen")) if pod_times.size else False
        for kind, boundary in (("start", float(row["start_seconds"])), ("end", float(row["end_seconds"]))):
            item = boundary_row(kind, i, boundary, times, values, state, peak_times, peak_scores)
            item["pod_start_seconds"] = float(row["start_seconds"])
            item["pod_end_seconds"] = float(row["end_seconds"])
            item["frozen_in_pod"] = frozen_in_pod
            item["gold_id"] = row["gold_id"]
            rows.append(item)

    boundary_times = np.array(
        [float(row["start_seconds"]) for row in breaks] + [float(row["end_seconds"]) for row in breaks]
    )
    outside = np.array([np.min(np.abs(boundary_times - t)) > FALSE_RADIUS_S for t in peak_times])
    start_scores = np.array([row["peak_score"] for row in rows if row["boundary"] == "start"])
    end_scores = np.array([row["peak_score"] for row in rows if row["boundary"] == "end"])
    both_scores = np.concatenate([start_scores, end_scores])
    thresholds = {
        "median_nearest_start_peak": float(np.median(start_scores)),
        "median_nearest_end_peak": float(np.median(end_scores)),
        "median_nearest_boundary_peak": float(np.median(both_scores)),
    }
    outside_scores = peak_scores[outside]
    false_counts = {
        name: int(np.sum(outside_scores >= threshold))
        for name, threshold in thresholds.items()
    }
    false_peaks = [
        {"timestamp_seconds": float(t), "score": float(s)}
        for t, s in zip(peak_times[outside], outside_scores)
        if s >= thresholds["median_nearest_boundary_peak"]
    ]
    false_peaks.sort(key=lambda item: item["score"], reverse=True)

    plots = output / "plots_labeled"
    minutes = times / 60.0
    draw_overall(plots / "overall_change_scores.png", minutes, frame, breaks)
    titles = {
        "mfcc_change.png": "MFCC distribution change with commercial labels",
        "loudness_dynamics.png": "Loudness and dynamic range with commercial labels",
        "spectral_change.png": "Spectral change with commercial labels",
        "rhythm_onset_change.png": "Rhythm and onset change with commercial labels",
        "stereo_production.png": "Stereo production with commercial labels",
    }
    for name, series in SERIES.items():
        if name == "overall_change_scores.png":
            continue
        draw(plots / name, minutes, frame, breaks, series, titles[name])

    write_csv(output / "overlay_boundaries.csv", rows)
    summary = {
        "experiment_spec_version": "exp001-v1",
        "score": SCORE,
        "score_note": "Local maxima of euclid_60. No score was recomputed and no threshold was fit to labels.",
        "session": session,
        "n_breaks": len(breaks),
        "n_local_maxima": int(peak_times.size),
        "false_radius_seconds": FALSE_RADIUS_S,
        "n_peaks_outside_10s_of_any_boundary": int(np.sum(outside)),
        "similarly_large_definition": "outside peak score >= median nearest-boundary peak score",
        "thresholds": thresholds,
        "false_peaks_at_least_as_large": false_counts,
        "false_peak_times_vs_median_boundary": false_peaks,
        "boundaries": rows,
        "plot_dir": str(plots),
    }
    (output / "overlay_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Overlay frozen Experiment 001 scores with commercial truth")
    parser.add_argument(
        "--parquet",
        type=Path,
        default=Path("experiments/exp001/hush_20260914_212529/features.parquet"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("experiments/exp001/hush_20260914_212529"),
    )
    parser.add_argument("--session", default="hush_20260914_212529")
    args = parser.parse_args(argv)
    summary = run(args.parquet, args.output, args.session)
    print(json.dumps({k: summary[k] for k in (
        "n_breaks",
        "n_local_maxima",
        "n_peaks_outside_10s_of_any_boundary",
        "thresholds",
        "false_peaks_at_least_as_large",
    )}, indent=2))


if __name__ == "__main__":
    main()
