"""Ledger audit of a frozen Exp004 listing. Does not move the clock or the peak rule."""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path

os.environ.setdefault(
    "MPLCONFIGDIR",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".mplconfig")),
)

import argparse
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from hush.overlay001 import commercial_breaks, shade
from hush.temporal import (
    DROP_SPAN_S,
    POD_S,
    RETURN_CLOCK_S,
    RETURN_HORIZON_S,
    SPOT_S,
    TOLERANCE_S,
    autocorr,
    gaps,
    grid_residual,
    nearest_mark,
    on_spot_clock,
)

REPO = Path(__file__).resolve().parents[2]
SESSION = "hush_20260914_212529"
HOLDOUTS = ("hush_20260917_205513", "hush_20260920_200635")
ANALYSIS_END = 6899.0
LAGS = (15, 30, 60, 10, 20, 45)


def _clean(value):
    if isinstance(value, dict):
        return {key: _clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(item) for item in value]
    if isinstance(value, (np.floating, float)):
        if not np.isfinite(value):
            return None
        return float(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    return value


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows([_clean(row) for row in rows])


def _gap_report(gap: np.ndarray) -> dict:
    if gap.size == 0:
        return {"n_gaps": 0, "n_on_clock": 0, "fraction": None, "n_near_15": 0, "n_near_30": 0, "n_near_60": 0, "median_s": None}
    near = {mark: int(np.sum(np.abs(gap - mark) <= TOLERANCE_S)) for mark in SPOT_S}
    hit = np.array([on_spot_clock(float(item)) for item in gap])
    return {
        "n_gaps": int(gap.size),
        "n_on_clock": int(hit.sum()),
        "fraction": float(hit.mean()),
        "n_near_15": near[15.0],
        "n_near_30": near[30.0],
        "n_near_60": near[60.0],
        "median_s": float(np.median(gap)),
    }


def _largest_drop(ends: np.ndarray, values: np.ndarray, origin: float, horizon: float) -> dict | None:
    ok = (ends > origin) & (ends <= origin + horizon) & np.isfinite(values)
    if not np.any(ok):
        return None
    # Pair each sample with the sample DROP_SPAN_S later, on this 1 s grid.
    index = np.flatnonzero(ok)
    drops = []
    for item in index:
        ahead = item + int(DROP_SPAN_S)
        if ahead >= ends.size or abs(float(ends[ahead] - ends[item]) - DROP_SPAN_S) > 0.05:
            continue
        if not np.isfinite(values[ahead]):
            continue
        drops.append((float(values[item] - values[ahead]), float(ends[item])))
    if not drops:
        return None
    amount, when = max(drops)
    offset = when - origin
    mark, error, hit = nearest_mark(offset, RETURN_CLOCK_S)
    return {
        "drop": amount,
        "time_s": when,
        "offset_s": offset,
        "nearest_clock_s": mark,
        "clock_error_s": error,
        "on_clock": hit,
    }


def _plot(path: Path, ends: np.ndarray, jumps: np.ndarray, peaks: list[float], breaks: list[dict]) -> None:
    fig, ax = plt.subplots(figsize=(14, 4.2))
    shade(ax, breaks)
    ax.plot(ends / 60.0, jumps, color="#1f4e79", lw=0.6, zorder=2)
    for index, t in enumerate(peaks):
        ax.axvline(t / 60.0, color="#a33b20", lw=0.45, alpha=0.8, zorder=3, label="listed cut" if index == 0 else None)
    ax.set_xlim(0, ANALYSIS_END / 60.0)
    ax.set_xlabel("minutes")
    ax.set_ylabel("10 s embedding jump")
    ax.set_title("Exp004 listed cuts with commercial pods")
    ax.legend(loc="upper right", fontsize=8)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=120)
    plt.close(fig)


