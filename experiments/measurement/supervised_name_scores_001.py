"""Compare NBC show scores and commercial scores inside two AudioSet names.

The head is the two-game logistic already fit. The names come from the frozen
AudioSet classifier on the same cached vectors. Clear show seconds are
entirely program and have no labeled commercial in the five-second lookback.
This script reads only the two NBC fit games. It does not choose a cutoff,
and it does not score a later broadcast.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from experiments.measurement.supervised_clear_ceiling_001 import _lookback_commercial  # noqa: E402
from experiments.measurement.supervised_heldout_001 import FIT, WINDOW_S, _fit, _scores  # noqa: E402
from tools.gpu_lab.embed import MODEL_ID  # noqa: E402
from tools.gpu_lab.ladder import pairs  # noqa: E402
from tools.gpu_lab.learning_net.data import bridge_masks, load_cache  # noqa: E402

OUT = REPO / "docs" / "ohush" / "research" / "SUPERVISED_NAME_SCORES_001"
NAMES = ("Music", "Speech")
PUBLISHED_CLEAR_CUTOFF = 8.284611701965334


def _top_name(vectors: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    import torch
    from transformers import AutoModelForAudioClassification

    model = AutoModelForAudioClassification.from_pretrained(MODEL_ID)
    model.eval()
    labels = [model.config.id2label[index] for index in range(model.config.num_labels)]
    chosen = np.empty(len(vectors), dtype=object)
    confidence = np.empty(len(vectors), dtype=np.float64)
    with torch.inference_mode():
        for start in range(0, len(vectors), 1024):
            batch = torch.tensor(vectors[start : start + 1024])
            logits = model.classifier(batch).detach().cpu().numpy()
            logits = logits - logits.max(axis=1, keepdims=True)
            prob = np.exp(logits)
            prob /= prob.sum(axis=1, keepdims=True)
            winner = prob.argmax(axis=1)
            chosen[start : start + len(winner)] = [labels[int(index)] for index in winner]
            confidence[start : start + len(winner)] = prob[np.arange(len(winner)), winner]
    return chosen, confidence


def _summary(scores: np.ndarray, confidence: np.ndarray) -> dict:
    if scores.size == 0:
        return {"n": 0}
    return {
        "n": int(scores.size),
        "median": round(float(np.median(scores)), 3),
        "p95": round(float(np.percentile(scores, 95)), 3),
        "p99": round(float(np.percentile(scores, 99)), 3),
        "max": round(float(scores.max()), 3),
        "min": round(float(scores.min()), 3),
        "top_name_probability_median": round(float(np.median(confidence)), 4),
    }


def _overlap(show: np.ndarray, commercial: np.ndarray) -> dict:
    if show.size == 0 or commercial.size == 0:
        return {"show_n": int(show.size), "commercial_n": int(commercial.size)}
    ceiling = float(show.max())
    commercial_median = float(np.median(commercial))
    return {
        "show_max": round(ceiling, 3),
        "commercial_seconds_above_show_max": int(np.sum(commercial > ceiling)),
        "commercial_seconds_at_or_below_show_max": int(np.sum(commercial <= ceiling)),
        "show_seconds_above_commercial_median": int(np.sum(show >= commercial_median)),
        "show_seconds_above_commercial_p95": int(np.sum(show >= float(np.percentile(commercial, 95)))),
    }


def _plot(path: Path, groups: dict[str, dict[str, np.ndarray]]) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.4), sharey=True)
    for axis, name in zip(axes, NAMES):
        show = groups[name]["show"]
        commercial = groups[name]["commercial"]
        bins = np.linspace(-15, 18, 67)
        axis.hist(show, bins=bins, color="#1f4b99", alpha=0.65, label="clear show")
        axis.hist(commercial, bins=bins, color="#b45309", alpha=0.55, label="commercial")
        if show.size:
            axis.axvline(float(show.max()), color="#1f4b99", linestyle="--", linewidth=0.8)
        axis.set_title(name)
        axis.set_xlabel("Logistic score")
        axis.legend(fontsize=8)
    axes[0].set_ylabel("NBC seconds")
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def main() -> None:
    masks = bridge_masks()
    head, receipt = _fit(FIT)
    show_score = []
    show_name = []
    show_conf = []
    show_at = []
    ad_score = []
    ad_name = []
    ad_conf = []
    for session in FIT:
        cache = load_cache(session, WINDOW_S)
        times, scores, labels = _scores(head, session)
        if len(times) != len(cache["emb"]):
            raise SystemExit(f"{session} cache and scores differ")
        names, confidence = _top_name(cache["emb"])
        commercials = pairs(masks[session], "verified_commercial")
        for moment, score, label, name, conf in zip(times, scores, labels, names, confidence):
            if int(label) == 1:
                ad_score.append(float(score))
                ad_name.append(str(name))
                ad_conf.append(float(conf))
            elif int(label) == 0 and _lookback_commercial(float(moment), commercials) <= 1e-9:
                show_score.append(float(score))
                show_name.append(str(name))
                show_conf.append(float(conf))
                show_at.append((session, round(float(moment), 3)))
    show_score = np.asarray(show_score)
    show_name = np.asarray(show_name)
    show_conf = np.asarray(show_conf)
    ad_score = np.asarray(ad_score)
    ad_name = np.asarray(ad_name)
    ad_conf = np.asarray(ad_conf)
    groups = {}
    named = {}
    for name in NAMES:
        show = show_score[show_name == name]
        commercial = ad_score[ad_name == name]
        groups[name] = {"show": show, "commercial": commercial}
        show_index = np.flatnonzero(show_name == name)
        commercial_median = float(np.median(commercial)) if commercial.size else None
        above = []
        if commercial_median is not None:
            for index in show_index:
                if show_score[index] < commercial_median:
                    continue
                session, moment = show_at[index]
                above.append(
                    {
                        "session": session,
                        "t": moment,
                        "score": round(float(show_score[index]), 3),
                        "top_name_probability": round(float(show_conf[index]), 4),
                    }
                )
            above.sort(key=lambda row: row["score"], reverse=True)
        named[name] = {
            "clear_show": _summary(show, show_conf[show_name == name]),
            "commercial": _summary(commercial, ad_conf[ad_name == name]),
            "overlap": _overlap(show, commercial),
            "show_seconds_at_or_above_commercial_median": above,
        }
        overlap = named[name]["overlap"]
        print(
            f"{name} show {named[name]['clear_show'].get('n')} "
            f"median {named[name]['clear_show'].get('median')} max {overlap.get('show_max')} "
            f"ads above that max {overlap.get('commercial_seconds_above_show_max')} "
            f"of {named[name]['commercial'].get('n')}",
            flush=True,
        )
    payload = {
        "id": "SUPERVISED_NAME_SCORES_001",
        "follows": "SUPERVISED_CLEAR_CEILING_001",
        "model": MODEL_ID,
        "window_s": WINDOW_S,
        "fit": receipt,
        "games_read": list(FIT),
        "held_out_games_read": False,
        "cutoff_moved": False,
        "published_clear_cutoff_unchanged": PUBLISHED_CLEAR_CUTOFF,
        "name_rule": "top class of the frozen AudioSet head on the cached AST vector",
        "clear_show_rule": "covered second entirely program, and no labeled commercial in the five-second lookback",
        "clear_show_seconds": int(show_score.size),
        "commercial_seconds": int(ad_score.size),
        "names": named,
        "live_mute_changed": False,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    _plot(OUT / "music_speech_scores.png", groups)
    (OUT / "results.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT / 'results.json'}", flush=True)


if __name__ == "__main__":
    main()
