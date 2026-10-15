"""CANDIDATE_VERIFICATION_001.

The DSP episodes are the frozen CONTINUOUS_DSP_001 list. This script does not
rescan for new alarms and does not change a threshold in the live system.

Departure score, frozen before the evaluation recordings are read:

- level: CNN14 anomaly at window_end = episode.available_at.
  That window is [available_at-10, available_at) and is available then.
- rise: level minus the median anomaly on window ends in
  [available_at-30, available_at-10).
- ratio: level divided by that same median.

A score is eligible only if it is finite for at least 80% of ESPN program
episodes and 80% of ESPN fresh-start episodes. Among eligible scores, ESPN
average precision chooses one. Ties prefer level, then rise, then ratio.

Budgets of 1, 0.5 and 0.1 false program-episode accepts per hour are turned
into a threshold on ESPN only. An episode is accepted when its score is
strictly above that threshold. Evaluation recordings, RedZone, and the
scripted sessions do not move the threshold.

A fresh start episode begins in [commercial IN, IN+3s]. An episode that
started earlier and is merely still on is not counted as that start.

PASS if some budget transfers to the evaluation football games and to RedZone
with a false-accept rate no higher than that budget, and accepts at least
half of the evaluation starts that have a fresh 3-second episode.
FAIL if the chosen ESPN score does not rank above the positive prevalence
by 0.02, or if every budget whose evaluation rate stays within twice the
budget accepts under a quarter of those fresh-candidate starts.
Otherwise INCONCLUSIVE.

Speaker identity is not scored. The booth file and cluster ids are unaudited.
"""

from __future__ import annotations

import csv
import hashlib
import json
import resource
import sys
import time
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from experiments.broadcast_intelligence.batch1 import read_span
from experiments.broadcast_intelligence.continuous_dsp import SR, deltas_from_parts, mono_of
from hush.audio import find_session, load_session
from hush.frozen_identity import exceed_mask, freeze_times
from hush.program_cloud import PARAMS

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "docs/ohush/research/CANDIDATE_VERIFICATION_001"
EPISODES = REPO / "docs/ohush/research/CONTINUOUS_DSP_001/episodes.csv"
STARTS = REPO / "docs/ohush/research/CONTINUOUS_DSP_001/starts.csv"
ENDS = REPO / "docs/ohush/research/CONTINUOUS_DSP_001/ends.csv"
RESULTS = REPO / "docs/ohush/research/CONTINUOUS_DSP_001/results.json"
EXP003 = REPO / "experiments/exp003"
RECORDINGS = REPO / "recordings"
DEV = "hush_20260914_212529"
REDZONE = "hush_20260913_150934"
NEAR_S = 3.0
BUDGETS = (1.0, 0.5, 0.1)
SCORE_ORDER = ("level", "rise", "ratio")
WINDOWS = (3, 5, 10, 30)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def pods_for(starts: list[dict], ends: list[dict]) -> dict[str, list[tuple[float, float]]]:
    by_start = defaultdict(list)
    by_end = defaultdict(list)
    for row in starts:
        by_start[row["session"]].append(float(row["boundary_s"]))
    for row in ends:
        by_end[row["session"]].append(float(row["boundary_s"]))
    pods = {}
    for sid in by_start:
        if len(by_start[sid]) != len(by_end[sid]):
            raise SystemExit(f"{sid} has {len(by_start[sid])} starts and {len(by_end[sid])} ends")
        pods[sid] = list(zip(by_start[sid], by_end[sid]))
    return pods


