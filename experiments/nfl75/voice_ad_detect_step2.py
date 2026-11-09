"""Step 2 of OHUSH_AD_DETECT_001: new audio-only ad heads vs the frozen mean.

    python -m experiments.nfl75.voice_ad_detect_step2

Logic:
  - Job is advertising vs programming. Speaker unused.
  - Fit only on the two NBC games. Prime hard board is held out.
  - Each new head is a logistic on audio features, then the same 10-second
    causal mean used by the frozen tool. The start line is chosen on NBC
    only (midpoint of commercial p10 and program p90), then frozen for Prime.
  - Heads:
      frozen_cls   — published NBC CLS logistic (reference)
      class527     — logistic on AudioSet class probabilities
      watch_seq    — watch classes plus 10s causal rolls of Speech/Music/Crowd/Jingle
      class527_hard — class527 with extra weight on NBC program seconds the
                      frozen mean already heats (train-time hard negatives)

No mute rule is installed. Realtime false.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression

from experiments.nfl75.forensics import START_LINE
from experiments.nfl75.mean import rolling_means
from experiments.nfl75.persist import FIT, WINDOW_S, _fit_nbc, _logits
from experiments.nfl75.voice_ad_detect import HARD, WATCH, _box_verdict, _classify, _gold_label
from tools.gpu_lab.embed import MODEL_ID
from tools.gpu_lab.ladder import pairs
from tools.gpu_lab.learning_net.data import bridge_masks, load_cache

REPO = Path(__file__).resolve().parents[2]
DEST = REPO / "docs" / "ohush" / "research" / "OHUSH_AD_DETECT_001"
CLASSIFIER = Path(r"C:\OHushData\gpu_lab\models\ast_audioset_classifier.npz")
MEAN_WINDOW = 10
HARD_WEIGHT = 5.0


def _line_from_means(means: np.ndarray, labels: np.ndarray) -> dict:
    commercial = means[(labels == 1) & np.isfinite(means)]
    program = means[(labels == 0) & np.isfinite(means)]
    if commercial.size == 0 or program.size == 0:
        raise RuntimeError("need commercial and program seconds to place a line")
    c_p10 = float(np.percentile(commercial, 10))
    p_p90 = float(np.percentile(program, 90))
    return {
        "commercial_p10": round(c_p10, 6),
        "program_p90": round(p_p90, 6),
        "gap": round(c_p10 - p_p90, 6),
        "line": float((c_p10 + p_p90) / 2.0),
    }


def _watch_matrix(probs: np.ndarray, labels: list[str]) -> np.ndarray:
    index = {name: i for i, name in enumerate(labels)}
    cols = [probs[:, index[name]] for name in WATCH]
    return np.column_stack(cols).astype(np.float64)


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


def _seq_features(probs: np.ndarray, labels: list[str]) -> np.ndarray:
    watch = _watch_matrix(probs, labels)
    index = {name: i for i, name in enumerate(labels)}
    filled = []
    for name in ("Speech", "Music", "Crowd", "Jingle (music)"):
        inst = probs[:, index[name]]
        col = _causal_roll(inst, MEAN_WINDOW)
        missing = ~np.isfinite(col)
        col[missing] = inst[missing]
        filled.append(col)
    return np.column_stack([watch, np.column_stack(filled)]).astype(np.float64)


def _pack_session(session: str, head_cls, pack: dict, label_names: list[str], masks: dict) -> dict:
    cached = load_cache(session, WINDOW_S)
    times = np.asarray(cached["t"], dtype=np.float64)
    emb = np.asarray(cached["emb"], dtype=np.float32)
    y = np.asarray(cached["label"], dtype=np.int8)
    probs = _classify(emb, pack)
    score_t, raw, _ = _logits(head_cls, session)
    raw = np.asarray(raw, dtype=np.float64)
    if not np.allclose(times, np.asarray(score_t, dtype=np.float64)):
        raise RuntimeError(f"{session}: stamp mismatch")
    return {
        "t": times,
        "y": y,
        "emb": emb,
        "probs": probs,
        "raw": raw,
        "watch_seq": _seq_features(probs, label_names),
        "commercials": pairs(masks[session], "verified_commercial"),
        "program": pairs(masks[session], "verified_program"),
    }


def _fit_head(x: np.ndarray, y: np.ndarray, sample_weight: np.ndarray | None = None):
    model = LogisticRegression(max_iter=4000, class_weight="balanced")
    model.fit(x, y, sample_weight=sample_weight)
    return model


def _score_head(model, x: np.ndarray) -> np.ndarray:
    return np.asarray(model.decision_function(x), dtype=np.float64)


def main() -> None:
    pack = dict(np.load(CLASSIFIER, allow_pickle=False))
    label_names = [str(name) for name in pack["labels"].tolist()]
    head_cls, receipt = _fit_nbc()
    masks = bridge_masks()
    sessions = list(FIT) + sorted({row["session"] for row in HARD})
    data = {}
    for session in sessions:
        print("pack", session, flush=True)
        data[session] = _pack_session(session, head_cls, pack, label_names, masks)

    # NBC fit rows.
    x527 = []
    xseq = []
    y_fit = []
    frozen_raw = []
    for session in FIT:
        block = data[session]
        keep = block["y"] >= 0
        x527.append(block["probs"][keep])
        xseq.append(block["watch_seq"][keep])
        y_fit.append(block["y"][keep])
        frozen_raw.append(block["raw"][keep])
    x527 = np.concatenate(x527)
    xseq = np.concatenate(xseq)
    y_fit = np.concatenate(y_fit).astype(np.int8)
    frozen_raw = np.concatenate(frozen_raw)

    print("fit rows", len(y_fit), "commercial", int((y_fit == 1).sum()), flush=True)
    model_527 = _fit_head(x527, y_fit)
    model_seq = _fit_head(xseq, y_fit)

    # Hard-negative weights on NBC: program seconds already hot under frozen mean.
    frozen_means_fit = []
    for session in FIT:
        block = data[session]
        means = rolling_means([float(t) for t in block["t"]], [float(s) for s in block["raw"]], MEAN_WINDOW)
        mean_arr = np.asarray([np.nan if v is None else v for v in means], dtype=np.float64)
        keep = block["y"] >= 0
        frozen_means_fit.append(mean_arr[keep])
    frozen_means_fit = np.concatenate(frozen_means_fit)
    weights = np.ones(len(y_fit), dtype=np.float64)
    hard = (y_fit == 0) & np.isfinite(frozen_means_fit) & (frozen_means_fit >= START_LINE)
    weights[hard] = HARD_WEIGHT
    print("nbc program-hot hard negatives", int(hard.sum()), flush=True)
    model_hard = _fit_head(x527, y_fit, sample_weight=weights)

    heads = {
        "frozen_cls": None,
        "class527": model_527,
        "watch_seq": model_seq,
        "class527_hard": model_hard,
    }

    # Place lines on NBC for each head.
    placements = {}
    nbc_means = {}
    for name, model in heads.items():
        per_session_scores = {}
        all_means = []
        all_labels = []
        for session in FIT:
            block = data[session]
            if name == "frozen_cls":
                scores = block["raw"]
            elif name == "watch_seq":
                scores = _score_head(model, block["watch_seq"])
            else:
                scores = _score_head(model, block["probs"])
            means = rolling_means([float(t) for t in block["t"]], [float(s) for s in scores], MEAN_WINDOW)
            mean_arr = np.asarray([np.nan if v is None else v for v in means], dtype=np.float64)
            per_session_scores[session] = {"scores": scores, "means": mean_arr}
            keep = block["y"] >= 0
            all_means.append(mean_arr[keep])
            all_labels.append(block["y"][keep])
        if name == "frozen_cls":
            placements[name] = {
                "commercial_p10": None,
                "program_p90": None,
                "gap": None,
                "line": START_LINE,
                "source": "published",
            }
        else:
            placements[name] = _line_from_means(np.concatenate(all_means), np.concatenate(all_labels))
        nbc_means[name] = per_session_scores
        print(name, "line", placements[name]["line"], "gap", placements[name].get("gap"), flush=True)

    # Score Prime hard board + NBC diagnostics.
    board_rows = []
    box_summaries = []
    for case in HARD:
        session = case["session"]
        block = data[session]
        start = float(case["start_s"])
        end = float(case["end_s"])
        idx = np.where((block["t"] > start) & (block["t"] <= end + 1e-9))[0]
        head_stats = {}
        for name, model in heads.items():
            if name == "frozen_cls":
                scores = block["raw"]
            elif name == "watch_seq":
                scores = _score_head(model, block["watch_seq"])
            else:
                scores = _score_head(model, block["probs"])
            means = rolling_means([float(t) for t in block["t"]], [float(s) for s in scores], MEAN_WINDOW)
            mean_arr = np.asarray([np.nan if v is None else v for v in means], dtype=np.float64)
            line = float(placements[name]["line"])
            vals = mean_arr[idx]
            finite = vals[np.isfinite(vals)]
            hot_frac = None if finite.size == 0 else round(float(np.mean(finite >= line)), 4)
            med = None if finite.size == 0 else round(float(np.median(finite)), 6)
            head_stats[name] = {
                "line": line,
                "median_mean10": med,
                "hot_fraction": hot_frac,
                "verdict": _box_verdict(case["expect"], hot_frac),
            }
            for i in idx:
                stamp = float(block["t"][i])
                mean = mean_arr[i]
                gold = _gold_label(stamp, block["commercials"], block["program"])
                hot = bool(np.isfinite(mean) and float(mean) >= line)
                board_rows.append(
                    {
                        "board_id": case["id"],
                        "head": name,
                        "session": session,
                        "stamp_s": stamp,
                        "gold": gold,
                        "expect_box": case["expect"],
                        "mean10": None if not np.isfinite(mean) else round(float(mean), 6),
                        "raw": round(float(scores[i]), 6),
                        "line": line,
                        "hot": hot,
                        "mean_agrees_gold": (hot and gold == "commercial")
                        or ((not hot) and gold == "program"),
                    }
                )
        box_summaries.append({**case, "heads": head_stats})
        print(
            case["id"],
            {k: v["verdict"] for k, v in head_stats.items()},
            flush=True,
        )

    # Control sample comparison on Prime sessions present in HARD.
    rng = np.random.default_rng(0)
    control_summary = []
    prime_sessions = sorted({row["session"] for row in HARD})
    for session in prime_sessions:
        block = data[session]
        gold = np.asarray(
            [_gold_label(float(t), block["commercials"], block["program"]) for t in block["t"]],
            dtype=object,
        )
        for kind in ("commercial", "program"):
            pool = np.flatnonzero(gold == kind)
            if len(pool) == 0:
                continue
            pick = rng.choice(pool, size=min(20, len(pool)), replace=False)
            for name, model in heads.items():
                if name == "frozen_cls":
                    scores = block["raw"]
                elif name == "watch_seq":
                    scores = _score_head(model, block["watch_seq"])
                else:
                    scores = _score_head(model, block["probs"])
                means = rolling_means([float(t) for t in block["t"]], [float(s) for s in scores], MEAN_WINDOW)
                mean_arr = np.asarray([np.nan if v is None else v for v in means], dtype=np.float64)
                line = float(placements[name]["line"])
                rows = []
                for i in pick:
                    mean = mean_arr[int(i)]
                    if not np.isfinite(mean):
                        continue
                    hot = float(mean) >= line
                    rows.append(hot == (kind == "commercial"))
                if not rows:
                    continue
                control_summary.append(
                    {
                        "session": session,
                        "gold": kind,
                        "head": name,
                        "n": len(rows),
                        "agree_fraction": round(float(np.mean(rows)), 4),
                    }
                )

    # Win/lose vs frozen on the hard board.
    compare = []
    for box in box_summaries:
        frozen = box["heads"]["frozen_cls"]["verdict"]
        for name, stats in box["heads"].items():
            if name == "frozen_cls":
                continue
            compare.append(
                {
                    "board_id": box["id"],
                    "expect": box["expect"],
                    "frozen": frozen,
                    "candidate": name,
                    "candidate_verdict": stats["verdict"],
                    "improved": frozen.startswith("MISS") and stats["verdict"].startswith("ok"),
                    "regressed": frozen.startswith("ok") and stats["verdict"].startswith("MISS"),
                }
            )

    DEST.mkdir(parents=True, exist_ok=True)
    summary = {
        "step": 2,
        "question": "Is this second advertising or programming?",
        "speaker_used": False,
        "model": MODEL_ID,
        "fit_sessions": list(FIT),
        "fit_receipt": receipt,
        "mean_window": MEAN_WINDOW,
        "hard_weight": HARD_WEIGHT,
        "nbc_program_hot_count": int(hard.sum()),
        "placements": placements,
        "hard_boxes": box_summaries,
        "compare_to_frozen": compare,
        "control_summary": control_summary,
        "mute_unchanged": True,
        "realtime": False,
    }
    (DEST / "step2_meta.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    with (DEST / "step2_hard_seconds.jsonl").open("w", encoding="utf-8") as handle:
        for row in board_rows:
            handle.write(json.dumps(row) + "\n")
    print("improved", sum(1 for row in compare if row["improved"]))
    print("regressed", sum(1 for row in compare if row["regressed"]))
    print("wrote", DEST)


if __name__ == "__main__":
    main()
