"""Exp003-v1 departure replication on September 9 NBC, plus the RedZone control.

Reads the frozen program-cloud scores. Does not re-embed, does not write into
experiments/exp003, and does not read gold while checking the cache.

exp003-v1 has no mute threshold. Two frozen descriptions are applied unchanged:

- The listing keeps the 20 largest scores at least 45 s apart. It is not an
  alarm rate. The top 50 is the cut already published in the ESPN overlay.
- The only causal operating point on this score is the Exp003b hit: above the
  99th percentile of the prior 10 minutes, then 3 of 5 seconds, then 60 s
  quiet. Those constants were not fit on September 9 or on RedZone.

The verdict rule is fixed here, before the NBC table is interpreted.

- A start is evaluable when both the prior 30 s and the following 30 s contain
  at least 10 defined scores. Earlier audio is startup, not a miss.
- The departure direction generalizes when a majority of evaluable starts have
  a higher median in the 30 s after the start than in the 30 s before.
- The listing is specific when at least 11 of the top 20 peaks fall inside a
  commercial or within 30 s of a start.
- The causal tradeoff holds when freezes within 30 s of a start are denser,
  per hour of that window, than freezes in the remaining program time.
- Speed holds when a majority of evaluable starts have such a freeze-hit, a
  single exceedance of the causal percentile, within 30 s. Latency to the
  maximum inside 30 s is reported and is not the detection delay.
- Fewer than 10 evaluable starts is INCONCLUSIVE. No rise, or a listing that
  is mostly program, or a causal alarm that is denser in program, is FAIL.
  A rise without a fast causal hit is INCONCLUSIVE. All four bars is PASS
  for testing frozen return later. PASS is not a mute policy.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import soundfile as sf

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from experiments.ledger import TRUTH_PATH, read_jsonl, resolve_ledger
from hush.frozen_identity import exceed_mask, freeze_times
from hush.program_cloud import MIN_REFERENCE_S, PARAMS, anomaly_scores, listing_peaks

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "docs/ohush/research/AUDIO_SIGNAL_REPLICATION_001"
NBC = "hush_20260909_213047"
REDZONE = "hush_20260913_150934"
HOLDOUTS = ("hush_20260917_205513", "hush_20260920_200635")
NBC_COVERAGE = (0.0, 9373.0)
REDZONE_COVERAGE = (0.0, 7200.0)
CHECKPOINT = REPO / "experiments/exp003/models/Cnn14_mAP=0.431.pth"
CHECKPOINT_SHA = "0dc499e40e9761ef5ea061ffc77697697f277f6a960894903df3ada000e34b31"
NEAR_S = 30.0


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
        if row.get("session") in HOLDOUTS:
            raise SystemExit("refusing a sealed holdout")
        if row.get("retracted") or row.get("event") == "retracted":
            continue
        if "start_seconds" not in row:
            continue
        kept.append(row)
    return kept


def commercials(rows: list[dict], session: str, coverage: tuple[float, float]) -> list[dict]:
    chosen = []
    for row in rows:
        if row.get("session") != session or row.get("event_class") != "commercial":
            continue
        if row.get("desired_action") != "mute" or row.get("confidence") == "unsure":
            continue
        start, end = float(row["start_seconds"]), float(row["end_seconds"])
        if start < coverage[0] or end > coverage[1] + 1e-6:
            raise SystemExit(f"{session} commercial leaves coverage")
        chosen.append(row)
    chosen.sort(key=lambda row: float(row["start_seconds"]))
    return chosen


def r4(value: float | None) -> float | None:
    if value is None or not np.isfinite(value):
        return None
    return round(float(value), 4)


def r3(value: float | None) -> float | None:
    if value is None or not np.isfinite(value):
        return None
    return round(float(value), 3)


def finite_slice(ends: np.ndarray, scores: np.ndarray, start: float, stop: float) -> np.ndarray:
    chosen = scores[(ends > start) & (ends <= stop)]
    return chosen[np.isfinite(chosen)]


def median(values: np.ndarray) -> float | None:
    if values.size == 0:
        return None
    return float(np.median(values))


def first_after(ends: np.ndarray, mask: np.ndarray, origin: float, horizon: float) -> float | None:
    chosen = np.flatnonzero((ends > origin) & (ends <= origin + horizon) & mask)
    if chosen.size == 0:
        return None
    return float(ends[chosen[0]] - origin)


def in_span(timestamp: float, spans: list[tuple[float, float]]) -> bool:
    return any(start <= timestamp <= stop for start, stop in spans)


def near_start(timestamp: float, starts: list[float]) -> bool:
    return any(0.0 < timestamp - start <= NEAR_S for start in starts)


def distribution(values: np.ndarray) -> dict:
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return {"n": 0}
    return {
        "n": int(finite.size),
        "p10": r4(float(np.percentile(finite, 10))),
        "p50": r4(float(np.percentile(finite, 50))),
        "p90": r4(float(np.percentile(finite, 90))),
        "mean": r4(float(np.mean(finite))),
    }


def verify_cache(session: str) -> dict:
    meta_path = REPO / "experiments/exp003" / session / "metadata.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if meta.get("truth_ledger_read") or meta.get("experiment_spec_version") != "exp003-v1":
        raise SystemExit(f"{session} cache is not an unlabeled exp003-v1 run")
    if meta.get("params") != PARAMS:
        raise SystemExit(f"{session} parameters differ from the frozen spec")
    if meta["embedding_model"]["checkpoint_sha256"] != CHECKPOINT_SHA:
        raise SystemExit(f"{session} metadata names a different checkpoint")
    if sha256(CHECKPOINT) != CHECKPOINT_SHA:
        raise SystemExit("checkpoint file hash does not match the frozen spec")
    wav = REPO / meta["analysis_wav"]["path"]
    wav_hash = sha256(wav)
    if wav_hash != meta["analysis_wav"]["sha256"]:
        raise SystemExit(f"{session} analysis wav hash does not match its metadata")
    info = pd.read_parquet(REPO / "experiments/exp003" / session / "program_cloud.parquet")
    ends = info["window_end"].to_numpy(dtype=np.float64)
    starts = info["window_start"].to_numpy(dtype=np.float64)
    stored = info["anomaly"].to_numpy(dtype=np.float64)
    embeddings = np.vstack([np.asarray(row, dtype=np.float64) for row in info["embedding"]])
    recomputed, _counts, _spans = anomaly_scores(starts, ends, embeddings)
    if not np.allclose(stored, recomputed, equal_nan=True, rtol=1e-5, atol=1e-6):
        raise SystemExit(f"{session} stored distances do not match the frozen formula")
    info = sf.info(str(wav))
    wav_seconds = info.frames / float(info.samplerate)
    if abs(wav_seconds - float(meta["t1"])) > 0.05:
        raise SystemExit(f"{session} wav duration {wav_seconds} does not match metadata t1")
    defined = np.flatnonzero(np.isfinite(stored))
    if defined.size == 0 or abs(float(ends[defined[0]]) - 80.0) > 1e-6:
        raise SystemExit(f"{session} warm-up is not the frozen 80 s first score")
    if float(np.median(np.diff(ends))) != 1.0:
        raise SystemExit(f"{session} hop is not 1 s")
    return {
        "metadata": meta,
        "wav_sha256": wav_hash,
        "wav_seconds": round(float(ends[-1]), 3),
        "ends": ends,
        "scores": stored,
        "parquet": REPO / "experiments/exp003" / session / "program_cloud.parquet",
    }


def listing_table(ends: np.ndarray, scores: np.ndarray, spans: list[tuple[float, float]], k: int) -> dict:
    peaks = listing_peaks(ends, scores, k=k)
    rows = []
    for rank, peak in enumerate(peaks, start=1):
        t = float(peak["timestamp_seconds"])
        start_times = [start for start, _stop in spans]
        rows.append(
            {
                "rank": rank,
                "timestamp_s": r3(t),
                "anomaly": r4(float(peak["anomaly"])),
                "in_commercial": in_span(t, spans),
                "within_30s_after_start": near_start(t, start_times),
            }
        )
    associated = sum(1 for row in rows if row["in_commercial"] or row["within_30s_after_start"])
    return {"k": k, "associated": associated, "in_program": k - associated, "peaks": rows}


def boundary_rows(ends: np.ndarray, scores: np.ndarray, hits: np.ndarray, breaks: list[dict]) -> list[dict]:
    rows = []
    for index, row in enumerate(breaks, start=1):
        start = float(row["start_seconds"])
        stop = float(row["end_seconds"])
        pre = finite_slice(ends, scores, start - 30.0, start)
        post = finite_slice(ends, scores, start, start + 30.0)
        pre_median = median(pre)
        post_median = median(post)
        evaluable = pre.size >= 10 and post.size >= 10 and pre_median is not None and post_median is not None
        rise = bool(evaluable and post_median > pre_median)
        pre_max = None if pre.size == 0 else float(np.max(pre))
        rise_delay = None
        if pre_max is not None:
            above = (ends > start) & (ends <= stop) & np.isfinite(scores) & (scores > pre_max)
            chosen = np.flatnonzero(above)
            if chosen.size:
                rise_delay = float(ends[chosen[0]] - start)
        hit_delay = first_after(ends, hits, start, max(0.0, stop - start))
        peak_idx = np.flatnonzero((ends > start) & (ends <= start + 30.0) & np.isfinite(scores))
        latency_to_max = None
        if peak_idx.size:
            latency_to_max = float(ends[peak_idx[int(np.argmax(scores[peak_idx]))]] - start)
        if not evaluable:
            failure = "signal_unavailable"
        elif not rise:
            failure = "median_does_not_rise"
        elif hit_delay is None:
            failure = "rises_without_causal_hit_during_the_break"
        elif hit_delay < 10.0:
            failure = "causal_hit_window_still_contains_prebreak_audio"
        elif hit_delay <= 30.0:
            failure = "causal_hit_within_30s"
        else:
            failure = "causal_hit_after_30s"
        rows.append(
            {
                "index": index,
                "gold_id": row.get("gold_id"),
                "start_s": r3(start),
                "end_s": r3(stop),
                "duration_s": r3(stop - start),
                "evaluable": evaluable,
                "pre30_n": int(pre.size),
                "post30_n": int(post.size),
                "pre30_median": r4(pre_median),
                "post30_median": r4(post_median),
                "post_minus_pre": None if not evaluable else r4(post_median - pre_median),
                "median_rises": rise,
                "first_score_above_pre30_max_s": r3(rise_delay),
                "first_causal_hit_during_break_s": r3(hit_delay),
                "latency_to_max_in_30s_not_a_detection_delay": r3(latency_to_max),
                "failure": failure,
            }
        )
    return rows


def freeze_split(triggers: list[float], spans: list[tuple[float, float]], coverage_end: float) -> dict:
    starts = [start for start, _stop in spans]
    near = [t for t in triggers if near_start(t, starts)]
    inside = [t for t in triggers if in_span(t, spans)]
    program = [t for t in triggers if not in_span(t, spans) and not near_start(t, starts)]
    grid = np.arange(coverage_end)
    pod = np.zeros(grid.shape, dtype=bool)
    near_grid = np.zeros(grid.shape, dtype=bool)
    for start, stop in spans:
        pod |= (grid >= start) & (grid < min(stop, coverage_end))
        near_grid |= (grid > start) & (grid <= start + NEAR_S) & (grid < coverage_end)
    near_hours = float(near_grid.sum()) / 3600.0
    program_hours = float((~pod & ~near_grid).sum()) / 3600.0
    return {
        "n_freezes": len(triggers),
        "within_30s_after_start": len(near),
        "inside_commercial_not_only_the_start_window": len(inside),
        "in_program": len(program),
        "program_s": r3(float((~pod & ~near_grid).sum())),
        "near_start_s": r3(float(near_grid.sum())),
        "program_per_hour": None if program_hours <= 0 else r4(len(program) / program_hours),
        "near_start_per_hour": None if near_hours <= 0 else r4(len(near) / near_hours),
        "freeze_times_s": [r3(t) for t in triggers],
        "program_freeze_times_s": [r3(t) for t in program],
    }


def speaker_at(frame: pd.DataFrame, t: float) -> dict:
    times = frame["timestamp_seconds"].to_numpy(dtype=float)
    idx = int(np.argmin(np.abs(times - t)))
    before = int(np.argmin(np.abs(times - (t - 30.0))))
    cluster = frame.iloc[idx]["speaker_cluster_id"]
    earlier = frame.iloc[before]["speaker_cluster_id"]
    continuity = float(frame.iloc[idx]["program_speaker_continuity_score"])
    earlier_continuity = float(frame.iloc[before]["program_speaker_continuity_score"])
    return {
        "cluster": None if pd.isna(cluster) else str(cluster),
        "cluster_30s_earlier": None if pd.isna(earlier) else str(earlier),
        "cluster_changed": (not pd.isna(cluster)) and (not pd.isna(earlier)) and str(cluster) != str(earlier),
        "continuity": r4(continuity),
        "continuity_drop_from_30s_earlier": r4(earlier_continuity - continuity),
    }


def plot_series(path: Path, ends: np.ndarray, scores: np.ndarray, spans: list[tuple[float, float]], title: str, xmax: float) -> None:
    fig, ax = plt.subplots(figsize=(14, 4.2))
    for start, stop in spans:
        ax.axvspan(start / 60.0, stop / 60.0, color="#e7d7c1", lw=0)
    ax.plot(ends / 60.0, scores, color="#1f4e79", lw=0.6)
    ax.set_xlim(0, xmax / 60.0)
    ax.set_xlabel("minutes")
    ax.set_ylabel("distance from recent 180 s")
    ax.set_title(title)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=120)
    plt.close(fig)


def plot_distributions(path: Path, nbc_pod: np.ndarray, nbc_program: np.ndarray, redzone: np.ndarray) -> None:
    fig, ax = plt.subplots(figsize=(7.2, 3.8))
    bins = np.linspace(0, 0.55, 40)
    ax.hist(nbc_program[np.isfinite(nbc_program)], bins=bins, density=True, alpha=0.55, color="#1f4e79", label="NBC program")
    ax.hist(nbc_pod[np.isfinite(nbc_pod)], bins=bins, density=True, alpha=0.55, color="#c47b2b", label="NBC commercials")
    ax.hist(redzone[np.isfinite(redzone)], bins=bins, density=True, histtype="step", linewidth=1.4, color="#111111", label="RedZone")
    ax.set_xlabel("distance from recent 180 s")
    ax.set_ylabel("density")
    ax.legend(fontsize=8)
    ax.set_title("Same frozen score. No threshold is drawn.")
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def verdict(rows: list[dict], top20_associated: int, split: dict) -> dict:
    evaluable = [row for row in rows if row["evaluable"]]
    rises = [row for row in evaluable if row["median_rises"]]
    fast = [
        row
        for row in evaluable
        if row["first_causal_hit_during_break_s"] is not None and row["first_causal_hit_during_break_s"] <= 30.0
    ]
    delays = [row["first_causal_hit_during_break_s"] for row in fast]
    median_delay = None if not delays else float(np.median(delays))
    near_rate = split["near_start_per_hour"]
    program_rate = split["program_per_hour"]
    if len(evaluable) < 10:
        name = "INCONCLUSIVE"
        reason = "Too few starts have a defined score both before and after the boundary."
    elif len(rises) * 2 <= len(evaluable):
        name = "FAIL"
        reason = "The 30-second median does not rise at a majority of evaluable commercial starts."
    elif top20_associated < 11:
        name = "FAIL"
        reason = "The frozen top-20 listing falls in ordinary programming at least as often as it falls near commercials."
    elif near_rate is None or program_rate is None or program_rate >= near_rate:
        name = "FAIL"
        reason = "At the only predeclared causal operating point, alarms during ordinary programming are at least as dense as alarms just after commercial starts."
    elif len(fast) * 2 <= len(evaluable):
        name = "INCONCLUSIVE"
        reason = "The distance usually rises, and the predeclared causal hit does not arrive within 30 seconds for a majority of starts."
    else:
        name = "PASS"
        reason = "The departure direction, the listing, and the causal hit are specific enough on this recording to justify a later frozen-return test. They are not a mute policy."
    return {
        "verdict": name,
        "reason": reason,
        "evaluable": len(evaluable),
        "median_rises": len(rises),
        "causal_hit_within_30s": len(fast),
        "median_causal_hit_delay_s": r3(median_delay),
        "top20_associated": top20_associated,
        "near_start_per_hour": near_rate,
        "program_per_hour": program_rate,
    }


def main() -> None:
    nbc = verify_cache(NBC)
    red = verify_cache(REDZONE)
    rows = active_marks()
    breaks = commercials(rows, NBC, NBC_COVERAGE)
    red_ads = commercials(rows, REDZONE, REDZONE_COVERAGE)
    if red_ads:
        raise SystemExit("RedZone range contains a commercial")
    if len(breaks) != 20:
        raise SystemExit(f"expected 20 NBC commercials, found {len(breaks)}")
    commercial_s = sum(float(row["end_seconds"]) - float(row["start_seconds"]) for row in breaks)
    if abs(commercial_s - 2849.9) > 0.1:
        raise SystemExit(f"NBC commercial seconds {commercial_s} are not 2849.9")
    ends, scores = nbc["ends"], nbc["scores"]
    hits = exceed_mask(ends, scores)
    triggers = freeze_times(ends, hits)
    spans = [(float(row["start_seconds"]), float(row["end_seconds"])) for row in breaks]
    table = boundary_rows(ends, scores, hits, breaks)
    split = freeze_split(triggers, spans, NBC_COVERAGE[1])
    top20 = listing_table(ends, scores, spans, 20)
    top50 = listing_table(ends, scores, spans, 50)
    decision = verdict(table, top20["associated"], split)
    pod = np.zeros(len(ends), dtype=bool)
    for start, stop in spans:
        pod |= (ends >= start) & (ends <= stop)
    startup = float(ends[np.isfinite(scores)][0])
    unavailable_commercial_s = 0.0
    for start, stop in spans:
        inside = finite_slice(ends, scores, start, stop)
        if inside.size == 0:
            unavailable_commercial_s += stop - start
    red_ends, red_scores = red["ends"], red["scores"]
    red_hits = exceed_mask(red_ends, red_scores)
    red_triggers = freeze_times(red_ends, red_hits)
    red_top = listing_table(red_ends, red_scores, [], 20)
    speaker = pd.read_parquet(REPO / "experiments/exp002" / REDZONE / "speaker_timeline.parquet")
    red_peaks = []
    for peak in red_top["peaks"][:10]:
        red_peaks.append({**peak, "speaker": speaker_at(speaker, float(peak["timestamp_s"]))})
    changed = sum(1 for row in red_peaks if row["speaker"]["cluster_changed"])
    OUT.mkdir(parents=True, exist_ok=True)
    series = pd.DataFrame({"window_end": ends, "anomaly": scores})
    series_path = OUT / "nbc_audio_distance.parquet"
    series.to_parquet(series_path, index=False)
    plot_series(
        OUT / "nbc_distance.png",
        ends,
        scores,
        spans,
        "September 9 NBC. Shaded spans are the 20 labeled commercials.",
        NBC_COVERAGE[1],
    )
    plot_series(
        OUT / "redzone_distance.png",
        red_ends,
        red_scores,
        [],
        "RedZone 0–7200 s. No labeled commercial. The same frozen score.",
        REDZONE_COVERAGE[1],
    )
    plot_distributions(OUT / "distributions.png", scores[pod], scores[~pod], red_scores)
    payload = {
        "verdict": decision,
        "nbc": {
            "session": NBC,
            "coverage_s": list(NBC_COVERAGE),
            "commercials": len(breaks),
            "commercial_s": r3(commercial_s),
            "feature_end_s": nbc["wav_seconds"],
            "startup_undefined_until_s": startup,
            "min_reference_s": MIN_REFERENCE_S,
            "commercial_seconds_with_no_defined_score": r3(unavailable_commercial_s),
            "capture_gaps_inside_coverage": [],
            "pod_distribution": distribution(scores[pod]),
            "program_distribution": distribution(scores[~pod & np.isfinite(scores)]),
            "top20": {key: value for key, value in top20.items() if key != "peaks"},
            "top50": {key: value for key, value in top50.items() if key != "peaks"},
            "causal_freezes": split,
            "breaks": table,
        },
        "redzone": {
            "session": REDZONE,
            "coverage_s": list(REDZONE_COVERAGE),
            "target_commercials": 0,
            "distribution": distribution(red_scores[np.isfinite(red_scores)]),
            "causal_freezes": len(red_triggers),
            "causal_false_starts_per_hour": r4(len(red_triggers) / (REDZONE_COVERAGE[1] / 3600.0)),
            "freeze_times_s": [r3(t) for t in red_triggers],
            "top20_all_in_program": red_top["in_program"] == 20,
            "strongest_peaks_speaker": red_peaks,
            "strongest_10_with_cluster_change": changed,
            "game_changes_labeled": False,
        },
        "hashes": {
            "checkpoint": sha256(CHECKPOINT),
            "nbc_wav": nbc["wav_sha256"],
            "nbc_program_cloud": sha256(nbc["parquet"]),
            "redzone_program_cloud": sha256(red["parquet"]),
            "distance_series": sha256(series_path),
            "truth_events": sha256(TRUTH_PATH),
        },
        "mute_policy": None,
        "simulated_playback_reported": False,
    }
    (OUT / "results.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    pd.DataFrame(table).to_csv(OUT / "nbc_breaks.csv", index=False)
    print(decision["verdict"], decision["reason"], flush=True)
    print(
        f"evaluable={decision['evaluable']} rises={decision['median_rises']} "
        f"fast={decision['causal_hit_within_30s']} top20={decision['top20_associated']} "
        f"near/h={decision['near_start_per_hour']} program/h={decision['program_per_hour']}",
        flush=True,
    )


if __name__ == "__main__":
    main()