def classify(episode: dict, pods: list[tuple[float, float]]) -> dict:
    t0 = int(episode["t_start"])
    t1 = int(episode["t_end"])
    fresh_start = None
    fresh_end = None
    inside = False
    for start, end in pods:
        if start <= t0 <= start + NEAR_S:
            fresh_start = start
        if end <= t0 <= end + NEAR_S:
            fresh_end = end
        if start <= t0 < end and not (start <= t0 <= start + NEAR_S):
            inside = True
    overlaps_start = [start for start, end in pods if t0 < start <= t1]
    overlaps_end = [end for start, end in pods if t0 < end <= t1]
    if episode["session"] == REDZONE:
        kind = "redzone"
    elif fresh_start is not None:
        kind = "fresh_start"
    elif fresh_end is not None:
        kind = "fresh_end"
    elif inside:
        kind = "inside_pod"
    elif overlaps_start:
        kind = "ongoing_start"
    elif overlaps_end:
        kind = "ongoing_end"
    else:
        kind = "program"
    return {
        "class": kind,
        "fresh_start_s": fresh_start,
        "fresh_end_s": fresh_end,
        "ongoing_start_s": overlaps_start[0] if overlaps_start else None,
        "ongoing_end_s": overlaps_end[0] if overlaps_end else None,
    }


def average_precision(labels: np.ndarray, scores: np.ndarray) -> float:
    order = np.argsort(-scores)
    y = labels[order]
    if int(y.sum()) == 0:
        return float("nan")
    tp = np.cumsum(y)
    precision = tp / np.arange(1, len(y) + 1)
    return float(precision[y == 1].mean())


def threshold_for_budget(program_scores: np.ndarray, hours: float, budget: float) -> tuple[float, int]:
    """Accept a score strictly above this value. At most floor(budget*hours) program episodes."""
    k = int(np.floor(budget * hours + 1e-12))
    ordered = np.sort(program_scores)[::-1]
    if ordered.size == 0:
        return float("inf"), k
    if k <= 0:
        return float(ordered[0]), k
    if k >= ordered.size:
        return float("-inf"), k
    return float(ordered[k]), k


def load_cnn(session: str) -> dict | None:
    folder = EXP003 / session
    path = folder / "program_cloud.parquet"
    meta_path = folder / "metadata.json"
    if not path.exists() or not meta_path.exists():
        return None
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if meta.get("truth_ledger_read") is not False:
        raise SystemExit(f"{session} CNN14 cache read the truth ledger")
    if meta.get("params") != PARAMS:
        raise SystemExit(f"{session} CNN14 params differ from program_cloud.PARAMS")
    if meta.get("analysis_wav", {}).get("hop_s") != 1.0 or meta.get("analysis_wav", {}).get("window_s") != 10.0:
        raise SystemExit(f"{session} CNN14 window is not 10 s / 1 s")
    import pyarrow.parquet as pq

    table = pq.read_table(path, columns=["window_end", "anomaly"])
    ends = table.column("window_end").to_numpy().astype(np.float64)
    scores = table.column("anomaly").to_numpy().astype(np.float64)
    if np.any(np.diff(ends) <= 0):
        raise SystemExit(f"{session} CNN14 times are not increasing")
    hits = exceed_mask(ends, scores)
    freezes = freeze_times(ends, hits)
    index = {int(round(t)): i for i, t in enumerate(ends)}
    return {
        "ends": ends,
        "scores": scores,
        "hits": hits,
        "freezes": freezes,
        "index": index,
        "sha256": sha256(path),
        "checkpoint_sha256": meta["embedding_model"]["checkpoint_sha256"],
        "first_defined": None if not np.isfinite(scores).any() else float(ends[np.isfinite(scores)][0]),
    }


def score_at(series: dict, t: float) -> tuple[float, bool]:
    slot = series["index"].get(int(round(t)))
    if slot is None:
        return float("nan"), False
    value = float(series["scores"][slot])
    if not np.isfinite(value):
        return float("nan"), False
    return value, bool(series["hits"][slot])


