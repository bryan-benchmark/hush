"""Truth overlay for frozen Experiment 003.

Reads the program-cloud scores and the truth ledger. Does not recompute
embeddings or change the 10 s window, 1 s hop, or 180 s memory.
"""

from __future__ import annotations

import csv
import json
import math
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
from hush.program_cloud import LISTING_GAP_S, listing_peaks

REPO = Path(__file__).resolve().parents[2]
SESSION = "hush_20260914_212529"
HOLDOUTS = ("hush_20260917_205513", "hush_20260920_200635")
ANALYSIS_END = 6899.0
NEAR_START_S = 30.0


def _num(value):
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (float, np.floating)):
        value = float(value)
        return None if not math.isfinite(value) else round(value, 4)
    if isinstance(value, (int, np.integer)):
        return int(value)
    return value


def _clean(obj):
    if isinstance(obj, dict):
        return {key: _clean(val) for key, val in obj.items()}
    if isinstance(obj, list):
        return [_clean(val) for val in obj]
    return _num(obj)


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _slice(ends: np.ndarray, scores: np.ndarray, start: float, stop: float) -> np.ndarray:
    """Scores whose window ended in (start, stop]. The audio is the preceding 10 s."""
    chosen = (ends > start) & (ends <= stop)
    return scores[chosen]


def _median(values: np.ndarray) -> float | None:
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return None
    return float(np.median(finite))


def _max(values: np.ndarray) -> float | None:
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return None
    return float(np.max(finite))


def percentile_rank(value: float | None, population: np.ndarray) -> float | None:
    """Percent of defined scores that are less than or equal to value."""
    if value is None or not math.isfinite(value):
        return None
    finite = population[np.isfinite(population)]
    if finite.size == 0:
        return None
    return 100.0 * float(np.mean(finite <= value))


def latency_to_max(ends: np.ndarray, scores: np.ndarray, origin: float, horizon: float) -> float | None:
    """Seconds from origin to the highest defined score with window_end in (origin, origin+horizon]."""
    chosen = (ends > origin) & (ends <= origin + horizon) & np.isfinite(scores)
    if not np.any(chosen):
        return None
    idx = np.flatnonzero(chosen)[int(np.nanargmax(scores[chosen]))]
    return float(ends[idx] - origin)


def window_stats(ends: np.ndarray, scores: np.ndarray, start: float, stop: float, population: np.ndarray) -> dict:
    values = _slice(ends, scores, start, stop)
    peak = _max(values)
    return {
        "n": int(np.isfinite(values).sum()),
        "median": _median(values),
        "max": peak,
        "percentile_of_max": percentile_rank(peak, population),
    }


def in_pod(timestamp: float, breaks: list[dict]) -> bool:
    return any(float(row["start_seconds"]) <= timestamp <= float(row["end_seconds"]) for row in breaks)


def near_start(timestamp: float, breaks: list[dict], radius: float = NEAR_START_S) -> bool:
    return any(abs(timestamp - float(row["start_seconds"])) <= radius for row in breaks)


def associated(timestamp: float, breaks: list[dict]) -> bool:
    """Inside a pod, or within 30 s of a commercial start."""
    return in_pod(timestamp, breaks) or near_start(timestamp, breaks)


def _mask_seconds(breaks: list[dict], end: float = ANALYSIS_END) -> tuple[float, float, float]:
    """Associated, pod, and program seconds on a 1 s grid over [0, end)."""
    grid = np.arange(end)
    pod = np.zeros(grid.shape, dtype=bool)
    assoc = np.zeros(grid.shape, dtype=bool)
    for row in breaks:
        start = float(row["start_seconds"])
        stop = min(float(row["end_seconds"]), end)
        pod |= (grid >= start) & (grid < stop)
        assoc |= (grid >= start) & (grid < stop)
        assoc |= np.abs(grid - start) <= NEAR_START_S
    assoc &= grid < end
    pod_s = float(pod.sum())
    assoc_s = float(assoc.sum())
    program_s = float(end - pod_s)
    outside_s = float(end - assoc_s)
    return assoc_s, pod_s, outside_s if outside_s > 0 else program_s


