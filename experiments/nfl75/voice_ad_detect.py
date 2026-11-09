"""Step 1 of OHUSH_AD_DETECT_001: raw commercial-detection board.

    python -m experiments.nfl75.voice_ad_detect

Job under test: is this second advertising or programming?
Not: who is speaking.

This step does not train a new head. It dumps the frozen 10-second mean
and the frozen AudioSet class names on a fixed hard-case board, plus a
small control sample, so the failures are reviewable before any new fit.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from experiments.nfl75.forensics import START_LINE
from experiments.nfl75.mean import PRIME_SESSIONS, rolling_means
from experiments.nfl75.persist import FIT, WINDOW_S, _fit_nbc, _logits
from tools.gpu_lab.embed import MODEL_ID
from tools.gpu_lab.ladder import pairs
from tools.gpu_lab.learning_net.data import bridge_masks, load_cache

REPO = Path(__file__).resolve().parents[2]
RESEARCH = REPO / "docs" / "ohush" / "research"
DEST = RESEARCH / "OHUSH_AD_DETECT_001"
CLASSIFIER = Path(r"C:\OHushData\gpu_lab\models\ast_audioset_classifier.npz")
NAMES = RESEARCH / "VOICE_ROSTER_001" / "names.jsonl"

WATCH = (
    "Speech",
    "Music",
    "Background music",
    "Theme music",
    "Jingle (music)",
    "Crowd",
    "Applause",
    "Cheering",
    "Narration, monologue",
    "Male speech, man speaking",
    "Female speech, woman speaking",
)

# Fixed board. Times are absolute session seconds.
HARD = (
    {
        "id": "ad_draftkings",
        "session": "hush_20261008_205100",
        "start_s": 140.78,
        "end_s": 146.0,
        "expect": "commercial",
        "note": "DraftKings; owner: Clarissa Thompson reading the ad",
    },
    {
        "id": "ad_fanduel",
        "session": "hush_20261008_205100",
        "start_s": 572.06,
        "end_s": 577.3,
        "expect": "commercial",
        "note": "FanDuel; owner: unknown male",
    },
    {
        "id": "ad_wendys",
        "session": "hush_20261008_205100",
        "start_s": 4450.36,
        "end_s": 4455.9,
        "expect": "commercial",
        "note": "Wendy's; owner: unknown female",
    },
    {
        "id": "prog_fitzpatrick",
        "session": "hush_20260924_220624",
        "start_s": 6589.0,
        "end_s": 6609.0,
        "expect": "program",
        "note": "Ryan Fitzpatrick pregame desk",
    },
    {
        "id": "prog_thompson_postgame",
        "session": "hush_20260924_220624",
        "start_s": 5571.0,
        "end_s": 5581.0,
        "expect": "program",
        "note": "Clarissa Thompson postgame",
    },
    {
        "id": "prog_whitworth",
        "session": "hush_20261008_205100",
        "start_s": 9163.76,
        "end_s": 9171.77,
        "expect": "program",
        "note": "Andrew Whitworth after dropped pass",
    },
    {
        "id": "prog_sherman",
        "session": "hush_20261008_205100",
        "start_s": 9153.0,
        "end_s": 9163.51,
        "expect": "program",
        "note": "Richard Sherman; gold program, desk-like",
    },
)


def _softmax(logits: np.ndarray) -> np.ndarray:
    shifted = logits - logits.max(axis=1, keepdims=True)
    exp = np.exp(shifted)
    return exp / exp.sum(axis=1, keepdims=True)


def _classify(vectors: np.ndarray, pack: dict) -> np.ndarray:
    eps = float(pack["eps"][0])
    mean = vectors.mean(axis=1, keepdims=True)
    var = vectors.var(axis=1, keepdims=True)
    normed = (vectors - mean) / np.sqrt(var + eps)
    normed = normed * pack["ln_weight"] + pack["ln_bias"]
    logits = normed @ pack["dense_weight"].T + pack["dense_bias"]
    return _softmax(logits.astype(np.float64))


def _gold_label(moment: float, commercials: list[tuple[float, float]], program: list[tuple[float, float]]) -> str:
    for start, end in commercials:
        if start - 1e-9 <= moment < end - 1e-9:
            return "commercial"
    for start, end in program:
        if start - 1e-9 <= moment < end - 1e-9:
            return "program"
    return "other"


def _top(prob: np.ndarray, labels: list[str], n: int = 5) -> list[dict]:
    order = np.argsort(prob)[::-1][:n]
    return [{"class": labels[int(i)], "p": round(float(prob[int(i)]), 6)} for i in order]


def main() -> None:
    if not CLASSIFIER.is_file():
        raise RuntimeError(f"missing classifier extract {CLASSIFIER}")
    pack = dict(np.load(CLASSIFIER, allow_pickle=False))
    labels = [str(name) for name in pack["labels"].tolist()]
    index = {name: i for i, name in enumerate(labels)}
    for name in WATCH:
        if name not in index:
            raise RuntimeError(f"missing watch class {name}")

    head, receipt = _fit_nbc()
    masks = bridge_masks()
    sessions = sorted({row["session"] for row in HARD} | set(PRIME_SESSIONS))
    packed = {}
    for session in sessions:
        cached = load_cache(session, WINDOW_S)
        times = np.asarray(cached["t"], dtype=np.float64)
        emb = np.asarray(cached["emb"], dtype=np.float32)
        probs = _classify(emb, pack)
        score_t, scores, _lab = _logits(head, session)
        score_t = np.asarray(score_t, dtype=np.float64)
        scores = np.asarray(scores, dtype=np.float64)
        if not np.allclose(times, score_t):
            raise RuntimeError(f"{session}: stamp mismatch")
        means = rolling_means([float(t) for t in times], [float(s) for s in scores], 10)
        mean_arr = np.asarray([np.nan if value is None else value for value in means], dtype=np.float64)
        commercials = pairs(masks[session], "verified_commercial")
        program = pairs(masks[session], "verified_program")
        packed[session] = {
            "t": times,
            "raw": scores,
            "mean": mean_arr,
            "prob": probs,
            "commercials": commercials,
            "program": program,
        }
        print(session, "stamps", len(times), flush=True)

    DEST.mkdir(parents=True, exist_ok=True)
    seconds = []
    boxes = []
    for case in HARD:
        session = case["session"]
        start = float(case["start_s"])
        end = float(case["end_s"])
        block = packed[session]
        chosen = np.where((block["t"] > start) & (block["t"] <= end + 1e-9))[0]
        rows = []
        for i in chosen:
            stamp = float(block["t"][i])
            prob = block["prob"][i]
            raw = float(block["raw"][i])
            mean = block["mean"][i]
            gold = _gold_label(stamp, block["commercials"], block["program"])
            hot = bool(np.isfinite(mean) and float(mean) >= START_LINE)
            # Desired mute open = gold commercial. Desired play = gold program.
            agree = (hot and gold == "commercial") or ((not hot) and gold == "program")
            item = {
                "board_id": case["id"],
                "session": session,
                "stamp_s": stamp,
                "audio_start_s": stamp - WINDOW_S,
                "gold": gold,
                "expect_box": case["expect"],
                "commercial_raw": round(raw, 6),
                "commercial_mean10": None if not np.isfinite(mean) else round(float(mean), 6),
                "hot": hot,
                "mean_agrees_gold": agree,
                "top5": _top(prob, labels),
                "watch": {name: round(float(prob[index[name]]), 6) for name in WATCH},
            }
            rows.append(item)
            seconds.append(item)
        hot_frac = None if not rows else round(float(np.mean([1.0 if r["hot"] else 0.0 for r in rows])), 4)
        agree_frac = None if not rows else round(float(np.mean([1.0 if r["mean_agrees_gold"] else 0.0 for r in rows])), 4)
        med_mean = None
        finite = [r["commercial_mean10"] for r in rows if r["commercial_mean10"] is not None]
        if finite:
            med_mean = round(float(np.median(finite)), 6)
        boxes.append(
            {
                **case,
                "n_stamps": len(rows),
                "median_mean10": med_mean,
                "hot_fraction": hot_frac,
                "mean_agrees_gold_fraction": agree_frac,
                "verdict": _box_verdict(case["expect"], hot_frac),
            }
        )
        print(
            case["id"],
            "expect",
            case["expect"],
            "hot",
            hot_frac,
            "agree_gold",
            agree_frac,
            "median",
            med_mean,
            "->",
            boxes[-1]["verdict"],
            flush=True,
        )

    # Control sample: 20 random clear commercial and 20 clear program seconds on each Prime tape.
    rng = np.random.default_rng(0)
    controls = []
    for session in PRIME_SESSIONS:
        block = packed[session]
        gold = np.asarray(
            [_gold_label(float(t), block["commercials"], block["program"]) for t in block["t"]],
            dtype=object,
        )
        for kind in ("commercial", "program"):
            idx = np.flatnonzero(gold == kind)
            if len(idx) == 0:
                continue
            pick = rng.choice(idx, size=min(20, len(idx)), replace=False)
            for i in sorted(int(x) for x in pick):
                stamp = float(block["t"][i])
                mean = block["mean"][i]
                hot = bool(np.isfinite(mean) and float(mean) >= START_LINE)
                controls.append(
                    {
                        "session": session,
                        "stamp_s": stamp,
                        "gold": kind,
                        "commercial_raw": round(float(block["raw"][i]), 6),
                        "commercial_mean10": None if not np.isfinite(mean) else round(float(mean), 6),
                        "hot": hot,
                        "mean_agrees_gold": (hot and kind == "commercial") or ((not hot) and kind == "program"),
                        "top1": _top(block["prob"][i], labels, 1)[0],
                        "Speech": round(float(block["prob"][i][index["Speech"]]), 6),
                        "Music": round(float(block["prob"][i][index["Music"]]), 6),
                    }
                )

    control_summary = []
    for session in PRIME_SESSIONS:
        for kind in ("commercial", "program"):
            rows = [r for r in controls if r["session"] == session and r["gold"] == kind]
            if not rows:
                continue
            control_summary.append(
                {
                    "session": session,
                    "gold": kind,
                    "n": len(rows),
                    "hot_fraction": round(float(np.mean([1.0 if r["hot"] else 0.0 for r in rows])), 4),
                    "agree_fraction": round(float(np.mean([1.0 if r["mean_agrees_gold"] else 0.0 for r in rows])), 4),
                    "median_mean10": round(
                        float(np.median([r["commercial_mean10"] for r in rows if r["commercial_mean10"] is not None])),
                        6,
                    ),
                }
            )

    meta = {
        "step": 1,
        "question": "Is this second advertising or programming?",
        "not_the_question": "Who is speaking?",
        "model": MODEL_ID,
        "window_s": WINDOW_S,
        "commercial_line": START_LINE,
        "fit_receipt": receipt,
        "fit_sessions": list(FIT),
        "logic": {
            "hot": "10-second mean of the NBC logistic on AST CLS >= 0.1632588496059179",
            "desired_on_commercial": "hot",
            "desired_on_program": "cold",
            "speaker_score": "not used",
        },
        "hard_boxes": boxes,
        "control_summary": control_summary,
        "n_hard_seconds": len(seconds),
        "n_control_seconds": len(controls),
    }
    (DEST / "step1_meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    with (DEST / "step1_hard_seconds.jsonl").open("w", encoding="utf-8") as handle:
        for row in seconds:
            handle.write(json.dumps(row) + "\n")
    with (DEST / "step1_controls.jsonl").open("w", encoding="utf-8") as handle:
        for row in controls:
            handle.write(json.dumps(row) + "\n")
    print("wrote", DEST)
    print("controls", json.dumps(control_summary))


def _box_verdict(expect: str, hot_frac: float | None) -> str:
    if hot_frac is None:
        return "no_stamps"
    mostly_hot = hot_frac >= 0.5
    if expect == "commercial" and mostly_hot:
        return "ok_commercial_hot"
    if expect == "program" and not mostly_hot:
        return "ok_program_cold"
    if expect == "commercial" and not mostly_hot:
        return "MISS_commercial_cold"
    return "MISS_program_hot"


if __name__ == "__main__":
    main()
