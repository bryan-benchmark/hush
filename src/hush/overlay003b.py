"""Ledger audit of a frozen Exp003b run. Does not move the trigger."""

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
from hush.overlay003 import _clean, _distribution, _median, _slice, percentile_rank

REPO = Path(__file__).resolve().parents[2]
SESSION = "hush_20260914_212529"
HOLDOUTS = ("hush_20260917_205513", "hush_20260920_200635")
ANALYSIS_END = 6899.0
# Audit window only. Not part of the freeze rule.
COVER_S = 60.0
RETURN_HORIZON_S = 120.0


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()), lineterminator="\n")
        writer.writeheader()
        writer.writerows([_clean(row) for row in rows])


def _first_latency(ends: np.ndarray, distances: np.ndarray, origin: float, horizon: float, level: float) -> float | None:
    chosen = (ends > origin) & (ends <= origin + horizon) & np.isfinite(distances)
    below = chosen & (distances <= level)
    if not np.any(below):
        return None
    return float(ends[np.flatnonzero(below)[0]] - origin)


def _plot(path: Path, ends: np.ndarray, frozen: np.ndarray, breaks: list[dict], triggers: list[float]) -> None:
    fig, ax = plt.subplots(figsize=(14, 4.2))
    shade(ax, breaks)
    ax.plot(ends / 60.0, frozen, color="#0b6e4f", lw=0.7, zorder=2, label="frozen-program distance")
    for index, t in enumerate(triggers):
        ax.axvline(t / 60.0, color="#a33b20", lw=0.7, zorder=3, label="freeze" if index == 0 else None)
    ax.set_xlim(0, ANALYSIS_END / 60.0)
    ax.set_xlabel("minutes")
    ax.set_ylabel("frozen-program distance")
    ax.set_title("Exp003b frozen-program distance with commercial pods")
    ax.legend(loc="upper right", fontsize=8)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=120)
    plt.close(fig)


def run(timeline_path: Path, freezes_path: Path, output: Path) -> dict:
    if SESSION in HOLDOUTS:
        raise SystemExit(f"refusing sealed holdout {SESSION}")
    frame = pd.read_parquet(timeline_path)
    ends = frame["window_end"].to_numpy(dtype=float)
    frozen = frame["frozen_program_distance"].to_numpy(dtype=float)
    breaks = commercial_breaks(SESSION)
    records = json.loads(freezes_path.read_text(encoding="utf-8"))
    triggers = [float(row["trigger_s"]) for row in records if not row.get("skipped")]
    baselines = {float(row["trigger_s"]): float(row["self_median_distance"]) for row in records if not row.get("skipped")}

    def active_baseline(t: float) -> float | None:
        prior = [trigger for trigger in triggers if trigger <= t]
        if not prior:
            return None
        return baselines[prior[-1]]

    rows = []
    covered = 0
    for index, brk in enumerate(breaks, start=1):
        start = float(brk["start_seconds"])
        stop = float(brk["end_seconds"])
        near = [t for t in triggers if start < t <= start + COVER_S]
        freeze_t = near[0] if near else None
        if freeze_t is not None:
            covered += 1
        baseline = active_baseline(stop)
        row = {
            "index": index,
            "break_start_s": start,
            "break_end_s": stop,
            "freeze_s": freeze_t,
            "freeze_latency_s": None if freeze_t is None else freeze_t - start,
            "pre30_frozen_median": _median(_slice(ends, frozen, start - 30.0, start)),
            "pod_0_20_frozen_median": _median(_slice(ends, frozen, start, min(start + 20.0, stop))),
            "pod_20_40_frozen_median": _median(_slice(ends, frozen, start + 20.0, min(start + 40.0, stop))),
            "late_pod_30_frozen_median": _median(_slice(ends, frozen, max(start, stop - 30.0), stop)),
            "post10_frozen_median": _median(_slice(ends, frozen, stop, stop + 10.0)),
            "post20_frozen_median": _median(_slice(ends, frozen, stop, stop + 20.0)),
            "post30_frozen_median": _median(_slice(ends, frozen, stop, stop + 30.0)),
            "self_baseline": baseline,
            "return_latency_s": None
            if baseline is None
            else _first_latency(ends, frozen, stop, RETURN_HORIZON_S, baseline),
        }
        post = _slice(ends, frozen, stop, stop + 30.0)
        post_min = None if post.size == 0 or not np.any(np.isfinite(post)) else float(np.nanmin(post))
        row["post30_min"] = post_min
        row["post30_min_percentile"] = percentile_rank(post_min, frozen)
        rows.append(row)

    pod = np.zeros(len(ends), dtype=bool)
    for brk in breaks:
        pod |= (ends >= float(brk["start_seconds"])) & (ends <= float(brk["end_seconds"]))
    program = ~pod & np.isfinite(frozen)
    pod_defined = pod & np.isfinite(frozen)
    outside = []
    for t in triggers:
        in_pod = any(float(brk["start_seconds"]) <= t <= float(brk["end_seconds"]) for brk in breaks)
        near_start = any(float(brk["start_seconds"]) < t <= float(brk["start_seconds"]) + COVER_S for brk in breaks)
        if not in_pod and not near_start:
            outside.append(t)
    program_seconds = float(np.sum(~np.array([
        any(float(brk["start_seconds"]) <= s < float(brk["end_seconds"]) for brk in breaks)
        for s in range(int(ANALYSIS_END))
    ])))
    returned = [row for row in rows if row["return_latency_s"] is not None]
    summary = {
        "experiment_spec_version": "exp003b-v1",
        "session": SESSION,
        "trigger_changed": False,
        "embeddings_recomputed": False,
        "cover_window_s": COVER_S,
        "cover_window_note": "A break counts as covered when a freeze falls in (start, start+60 s]. That window is for counting only.",
        "n_breaks": len(breaks),
        "breaks_with_freeze": covered,
        "n_freezes": len(triggers),
        "freezes_outside_pods_and_not_near_a_start": len(outside),
        "false_freezes_per_program_hour": len(outside) / (program_seconds / 3600.0),
        "program_frozen_distribution": _distribution(frozen[program]),
        "pod_frozen_distribution": _distribution(frozen[pod_defined]),
        "returns_reaching_self_baseline_within_120s": len(returned),
        "validation_note": "This ESPN session is development data. The trigger was not fit to these breaks.",
    }
    output.mkdir(parents=True, exist_ok=True)
    _write_csv(output / "overlay_breaks.csv", rows)
    (output / "overlay_summary.json").write_text(json.dumps(_clean(summary), indent=2) + "\n", encoding="utf-8")
    _plot(output / "plots_labeled" / "frozen_program.png", ends, frozen, breaks, triggers)
    print(
        f"breaks_with_freeze={covered}/{len(breaks)} "
        f"outside={len(outside)} per_program_hour={summary['false_freezes_per_program_hour']:.2f} "
        f"returns_to_baseline={len(returned)}",
        flush=True,
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit a frozen Exp003b run. Does not refire the trigger.")
    default = REPO / "experiments" / "exp003b" / SESSION
    parser.add_argument("--timeline", type=Path, default=default / "frozen_timeline.parquet")
    parser.add_argument("--freezes", type=Path, default=default / "freezes.json")
    parser.add_argument("--output", type=Path, default=default)
    args = parser.parse_args()
    run(args.timeline, args.freezes, args.output)


if __name__ == "__main__":
    main()
