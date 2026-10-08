"""Experiment 003: distance from the recent program embedding cloud.

Unlabeled run on the ESPN dev session. This module does not read the truth
ledger, Exp001 scores, Exp002 scores, or sealed holdouts. It does not train
an ad classifier.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
import urllib.request
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

os.environ.setdefault(
    "MPLCONFIGDIR",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".mplconfig")),
)

import argparse

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import soundfile as sf

from hush.audio import RAW_SR, analysis_pieces, find_session, load_session, read_stereo, resample_concat, write_mono_wav
from hush.program_cloud import (
    CHECKPOINT_NAME,
    CHECKPOINT_URL,
    EMBEDDING_MODEL_ID,
    EXPERIMENT_SPEC_VERSION,
    FEATURE_SCHEMA_VERSION,
    HOP_S,
    PARAMS,
    SR,
    WINDOW_S,
    anomaly_scores,
    listing_peaks,
    window_bounds,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SESSION_ID = "hush_20260914_212529"
T0 = 0.0
T1 = 6899.0
HOLDOUTS = ("hush_20260917_205513", "hush_20260920_200635")
SOURCE_16K = (
    REPO_ROOT
    / "experiments"
    / "exp001"
    / "derived"
    / "hush_20260914_212529_0_6899_16k_mono.wav"
)
SOURCE_16K_SHA256 = "11e314c1588de6480f070f102f387e0e814f3c5bb89d7b9f3c5b66de500b8a41"
BATCH = 8


def _pkg(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:
        return "not-installed"


def _git_sha(root: Path) -> str | None:
    probe = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if probe.returncode != 0 or probe.stdout.strip() != "true":
        return None
    read = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if read.returncode != 0:
        return None
    return read.stdout.strip() or None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _refuse_holdout(text: str) -> None:
    for session in HOLDOUTS:
        if session in text:
            raise SystemExit(f"refusing sealed holdout {session}")


def _prepare_32k(session_dir: Path, meta: dict, dest: Path) -> np.ndarray:
    if dest.is_file():
        info = sf.info(str(dest))
        expected = int(round((T1 - T0) * SR))
        if info.samplerate == SR and info.channels == 1 and abs(info.frames - expected) <= 1:
            audio, rate = sf.read(str(dest), dtype="float32")
            if rate != SR:
                raise RuntimeError(f"stored analysis wav is {rate} Hz")
            return np.asarray(audio, dtype=np.float32)
    pieces = analysis_pieces(session_dir, meta, T0, T1)
    parts = []
    for piece in pieces:
        print(f"reading {piece['file']} {piece['session_start_seconds']:.1f}..{piece['session_end_seconds']:.1f}", flush=True)
        stereo = read_stereo(piece)
        parts.append(stereo.mean(axis=1))
        del stereo
    print("resampling one continuous 48 kHz mono stream to 32 kHz", flush=True)
    audio = np.asarray(resample_concat(parts, up=2, down=3), dtype=np.float32)
    expected = int(round((T1 - T0) * SR))
    if abs(len(audio) - expected) > 2:
        raise RuntimeError(f"32 kHz length {len(audio)} != {expected}")
    write_mono_wav(dest, audio, SR)
    return audio


def _checkpoint(model_dir: Path) -> Path:
    path = model_dir / CHECKPOINT_NAME
    if path.is_file() and path.stat().st_size > 300_000_000:
        return path
    model_dir.mkdir(parents=True, exist_ok=True)
    print(f"downloading {CHECKPOINT_NAME}", flush=True)
    urllib.request.urlretrieve(CHECKPOINT_URL, path)
    if path.stat().st_size < 300_000_000:
        raise RuntimeError(f"checkpoint download looks incomplete: {path}")
    return path


def _embed(audio: np.ndarray, checkpoint: Path, n_threads: int):
    import torch
    import torch.backends.nnpack as nnpack

    nnpack.set_flags(False)
    torch.set_num_threads(n_threads)
    from panns_inference import AudioTagging

    labels_csv = Path.home() / "panns_data" / "class_labels_indices.csv"
    if not labels_csv.is_file() or labels_csv.stat().st_size < 1000:
        labels_csv.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(
            "http://storage.googleapis.com/us_audioset/youtube_corpus/v1/csv/class_labels_indices.csv",
            labels_csv,
        )
    tagger = AudioTagging(checkpoint_path=str(checkpoint), device="cpu")
    # Times in the score file are seconds since T0. ESPN keeps T0 at 0, so this
    # matches the original session clock on that tape.
    starts, ends = window_bounds((T1 - T0), origin_s=0.0)
    window_samples = int(round(WINDOW_S * SR))
    rows = []
    total = len(starts)
    for offset in range(0, total, BATCH):
        frames = []
        for start in starts[offset : offset + BATCH]:
            a = int(round(float(start) * SR))
            frames.append(audio[a : a + window_samples])
        chunk = np.stack(frames).astype(np.float32)
        _clipwise, embedding = tagger.inference(chunk)
        del _clipwise
        matrix = np.asarray(embedding, dtype=np.float64)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        if np.any(norms == 0.0):
            raise RuntimeError("encoder returned a zero embedding")
        rows.append(matrix / norms)
        done = offset + len(frames)
        if done == total or done % 256 < BATCH:
            print(f"embedded {done}/{total}", flush=True)
    return starts, ends, np.vstack(rows)


def _plot(path: Path, minutes: np.ndarray, scores: np.ndarray) -> None:
    fig, ax = plt.subplots(figsize=(12, 3.4))
    ax.plot(minutes, scores, color="#1f4e79", lw=0.6)
    ax.set_xlim(float(minutes[0]), float(minutes[-1]))
    ax.set_xlabel("minutes")
    ax.set_ylabel("distance from recent cloud")
    ax.set_title("Exp003 program-cloud distance, unlabeled")
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=120)
    plt.close(fig)


def _plot_hist(path: Path, scores: np.ndarray) -> None:
    defined = scores[np.isfinite(scores)]
    fig, ax = plt.subplots(figsize=(6, 3.4))
    ax.hist(defined, bins=40, color="#1f4e79")
    ax.set_xlabel("distance from recent cloud")
    ax.set_ylabel("windows")
    ax.set_title("Defined scores only")
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def _espn_source_locked() -> bool:
    return SESSION_ID == "hush_20260914_212529" and T0 == 0.0 and T1 == 6899.0


def run(output: Path, recordings_root: Path) -> None:
    _refuse_holdout(SESSION_ID)
    _refuse_holdout(str(output))
    if _espn_source_locked():
        if not SOURCE_16K.is_file():
            raise SystemExit(f"missing derived wav {SOURCE_16K}")
        if _sha256(SOURCE_16K) != SOURCE_16K_SHA256:
            raise SystemExit("16 kHz derived wav hash does not match the Exp001/Exp002 file")
    session_dir = find_session(recordings_root, SESSION_ID)
    _refuse_holdout(str(session_dir))
    meta = load_session(session_dir)
    output.mkdir(parents=True, exist_ok=True)
    derived = output.parent / "derived" / f"{SESSION_ID}_{T0:.0f}_{T1:.0f}_32k_mono.wav"
    audio = _prepare_32k(session_dir, meta, derived)
    model_dir = output.parent / "models"
    checkpoint = _checkpoint(model_dir)
    n_threads = min(8, os.cpu_count() or 1)
    print(f"nnpack=False threads={n_threads} samples={len(audio)}", flush=True)
    starts, ends, embeddings = _embed(audio, checkpoint, n_threads)
    del audio
    scores, counts, spans = anomaly_scores(starts, ends, embeddings)
    frame = pd.DataFrame(
        {
            "window_start": starts,
            "window_end": ends,
            "anomaly": scores,
            "n_reference": counts,
            "reference_span_s": spans,
            "embedding": list(embeddings.astype(np.float32)),
        }
    )
    frame.to_parquet(output / "program_cloud.parquet", index=False)
    defined = scores[np.isfinite(scores)]
    peaks = listing_peaks(ends, scores)
    summary = {
        "experiment_spec_version": EXPERIMENT_SPEC_VERSION,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "session_id": SESSION_ID,
        "t0": T0,
        "t1": T1,
        "timestamps": "seconds since t0",
        "n_windows": int(len(scores)),
        "n_defined": int(defined.size),
        "first_defined_window_end": None if defined.size == 0 else float(ends[np.isfinite(scores)][0]),
        "anomaly_p10": None if defined.size == 0 else float(np.percentile(defined, 10)),
        "anomaly_p50": None if defined.size == 0 else float(np.percentile(defined, 50)),
        "anomaly_p90": None if defined.size == 0 else float(np.percentile(defined, 90)),
        "listing_peaks_not_a_mute_rule": peaks,
        "truth_ledger_read": False,
        "exp001_scores_read": False,
        "exp002_scores_read": False,
        "classifier_head_used": False,
        "params": PARAMS,
    }
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    _plot(output / "program_distance.png", ends / 60.0, scores)
    _plot_hist(output / "program_distance_hist.png", scores)
    metadata = {
        "experiment_spec_version": EXPERIMENT_SPEC_VERSION,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "session_id": SESSION_ID,
        "t0": T0,
        "t1": T1,
        "git_commit": _git_sha(REPO_ROOT),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "device": "cpu",
        "torch_num_threads": n_threads,
        "nnpack_enabled": False,
        "packages": {
            "torch": _pkg("torch"),
            "panns-inference": _pkg("panns-inference"),
            "numpy": _pkg("numpy"),
            "soundfile": _pkg("soundfile"),
        },
        "embedding_model": {
            "id": EMBEDDING_MODEL_ID,
            "checkpoint": CHECKPOINT_NAME,
            "checkpoint_url": CHECKPOINT_URL,
            "checkpoint_sha256": _sha256(checkpoint),
            "embedding": "penultimate CNN14 embedding, L2-normalized",
            "classifier_head_used": False,
            "fine_tuned": False,
        },
        "source_16k_sha256": SOURCE_16K_SHA256 if _espn_source_locked() else None,
        "analysis_wav": {
            "path": str(derived.relative_to(REPO_ROOT)),
            "sha256": _sha256(derived),
            "sample_rate_hz": SR,
            "channels": 1,
            "hop_s": HOP_S,
            "window_s": WINDOW_S,
        },
        "params": PARAMS,
        "truth_ledger_read": False,
        "holdouts_read": False,
        "exp001_scores_read": False,
        "exp002_scores_read": False,
    }
    (output / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(
        f"windows={summary['n_windows']} defined={summary['n_defined']} "
        f"p50={summary['anomaly_p50']}",
        flush=True,
    )


def main() -> None:
    global SESSION_ID, T0, T1
    parser = argparse.ArgumentParser(description="Unlabeled Exp003 program-cloud distance.")
    parser.add_argument("--session", default=SESSION_ID)
    parser.add_argument("--t0", type=float, default=T0)
    parser.add_argument("--t1", type=float, default=T1)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--recordings", type=Path, default=REPO_ROOT / "recordings")
    args = parser.parse_args()
    SESSION_ID = args.session
    T0 = args.t0
    T1 = args.t1
    output = args.output if args.output is not None else REPO_ROOT / "experiments" / "exp003" / SESSION_ID
    run(output, args.recordings)


if __name__ == "__main__":
    main()
