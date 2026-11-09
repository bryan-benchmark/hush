"""Step 3 of OHUSH_AD_DETECT_001: pod-vs-desk stage on top of the frozen mean.

    python -m experiments.nfl75.voice_ad_detect_step3

Logic (expert second stage):
  1. Stage A stays the frozen 10-second CLS mean at 0.163. Unchanged.
  2. Stage B only runs when A is hot. It asks: true commercial pod, or
     false-hot program (desk / talk)?
  3. Fit B only on NBC seconds where A is already hot. Labels are gold
     commercial vs program. Prime hard board stays held out.
  4. Final commercial decision = A hot AND B says commercial.
  5. Speaker unused. Mute not installed.

B features are causal shape cues around the hot streak: mean level, raw
level, how long A has been hot, onset rise, Speech/Music now and over the
last 10 stamps, and stability of the mean while hot.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression

from experiments.nfl75.forensics import START_LINE
from experiments.nfl75.mean import rolling_means
from experiments.nfl75.persist import FIT, WINDOW_S, _fit_nbc, _logits
from experiments.nfl75.voice_ad_detect import HARD, _box_verdict, _classify, _gold_label
from tools.gpu_lab.embed import MODEL_ID
from tools.gpu_lab.ladder import pairs
from tools.gpu_lab.learning_net.data import bridge_masks, load_cache

REPO = Path(__file__).resolve().parents[2]
DEST = REPO / "docs" / "ohush" / "research" / "OHUSH_AD_DETECT_001"
CLASSIFIER = Path(r"C:\OHushData\gpu_lab\models\ast_audioset_classifier.npz")
MEAN_WINDOW = 10
ROLL = 10


def _causal_roll(values: np.ndarray, window: int) -> np.ndarray:
    out = np.full(len(values), np.nan, dtype=np.float64)
    for i in range(len(values)):
        start = i - window + 1
        if start < 0:
            continue
        chunk = values[start : i + 1]
        if np.isfinite(chunk).sum() < window:
            continue
        out[i] = float(np.nanmean(chunk))
    return out


def _hot_run_lengths(hot: np.ndarray) -> np.ndarray:
    """Inclusive count of consecutive hot stamps ending at i. 0 if cold."""
    out = np.zeros(len(hot), dtype=np.float64)
    run = 0
    for i, flag in enumerate(hot):
        if flag:
            run += 1
        else:
            run = 0
        out[i] = float(run)
    return out


def _onset_rise(means: np.ndarray, hot_run: np.ndarray) -> np.ndarray:
    """mean[i] - mean at the stamp before this hot streak began."""
    out = np.full(len(means), 0.0, dtype=np.float64)
    for i in range(len(means)):
        run = int(hot_run[i])
        if run <= 0 or not np.isfinite(means[i]):
            continue
        prev = i - run
        if prev < 0 or not np.isfinite(means[prev]):
            out[i] = float(means[i])
        else:
            out[i] = float(means[i] - means[prev])
    return out


def _hot_stability(means: np.ndarray, hot_run: np.ndarray) -> np.ndarray:
    """Std of mean over the current hot streak (0 if run < 2)."""
    out = np.zeros(len(means), dtype=np.float64)
    for i in range(len(means)):
        run = int(hot_run[i])
        if run < 2:
            continue
        chunk = means[i - run + 1 : i + 1]
        finite = chunk[np.isfinite(chunk)]
        if finite.size >= 2:
            out[i] = float(np.std(finite))
    return out


def _pack(session: str, head, pack: dict, masks: dict, labels: list[str]) -> dict:
    cached = load_cache(session, WINDOW_S)
    times = np.asarray(cached["t"], dtype=np.float64)
    emb = np.asarray(cached["emb"], dtype=np.float32)
    y = np.asarray(cached["label"], dtype=np.int8)
    probs = _classify(emb, pack)
    score_t, raw, _ = _logits(head, session)
    raw = np.asarray(raw, dtype=np.float64)
    if not np.allclose(times, np.asarray(score_t, dtype=np.float64)):
        raise RuntimeError(f"{session} stamp mismatch")
    means = rolling_means([float(t) for t in times], [float(s) for s in raw], MEAN_WINDOW)
    mean_arr = np.asarray([np.nan if v is None else v for v in means], dtype=np.float64)
    hot = np.isfinite(mean_arr) & (mean_arr >= START_LINE)
    hot_run = _hot_run_lengths(hot)
    index = {name: i for i, name in enumerate(labels)}
    speech = probs[:, index["Speech"]]
    music = probs[:, index["Music"]]
    crowd = probs[:, index["Crowd"]]
    jingle = probs[:, index["Jingle (music)"]]
    features = np.column_stack(
        [
            mean_arr,
            raw,
            hot_run,
            _onset_rise(mean_arr, hot_run),
            _hot_stability(mean_arr, hot_run),
            speech,
            music,
            crowd,
            jingle,
            _causal_roll(speech, ROLL),
            _causal_roll(music, ROLL),
            _causal_roll(crowd, ROLL),
            _causal_roll(jingle, ROLL),
        ]
    ).astype(np.float64)
    # Fill leading roll NaNs with instantaneous values.
    for col in range(9, 13):
        bad = ~np.isfinite(features[:, col])
        features[bad, col] = features[bad, col - 4]
    # Cold stamps keep zeros for mean-derived cols already; replace non-finite means.
    features[~np.isfinite(features[:, 0]), 0] = 0.0
    features[~np.isfinite(features)] = 0.0
    return {
        "t": times,
        "y": y,
        "raw": raw,
        "mean": mean_arr,
        "hot": hot,
        "features": features,
        "commercials": pairs(masks[session], "verified_commercial"),
        "program": pairs(masks[session], "verified_program"),
    }


def main() -> None:
    pack = dict(np.load(CLASSIFIER, allow_pickle=False))
    labels = [str(name) for name in pack["labels"].tolist()]
    head, receipt = _fit_nbc()
    masks = bridge_masks()
    sessions = list(FIT) + sorted({row["session"] for row in HARD})
    data = {}
    for session in sessions:
        print("pack", session, flush=True)
        data[session] = _pack(session, head, pack, masks, labels)

    # Fit stage B on NBC hot seconds only.
    x_rows = []
    y_rows = []
    for session in FIT:
        block = data[session]
        keep = block["hot"] & (block["y"] >= 0)
        x_rows.append(block["features"][keep])
        y_rows.append(block["y"][keep])
    x = np.concatenate(x_rows)
    y = np.concatenate(y_rows).astype(np.int8)
    print(
        "stageB fit hot seconds",
        len(y),
        "commercial",
        int((y == 1).sum()),
        "program",
        int((y == 0).sum()),
        flush=True,
    )
    stage_b = LogisticRegression(max_iter=4000, class_weight="balanced")
    stage_b.fit(x, y)
    # Probability threshold on NBC hot seconds: midpoint of commercial p10 and program p90 of proba.
    proba = stage_b.predict_proba(x)[:, 1]
    c_p10 = float(np.percentile(proba[y == 1], 10))
    p_p90 = float(np.percentile(proba[y == 0], 90))
    b_line = float((c_p10 + p_p90) / 2.0)
    # Also report 0.5 for reference.
    placement = {
        "commercial_p10": round(c_p10, 6),
        "program_p90": round(p_p90, 6),
        "gap": round(c_p10 - p_p90, 6),
        "line": b_line,
        "line_half": 0.5,
    }
    print("stageB placement", placement, flush=True)

    feature_names = [
        "mean10",
        "raw",
        "hot_run_s",
        "onset_rise",
        "hot_stability",
        "speech",
        "music",
        "crowd",
        "jingle",
        "speech_roll10",
        "music_roll10",
        "crowd_roll10",
        "jingle_roll10",
    ]

    # Hard board.
    seconds = []
    boxes = []
    for case in HARD:
        session = case["session"]
        block = data[session]
        start = float(case["start_s"])
        end = float(case["end_s"])
        idx = np.where((block["t"] > start) & (block["t"] <= end + 1e-9))[0]
        for threshold_name, threshold in (("midpoint", b_line), ("half", 0.5)):
            for i in idx:
                stamp = float(block["t"][i])
                gold = _gold_label(stamp, block["commercials"], block["program"])
                hot_a = bool(block["hot"][i])
                prob = float(stage_b.predict_proba(block["features"][i : i + 1])[0, 1])
                hot_b = prob >= threshold
                final = hot_a and hot_b
                seconds.append(
                    {
                        "board_id": case["id"],
                        "threshold": threshold_name,
                        "session": session,
                        "stamp_s": stamp,
                        "gold": gold,
                        "expect_box": case["expect"],
                        "mean10": round(float(block["mean"][i]), 6) if np.isfinite(block["mean"][i]) else None,
                        "stage_a_hot": hot_a,
                        "stage_b_prob": round(prob, 6),
                        "stage_b_commercial": hot_b,
                        "final_hot": final,
                        "final_agrees_gold": (final and gold == "commercial")
                        or ((not final) and gold == "program"),
                        "hot_run_s": round(float(block["features"][i, 2]), 3),
                        "onset_rise": round(float(block["features"][i, 3]), 6),
                        "hot_stability": round(float(block["features"][i, 4]), 6),
                        "speech": round(float(block["features"][i, 5]), 6),
                        "music": round(float(block["features"][i, 6]), 6),
                    }
                )
        head_stats = {}
        for threshold_name, threshold in (("midpoint", b_line), ("half", 0.5), ("stage_a_only", None)):
            if threshold_name == "stage_a_only":
                rows = [row for row in seconds if row["board_id"] == case["id"] and row["threshold"] == "midpoint"]
                flags = [row["stage_a_hot"] for row in rows]
                med_prob = None
            else:
                rows = [row for row in seconds if row["board_id"] == case["id"] and row["threshold"] == threshold_name]
                flags = [row["final_hot"] for row in rows]
                med_prob = round(float(np.median([row["stage_b_prob"] for row in rows])), 6) if rows else None
            hot_frac = None if not flags else round(float(np.mean(flags)), 4)
            head_stats[threshold_name] = {
                "line": threshold,
                "median_stage_b_prob": med_prob,
                "hot_fraction": hot_frac,
                "verdict": _box_verdict(case["expect"], hot_frac),
            }
        boxes.append({**case, "heads": head_stats})
        print(
            case["id"],
            {k: v["verdict"] for k, v in head_stats.items()},
            "med_b",
            head_stats["midpoint"]["median_stage_b_prob"],
            flush=True,
        )

    # Compare stage_a_only vs midpoint / half.
    compare = []
    for box in boxes:
        base = box["heads"]["stage_a_only"]["verdict"]
        for name in ("midpoint", "half"):
            stats = box["heads"][name]
            compare.append(
                {
                    "board_id": box["id"],
                    "expect": box["expect"],
                    "stage_a": base,
                    "candidate": name,
                    "candidate_verdict": stats["verdict"],
                    "improved": base.startswith("MISS") and stats["verdict"].startswith("ok"),
                    "regressed": base.startswith("ok") and stats["verdict"].startswith("MISS"),
                }
            )

    # NBC hot-second accuracy for stage B alone.
    nbc_acc = {
        "n": int(len(y)),
        "accuracy_at_midpoint": round(float(np.mean((proba >= b_line) == (y == 1))), 4),
        "accuracy_at_half": round(float(np.mean((proba >= 0.5) == (y == 1))), 4),
        "commercial_recall_midpoint": round(float(np.mean(proba[y == 1] >= b_line)), 4),
        "program_reject_midpoint": round(float(np.mean(proba[y == 0] < b_line)), 4),
        "commercial_recall_half": round(float(np.mean(proba[y == 1] >= 0.5)), 4),
        "program_reject_half": round(float(np.mean(proba[y == 0] < 0.5)), 4),
    }

    summary = {
        "step": 3,
        "question": "When stage A is hot, is this a commercial pod or false-hot program?",
        "stage_a": {"line": START_LINE, "window": MEAN_WINDOW, "unchanged": True},
        "stage_b": {
            "features": feature_names,
            "fit": "NBC seconds with stage A already hot",
            "placement": placement,
            "nbc_hot_accuracy": nbc_acc,
            "coef": {name: round(float(coef), 6) for name, coef in zip(feature_names, stage_b.coef_[0])},
        },
        "fit_receipt": receipt,
        "model": MODEL_ID,
        "hard_boxes": boxes,
        "compare_to_stage_a": compare,
        "improved": sum(1 for row in compare if row["improved"]),
        "regressed": sum(1 for row in compare if row["regressed"]),
        "mute_unchanged": True,
        "realtime": False,
        "speaker_used": False,
    }
    DEST.mkdir(parents=True, exist_ok=True)
    (DEST / "step3_meta.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    with (DEST / "step3_hard_seconds.jsonl").open("w", encoding="utf-8") as handle:
        for row in seconds:
            handle.write(json.dumps(row) + "\n")
    print("improved", summary["improved"], "regressed", summary["regressed"])
    print("nbc", nbc_acc)
    print("wrote", DEST)


if __name__ == "__main__":
    main()
