"""Name the NBC program seconds that set the supervised cutoff.

The head and the cutoff are the ones already locked in SUPERVISED_HELDOUT_001.
This script only reads the two fit games. It does not move the cutoff, and it
does not score ESPN, Prime, RedZone, or October.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from experiments.measurement.supervised_heldout_001 import FIT, WINDOW_S, _fit, _program_ceiling, _scores  # noqa: E402
from tools.gpu_lab.embed import MODEL_ID  # noqa: E402
from tools.gpu_lab.ladder import pairs  # noqa: E402
from tools.gpu_lab.learning_net.data import bridge_masks, load_cache  # noqa: E402

OUT = REPO / "docs" / "ohush" / "research" / "SUPERVISED_CEILING_001"
PUBLISHED_CUTOFF = 12.155325889587404
NAMES = {
    "hush_20260909_213047": "Sept 9 NBC",
    "hush_20260913_210542": "Sept 13 NBC",
}
TOP_RUNS = 12


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def _touches(moment: float, spans: list[tuple[float, float]]) -> float:
    end = moment + 1.0
    return sum(_overlap(moment, end, start, stop) for start, stop in spans)


def _nearest_break(moment: float, commercials: list[tuple[float, float]]) -> dict:
    best = None
    for start, end in commercials:
        if _overlap(moment, moment + 1.0, start, end) > 0:
            return {"seconds": 0.0, "side": "decision second overlaps a labeled commercial"}
        if moment < start:
            gap = start - moment
            side = "before the next labeled commercial"
        else:
            gap = moment - end
            side = "after the previous labeled commercial"
        if best is None or gap < best["seconds"]:
            best = {"seconds": round(gap, 3), "side": side}
    if best is None:
        raise RuntimeError("fit game has no commercials")
    return best


def _runs(rows: list[dict]) -> list[dict]:
    grouped = []
    for row in rows:
        if grouped and grouped[-1]["session"] == row["session"] and row["t"] <= grouped[-1]["t1"] + 1.01:
            grouped[-1]["t1"] = row["t"]
            grouped[-1]["n"] += 1
            if row["score"] > grouped[-1]["peak_score"]:
                grouped[-1]["peak_score"] = row["score"]
                grouped[-1]["peak"] = row
        else:
            grouped.append({"session": row["session"], "t0": row["t"], "t1": row["t"], "n": 1, "peak_score": row["score"], "peak": row})
    return grouped


def _names(vectors: np.ndarray) -> list[list[dict]]:
    import torch
    from transformers import AutoModelForAudioClassification

    model = AutoModelForAudioClassification.from_pretrained(MODEL_ID)
    model.eval()
    labels = [model.config.id2label[index] for index in range(model.config.num_labels)]
    with torch.inference_mode():
        logits = model.classifier(torch.tensor(vectors)).detach().cpu().numpy()
    logits = logits - logits.max(axis=1, keepdims=True)
    prob = np.exp(logits)
    prob /= prob.sum(axis=1, keepdims=True)
    named = []
    for row in prob:
        order = np.argsort(row)[::-1][:3]
        named.append(
            [{"class": labels[int(index)], "probability": round(float(row[index]), 4)} for index in order]
        )
    return named


def main() -> None:
    masks = bridge_masks()
    head, receipt = _fit(FIT)
    packed = []
    ceilings = []
    for session in FIT:
        cache = load_cache(session, WINDOW_S)
        times, scores, labels = _scores(head, session)
        if not np.array_equal(times, cache["t"]):
            raise SystemExit(f"{session} score times drifted from the cache")
        ceilings.append(_program_ceiling(masks[session], times, scores))
        packed.append((session, times, scores, labels, cache["emb"], masks[session]))
    ceiling = max(ceilings)
    threshold = float(np.nextafter(ceiling, np.inf))
    if abs(threshold - PUBLISHED_CUTOFF) > 1e-9:
        raise SystemExit(f"cutoff moved: {threshold} versus published {PUBLISHED_CUTOFF}")

    commercial_scores = np.concatenate([scores[labels == 1] for _session, _times, scores, labels, _emb, _mask in packed])
    program_rows = []
    for session, times, scores, labels, emb, mask in packed:
        program = pairs(mask, "verified_program")
        commercials = pairs(mask, "verified_commercial")
        for index, (moment, score, label) in enumerate(zip(times, scores, labels)):
            touched = _touches(float(moment), program)
            if touched <= 1e-9:
                continue
            window_ad = sum(_overlap(float(moment) - WINDOW_S, float(moment), start, stop) for start, stop in commercials)
            program_rows.append(
                {
                    "session": session,
                    "name": NAMES[session],
                    "t": round(float(moment), 3),
                    "score": float(score),
                    "label": int(label),
                    "decision_program_s": round(touched, 3),
                    "window_commercial_s": round(window_ad, 3),
                    "nearest_break": _nearest_break(float(moment), commercials),
                    "emb_index": index,
                    "emb": emb[index],
                }
            )
    program_scores = np.array([row["score"] for row in program_rows])
    commercial_p50 = float(np.percentile(commercial_scores, 50))
    commercial_p95 = float(np.percentile(commercial_scores, 95))
    p99 = float(np.percentile(commercial_scores, 99))
    percentiles = {
        "commercial_p50": round(commercial_p50, 3),
        "commercial_p95": round(commercial_p95, 3),
        "commercial_p99": round(p99, 3),
        "commercial_max": round(float(commercial_scores.max()), 3),
        "program_p50": round(float(np.percentile(program_scores, 50)), 3),
        "program_p95": round(float(np.percentile(program_scores, 95)), 3),
        "program_p99": round(float(np.percentile(program_scores, 99)), 3),
        "program_max": round(float(program_scores.max()), 3),
    }
    program_p99 = float(np.percentile(program_scores, 99))
    tail = [row for row in program_rows if row["score"] >= program_p99]
    runs = _runs(sorted(tail, key=lambda row: (row["session"], row["t"])))
    runs.sort(key=lambda row: row["peak_score"], reverse=True)
    shown = runs[:TOP_RUNS]
    named = _names(np.stack([row["peak"]["emb"] for row in shown])) if shown else []
    listed = []
    for run, tags in zip(shown, named):
        peak = {key: value for key, value in run["peak"].items() if key not in {"emb", "emb_index"}}
        listed.append(
            {
                "session": run["session"],
                "name": NAMES[run["session"]],
                "t0": run["t0"],
                "t1": round(run["t1"] + 1.0, 3),
                "seconds": run["n"],
                "peak_score": round(run["peak_score"], 3),
                "peak": peak,
                "audioset_top3": tags,
                "note": "t0 and t1 are on the session clock. The clip is not copied. The score at the peak uses audio from t-5 to t.",
            }
        )
    above_median = [row for row in program_rows if row["score"] >= commercial_p50]
    clear = [row for row in program_rows if row["label"] == 0 and row["window_commercial_s"] <= 1e-9]
    highest_clear = max(clear, key=lambda row: row["score"])
    split = {
        "above_commercial_median": len(above_median),
        "mixed_label": sum(row["label"] < 0 for row in above_median),
        "entire_program_label": sum(row["label"] == 0 for row in above_median),
        "lookback_entirely_commercial": sum(row["window_commercial_s"] >= WINDOW_S - 1e-6 for row in above_median),
        "entire_program_and_clear_lookback": sum(
            row["label"] == 0 and row["window_commercial_s"] <= 1e-9 for row in above_median
        ),
        "highest_clear_program_second": {
            "session": highest_clear["session"],
            "name": highest_clear["name"],
            "t": highest_clear["t"],
            "score": round(highest_clear["score"], 3),
            "nearest_break": highest_clear["nearest_break"],
        },
    }
    setters = [row for row in program_rows if row["score"] >= ceiling - 1e-6]
    payload = {
        "id": "SUPERVISED_CEILING_001",
        "follows": "SUPERVISED_HELDOUT_001",
        "fit": receipt,
        "threshold": threshold,
        "threshold_moved": False,
        "games_scored": list(FIT),
        "held_out_games_read": False,
        "percentiles": percentiles,
        "program_seconds": int(len(program_rows)),
        "program_seconds_above_commercial_p50": int(np.sum(program_scores >= commercial_p50)),
        "program_seconds_above_commercial_p95": int(np.sum(program_scores >= commercial_p95)),
        "program_seconds_above_commercial_p99": int(np.sum(program_scores >= p99)),
        "above_median_split": split,
        "program_seconds_at_ceiling": len(setters),
        "ceiling_setters": [
            {
                "session": row["session"],
                "name": row["name"],
                "t": row["t"],
                "score": round(row["score"], 6),
                "label": row["label"],
                "decision_program_s": row["decision_program_s"],
                "window_commercial_s": row["window_commercial_s"],
                "nearest_break": row["nearest_break"],
            }
            for row in setters
        ],
        "program_p99_line": round(program_p99, 3),
        "commercial_p99_above_every_program_second": bool(p99 > float(program_scores.max())),
        "program_runs_at_or_above_program_p99": len(runs),
        "highest_program_runs": listed,
        "live_mute_changed": False,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(
        f"cutoff {threshold} program seconds {len(program_rows)} "
        f"above commercial p99 {payload['program_seconds_above_commercial_p99']} "
        f"program-p99 runs {len(runs)} ceiling setters {len(setters)}",
        flush=True,
    )
    for row in listed[:8]:
        top = row["audioset_top3"][0]["class"]
        print(
            f"{row['name']} {row['t0']:.0f}-{row['t1']:.0f} peak {row['peak_score']} "
            f"window ad {row['peak']['window_commercial_s']}s {top}",
            flush=True,
        )


if __name__ == "__main__":
    main()