def attach_cnn(episode: dict, series: dict | None) -> dict:
    available = int(episode["available_at"])
    blank = {
        "cnn_joined": False,
        "level": None,
        "before": None,
        "rise": None,
        "ratio": None,
        "exceed_at_available": False,
        "freeze_within_10s": False,
        "history_n": 0,
    }
    if series is None:
        return blank
    level, exceed = score_at(series, available)
    before, _ = score_at(series, int(episode["t_start"]))
    hist = []
    for t in range(available - 30, available - 10):
        value, _ = score_at(series, t)
        if np.isfinite(value):
            hist.append(value)
    median = float(np.median(hist)) if len(hist) >= 10 else float("nan")
    rise = level - median if np.isfinite(level) and np.isfinite(median) else float("nan")
    ratio = level / median if np.isfinite(level) and np.isfinite(median) and median > 0 else float("nan")
    t0 = int(episode["t_start"])
    freeze = any(t0 <= freeze_t <= t0 + 10 for freeze_t in series["freezes"])
    return {
        "cnn_joined": True,
        "level": None if not np.isfinite(level) else level,
        "before": None if not np.isfinite(before) else before,
        "rise": None if not np.isfinite(rise) else rise,
        "ratio": None if not np.isfinite(ratio) else ratio,
        "exceed_at_available": exceed,
        "freeze_within_10s": freeze,
        "history_n": len(hist),
    }


def attach_deltas(episodes: list[dict]) -> None:
    by_session = defaultdict(list)
    for episode in episodes:
        by_session[episode["session"]].append(episode)
    for sid, rows in by_session.items():
        folder = find_session(RECORDINGS, sid)
        meta = load_session(folder)
        rows.sort(key=lambda row: int(row["t_start"]))
        cache_t0 = None
        cache = None
        for episode in rows:
            t0 = int(episode["t_start"])
            if cache is None or t0 < cache_t0 + 2 or t0 + 1 > cache_t0 + len(cache) / SR:
                cache_t0 = t0 - 2.0
                try:
                    audio = read_span(folder, meta, cache_t0, t0 + 90.0)
                    cache = mono_of(audio)
                except RuntimeError:
                    cache = None
            if cache is None:
                episode["rms"] = episode["flatness"] = episode["centroid"] = None
                continue
            offset = int(round((t0 - 2.0 - cache_t0) * SR))
            piece_pre = cache[offset : offset + 2 * SR]
            piece_post = cache[offset + 2 * SR : offset + 3 * SR]
            if len(piece_pre) < 2 * SR or len(piece_post) < SR:
                episode["rms"] = episode["flatness"] = episode["centroid"] = None
                continue
            rms, flat, cent = deltas_from_parts(piece_pre, piece_post)
            episode["rms"] = float(rms)
            episode["flatness"] = float(flat)
            episode["centroid"] = float(cent)


def finite_scores(rows: list[dict], name: str) -> np.ndarray:
    return np.asarray([row[name] for row in rows if row[name] is not None], dtype=np.float64)


def choose_score(espn: list[dict]) -> dict:
    positives = [row for row in espn if row["class"] == "fresh_start"]
    negatives = [row for row in espn if row["class"] == "program"]
    choice = {"eligible": [], "rejected": [], "chosen": None, "average_precision": None, "prevalence": None}
    if not positives or not negatives:
        return choice
    best = None
    for name in SCORE_ORDER:
        pos = finite_scores(positives, name)
        neg = finite_scores(negatives, name)
        pos_frac = len(pos) / len(positives)
        neg_frac = len(neg) / len(negatives)
        record = {
            "score": name,
            "finite_positive_fraction": round(pos_frac, 4),
            "finite_negative_fraction": round(neg_frac, 4),
        }
        if pos_frac < 0.80 or neg_frac < 0.80 or pos.size == 0 or neg.size == 0:
            record["average_precision"] = None
            choice["rejected"].append(record)
            continue
        labels = np.concatenate([np.ones(pos.size), np.zeros(neg.size)])
        scores = np.concatenate([pos, neg])
        ap = average_precision(labels, scores)
        record["average_precision"] = round(ap, 4)
        record["n_positive"] = int(pos.size)
        record["n_negative"] = int(neg.size)
        choice["eligible"].append(record)
        if best is None or ap > best[0] + 1e-12:
            best = (ap, name, len(pos) / (len(pos) + len(neg)))
    if best is not None:
        choice["chosen"] = best[1]
        choice["average_precision"] = round(best[0], 4)
        choice["prevalence"] = round(best[2], 4)
    return choice


