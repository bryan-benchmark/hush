"""Replay the published ECAPA announcer match. Does not train or touch booth files.

    C:\\Python313\\python.exe -m experiments.nfl75.protect_embed

Writes one cosine per speech window for the two Prime development tapes.
Enrollment is the TNF cast from VOICE_ENROLL_001, leaving out the tape
being scored and every sealed holdout. The saved enroll_tnf.npy matrix is
not used, because it can contain the tape itself.
"""

from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

CACHE = REPO / "ohush_live" / "cache"
os.environ.setdefault("HF_HOME", str(CACHE / "hf"))
os.environ.setdefault("HUGGINGFACE_HUB_CACHE", str(CACHE / "hf" / "hub"))
os.environ.setdefault("TORCH_HOME", str(CACHE / "torch"))

from experiments.ledger import RECORDINGS  # noqa: E402
from experiments.nfl75.mean import PRIME_SESSIONS  # noqa: E402
from hush.audio import (  # noqa: E402
    RAW_SR,
    analysis_pieces,
    find_session,
    load_session,
    read_stereo,
    resample_concat,
)
from hush.speaker_memory import (  # noqa: E402
    EMBEDDING_MODEL_ID,
    SR,
    VAD_MIN_SILENCE_MS,
    VAD_MIN_SPEECH_MS,
    VAD_SPEECH_PAD_MS,
    VAD_THRESHOLD,
    embedding_windows,
)
from ohush_live.enroll_floor import CAST, KEEP  # noqa: E402
from tools.gpu_lab.splits import HOLDOUTS  # noqa: E402

OUT = REPO / "docs" / "ohush" / "research" / "NFL75_PROTECT_001" / "cache"
LABELS = REPO / "docs" / "ohush" / "research" / "VOICE_ENROLL_001" / "labels.jsonl"
MODEL = REPO / "experiments" / "exp002" / "models" / "spkrec-ecapa-voxceleb"


def _latest_labels() -> list[dict]:
    by_id: dict[str, dict] = {}
    for line in LABELS.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            by_id[row["id"]] = row
    return list(by_id.values())


def _prototype(vectors: list[np.ndarray]) -> np.ndarray:
    mean = np.mean(np.stack(vectors), axis=0)
    return mean / np.linalg.norm(mean)


def _load_encoder(savedir: Path):
    import torch
    from speechbrain.inference.speaker import EncoderClassifier
    from speechbrain.utils.fetching import LocalStrategy

    savedir.mkdir(parents=True, exist_ok=True)
    encoder = EncoderClassifier.from_hparams(
        source=EMBEDDING_MODEL_ID,
        savedir=str(savedir),
        run_opts={"device": "cpu"},
        local_strategy=LocalStrategy.COPY,
    )
    encoder.device = torch.device("cpu")
    return encoder


def _embed_windows(audio: np.ndarray, windows: list[tuple[float, float]], encoder, batch_size: int) -> np.ndarray:
    import torch

    groups: dict[int, list[int]] = {}
    pieces = []
    for index, (start, end) in enumerate(windows):
        i0 = max(0, int(round(start * SR)))
        i1 = max(i0 + 1, min(int(round(end * SR)), audio.shape[0]))
        piece = np.asarray(audio[i0:i1], dtype=np.float32)
        pieces.append(piece)
        groups.setdefault(piece.shape[0], []).append(index)
    out = None
    done = 0
    with torch.inference_mode():
        for _length, indexes in groups.items():
            for offset in range(0, len(indexes), batch_size):
                batch_ids = indexes[offset : offset + batch_size]
                stacked = np.stack([pieces[item] for item in batch_ids])
                encoded = encoder.encode_batch(torch.from_numpy(stacked), normalize=False)
                arr = encoded.detach().float().cpu().numpy()
                arr = np.squeeze(arr, axis=1) if arr.ndim == 3 else arr
                if out is None:
                    out = np.zeros((len(windows), arr.shape[-1]), dtype=np.float32)
                out[batch_ids] = arr
                done += len(batch_ids)
                if done % 256 < len(batch_ids) or done == len(windows):
                    print(f"embedded {done}/{len(windows)}", flush=True)
    norms = np.linalg.norm(out, axis=1, keepdims=True)
    if np.any(norms < 1e-6):
        raise RuntimeError("encoder returned a zero embedding")
    return (out / norms).astype(np.float32)


def _speech_regions(audio: np.ndarray) -> tuple[list[tuple[float, float]], dict]:
    import torch
    from silero_vad import get_speech_timestamps, load_silero_vad

    from hush.speaker_memory import merge_regions

    model = load_silero_vad()
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
    raw = [(float(item["start"]), float(item["end"])) for item in stamps]
    kept = merge_regions(raw)
    return kept, {"n_raw_regions": len(raw), "n_regions": len(kept)}