def _boundary_row(ends, scores, population, origin: float, kind: str, index: int, start: float, stop: float) -> dict:
    pre = window_stats(ends, scores, origin - 30.0, origin, population)
    row = {
        "kind": kind,
        "index": index,
        "boundary_s": start if kind == "start" else stop,
        "break_start_s": start,
        "break_end_s": stop,
        "pre30_n": pre["n"],
        "pre30_median": pre["median"],
        "pre30_max": pre["max"],
        "pre30_percentile_of_max": pre["percentile_of_max"],
    }
    for horizon in (10, 20, 30):
        post = window_stats(ends, scores, origin, origin + horizon, population)
        row[f"post{horizon}_n"] = post["n"]
        row[f"post{horizon}_median"] = post["median"]
        row[f"post{horizon}_max"] = post["max"]
        row[f"post{horizon}_percentile_of_max"] = post["percentile_of_max"]
        if post["median"] is not None and pre["median"] is not None:
            row[f"post{horizon}_median_minus_pre30"] = post["median"] - pre["median"]
        else:
            row[f"post{horizon}_median_minus_pre30"] = None
    row["latency_to_max_30s"] = latency_to_max(ends, scores, origin, 30.0)
    if kind == "start":
        for lo, hi, name in ((0, 20, "pod_0_20"), (20, 40, "pod_20_40"), (40, 60, "pod_40_60")):
            stats = window_stats(ends, scores, origin + lo, min(origin + hi, stop), population)
            row[f"{name}_median"] = stats["median"]
            row[f"{name}_n"] = stats["n"]
    return row


def _plot(path: Path, ends: np.ndarray, scores: np.ndarray, breaks: list[dict]) -> None:
    fig, ax = plt.subplots(figsize=(14, 4.2))
    shade(ax, breaks)
    ax.plot(ends / 60.0, scores, color="#1f4e79", lw=0.7, zorder=2, label="distance from recent cloud")
    ax.set_xlim(0, ANALYSIS_END / 60.0)
    ax.set_xlabel("minutes")
    ax.set_ylabel("distance from recent cloud")
    ax.set_title("Exp003 program-cloud distance with commercial pods")
    ax.legend(loc="upper right", fontsize=8)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=120)
    plt.close(fig)


def _plot_distributions(path: Path, pod_scores: np.ndarray, program_scores: np.ndarray) -> None:
    fig, ax = plt.subplots(figsize=(7, 3.6))
    bins = np.linspace(0, max(0.5, float(np.nanmax(np.concatenate([pod_scores, program_scores])))), 40)
    ax.hist(program_scores, bins=bins, density=True, alpha=0.65, color="#1f4e79", label="program")
    ax.hist(pod_scores, bins=bins, density=True, alpha=0.65, color="#c47b2b", label="commercial pod")
    ax.set_xlabel("distance from recent cloud")
    ax.set_ylabel("density")
    ax.set_title("Pod versus program score distributions")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def _distribution(values: np.ndarray) -> dict:
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return {"n": 0}
    return {
        "n": int(finite.size),
        "p10": float(np.percentile(finite, 10)),
        "p50": float(np.percentile(finite, 50)),
        "p90": float(np.percentile(finite, 90)),
        "mean": float(np.mean(finite)),
    }


