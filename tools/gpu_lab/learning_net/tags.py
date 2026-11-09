"""Name the sounds with the frozen AudioSet head on the cached 10-second vectors.

The class list is ordered by the training games. October describes the seconds
the ESPN past-median rule already hid. Listening notes are left blank.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from tools.gpu_lab.audio_load import load_coverage
from tools.gpu_lab.decisions import playback_from_scores, pod_losses, program_incidents, relative_excess, _separating_threshold
from tools.gpu_lab.embed import MODEL_ID
from tools.gpu_lab.ladder import pairs
from tools.gpu_lab.learning_net.data import BRIDGE, bridge_masks, input_hashes, load_cache, load_head, logits_for
from tools.gpu_lab.learning_net.log import finish_probe, open_probe
from tools.gpu_lab.prepare import DATA_ROOT
from tools.gpu_lab.splits import CALIBRATE, DEVELOP, TRAIN

MODULE = Path(__file__)
PROBE_ID = "failure_tags"
QUESTION = "Which AudioSet event names separate training ads from the game, and which names sit on the program seconds the ESPN rule hid?"
WINDOW_S = 10.0
MEMORY_S = 180
QUANTILE = 0.5
TOP_CLASSES = 12
LISTEN_PROGRAM = 20
LISTEN_COMMERCIAL = 20
CLIP_S = 12.0


def _head():
    import torch
    from transformers import AutoModelForAudioClassification

    model = AutoModelForAudioClassification.from_pretrained(MODEL_ID)
    model.eval()
    labels = [model.config.id2label[index] for index in range(model.config.num_labels)]
    return model, labels, torch


def _group_stats(vectors: np.ndarray, model, torch, n_labels: int) -> dict:
    if len(vectors) == 0:
        return {"n": 0, "mean_probability": [0.0] * n_labels, "top1_count": [0] * n_labels}
    total = np.zeros(n_labels, dtype=np.float64)
    top1 = np.zeros(n_labels, dtype=np.int64)
    with torch.inference_mode():
        for start in range(0, len(vectors), 1024):
            batch = torch.tensor(vectors[start : start + 1024])
            logits = model.classifier(batch).detach().cpu().numpy()
            logits = logits - logits.max(axis=1, keepdims=True)
            prob = np.exp(logits)
            prob /= prob.sum(axis=1, keepdims=True)
            total += prob.sum(axis=0)
            np.add.at(top1, prob.argmax(axis=1), 1)
    return {"n": int(len(vectors)), "mean_probability": total / len(vectors), "top1_count": top1}


def _named(stats: dict, names: list[str], wanted: list[int]) -> list[dict]:
    rows = []
    for index in wanted:
        rows.append(
            {
                "class": names[index],
                "mean_probability": round(float(stats["mean_probability"][index]), 6),
                "top1_fraction": round(float(stats["top1_count"][index]) / stats["n"], 6) if stats["n"] else None,
            }
        )
    return rows


def _listen_rows(folder: Path, masks: dict[str, dict], scores: dict[str, tuple[list[float], list[float]]], threshold: float) -> list[dict]:
    incidents = []
    pods = []
    for session in DEVELOP:
        times, values = scores[session]
        replay_play = playback_from_scores(pairs(masks[session], "coverage")[0], times, values, threshold)
        for row in program_incidents(pairs(masks[session], "verified_program"), replay_play):
            incidents.append({"session": session, "kind": "hidden_program", **row})
        for row in pod_losses(pairs(masks[session], "verified_commercial"), replay_play):
            heard = row["missed_s"] + row["late_start_s"] + row["early_unmute_s"]
            if heard > 0:
                pods.append({"session": session, "kind": "heard_commercial", "heard_s": round(heard, 3), **row})
    chosen = sorted(incidents, key=lambda row: row["program_s"], reverse=True)[:LISTEN_PROGRAM]
    chosen += sorted(pods, key=lambda row: row["heard_s"], reverse=True)[:LISTEN_COMMERCIAL]
    from hush.audio import write_mono_wav

    listen_dir = folder / "listen"
    listen_dir.mkdir(parents=True, exist_ok=True)
    by_session: dict[str, list[dict]] = {}
    for row in chosen:
        by_session.setdefault(row["session"], []).append(row)
    written = []
    for session, rows in by_session.items():
        coverage = pairs(masks[session], "coverage")[0]
        audio = load_coverage(session, coverage[0], coverage[1])
        origin = coverage[0]
        for row in rows:
            start = float(row["start_seconds"])
            end = float(row.get("end_seconds", start + 1.0))
            clip_end = min(end, start + CLIP_S)
            a = int(round((start - origin) * 16000))
            b = int(round((clip_end - origin) * 16000))
            a = max(0, min(a, len(audio)))
            b = max(a, min(b, len(audio)))
            name = f"{session}_{int(start):06d}_{row['kind']}.wav"
            path = listen_dir / name
            write_mono_wav(path, audio[a:b], 16000)
            note = {key: row[key] for key in row if key != "kind"}
            written.append(
                {
                    "file": name,
                    "kind": row["kind"],
                    "session": session,
                    "start_seconds": round(start, 3),
                    "end_seconds": round(end, 3),
                    "clip_end_seconds": round(clip_end, 3),
                    "detail": note,
                    "note": None,
                    "allowed_notes": ["crowd", "booth", "song", "promo", "silence", "edge"],
                }
            )
        del audio
    return written


def run(root: Path = DATA_ROOT) -> dict:
    parameters = {
        "model": MODEL_ID,
        "window_s": WINDOW_S,
        "head": "frozen AudioSet classifier applied to cached CLS vectors",
        "class_order": "largest training-game gap, commercial mean minus program mean",
        "top_classes": TOP_CLASSES,
        "failure_rule": "ESPN past-median lock, 10s window, 180s memory, quantile 0.50",
        "listen_sample": {"hidden_program": LISTEN_PROGRAM, "heard_commercial": LISTEN_COMMERCIAL, "notes_filled": False},
        "october_may_choose_cutoff": False,
    }
    folder = open_probe(PROBE_ID, QUESTION, parameters, MODULE)
    model, names, torch = _head()
    masks = bridge_masks()
    _model_path, logistic = load_head(WINDOW_S, root)
    caches = {session: load_cache(session, WINDOW_S, root) for session in BRIDGE}
    excess = {}
    for session in BRIDGE:
        raw = logits_for(logistic, caches[session]["emb"]).tolist()
        times = caches[session]["t"].astype(float).tolist()
        excess[session] = (times, relative_excess(times, raw, MEMORY_S, QUANTILE))
    espn_times, espn_scores = excess[CALIBRATE[0]]
    threshold = _separating_threshold(espn_times, espn_scores, pairs(masks[CALIBRATE[0]], "verified_program"))
    print(f"  ESPN past-median threshold {threshold}", flush=True)

    def vectors_for(session: str, wanted: np.ndarray) -> np.ndarray:
        return caches[session]["emb"][wanted]

    def collect(sessions: list[str], kind: str) -> np.ndarray:
        parts = []
        for session in sessions:
            labels = caches[session]["label"]
            mask = labels == (1 if kind == "commercial" else 0)
            parts.append(vectors_for(session, mask))
        return np.concatenate(parts) if parts else np.zeros((0, 1), dtype=np.float32)

    hidden_parts = []
    for session in DEVELOP:
        times, values = excess[session]
        play = playback_from_scores(pairs(masks[session], "coverage")[0], times, values, threshold)
        spans = [(row["start_seconds"], row["end_seconds"]) for row in program_incidents(pairs(masks[session], "verified_program"), play)]
        clock = caches[session]["t"]
        chosen = np.zeros(len(clock), dtype=bool)
        for start, end in spans:
            chosen |= (clock >= start - 1e-9) & (clock < end - 1e-9)
        if chosen.any():
            hidden_parts.append(caches[session]["emb"][chosen])
    hidden = np.concatenate(hidden_parts) if hidden_parts else np.zeros((0, caches[TRAIN[0]]["emb"].shape[1]), dtype=np.float32)

    groups = {
        "train_commercial": _group_stats(collect(list(TRAIN), "commercial"), model, torch, len(names)),
        "train_program": _group_stats(collect(list(TRAIN), "program"), model, torch, len(names)),
        "october_commercial": _group_stats(collect(list(DEVELOP), "commercial"), model, torch, len(names)),
        "october_program": _group_stats(collect(list(DEVELOP), "program"), model, torch, len(names)),
        "october_hidden_program": _group_stats(hidden, model, torch, len(names)),
    }
    gap = groups["train_commercial"]["mean_probability"] - groups["train_program"]["mean_probability"]
    order = list(np.argsort(gap)[::-1][:TOP_CLASSES])
    print(f"  top train class {names[order[0]]}", flush=True)
    listen = _listen_rows(folder, masks, {session: excess[session] for session in DEVELOP}, threshold)
    result = {
        "probe_id": PROBE_ID,
        "inputs": input_hashes(WINDOW_S, BRIDGE, root),
        "espn_past_median_threshold": threshold,
        "class_order": [names[index] for index in order],
        "groups": {name: {"n": stats["n"], "classes": _named(stats, names, order)} for name, stats in groups.items()},
        "hidden_program_top1": [
            {"class": names[index], "n": int(groups["october_hidden_program"]["top1_count"][index])}
            for index in np.argsort(groups["october_hidden_program"]["top1_count"])[::-1][:TOP_CLASSES]
            if groups["october_hidden_program"]["top1_count"][index] > 0
        ],
        "listen": listen,
        "listen_notes": "blank until a person writes crowd, booth, song, promo, silence, or edge",
        "corrects_probe": "20261023T005012Z_failure_tags top1 counts under-counted repeated class winners",
    }
    finish_probe(folder, PROBE_ID, QUESTION, parameters, result, MODULE)
    return result
