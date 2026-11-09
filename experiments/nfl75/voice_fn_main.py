"""Atomic view of frozen ECAPA misses. Does not retune or mute.

    py -3.13 -m experiments.nfl75.voice_fn_main

Human fields in the queue are empty. The model hint is why the clip was
picked, not who was speaking.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from experiments.ledger import RECORDINGS
from experiments.measurement.metrics import target_commercials
from experiments.nfl75.inventory import active_intervals
from experiments.nfl75.protect_embed import _latest_labels
from experiments.nfl75.voice_fn import FRESH_S, MATCH, classify_episode
from hush.audio import RAW_SR, analysis_pieces, find_session, load_session, read_stereo, resample_concat, write_mono_wav
from hush.speaker_memory import (
    EMBED_HOP_S,
    EMBED_WIN_S,
    MIN_SPEECH_S,
    SR,
    VAD_MIN_SILENCE_MS,
    VAD_MIN_SPEECH_MS,
    VAD_SPEECH_PAD_MS,
    VAD_THRESHOLD,
)

RESEARCH = REPO / "docs" / "ohush" / "research"
FORENSICS = RESEARCH / "OHUSH_FAILURE_FORENSICS_001" / "episodes.jsonl"
CACHE = RESEARCH / "NFL75_PROTECT_001" / "cache"
OUT = RESEARCH / "OHUSH_VOICE_FN_ATOMIC_001"
PRIME = ("hush_20261008_205100", "hush_20260924_220624")
PIPELINE = {
    "sample_rate_hz": SR,
    "source": "stereo recording, mean of the two channels, one resample from 48 kHz to 16 kHz",
    "embed_window_s": EMBED_WIN_S,
    "embed_hop_s": EMBED_HOP_S,
    "min_speech_s": MIN_SPEECH_S,
    "vad_threshold": VAD_THRESHOLD,
    "vad_min_speech_ms": VAD_MIN_SPEECH_MS,
    "vad_min_silence_ms": VAD_MIN_SILENCE_MS,
    "vad_speech_pad_ms": VAD_SPEECH_PAD_MS,
    "cosine_line": MATCH,
    "fresh_s": FRESH_S,
    "enrollment": "Thursday cast, SpeechBrain ECAPA, clips from an earlier game or from earlier in the same game",
}


def _audio(session: str, start: float, end: float) -> np.ndarray:
    folder = find_session(RECORDINGS, session)
    meta = load_session(folder)
    pieces = analysis_pieces(folder, meta, start, end)
    mono = [read_stereo(piece).mean(axis=1) for piece in pieces]
    return np.asarray(resample_concat(mono, up=1, down=RAW_SR // SR), dtype=np.float32)


def _vad(audio: np.ndarray, model) -> list[tuple[float, float]]:
    import torch
    from silero_vad import get_speech_timestamps

    stamps = get_speech_timestamps(
        torch.from_numpy(np.asarray(audio, dtype=np.float32)),
        model,
        threshold=VAD_THRESHOLD,
        sampling_rate=SR,
        min_speech_duration_ms=VAD_MIN_SPEECH_MS,
        min_silence_duration_ms=VAD_MIN_SILENCE_MS,
        speech_pad_ms=VAD_SPEECH_PAD_MS,
        return_seconds=True,
    )
    return [(float(item["start"]), float(item["end"])) for item in stamps]


def _speech_s(regions: list[tuple[float, float]], start: float, end: float, origin: float) -> float:
    total = 0.0
    for left, right in regions:
        a0, a1 = origin + left, origin + right
        total += max(0.0, min(a1, end) - max(a0, start))
    return total


def _load_windows(session: str) -> tuple[list[str], list[dict]]:
    receipt = json.loads((CACHE / f"{session}.json").read_text(encoding="utf-8"))
    names = list(receipt["names"])
    bundle = np.load(CACHE / f"{session}.npz")
    starts = np.asarray(bundle["start"], dtype=np.float64)
    ends = np.asarray(bundle["end"], dtype=np.float64)
    people = np.asarray(bundle["people"], dtype=np.float64)
    windows = []
    for index in range(len(ends)):
        scores = {}
        for slot, name in enumerate(names):
            value = float(people[index, slot])
            if value == value:
                scores[name] = value
        windows.append({"start": float(starts[index]), "end": float(ends[index]), "scores": scores})
    return names, windows


def _episodes() -> list[dict]:
    rows = []
    for line in FORENSICS.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("policy") == "unprotected" and row.get("clock") == "oracle" and row.get("kind") == "false_mute":
            rows.append(row)
    return rows


def _commercials(session: str) -> list[tuple[float, float]]:
    return target_commercials(active_intervals(session))


def _in_ad(moment: float, commercials: list[tuple[float, float]]) -> bool:
    return any(start <= moment < end for start, end in commercials)


def main() -> None:
    if MATCH != 0.25:
        raise RuntimeError("refusing a cosine line other than 0.25")
    from silero_vad import load_silero_vad

    vad_model = load_silero_vad()
    tapes = {}
    for session in PRIME:
        names, windows = _load_windows(session)
        tapes[session] = {"names": names, "windows": windows, "ads": _commercials(session)}
    items = []
    atomic = []
    for episode in _episodes():
        session = episode["session"]
        start, end = float(episode["start_s"]), float(episode["end_s"])
        tape = tapes[session]
        pad0 = max(0.0, start - 2.0)
        pad1 = end + 2.0
        audio = _audio(session, pad0, pad1)
        regions = _vad(audio, vad_model)
        speech = _speech_s(regions, start, end, pad0)
        nearby = [row for row in tape["windows"] if row["end"] > start - 20.0 and row["start"] < end + 20.0]
        found = classify_episode(start, end, tape["windows"], speech)
        if episode.get("overlay") == "promotional_read":
            found["kind"] = "promotional_sample"
        item = {
            "session": session,
            "focus_start_s": round(start, 3),
            "focus_end_s": round(end, 3),
            "duration_s": round(end - start, 3),
            "prior_listen": episode.get("listen_category"),
            "prior_listen_is": "a transcript note, not a speaker label",
            "kind": found["kind"],
            "speech_s": round(speech, 3),
            "windows": found["windows"],
            "available_at_s": found["available_at_s"],
            "seconds_after_open": found["seconds_after_open"],
            "cited_name": found["cited_name"],
            "cited_cosine": found["cited_cosine"],
            "second_name": found["second_name"],
            "second_cosine": found["second_cosine"],
            "identity_verified": False,
        }
        items.append(item)
        if found["kind"] in (
            "below_line",
            "missing_reference",
            "delayed_recognition",
            "no_speech_detected",
            "speech_without_embedding_window",
        ):
            for row in nearby:
                if row["end"] < start - 5.0 or row["start"] > end + 5.0:
                    continue
                ordered = sorted(row["scores"].items(), key=lambda pair: pair[1], reverse=True)
                top = ordered[0] if ordered else (None, None)
                second = ordered[1] if len(ordered) > 1 else (None, None)
                atomic.append(
                    {
                        "session": session,
                        "focus_start_s": round(start, 3),
                        "window_start_s": round(row["start"], 3),
                        "window_end_s": round(row["end"], 3),
                        "speech_s": round(_speech_s(regions, row["start"], row["end"], pad0), 3),
                        "top_name": top[0],
                        "top_cosine": None if top[1] is None else round(top[1], 4),
                        "second_name": second[0],
                        "second_cosine": None if second[1] is None else round(second[1], 4),
                        "scores": {name: round(value, 4) for name, value in ordered},
                        "usable_at_s": round(row["end"], 3),
                        "open_s": round(start, 3),
                        "kind": found["kind"],
                    }
                )
    # Commercial windows the cosine already accepts. Identity is not verified.
    for session in PRIME:
        last = -1e9
        taken = 0
        for row in tapes[session]["windows"]:
            mid = (row["start"] + row["end"]) / 2.0
            ordered = sorted(row["scores"].items(), key=lambda pair: pair[1], reverse=True)
            if not ordered or ordered[0][1] < MATCH or not _in_ad(mid, tapes[session]["ads"]):
                continue
            if mid < last + 180.0:
                continue
            last = mid
            taken += 1
            if taken > 12:
                break
            items.append(
                {
                    "session": session,
                    "focus_start_s": round(row["start"], 3),
                    "focus_end_s": round(row["end"], 3),
                    "duration_s": round(row["end"] - row["start"], 3),
                    "prior_listen": None,
                    "prior_listen_is": "gold says commercial; nobody has named the voice",
                    "kind": "commercial_match",
                    "speech_s": None,
                    "windows": 1,
                    "available_at_s": round(row["end"], 3),
                    "seconds_after_open": None,
                    "cited_name": ordered[0][0],
                    "cited_cosine": round(ordered[0][1], 4),
                    "second_name": ordered[1][0] if len(ordered) > 1 else None,
                    "second_cosine": round(ordered[1][1], 4) if len(ordered) > 1 else None,
                    "identity_verified": False,
                }
            )
    for row in _latest_labels():
        if row["session"] not in PRIME:
            continue
        if row.get("condition") != "song" and not (
            row.get("who") == "Tony Gonzalez" and row.get("condition") == "clear"
        ):
            continue
        items.append(
            {
                "session": row["session"],
                "focus_start_s": float(row["play_start"]),
                "focus_end_s": float(row["play_start"]) + float(row["duration"]),
                "duration_s": float(row["duration"]),
                "prior_listen": row.get("condition"),
                "prior_listen_is": "the owner marked this enrollment clip",
                "kind": "enrollment_audit",
                "owner_who": row.get("who"),
                "owner_condition": row.get("condition"),
                "clip_id": row["id"],
                "speech_s": None,
                "windows": None,
                "available_at_s": None,
                "seconds_after_open": None,
                "cited_name": row.get("who"),
                "cited_cosine": None,
                "second_name": None,
                "second_cosine": None,
                "identity_verified": False,
            }
        )
    rank = {
        "missing_reference": 0,
        "below_line": 0,
        "no_speech_detected": 0,
        "speech_without_embedding_window": 1,
        "no_embedding_window": 1,
        "delayed_recognition": 2,
        "decision_ignored_match": 3,
        "commercial_match": 4,
        "promotional_sample": 5,
        "enrollment_audit": 6,
    }
    items.sort(key=lambda row: (rank.get(row["kind"], 9), row["session"], row["focus_start_s"]))
    dev_ignored = 0
    queue = []
    clip_root = OUT / "clips"
    for index, item in enumerate(items, start=1):
        split = "dev"
        if item["kind"] in ("decision_ignored_match", "commercial_match"):
            dev_ignored += 1
            if dev_ignored % 4 == 0:
                split = "eval"
        start = max(0.0, item["focus_start_s"] - 3.0)
        end = item["focus_end_s"] + 3.0
        cap = 40.0 if item["kind"] in ("below_line", "missing_reference", "delayed_recognition", "no_speech_detected") else 28.0
        if end - start > cap:
            end = start + cap
        audio = _audio(item["session"], start, end)
        wav = clip_root / item["session"] / f"fn{index:04d}.wav"
        wav.parent.mkdir(parents=True, exist_ok=True)
        write_mono_wav(wav, audio, SR)
        queue.append(
            {
                "id": f"fn{index:04d}",
                "split": split,
                "kind": item["kind"],
                "session": item["session"],
                "wav": str(wav.relative_to(REPO)),
                "clip_start_s": round(start, 3),
                "clip_end_s": round(end, 3),
                "focus_start_s": item["focus_start_s"],
                "focus_end_s": item["focus_end_s"],
                "why_queued": {
                    "kind": item["kind"],
                    "cited_name": item["cited_name"],
                    "cited_cosine": item["cited_cosine"],
                    "second_name": item["second_name"],
                    "second_cosine": item["second_cosine"],
                    "speech_s_in_focus": item["speech_s"],
                    "embedding_windows": item["windows"],
                    "match_usable_at_s": item["available_at_s"],
                    "seconds_after_mute_opened": item["seconds_after_open"],
                    "prior_listen": item["prior_listen"],
                    "prior_listen_is": item["prior_listen_is"],
                    "owner_who": item.get("owner_who"),
                    "owner_condition": item.get("owner_condition"),
                    "enrollment_id": item.get("clip_id"),
                },
                "label": {
                    "speaker": None,
                    "background": None,
                    "overlap": None,
                    "certainty": None,
                    "speech_start_s": None,
                    "speech_end_s": None,
                    "notes": None,
                },
            }
        )
    # Exact windows the embedder used, for the misses and the late matches.
    window_dir = OUT / "windows"
    delayed_written = 0
    preferred = sorted(
        atomic,
        key=lambda row: (0 if row["kind"] in ("below_line", "missing_reference") else 1, row["open_s"], row["window_end_s"]),
    )
    for row in preferred:
        if row["top_cosine"] is None and row["kind"] != "missing_reference":
            continue
        forced = abs(row["open_s"] - 9156.0) < 0.1
        keep = row["kind"] in ("below_line", "missing_reference")
        if not forced and not keep:
            if row["top_cosine"] >= MATCH and row["window_end_s"] + 5.0 < row["open_s"]:
                continue
            if delayed_written >= 24:
                continue
        audio = _audio(row["session"], row["window_start_s"], row["window_end_s"])
        path = window_dir / row["session"] / f"{row['open_s']:.0f}_{row['window_end_s']:.0f}.wav"
        path.parent.mkdir(parents=True, exist_ok=True)
        write_mono_wav(path, audio, SR)
        row["wav"] = str(path.relative_to(REPO))
        if not forced and row["kind"] not in ("below_line", "missing_reference"):
            delayed_written += 1
    labeled = [row for row in queue if row["label"]["speech_start_s"] is not None]
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "queue.jsonl").write_text("".join(json.dumps(row) + "\n" for row in queue), encoding="utf-8")
    (OUT / "windows.jsonl").write_text("".join(json.dumps(row) + "\n" for row in atomic), encoding="utf-8")
    counts = {}
    for row in queue:
        if row["split"] != "dev":
            continue
        counts.setdefault(row["kind"], {"n": 0, "seconds": 0.0})
        counts[row["kind"]]["n"] += 1
        counts[row["kind"]]["seconds"] = round(
            counts[row["kind"]]["seconds"] + (row["focus_end_s"] - row["focus_start_s"]), 3
        )
    manifest = {
        "experiment": "OHUSH_VOICE_FN_ATOMIC_001",
        "pipeline": PIPELINE,
        "identity_verified": False,
        "threshold_changed": False,
        "television_changed": False,
        "ideal_speech_cut": "not run; speech_start_s and speech_end_s are empty on every queue row",
        "labeled_rows": len(labeled),
        "queue": len(queue),
        "eval_rows": sum(1 for row in queue if row["split"] == "eval"),
        "dev_counts": counts,
        "fields": {
            "speaker": "who is speaking, or other/unknown",
            "background": "clean, music, crowd, or other mixed",
            "overlap": "yes or no",
            "certainty": "certain or uncertain",
            "speech_start_s": "session seconds where that person's speech starts",
            "speech_end_s": "session seconds where it ends",
        },
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(counts, indent=2))
    print("queue", len(queue), "eval", manifest["eval_rows"], "windows", len(atomic))


if __name__ == "__main__":
    main()
