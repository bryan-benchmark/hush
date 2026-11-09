"""Supervised commercial-versus-program scores on broadcasts excluded from the fit.

The head is a logistic regression on cached 5-second AST windows. It is fit
on two NBC games only. The cutoff sits one step above every score that
touches program audio on those two games, and it is not moved afterward.
October is described with that same cutoff. It is not a blind test.
Sealed holdouts are not opened. Nothing here mutes.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from sklearn.linear_model import LogisticRegression

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.gpu_lab.decisions import playback_from_scores, pod_losses, program_incidents  # noqa: E402
from tools.gpu_lab.ladder import pairs, score_mask  # noqa: E402
from tools.gpu_lab.learning_net.data import bridge_masks, load_cache  # noqa: E402
from tools.gpu_lab.splits import DEVELOP, HOLDOUTS  # noqa: E402

OUT = REPO / "docs" / "ohush" / "research" / "SUPERVISED_HELDOUT_001"
WINDOW_S = 5.0
FIT = ("hush_20260909_213047", "hush_20260913_210542")
REPORT = (
    ("hush_20260914_212529", "Sept 14 ESPN", "held_out"),
    ("hush_20260924_220624", "Sept 24 Prime", "held_out"),
    ("hush_20260913_150934", "Sept 13 RedZone", "held_out"),
)
OCTOBER = (
    ("hush_20261008_205100", "Oct 8 Prime Video"),
    ("hush_20261010_222400", "Oct 10 cable"),
    ("hush_20261011_135700", "Oct 11 afternoon"),
    ("hush_20261011_204300", "Oct 11 night"),
    ("hush_20261012_204200", "Oct 12 MNF"),
)
NAMES = {
    "hush_20260909_213047": "Sept 9 NBC",
    "hush_20260913_210542": "Sept 13 NBC",
    **{sid: name for sid, name, _role in REPORT},
    **{sid: name for sid, name in OCTOBER},
}


def _fit(sessions: tuple[str, ...]) -> tuple[LogisticRegression, dict]:
    vectors = []
    labels = []
    for session in sessions:
        if session in HOLDOUTS:
            raise RuntimeError(f"refusing sealed holdout {session}")
        cache = load_cache(session, WINDOW_S)
        keep = cache["label"] >= 0
        vectors.append(cache["emb"][keep])
        labels.append(cache["label"][keep])
    x = np.concatenate(vectors)
    y = np.concatenate(labels)
    head = LogisticRegression(max_iter=2000, class_weight="balanced")
    head.fit(x, y)
    receipt = {
        "sessions": list(sessions),
        "rows": int(len(y)),
        "commercial_rows": int((y == 1).sum()),
        "program_rows": int((y == 0).sum()),
        "train_accuracy": round(float(head.score(x, y)), 4),
    }
    return head, receipt


def _scores(head: LogisticRegression, session: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if session in HOLDOUTS:
        raise RuntimeError(f"refusing sealed holdout {session}")
    cache = load_cache(session, WINDOW_S)
    logits = np.asarray(head.decision_function(cache["emb"]), dtype=np.float64)
    return cache["t"], logits, cache["label"]


def _program_ceiling(mask: dict, times: np.ndarray, scores: np.ndarray) -> float:
    program = pairs(mask, "verified_program")
    ceiling = None
    for moment, score in zip(times, scores):
        end = float(moment) + 1.0
        if any(min(end, stop) - max(float(moment), start) > 1e-9 for start, stop in program):
            ceiling = float(score) if ceiling is None else max(ceiling, float(score))
    if ceiling is None:
        raise RuntimeError(f"{mask['session']} has no program-overlapping score")
    return ceiling


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return round(ordered[mid], 3)
    return round(0.5 * (ordered[mid - 1] + ordered[mid]), 3)


def _return_delays(commercials: list[tuple[float, float]], playback) -> dict:
    delays = []
    still = 0
    for _start, end in commercials:
        found = None
        for span in playback:
            if span.state != "program" or span.end <= end:
                continue
            found = max(span.start, end) - end
            break
        if found is None:
            still += 1
        else:
            delays.append(found)
    return {"median_s": _median(delays), "returned": len(delays), "still_covered": still}


def _class_medians(scores: np.ndarray, labels: np.ndarray) -> dict:
    commercial = scores[labels == 1]
    program = scores[labels == 0]
    return {
        "commercial_median": None if commercial.size == 0 else round(float(np.median(commercial)), 3),
        "program_median": None if program.size == 0 else round(float(np.median(program)), 3),
    }


def _score_session(mask: dict, times: np.ndarray, scores: np.ndarray, labels: np.ndarray, threshold: float) -> dict:
    coverage = pairs(mask, "coverage")[0]
    playback = playback_from_scores(coverage, times.tolist(), scores.tolist(), threshold)
    scored = score_mask(mask, playback)
    commercials = pairs(mask, "verified_commercial")
    losses = pod_losses(commercials, playback)
    early = round(sum(row["early_unmute_s"] for row in losses), 3)
    late = round(sum(row["late_start_s"] for row in losses), 3)
    incidents = program_incidents(pairs(mask, "verified_program"), playback)
    worst = max(incidents, key=lambda row: row["program_s"]) if incidents else None
    missed = [row for row in commercials if not any(
        span.state == "covered" and span.end > row[0] and span.start < row[1] for span in playback
    )]
    longest_miss = None
    if missed:
        start, end = max(missed, key=lambda row: row[1] - row[0])
        longest_miss = {"t0": round(start, 3), "t1": round(end, 3), "seconds": round(end - start, 3)}
    return {
        "session": mask["session"],
        "name": NAMES.get(mask["session"], mask["session"]),
        "commercial_recognized_s": scored["commercial_held_s"],
        "commercial_missed_s": scored["commercial_heard_s"],
        "commercial_s": round(sum(end - start for start, end in commercials), 3),
        "program_mistaken_s": scored["program_cut_s"],
        "program_interruptions": scored["false_cover_incidents"],
        "start_delay_median_s": scored["start_delay_median_s"],
        "starts": scored["starts"],
        "starts_missed": scored["starts_missed"],
        "return_delay": _return_delays(commercials, playback),
        "late_start_s": late,
        "early_unmute_s": early,
        "class_medians": _class_medians(scores, labels),
        "worst_program_interruption": None
        if worst is None
        else {
            "t0": worst["start_seconds"],
            "t1": worst["end_seconds"],
            "program_s": worst["program_s"],
            "note": "Times are on the session clock. The clip is not copied.",
        },
        "longest_missed_break": None
        if longest_miss is None
        else {**longest_miss, "note": "Times are on the session clock. The clip is not copied."},
        "broken": scored["broken"],
    }


def _plot(path: Path, title: str, times: np.ndarray, scores: np.ndarray, commercials: list[tuple[float, float]], threshold: float) -> None:
    fig, ax = plt.subplots(figsize=(12, 3.2))
    ax.plot(times, scores, color="#1f4b99", linewidth=0.6, label="score")
    ax.axhline(threshold, color="#b45309", linewidth=0.8, linestyle="--", label="NBC cutoff")
    for index, (start, end) in enumerate(commercials):
        ax.axvspan(start, end, color="#f4c7c3", alpha=0.7, label="labeled commercial" if index == 0 else None)
    ax.set_title(title)
    ax.set_xlabel("Session seconds")
    ax.set_ylabel("Logistic score")
    ax.legend(loc="upper right", fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def main() -> None:
    if set(DEVELOP) != {sid for sid, _name in OCTOBER}:
        raise SystemExit("October list drifted from the published development split")
    masks = bridge_masks()
    head, receipt = _fit(FIT)
    ceilings = []
    for session in FIT:
        times, scores, _labels = _scores(head, session)
        ceilings.append(_program_ceiling(masks[session], times, scores))
    ceiling = max(ceilings)
    threshold = math.nextafter(ceiling, math.inf)
    print(f"fit {receipt} cutoff {threshold}", flush=True)

    rows = []
    series = {}
    for session in (*FIT, *(sid for sid, _name, _role in REPORT), *(sid for sid, _name in OCTOBER)):
        times, scores, labels = _scores(head, session)
        row = _score_session(masks[session], times, scores, labels, threshold)
        if session in FIT:
            row["role"] = "fit"
        elif session in {sid for sid, _name, _role in REPORT}:
            row["role"] = "held_out"
        else:
            row["role"] = "october_already_inspected"
        rows.append(row)
        if session in ("hush_20260914_212529", "hush_20260913_150934"):
            series[session] = (times, scores, pairs(masks[session], "verified_commercial"))
        print(
            f"{row['name']} recognized {row['commercial_recognized_s']} "
            f"missed {row['commercial_missed_s']} program {row['program_mistaken_s']} "
            f"interruptions {row['program_interruptions']}",
            flush=True,
        )

    for session in FIT:
        fit_row = next(row for row in rows if row["session"] == session)
        if fit_row["program_mistaken_s"] > 0:
            raise SystemExit(f"cutoff touched program on a fit game: {session}")

    OUT.mkdir(parents=True, exist_ok=True)
    _plot(
        OUT / "espn_timeline.png",
        "ESPN, held out. Shaded spans are labeled commercials.",
        *series["hush_20260914_212529"],
        threshold,
    )
    _plot(
        OUT / "redzone_timeline.png",
        "RedZone, held out. This tape has no labeled commercials.",
        *series["hush_20260913_150934"],
        threshold,
    )
    payload = {
        "id": "SUPERVISED_HELDOUT_001",
        "model": "MIT/ast-finetuned-audioset-10-10-0.4593",
        "window_s": WINDOW_S,
        "head": "logistic regression, class_weight balanced",
        "fit": receipt,
        "threshold": threshold,
        "threshold_rule": "one step above the highest score that touches program audio on the two NBC fit games",
        "october_may_choose_cutoff": False,
        "live_mute_changed": False,
        "continuity_baseline": {
            "source": "docs/ohush/research/FROZEN_RETURN_REPLICATION_001 and experiments/exp002/EXP002_RESULT.md",
            "espn_starts_within_15s": "12 of 13 evaluable",
            "espn_program_collapses_per_hour": 4.2,
            "redzone_collapses": 17,
            "redzone_per_hour": 8.5,
        },
        "sessions": rows,
    }
    (OUT / "results.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT / 'results.json'}", flush=True)


if __name__ == "__main__":
    main()
