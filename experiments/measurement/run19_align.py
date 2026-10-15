"""Test whether frozen run19 is the same audio as audio_0023.wav.

This does not change the live engine, thresholds, booth identities, or gold.
It does not use commercial labels to choose an offset.

A duration match is not acceptance. A feature correlation is not a sample lock.
Sample lock would require a persisted sample counter or a chunk-open timestamp
that ties engine time to a WAV sample. This session does not have one.
"""

from __future__ import annotations

import hashlib
import json
import wave
from pathlib import Path

import numpy as np
from scipy.signal import resample_poly

from hush.program_cloud import HOP_S, MEMORY_S, SR, WINDOW_S
from ohush_live.policy import AUDIO_MIN_REFERENCE_S

REPO = Path(__file__).resolve().parents[2]
FROZEN = REPO / "docs/ohush/experiments/LIVE_RECOVERY_001/inputs/session_2026-10-08-tnf"
LIVE = REPO / "ohush_live/sessions/2026-10-08-tnf"
CHECKPOINT = REPO / "experiments/exp003/models/Cnn14_mAP=0.431.pth"
OUT = REPO / "docs/ohush/research/run19_alignment.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def segment_runs(rows: list[dict]) -> list[list[dict]]:
    runs: list[list[dict]] = []
    current: list[dict] = []
    previous = None
    for row in rows:
        t = float(row.get("t") or 0)
        if previous is not None and t + 1e-6 < previous:
            if current:
                runs.append(current)
            current = []
        current.append(row)
        previous = t
    if current:
        runs.append(current)
    return runs


def wav_info(path: Path) -> dict:
    with wave.open(str(path), "rb") as handle:
        rate = handle.getframerate()
        frames = handle.getnframes()
        channels = handle.getnchannels()
        width = handle.getsampwidth()
    stat = path.stat()
    return {
        "name": path.name,
        "bytes": stat.st_size,
        "sha256": sha256(path),
        "sample_rate": rate,
        "channels": channels,
        "sample_width": width,
        "frames": frames,
        "duration_s": frames / float(rate),
        "mtime_unix": stat.st_mtime,
        "birthtime_unix": getattr(stat, "st_birthtime", None),
    }


def read_mono_32k(path: Path) -> np.ndarray:
    """Same mix the live desk feeds the audio worker: stereo mean, then 48 kHz to 32 kHz."""
    with wave.open(str(path), "rb") as handle:
        if handle.getnchannels() != 2 or handle.getsampwidth() != 2 or handle.getframerate() != 48000:
            raise RuntimeError(f"{path.name} is not 48 kHz stereo PCM16")
        pcm = np.frombuffer(handle.readframes(handle.getnframes()), dtype=np.int16).reshape(-1, 2)
    mono = pcm.astype(np.float32).mean(axis=1) / 32768.0
    return resample_poly(mono, 2, 3).astype(np.float32)


