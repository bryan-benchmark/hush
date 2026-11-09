"""Are the loud NBC show stretches one repeated sound?

The stretches were named on Sept 13 NBC before this listen: 1011–1124 and
10151–11419. This script stays on that game. It compares the clear show
seconds there whose Music score reaches the commercial-music median against
each other, and against ordinary show seconds on the same tape. The
fingerprint accept count stays 200. No cutoff moves, and no later game is
opened.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy.signal import resample_poly

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "experiments/broadcast_intelligence/third_party/audfprint"))

from experiments.broadcast_intelligence.batch1 import read_span  # noqa: E402
from experiments.measurement.sting_landmarks_001 import (  # noqa: E402
    PUBLISHED_COUNT,
    best_match,
    build_index,
    fingerprint,
)
from experiments.measurement.supervised_clear_ceiling_001 import _lookback_commercial  # noqa: E402
from experiments.measurement.supervised_heldout_001 import FIT, WINDOW_S, _fit, _scores  # noqa: E402
from experiments.measurement.supervised_name_scores_001 import _top_name  # noqa: E402
from hush.audio import find_session, load_session  # noqa: E402
from tools.gpu_lab.ladder import pairs  # noqa: E402
from tools.gpu_lab.learning_net.data import bridge_masks, load_cache  # noqa: E402

OUT = REPO / "docs" / "ohush" / "research" / "SUPERVISED_STRETCH_001"
SESSION = "hush_20260913_210542"
SPANS = ((1011.0, 1124.0), (10151.0, 11419.0))
CONTROL_STRIDE_S = 600.0
RECORDINGS = REPO / "recordings"


def _span_name(moment: float) -> str:
    for index, (start, end) in enumerate(SPANS):
        if start <= moment <= end:
            return f"stretch_{index + 1}"
    return "other_tail"


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12))


def _mean_pairs(rows: list[dict], other: list[dict] | None = None) -> float | None:
    values = []
    if other is None:
        for i, left in enumerate(rows):
            for right in rows[i + 1 :]:
                values.append(_cosine(left["emb"], right["emb"]))
    else:
        for left in rows:
            for right in other:
                values.append(_cosine(left["emb"], right["emb"]))
    if not values:
        return None
    return round(float(np.mean(values)), 4)


HEARD = ("Music", "Speech", "Crowd", "Applause", "Cheering", "Chatter")


def _heard(vectors: np.ndarray) -> list[dict]:
    import torch
    from transformers import AutoModelForAudioClassification

    from tools.gpu_lab.embed import MODEL_ID

    model = AutoModelForAudioClassification.from_pretrained(MODEL_ID)
    model.eval()
    labels = [model.config.id2label[index] for index in range(model.config.num_labels)]
    wanted = [labels.index(name) for name in HEARD if name in labels]
    with torch.inference_mode():
        logits = model.classifier(torch.tensor(vectors)).detach().cpu().numpy()
    logits = logits - logits.max(axis=1, keepdims=True)
    prob = np.exp(logits)
    prob /= prob.sum(axis=1, keepdims=True)
    rows = []
    for one in prob:
        rows.append({labels[index]: round(float(one[index]), 4) for index in wanted})
    return rows


def _window(folder, meta, end: float) -> np.ndarray:
    audio = read_span(folder, meta, end - WINDOW_S, end)
    mono = audio.mean(axis=1).astype(np.float32)
    return resample_poly(mono, 147, 640).astype(np.float32)


def _best_against(row: dict, library: list[dict]) -> dict:
    best = {"score": 0, "t": None}
    for other in library:
        if other["t"] == row["t"] and other["group"] == row["group"]:
            continue
        solo = dict(other)
        solo["id"] = 0
        found = best_match(row["frames"], row["hashes"], build_index([solo]), np.ones(1, dtype=bool))
        if int(found["score"]) > best["score"]:
            best = {"score": int(found["score"]), "t": other["t"], "group": other["group"]}
    return best


def main() -> None:
    masks = bridge_masks()
    head, _receipt = _fit(FIT)
    music_scores = []
    tail = []
    span_trace = {name: [] for name in ("stretch_1", "stretch_2")}
    for session in FIT:
        cache = load_cache(session, WINDOW_S)
        times, scores, labels = _scores(head, session)
        names, _confidence = _top_name(cache["emb"])
        commercials = pairs(masks[session], "verified_commercial")
        for index, (moment, score, label, name) in enumerate(zip(times, scores, labels, names)):
            moment = float(moment)
            if int(label) == 1 and str(name) == "Music":
                music_scores.append(float(score))
            if session != SESSION:
                continue
            group = _span_name(moment)
            if group.startswith("stretch"):
                span_trace[group].append({"t": round(moment, 3), "score": round(float(score), 3), "name": str(name)})
            if int(label) != 0 or str(name) != "Music":
                continue
            if _lookback_commercial(moment, commercials) > 1e-9:
                continue
            tail.append(
                {
                    "id": len(tail),
                    "t": round(moment, 3),
                    "score": float(score),
                    "group": group,
                    "emb": cache["emb"][index],
                }
            )
    if not music_scores:
        raise SystemExit("no commercial music seconds")
    music_median = float(np.median(music_scores))
    tail = [row for row in tail if row["score"] >= music_median]
    for index, row in enumerate(tail):
        row["id"] = index

    commercials = pairs(masks[SESSION], "verified_commercial")
    coverage = pairs(masks[SESSION], "coverage")[0]
    cache = load_cache(SESSION, WINDOW_S)
    times, scores, labels = _scores(head, SESSION)
    by_time = {round(float(moment), 3): (float(score), int(label), emb) for moment, score, label, emb in zip(times, scores, labels, cache["emb"])}
    controls = []
    moment = float(coverage[0]) + CONTROL_STRIDE_S
    while moment < float(coverage[1]) and len(controls) < len(tail):
        key = round(moment, 3)
        # Decision times are integer seconds in this cache.
        key = float(np.round(moment))
        found = by_time.get(key)
        blocked = _span_name(key) != "other_tail" or any(abs(key - row["t"]) < 30 for row in tail)
        if (
            found is not None
            and found[1] == 0
            and not blocked
            and _lookback_commercial(key, commercials) <= 1e-9
        ):
            controls.append({"id": len(controls), "t": key, "score": found[0], "group": "ordinary_show", "emb": found[2]})
        moment += CONTROL_STRIDE_S

    folder = find_session(RECORDINGS, SESSION)
    meta = load_session(folder)
    heard = _heard(np.stack([row["emb"] for row in tail + controls]))
    for row, tags in zip(tail + controls, heard):
        sampled = _window(folder, meta, row["t"])
        frames, hashes = fingerprint(sampled)
        row["frames"] = frames
        row["hashes"] = hashes
        row["tags"] = tags

    self_match = best_match(tail[0]["frames"], tail[0]["hashes"], build_index([tail[0]]), np.ones(1, dtype=bool))
    cross = []
    for row in tail:
        other = _best_against(row, tail)
        control = _best_against(row, controls) if controls else {"score": 0, "t": None, "group": None}
        cross.append(
            {
                "t": row["t"],
                "group": row["group"],
                "score": round(row["score"], 3),
                "speech": row["tags"].get("Speech"),
                "music": row["tags"].get("Music"),
                "crowd": row["tags"].get("Crowd"),
                "applause": row["tags"].get("Applause"),
                "best_other_tail_fingerprint": other["score"],
                "best_other_tail_t": other["t"],
                "best_ordinary_fingerprint": control["score"],
                "best_ordinary_t": control["t"],
            }
        )
    groups = {}
    for name in ("stretch_1", "stretch_2", "other_tail"):
        rows = [row for row in tail if row["group"] == name]
        groups[name] = {
            "n": len(rows),
            "t": [row["t"] for row in rows],
            "score_max": None if not rows else round(max(row["score"] for row in rows), 3),
        }
    between = []
    early = [row for row in tail if row["group"] == "stretch_1"]
    late = [row for row in tail if row["group"] == "stretch_2"]
    for left in early:
        for right in late:
            solo = dict(right)
            solo["id"] = 0
            found = best_match(left["frames"], left["hashes"], build_index([solo]), np.ones(1, dtype=bool))
            between.append(int(found["score"]))
    payload = {
        "id": "SUPERVISED_STRETCH_001",
        "session": SESSION,
        "spans": [{"t0": start, "t1": end} for start, end in SPANS],
        "music_commercial_median": round(music_median, 3),
        "fingerprint_accept_count": PUBLISHED_COUNT,
        "count_lowered": False,
        "later_games_read": False,
        "cutoff_moved": False,
        "words_transcribed": False,
        "self_match_score": int(self_match["score"]),
        "tail_seconds": len(tail),
        "ordinary_controls": [row["t"] for row in controls],
        "groups": groups,
        "embedding_cosine": {
            "within_tail": _mean_pairs(tail),
            "within_ordinary": _mean_pairs(controls),
            "tail_to_ordinary": _mean_pairs(tail, controls),
            "stretch_1_to_stretch_2": _mean_pairs(early, late),
        },
        "fingerprint": {
            "max_between_stretches": None if not between else max(between),
            "pairs_between_stretches_at_200": sum(score >= PUBLISHED_COUNT for score in between),
            "pairs_between_stretches": len(between),
            "max_tail_to_other_tail": max(row["best_other_tail_fingerprint"] for row in cross),
            "tail_pairs_at_200": sum(row["best_other_tail_fingerprint"] >= PUBLISHED_COUNT for row in cross),
            "max_tail_to_ordinary": max((row["best_ordinary_fingerprint"] for row in cross), default=0),
        },
        "tag_medians": {
            "tail_music": round(float(np.median([row["music"] for row in cross])), 4),
            "tail_speech": round(float(np.median([row["speech"] for row in cross])), 4),
            "tail_crowd": round(float(np.median([row["crowd"] for row in cross])), 4),
            "ordinary_music": round(float(np.median([row["tags"].get("Music", 0) for row in controls])), 4) if controls else None,
            "ordinary_speech": round(float(np.median([row["tags"].get("Speech", 0) for row in controls])), 4) if controls else None,
            "ordinary_crowd": round(float(np.median([row["tags"].get("Crowd", 0) for row in controls])), 4) if controls else None,
        },
        "seconds": cross,
        "live_mute_changed": False,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(2, 1, figsize=(10, 4.6), sharey=True)
    for axis, (name, title) in zip(axes, (("stretch_1", "1011–1124"), ("stretch_2", "10151–11419"))):
        trace = span_trace[name]
        axis.plot([row["t"] for row in trace], [row["score"] for row in trace], color="#1f4b99", linewidth=0.7)
        marked = [row for row in cross if row["group"] == name]
        if marked:
            axis.scatter([row["t"] for row in marked], [row["score"] for row in marked], color="#b45309", s=16, zorder=3)
        axis.axhline(music_median, color="#b45309", linestyle="--", linewidth=0.7)
        axis.set_title(f"Sept 13 NBC {title}")
        axis.set_ylabel("Score")
    axes[1].set_xlabel("Session seconds")
    fig.tight_layout()
    fig.savefig(OUT / "stretches.png", dpi=120)
    plt.close(fig)
    (OUT / "results.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(
        f"tail {len(tail)} controls {len(controls)} self {payload['self_match_score']} "
        f"between {payload['fingerprint']['max_between_stretches']} "
        f"cosine within {payload['embedding_cosine']['within_tail']} "
        f"to ordinary {payload['embedding_cosine']['tail_to_ordinary']}",
        flush=True,
    )
    print(payload["groups"], flush=True)
    print(payload["tag_medians"], flush=True)


if __name__ == "__main__":
    main()
