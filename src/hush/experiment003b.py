"""Unlabeled Exp003b. Reads frozen Exp003 embeddings and does not open the ledger."""

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

from hush.frozen_identity import (
    EXPERIMENT_SPEC_VERSION,
    FEATURE_SCHEMA_VERSION,
    PARAMS,
    cloud_distance,
    exceed_mask,
    freeze_times,
    reference_bounds,
    reference_mask,
)
from hush.program_cloud import EXPERIMENT_SPEC_VERSION as EXP003_SPEC

REPO = Path(__file__).resolve().parents[2]
SESSION = "hush_20260914_212529"
HOLDOUTS = ("hush_20260917_205513", "hush_20260920_200635")
SCORES = REPO / "experiments" / "exp003" / SESSION / "program_cloud.parquet"


def _plot(path: Path, ends: np.ndarray, adaptive: np.ndarray, frozen: np.ndarray, triggers: list[float]) -> None:
    fig, axes = plt.subplots(2, 1, figsize=(14, 6.2), sharex=True)
    minutes = ends / 60.0
    axes[0].plot(minutes, adaptive, color="#1f4e79", lw=0.6)
    axes[0].set_ylabel("adaptive distance")
    axes[1].plot(minutes, frozen, color="#0b6e4f", lw=0.6)
    axes[1].set_ylabel("frozen-program distance")
    axes[1].set_xlabel("minutes")
    for ax in axes:
        for t in triggers:
            ax.axvline(t / 60.0, color="#a33b20", lw=0.7, alpha=0.8)
        ax.set_xlim(float(minutes[0]), float(minutes[-1]))
    axes[0].set_title("Exp003b unlabeled. Red lines are freezes. No commercial shading.")
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=120)
    plt.close(fig)


def run(scores_path: Path, output: Path) -> dict:
    if SESSION in HOLDOUTS or any(token in str(scores_path) for token in HOLDOUTS):
        raise SystemExit(f"refusing sealed holdout {SESSION}")
    if scores_path.parent.name != SESSION:
        raise SystemExit(f"scores directory {scores_path.parent.name} != session {SESSION}")
    frame = pd.read_parquet(scores_path, columns=["window_end", "anomaly", "embedding"])
    ends = frame["window_end"].to_numpy(dtype=np.float64)
    adaptive = frame["anomaly"].to_numpy(dtype=np.float64)
    embeddings = np.vstack([np.asarray(row, dtype=np.float64) for row in frame["embedding"]])
    hits = exceed_mask(ends, adaptive)
    triggers = freeze_times(ends, hits)
    frozen = np.full(len(ends), np.nan)
    records = []
    edges = triggers[1:] + [float(ends[-1]) + 1.0]
    for trigger, nxt in zip(triggers, edges):
        chosen = reference_mask(ends, trigger)
        if not np.any(chosen):
            records.append({"trigger_s": trigger, "n_reference": 0, "skipped": True})
            continue
        start, stop = reference_bounds(trigger)
        distances, baseline = cloud_distance(embeddings[ends >= trigger], embeddings[chosen])
        # distances align with rows whose end >= trigger; assign only until the next freeze
        target = np.flatnonzero(ends >= trigger)
        keep = target[ends[target] < nxt]
        # cloud_distance was computed for all ends >= trigger, so slice the prefix
        frozen[keep] = distances[: keep.size]
        records.append(
            {
                "trigger_s": trigger,
                "reference_after_s": start,
                "reference_through_s": stop,
                "n_reference": int(chosen.sum()),
                "reference_span_s": float(ends[chosen][-1] - ends[chosen][0]),
                "self_median_distance": baseline,
                "skipped": False,
            }
        )
    defined = frozen[np.isfinite(frozen)]
    summary = {
        "experiment_spec_version": EXPERIMENT_SPEC_VERSION,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "reads_exp003_spec": EXP003_SPEC,
        "session_id": SESSION,
        "embeddings_recomputed": False,
        "exp003_scores_recomputed": False,
        "truth_ledger_read": False,
        "n_freezes": len(triggers),
        "freeze_times_s": triggers,
        "n_frozen_distance": int(defined.size),
        "frozen_distance_p50": None if defined.size == 0 else float(np.median(defined)),
        "params": PARAMS,
        "validation_note": (
            "This ESPN session is development data. A result here is not independent confirmation."
            if SESSION == "hush_20260914_212529"
            else "Unlabeled. The commercial ledger was not read."
        ),
    }
    output.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "window_end": ends,
            "adaptive_distance": adaptive,
            "hit": hits,
            "frozen_program_distance": frozen,
        }
    ).to_parquet(output / "frozen_timeline.parquet", index=False)
    (output / "freezes.json").write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    _plot(output / "frozen_program.png", ends, adaptive, frozen, triggers)
    print(f"freezes={len(triggers)} frozen_scores={defined.size}", flush=True)
    return summary


def main() -> None:
    global SESSION
    parser = argparse.ArgumentParser(description="Unlabeled Exp003b freeze of the pre-departure cloud.")
    parser.add_argument("--session", default=SESSION)
    parser.add_argument("--scores", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    SESSION = args.session
    scores = args.scores if args.scores is not None else REPO / "experiments" / "exp003" / SESSION / "program_cloud.parquet"
    output = args.output if args.output is not None else REPO / "experiments" / "exp003b" / SESSION
    run(scores, output)


if __name__ == "__main__":
    main()