def embed(audio: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    import os

    import torch
    import torch.backends.nnpack as nnpack
    from panns_inference import AudioTagging

    os.environ.setdefault("OMP_NUM_THREADS", "1")
    nnpack.set_flags(False)
    torch.set_num_threads(1)
    torch.set_grad_enabled(False)
    tagger = AudioTagging(checkpoint_path=str(CHECKPOINT), device="cpu")
    window = int(round(WINDOW_S * SR))
    if len(audio) < window:
        raise RuntimeError("audio is shorter than the 10 s window")
    duration = len(audio) / SR
    ends = np.arange(WINDOW_S, duration + 1e-9, HOP_S, dtype=np.float64)
    ends = ends[ends <= duration + 1e-9]
    rows = []
    batch = 8
    total = len(ends)
    for offset in range(0, total, batch):
        frames = []
        for end in ends[offset : offset + batch]:
            stop = int(round(float(end) * SR))
            frames.append(audio[stop - window : stop])
        matrix = np.stack(frames).astype(np.float32)
        _clip, embedding = tagger.inference(matrix)
        del _clip
        emb = np.asarray(embedding, dtype=np.float64)
        norms = np.linalg.norm(emb, axis=1, keepdims=True)
        if np.any(norms == 0.0):
            raise RuntimeError("encoder returned a zero embedding")
        rows.append(emb / norms)
        done = offset + len(frames)
        if done == total or done % 64 < batch:
            print(f"embedded {done}/{total}", flush=True)
    return ends, np.vstack(rows)


def live_scores(ends: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    """audio_worker._latest: cosine distance to the causal cloud. Minimum reference is 15 s."""
    scores = np.full(len(ends), np.nan, dtype=np.float64)
    for index, end in enumerate(ends):
        start = float(end) - WINDOW_S
        chosen = np.flatnonzero((ends <= start + 1e-9) & (ends > start - MEMORY_S))
        if chosen.size == 0:
            continue
        span = float(ends[chosen[-1]] - ends[chosen[0]])
        if span + 1e-9 < AUDIO_MIN_REFERENCE_S:
            continue
        centroid = matrix[chosen].mean(axis=0)
        norm = np.linalg.norm(centroid)
        if norm == 0.0 or not np.isfinite(norm):
            continue
        scores[index] = 1.0 - float(np.dot(matrix[index], centroid / norm))
    return scores


def logged_series(run: list[dict]) -> tuple[np.ndarray, np.ndarray]:
    times = []
    values = []
    for row in run:
        audio = row.get("audio") or {}
        score = audio.get("departure")
        if score is None:
            continue
        times.append(float(row["t"]))
        values.append(float(score))
    return np.asarray(times, dtype=np.float64), np.asarray(values, dtype=np.float64)


def pearson(left: np.ndarray, right: np.ndarray) -> float | None:
    if len(left) < 30:
        return None
    if float(np.std(left)) < 1e-8 or float(np.std(right)) < 1e-8:
        return None
    return float(np.corrcoef(left, right)[0, 1])


def paired(engine_t: np.ndarray, engine_y: np.ndarray, wav_t: np.ndarray, wav_y: np.ndarray, offset: float) -> tuple[np.ndarray, np.ndarray]:
    """Pair each engine score with the WAV score nearest to engine_t + offset."""
    left = []
    right = []
    finite = np.isfinite(wav_y)
    usable_t = wav_t[finite]
    usable_y = wav_y[finite]
    if usable_t.size == 0:
        return np.asarray([]), np.asarray([])
    for t, y in zip(engine_t, engine_y):
        target = float(t) + offset
        index = int(np.argmin(np.abs(usable_t - target)))
        if abs(float(usable_t[index]) - target) > 0.6:
            continue
        left.append(float(y))
        right.append(float(usable_y[index]))
    return np.asarray(left), np.asarray(right)


def search(engine_t, engine_y, wav_t, wav_y, offsets: np.ndarray) -> list[dict]:
    found = []
    for offset in offsets:
        left, right = paired(engine_t, engine_y, wav_t, wav_y, float(offset))
        corr = pearson(left, right)
        if corr is None:
            continue
        residual = left - right
        found.append(
            {
                "offset_s": round(float(offset), 3),
                "pairs": int(len(left)),
                "pearson_r": round(corr, 4),
                "mae": round(float(np.mean(np.abs(residual))), 4),
            }
        )
    found.sort(key=lambda row: row["pearson_r"], reverse=True)
    return found


def third_offsets(engine_t, engine_y, wav_t, wav_y, center: float) -> list[dict]:
    if engine_t.size == 0:
        return []
    lo, hi = float(engine_t[0]), float(engine_t[-1])
    edges = [lo + (hi - lo) * part / 3 for part in range(4)]
    offsets = np.arange(center - 5.0, center + 5.01, 0.25)
    out = []
    for index in range(3):
        if index == 2:
            mask = (engine_t >= edges[index]) & (engine_t <= edges[index + 1])
        else:
            mask = (engine_t >= edges[index]) & (engine_t < edges[index + 1])
        ranked = search(engine_t[mask], engine_y[mask], wav_t, wav_y, offsets)
        best = ranked[0] if ranked else None
        out.append({"third": index + 1, "engine_t0": round(edges[index], 3), "engine_t1": round(edges[index + 1], 3), "best": best})
    return out


def main() -> None:
    track = load_jsonl(FROZEN / "track.jsonl")
    runs = segment_runs(track)
    run = runs[19]
    t_end = float(run[-1]["t"])
    dropped = [int(row.get("dropped_frames") or 0) for row in run]
    lags = [float(row.get("lag_ms") or 0) for row in run]
    engine_t, engine_y = logged_series(run)
    wavs = sorted(LIVE.glob("audio_*.wav"))
    inventory = [wav_info(path) for path in wavs]
    candidate = next(row for row in inventory if row["name"] == "audio_0023.wav")
    others = [row for row in inventory if row["name"] != "audio_0023.wav" and row["duration_s"] >= 120]
    others.sort(key=lambda row: abs(row["duration_s"] - candidate["duration_s"]))
    alternatives = others[:2]
    anchors = {
        "frozen_track_rows": len(track),
        "frozen_track_runs": len(runs),
        "run_index": 19,
        "run_rows": len(run),
        "run_t_end": round(t_end, 3),
        "track_has_sample_index": False,
        "track_has_wall_clock": False,
        "track_events": sorted({row.get("event") for row in track}),
        "chunk_writer_persists_open_time": False,
        "decisions_have_only_relative_t": True,
        "dropped_frames_max": max(dropped) if dropped else None,
        "lag_ms_median": round(float(np.median(lags)), 3) if lags else None,
        "logged_audio_scores": int(engine_y.size),
        "logged_score_t0": None if engine_t.size == 0 else round(float(engine_t[0]), 3),
        "logged_score_t1": None if engine_t.size == 0 else round(float(engine_t[-1]), 3),
        "duration_delta_s": round(candidate["duration_s"] - t_end, 3),
        "note": (
            "Engine t and the WAV sample index are separate clocks. "
            "File mtime is when the chunk was last written, not a timestamp stored beside t."
        ),
    }
    print(json.dumps({"anchors": anchors, "candidate": candidate["name"], "alternatives": [row["name"] for row in alternatives]}, indent=2), flush=True)

    results = []
    files = [candidate] + alternatives
    for info in files:
        path = LIVE / info["name"]
        print(f"reading {info['name']}", flush=True)
        audio = read_mono_32k(path)
        ends, matrix = embed(audio)
        scores = live_scores(ends, matrix)
        wide = search(engine_t, engine_y, ends, scores, np.arange(-120, 120.01, 1.0))
        best = wide[0]
        fine_center = best["offset_s"]
        fine = search(
            engine_t,
            engine_y,
            ends,
            scores,
            np.arange(fine_center - 2.0, fine_center + 2.01, 0.25),
        )
        top = fine[0]
        results.append(
            {
                "file": info["name"],
                "sha256": info["sha256"],
                "duration_s": round(info["duration_s"], 3),
                "defined_wav_scores": int(np.isfinite(scores).sum()),
                "best_wide": best,
                "best_fine": top,
                "top_fine": fine[:5],
                "thirds": third_offsets(engine_t, engine_y, ends, scores, top["offset_s"])
                if info["name"] == "audio_0023.wav"
                else [],
            }
        )
        print(json.dumps({"file": info["name"], "best_fine": top}, indent=2), flush=True)

    candidate_result = results[0]
    other_best = max((row["best_fine"]["pearson_r"] for row in results[1:]), default=None)
    third_best = [row["best"]["offset_s"] for row in candidate_result["thirds"] if row.get("best")]
    offset_span = None if len(third_best) < 2 else round(max(third_best) - min(third_best), 3)
    feature_r = candidate_result["best_fine"]["pearson_r"]
    feature_aligned = (
        feature_r >= 0.85
        and offset_span is not None
        and offset_span <= 1.0
        and other_best is not None
        and feature_r - other_best >= 0.25
    )
    report = {
        "question": "Does frozen run19 join audio_0023.wav?",
        "scientific_authority": False,
        "sample_locked": False,
        "feature_aligned": feature_aligned,
        "join_accepted": False,
        "rejection_reason": (
            "No persisted sample counter or chunk-open timestamp ties engine t to a WAV sample. "
            "Duration agreement of 0.30 s is not a join. "
            + (
                "The frozen CNN14 distance series does line up with this file, but that is feature alignment, not a sample lock, so engine decisions are not attributed to these samples."
                if feature_aligned
                else "The frozen CNN14 distance series does not establish a unique, stable offset against this file."
            )
        ),
        "acceptance_rule": {
            "sample_lock_requires": "a stored sample index or chunk-open time shared with engine t",
            "feature_alignment_requires": "pearson r >= 0.85, third-wise offset span <= 1 s, and r at least 0.25 above the best alternative file",
            "commercial_labels_used": False,
            "live_reference_s": AUDIO_MIN_REFERENCE_S,
            "window_s": WINDOW_S,
            "memory_s": MEMORY_S,
            "embedding": "Cnn14_mAP=0.431.pth",
        },
        "anchors": anchors,
        "candidate": {key: candidate[key] for key in ("name", "sha256", "duration_s", "frames", "bytes")},
        "comparisons": results,
        "alternative_best_r": other_best,
        "third_offset_span_s": offset_span,
        "frozen_track_sha256": sha256(FROZEN / "track.jsonl"),
    }
    OUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"wrote": str(OUT), "feature_aligned": feature_aligned, "join_accepted": False, "r": feature_r, "other": other_best, "span": offset_span}, indent=2), flush=True)


if __name__ == "__main__":
    main()
