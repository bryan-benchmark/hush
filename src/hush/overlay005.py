"""Ledger audit of a frozen Exp005 run. Does not move phrases, the matcher, or the semantic window."""

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
from hush.overlay003 import _median, _slice
from hush.semantic_text import MEMORY_S, MIN_REFERENCE_S

REPO = Path(__file__).resolve().parents[2]
SESSION = "hush_20260914_212529"
HOLDOUTS = ("hush_20260917_205513", "hush_20260920_200635")
ANALYSIS_END = 6899.0
# Audit collars only. Not part of the matcher.
DEPARTURE_BEFORE_S = 10.0
DEPARTURE_AFTER_S = 15.0
RETURN_BEFORE_S = 5.0
RETURN_AFTER_S = 15.0
PREBREAK_EXCLUDE_S = 30.0
PREBREAK_SPAN_S = 180.0
RETURN_HORIZON_S = 120.0


def _clean(value):
    if isinstance(value, dict):
        return {key: _clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(item) for item in value]
    if isinstance(value, (np.floating, float)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    return value


def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
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


def _in_pod(t: float, breaks: list[dict]) -> bool:
    return any(float(brk["start_seconds"]) <= t <= float(brk["end_seconds"]) for brk in breaks)


def _program_seconds(breaks: list[dict]) -> float:
    covered = np.zeros(int(ANALYSIS_END), dtype=bool)
    for brk in breaks:
        start = max(0, int(np.floor(float(brk["start_seconds"]))))
        stop = min(int(ANALYSIS_END), int(np.ceil(float(brk["end_seconds"]))))
        covered[start:stop] = True
    return float(np.sum(~covered))


def _first_latency(ends: np.ndarray, distances: np.ndarray, origin: float, level: float) -> float | None:
    chosen = (ends > origin) & (ends <= origin + RETURN_HORIZON_S) & np.isfinite(distances) & (distances <= level)
    if not np.any(chosen):
        return None
    return float(ends[np.flatnonzero(chosen)[0]] - origin)


def _plot(path: Path, ends: np.ndarray, semantic: np.ndarray, breaks: list[dict], cues: list[dict]) -> None:
    fig, ax = plt.subplots(figsize=(14, 4.2))
    shade(ax, breaks)
    ax.plot(ends / 60.0, semantic, color="#0b6e4f", lw=0.7, zorder=2, label="semantic distance")
    labeled = {"departure": False, "return": False}
    for cue in cues:
        kind = cue["kind"]
        color = "#a33b20" if kind == "departure" else "#1f4e79"
        ax.axvline(
            float(cue["start"]) / 60.0,
            color=color,
            lw=0.6,
            zorder=3,
            label=f"{kind} phrase" if not labeled[kind] else None,
        )
        labeled[kind] = True
    ax.set_xlim(0, ANALYSIS_END / 60.0)
    ax.set_xlabel("minutes")
    ax.set_ylabel("semantic distance")
    ax.set_title("Exp005 semantic distance with commercial pods")
    ax.legend(loc="upper right", fontsize=8)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=120)
    plt.close(fig)