def _clip(session: str, start: float, duration: float) -> np.ndarray:
    if session in HOLDOUTS:
        raise RuntimeError(f"refusing sealed holdout {session}")
    folder = find_session(RECORDINGS, session)
    meta = load_session(folder)
    pieces = analysis_pieces(folder, meta, start, start + duration)
    mono = [read_stereo(piece).mean(axis=1) for piece in pieces]
    audio = resample_concat(mono, up=1, down=RAW_SR // SR)
    return np.asarray(audio, dtype=np.float32)


def _coverage_audio(session: str) -> tuple[np.ndarray, float, float]:
    if session in HOLDOUTS or session not in PRIME_SESSIONS:
        raise RuntimeError(f"refusing {session}")
    folder = find_session(RECORDINGS, session)
    meta = load_session(folder)
    chunks = meta["chunks"]
    start = float(chunks[0]["start_elapsed_seconds"])
    end = float(chunks[-1]["end_elapsed_seconds"])
    pieces = analysis_pieces(folder, meta, start, end)
    print(f"load {session} {end - start:.0f}s", flush=True)
    mono = [read_stereo(piece).mean(axis=1) for piece in pieces]
    audio = np.asarray(resample_concat(mono, up=1, down=RAW_SR // SR), dtype=np.float32)
    return audio, start, end


def _stamp(session: str) -> str:
    parts = session.split("_")
    return parts[1] + parts[2]


def _eligible(row: dict, session: str) -> bool:
    if row.get("condition") not in KEEP or row.get("who") not in set(CAST["tnf"]):
        return False
    other = row.get("session")
    if other in HOLDOUTS:
        return False
    if other == session:
        return True
    return _stamp(other) < _stamp(session)


def _enroll(encoder, session: str) -> tuple[dict[str, list[np.ndarray]], dict[str, list[float]], list[dict]]:
    """Prior games are available immediately. This game's clips start at their end."""
    vectors: dict[str, list[np.ndarray]] = defaultdict(list)
    ready: dict[str, list[float]] = defaultdict(list)
    used = []
    for row in _latest_labels():
        if not _eligible(row, session):
            continue
        audio = _clip(row["session"], float(row["play_start"]), float(row["duration"]))
        vector = _embed_windows(audio, [(0.0, len(audio) / SR)], encoder, 1)[0]
        end = 0.0 if row["session"] != session else float(row["play_start"]) + float(row["duration"])
        vectors[row["who"]].append(vector)
        ready[row["who"]].append(end)
        used.append(
            {
                "id": row["id"],
                "session": row["session"],
                "who": row["who"],
                "condition": row["condition"],
                "play_start": row["play_start"],
                "available_at": end,
            }
        )
    if not used:
        raise RuntimeError(f"no causal TNF enrollment for {session}")
    return vectors, ready, used


def _match(
    units: np.ndarray,
    window_ends: np.ndarray,
    vectors: dict[str, list[np.ndarray]],
    ready: dict[str, list[float]],
    names: list[str],
) -> tuple[np.ndarray, np.ndarray]:
    """Cosine to each cast member, using only clips already heard."""
    people = np.full((len(window_ends), len(names)), np.nan, dtype=np.float32)
    order = np.argsort(window_ends)
    for slot, name in enumerate(names):
        clip_ready = np.asarray(ready[name], dtype=np.float64)
        clip_rows = np.stack(vectors[name])
        rank = np.argsort(clip_ready)
        clip_ready = clip_ready[rank]
        clip_rows = clip_rows[rank]
        running = np.zeros(clip_rows.shape[1], dtype=np.float64)
        cursor = 0
        for index in order:
            moment = float(window_ends[index])
            while cursor < len(clip_ready) and clip_ready[cursor] <= moment + 1e-9:
                running += clip_rows[cursor]
                cursor += 1
            if cursor == 0:
                continue
            proto = running / max(np.linalg.norm(running), 1e-12)
            people[index, slot] = float(units[index] @ proto)
    finite = np.isfinite(people)
    masked = np.where(finite, people, -np.inf)
    cosine = masked.max(axis=1).astype(np.float64)
    cosine[~finite.any(axis=1)] = np.nan
    return cosine, people


def _session(encoder, session: str) -> None:
    if (OUT / f"{session}.npz").is_file() and (OUT / f"{session}.json").is_file():
        print(f"cached {session}", flush=True)
        return
    vectors, ready, used = _enroll(encoder, session)
    names = [name for name in CAST["tnf"] if name in vectors]
    audio, start, end = _coverage_audio(session)
    regions, vad = _speech_regions(audio)
    windows = embedding_windows(regions)
    print(f"{session} windows {len(windows)}", flush=True)
    embedded = _embed_windows(audio, windows, encoder, 16)
    units = embedded / np.maximum(np.linalg.norm(embedded, axis=1, keepdims=True), 1e-12)
    # Window times are offsets into an audio buffer that begins at `start`.
    window_ends = np.asarray([item[1] + start for item in windows], dtype=np.float64)
    cosine, people = _match(units, window_ends, vectors, ready, names)
    OUT.mkdir(parents=True, exist_ok=True)
    np.savez(
        OUT / f"{session}.npz",
        start=np.asarray([item[0] + start for item in windows], dtype=np.float64),
        end=window_ends,
        cosine=cosine.astype(np.float64),
        people=people.astype(np.float32),
    )
    receipt = {
        "session": session,
        "model": EMBEDDING_MODEL_ID,
        "coverage": [start, end],
        "vad": vad,
        "windows": len(windows),
        "names": names,
        "enrollment_clips": used,
        "enrollment": "prior games are available at kickoff; a clip from this game starts at its own end",
        "saved_enroll_tnf_npy_used": False,
        "sealed_holdouts_read": False,
    }
    (OUT / f"{session}.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    print(f"wrote {session} max cosine {float(cosine.max()):.3f}", flush=True)


def main() -> None:
    encoder = _load_encoder(MODEL)
    for session in PRIME_SESSIONS:
        _session(encoder, session)


if __name__ == "__main__":
    main()