def operating_points(dev_program: list[dict], dev_hours: float, score: str) -> list[dict]:
    values = finite_scores(dev_program, score)
    points = []
    for budget in BUDGETS:
        level, k = threshold_for_budget(values, dev_hours, budget)
        points.append({"budget_per_hour": budget, "espn_allowed_false_accepts": k, "threshold": level, "comparison": "score > threshold"})
    return points


def accepts(row: dict, score: str, threshold: float) -> bool:
    value = row.get(score)
    return value is not None and value > threshold


def program_hours(recordings: list[dict], sessions: set[str]) -> float:
    seconds = 0
    for row in recordings:
        if row["session"] in sessions:
            seconds += row["features"]["or"]["program_seconds"]
    return seconds / 3600.0


def evaluate(starts: list[dict], episodes: list[dict], recordings: list[dict], score: str, threshold: float, sessions: set[str]) -> dict:
    chosen_eps = [row for row in episodes if row["session"] in sessions]
    program = [row for row in chosen_eps if row["class"] == "program"]
    redzone = [row for row in chosen_eps if row["class"] == "redzone"]
    inside = [row for row in chosen_eps if row["class"] == "inside_pod"]
    hours = program_hours(recordings, sessions - {REDZONE})
    rz_hours = program_hours(recordings, {REDZONE} & sessions)
    accepted_program = [row for row in program if accepts(row, score, threshold)]
    accepted_inside = [row for row in inside if accepts(row, score, threshold)]
    accepted_rz = [row for row in redzone if accepts(row, score, threshold)]
    by_session = defaultdict(lambda: {"program": 0, "accepted_program": 0, "fresh_starts": 0})
    for row in program:
        by_session[row["session"]]["program"] += 1
        if accepts(row, score, threshold):
            by_session[row["session"]]["accepted_program"] += 1
    start_rows = [row for row in starts if row["session"] in sessions and row["content"] == "sports"]
    delays = {window: [] for window in WINDOWS}
    accepted_at = {window: 0 for window in WINDOWS}
    candidate_at_3 = 0
    rejected_at_3 = 0
    missing_score_at_3 = 0
    for start in start_rows:
        boundary = float(start["boundary_s"])
        fresh = [
            row for row in chosen_eps
            if row["class"] == "fresh_start" and row["fresh_start_s"] is not None and abs(row["fresh_start_s"] - boundary) < 1e-6
        ]
        if any(boundary <= int(row["t_start"]) <= boundary + NEAR_S for row in fresh):
            candidate_at_3 += 1
            scored = [row for row in fresh if row[score] is not None and boundary <= int(row["t_start"]) <= boundary + NEAR_S]
            if not scored:
                missing_score_at_3 += 1
            elif not any(accepts(row, score, threshold) for row in scored):
                rejected_at_3 += 1
        for window in WINDOWS:
            hit = [
                row for row in fresh
                if boundary <= int(row["t_start"]) <= boundary + window and accepts(row, score, threshold)
            ]
            if hit:
                accepted_at[window] += 1
                delay = min(int(row["available_at"]) - boundary for row in hit)
                delays[window].append(delay)
    per_recording = []
    hour_map = {row["session"]: row["features"]["or"]["program_seconds"] / 3600.0 for row in recordings}
    for sid, bag in sorted(by_session.items()):
        hours_here = hour_map.get(sid, 0.0)
        rate = None if hours_here <= 0 else bag["accepted_program"] / hours_here
        per_recording.append({
            "session": sid,
            "program_episodes": bag["program"],
            "accepted_program_episodes": bag["accepted_program"],
            "false_accepts_per_hour": None if rate is None else round(rate, 3),
            "program_hours": round(hours_here, 3),
        })
    worst = max(per_recording, key=lambda row: row["false_accepts_per_hour"] or -1, default=None)
    clean = [row["session"] for row in per_recording if row["accepted_program_episodes"] == 0]
    def delay_stats(window: int) -> dict:
        values = delays[window]
        if not values:
            return {"median_s": None, "p95_s": None}
        arr = np.asarray(values)
        return {"median_s": round(float(np.median(arr)), 3), "p95_s": round(float(np.percentile(arr, 95)), 3)}
    return {
        "starts": len(start_rows),
        "fresh_candidate_starts_within_3s": candidate_at_3,
        "accepted_starts": {str(window): accepted_at[window] for window in WINDOWS},
        "fraction_of_starts": {str(window): round(accepted_at[window] / len(start_rows), 4) if start_rows else None for window in WINDOWS},
        "fraction_of_fresh_3s_candidates": None if candidate_at_3 == 0 else round(accepted_at[3] / candidate_at_3, 4),
        "rejected_fresh_3s_candidates": rejected_at_3,
        "fresh_3s_missing_score": missing_score_at_3,
        "delay_s": {str(window): delay_stats(window) for window in WINDOWS},
        "program_episodes": len(program),
        "accepted_program_episodes": len(accepted_program),
        "program_hours": round(hours, 3),
        "false_accepts_per_hour": None if hours <= 0 else round(len(accepted_program) / hours, 3),
        "inside_pod_episodes": len(inside),
        "accepted_inside_pod_episodes": len(accepted_inside),
        "redzone_episodes": len(redzone),
        "accepted_redzone_episodes": len(accepted_rz),
        "redzone_hours": round(rz_hours, 3),
        "redzone_false_accepts_per_hour": None if rz_hours <= 0 else round(len(accepted_rz) / rz_hours, 3),
        "recordings_with_no_false_accepts": clean,
        "worst_recording": worst,
        "per_recording": per_recording,
    }