def run(output: Path) -> dict:
    if SESSION in HOLDOUTS:
        raise SystemExit(f"refusing sealed holdout {SESSION}")
    cues = json.loads((output / "cues.json").read_text(encoding="utf-8"))
    vocabulary = json.loads((output / "vocabulary_hits.json").read_text(encoding="utf-8"))
    semantic = pd.read_parquet(output / "semantic.parquet")
    ends = semantic["window_end"].to_numpy(dtype=float)
    scores = semantic["semantic_distance"].to_numpy(dtype=float)
    breaks = commercial_breaks(SESSION)
    program_hours = _program_seconds(breaks) / 3600.0

    def departure_near(start: float, t: float) -> bool:
        return start - DEPARTURE_BEFORE_S < t <= start + DEPARTURE_AFTER_S

    def return_near(stop: float, t: float) -> bool:
        return stop - RETURN_BEFORE_S < t <= stop + RETURN_AFTER_S

    rows = []
    for index, brk in enumerate(breaks, start=1):
        start = float(brk["start_seconds"])
        stop = float(brk["end_seconds"])
        dep = [cue for cue in cues if cue["kind"] == "departure" and departure_near(start, float(cue["start"]))]
        ret = [cue for cue in cues if cue["kind"] == "return" and return_near(stop, float(cue["start"]))]
        rows.append(
            {
                "index": index,
                "break_start_s": start,
                "break_end_s": stop,
                "departure_cues": len(dep),
                "departure_latency_s": None if not dep else float(dep[0]["start"]) - start,
                "return_cues": len(ret),
                "return_latency_s": None if not ret else float(ret[0]["start"]) - stop,
                "pre30_semantic_median": _median(_slice(ends, scores, start - 30.0, start)),
                "post30_semantic_median": _median(_slice(ends, scores, start, start + 30.0)),
                "late_pod_semantic_median": _median(_slice(ends, scores, max(start, stop - 30.0), stop)),
                "return10_semantic_median": _median(_slice(ends, scores, stop, stop + 10.0)),
                "return20_semantic_median": _median(_slice(ends, scores, stop, stop + 20.0)),
                "return30_semantic_median": _median(_slice(ends, scores, stop, stop + 30.0)),
            }
        )

    # Pre-break language cloud, using the embeddings frozen in the unlabeled run.
    # The snapshot is the mean of windows whose ends fall in (S-210, S-30].
    # Choosing S from the ledger is this audit. It is not a detector and it does not read Exp003b.
    embeddings = np.load(output / "semantic_embeddings.npy").astype(np.float64)
    present = semantic["n_words"].to_numpy(dtype=int) >= 8
    frozen_rows = []
    recovered = 0
    for index, brk in enumerate(breaks, start=1):
        start = float(brk["start_seconds"])
        stop = float(brk["end_seconds"])
        ref_stop = start - PREBREAK_EXCLUDE_S
        ref_start = ref_stop - PREBREAK_SPAN_S
        chosen = present & (ends > ref_start) & (ends <= ref_stop)
        row = {"index": index, "n_reference_windows": int(chosen.sum())}
        if int(chosen.sum()) < 2:
            row["skipped"] = True
            frozen_rows.append(row)
            continue
        centroid = embeddings[chosen].mean(axis=0)
        norm = np.linalg.norm(centroid)
        unit = centroid / norm
        distances = np.full(len(ends), np.nan)
        distances[present] = 1.0 - embeddings[present] @ unit
        level = _median(distances[chosen])
        row.update(
            {
                "skipped": False,
                "program_level": level,
                "pod_frozen_median": _median(_slice(ends, distances, start, stop)),
                "return30_frozen_median": _median(_slice(ends, distances, stop, stop + 30.0)),
                "return_latency_s": None if level is None else _first_latency(ends, distances, stop, level),
            }
        )
        if row["return_latency_s"] is not None:
            recovered += 1
        frozen_rows.append(row)
        for table_row in rows:
            if table_row["index"] == index:
                table_row["frozen_pod_median"] = row["pod_frozen_median"]
                table_row["frozen_return30_median"] = row["return30_frozen_median"]
                table_row["frozen_return_latency_s"] = row["return_latency_s"]

    def cue_bucket(cue: dict) -> str:
        t = float(cue["start"])
        if cue["kind"] == "departure" and any(departure_near(float(brk["start_seconds"]), t) for brk in breaks):
            return "near_start"
        if cue["kind"] == "return" and any(return_near(float(brk["end_seconds"]), t) for brk in breaks):
            return "near_end"
        if _in_pod(t, breaks):
            return "inside_pod"
        return "program"

    buckets = {"departure": {}, "return": {}}
    for cue in cues:
        kind = cue["kind"]
        bucket = cue_bucket(cue)
        buckets[kind][bucket] = buckets[kind].get(bucket, 0) + 1
    vocab_times = np.array([float(row["start"]) for row in vocabulary], dtype=float)
    pod_mask = np.zeros(vocab_times.shape, dtype=bool)
    for brk in breaks:
        pod_mask |= (vocab_times >= float(brk["start_seconds"])) & (vocab_times <= float(brk["end_seconds"]))
    pod_seconds = ANALYSIS_END - _program_seconds(breaks)
    in_pod_scores = np.zeros(len(ends), dtype=bool)
    for brk in breaks:
        in_pod_scores |= (ends >= float(brk["start_seconds"])) & (ends <= float(brk["end_seconds"]))
    summary = {
        "experiment_spec_version": "exp005-v1",
        "session": SESSION,
        "phrases_changed": False,
        "matcher_changed": False,
        "semantic_window_changed": False,
        "asr_rerun": False,
        "asr_is_closed_captions": False,
        "collar_note": "A departure cue counts for a start in (start-10 s, start+15 s]. A return cue counts for an end in (end-5 s, end+15 s]. Those collars are for counting only.",
        "prebreak_note": f"The pre-break cloud is the mean of semantic windows whose ends fall in (S-{PREBREAK_EXCLUDE_S + PREBREAK_SPAN_S:.0f} s, S-{PREBREAK_EXCLUDE_S:.0f} s]. It is built from the labeled start during this audit. It is not a detector and it does not read Exp003b.",
        "n_breaks": len(breaks),
        "starts_with_departure_language": sum(1 for row in rows if row["departure_cues"]),
        "ends_with_return_language": sum(1 for row in rows if row["return_cues"]),
        "cue_buckets": buckets,
        "false_departure_per_program_hour": buckets["departure"].get("program", 0) / program_hours,
        "false_return_per_program_hour": buckets["return"].get("program", 0) / program_hours,
        "vocabulary_hits_in_pods": int(pod_mask.sum()),
        "vocabulary_hits_outside_pods": int((~pod_mask).sum()),
        "vocabulary_per_pod_minute": float(pod_mask.sum()) / (pod_seconds / 60.0),
        "vocabulary_per_program_minute": float((~pod_mask).sum()) / (_program_seconds(breaks) / 60.0),
        "semantic_pod_median": _median(scores[in_pod_scores]),
        "semantic_program_median": _median(scores[~in_pod_scores & np.isfinite(scores)]),
        "returns_reaching_prebreak_level_within_120s": recovered,
        "semantic_memory_s": MEMORY_S,
        "semantic_min_reference_s": MIN_REFERENCE_S,
        "validation_note": "This ESPN session is development data. The phrases and the matcher were not changed after these counts.",
    }
    output.mkdir(parents=True, exist_ok=True)
    _write_csv(output / "overlay_breaks.csv", rows)
    _write_csv(output / "overlay_frozen_language.csv", frozen_rows)
    (output / "overlay_summary.json").write_text(json.dumps(_clean(summary), indent=2) + "\n", encoding="utf-8")
    _plot(output / "plots_labeled" / "semantic.png", ends, scores, breaks, cues)
    print(
        f"departure_starts={summary['starts_with_departure_language']}/{len(breaks)} "
        f"return_ends={summary['ends_with_return_language']}/{len(breaks)} "
        f"vocab_per_min pod={summary['vocabulary_per_pod_minute']:.3f} "
        f"program={summary['vocabulary_per_program_minute']:.3f}",
        flush=True,
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit a frozen Exp005 run. Does not refit the phrases.")
    parser.add_argument("--output", type=Path, default=REPO / "experiments" / "exp005" / SESSION)
    args = parser.parse_args()
    run(args.output)


if __name__ == "__main__":
    main()