def run(jumps_path: Path, peaks_path: Path, output: Path, frozen_path: Path) -> dict:
    if SESSION in HOLDOUTS:
        raise SystemExit(f"refusing sealed holdout {SESSION}")
    frame = pd.read_parquet(jumps_path)
    ends = frame["window_end"].to_numpy(dtype=float)
    jumps = frame["jump"].to_numpy(dtype=float)
    peaks = [float(item) for item in json.loads(peaks_path.read_text(encoding="utf-8"))]
    breaks = commercial_breaks(SESSION)
    frozen = pd.read_parquet(frozen_path)
    frozen_ends = frozen["window_end"].to_numpy(dtype=float)
    frozen_d = frozen["frozen_program_distance"].to_numpy(dtype=float)

    pod_rows = []
    residuals: list[float] = []
    same_pod_gaps: list[float] = []
    for index, brk in enumerate(breaks, start=1):
        start = float(brk["start_seconds"])
        stop = float(brk["end_seconds"])
        duration = stop - start
        complete = stop < ANALYSIS_END - 1.0
        mark, error, hit = nearest_mark(duration, POD_S)
        chosen = [t for t in peaks if start < t <= stop]
        residuals.extend(grid_residual(t - start) for t in chosen)
        same_pod_gaps.extend(float(item) for item in gaps(chosen))
        pod_rows.append(
            {
                "index": index,
                "break_start_s": start,
                "break_end_s": stop,
                "duration_s": duration,
                "complete": complete,
                "nearest_pod_clock_s": mark if complete else None,
                "clock_error_s": error if complete else None,
                "on_clock": hit if complete else None,
                "n_listed_cuts": len(chosen),
                "median_abs_grid_residual_s": None
                if not chosen
                else float(np.median(np.abs([grid_residual(t - start) for t in chosen]))),
            }
        )
    def _pod_index(t: float) -> int | None:
        for index, brk in enumerate(breaks):
            if float(brk["start_seconds"]) < t <= float(brk["end_seconds"]):
                return index
        return None

    outside_gaps: list[float] = []
    for left, right in zip(peaks, peaks[1:]):
        if _pod_index(left) is None and _pod_index(right) is None:
            outside_gaps.append(float(right - left))

    pod_mask = np.zeros(len(ends), dtype=bool)
    for brk in breaks:
        pod_mask |= (ends >= float(brk["start_seconds"])) & (ends <= float(brk["end_seconds"]))
    program_mask = ~pod_mask & np.isfinite(jumps)

    drop_rows = []
    for index, brk in enumerate(breaks, start=1):
        start = float(brk["start_seconds"])
        found = _largest_drop(frozen_ends, frozen_d, start, RETURN_HORIZON_S)
        row = {"index": index, "origin": "break_start", "origin_s": start}
        if found:
            row.update(found)
            row["inside_pod"] = found["time_s"] <= float(brk["end_seconds"])
        drop_rows.append(row)

    program_origins = []
    cursor = 0.0
    for brk in breaks:
        start = float(brk["start_seconds"])
        if start - cursor >= RETURN_HORIZON_S:
            program_origins.append(cursor)
        cursor = float(brk["end_seconds"])
    if ANALYSIS_END - cursor >= RETURN_HORIZON_S:
        program_origins.append(cursor)
    for origin in program_origins:
        found = _largest_drop(frozen_ends, frozen_d, origin, RETURN_HORIZON_S)
        row = {"index": None, "origin": "program", "origin_s": origin}
        if found:
            row.update(found)
            row["inside_pod"] = False
        drop_rows.append(row)

    complete = [row for row in pod_rows if row["complete"]]
    on_clock = [row for row in complete if row["on_clock"]]
    break_drops = [row for row in drop_rows if row["origin"] == "break_start" and row.get("on_clock") is not None]
    program_drops = [row for row in drop_rows if row["origin"] == "program" and row.get("on_clock") is not None]
    summary = {
        "experiment_spec_version": "exp004-v1",
        "session": SESSION,
        "clock_changed": False,
        "peak_rule_changed": False,
        "embeddings_recomputed": False,
        "tolerance_s": TOLERANCE_S,
        "spot_s": list(SPOT_S),
        "pod_s": list(POD_S),
        "return_clock_s": list(RETURN_CLOCK_S),
        "tolerance_note": "Within 3 s of 15/30/60 for cuts, or of 60/90/120/150/180 for a whole pod. The tolerance was not widened after the durations were seen.",
        "n_complete_pods": len(complete),
        "pods_within_3s_of_60_90_120_150_180": len(on_clock),
        "pod_durations_s": [round(row["duration_s"], 1) for row in complete],
        "cuts_inside_one_pod": _gap_report(np.asarray(same_pod_gaps, dtype=float)),
        "cuts_outside_pods": _gap_report(np.asarray(outside_gaps, dtype=float)),
        "gap_note": "A 12 s refractory means many gaps land in the 12–18 s bin. Near-15 is reported separately from near-30 and near-60 so that bin is not read as a 15 s spot clock.",
        "median_abs_15s_residual_inside_pods": None if not residuals else float(np.median(np.abs(residuals))),
        "uniform_15s_residual_median": 3.75,
        "jump_autocorr_inside_pods": {str(lag): autocorr(jumps, lag, pod_mask) for lag in LAGS},
        "jump_autocorr_outside_pods": {str(lag): autocorr(jumps, lag, program_mask) for lag in LAGS},
        "largest_frozen_drop_on_return_clock": {
            "note": "Largest 10 s drop in frozen-program distance during the 180 s after a break start, and the same measurement after a program stretch begins. On-clock means that drop's offset is within 3 s of 60, 90, 120, or 150. This is not an unmute threshold.",
            "breaks_on_clock": sum(1 for row in break_drops if row["on_clock"]),
            "n_breaks": len(break_drops),
            "program_stretches_on_clock": sum(1 for row in program_drops if row["on_clock"]),
            "n_program_stretches": len(program_drops),
            "median_clock_error_after_break_start_s": None
            if not break_drops
            else float(np.median([row["clock_error_s"] for row in break_drops])),
            "median_clock_error_in_program_s": None
            if not program_drops
            else float(np.median([row["clock_error_s"] for row in program_drops])),
        },
        "validation_note": "This ESPN session is development data. A clock result here is not independent confirmation.",
    }
    output.mkdir(parents=True, exist_ok=True)
    _write_csv(output / "overlay_pods.csv", pod_rows)
    _write_csv(output / "overlay_drops.csv", drop_rows)
    (output / "overlay_summary.json").write_text(json.dumps(_clean(summary), indent=2) + "\n", encoding="utf-8")
    _plot(output / "plots_labeled" / "temporal.png", ends, jumps, peaks, breaks)
    print(
        f"pods_on_clock={len(on_clock)}/{len(complete)} "
        f"inside={summary['cuts_inside_one_pod']} "
        f"outside={summary['cuts_outside_pods']}",
        flush=True,
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit a frozen Exp004 listing. Does not refit the clock.")
    default = REPO / "experiments" / "exp004" / SESSION
    parser.add_argument("--jumps", type=Path, default=default / "jumps.parquet")
    parser.add_argument("--peaks", type=Path, default=default / "peaks.json")
    parser.add_argument(
        "--frozen",
        type=Path,
        default=REPO / "experiments" / "exp003b" / SESSION / "frozen_timeline.parquet",
    )
    parser.add_argument("--output", type=Path, default=default)
    args = parser.parse_args()
    run(args.jumps, args.peaks, args.output, args.frozen)


if __name__ == "__main__":
    main()