def pr_curve(episodes: list[dict], score: str) -> list[dict]:
    rows = [row for row in episodes if row["class"] in ("fresh_start", "program") and row[score] is not None]
    if not rows:
        return []
    labels = np.asarray([1 if row["class"] == "fresh_start" else 0 for row in rows])
    scores = np.asarray([row[score] for row in rows], dtype=np.float64)
    order = np.argsort(-scores)
    y = labels[order]
    tp = np.cumsum(y)
    fp = np.cumsum(1 - y)
    precision = tp / (tp + fp)
    recall = tp / max(int(y.sum()), 1)
    # Keep about 200 points.
    step = max(1, len(y) // 200)
    return [
        {"precision": round(float(precision[i]), 4), "recall": round(float(recall[i]), 4)}
        for i in range(0, len(y), step)
    ]


def residual(starts: list[dict], episodes: list[dict], cnn_sessions: set[str], score: str, threshold: float) -> list[dict]:
    by_start = defaultdict(list)
    for row in episodes:
        if row["class"] == "fresh_start" and row["fresh_start_s"] is not None:
            by_start[(row["session"], round(row["fresh_start_s"], 3))].append(row)
    ongoing = defaultdict(list)
    for row in episodes:
        if row["ongoing_start_s"] is not None:
            ongoing[(row["session"], round(float(row["ongoing_start_s"]), 3))].append(row)
    rows = []
    for start in starts:
        if start["content"] != "sports":
            continue
        boundary = float(start["boundary_s"])
        key = (start["session"], round(boundary, 3))
        fresh = [row for row in by_start.get(key, []) if boundary <= int(row["t_start"]) <= boundary + NEAR_S]
        still_on = ongoing.get(key, [])
        if start["session"] not in cnn_sessions:
            cause = "cnn_evidence_unavailable" if fresh else ("dsp_already_active" if still_on else "no_dsp_candidate")
        elif not fresh and still_on:
            cause = "dsp_already_active"
        elif not fresh:
            cause = "no_dsp_candidate"
        elif all(row[score] is None for row in fresh):
            cause = "cnn_evidence_unavailable"
        elif any(accepts(row, score, threshold) for row in fresh):
            delay = min(int(row["available_at"]) - boundary for row in fresh if accepts(row, score, threshold))
            cause = "accepted" if delay <= 10 else "accepted_too_late"
        else:
            cause = "cnn_evidence_insufficient"
        rows.append({"session": start["session"], "boundary_s": boundary, "cause": cause})
    return rows


def main() -> None:
    sys.stdout.reconfigure(line_buffering=True)
    started = time.perf_counter()
    prior = json.loads(RESULTS.read_text(encoding="utf-8"))
    recordings = prior["recordings"]
    starts = load_rows(STARTS)
    ends = load_rows(ENDS)
    episodes = [row for row in load_rows(EPISODES) if row["feature"] == "or"]
    pods = pods_for(starts, ends)
    print(f"frozen OR episodes {len(episodes)}", flush=True)
    for episode in episodes:
        episode.update(classify(episode, pods.get(episode["session"], [])))
    print("reading onset deltas", flush=True)
    attach_deltas(episodes)
    sessions = sorted({row["session"] for row in episodes})
    cnn = {}
    hashes = {}
    for sid in sessions:
        print(f"cnn {sid}", flush=True)
        series = load_cnn(sid)
        cnn[sid] = series
        if series is not None:
            hashes[sid] = {"program_cloud_sha256": series["sha256"], "checkpoint_sha256": series["checkpoint_sha256"], "first_defined_window_end": series["first_defined"]}
        for episode in episodes:
            if episode["session"] == sid:
                episode.update(attach_cnn(episode, series))
    espn = [row for row in episodes if row["session"] == DEV]
    selection = choose_score(espn)
    score = selection["chosen"]
    if score is None:
        raise SystemExit(f"no eligible CNN14 score on ESPN: {json.dumps(selection)}")
    dev_hours = program_hours(recordings, {DEV})
    points = operating_points([row for row in espn if row["class"] == "program"], dev_hours, score)
    eval_sessions = {
        row["session"] for row in recordings
        if row["content"] == "sports" and row["session"] not in {DEV, REDZONE} and cnn.get(row["session"]) is not None
    }
    missing_cnn = [
        row["session"] for row in recordings
        if row["content"] == "sports" and cnn.get(row["session"]) is None
    ]
    budgets = []
    for point in points:
        point = dict(point)
        point["development"] = evaluate(starts, espn, recordings, score, point["threshold"], {DEV})
        point["evaluation_football"] = evaluate(starts, episodes, recordings, score, point["threshold"], eval_sessions)
        point["redzone"] = evaluate(starts, episodes, recordings, score, point["threshold"], {REDZONE})
        budgets.append(point)
    published = []
    for sid, series in cnn.items():
        if series is None:
            continue
        info = next(row for row in recordings if row["session"] == sid)
        hours = info["features"]["or"]["program_seconds"] / 3600.0
        program_eps = [row for row in episodes if row["session"] == sid and row["class"] == "program"]
        fresh = [row for row in episodes if row["session"] == sid and row["class"] == "fresh_start"]
        published.append({
            "session": sid,
            "content": info["content"],
            "program_hours": round(hours, 3),
            "published_freezes": len(series["freezes"]),
            "freezes_per_program_hour": None if hours <= 0 else round(len(series["freezes"]) / hours, 3),
            "program_episodes_with_exceedance": sum(1 for row in program_eps if row["exceed_at_available"]),
            "fresh_start_episodes_with_exceedance": sum(1 for row in fresh if row["exceed_at_available"]),
            "program_episodes": len(program_eps),
            "fresh_start_episodes": len(fresh),
        })
    counts = defaultdict(int)
    for row in episodes:
        counts[row["class"]] += 1
        if row["ongoing_start_s"] is not None:
            counts["ongoing_overlaps_start"] += 1
        if row["ongoing_end_s"] is not None:
            counts["ongoing_overlaps_end"] += 1
    # The reported taxonomy uses the 1/hour threshold, the loosest frozen budget.
    loose = next(point for point in budgets if point["budget_per_hour"] == 1.0)
    causes = residual(starts, episodes, {sid for sid, series in cnn.items() if series is not None}, score, loose["threshold"])
    cause_counts = defaultdict(int)
    for row in causes:
        cause_counts[row["cause"]] += 1
    football_ends = [row for row in ends if row["content"] == "sports" and row["eligible"] == "True"]
    end_causes = defaultdict(int)
    fresh_ends = {(row["session"], round(float(row["fresh_end_s"]), 3)) for row in episodes if row["class"] == "fresh_end" and row["fresh_end_s"] is not None}
    for row in football_ends:
        key = (row["session"], round(float(row["boundary_s"]), 3))
        if key in fresh_ends:
            end_causes["fresh_dsp_episode_no_verified_speaker"] += 1
        else:
            end_causes["no_dsp_candidate_and_no_verified_speaker"] += 1
    curve = pr_curve([row for row in episodes if row["session"] in eval_sessions], score)
    elapsed = time.perf_counter() - started
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    verdict = decide(selection, budgets)
    payload = {
        "rule": {
            "near_s": NEAR_S,
            "budgets_per_hour": list(BUDGETS),
            "development_session": DEV,
            "score_selection": "highest ESPN average precision among level, rise, ratio; 80% finite required",
            "acceptance": "score > ESPN threshold",
        },
        "episode_counts": dict(counts),
        "cnn_hashes": hashes,
        "cnn_missing_football_sessions": missing_cnn,
        "evaluation_sessions": sorted(eval_sessions),
        "score_selection": selection,
        "budgets": budgets,
        "published_cnn14_exceedance": published,
        "start_causes_at_1_per_hour": dict(cause_counts),
        "end_causes": dict(end_causes),
        "speaker_identity": {
            "verified_enrollments": 0,
            "reason": "Cluster ids, booth_present, and .booth.json were not audited on these recordings. They are not used as program-speaker evidence.",
        },
        "pr_curve_evaluation_football": curve,
        "verdict": verdict,
        "compute": {"wall_s": round(elapsed, 1), "max_rss_bytes": int(rss)},
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    with (OUT / "episodes.csv").open("w", encoding="utf-8", newline="") as handle:
        fields = [
            "session", "network", "content", "t_start", "t_end", "n_seconds", "available_at",
            "class", "fresh_start_s", "fresh_end_s", "ongoing_start_s", "ongoing_end_s",
            "rms", "flatness", "centroid", "cnn_joined", "level", "before", "rise", "ratio",
            "exceed_at_available", "freeze_within_10s", "history_n",
        ]
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(episodes)
    with (OUT / "start_causes.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["session", "boundary_s", "cause"])
        writer.writeheader()
        writer.writerows(causes)
    if curve:
        fig, ax = plt.subplots(figsize=(6.2, 4.2))
        ax.plot([row["recall"] for row in curve], [row["precision"] for row in curve], color="#222222")
        ax.set_xlabel("Recall of fresh-start episodes")
        ax.set_ylabel("Precision against program episodes")
        ax.set_title("Evaluation football, ESPN threshold not refit")
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        fig.tight_layout()
        fig.savefig(OUT / "pr_curve.png", dpi=120)
        plt.close(fig)
    print(json.dumps({"verdict": verdict, "chosen": score, "selection": selection, "budgets": [
        {"budget": point["budget_per_hour"], "k": point["espn_allowed_false_accepts"], "threshold": point["threshold"],
         "eval_fa": point["evaluation_football"]["false_accepts_per_hour"],
         "eval_recall3": point["evaluation_football"]["fraction_of_fresh_3s_candidates"],
         "eval_starts": point["evaluation_football"]["fraction_of_starts"],
         "rz_fa": point["redzone"]["redzone_false_accepts_per_hour"]}
        for point in budgets
    ]}, indent=2))


def decide(selection: dict, budgets: list[dict]) -> str:
    prevalence = selection.get("prevalence") or 0.0
    ap = selection.get("average_precision")
    if ap is None or ap < prevalence + 0.02:
        return "FAIL"
    transferred = []
    relaxed = []
    for point in budgets:
        budget = point["budget_per_hour"]
        ev = point["evaluation_football"]
        rz = point["redzone"]["redzone_false_accepts_per_hour"]
        fa = ev["false_accepts_per_hour"]
        recall = ev["fraction_of_fresh_3s_candidates"] or 0.0
        if fa is not None and rz is not None and fa <= budget and rz <= budget and recall >= 0.50:
            transferred.append(point)
        if fa is not None and fa <= 2 * budget:
            relaxed.append(recall)
    if transferred:
        return "PASS"
    if relaxed and max(relaxed) < 0.25:
        return "FAIL"
    return "INCONCLUSIVE"


if __name__ == "__main__":
    main()
