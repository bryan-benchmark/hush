"""Truth overlay and cluster audit for frozen Experiment 002.

Reads the timeline, the embedding windows, and the truth ledger.
Does not recompute embeddings, assignments, the 0.25 match threshold,
or the recurrence rule.
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
import soundfile as sf

from hush.overlay001 import commercial_breaks, shade
from hush.speaker_memory import (
    DROP_MIN,
    DROP_WINDOW_S,
    EVENT_REFRACTORY_S,
    RETURN_ABSENCE_S,
    RETURN_EVENT_MIN,
)

REPO = Path(__file__).resolve().parents[2]
SESSION = "hush_20260914_212529"
HOLDOUTS = ("hush_20260917_205513", "hush_20260920_200635")
DERIVED_WAV = REPO / "experiments" / "exp001" / "derived" / "hush_20260914_212529_0_6899_16k_mono.wav"
ANALYSIS_END = 6899.0
NAMED_CLUSTERS = ("c0001", "c0049", "c0002")
ASSIGNED_STATES = {"SPEECH_RECURRING", "SPEECH_NOVEL", "SPEECH_KNOWN_NOT_RECURRING"}


def _num(value):
    if value is None:
        return None
    if isinstance(value, (float, np.floating)):
        value = float(value)
        if not math.isfinite(value):
            return None
        return round(value, 4)
    if isinstance(value, (int, np.integer)):
        return int(value)
    return value


def _clean(obj):
    if isinstance(obj, dict):
        return {key: _clean(val) for key, val in obj.items()}
    if isinstance(obj, list):
        return [_clean(val) for val in obj]
    return _num(obj) if not isinstance(obj, str) else obj


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows([{key: _num(val) if not isinstance(val, str) else val for key, val in row.items()} for row in rows])


def _mean(values: np.ndarray) -> float | None:
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return None
    return float(np.mean(finite))


def _percentile(values: np.ndarray, q: float) -> float | None:
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return None
    return float(np.percentile(finite, q))


def drop_series(score: np.ndarray) -> np.ndarray:
    """Same drop as the unlabeled listing: current continuity versus the previous 10 s max."""
    drops = np.full(score.shape[0], np.nan)
    window = int(DROP_WINDOW_S)
    for i in range(score.shape[0]):
        if i == 0 or not math.isfinite(float(score[i])):
            continue
        prev = score[max(0, i - window) : i]
        finite = prev[np.isfinite(prev)]
        if finite.size == 0:
            continue
        drops[i] = float(np.max(finite) - score[i])
    return drops


def time_ordered_events(times: np.ndarray, values: np.ndarray, minimum: float) -> list[dict]:
    kept: list[dict] = []
    last = -1e9
    for t, value in zip(times, values):
        if not math.isfinite(float(value)) or float(value) < minimum:
            continue
        if float(t) - last <= EVENT_REFRACTORY_S:
            continue
        kept.append({"timestamp_seconds": float(t), "value": float(value)})
        last = float(t)
    return kept


def top_events(times: np.ndarray, values: np.ndarray, minimum: float, limit: int = 20) -> list[dict]:
    order = np.lexsort((times, -np.asarray(values, dtype=np.float64)))
    kept: list[dict] = []
    for idx in order:
        value = float(values[idx])
        if not math.isfinite(value) or value < minimum:
            continue
        t = float(times[idx])
        if any(abs(t - prev["timestamp_seconds"]) <= EVENT_REFRACTORY_S for prev in kept):
            continue
        kept.append({"timestamp_seconds": t, "value": value})
        if len(kept) >= limit:
            break
    kept.sort(key=lambda row: row["timestamp_seconds"])
    return kept


def _slice_mask(times: np.ndarray, start: float, end: float) -> np.ndarray:
    return (times > start) & (times <= end)


def _window_stats(frame: pd.DataFrame, start: float, end: float) -> dict:
    mask = _slice_mask(frame["timestamp_seconds"].to_numpy(dtype=float), start, end)
    chunk = frame.loc[mask]
    assigned = chunk[chunk["speech_state"].isin(ASSIGNED_STATES)]
    n_assigned = int(len(assigned))
    recurring = int(assigned["speaker_is_recurring"].sum()) if n_assigned else 0
    novel = int(assigned["speaker_is_novel"].sum()) if n_assigned else 0
    c0001 = int((assigned["speaker_cluster_id"] == "c0001").sum()) if n_assigned else 0
    return {
        "continuity_mean": _mean(chunk["program_speaker_continuity_score"].to_numpy(dtype=float)),
        "continuity_n": int(np.isfinite(chunk["program_speaker_continuity_score"].to_numpy(dtype=float)).sum()),
        "assigned_seconds": n_assigned,
        "recurring_fraction": None if n_assigned == 0 else recurring / n_assigned,
        "novel_fraction": None if n_assigned == 0 else novel / n_assigned,
        "c0001_fraction": None if n_assigned == 0 else c0001 / n_assigned,
    }


def _first_after(times: np.ndarray, values: np.ndarray, t0: float, t1: float, minimum: float) -> float | None:
    for t, value in zip(times, values):
        if t + 1e-9 < t0:
            continue
        if t > t1 + 1e-9:
            break
        if math.isfinite(float(value)) and float(value) >= minimum:
            return float(t - t0)
    return None


def _nearest_delay(event_times: list[float], boundary: float) -> float | None:
    if not event_times:
        return None
    delays = [t - boundary for t in event_times]
    return float(min(delays, key=abs))


def _in_pods(t: float, breaks: list[dict]) -> bool:
    return any(float(row["start_seconds"]) < t <= float(row["end_seconds"]) for row in breaks)


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def _added_span(row: pd.Series) -> tuple[float, float]:
    before = row["cluster_cumulative_speech_seconds"]
    if row["match_decision"] == "NOVEL" or before is None or (isinstance(before, float) and not math.isfinite(before)):
        added = float(row["duration"])
    else:
        added = max(0.0, float(row["cum_after"]) - float(before))
    end = float(row["window_end"])
    return end - added, end


def _unit(vec: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vec))
    if norm < 1e-8:
        raise ValueError("zero embedding in a frozen window")
    return vec / norm


def _centroid(matrix: np.ndarray) -> np.ndarray | None:
    if matrix.size == 0:
        return None
    return _unit(np.mean(matrix, axis=0))


def cluster_balance(windows: pd.DataFrame, breaks: list[dict]) -> list[dict]:
    totals: dict[str, dict] = {}
    for _, row in windows.iterrows():
        start, end = _added_span(row)
        if end <= start:
            continue
        inside = sum(_overlap(start, end, float(b["start_seconds"]), float(b["end_seconds"])) for b in breaks)
        cid = str(row["assigned_cluster_id"])
        bucket = totals.setdefault(
            cid,
            {"cluster_id": cid, "inside_seconds": 0.0, "outside_seconds": 0.0, "n_windows": 0, "first_seen": start, "last_seen": end},
        )
        bucket["inside_seconds"] += inside
        bucket["outside_seconds"] += (end - start) - inside
        bucket["n_windows"] += 1
        bucket["first_seen"] = min(bucket["first_seen"], float(row["window_start"]))
        bucket["last_seen"] = max(bucket["last_seen"], float(row["window_end"]))
    rows = []
    for bucket in totals.values():
        total = bucket["inside_seconds"] + bucket["outside_seconds"]
        bucket["total_seconds"] = total
        bucket["percent_inside_pods"] = None if total <= 0 else 100.0 * bucket["inside_seconds"] / total
        rows.append(bucket)
    rows.sort(key=lambda item: (-item["total_seconds"], item["cluster_id"]))
    return rows


def cluster_integrity(windows: pd.DataFrame, focus_ids: list[str]) -> list[dict]:
    """Describe the frozen assignments. Membership is not recomputed."""
    ordered = windows.sort_values(["window_end", "window_start"])
    embeddings = np.vstack([np.asarray(vec, dtype=np.float64) for vec in ordered["embedding"]])
    ids = ordered["assigned_cluster_id"].astype(str).tolist()
    decisions = ordered["match_decision"].astype(str).tolist()
    stored = ordered["similarity_to_best_known"].to_numpy(dtype=float)
    protos: dict[str, np.ndarray] = {}
    counts: dict[str, int] = {}
    margins: dict[str, list[float]] = {cid: [] for cid in focus_ids}
    proto_path: dict[str, list[np.ndarray]] = {cid: [] for cid in focus_ids}
    seen_focus = {cid: 0 for cid in focus_ids}
    focus_n = ordered["assigned_cluster_id"].astype(str).value_counts().to_dict()
    replay_gap: list[float] = []
    for emb, cid, decision, stored_sim in zip(embeddings, ids, decisions, stored):
        emb = _unit(emb)
        sims = {pid: float(np.dot(emb, proto)) for pid, proto in protos.items()}
        if decision == "MATCH" and cid in sims:
            others = [sim for pid, sim in sims.items() if pid != cid]
            if others:
                margins.setdefault(cid, []).append(sims[cid] - max(others))
            if math.isfinite(stored_sim):
                replay_gap.append(abs(sims[cid] - float(stored_sim)))
        if cid not in protos:
            protos[cid] = emb.copy()
            counts[cid] = 1
        else:
            protos[cid] = _unit(protos[cid] * counts[cid] + emb)
            counts[cid] += 1
        if cid in proto_path:
            seen_focus[cid] += 1
            span = max(1, int(focus_n.get(cid, 1)))
            if seen_focus[cid] in {max(1, span // 5), max(1, 2 * span // 5), max(1, 3 * span // 5), max(1, 4 * span // 5), span}:
                proto_path[cid].append(protos[cid].copy())

    rows = []
    for cid in focus_ids:
        chosen = ordered[ordered["assigned_cluster_id"] == cid]
        matrix = np.vstack([_unit(np.asarray(vec, dtype=np.float64)) for vec in chosen["embedding"]])
        final = _centroid(matrix)
        to_final = matrix @ final if final is not None else np.array([])
        matched = chosen[chosen["match_decision"] == "MATCH"]["similarity_to_best_known"].to_numpy(dtype=float)
        n = len(chosen)
        early_late = None
        quintile_to_first: list[float | None] = []
        if n >= 10 and final is not None:
            k = max(1, n // 5)
            early = _centroid(matrix[:k])
            late = _centroid(matrix[-k:])
            early_late = float(np.dot(early, late))
            for q in range(5):
                block = matrix[q * k : (q + 1) * k] if q < 4 else matrix[q * k :]
                center = _centroid(block)
                first = _centroid(matrix[:k])
                quintile_to_first.append(None if center is None or first is None else float(np.dot(center, first)))
        margin = np.asarray(margins.get(cid, []), dtype=np.float64)
        path = proto_path.get(cid, [])
        path_cosine = []
        if path:
            path_cosine = [1.0] + [float(np.dot(path[0], later)) for later in path[1:]]
        rows.append(
            {
                "cluster_id": cid,
                "n_windows": n,
                "match_cosine_p10": _percentile(matched, 10),
                "match_cosine_p50": _percentile(matched, 50),
                "match_cosine_p90": _percentile(matched, 90),
                "cosine_to_final_centroid_p10": _percentile(to_final, 10),
                "cosine_to_final_centroid_p50": _percentile(to_final, 50),
                "cosine_to_final_centroid_p90": _percentile(to_final, 90),
                "cosine_to_final_centroid_min": None if to_final.size == 0 else float(np.min(to_final)),
                "min_cosine_window_end": None if to_final.size == 0 else float(chosen["window_end"].to_numpy(dtype=float)[int(np.argmin(to_final))]),
                "early_vs_late_centroid_cosine": early_late,
                "quintile_cosine_to_first": quintile_to_first,
                "causal_prototype_cosine_to_first_quintile": path_cosine,
                "margin_p10": _percentile(margin, 10),
                "margin_p50": _percentile(margin, 50),
                "n_margin": int(margin.size),
            }
        )
    replay = {
        "n_compared": len(replay_gap),
        "median_abs_diff_vs_stored_similarity": None if not replay_gap else float(np.median(replay_gap)),
        "max_abs_diff_vs_stored_similarity": None if not replay_gap else float(np.max(replay_gap)),
    }
    return rows, replay


def _pick_excerpts(cluster_windows: pd.DataFrame, n: int = 5, min_gap: float = 600.0) -> list[pd.Series]:
    ordered = cluster_windows.sort_values("window_start")
    if ordered.empty:
        return []
    start = float(ordered["window_start"].iloc[0])
    end = float(ordered["window_start"].iloc[-1])
    targets = np.linspace(start, end, n)
    chosen: list[pd.Series] = []
    used: set[int] = set()
    for target in targets:
        distances = (ordered["window_start"] - target).abs()
        for idx in distances.sort_values().index:
            if idx in used:
                continue
            row = ordered.loc[idx]
            if all(abs(float(row["window_start"]) - float(prev["window_start"])) >= min_gap for prev in chosen):
                chosen.append(row)
                used.add(idx)
                break
    chosen.sort(key=lambda row: float(row["window_start"]))
    return chosen


def _clip_end(cluster_windows: pd.DataFrame, seed: pd.Series, limit: float = 5.0) -> tuple[float, float]:
    start = float(seed["window_start"])
    end = float(seed["window_end"])
    ordered = cluster_windows.sort_values("window_start")
    for _, row in ordered.iterrows():
        row_start = float(row["window_start"])
        if row_start < end - 0.05:
            continue
        if row_start > end + 0.25:
            break
        end = max(end, float(row["window_end"]))
        if end - start >= limit:
            return start, start + limit
    return start, min(end, start + limit)


def export_excerpts(windows: pd.DataFrame, wav_path: Path, dest: Path) -> list[dict]:
    info = sf.info(wav_path)
    rows = []
    dest.mkdir(parents=True, exist_ok=True)
    for cid in ("c0001", "c0049"):
        cluster = windows[windows["assigned_cluster_id"] == cid]
        for index, seed in enumerate(_pick_excerpts(cluster), start=1):
            start, end = _clip_end(cluster, seed)
            i0 = max(0, int(round(start * info.samplerate)))
            i1 = min(info.frames, int(round(end * info.samplerate)))
            audio, sr = sf.read(wav_path, start=i0, frames=i1 - i0, dtype="float32")
            name = f"{cid}_{index:02d}.wav"
            sf.write(dest / name, audio, sr, subtype="PCM_16")
            rows.append(
                {
                    "file": name,
                    "cluster_id": cid,
                    "excerpt_index": index,
                    "start_seconds": start,
                    "end_seconds": end,
                    "embedding_id": seed["embedding_id"],
                    "window_similarity": seed["similarity_to_best_known"],
                    "selection": "spread across this cluster's own timeline; commercial labels were not used",
                }
            )
    return rows


def _latency_to_cluster(windows: pd.DataFrame, cid: str, t: float) -> dict:
    cluster = windows[windows["assigned_cluster_id"] == cid]
    before = cluster[cluster["window_end"] <= t]
    after = cluster[cluster["window_end"] > t]
    if before.empty:
        return {"observed_before": False, "latency_seconds": None, "window_end": None}
    if after.empty:
        return {"observed_before": True, "latency_seconds": None, "window_end": None}
    window_end = float(after["window_end"].iloc[0])
    return {"observed_before": True, "latency_seconds": window_end - t, "window_end": window_end}


def _plots(frame: pd.DataFrame, windows: pd.DataFrame, breaks: list[dict], balance: list[dict], dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    minutes = frame["timestamp_seconds"].to_numpy(dtype=float) / 60.0
    fig, axes = plt.subplots(5, 1, figsize=(14, 12), sharex=True)
    for ax in axes:
        shade(ax, breaks)
    axes[0].plot(minutes, frame["speech_active"], color="0.2", lw=0.6, zorder=2)
    axes[0].set_ylabel("speech")
    axes[1].plot(minutes, frame["speaker_is_recurring"], color="tab:blue", lw=0.6, zorder=2)
    axes[1].set_ylabel("recurring")
    axes[2].plot(minutes, frame["speaker_is_novel"], color="tab:orange", lw=0.6, zorder=2)
    axes[2].set_ylabel("novel")
    axes[3].plot(minutes, np.ma.masked_invalid(frame["program_speaker_continuity_score"]), color="tab:purple", lw=0.7, zorder=2)
    axes[3].set_ylabel("continuity")
    axes[3].set_ylim(-0.05, 1.05)
    axes[4].plot(minutes, np.ma.masked_invalid(frame["seconds_since_any_recurring_speaker"]), color="tab:green", lw=0.7, zorder=2)
    axes[4].set_ylabel("sec since recurring")
    axes[4].set_xlabel("minutes")
    axes[0].legend(loc="upper right", fontsize=7)
    fig.suptitle("Exp002 speaker continuity with commercial labels")
    fig.tight_layout()
    fig.savefig(dest / "speaker_continuity.png", dpi=120)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(14, 6))
    shade(ax, breaks)
    x = windows["window_end"].to_numpy(dtype=float) / 60.0
    y = windows["assigned_cluster_id"].astype(str).str[1:].astype(int)
    recurring = windows["speaker_is_recurring"].to_numpy(dtype=bool)
    ax.scatter(x[~recurring], y[~recurring], s=6, c="0.75", linewidths=0, label="not yet recurring", zorder=2)
    ax.scatter(x[recurring], y[recurring], s=8, c="tab:blue", linewidths=0, label="already recurring", zorder=2)
    ax.legend(loc="upper right")
    ax.set_xlabel("minutes")
    ax.set_ylabel("cluster (discovery order)")
    ax.set_title("Exp002 clusters with commercial labels")
    fig.tight_layout()
    fig.savefig(dest / "speaker_clusters.png", dpi=120)
    plt.close(fig)

    fig, axes = plt.subplots(4, 1, figsize=(14, 10), sharex=True)
    for ax in axes:
        shade(ax, breaks)
    axes[0].plot(minutes, frame["unique_speaker_clusters_30s"], color="0.2", lw=0.7, zorder=2)
    axes[0].set_ylabel("unique / 30s")
    axes[1].plot(minutes, np.ma.masked_invalid(frame["speaker_cluster_entropy_30s"]), color="tab:blue", lw=0.7, zorder=2)
    axes[1].set_ylabel("entropy")
    axes[2].plot(minutes, frame["speaker_turnover_rate_30s"], color="tab:orange", lw=0.7, zorder=2)
    axes[2].set_ylabel("switches / 30s")
    axes[3].plot(minutes, np.ma.masked_invalid(frame["novel_speaker_fraction_30s"]), color="tab:red", lw=0.7, zorder=2)
    axes[3].set_ylabel("novel fraction")
    axes[3].set_xlabel("minutes")
    axes[3].set_ylim(-0.05, 1.05)
    axes[0].legend(loc="upper right", fontsize=7)
    fig.suptitle("Exp002 speaker turnover with commercial labels")
    fig.tight_layout()
    fig.savefig(dest / "speaker_turnover.png", dpi=120)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(14, 4))
    shade(ax, breaks)
    ax.plot(minutes, frame["program_speaker_return_score"], color="tab:green", lw=0.7, zorder=2)
    ax.set_xlabel("minutes")
    ax.set_ylabel("return score")
    ax.set_title("Exp002 return score with commercial labels")
    ax.legend(loc="upper right", fontsize=7)
    fig.tight_layout()
    fig.savefig(dest / "speaker_returns.png", dpi=120)
    plt.close(fig)

    top = balance[:15]
    fig, ax = plt.subplots(figsize=(10, 6))
    labels = [row["cluster_id"] for row in top][::-1]
    percents = [0.0 if row["percent_inside_pods"] is None else row["percent_inside_pods"] for row in top][::-1]
    ax.barh(labels, percents, color="0.45")
    ax.set_xlabel("percent of this cluster's attributed speech inside commercial pods")
    ax.set_xlim(0, 100)
    ax.set_title("Frozen clusters vs commercial pods (descriptive)")
    fig.tight_layout()
    fig.savefig(dest / "cluster_pod_balance.png", dpi=120)
    plt.close(fig)


def cluster_absence_returns(windows: pd.DataFrame, cid: str, breaks: list[dict]) -> dict:
    """Reappearances of one frozen cluster after the frozen 30 s absence. Not a new rule."""
    cluster = windows[windows["assigned_cluster_id"] == cid].sort_values("window_end")
    events = []
    previous = None
    for _, row in cluster.iterrows():
        if previous is not None and float(row["window_start"]) - previous >= RETURN_ABSENCE_S:
            events.append(float(row["window_end"]))
        previous = float(row["window_end"])
    near = []
    in_pod = []
    program = []
    for t in events:
        if any(0.0 <= t - float(b["end_seconds"]) <= 10.0 for b in breaks):
            near.append(t)
        elif _in_pods(t, breaks):
            in_pod.append(t)
        else:
            program.append(t)
    return {
        "cluster_id": cid,
        "absence_seconds": RETURN_ABSENCE_S,
        "n_reappearances": len(events),
        "within_10s_after_a_true_return": len(near),
        "inside_pods": len(in_pod),
        "in_program": len(program),
    }


def _event_split(events: list[dict], breaks: list[dict], near_ends: bool) -> dict:
    in_pod = [event for event in events if _in_pods(event["timestamp_seconds"], breaks)]
    if near_ends:
        near = []
        for event in events:
            t = event["timestamp_seconds"]
            if any(0 <= t - float(row["end_seconds"]) <= 10.0 for row in breaks):
                near.append(event)
        program = [
            event
            for event in events
            if event not in in_pod and event not in near
        ]
        return {"in_pods": len(in_pod), "within_10s_after_a_return": len(near), "in_program": len(program)}
    program = [event for event in events if not _in_pods(event["timestamp_seconds"], breaks)]
    return {"in_pods": len(in_pod), "in_program": len(program)}


def run(timeline_path: Path, segments_path: Path, output: Path, session: str, wav_path: Path) -> dict:
    if session in HOLDOUTS:
        raise SystemExit(f"refusing sealed holdout {session}")
    frame = pd.read_parquet(timeline_path)
    segments = pd.read_parquet(segments_path)
    windows = segments[segments["row_kind"] == "embedding_window"].sort_values(["window_end", "window_start"]).reset_index(drop=True)
    breaks = commercial_breaks(session)
    times = frame["timestamp_seconds"].to_numpy(dtype=float)
    continuity = frame["program_speaker_continuity_score"].to_numpy(dtype=float)
    drops = drop_series(continuity)
    returns = frame["program_speaker_return_score"].to_numpy(dtype=float)

    collapse_top = top_events(times, drops, DROP_MIN, 20)
    return_top = top_events(times, returns, RETURN_EVENT_MIN, 20)
    collapse_all = time_ordered_events(times, drops, DROP_MIN)
    return_all = time_ordered_events(times, returns, RETURN_EVENT_MIN)
    collapse_times = [event["timestamp_seconds"] for event in collapse_top]
    return_times = [event["timestamp_seconds"] for event in return_top]

    break_rows = []
    for index, row in enumerate(breaks, start=1):
        start = float(row["start_seconds"])
        end = float(row["end_seconds"])
        pre = _window_stats(frame, start - 30.0, start)
        early = _window_stats(frame, start, start + 5.0)
        mid = _window_stats(frame, start + 5.0, start + 15.0)
        late = _window_stats(frame, start + 15.0, start + 30.0)
        pod = _window_stats(frame, start, end)
        before_times = times[times <= start]
        dominant = None
        if before_times.size:
            dominant = frame.loc[frame["timestamp_seconds"] == before_times[-1], "dominant_recurring_cluster_id"]
            dominant = None if dominant.empty else dominant.iloc[0]
            if dominant is not None and (isinstance(dominant, float) and not math.isfinite(dominant)):
                dominant = None
            if pd.isna(dominant):
                dominant = None
        latency = _first_after(times, drops, start, end, DROP_MIN)
        break_rows.append(
            {
                "break_index": index,
                "gold_id": row.get("gold_id"),
                "start_seconds": start,
                "end_seconds": end,
                "duration_seconds": end - start,
                "continuity_pre_30": pre["continuity_mean"],
                "continuity_0_5": early["continuity_mean"],
                "continuity_5_15": mid["continuity_mean"],
                "continuity_15_30": late["continuity_mean"],
                "recurring_fraction_pre_30": pre["recurring_fraction"],
                "recurring_fraction_0_5": early["recurring_fraction"],
                "recurring_fraction_5_15": mid["recurring_fraction"],
                "recurring_fraction_15_30": late["recurring_fraction"],
                "recurring_fraction_during_pod": pod["recurring_fraction"],
                "novel_fraction_during_pod": pod["novel_fraction"],
                "c0001_fraction_pre_30": pre["c0001_fraction"],
                "c0001_fraction_during_pod": pod["c0001_fraction"],
                "assigned_seconds_during_pod": pod["assigned_seconds"],
                "latency_to_collapse_seconds": latency,
                "collapse_within_15s": latency is not None and latency <= 15.0,
                "nearest_top20_drop_delay_seconds": _nearest_delay(collapse_times, start),
                "dominant_cluster_before_break": None if dominant is None else str(dominant),
            }
        )

    return_rows = []
    for index, row in enumerate(breaks, start=1):
        start = float(row["start_seconds"])
        end = float(row["end_seconds"])
        before = next(item["dominant_cluster_before_break"] for item in break_rows if item["break_index"] == index)
        any_recurring = windows[(windows["window_end"] > end) & (windows["speaker_is_recurring"] == True)]  # noqa: E712
        if any_recurring.empty:
            any_latency = None
            any_cluster = None
        else:
            first = any_recurring.iloc[0]
            any_latency = float(first["window_end"]) - end
            any_cluster = str(first["assigned_cluster_id"])
        named = {cid: _latency_to_cluster(windows, cid, end) for cid in NAMED_CLUSTERS}
        dominant_latency = None if before is None else _latency_to_cluster(windows, before, end)
        return_rows.append(
            {
                "break_index": index,
                "gold_id": row.get("gold_id"),
                "return_seconds": end,
                "latency_any_recurring_seconds": any_latency,
                "first_recurring_cluster": any_cluster,
                "latency_c0001_seconds": named["c0001"]["latency_seconds"],
                "c0001_observed_before_return": named["c0001"]["observed_before"],
                "latency_c0049_seconds": named["c0049"]["latency_seconds"],
                "c0049_observed_before_return": named["c0049"]["observed_before"],
                "latency_c0002_seconds": named["c0002"]["latency_seconds"],
                "c0002_observed_before_return": named["c0002"]["observed_before"],
                "dominant_cluster_before_break": before,
                "latency_dominant_before_break_seconds": None if dominant_latency is None else dominant_latency["latency_seconds"],
                "nearest_top20_return_delay_seconds": _nearest_delay(return_times, end),
                "return_event_within_10s": any(0.0 <= event["timestamp_seconds"] - end <= 10.0 for event in return_all),
                "c0001_within_10s": named["c0001"]["latency_seconds"] is not None and named["c0001"]["latency_seconds"] <= 10.0,
                "dominant_within_10s": (
                    dominant_latency is not None
                    and dominant_latency["latency_seconds"] is not None
                    and dominant_latency["latency_seconds"] <= 10.0
                ),
                "any_recurring_within_10s": any_latency is not None and any_latency <= 10.0,
                "top20_return_within_10s": (
                    _nearest_delay(return_times, end) is not None and abs(_nearest_delay(return_times, end)) <= 10.0
                ),
            }
        )

    balance = cluster_balance(windows, breaks)
    focus = []
    for cid in list(NAMED_CLUSTERS) + [row["cluster_id"] for row in balance[:15]]:
        if cid not in focus:
            focus.append(cid)
    integrity, replay = cluster_integrity(windows, focus)
    excerpts = export_excerpts(windows, wav_path, output / "excerpts")

    pod_seconds = sum(float(row["end_seconds"]) - float(row["start_seconds"]) for row in breaks)
    program_seconds = ANALYSIS_END - pod_seconds
    named_returns = [cluster_absence_returns(windows, cid, breaks) for cid in NAMED_CLUSTERS]
    collapse_split = _event_split(collapse_all, breaks, near_ends=False)
    return_split = _event_split(return_all, breaks, near_ends=True)

    def per_hour(count: int, seconds: float) -> float | None:
        if seconds <= 0:
            return None
        return count / (seconds / 3600.0)

    _plots(frame, windows, breaks, balance, output / "plots_labeled")
    _write_csv(output / "overlay_breaks.csv", break_rows)
    _write_csv(output / "overlay_returns.csv", return_rows)
    _write_csv(output / "cluster_pod_balance.csv", balance)
    integrity_csv = []
    for row in integrity:
        flat = dict(row)
        quintiles = flat.pop("quintile_cosine_to_first")
        for q, value in enumerate(quintiles, start=1):
            flat[f"quintile_{q}_cosine_to_first"] = value
        causal = flat.pop("causal_prototype_cosine_to_first_quintile")
        for q, value in enumerate(causal, start=1):
            flat[f"causal_prototype_quintile_{q}"] = value
        integrity_csv.append(flat)
    _write_csv(output / "cluster_integrity.csv", integrity_csv)
    _write_csv(output / "excerpts" / "manifest.csv", excerpts)

    named_balance = [row for row in balance if row["cluster_id"] in NAMED_CLUSTERS or balance.index(row) < 15]
    summary = {
        "experiment_spec_version": "exp002-v1",
        "parameters_changed": False,
        "embeddings_recomputed": False,
        "assignments_recomputed": False,
        "session": session,
        "n_breaks": len(breaks),
        "collapse_definition": (
            f"continuity at least {DROP_MIN} below the max of the previous {int(DROP_WINDOW_S)} seconds. "
            "Those constants are the frozen unlabeled listing parameters."
        ),
        "return_event_definition": (
            f"program_speaker_return_score >= {RETURN_EVENT_MIN}, the frozen unlabeled listing minimum."
        ),
        "refractory_seconds": EVENT_REFRACTORY_S,
        "pod_seconds": pod_seconds,
        "program_seconds": program_seconds,
        "starts_with_collapse_within_15s": int(sum(row["collapse_within_15s"] for row in break_rows)),
        "starts_within_15s_of_a_top20_drop": int(
            sum(
                row["nearest_top20_drop_delay_seconds"] is not None and abs(row["nearest_top20_drop_delay_seconds"]) <= 15.0
                for row in break_rows
            )
        ),
        "median_collapse_latency_seconds": _percentile(
            np.asarray([row["latency_to_collapse_seconds"] if row["latency_to_collapse_seconds"] is not None else np.nan for row in break_rows]),
            50,
        ),
        "returns_with_a_time_ordered_return_event_within_10s": int(sum(row["return_event_within_10s"] for row in return_rows)),
        "returns_within_10s_of_a_top20_return": int(sum(row["top20_return_within_10s"] for row in return_rows)),
        "returns_c0001_within_10s": int(sum(row["c0001_within_10s"] for row in return_rows)),
        "returns_dominant_before_break_within_10s": int(sum(row["dominant_within_10s"] for row in return_rows)),
        "returns_any_recurring_within_10s": int(sum(row["any_recurring_within_10s"] for row in return_rows)),
        "collapse_events_time_ordered": {
            **collapse_split,
            "per_hour_in_pods": per_hour(collapse_split["in_pods"], pod_seconds),
            "per_hour_in_program": per_hour(collapse_split["in_program"], program_seconds),
        },
        "named_cluster_reappearances_after_30s": named_returns,
        "return_events_time_ordered": {
            **return_split,
            "per_hour_in_program": per_hour(return_split["in_program"], program_seconds),
            "post_return_window_seconds": 150.0,
        },
        "named_and_top_clusters": named_balance,
        "cluster_integrity": integrity,
        "prototype_replay_check": replay,
        "excerpt_note": "Five clips each from c0001 and c0049, spread across that cluster's own times. Labels were not used to choose them.",
        "breaks": break_rows,
        "returns": return_rows,
    }
    (output / "overlay_summary.json").write_text(json.dumps(_clean(summary), indent=2) + "\n", encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Overlay frozen Experiment 002 with commercial truth")
    root = REPO / "experiments" / "exp002" / SESSION
    parser.add_argument("--timeline", type=Path, default=root / "speaker_timeline.parquet")
    parser.add_argument("--segments", type=Path, default=root / "speaker_segments.parquet")
    parser.add_argument("--output", type=Path, default=root)
    parser.add_argument("--wav", type=Path, default=DERIVED_WAV)
    parser.add_argument("--session", default=SESSION)
    args = parser.parse_args(argv)
    summary = run(args.timeline, args.segments, args.output, args.session, args.wav)
    brief = {
        key: summary[key]
        for key in (
            "n_breaks",
            "starts_with_collapse_within_15s",
            "starts_within_15s_of_a_top20_drop",
            "median_collapse_latency_seconds",
            "returns_within_10s_of_a_top20_return",
            "returns_c0001_within_10s",
            "returns_dominant_before_break_within_10s",
            "returns_any_recurring_within_10s",
            "collapse_events_time_ordered",
            "return_events_time_ordered",
            "prototype_replay_check",
        )
    }
    print(json.dumps(_clean(brief), indent=2))


if __name__ == "__main__":
    main()
