"""Does a labeled 1–3 second clip name the right announcer?

    py -3.13 -m experiments.nfl75.voice_id_main

The frozen ECAPA cosine at 0.25 is the only accept rule. TitaNet is not in
this environment. Owner marks are three seconds, so a five-second window is
not scored. Pause tracking is not scored: these marks are isolated clips.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from experiments.nfl75.protect_embed import MODEL, _clip, _load_encoder, _latest_labels
from experiments.nfl75.voice_id import (
    DURATIONS,
    TNF,
    enrollment_rows,
    identify,
    outcome,
    probe_bucket,
    tally,
)
from hush.speaker_memory import (
    MATCH_COSINE,
    SR,
    VAD_MIN_SILENCE_MS,
    VAD_MIN_SPEECH_MS,
    VAD_SPEECH_PAD_MS,
    VAD_THRESHOLD,
)

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "docs" / "ohush" / "research" / "OHUSH_VOICE_ID_001"
PRIME = ("hush_20261008_205100", "hush_20260924_220624")
OCTOBER = PRIME[0]
MODES = (
    ("cross_published", True, False),
    ("cross_clean", True, True),
    ("same_published", False, False),
    ("same_clean", False, True),
)


def _prototype(vectors: list[np.ndarray]) -> np.ndarray:
    mean = np.mean(np.stack(vectors), axis=0)
    return mean / max(float(np.linalg.norm(mean)), 1e-12)


def _speech(audio: np.ndarray, model) -> np.ndarray:
    import torch
    from silero_vad import get_speech_timestamps

    stamps = get_speech_timestamps(
        torch.from_numpy(audio),
        model,
        threshold=VAD_THRESHOLD,
        sampling_rate=SR,
        min_speech_duration_ms=VAD_MIN_SPEECH_MS,
        min_silence_duration_ms=VAD_MIN_SILENCE_MS,
        speech_pad_ms=VAD_SPEECH_PAD_MS,
        return_seconds=True,
    )
    pieces = []
    for item in stamps:
        i0 = max(0, int(round(float(item["start"]) * SR)))
        i1 = min(len(audio), int(round(float(item["end"]) * SR)))
        if i1 > i0:
            pieces.append(audio[i0:i1])
    if not pieces:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(pieces)


def _embed_all(labels: list[dict]) -> tuple[dict[str, np.ndarray], dict[str, float]]:
    cache = OUT / "embeddings.npz"
    index_path = OUT / "embeddings.json"
    expected = []
    for row in labels:
        for duration in DURATIONS:
            expected.append(f"{row['id']}|clock|{duration}")
    if cache.is_file() and index_path.is_file():
        saved = json.loads(index_path.read_text(encoding="utf-8"))
        if saved.get("keys", [])[: len(expected)] == expected or set(expected).issubset(saved.get("keys", [])):
            bundle = np.load(cache)
            vectors = {
                key: np.asarray(bundle["vector"][index], dtype=np.float32)
                for index, key in enumerate(saved["keys"])
            }
            speech_s = saved["speech_s"]
            print(f"cached embeddings {len(vectors)}", flush=True)
            return vectors, speech_s
    encoder = _load_encoder(MODEL)
    from silero_vad import load_silero_vad

    vad = load_silero_vad()
    speech_s: dict[str, float] = {}
    pieces: list[tuple[str, np.ndarray]] = []
    for row in labels:
        audio = _clip(row["session"], float(row["play_start"]), float(row["duration"]))
        spoken = _speech(audio, vad)
        speech_s[row["id"]] = round(len(spoken) / SR, 3)
        for duration in DURATIONS:
            need = int(round(duration * SR))
            pieces.append((f"{row['id']}|clock|{duration}", np.asarray(audio[:need], dtype=np.float32)))
            if len(spoken) + int(0.05 * SR) >= need:
                pieces.append((f"{row['id']}|speech|{duration}", np.asarray(spoken[:need], dtype=np.float32)))
        print(f"cut {row['id']} speech {speech_s[row['id']]}s", flush=True)
    grouped: dict[int, list[int]] = defaultdict(list)
    for index, (_key, audio) in enumerate(pieces):
        grouped[len(audio)].append(index)
    vectors: dict[str, np.ndarray] = {}
    for indexes in grouped.values():
        batch = np.stack([pieces[item][1] for item in indexes])
        encoded = _embed_batch(encoder, batch)
        for slot, item in enumerate(indexes):
            vectors[pieces[item][0]] = encoded[slot]
    OUT.mkdir(parents=True, exist_ok=True)
    keys = list(vectors)
    np.savez(cache, vector=np.stack([vectors[key] for key in keys]))
    index_path.write_text(
        json.dumps({"keys": keys, "speech_s": speech_s, "model": "speechbrain/spkrec-ecapa-voxceleb"}),
        encoding="utf-8",
    )
    print(f"embedded {len(vectors)}", flush=True)
    return vectors, speech_s


def _embed_batch(encoder, batch: np.ndarray) -> np.ndarray:
    import torch

    with torch.inference_mode():
        encoded = encoder.encode_batch(torch.from_numpy(batch), normalize=False)
    arr = encoded.detach().float().cpu().numpy()
    arr = np.squeeze(arr, axis=1) if arr.ndim == 3 else arr
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    if np.any(norms < 1e-6):
        raise RuntimeError("encoder returned a zero embedding")
    return (arr / norms).astype(np.float32)


def _scores(prototypes: dict[str, np.ndarray], probe: np.ndarray) -> dict[str, float]:
    return {name: float(probe @ vector) for name, vector in prototypes.items()}


def _build(labels: list[dict], vectors: dict[str, np.ndarray], refs: list[dict], kind: str, duration: float) -> dict[str, np.ndarray]:
    grouped: dict[str, list[np.ndarray]] = defaultdict(list)
    for row in refs:
        vector = vectors.get(f"{row['id']}|{kind}|{duration}")
        if vector is not None:
            grouped[row["who"]].append(vector)
    return {name: _prototype(rows) for name, rows in grouped.items() if rows}


def _record(row: dict, kind: str, duration: float, mode: str, prototypes: dict[str, np.ndarray], probe: np.ndarray | None) -> dict:
    names = set(prototypes)
    bucket = probe_bucket(row, names)
    label = row.get("who") or ""
    if probe is None or not prototypes:
        decision = {"accepted": None, "rank1": None, "best": None, "second": None}
        scores = {}
    else:
        scores = _scores(prototypes, probe)
        decision = identify(scores)
    true = scores.get(label) if label in scores else None
    others = [value for name, value in scores.items() if name != label]
    best_other = max(others) if others else None
    result = outcome(label, decision["accepted"], decision["rank1"], bucket)
    rank1_correct = None
    if bucket in ("clear", "noisy") and decision["rank1"] is not None:
        rank1_correct = decision["rank1"] == label
    return {
        "id": row["id"],
        "session": row["session"],
        "who": label or None,
        "condition": row.get("condition"),
        "mode": mode,
        "audio": kind,
        "duration_s": duration,
        "bucket": bucket,
        "outcome": result,
        "accepted": decision["accepted"],
        "rank1": decision["rank1"],
        "rank1_correct": rank1_correct,
        "best": None if decision["best"] is None else round(decision["best"], 4),
        "true_cosine": None if true is None else round(true, 4),
        "best_other": None if best_other is None else round(best_other, 4),
    }


def _groups(records: list[dict]) -> list[dict]:
    grouped: dict[tuple, list[dict]] = defaultdict(list)
    for row in records:
        session = "other_shows" if row["bucket"] == "other_show" else row["session"]
        grouped[(session, row["mode"], row["audio"], row["duration_s"], row["bucket"])].append(row)
    rendered = []
    for key in sorted(grouped):
        session, mode, audio, duration, bucket = key
        summary = tally(grouped[key])
        hits = [row for row in grouped[key] if row.get("rank1_correct") is True]
        trials = [row for row in grouped[key] if row.get("rank1_correct") is not None]
        summary.update(
            {
                "session": session,
                "mode": mode,
                "audio": audio,
                "duration_s": duration,
                "bucket": bucket,
                "rank1_correct": len(hits),
                "rank1_n": len(trials),
                "median_true_cosine": None if summary["median_true_cosine"] is None else round(summary["median_true_cosine"], 4),
                "median_best_other": None if summary["median_best_other"] is None else round(summary["median_best_other"], 4),
            }
        )
        rendered.append(summary)
    return rendered


def _delay(records: list[dict]) -> list[dict]:
    """Shortest clock prefix of an owner mark that the frozen line accepts."""
    grouped: dict[tuple, list[dict]] = defaultdict(list)
    for row in records:
        if row["audio"] != "clock" or row["bucket"] not in ("clear", "noisy"):
            continue
        grouped[(row["session"], row["mode"], row["id"])].append(row)
    found = []
    for (session, mode, _clip_id), rows in grouped.items():
        ordered = sorted(rows, key=lambda item: item["duration_s"])
        hit = next((item["duration_s"] for item in ordered if item["outcome"] == "correct"), None)
        found.append({"session": session, "mode": mode, "delay_s": hit, "who": ordered[0]["who"], "condition": ordered[0]["condition"]})
    summary = []
    buckets: dict[tuple, list[float | None]] = defaultdict(list)
    for row in found:
        buckets[(row["session"], row["mode"], row["condition"])].append(row["delay_s"])
    for key in sorted(buckets):
        values = buckets[key]
        known = [value for value in values if value is not None]
        summary.append(
            {
                "session": key[0],
                "mode": key[1],
                "condition": key[2],
                "n": len(values),
                "recognized": len(known),
                "median_delay_s": None if not known else sorted(known)[len(known) // 2],
            }
        )
    return summary


def main() -> None:
    if MATCH_COSINE != 0.25:
        raise RuntimeError("refusing a speaker line other than 0.25")
    labels = _latest_labels()
    if any(float(row["duration"]) != 3.0 for row in labels):
        raise RuntimeError("an owner mark is not 3 seconds; refusing to stretch it")
    vectors, speech_s = _embed_all(labels)
    inventory = []
    for session in PRIME:
        for mode, cross, clean in MODES:
            refs = enrollment_rows(labels, session, cross_tape=cross, clean=clean, exclude_ids=set())
            inventory.append(
                {
                    "session": session,
                    "mode": mode,
                    "n": len(refs),
                    "by_person": dict(Counter(row["who"] for row in refs)),
                    "conditions": dict(Counter(row["condition"] for row in refs)),
                }
            )
    records = []
    for row in labels:
        if row["session"] not in PRIME and (row.get("who") or "") in ("", *TNF):
            continue
        for mode, cross, clean in MODES:
            test_session = OCTOBER if (row.get("who") or "") not in TNF else row["session"]
            if (row.get("who") or "") not in TNF and row["session"] in PRIME:
                test_session = row["session"]
            refs = enrollment_rows(labels, test_session, cross_tape=cross, clean=clean, exclude_ids={row["id"]})
            if not refs:
                continue
            for kind in ("clock", "speech"):
                for duration in DURATIONS:
                    prototypes = _build(labels, vectors, refs, kind, duration)
                    probe = vectors.get(f"{row['id']}|{kind}|{duration}")
                    if kind == "speech" and probe is None:
                        continue
                    records.append(_record(row, kind, duration, mode, prototypes, probe))
    document = {
        "experiment": "OHUSH_VOICE_ID_001",
        "question": "Given one to three seconds inside an owner mark, does frozen ECAPA at 0.25 name that person?",
        "deployable": False,
        "television_changed": False,
        "pause_trust_built": False,
        "model": "speechbrain/spkrec-ecapa-voxceleb",
        "titanet": "not run; NeMo is not installed and torch is the CPU build",
        "match_cosine": MATCH_COSINE,
        "owner_mark_s": 3.0,
        "five_second_windows": "not measured; scoring past the owner mark would name audio nobody labeled",
        "tracking_across_pauses": "not measured; the owner marks are isolated clips, not turns",
        "clips": len(labels),
        "speech_s": speech_s,
        "cast": list(TNF),
        "enrollment": inventory,
        "groups": _groups(records),
        "recognition_delay": _delay(records),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(document, indent=2), encoding="utf-8")
    with (OUT / "records.jsonl").open("w", encoding="utf-8") as handle:
        for row in records:
            handle.write(json.dumps(row) + "\n")
    print("records", len(records))
    for row in document["groups"]:
        if row["audio"] == "clock" and row["bucket"] in ("clear", "noisy", "other_show", "not_them", "not_enrolled", "song"):
            print(
                row["session"][-6:],
                row["mode"],
                row["duration_s"],
                row["bucket"],
                "n",
                row["n"],
                row["outcomes"],
                "rank1",
                f"{row['rank1_correct']}/{row['rank1_n']}",
                "true",
                row["median_true_cosine"],
                "other",
                row["median_best_other"],
            )


if __name__ == "__main__":
    main()
