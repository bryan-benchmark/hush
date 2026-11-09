"""Refit the frozen GRU head with verified studio program from the training games.

The encoder, the controller, the frozen checkpoint, and the Prime tapes stay
where they are. Prime is scored afterward as a regression, on the original gold.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

from experiments.audio_learn.controller import decisions, recovery_rate
from experiments.audio_learn.encoder import DATA_ROOT
from experiments.audio_learn.extract import load_cache
from experiments.audio_learn.head import CausalHead, load_head, probabilities, save_head
from experiments.audio_learn.splits import (
    CALIBRATE,
    EVAL,
    HIDDEN,
    HOP_S,
    SEED,
    SEQUENCE,
    TRAIN,
    assert_split,
)
from experiments.audio_learn.train_head import _batch, _indexes
from experiments.audio_learn.windows import consecutive_end_indices
from experiments.measurement.metrics import Interval
from experiments.nfl75.inventory import (
    active_intervals,
    coverage_by_session,
    excluded_ranges,
    wall_gaps,
)
from experiments.nfl75.score import aggregate, playback_from_decisions, score_product
from tools.gpu_lab.splits import HOLDOUTS

EPOCHS = 8
PER_CLASS = 4000
BATCH = 64
STUDIO_SHARE = 0.25
CONTROLLER = {"on": 0.90, "off": 0.50, "on_streak": 8, "off_streak": 2}
HEAD_PATH = DATA_ROOT / "checkpoints" / "studio_head.pt"
SPANS_PATH = DATA_ROOT / "studio_survey" / "verified_spans.json"
OUT_DIR = DATA_ROOT / "studio_head"

# Desk and feature stretches named by the listening pass. Regression diagnostic
# only. They are not training targets and they do not change the gold.
DESK_SPANS = {
    "hush_20260924_220624": [
        (3647.0, 3652.5),
        (5026.8, 5046.5),
        (5518.7, 5526.3),
        (6180.7, 6207.8),
        (6267.8, 6287.2),
        (6315.2, 6336.5),
        (6599.5, 6605.7),
        (6614.0, 6629.2),
        (6734.0, 6739.8),
        (6836.2, 6844.5),
        (7035.0, 7095.2),
        (7370.2, 7379.8),
        (7406.8, 7436.2),
        (7491.8, 7515.4),
    ],
    "hush_20261008_205100": [
        (376.9, 386.2),
        (1749.8, 1760.8),
        (3434.0, 3443.0),
    ],
}


def _in_spans(moment: float, spans: list[tuple[float, float]]) -> bool:
    return any(start <= moment < end for start, end in spans)


def _studio_indexes(caches: list[dict], sessions: tuple[str, ...], spans: dict[str, list[tuple[float, float]]]) -> list[tuple[int, int]]:
    chosen = []
    for cache_index, (session, cache) in enumerate(zip(sessions, caches)):
        session_spans = spans.get(session, [])
        if not session_spans:
            continue
        for end in consecutive_end_indices(cache["t"], SEQUENCE, HOP_S):
            if int(cache["label"][end]) != 0:
                continue
            if _in_spans(float(cache["t"][end]), session_spans):
                chosen.append((cache_index, end))
    return chosen


def load_spans(path: Path = SPANS_PATH) -> dict[str, list[tuple[float, float]]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    spans: dict[str, list[tuple[float, float]]] = {}
    for row in payload["spans"]:
        session = row["session"]
        if session in EVAL or session in CALIBRATE or session in HOLDOUTS:
            raise RuntimeError(f"studio span names a game the fit must not train on: {session}")
        if session not in TRAIN:
            raise RuntimeError(f"studio span is outside the training games: {session}")
        spans.setdefault(session, []).append((float(row["start_s"]), float(row["end_s"])))
    return spans


def train_studio_head(spans: dict[str, list[tuple[float, float]]], out: Path = HEAD_PATH) -> dict:
    assert_split()
    if not torch.cuda.is_available():
        raise RuntimeError("head training needs the CUDA device")
    device = torch.device("cuda")
    paths = [DATA_ROOT / "embeddings" / "frozen" / f"{session}.npz" for session in TRAIN]
    caches = [load_cache(path) for path in paths]
    commercial, program = _indexes(caches)
    studio = _studio_indexes(caches, TRAIN, spans)
    studio_keys = set(studio)
    ordinary = [item for item in program if item not in studio_keys]
    if len(studio) < 200:
        raise RuntimeError(f"only {len(studio)} studio sequences; refusing a fit that would memorize them")
    head = CausalHead(caches[0]["emb"].shape[1], HIDDEN).to(device)
    optimizer = torch.optim.AdamW(head.parameters(), lr=1e-3, weight_decay=1e-4)
    rng = np.random.default_rng(SEED)
    studio_draw = int(round(PER_CLASS * STUDIO_SHARE))
    ordinary_draw = PER_CLASS - studio_draw
    history = []
    for epoch in range(EPOCHS):
        order_c = commercial.copy()
        order_p = ordinary.copy()
        order_s = studio.copy()
        rng.shuffle(order_c)
        rng.shuffle(order_p)
        rng.shuffle(order_s)
        if len(order_s) < studio_draw:
            reps = int(np.ceil(studio_draw / len(order_s)))
            order_s = (order_s * reps)[:studio_draw]
        picks = order_c[:PER_CLASS] + order_p[:ordinary_draw] + order_s[:studio_draw]
        rng.shuffle(picks)
        total = 0.0
        seen = 0
        head.train()
        for start in range(0, len(picks), BATCH):
            waves, labels = _batch(caches, picks[start : start + BATCH], device)
            optimizer.zero_grad(set_to_none=True)
            logits = head(waves)
            mask = labels >= 0
            if int(mask.sum()) == 0:
                continue
            loss = F.binary_cross_entropy_with_logits(logits[mask], labels[mask].float())
            loss.backward()
            optimizer.step()
            total += float(loss.detach()) * int(mask.sum())
            seen += int(mask.sum())
        mean = total / seen if seen else None
        history.append(mean)
        print(f"studio head epoch {epoch + 1}/{EPOCHS} loss {mean:.4f}", flush=True)
    head.eval()
    save_head(out, head)
    return {
        "epochs": EPOCHS,
        "per_class": PER_CLASS,
        "studio_share": STUDIO_SHARE,
        "studio_sequences": len(studio),
        "ordinary_program_sequences": len(ordinary),
        "commercial_sequences": len(commercial),
        "loss": history,
        "checkpoint": str(out),
        "controller": CONTROLLER,
    }


def _overlap(spans, intervals: list[tuple[float, float]]) -> float:
    total = 0.0
    for span in spans:
        if span.state != "covered":
            continue
        for start, end in intervals:
            left = max(span.start, start)
            right = min(span.end, end)
            if right > left:
                total += right - left
    return total


def _score_array(session: str, times: np.ndarray, scores: np.ndarray, intervals=None) -> dict:
    coverage = coverage_by_session()[session]
    base_intervals = active_intervals(session) if intervals is None else intervals
    rows = decisions(times.tolist(), scores.tolist(), **CONTROLLER)
    spans = playback_from_decisions(coverage, rows)
    scored = score_product(
        coverage,
        base_intervals,
        spans,
        session=session,
        excluded_ranges=excluded_ranges(session, base_intervals),
        wall_gap_s=wall_gaps().get(session, 0.0),
        audio_present=True,
    )
    scored["recovery"] = recovery_rate(spans, coverage[1])
    scored["desk_span_covered_s"] = _overlap(spans, DESK_SPANS.get(session, []))
    scored["longest_episodes"] = [
        {
            "start_s": round(float(episode["start_s"]), 1),
            "end_s": round(float(episode["end_s"]), 1),
            "program_s": round(float(episode["duration_s"]), 1),
        }
        for episode in sorted(scored["episodes"], key=lambda item: item["duration_s"], reverse=True)[:8]
    ]
    return scored


def predict_and_score(head_path: Path) -> dict:
    assert_split()
    device = torch.device("cuda")
    head = load_head(head_path, device)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fresh = []
    frozen = []
    for session in EVAL:
        cache = load_cache(DATA_ROOT / "embeddings" / "frozen" / f"{session}.npz")
        scores = probabilities(head, cache["emb"], cache["t"], device)
        np.savez(OUT_DIR / f"{session}.npz", t=cache["t"], p=scores, label=cache["label"])
        fresh.append(_score_array(session, cache["t"], scores))
        prior = np.load(DATA_ROOT / "predictions" / "frozen" / f"{session}.npz")
        frozen.append(_score_array(session, prior["t"], prior["p"]))
    return {"frozen_controller_on_original_gold": _pack(frozen), "studio_head_on_original_gold": _pack(fresh)}


def _pack(rows: list[dict]) -> dict:
    slim = []
    for row in rows:
        slim.append(
            {
                "session": row["session"],
                "commercial_coverage": row["commercial_coverage"],
                "commercial_covered_s": row["commercial_covered_s"],
                "program_covered_s": row["program_covered_s"],
                "false_mute_episodes": row["false_mute_episodes"],
                "false_mutes_per_hour": row["false_mutes_per_hour"],
                "longest_false_mute_s": row["longest_false_mute_s"],
                "recovery": row["recovery"],
                "desk_span_covered_s": row["desk_span_covered_s"],
                "longest_episodes": row["longest_episodes"],
            }
        )
    summary = aggregate(rows)
    return {
        "commercial_coverage": summary["commercial_coverage"],
        "commercial_covered_s": summary["commercial_covered_s"],
        "program_covered_s": summary["program_covered_s"],
        "false_mute_episodes": summary["false_mute_episodes"],
        "false_mutes_per_hour": summary["false_mutes_per_hour"],
        "longest_false_mute_s": summary["longest_false_mute_s"],
        "program_hidden_per_hour": summary["program_hidden_per_hour"],
        "desk_span_covered_s": sum(row["desk_span_covered_s"] for row in rows),
        "games": slim,
    }


def score_with_added_commercials(head_path: Path, additions: list[dict]) -> dict:
    """Score the same predictions after a reviewed boundary file. Not a model change."""
    device = torch.device("cuda")
    head = load_head(head_path, device)
    rows = []
    for session in EVAL:
        cache = load_cache(DATA_ROOT / "embeddings" / "frozen" / f"{session}.npz")
        scores = probabilities(head, cache["emb"], cache["t"], device)
        intervals = list(active_intervals(session))
        for row in additions:
            if row["session"] != session:
                continue
            intervals.append(
                Interval(
                    start=float(row["start_s"]),
                    end=float(row["end_s"]),
                    event_class="commercial",
                    desired_action="mute",
                    confidence="reviewed",
                )
            )
        rows.append(_score_array(session, cache["t"], scores, intervals))
    return _pack(rows)
