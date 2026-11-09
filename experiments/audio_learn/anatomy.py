"""Read the frozen model's existing scores. Does not train or move a threshold.

The Prime games are a regression benchmark. This file only describes the
program seconds the already-chosen controller covered.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from experiments.audio_learn.controller import decisions
from experiments.audio_learn.encoder import DATA_ROOT
from experiments.audio_learn.splits import EVAL, HOP_S, TRAIN
from experiments.nfl75.inventory import active_intervals, coverage_by_session, excluded_ranges
from experiments.nfl75.score import playback_from_decisions, score_product
from experiments.measurement.metrics import target_commercials

FROZEN = {"on": 0.90, "off": 0.50, "on_streak": 8, "off_streak": 2}
PRED = DATA_ROOT / "predictions" / "frozen"
EMB = DATA_ROOT / "embeddings" / "frozen"


def _pred(session: str) -> dict:
    data = np.load(PRED / f"{session}.npz")
    return {
        "t": data["t"].astype(np.float64),
        "p": data["p"].astype(np.float64),
        "label": data["label"].astype(np.int8),
    }


def _emb(session: str) -> np.ndarray:
    data = np.load(EMB / f"{session}.npz")
    return data["emb"].astype(np.float32)


def _cover_started_in_ad(spans, episode_start: float, ads: list[tuple[float, float]]) -> bool:
    """True when this program cover is the tail of a mute that opened during a commercial."""
    covered = [span for span in spans if span.state == "covered"]
    if not covered:
        return False
    host = None
    for span in covered:
        if span.start - 1e-6 <= episode_start < span.end:
            host = span
            break
    if host is None:
        return False
    cursor = host
    changed = True
    while changed:
        changed = False
        for span in covered:
            if abs(span.end - cursor.start) <= 1e-3 and span.start < cursor.start:
                cursor = span
                changed = True
                break
    return any(a0 <= cursor.start < a1 for a0, a1 in ads)


def _near_ad(start: float, end: float, ads: list[tuple[float, float]]) -> float | None:
    best = None
    for a0, a1 in ads:
        if end > a0 and start < a1:
            return 0.0
        gap = min(abs(start - a1), abs(end - a0), abs(start - a0), abs(end - a1))
        best = gap if best is None else min(best, gap)
    return best


def _slice_stats(times: np.ndarray, probs: np.ndarray, start: float, end: float) -> dict:
    mask = (times >= start) & (times < end)
    chosen = probs[mask]
    if chosen.size == 0:
        return {"hops": 0}
    return {
        "hops": int(chosen.size),
        "p_median": float(np.median(chosen)),
        "p_min": float(chosen.min()),
        "share_at_least_0.90": float(np.mean(chosen >= 0.90)),
        "share_above_0.50": float(np.mean(chosen > 0.50)),
    }


def episode_table(session: str) -> dict:
    pred = _pred(session)
    coverage = coverage_by_session()[session]
    intervals = active_intervals(session)
    rows = decisions(pred["t"].tolist(), pred["p"].tolist(), **FROZEN)
    spans = playback_from_decisions(coverage, rows)
    scored = score_product(
        coverage,
        intervals,
        spans,
        session=session,
        excluded_ranges=excluded_ranges(session, intervals),
        audio_present=True,
    )
    ads = target_commercials(intervals)
    episodes = []
    for episode in scored["episodes"]:
        start, end = float(episode["start_s"]), float(episode["end_s"])
        stats = _slice_stats(pred["t"], pred["p"], start, end)
        began_in_ad = _cover_started_in_ad(spans, start, ads)
        episodes.append(
            {
                "session": session,
                "start_s": start,
                "end_s": end,
                "program_s": float(episode["duration_s"]),
                "gap_to_commercial_s": _near_ad(start, end, ads),
                "cover_began_inside_commercial": began_in_ad,
                **stats,
            }
        )
    program_high = 0.0
    for t, p, label in zip(pred["t"], pred["p"], pred["label"]):
        if label == 0 and p >= 0.90:
            program_high += HOP_S
    cold = []
    for a0, a1 in ads:
        mask = (pred["t"] >= a0) & (pred["t"] < a1) & (pred["p"] < 0.50)
        if not np.any(mask):
            continue
        idx = np.flatnonzero(mask)
        run_start = idx[0]
        prev = idx[0]
        for i in idx[1:]:
            if i == prev + 1:
                prev = i
                continue
            cold.append(_cold_row(session, pred, run_start, prev, a0, a1))
            run_start = prev = i
        cold.append(_cold_row(session, pred, run_start, prev, a0, a1))
    return {
        "session": session,
        "commercial_s": scored["commercial_s"],
        "commercial_covered_s": scored["commercial_covered_s"],
        "program_s": scored["program_s"],
        "program_covered_s": scored["program_covered_s"],
        "false_mute_episodes": scored["false_mute_episodes"],
        "program_seconds_with_p_at_least_0.90": program_high,
        "episodes": episodes,
        "commercial_cold_runs": cold,
    }


def _cold_row(session: str, pred: dict, i0: int, i1: int, a0: float, a1: float) -> dict:
    start = float(pred["t"][i0])
    end = float(pred["t"][i1]) + HOP_S
    return {
        "session": session,
        "start_s": start,
        "end_s": min(end, a1),
        "seconds": min(end, a1) - start,
        "commercial_start_s": a0,
        "commercial_end_s": a1,
        "p_median": float(np.median(pred["p"][i0 : i1 + 1])),
    }


def _unit(matrix: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(matrix, axis=1, keepdims=True)
    norm = np.maximum(norm, 1e-8)
    return matrix / norm


def train_bank() -> dict:
    vectors = []
    labels = []
    sessions = []
    times = []
    for session in TRAIN:
        data = np.load(EMB / f"{session}.npz")
        emb = data["emb"].astype(np.float32)
        label = data["label"].astype(np.int8)
        clock = data["t"].astype(np.float64)
        keep = label >= 0
        vectors.append(emb[keep])
        labels.append(label[keep])
        sessions.append(np.full(int(keep.sum()), session, dtype=object))
        times.append(clock[keep])
    return {
        "emb": _unit(np.concatenate(vectors)),
        "label": np.concatenate(labels),
        "session": np.concatenate(sessions),
        "t": np.concatenate(times),
    }


def neighbors(bank: dict, session: str, moment: float, k: int = 5) -> list[dict]:
    data = np.load(EMB / f"{session}.npz")
    clock = data["t"].astype(np.float64)
    index = int(np.argmin(np.abs(clock - moment)))
    query = _unit(data["emb"][index : index + 1].astype(np.float32))
    order = np.argpartition(bank["emb"] @ query[0], -k)[-k:]
    order = order[np.argsort((bank["emb"][order] @ query[0]))[::-1]]
    rows = []
    for item in order:
        rows.append(
            {
                "session": str(bank["session"][item]),
                "t": float(bank["t"][item]),
                "label": "commercial" if int(bank["label"][item]) == 1 else "program",
                "cosine": float(bank["emb"][item] @ query[0]),
            }
        )
    return rows


def main() -> None:
    tables = [episode_table(session) for session in EVAL]
    bank = train_bank()
    ranked = sorted(
        (episode for table in tables for episode in table["episodes"]),
        key=lambda row: row["program_s"],
        reverse=True,
    )
    for episode in ranked:
        mid = (episode["start_s"] + episode["end_s"]) / 2
        episode["train_neighbors_at_midpoint"] = neighbors(bank, episode["session"], mid)
    cold = sorted(
        (row for table in tables for row in table["commercial_cold_runs"] if row["seconds"] >= 8),
        key=lambda row: row["seconds"],
        reverse=True,
    )
    payload = {
        "controller": FROZEN,
        "note": "Reads the frozen probability streams. Does not refit or move the ESPN-chosen controller.",
        "games": [
            {key: value for key, value in table.items() if key not in {"episodes", "commercial_cold_runs", "program_regions"}}
            for table in tables
        ],
        "episodes_by_program_seconds": ranked,
        "commercial_cold_runs_at_least_8s": cold[:12],
    }
    out = DATA_ROOT / "anatomy" / "frozen_false_mutes.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    harmed = sum(row["program_s"] for row in ranked)
    high = sum((row.get("share_at_least_0.90") or 0) * row["program_s"] for row in ranked)
    began = sum(row["program_s"] for row in ranked if row["cover_began_inside_commercial"])
    close = sum(row["program_s"] for row in ranked if (row["gap_to_commercial_s"] or 99) <= 5)
    commercial_neighbors = 0
    neighbor_seconds = 0.0
    for row in ranked:
        votes = [item["label"] for item in row["train_neighbors_at_midpoint"]]
        if votes and votes.count("commercial") >= 3:
            commercial_neighbors += 1
            neighbor_seconds += row["program_s"]
    print(
        json.dumps(
            {
                "episodes": len(ranked),
                "program_s": round(harmed, 1),
                "approx_seconds_while_p_ge_0.90": round(high, 1),
                "program_s_cover_began_in_commercial": round(began, 1),
                "program_s_within_5s_of_a_commercial": round(close, 1),
                "episodes_whose_midpoint_neighbors_are_mostly_commercial": commercial_neighbors,
                "program_s_those_episodes": round(neighbor_seconds, 1),
                "longest": [
                    {
                        "session": row["session"][-6:],
                        "start": round(row["start_s"], 1),
                        "program_s": round(row["program_s"], 1),
                        "p_median": None if row.get("p_median") is None else round(row["p_median"], 3),
                        "share_0.90": None if row.get("share_at_least_0.90") is None else round(row["share_at_least_0.90"], 2),
                        "gap_s": None if row["gap_to_commercial_s"] is None else round(row["gap_to_commercial_s"], 1),
                        "from_ad": row["cover_began_inside_commercial"],
                        "neighbors": [item["label"][0] + f"{item['cosine']:.2f}" for item in row["train_neighbors_at_midpoint"]],
                    }
                    for row in ranked[:12]
                ],
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
