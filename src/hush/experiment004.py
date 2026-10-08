"""Unlabeled Exp004. Reads frozen Exp003 embeddings and does not open the ledger."""

from __future__ import annotations

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

from hush.program_cloud import EXPERIMENT_SPEC_VERSION as EXP003_SPEC
from hush.temporal import (
    EXPERIMENT_SPEC_VERSION,
    FEATURE_SCHEMA_VERSION,
    PARAMS,
    SPOT_S,
    autocorr,
    exceed_mask,
    gaps,
    jump_score,
    on_spot_clock,
    peak_times,
)

REPO = Path(__file__).resolve().parents[2]
SESSION = "hush_20260914_212529"
HOLDOUTS = ("hush_20260917_205513", "hush_20260920_200635")
SCORES = REPO / "experiments" / "exp003" / SESSION / "program_cloud.parquet"
LAGS = tuple(range(5, 91, 5))


def _plot(path: Path, ends: np.ndarray, jumps: np.ndarray, peaks: list[float], gap: np.ndarray, lags: dict) -> None:
    fig, axes = plt.subplots(3, 1, figsize=(14, 8.2))
    axes[0].plot(ends / 60.0, jumps, color="#1f4e79", lw=0.5)
    for index, t in enumerate(peaks):
        axes[0].axvline(t / 60.0, color="#a33b20", lw=0.4, alpha=0.7, label="listed cut" if index == 0 else None)
    axes[0].set_ylabel("10 s embedding jump")
    axes[0].set_xlim(float(ends[0] / 60.0), float(ends[-1] / 60.0))
    axes[0].legend(loc="upper right", fontsize=8)
    if gap.size:
        bins = np.arange(0.0, 121.0, 1.0)
        axes[1].hist(gap, bins=bins, color="#1f4e79")
    for spot in SPOT_S:
        axes[1].axvline(spot, color="#a33b20", lw=0.8)
    axes[1].set_xlim(0, 120)
    axes[1].set_xlabel("seconds between listed cuts")
    axes[1].set_ylabel("gaps")
    lag_x = np.array(sorted(lags), dtype=float)
    axes[2].plot(lag_x, [lags[int(item)] for item in lag_x], color="#1f4e79", marker="o", ms=3)
    for spot in SPOT_S:
        axes[2].axvline(spot, color="#a33b20", lw=0.8)
    axes[2].set_xlabel("lag (seconds)")
    axes[2].set_ylabel("autocorr")
    axes[0].set_title("Exp004 unlabeled. Red lines are a listing, not commercial pods.")
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=120)
    plt.close(fig)


def run(scores_path: Path, output: Path) -> dict:
    if SESSION in HOLDOUTS or any(token in str(scores_path) for token in HOLDOUTS):
        raise SystemExit(f"refusing sealed holdout {SESSION}")
    frame = pd.read_parquet(scores_path, columns=["window_end", "embedding"])
    ends = frame["window_end"].to_numpy(dtype=np.float64)
    embeddings = np.vstack([np.asarray(row, dtype=np.float64) for row in frame["embedding"]])
    jumps = jump_score(ends, embeddings)
    hits = exceed_mask(ends, jumps)
    peaks = peak_times(ends, jumps, hits)
    gap = gaps(peaks)
    clock = np.array([on_spot_clock(float(item)) for item in gap]) if gap.size else np.array([], dtype=bool)
    lag_values = {lag: autocorr(jumps, lag) for lag in LAGS}
    defined = jumps[np.isfinite(jumps)]
    summary = {
        "experiment_spec_version": EXPERIMENT_SPEC_VERSION,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "reads_exp003_spec": EXP003_SPEC,
        "session_id": SESSION,
        "embeddings_recomputed": False,
        "truth_ledger_read": False,
        "n_jumps": int(defined.size),
        "jump_p50": float(np.median(defined)),
        "n_peaks": len(peaks),
        "n_gaps": int(gap.size),
        "gaps_on_15_30_60_within_3s": int(clock.sum()) if clock.size else 0,
        "gap_clock_fraction": None if clock.size == 0 else float(clock.mean()),
        "autocorr": {str(lag): lag_values[lag] for lag in LAGS},
        "params": PARAMS,
        "validation_note": "This ESPN session is development data. The clock was not fit to its commercial pods.",
    }
    output.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"window_end": ends, "jump": jumps, "hit": hits}).to_parquet(output / "jumps.parquet", index=False)
    (output / "peaks.json").write_text(json.dumps(peaks) + "\n", encoding="utf-8")
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    _plot(output / "temporal.png", ends, jumps, peaks, gap, lag_values)
    print(
        f"peaks={len(peaks)} gaps_on_clock={summary['gaps_on_15_30_60_within_3s']}/{gap.size} "
        f"fraction={summary['gap_clock_fraction']}",
        flush=True,
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Unlabeled Exp004 commercial-clock structure.")
    parser.add_argument("--scores", type=Path, default=SCORES)
    parser.add_argument("--output", type=Path, default=REPO / "experiments" / "exp004" / SESSION)
    args = parser.parse_args()
    run(args.scores, args.output)


if __name__ == "__main__":
    main()