def run(frame_path: Path, output: Path) -> dict:
    if SESSION in HOLDOUTS:
        raise SystemExit(f"refusing sealed holdout {SESSION}")
    frame = pd.read_parquet(frame_path, columns=["window_start", "window_end", "anomaly"])
    ends = frame["window_end"].to_numpy(dtype=float)
    scores = frame["anomaly"].to_numpy(dtype=float)
    population = scores[np.isfinite(scores)]
    breaks = commercial_breaks(SESSION)
    starts = [_boundary_row(ends, scores, population, float(row["start_seconds"]), "start", i + 1, float(row["start_seconds"]), float(row["end_seconds"])) for i, row in enumerate(breaks)]
    returns = [_boundary_row(ends, scores, population, float(row["end_seconds"]), "end", i + 1, float(row["start_seconds"]), float(row["end_seconds"])) for i, row in enumerate(breaks)]
    peaks = listing_peaks(ends, scores, gap_s=LISTING_GAP_S, k=50)
    events = []
    for rank, peak in enumerate(peaks, start=1):
        t = float(peak["timestamp_seconds"])
        events.append(
            {
                "rank": rank,
                "timestamp_s": t,
                "anomaly": float(peak["anomaly"]),
                "in_pod": in_pod(t, breaks),
                "within_30s_of_start": near_start(t, breaks),
                "associated": associated(t, breaks),
            }
        )
    pod_mask = np.array([in_pod(float(t), breaks) for t in ends]) & np.isfinite(scores)
    assoc_s, pod_s, outside_s = _mask_seconds(breaks)
    def _event_counts(limit: int) -> dict:
        chosen = events[:limit]
        n_assoc = sum(1 for row in chosen if row["associated"])
        n_pod = sum(1 for row in chosen if row["in_pod"])
        n_near = sum(1 for row in chosen if row["within_30s_of_start"])
        n_out = limit - n_assoc
        return {
            "k": limit,
            "inside_pod": n_pod,
            "within_30s_of_start": n_near,
            "associated_pod_or_near_start": n_assoc,
            "outside": n_out,
            "associated_per_hour": n_assoc / (assoc_s / 3600.0),
            "outside_per_hour": n_out / (outside_s / 3600.0),
            "enrichment": (n_assoc / assoc_s) / (n_out / outside_s) if n_out else None,
        }

    higher_median_30 = sum(
        1
        for row in starts
        if row["post30_median_minus_pre30"] is not None and row["post30_median_minus_pre30"] > 0
    )
    summary = {
        "experiment_spec_version": "exp003-v1",
        "session": SESSION,
        "embeddings_recomputed": False,
        "params_changed": False,
        "score_timestamp": "window_end; the scored audio is the preceding 10 s",
        "n_breaks": len(breaks),
        "starts_with_higher_median_in_0_30_than_pre_30": higher_median_30,
        "pod_seconds": pod_s,
        "associated_seconds": assoc_s,
        "outside_associated_seconds": outside_s,
        "pod_distribution": _distribution(scores[pod_mask]),
        "program_distribution": _distribution(scores[~pod_mask & np.isfinite(scores)]),
        "top20": _event_counts(20),
        "top50": _event_counts(50),
        "return_note": "A high score after a pod end means the audio differs from the previous 3 minutes. It is not a PLAY decision.",
    }
    output.mkdir(parents=True, exist_ok=True)
    _write_csv(output / "overlay_starts.csv", [_clean(row) for row in starts])
    _write_csv(output / "overlay_returns.csv", [_clean(row) for row in returns])
    _write_csv(output / "overlay_events.csv", [_clean(row) for row in events])
    (output / "overlay_summary.json").write_text(json.dumps(_clean(summary), indent=2) + "\n", encoding="utf-8")
    _plot(output / "plots_labeled" / "program_distance.png", ends, scores, breaks)
    _plot_distributions(
        output / "plots_labeled" / "pod_vs_program.png",
        scores[pod_mask],
        scores[~pod_mask & np.isfinite(scores)],
    )
    print(
        f"breaks={len(breaks)} higher_median_0_30={higher_median_30} "
        f"top20_associated={summary['top20']['associated_pod_or_near_start']}/20 "
        f"top50_associated={summary['top50']['associated_pod_or_near_start']}/50",
        flush=True,
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Overlay frozen Exp003 scores. Does not rescore.")
    parser.add_argument(
        "--scores",
        type=Path,
        default=REPO / "experiments" / "exp003" / SESSION / "program_cloud.parquet",
    )
    parser.add_argument("--output", type=Path, default=REPO / "experiments" / "exp003" / SESSION)
    args = parser.parse_args()
    run(args.scores, args.output)


if __name__ == "__main__":
    main()
