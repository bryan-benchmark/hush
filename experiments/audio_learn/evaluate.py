"""Score causal predictions with the existing playback controller. Prime chooses nothing."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import soundfile as sf

from experiments.audio_learn.baseline import locked_lines, locked_persist_playback
from experiments.audio_learn.controller import assignment_pass, decisions, recovery_rate, select_controller
from experiments.audio_learn.encoder import DATA_ROOT
from experiments.audio_learn.extract import cache_path, load_cache
from experiments.audio_learn.head import load_head, probabilities
from experiments.audio_learn.splits import CALIBRATE, EVAL, HOP_S, SR
from experiments.ledger import sha256_file
from experiments.nfl75.inventory import (
    active_intervals,
    coverage_by_session,
    excluded_ranges,
    wall_gaps,
)
from experiments.nfl75.score import aggregate, always_play, playback_from_decisions, score_product
from tools.gpu_lab.audio_load import load_coverage
from tools.gpu_lab.splits import HOLDOUTS

REPO = Path(__file__).resolve().parents[2]
REPORT_DIR = REPO / "docs" / "ohush" / "research" / "OHUSH_AUDIO_LEARNING_001"


def _clean(value):
    if isinstance(value, dict):
        return {key: _clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(item) for item in value]
    if isinstance(value, np.ndarray):
        return _clean(value.tolist())
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.integer):
        return int(value)
    return value


def _predict(kind: str, head_path: Path, session: str) -> dict:
    if session in HOLDOUTS:
        raise RuntimeError(f"refusing sealed holdout {session}")
    import torch

    cache = load_cache(cache_path(kind, session))
    device = torch.device("cuda")
    head = load_head(head_path, device)
    scores = probabilities(head, cache["emb"], cache["t"], device)
    out = DATA_ROOT / "predictions" / kind / f"{session}.npz"
    out.parent.mkdir(parents=True, exist_ok=True)
    np.savez(out, t=cache["t"], p=scores, label=cache["label"])
    return {"t": cache["t"], "p": scores, "label": cache["label"], "path": str(out)}


def _auroc(labels: np.ndarray, scores: np.ndarray) -> float | None:
    keep = labels >= 0
    y = labels[keep]
    s = scores[keep]
    if len(np.unique(y)) < 2:
        return None
    from sklearn.metrics import roc_auc_score

    return float(roc_auc_score(y, s))


def _bootstrap(breaks: list[dict], other: list[dict] | None = None, draws: int = 2000) -> dict:
    if not breaks:
        return {"breaks": 0}
    length = np.asarray([row["length_s"] for row in breaks], dtype=np.float64)
    covered = np.asarray([row["covered_s"] for row in breaks], dtype=np.float64)
    rng = np.random.default_rng(1)
    index = rng.integers(0, len(breaks), size=(draws, len(breaks)))
    stat = covered[index].sum(axis=1) / length[index].sum(axis=1)
    result = {
        "breaks": len(breaks),
        "coverage": float(covered.sum() / length.sum()),
        "coverage_ci95": [float(np.quantile(stat, 0.025)), float(np.quantile(stat, 0.975))],
    }
    if other is not None:
        if len(other) != len(breaks):
            raise RuntimeError("bootstrap pairs breaks by order")
        base = np.asarray([row["covered_s"] for row in other], dtype=np.float64)
        diff = (covered[index] - base[index]).sum(axis=1) / length[index].sum(axis=1)
        result["coverage_minus_baseline_ci95"] = [float(np.quantile(diff, 0.025)), float(np.quantile(diff, 0.975))]
    return result


def _score_rows(session: str, spans) -> dict:
    coverage = coverage_by_session()[session]
    intervals = active_intervals(session)
    return score_product(
        coverage,
        intervals,
        spans,
        session=session,
        excluded_ranges=excluded_ranges(session, intervals),
        wall_gap_s=wall_gaps().get(session, 0.0),
        audio_present=True,
    )


def _setting(chosen: dict) -> dict:
    return {key: chosen[key] for key in ("on", "off", "on_streak", "off_streak")}


def _play_model(session: str, prediction: dict, chosen: dict):
    coverage = coverage_by_session()[session]
    rows = decisions(prediction["t"].tolist(), prediction["p"].tolist(), **_setting(chosen))
    spans = playback_from_decisions(coverage, rows)
    scored = _score_rows(session, spans)
    scored["recovery"] = recovery_rate(spans, coverage[1])
    scored["assignment_pass"] = assignment_pass(scored, scored["recovery"])
    return spans, scored


def _lags(scored: dict) -> dict:
    caught = [row for row in scored.get("breaks") or [] if row["start_delay_s"] is not None]
    breaks = scored.get("breaks") or []
    returns = [row["late_return_s"] for row in breaks if row["covered_s"] > 0]
    return {
        "breaks": len(breaks),
        "breaks_never_covered": sum(1 for row in breaks if row["missed_break"]),
        "median_start_delay_s": None if not caught else float(np.median([row["start_delay_s"] for row in caught])),
        "median_late_return_s": None if not returns else float(np.median(returns)),
    }


def _public(scored: dict) -> dict:
    keys = (
        "session",
        "evaluable",
        "commercial_s",
        "commercial_covered_s",
        "commercial_coverage",
        "program_s",
        "program_covered_s",
        "false_mute_episodes",
        "false_mutes_per_hour",
        "longest_false_mute_s",
        "program_hidden_per_hour",
        "recovery",
        "assignment_pass",
    )
    out = {key: scored.get(key) for key in keys}
    out["nfl75_pass"] = bool(scored["acceptance"]["pass"])
    out["nfl75_reasons"] = list(scored["acceptance"]["reasons"])
    out["lags"] = _lags(scored)
    return out


def _clips(kind: str, scored: dict, limit: int = 4) -> list[dict]:
    session = scored["session"]
    coverage = coverage_by_session()[session]
    written = []
    episodes = sorted(scored["episodes"], key=lambda row: row["duration_s"], reverse=True)[:limit]
    misses = sorted(scored["breaks"], key=lambda row: row["missed_s"], reverse=True)[:limit]
    folder = DATA_ROOT / "clips" / kind / session
    folder.mkdir(parents=True, exist_ok=True)
    specs = []
    for episode in episodes:
        specs.append(("false_mute", episode["start_s"], episode["end_s"], episode["duration_s"]))
    for brk in misses:
        if brk["missed_s"] <= 0:
            continue
        specs.append(("missed_commercial", brk["start_s"], min(brk["start_s"] + 12.0, brk["end_s"]), brk["missed_s"]))
    for kind_name, start, end, size in specs:
        left = max(coverage[0], start - 2.0)
        right = min(coverage[1], max(end + 2.0, left + 1.0))
        audio = load_coverage(session, left, right)
        path = folder / f"{kind_name}_{start:.1f}_{end:.1f}.wav"
        sf.write(path, audio, SR)
        written.append(
            {
                "kind": kind_name,
                "session": session,
                "start_s": start,
                "end_s": end,
                "size_s": size,
                "clip_start_s": left,
                "clip_end_s": right,
                "path": str(path),
                "sha256": sha256_file(path),
            }
        )
    return written


def _plot(kind: str, session: str, prediction: dict, scored: dict) -> str:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    times = prediction["t"]
    scores = prediction["p"]
    figure, axis = plt.subplots(figsize=(14, 3.2))
    axis.plot(times / 60.0, scores, color="#1f4b99", lw=0.6, label="P(commercial)")
    for brk in scored["breaks"]:
        axis.axvspan(brk["start_s"] / 60.0, brk["end_s"] / 60.0, color="#c45c26", alpha=0.35, lw=0)
    axis.set_ylim(-0.02, 1.02)
    axis.set_xlabel("Minutes on the capture clock")
    axis.set_ylabel("P(commercial)")
    axis.set_title(f"{kind} {session}")
    path = REPORT_DIR / f"{kind}_{session}.png"
    figure.tight_layout()
    figure.savefig(path, dpi=120)
    plt.close(figure)
    if scored["breaks"]:
        first = scored["breaks"][0]
        left = max(float(times[0]), first["start_s"] - 60.0)
        right = min(float(times[-1]), first["end_s"] + 60.0)
        mask = (times >= left) & (times <= right)
        zoom, zoom_axis = plt.subplots(figsize=(10, 3.2))
        zoom_axis.plot(times[mask] / 60.0, scores[mask], color="#1f4b99", lw=1.0)
        zoom_axis.axvspan(first["start_s"] / 60.0, first["end_s"] / 60.0, color="#c45c26", alpha=0.35, lw=0)
        zoom_axis.set_ylim(-0.02, 1.02)
        zoom_axis.set_xlabel("Minutes")
        zoom_axis.set_ylabel("P(commercial)")
        zoom_axis.set_title(f"{kind} {session} first commercial")
        zoom_path = REPORT_DIR / f"{kind}_{session}_first_break.png"
        zoom.tight_layout()
        zoom.savefig(zoom_path, dpi=120)
        plt.close(zoom)
    return str(path)


def _recommend(frozen: dict, tuned: dict, baseline: dict) -> str:
    def coverage(row: dict) -> float:
        value = row["aggregate"]["commercial_coverage"]
        return -1.0 if value is None else float(value)

    best_name, best = max((("frozen", frozen), ("finetuned", tuned)), key=lambda item: coverage(item[1]))
    base = float(baseline["aggregate"]["commercial_coverage"] or 0.0)
    gain = coverage(best) - base
    auroc = best["prime_auroc"]
    passed = best["aggregate_assignment_pass"]
    if passed and gain > 0:
        return (
            f"The {best_name} model clears the experimental full-game gate on the two Prime games "
            f"and covers more advertising than the locked logistic. That is the result that would justify "
            f"a later live trial. It is not installed."
        )
    if auroc is not None and auroc >= 0.75 and coverage(best) < 0.75:
        return (
            f"The {best_name} probabilities separate ads from programming (Prime AUROC {auroc:.3f}), "
            f"and the volume rule still misses the coverage gate. The next change is the temporal rule "
            f"or the decision latency, using the same encoder. A new detector family is not indicated."
        )
    if auroc is not None and auroc < 0.65:
        return (
            "The frame encoder is not yet separating Prime ads from Prime programming. "
            "The next response is more verified hard examples and another fit of this same model. "
            "A second detection method is not indicated by this run."
        )
    if best["aggregate"]["false_mutes_per_hour"] is not None and best["aggregate"]["false_mutes_per_hour"] >= 1.0:
        return (
            f"The {best_name} model covers advertising and also interrupts the game too often. "
            f"The next response is to add the interrupted stretches as program examples and refit. "
            f"The controller grid should stay the one declared here."
        )
    return (
        f"The {best_name} model changes coverage by {gain:+.3f} against the locked logistic "
        f"and does not clear the experimental gate. Keep this encoder, add the missed Prime "
        f"breaks as training examples only after a new untouched Prime tape exists, and do not "
        f"treat these two games as both the lesson and the exam."
    )


def run_evaluation(frozen_head: Path, tuned_head: Path) -> dict:
    import torch

    if not torch.cuda.is_available():
        raise RuntimeError("evaluation needs the CUDA device for the causal head")
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    needed = list(CALIBRATE + EVAL)
    frozen_pred = {session: _predict("frozen", frozen_head, session) for session in needed}
    tuned_pred = {session: _predict("finetuned", tuned_head, session) for session in needed}
    coverage = coverage_by_session()
    gaps = wall_gaps()

    def choose(kind: str, pred: dict) -> dict:
        session = CALIBRATE[0]
        intervals = active_intervals(session)
        return select_controller(
            coverage[session],
            intervals,
            pred[session]["t"],
            pred[session]["p"],
            gaps.get(session, 0.0),
            excluded_ranges(session, intervals),
        )

    frozen_choice = choose("frozen", frozen_pred)
    tuned_choice = choose("finetuned", tuned_pred)
    (REPORT_DIR / "controller_frozen.json").write_text(json.dumps(_clean(frozen_choice), indent=2), encoding="utf-8")
    (REPORT_DIR / "controller_finetuned.json").write_text(json.dumps(_clean(tuned_choice), indent=2), encoding="utf-8")

    def pack(kind: str, pred: dict, choice: dict) -> dict:
        per_game = {}
        spans = {}
        for session in EVAL:
            playback, scored = _play_model(session, pred[session], choice["chosen"])
            spans[session] = playback
            per_game[session] = scored
            _plot(kind, session, pred[session], scored)
        pooled = aggregate([per_game[session] for session in EVAL])
        recovery_values = [per_game[session]["recovery"] for session in EVAL]
        # A mute still open on either game fails the pooled recovery claim.
        pooled_recovery = min(recovery_values)
        pooled_public = _public(pooled)
        pooled_public["recovery"] = pooled_recovery
        pooled_public["assignment_pass"] = assignment_pass(pooled, pooled_recovery)
        clips = []
        for session in EVAL:
            clips.extend(_clips(kind, per_game[session]))
        return {
            "controller": choice["chosen"],
            "calibration_auroc": _auroc(pred[CALIBRATE[0]]["label"], pred[CALIBRATE[0]]["p"]),
            "prime_auroc": _auroc(
                np.concatenate([pred[session]["label"] for session in EVAL]),
                np.concatenate([pred[session]["p"] for session in EVAL]),
            ),
            "games": {session: _public(per_game[session]) for session in EVAL},
            "aggregate": pooled_public,
            "aggregate_assignment_pass": pooled_public["assignment_pass"],
            "breaks": {session: per_game[session]["breaks"] for session in EVAL},
            "clips": clips,
            "plots": [str(REPORT_DIR / f"{kind}_{session}.png") for session in EVAL],
        }

    frozen = pack("frozen", frozen_pred, frozen_choice)
    tuned = pack("finetuned", tuned_pred, tuned_choice)
    lines = locked_lines()
    baseline_games = {}
    for session in EVAL:
        playback, meta = locked_persist_playback(session, coverage[session], lines)
        scored = _score_rows(session, playback)
        scored["recovery"] = recovery_rate(playback, coverage[session][1])
        scored["assignment_pass"] = assignment_pass(scored, scored["recovery"])
        baseline_games[session] = scored
        del meta
    always_games = {}
    for session in EVAL:
        scored = _score_rows(session, always_play(coverage[session]))
        scored["recovery"] = 1.0
        scored["assignment_pass"] = assignment_pass(scored, 1.0)
        always_games[session] = scored
    baseline_pool = aggregate([baseline_games[session] for session in EVAL])
    baseline_public = _public(baseline_pool)
    baseline_public["recovery"] = min(baseline_games[session]["recovery"] for session in EVAL)
    baseline_public["assignment_pass"] = assignment_pass(baseline_pool, baseline_public["recovery"])
    always_pool = aggregate([always_games[session] for session in EVAL])
    always_public = _public(always_pool)
    always_public["recovery"] = 1.0
    always_public["assignment_pass"] = False
    frozen_breaks = [row for session in EVAL for row in frozen["breaks"][session]]
    base_breaks = [row for session in EVAL for row in baseline_games[session]["breaks"]]
    tuned_breaks = [row for session in EVAL for row in tuned["breaks"][session]]
    result = {
        "frozen": {key: value for key, value in frozen.items() if key != "breaks"},
        "finetuned": {key: value for key, value in tuned.items() if key != "breaks"},
        "baseline": {
            "name": "locked_nbc_logistic_persist_10s",
            "games": {session: _public(baseline_games[session]) for session in EVAL},
            "aggregate": baseline_public,
        },
        "always_play": {
            "games": {session: _public(always_games[session]) for session in EVAL},
            "aggregate": always_public,
        },
        "bootstrap": {
            "frozen_vs_baseline": _bootstrap(frozen_breaks, base_breaks),
            "finetuned_vs_baseline": _bootstrap(tuned_breaks, base_breaks),
        },
    }
    result["recommendation"] = _recommend(result["frozen"], result["finetuned"], result["baseline"])
    (REPORT_DIR / "metrics.json").write_text(json.dumps(_clean(result), indent=2), encoding="utf-8")
    return result
