"""Frozen-return replication on one NBC game, plus the RedZone negative control.

Reads the frozen Exp003 embeddings and the frozen Exp003b timeline. Does not
re-embed, does not refire the trigger, and does not write into experiments/exp003
or experiments/exp003b.

Gold is used in two places only: to place the oracle snapshot at a known
commercial start, and to score both series. The causal snapshot is the one
already stored. No distance threshold is chosen here.

The stop rule is fixed before the NBC table is read back:

- A full oracle snapshot has a reference span of at least 60 s, the Exp003
  minimum, and its reference window does not overlap an earlier commercial.
- A break is separated when the median oracle distance in the last 30 s of the
  commercial is above that snapshot's own median self-distance and above the
  median in the first 30 s after the true end.
- Oracle fails if separated breaks are not a majority of the full snapshots,
  or if a majority of the separated breaks also fall back to the self-distance
  while the commercial is still playing.
- Causal acquisition is a published freeze in (start, start+60 s] whose
  reference ends at or before the commercial start and does not overlap a
  commercial. Causal fails the availability bar when that is not a majority
  of the 21 breaks.
- Oracle failure stops this line. Oracle success with causal failure points
  at snapshot selection. Both succeeding only authorizes a later experiment.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from experiments.ledger import TRUTH_PATH, read_jsonl, resolve_ledger
from hush.frozen_identity import cloud_distance, freeze_times, reference_bounds, reference_mask
from hush.overlay002 import drop_series, time_ordered_events
from hush.overlay003 import _median, _slice
from hush.program_cloud import MIN_REFERENCE_S
from hush.speaker_memory import DROP_MIN

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "docs/ohush/research/FROZEN_RETURN_REPLICATION_001"
NBC = "hush_20260913_210542"
REDZONE = "hush_20260913_150934"
HOLDOUTS = ("hush_20260917_205513", "hush_20260920_200635")
NBC_COVERAGE = (0.0, 12600.0)
REDZONE_COVERAGE = (0.0, 7200.0)
COVER_S = 60.0
RETURN_HORIZON_S = 120.0
ESPN_FALSE_FREEZES_PER_PROGRAM_HOUR = 1.4132


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def active_marks() -> list[dict]:
    rows = resolve_ledger(read_jsonl(TRUTH_PATH), "gold_id")
    kept = []
    for row in rows:
        if row.get("retracted") or row.get("event") == "retracted":
            continue
        if "start_seconds" not in row:
            continue
        if row.get("session") in HOLDOUTS:
            raise SystemExit("refusing a sealed holdout")
        kept.append(row)
    return kept


def commercials(rows: list[dict], session: str, coverage: tuple[float, float]) -> list[dict]:
    c0, c1 = coverage
    chosen = []
    for row in rows:
        if row.get("session") != session:
            continue
        if row.get("event_class") != "commercial" or row.get("desired_action") != "mute":
            continue
        if row.get("confidence") == "unsure":
            continue
        start, end = float(row["start_seconds"]), float(row["end_seconds"])
        if start < c0 or end > c1:
            raise SystemExit(f"{session} commercial leaves coverage: {start} {end}")
        chosen.append(row)
    chosen.sort(key=lambda row: float(row["start_seconds"]))
    return chosen


def round_or_none(value: float | None, places: int = 4) -> float | None:
    if value is None or not np.isfinite(value):
        return None
    return round(float(value), places)


def overlaps(a0: float, a1: float, b0: float, b1: float) -> bool:
    return a0 < b1 - 1e-9 and b0 < a1 - 1e-9


def window_count_at_or_below(ends: np.ndarray, values: np.ndarray, start: float, stop: float, level: float) -> int:
    chosen = (ends > start) & (ends <= stop) & np.isfinite(values)
    return int(np.count_nonzero(chosen & (values <= level)))


def window_count(ends: np.ndarray, start: float, stop: float) -> int:
    return int(np.count_nonzero((ends > start) & (ends <= stop)))


def first_latency(ends: np.ndarray, values: np.ndarray, origin: float, horizon: float, level: float) -> float | None:
    chosen = np.flatnonzero((ends > origin) & (ends <= origin + horizon) & np.isfinite(values) & (values <= level))
    if chosen.size == 0:
        return None
    return float(ends[chosen[0]] - origin)


def persistence(ends: np.ndarray, values: np.ndarray, hit: float, level: float) -> float | None:
    chosen = (ends > hit) & (ends <= hit + 30.0) & np.isfinite(values)
    if not np.any(chosen):
        return None
    return float(np.mean(values[chosen] <= level))


def premature(ends: np.ndarray, values: np.ndarray, start: float, stop: float, level: float) -> bool:
    """True when the distance leaves the self-line and then comes back before the true end."""
    chosen = np.flatnonzero((ends > start) & (ends <= stop) & np.isfinite(values))
    seen_above = False
    for index in chosen:
        if values[index] > level:
            seen_above = True
        elif seen_above and values[index] <= level:
            return True
    return False


def load_cloud(session: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    frame = pd.read_parquet(REPO / "experiments/exp003" / session / "program_cloud.parquet")
    ends = frame["window_end"].to_numpy(dtype=np.float64)
    adaptive = frame["anomaly"].to_numpy(dtype=np.float64)
    embeddings = np.vstack([np.asarray(row, dtype=np.float64) for row in frame["embedding"]])
    return ends, adaptive, embeddings


def oracle_for_break(
    ends: np.ndarray,
    embeddings: np.ndarray,
    start: float,
    stop: float,
    nxt: float,
    breaks: list[tuple[float, float]],
) -> dict:
    chosen = reference_mask(ends, start)
    ref_lo, ref_hi = reference_bounds(start)
    contaminated = any(overlaps(ref_lo, ref_hi, b0, b1) for b0, b1 in breaks)
    if not np.any(chosen):
        return {
            "available": False,
            "n_reference": 0,
            "reference_span_s": None,
            "reference_after_s": ref_lo,
            "reference_through_s": ref_hi,
            "contaminated": contaminated,
            "self_median": None,
            "distances": None,
        }
    span = float(ends[chosen][-1] - ends[chosen][0])
    target = np.flatnonzero((ends > ref_hi) & (ends <= nxt))
    distances = np.full(len(ends), np.nan)
    series, baseline = cloud_distance(embeddings[target], embeddings[chosen])
    distances[target] = series
    return {
        "available": True,
        "n_reference": int(chosen.sum()),
        "reference_span_s": span,
        "reference_after_s": ref_lo,
        "reference_through_s": ref_hi,
        "contaminated": contaminated,
        "self_median": baseline,
        "distances": distances,
        "full": span + 1e-9 >= MIN_REFERENCE_S and not contaminated,
        "pod_end": stop,
    }


def break_row(
    index: int,
    row: dict,
    nxt: float,
    ends: np.ndarray,
    adaptive: np.ndarray,
    oracle: dict,
    causal_distance: np.ndarray,
    causal: dict | None,
) -> dict:
    start = float(row["start_seconds"])
    stop = float(row["end_seconds"])
    feature_end = float(ends[-1])
    truncated = stop > feature_end + 1e-9 or start > feature_end + 1e-9
    self_median = oracle.get("self_median")
    distances = oracle.get("distances")
    late = _median(_slice(ends, distances, max(start, stop - 30.0), min(stop, feature_end))) if distances is not None else None
    post = _median(_slice(ends, distances, stop, min(stop + 30.0, feature_end))) if distances is not None else None
    pre = _median(_slice(ends, distances, start - 30.0, start)) if distances is not None else None
    pod = _median(_slice(ends, distances, start, min(stop, feature_end))) if distances is not None else None
    adaptive_late = _median(_slice(ends, adaptive, max(start, stop - 30.0), min(stop, feature_end)))
    adaptive_post = _median(_slice(ends, adaptive, stop, min(stop + 30.0, feature_end)))
    adaptive_pre = _median(_slice(ends, adaptive, start - 30.0, start))
    adaptive_pod = _median(_slice(ends, adaptive, start, min(stop, feature_end)))
    full = bool(oracle.get("full")) and not truncated and late is not None and post is not None and self_median is not None
    separated = bool(full and late > self_median and late > post)
    came_back = bool(
        full and distances is not None and self_median is not None and premature(ends, distances, start, min(stop, feature_end), self_median)
    )
    latency = None
    held = None
    if full and distances is not None and self_median is not None and late > self_median:
        latency = first_latency(ends, distances, stop, RETURN_HORIZON_S, self_median)
        if latency is not None:
            held = persistence(ends, distances, stop + latency, self_median)
    pod_windows = window_count(ends, start, min(stop, feature_end))
    below = 0 if distances is None or self_median is None else window_count_at_or_below(ends, distances, start, min(stop, feature_end), self_median)
    causal_latency = None
    causal_separated = False
    causal_premature = False
    causal_return = None
    causal_held = None
    if causal is not None and np.isfinite(causal["self_median"]):
        level = float(causal["self_median"])
        causal_late = _median(_slice(ends, causal_distance, max(start, stop - 30.0), min(stop, feature_end)))
        causal_post = _median(_slice(ends, causal_distance, stop, min(stop + 30.0, feature_end)))
        causal_separated = causal_late is not None and causal_post is not None and causal_late > level and causal_late > causal_post
        causal_premature = premature(ends, causal_distance, start, min(stop, feature_end), level)
        if causal_late is not None and causal_late > level:
            causal_return = first_latency(ends, causal_distance, stop, RETURN_HORIZON_S, level)
            if causal_return is not None:
                causal_held = persistence(ends, causal_distance, stop + causal_return, level)
        causal_latency = None if causal["trigger_s"] is None else float(causal["trigger_s"]) - start
    if not oracle.get("available"):
        failure = "oracle_unavailable"
    elif truncated:
        failure = "features_end_before_break"
    elif oracle.get("contaminated"):
        failure = "oracle_contaminated_by_earlier_commercial"
    elif oracle.get("reference_span_s") is None or oracle["reference_span_s"] + 1e-9 < MIN_REFERENCE_S:
        failure = "oracle_reference_shorter_than_60s"
    elif late is None or self_median is None or late <= self_median:
        failure = "oracle_does_not_see_the_break"
    elif post is None or late <= post:
        failure = "return_window_not_closer_than_the_pod"
    elif came_back:
        failure = "premature_return_during_ads"
    elif latency is None:
        failure = "no_return_within_120s"
    else:
        failure = "returned"
    return {
        "index": index,
        "gold_id": row.get("gold_id"),
        "start_s": round(start, 3),
        "end_s": round(stop, 3),
        "duration_s": round(stop - start, 3),
        "next_start_s": round(nxt, 3),
        "feature_truncated": truncated,
        "oracle_n_reference": oracle.get("n_reference"),
        "oracle_reference_span_s": round_or_none(oracle.get("reference_span_s"), 3),
        "oracle_reference_after_s": round_or_none(oracle.get("reference_after_s"), 3),
        "oracle_reference_through_s": round_or_none(oracle.get("reference_through_s"), 3),
        "oracle_contaminated": bool(oracle.get("contaminated")),
        "oracle_full": full,
        "oracle_self_median": round_or_none(self_median),
        "oracle_pre30_median": round_or_none(pre),
        "oracle_pod_median": round_or_none(pod),
        "oracle_late30_median": round_or_none(late),
        "oracle_post30_median": round_or_none(post),
        "oracle_separated": separated,
        "oracle_premature_return": came_back,
        "oracle_pod_windows": pod_windows,
        "oracle_pod_windows_at_or_below_self": below,
        "oracle_return_latency_s": round_or_none(latency, 3),
        "oracle_return_persists_30s": round_or_none(held, 3),
        "adaptive_pre30_median": round_or_none(adaptive_pre),
        "adaptive_pod_median": round_or_none(adaptive_pod),
        "adaptive_late30_median": round_or_none(adaptive_late),
        "adaptive_post30_median": round_or_none(adaptive_post),
        "adaptive_late_above_post": bool(
            adaptive_late is not None and adaptive_post is not None and adaptive_late > adaptive_post
        ),
        "causal_trigger_s": None if causal is None else causal["trigger_s"],
        "causal_freeze_latency_s": round_or_none(causal_latency, 3),
        "causal_reference_through_s": None if causal is None else causal["reference_through_s"],
        "causal_reference_ends_before_break": False if causal is None else bool(causal["ends_before_break"]),
        "causal_contaminated": False if causal is None else bool(causal["contaminated"]),
        "causal_clean": False if causal is None else bool(causal["clean"]),
        "causal_self_median": None if causal is None else round_or_none(causal["self_median"]),
        "causal_separated": causal_separated,
        "causal_premature_return": causal_premature,
        "causal_return_latency_s": round_or_none(causal_return, 3),
        "causal_return_persists_30s": round_or_none(causal_held, 3),
        "failure": failure,
    }


def causal_for_break(
    start: float,
    records: list[dict],
    breaks: list[tuple[float, float]],
) -> dict | None:
    near = [row for row in records if start < float(row["trigger_s"]) <= start + COVER_S and not row.get("skipped")]
    if not near:
        return None
    row = near[0]
    trigger = float(row["trigger_s"])
    ref_lo, ref_hi = reference_bounds(trigger)
    contaminated = any(overlaps(ref_lo, ref_hi, b0, b1) for b0, b1 in breaks)
    ends_before = ref_hi <= start + 1e-9
    return {
        "trigger_s": trigger,
        "reference_through_s": round(ref_hi, 3),
        "ends_before_break": ends_before,
        "contaminated": contaminated,
        "clean": ends_before and not contaminated,
        "self_median": float(row["self_median_distance"]),
    }


def pooled_gap(rows: list[dict], ends: np.ndarray, primary: np.ndarray, other: np.ndarray) -> dict:
    """Median distance inside commercials minus median distance in the 120 s after them."""
    pod = np.zeros(len(ends), dtype=bool)
    after = np.zeros(len(ends), dtype=bool)
    for row in rows:
        start, stop = float(row["start_s"]), float(row["end_s"])
        pod |= (ends > start) & (ends <= stop)
        after |= (ends > stop) & (ends <= stop + RETURN_HORIZON_S)
    def median(mask: np.ndarray, values: np.ndarray) -> float | None:
        chosen = values[mask & np.isfinite(values)]
        if chosen.size == 0:
            return None
        return float(np.median(chosen))
    oracle_pod = median(pod, primary)
    oracle_after = median(after, primary)
    adaptive_pod = median(pod, other)
    adaptive_after = median(after, other)
    oracle_gap = None if oracle_pod is None or oracle_after is None else oracle_pod - oracle_after
    adaptive_gap = None if adaptive_pod is None or adaptive_after is None else adaptive_pod - adaptive_after
    return {
        "oracle_commercial_median": round_or_none(oracle_pod),
        "oracle_return_120s_median": round_or_none(oracle_after),
        "oracle_gap": round_or_none(oracle_gap),
        "adaptive_commercial_median": round_or_none(adaptive_pod),
        "adaptive_return_120s_median": round_or_none(adaptive_after),
        "adaptive_gap": round_or_none(adaptive_gap),
        "oracle_gap_larger": bool(
            oracle_gap is not None and adaptive_gap is not None and oracle_gap > adaptive_gap and oracle_gap > 0
        ),
    }


def verdict(rows: list[dict], gap: dict) -> dict:
    eligible = [row for row in rows if row["oracle_full"]]
    separated = [row for row in eligible if row["oracle_separated"]]
    premature_rows = [row for row in separated if row["oracle_premature_return"]]
    causal_clean = [row for row in rows if row["causal_clean"]]
    oracle_majority = len(separated) * 2 > len(eligible) if eligible else False
    premature_majority = len(premature_rows) * 2 > len(separated) if separated else False
    causal_majority = len(causal_clean) * 2 > len(rows)
    if not eligible:
        name = "INCONCLUSIVE"
        reason = "No full uncontaminated oracle snapshot could be formed, so the representation was not tested."
    elif not oracle_majority:
        name = "FAIL"
        reason = "Oracle snapshots do not separate the end of the commercial from the following program on a majority of full snapshots."
    elif premature_majority:
        name = "FAIL"
        reason = "Oracle distance falls back to the program's own self-distance while advertisements are still playing, on a majority of the breaks it otherwise separates."
    elif not causal_majority:
        name = "INCONCLUSIVE"
        reason = "The oracle snapshot can separate returns, and the unchanged causal snapshot is not available in a clean form before most breaks."
    elif not gap["oracle_gap_larger"]:
        name = "INCONCLUSIVE"
        reason = "Per-break signs favor the frozen reference, but the pooled commercial-versus-return gap is not larger than the adaptive gap."
    else:
        name = "PASS"
        reason = "Both the oracle snapshot and the unchanged causal snapshot clear the pre-set majority bars on this one broadcast. That authorizes a later fixed-policy experiment. It does not choose a threshold."
    return {
        "verdict": name,
        "reason": reason,
        "eligible_full_oracle": len(eligible),
        "oracle_separated": len(separated),
        "oracle_premature_among_separated": len(premature_rows),
        "causal_clean": len(causal_clean),
        "n_breaks": len(rows),
        "oracle_gap_larger_than_adaptive": gap["oracle_gap_larger"],
    }


def plot_nbc(path: Path, ends: np.ndarray, adaptive: np.ndarray, oracle: np.ndarray, causal: np.ndarray, breaks: list[tuple[float, float]]) -> None:
    fig, axes = plt.subplots(3, 1, figsize=(14, 8.2), sharex=True)
    series = (
        (adaptive, "Adaptive 180 s reference", "#1f4e79"),
        (oracle, "Oracle snapshot, frozen at the known start", "#0b6e4f"),
        (causal, "Causal Exp003b snapshot, unchanged", "#6b3fa0"),
    )
    minutes = ends / 60.0
    for ax, (values, title, color) in zip(axes, series):
        for start, stop in breaks:
            ax.axvspan(start / 60.0, stop / 60.0, color="#e7d7c1", lw=0)
        ax.plot(minutes, values, color=color, lw=0.6)
        ax.set_ylabel("distance")
        ax.set_title(title)
        ax.set_xlim(0, NBC_COVERAGE[1] / 60.0)
    axes[-1].set_xlabel("minutes on the recording clock")
    fig.suptitle("NBC Cowboys at Giants. Shaded spans are the 21 labeled commercials.", fontsize=12)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=120)
    plt.close(fig)


def plot_redzone(path: Path, ends: np.ndarray, adaptive: np.ndarray, freezes: list[float], collapses: list[float]) -> None:
    fig, ax = plt.subplots(figsize=(14, 4.2))
    ax.plot(ends / 60.0, adaptive, color="#1f4e79", lw=0.6, label="adaptive distance")
    for index, t in enumerate(freezes):
        ax.axvline(t / 60.0, color="#a33b20", lw=0.7, label="Exp003b freeze" if index == 0 else None)
    for index, t in enumerate(collapses):
        ax.axvline(t / 60.0, color="#888888", lw=0.4, alpha=0.5, label="Exp002 collapse" if index == 0 else None)
    ax.set_xlim(0, REDZONE_COVERAGE[1] / 60.0)
    ax.set_xlabel("minutes")
    ax.set_ylabel("adaptive distance")
    ax.set_title("RedZone 0–7200 s. No labeled commercial. Every line is a false start if read as one.")
    ax.legend(loc="upper right", fontsize=8)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=120)
    plt.close(fig)


def write_csv(path: Path, rows: list[dict]) -> None:
    frame = pd.DataFrame(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def redzone_control(rows: list[dict]) -> dict:
    programs = [
        row for row in rows
        if row.get("session") == REDZONE and row.get("event_class") == "program"
    ]
    ads = commercials(rows, REDZONE, REDZONE_COVERAGE)
    if ads:
        raise SystemExit("RedZone coverage contains a commercial; refusing to invent a negative control")
    ends, adaptive, _embeddings = load_cloud(REDZONE)
    if float(ends[-1]) + 1e-6 < REDZONE_COVERAGE[1] - 1.0:
        raise SystemExit("RedZone features do not cover the closed range")
    freeze_path = REPO / "experiments/exp003b" / REDZONE / "freezes.json"
    records = json.loads(freeze_path.read_text(encoding="utf-8"))
    published = [float(row["trigger_s"]) for row in records if not row.get("skipped")]
    timeline = pd.read_parquet(REPO / "experiments/exp003b" / REDZONE / "frozen_timeline.parquet")
    recomputed = freeze_times(timeline["window_end"].to_numpy(dtype=float), timeline["hit"].to_numpy(dtype=bool))
    if [round(t, 3) for t in recomputed] != [round(t, 3) for t in published]:
        raise SystemExit("RedZone published freezes do not match the frozen hit mask")
    speaker = pd.read_parquet(REPO / "experiments/exp002" / REDZONE / "speaker_timeline.parquet")
    times = speaker["timestamp_seconds"].to_numpy(dtype=float)
    drops = drop_series(speaker["program_speaker_continuity_score"].to_numpy(dtype=float))
    collapses = time_ordered_events(times, drops, DROP_MIN)
    collapse_times = [float(row["timestamp_seconds"]) for row in collapses]
    hours = REDZONE_COVERAGE[1] / 3600.0
    summary_path = REPO / "experiments/exp003" / REDZONE / "summary.json"
    listing = json.loads(summary_path.read_text(encoding="utf-8"))["listing_peaks_not_a_mute_rule"]
    plot_redzone(OUT / "redzone_departures.png", ends, adaptive, published, collapse_times)
    return {
        "session": REDZONE,
        "coverage_s": list(REDZONE_COVERAGE),
        "target_commercials": len(ads),
        "program_marks": [
            {
                "start_s": float(row["start_seconds"]),
                "end_s": float(row["end_seconds"]),
                "note": row.get("note"),
            }
            for row in programs
        ],
        "capture_hole_after_coverage": "SESSION_CATALOG.csv says chunks 9–14 were removed, leaving 0–7200 s, then a 90 minute hole, then audio again at 12600 s. That hole is outside this closed range and is not scored.",
        "exp003b_freezes": len(published),
        "exp003b_false_starts_per_hour": round(len(published) / hours, 4),
        "exp003b_freeze_times_s": published,
        "espn_published_false_freezes_per_program_hour": ESPN_FALSE_FREEZES_PER_PROGRAM_HOUR,
        "exp002_collapse_events": len(collapse_times),
        "exp002_false_starts_per_hour": round(len(collapse_times) / hours, 4),
        "exp002_definition": f"continuity at least {DROP_MIN} below the max of the previous 10 s, then 45 s refractory",
        "exp003_listing_peaks": len(listing),
        "exp003_listing_note": "The frozen listing keeps 20 peaks at least 45 s apart. It is a fixed-length list, not an alarm rate. All 20 fall inside a range with no commercial.",
        "game_changes_labeled": False,
    }


def main() -> None:
    rows = active_marks()
    n_commercial = sum(1 for row in rows if row.get("event_class") == "commercial" and row.get("desired_action") == "mute" and row.get("confidence") != "unsure")
    n_program = sum(1 for row in rows if row.get("event_class") == "program" and row.get("desired_action") == "play")
    if len(rows) != 177 or n_commercial != 166 or n_program != 11:
        raise SystemExit(f"ledger counts {len(rows)} {n_commercial} {n_program}, expected 177 / 166 / 11")
    breaks = commercials(rows, NBC, NBC_COVERAGE)
    if len(breaks) != 21:
        raise SystemExit(f"NBC commercials {len(breaks)}, expected 21")
    ends, adaptive, embeddings = load_cloud(NBC)
    feature_end = float(ends[-1])
    timeline = pd.read_parquet(REPO / "experiments/exp003b" / NBC / "frozen_timeline.parquet")
    if not np.allclose(timeline["window_end"].to_numpy(dtype=float), ends):
        raise SystemExit("NBC Exp003 and Exp003b clocks differ")
    causal_distance = timeline["frozen_program_distance"].to_numpy(dtype=float)
    records = json.loads((REPO / "experiments/exp003b" / NBC / "freezes.json").read_text(encoding="utf-8"))
    published = [float(row["trigger_s"]) for row in records if not row.get("skipped")]
    recomputed = freeze_times(ends, timeline["hit"].to_numpy(dtype=bool))
    if [round(t, 3) for t in recomputed] != [round(t, 3) for t in published]:
        raise SystemExit("NBC published freezes do not match the frozen hit mask")
    spans = [(float(row["start_seconds"]), float(row["end_seconds"])) for row in breaks]
    oracle_series = np.full(len(ends), np.nan)
    table = []
    for index, row in enumerate(breaks, start=1):
        start = float(row["start_seconds"])
        stop = float(row["end_seconds"])
        nxt = spans[index][0] if index < len(breaks) else feature_end
        oracle = oracle_for_break(ends, embeddings, start, stop, nxt, spans)
        if oracle.get("distances") is not None:
            write = (ends > start) & (ends <= nxt) & np.isfinite(oracle["distances"])
            oracle_series[write] = oracle["distances"][write]
        table.append(break_row(index, row, nxt, ends, adaptive, oracle, causal_distance, causal_for_break(start, records, spans)))
    gap = pooled_gap([row for row in table if row["oracle_full"]], ends, oracle_series, adaptive)
    decision = verdict(table, gap)
    OUT.mkdir(parents=True, exist_ok=True)
    plot_nbc(OUT / "nbc_distances.png", ends, adaptive, oracle_series, causal_distance, spans)
    redzone = redzone_control(rows)
    payload = {
        "session": NBC,
        "coverage_s": list(NBC_COVERAGE),
        "feature_clock_end_s": feature_end,
        "feature_tail_without_embeddings_s": round(NBC_COVERAGE[1] - feature_end, 3),
        "n_breaks": len(table),
        "decision": decision,
        "pooled_full_oracle_breaks": gap,
        "breaks": table,
        "redzone": redzone,
        "hashes": {
            "truth_events.jsonl": sha256(TRUTH_PATH),
            "program_cloud_nbc": sha256(REPO / "experiments/exp003" / NBC / "program_cloud.parquet"),
            "frozen_timeline_nbc": sha256(REPO / "experiments/exp003b" / NBC / "frozen_timeline.parquet"),
            "freezes_nbc": sha256(REPO / "experiments/exp003b" / NBC / "freezes.json"),
            "program_cloud_redzone": sha256(REPO / "experiments/exp003" / REDZONE / "program_cloud.parquet"),
            "frozen_timeline_redzone": sha256(REPO / "experiments/exp003b" / REDZONE / "frozen_timeline.parquet"),
            "speaker_timeline_redzone": sha256(REPO / "experiments/exp002" / REDZONE / "speaker_timeline.parquet"),
            "checkpoint": "0dc499e40e9761ef5ea061ffc77697697f277f6a960894903df3ada000e34b31",
        },
        "rules": {
            "cover_s": COVER_S,
            "return_horizon_s": RETURN_HORIZON_S,
            "min_reference_s": MIN_REFERENCE_S,
            "oracle_uses_gold_only_to_place_the_snapshot": True,
            "causal_trigger_recomputed": False,
            "thresholds_fit": False,
        },
    }
    (OUT / "results.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    write_csv(OUT / "nbc_breaks.csv", table)
    print(decision["verdict"], decision["reason"], flush=True)
    print(
        f"eligible={decision['eligible_full_oracle']} separated={decision['oracle_separated']} "
        f"premature={decision['oracle_premature_among_separated']} causal_clean={decision['causal_clean']}",
        flush=True,
    )


if __name__ == "__main__":
    main()
