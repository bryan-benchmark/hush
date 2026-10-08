"""Experiment 002: does a recurring speaker ecosystem mark programming?

Unlabeled run. This module does not read the truth ledger, Exp001 scores,
or sealed holdouts.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
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

from hush.speaker_memory import (
    EMBEDDING_MODEL_ID,
    EXPERIMENT_SPEC_VERSION,
    FEATURE_SCHEMA_VERSION,
    PARAMS,
    SR,
    VAD_IMPL,
    VAD_MIN_SILENCE_MS,
    VAD_MIN_SPEECH_MS,
    VAD_SPEECH_PAD_MS,
    VAD_THRESHOLD,
    OnlineSpeakerMemory,
    build_timeline,
    embedding_windows,
    merge_regions,
    unlabeled_summary,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SESSION_ID = "hush_20260914_212529"
T0 = 0.0
T1 = 6899.0
HOLDOUTS = ("hush_20260917_205513", "hush_20260920_200635")
DERIVED_WAV = (
    REPO_ROOT
    / "experiments"
    / "exp001"
    / "derived"
    / "hush_20260914_212529_0_6899_16k_mono.wav"
)


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
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True)
    return head.stdout.strip()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _refuse_holdout(text: str) -> None:
    for session in HOLDOUTS:
        if session in text:
            raise SystemExit(f"refusing sealed holdout {session}")


def _load_audio(path: Path) -> np.ndarray:
    info = sf.info(path)
    expected = int(round((T1 - T0) * SR))
    if info.samplerate != SR or info.channels != 1 or info.frames != expected:
        raise SystemExit(
            f"expected {expected} mono frames at {SR} Hz, got sr={info.samplerate} "
            f"channels={info.channels} frames={info.frames}"
        )
    audio, _ = sf.read(path, dtype="float32", always_2d=False)
    return np.asarray(audio, dtype=np.float32)


def _speech_regions(audio: np.ndarray) -> tuple[list[tuple[float, float]], dict]:
    import torch
    from silero_vad import get_speech_timestamps, load_silero_vad

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
    info = {
        "implementation": VAD_IMPL,
        "package": _pkg("silero-vad"),
        "n_raw_regions": len(raw),
        "n_regions_at_least_min_speech": len(kept),
        "per_region_confidence": None,
        "confidence_note": "Silero's segment API does not return a per-region confidence.",
    }
    return kept, info


def _load_encoder(savedir: Path, device: str):
    import torch
    from speechbrain.inference.speaker import EncoderClassifier

    savedir.mkdir(parents=True, exist_ok=True)
    encoder = EncoderClassifier.from_hparams(
        source=EMBEDDING_MODEL_ID,
        savedir=str(savedir),
        run_opts={"device": device},
    )
    encoder.device = torch.device(device)
    return encoder


def _embed_windows(audio: np.ndarray, windows: list[tuple[float, float]], encoder, device: str, batch_size: int) -> np.ndarray:
    import torch

    groups: dict[int, list[int]] = {}
    pieces: list[np.ndarray] = []
    for index, (start, end) in enumerate(windows):
        i0 = int(round(start * SR))
        i1 = int(round(end * SR))
        i0 = max(0, min(i0, audio.shape[0] - 1))
        i1 = max(i0 + 1, min(i1, audio.shape[0]))
        piece = np.asarray(audio[i0:i1], dtype=np.float32)
        pieces.append(piece)
        groups.setdefault(piece.shape[0], []).append(index)

    out = np.zeros((len(windows), 0), dtype=np.float32)
    dim = None
    done = 0
    with torch.inference_mode():
        for length, indexes in groups.items():
            for offset in range(0, len(indexes), batch_size):
                batch_ids = indexes[offset : offset + batch_size]
                batch = torch.from_numpy(np.stack([pieces[i] for i in batch_ids])).to(device)
                encoded = encoder.encode_batch(batch, normalize=False)
                arr = encoded.detach().float().cpu().numpy()
                arr = np.squeeze(arr, axis=1) if arr.ndim == 3 else arr
                if dim is None:
                    dim = int(arr.shape[-1])
                    out = np.zeros((len(windows), dim), dtype=np.float32)
                out[batch_ids] = arr
                done += len(batch_ids)
                if done % 256 < len(batch_ids):
                    print(f"embedded {done}/{len(windows)}", flush=True)
    norms = np.linalg.norm(out, axis=1, keepdims=True)
    if np.any(norms < 1e-6):
        raise SystemExit("encoder returned a zero embedding")
    return (out / norms).astype(np.float32)


def _assign(embeddings: np.ndarray, windows: list[tuple[float, float]]) -> list[dict]:
    memory = OnlineSpeakerMemory()
    rows = []
    for index, ((start, end), emb) in enumerate(zip(windows, embeddings)):
        row = memory.observe(emb, start, end)
        row["embedding_id"] = f"e{index:06d}"
        row["embedding"] = emb
        rows.append(row)
    return rows


def _write_segments(path: Path, regions: list[tuple[float, float]], windows: list[dict]) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    rows: list[dict] = []
    for start, end in regions:
        rows.append(
            {
                "row_kind": "speech_region",
                "start_seconds": start,
                "end_seconds": end,
                "duration": end - start,
                "speech_confidence": None,
                "window_start": None,
                "window_end": None,
                "embedding_id": None,
                "embedding": None,
            }
        )
    cluster_keys = [
        "match_decision",
        "assigned_cluster_id",
        "matched_cluster_id",
        "similarity_to_best_known",
        "similarity_to_best_recurring",
        "speaker_is_novel",
        "speaker_is_recurring",
        "cluster_age_seconds",
        "cluster_last_seen_seconds",
        "cluster_cumulative_speech_seconds",
        "cluster_occurrence_count",
        "program_speaker_return_score",
        "cum_after",
        "occ_after",
        "first_seen",
        "last_seen_after",
        "recurring_after",
    ]
    for row in windows:
        item = {
            "row_kind": "embedding_window",
            "start_seconds": row["window_start"],
            "end_seconds": row["window_end"],
            "duration": row["duration"],
            "speech_confidence": None,
            "window_start": row["window_start"],
            "window_end": row["window_end"],
            "embedding_id": row["embedding_id"],
            "embedding": row["embedding"].astype(np.float32),
        }
        for key in cluster_keys:
            item[key] = row[key]
        rows.append(item)

    frame = pd.DataFrame(rows)
    embedding = pa.array(frame["embedding"].tolist(), type=pa.list_(pa.float32()))
    table = pa.Table.from_pandas(frame.drop(columns=["embedding"]), preserve_index=False)
    table = table.append_column("embedding", embedding)
    pq.write_table(table, path)


def _plots(timeline: dict[str, np.ndarray], windows: list[dict], output: Path) -> None:
    minutes = timeline["timestamp_seconds"] / 60.0

    fig, axes = plt.subplots(5, 1, figsize=(14, 12), sharex=True)
    axes[0].plot(minutes, timeline["speech_active"], color="0.2", lw=0.6)
    axes[0].set_ylabel("speech")
    axes[1].plot(minutes, timeline["speaker_is_recurring"], color="tab:blue", lw=0.6)
    axes[1].set_ylabel("recurring")
    axes[2].plot(minutes, timeline["speaker_is_novel"], color="tab:orange", lw=0.6)
    axes[2].set_ylabel("novel")
    cont = np.ma.masked_invalid(timeline["program_speaker_continuity_score"])
    axes[3].plot(minutes, cont, color="tab:purple", lw=0.7)
    axes[3].set_ylabel("continuity")
    axes[3].set_ylim(-0.05, 1.05)
    since = np.ma.masked_invalid(timeline["seconds_since_any_recurring_speaker"])
    axes[4].plot(minutes, since, color="tab:green", lw=0.7)
    axes[4].set_ylabel("sec since recurring")
    axes[4].set_xlabel("minutes")
    fig.suptitle("Exp002 speaker continuity (unlabeled)")
    fig.tight_layout()
    fig.savefig(output / "speaker_continuity.png", dpi=120)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(14, 6))
    if windows:
        x = np.asarray([w["window_end"] for w in windows]) / 60.0
        y = np.asarray([int(w["assigned_cluster_id"][1:]) for w in windows])
        recurring = np.asarray([w["speaker_is_recurring"] for w in windows])
        ax.scatter(x[~recurring], y[~recurring], s=6, c="0.75", label="not yet recurring", linewidths=0)
        ax.scatter(x[recurring], y[recurring], s=8, c="tab:blue", label="already recurring", linewidths=0)
        ax.legend(loc="upper right")
    ax.set_xlabel("minutes")
    ax.set_ylabel("cluster (discovery order)")
    ax.set_title("Exp002 clusters (color is causal, unlabeled)")
    fig.tight_layout()
    fig.savefig(output / "speaker_clusters.png", dpi=120)
    plt.close(fig)

    fig, axes = plt.subplots(4, 1, figsize=(14, 10), sharex=True)
    axes[0].plot(minutes, timeline["unique_speaker_clusters_30s"], color="0.2", lw=0.7)
    axes[0].set_ylabel("unique / 30s")
    ent = np.ma.masked_invalid(timeline["speaker_cluster_entropy_30s"])
    axes[1].plot(minutes, ent, color="tab:blue", lw=0.7)
    axes[1].set_ylabel("entropy")
    axes[2].plot(minutes, timeline["speaker_turnover_rate_30s"], color="tab:orange", lw=0.7)
    axes[2].set_ylabel("switches / 30s")
    novel = np.ma.masked_invalid(timeline["novel_speaker_fraction_30s"])
    axes[3].plot(minutes, novel, color="tab:red", lw=0.7)
    axes[3].set_ylabel("novel fraction")
    axes[3].set_xlabel("minutes")
    axes[3].set_ylim(-0.05, 1.05)
    fig.suptitle("Exp002 speaker turnover (unlabeled)")
    fig.tight_layout()
    fig.savefig(output / "speaker_turnover.png", dpi=120)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(14, 4))
    ax.plot(minutes, timeline["program_speaker_return_score"], color="tab:green", lw=0.7)
    ax.set_xlabel("minutes")
    ax.set_ylabel("return score")
    ax.set_title("Exp002 recurring-speaker returns (unlabeled)")
    fig.tight_layout()
    fig.savefig(output / "speaker_returns.png", dpi=120)
    plt.close(fig)


def _model_revision(savedir: Path) -> str | None:
    try:
        from huggingface_hub import model_info

        info = model_info(EMBEDDING_MODEL_ID)
        return info.sha
    except Exception as exc:  # receipt only; the local files still identify the run
        print(f"model revision lookup failed: {exc}", flush=True)
        return None


def run(wav_path: Path, output: Path, device: str, batch_size: int) -> None:
    _refuse_holdout(str(wav_path))
    _refuse_holdout(SESSION_ID)
    output.mkdir(parents=True, exist_ok=True)
    cache = REPO_ROOT / "experiments" / "exp002" / ".cache"
    cache.mkdir(parents=True, exist_ok=True)
    os.environ["HF_HOME"] = str(cache / "hf")
    os.environ["HUGGINGFACE_HUB_CACHE"] = str(cache / "hf" / "hub")
    os.environ["TORCH_HOME"] = str(cache / "torch")

    import torch

    torch.set_grad_enabled(False)
    # The `enabled` attribute on this torch build does not toggle the kernel.
    # NNPACK's conv1d path is pathologically slow here. set_flags actually disables it.
    torch.backends.nnpack.set_flags(False)
    n_threads = min(8, os.cpu_count() or 1)
    torch.set_num_threads(n_threads)
    print(f"nnpack={torch._C._get_nnpack_enabled()} threads={n_threads}", flush=True)
    print("reading audio", flush=True)
    audio = _load_audio(wav_path)
    print("speech segmentation", flush=True)
    regions, vad_info = _speech_regions(audio)
    windows = embedding_windows(regions)
    print(f"regions={len(regions)} windows={len(windows)}", flush=True)
    if not windows:
        raise SystemExit("no embedding windows")

    savedir = REPO_ROOT / "experiments" / "exp002" / "models" / "spkrec-ecapa-voxceleb"
    print(f"loading {EMBEDDING_MODEL_ID} on {device}", flush=True)
    encoder = _load_encoder(savedir, device)
    embeddings = _embed_windows(audio, windows, encoder, device, batch_size)
    assigned = _assign(embeddings, windows)
    timeline = build_timeline(regions, assigned, T1 - T0)
    summary = unlabeled_summary(regions, assigned, timeline)
    norms = np.linalg.norm(embeddings, axis=1)
    summary["embedding_l2_norm"] = {
        "min": float(norms.min()),
        "max": float(norms.max()),
        "mean": float(norms.mean()),
    }
    summary["embedding_dim"] = int(embeddings.shape[1])

    print("writing artifacts", flush=True)
    _write_segments(output / "speaker_segments.parquet", regions, assigned)
    frame = pd.DataFrame(timeline)
    frame.to_parquet(output / "speaker_timeline.parquet", index=False)
    _plots(timeline, assigned, output)

    metadata = {
        "experiment_spec_version": EXPERIMENT_SPEC_VERSION,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "git_commit": _git_sha(REPO_ROOT),
        "python": sys.version,
        "platform": platform.platform(),
        "device": device,
        "torch_num_threads": n_threads,
        "nnpack_enabled": bool(torch._C._get_nnpack_enabled()),
        "mps_available": bool(torch.backends.mps.is_available()),
        "packages": {
            "torch": torch.__version__,
            "torchaudio": _pkg("torchaudio"),
            "speechbrain": _pkg("speechbrain"),
            "silero-vad": _pkg("silero-vad"),
            "numpy": _pkg("numpy"),
            "pandas": _pkg("pandas"),
            "pyarrow": _pkg("pyarrow"),
            "matplotlib": _pkg("matplotlib"),
            "soundfile": _pkg("soundfile"),
        },
        "session_id": SESSION_ID,
        "analysis_start_seconds": T0,
        "analysis_end_seconds": T1,
        "timestamps": "seconds since analysis_start_seconds",
        "source_audio": {
            "path": str(wav_path.relative_to(REPO_ROOT)),
            "sha256": _sha256(wav_path),
            "sample_rate": SR,
            "n_samples": int(audio.shape[0]),
            "note": (
                "Read-only 16 kHz mono derived by Exp001. Exp001 scores were not read."
                if SESSION_ID == "hush_20260914_212529"
                else "Read-only 16 kHz mono from the same resampler as Exp001. Exp001 scores were not read."
            ),
        },
        "embedding_model": {
            "id": EMBEDDING_MODEL_ID,
            "revision": _model_revision(savedir),
            "savedir": str(savedir.relative_to(REPO_ROOT)),
            "fine_tuned": False,
            "embedding_dim": int(embeddings.shape[1]),
            "normalization": "L2 after encode_batch(..., normalize=False), matching verify_batch cosine.",
        },
        "vad": vad_info,
        "params": PARAMS,
        "truth_ledger_read": False,
        "exp001_scores_read": False,
        "holdouts_read": False,
    }
    (output / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    printable = {
        key: summary[key]
        for key in (
            "n_speech_regions",
            "speech_region_seconds",
            "speech_active_fraction",
            "n_embedding_windows",
            "n_clusters",
            "n_recurring_clusters",
            "novel_window_fraction",
            "causal_fraction_of_attributed_speech_on_already_recurring",
            "end_state_fraction_of_speech_in_recurring_clusters",
            "first_recurring_window_end",
            "similarity_when_matched",
            "similarity_when_novel",
            "continuity_when_defined",
        )
    }
    print(json.dumps(printable, indent=2), flush=True)


def main() -> None:
    global SESSION_ID, T0, T1
    parser = argparse.ArgumentParser(description="Experiment 002 unlabeled speaker continuity")
    parser.add_argument("--session", default=SESSION_ID)
    parser.add_argument("--t0", type=float, default=T0)
    parser.add_argument("--t1", type=float, default=T1)
    parser.add_argument("--wav", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--device", choices=("cpu", "mps"), default="cpu")
    parser.add_argument("--batch-size", type=int, default=32)
    args = parser.parse_args()
    SESSION_ID = args.session
    T0 = args.t0
    T1 = args.t1
    if args.wav is None and (SESSION_ID != "hush_20260914_212529" or T0 != 0.0 or T1 != 6899.0):
        raise SystemExit("--wav is required unless this is the locked ESPN span")
    wav = args.wav if args.wav is not None else DERIVED_WAV
    output = args.output if args.output is not None else REPO_ROOT / "experiments" / "exp002" / SESSION_ID
    run(wav, output, args.device, args.batch_size)


if __name__ == "__main__":
    main()
