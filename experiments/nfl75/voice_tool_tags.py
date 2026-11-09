"""Score owner speech boxes with frozen AudioSet class probabilities.

Uses the same 5-second CLS vectors that feed the commercial logistic. The
AudioSet head is the frozen MIT AST classifier (LayerNorm then Linear). No
speaker line moves. No mute rule changes. Path B boxes stay the probe set.

Stamp contract: a row stamped at t uses audio [t-5, t). A short box can sit
inside a lookback that is mostly outside the box. That is written on every row.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from experiments.nfl75.forensics import START_LINE
from experiments.nfl75.mean import rolling_means
from experiments.nfl75.persist import WINDOW_S, _fit_nbc, _logits
from tools.gpu_lab.embed import MODEL_ID
from tools.gpu_lab.learning_net.data import load_cache

REPO = Path(__file__).resolve().parents[2]
PATHB = REPO / "docs" / "ohush" / "research" / "OHUSH_VOICE_TRUTH_002" / "pathb.jsonl"
OUT = REPO / "docs" / "ohush" / "research" / "OHUSH_VOICE_TOOL_001"
CLASSIFIER = Path(r"C:\OHushData\gpu_lab\models\ast_audioset_classifier.npz")

WATCH = (
    "Speech",
    "Male speech, man speaking",
    "Female speech, woman speaking",
    "Narration, monologue",
    "Music",
    "Background music",
    "Theme music",
    "Jingle (music)",
    "Crowd",
    "Applause",
    "Cheering",
    "Hubbub, speech noise, speech babble",
    "Radio",
    "Television",
)

FOCUS = (
    ("fn0110", "Fanduel in game broadcast"),
    ("fn0009", "ryan fits"),
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


def _top(prob: np.ndarray, labels: list[str], n: int = 5) -> list[dict]:
    order = np.argsort(prob)[::-1][:n]
    return [{"class": labels[int(i)], "p": round(float(prob[int(i)]), 6)} for i in order]


def _watch(prob: np.ndarray, labels: list[str], index: dict[str, int]) -> dict[str, float]:
    out = {}
    for name in WATCH:
        out[name] = round(float(prob[index[name]]), 6) if name in index else None
    return out


def _overlap_inside(stamp: float, start: float, end: float) -> float:
    audio_start = stamp - WINDOW_S
    audio_end = stamp
    return max(0.0, min(audio_end, end) - max(audio_start, start)) / WINDOW_S


def _box_kind(row: dict) -> str:
    if row["id"] >= "fn0101":
        return "ad"
    if row.get("owner") and row["owner"] != "unnamed":
        return "booth"
    return "other"


def main() -> None:
    if not CLASSIFIER.is_file():
        raise RuntimeError(f"missing classifier extract at {CLASSIFIER}")
    pack = dict(np.load(CLASSIFIER, allow_pickle=False))
    labels = [str(name) for name in pack["labels"].tolist()]
    index = {name: i for i, name in enumerate(labels)}
    missing = [name for name in WATCH if name not in index]
    if missing:
        raise RuntimeError(f"watch classes missing from AudioSet labels: {missing}")

    rows = [json.loads(line) for line in PATHB.read_text(encoding="utf-8").splitlines() if line]
    sessions = sorted({row["session"] for row in rows})
    head, receipt = _fit_nbc()
    packed = {}
    for session in sessions:
        cached = load_cache(session, WINDOW_S)
        times = np.asarray(cached["t"], dtype=np.float64)
        emb = np.asarray(cached["emb"], dtype=np.float32)
        probs = _classify(emb, pack)
        score_times, scores, _labels = _logits(head, session)
        score_times = np.asarray(score_times, dtype=np.float64)
        scores = np.asarray(scores, dtype=np.float64)
        if not np.allclose(times, score_times):
            raise RuntimeError(f"{session}: embedding stamps and logistic stamps disagree")
        means = rolling_means([float(t) for t in times], [float(s) for s in scores], 10)
        mean_arr = np.asarray([np.nan if value is None else value for value in means], dtype=np.float64)
        packed[session] = {
            "t": times,
            "prob": probs,
            "raw": scores,
            "mean": mean_arr,
            "sidecar": {
                "model": MODEL_ID,
                "window_s": WINDOW_S,
                "n": int(len(times)),
                "path": str(cached["path"]),
            },
        }
        print(f"session {session} stamps {len(times)}", flush=True)

    OUT.mkdir(parents=True, exist_ok=True)
    seconds_path = OUT / "tags_seconds.jsonl"
    boxes_path = OUT / "tags_boxes.jsonl"
    second_rows = []
    box_rows = []

    for row in rows:
        if row.get("path_b") is None and row.get("reason") == "box shorter than 0.4s":
            box_rows.append(
                {
                    "id": row["id"],
                    "session": row["session"],
                    "abs_start_s": row["abs_start_s"],
                    "abs_end_s": row["abs_end_s"],
                    "owner_text": row.get("owner_text"),
                    "kind": _box_kind(row),
                    "skipped": "box shorter than 0.4s",
                    "n_stamps": 0,
                }
            )
            continue
        start = float(row["abs_start_s"])
        end = float(row["abs_end_s"])
        session = row["session"]
        times = packed[session]["t"]
        chosen = np.where((times > start) & (times <= end + 1e-9))[0]
        # Also keep any stamp whose 5s lookback overlaps the box, for audit.
        overlap = np.asarray([_overlap_inside(float(t), start, end) for t in times], dtype=np.float64)
        overlap_idx = np.where(overlap > 0)[0]
        inside = []
        for i in chosen:
            stamp = float(times[i])
            prob = packed[session]["prob"][i]
            raw = float(packed[session]["raw"][i])
            mean = packed[session]["mean"][i]
            item = {
                "id": row["id"],
                "session": session,
                "box_start_s": start,
                "box_end_s": end,
                "owner_text": row.get("owner_text"),
                "kind": _box_kind(row),
                "stamp_s": stamp,
                "audio_start_s": stamp - WINDOW_S,
                "audio_end_s": stamp,
                "lookback_inside_box": round(float(overlap[i]), 4),
                "commercial_raw": round(raw, 6),
                "commercial_mean10": None if not np.isfinite(mean) else round(float(mean), 6),
                "commercial_hot": bool(np.isfinite(mean) and float(mean) >= START_LINE),
                "top5": _top(prob, labels),
                "watch": _watch(prob, labels, index),
                "path_b_name": None if not row.get("path_b") else row["path_b"].get("name"),
                "path_b_cosine": None if not row.get("path_b") else row["path_b"].get("cosine"),
            }
            inside.append(item)
            second_rows.append(item)

        overlap_only = [
            {
                "stamp_s": float(times[i]),
                "lookback_inside_box": round(float(overlap[i]), 4),
                "top1": _top(packed[session]["prob"][i], labels, 1)[0],
                "commercial_mean10": None
                if not np.isfinite(packed[session]["mean"][i])
                else round(float(packed[session]["mean"][i]), 6),
            }
            for i in overlap_idx
            if i not in set(chosen.tolist())
        ]

        def median_watch(name: str) -> float | None:
            if not inside:
                return None
            return round(float(np.median([item["watch"][name] for item in inside])), 6)

        top1_counts: dict[str, int] = {}
        for item in inside:
            name = item["top5"][0]["class"]
            top1_counts[name] = top1_counts.get(name, 0) + 1
        box_rows.append(
            {
                "id": row["id"],
                "session": session,
                "abs_start_s": start,
                "abs_end_s": end,
                "seconds": round(end - start, 4),
                "owner": row.get("owner"),
                "owner_text": row.get("owner_text"),
                "kind": _box_kind(row),
                "n_stamps": len(inside),
                "n_overlap_stamps": int(len(overlap_idx)),
                "median_lookback_inside_box": None
                if not inside
                else round(float(np.median([item["lookback_inside_box"] for item in inside])), 4),
                "min_lookback_inside_box": None
                if not inside
                else round(float(np.min([item["lookback_inside_box"] for item in inside])), 4),
                "median_commercial_mean10": None
                if not inside
                else round(
                    float(np.nanmedian([item["commercial_mean10"] for item in inside if item["commercial_mean10"] is not None])),
                    6,
                )
                if any(item["commercial_mean10"] is not None for item in inside)
                else None,
                "hot_fraction": None
                if not inside
                else round(float(np.mean([1.0 if item["commercial_hot"] else 0.0 for item in inside])), 4),
                "top1_counts": dict(sorted(top1_counts.items(), key=lambda kv: (-kv[1], kv[0]))),
                "median_watch": {name: median_watch(name) for name in WATCH},
                "path_b": row.get("path_b"),
                "overlap_stamps_outside_end": overlap_only[:8],
            }
        )

    seconds_path.write_text("\n".join(json.dumps(row) for row in second_rows) + ("\n" if second_rows else ""), encoding="utf-8")
    boxes_path.write_text("\n".join(json.dumps(row) for row in box_rows) + ("\n" if box_rows else ""), encoding="utf-8")

    meta = {
        "model": MODEL_ID,
        "classifier_extract": str(CLASSIFIER),
        "window_s": WINDOW_S,
        "commercial_line": START_LINE,
        "stamp_contract": "stamp t uses audio [t-window_s, t)",
        "box_stamp_rule": "include stamps with start < t <= end",
        "fit_receipt": receipt,
        "watch_classes": list(WATCH),
        "n_boxes": len(box_rows),
        "n_seconds": len(second_rows),
        "sessions": {session: packed[session]["sidecar"] for session in sessions},
        "focus": [{"id": clip_id, "owner_text": text} for clip_id, text in FOCUS],
        "realtime": False,
    }
    (OUT / "tags_meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")

    print("FOCUS FanDuel vs Fitzpatrick", flush=True)
    for clip_id, text in FOCUS:
        matches = [row for row in box_rows if row["id"] == clip_id and row.get("owner_text") == text]
        if not matches:
            matches = [row for row in box_rows if row["id"] == clip_id]
        for row in matches:
            print(
                json.dumps(
                    {
                        "id": row["id"],
                        "owner_text": row["owner_text"],
                        "n_stamps": row["n_stamps"],
                        "median_lookback_inside_box": row["median_lookback_inside_box"],
                        "median_commercial_mean10": row["median_commercial_mean10"],
                        "hot_fraction": row["hot_fraction"],
                        "top1_counts": row["top1_counts"],
                        "Speech": row["median_watch"]["Speech"],
                        "Music": row["median_watch"]["Music"],
                        "Background music": row["median_watch"]["Background music"],
                        "Jingle (music)": row["median_watch"]["Jingle (music)"],
                        "Crowd": row["median_watch"]["Crowd"],
                        "path_b": row["path_b"],
                    },
                    sort_keys=False,
                ),
                flush=True,
            )
            for item in second_rows:
                if item["id"] != clip_id or item["owner_text"] != row["owner_text"]:
                    continue
                print(
                    f"  t={item['stamp_s']:.1f} inside={item['lookback_inside_box']:.2f} "
                    f"mean10={item['commercial_mean10']} top={item['top5'][0]['class']}:{item['top5'][0]['p']:.3f} "
                    f"Speech={item['watch']['Speech']:.3f} Music={item['watch']['Music']:.3f} "
                    f"BgMusic={item['watch']['Background music']:.3f} Jingle={item['watch']['Jingle (music)']:.3f} "
                    f"Crowd={item['watch']['Crowd']:.3f}",
                    flush=True,
                )

    print("wrote", seconds_path)
    print("wrote", boxes_path)
    print("boxes", len(box_rows), "seconds", len(second_rows))


if __name__ == "__main__":
    main()
