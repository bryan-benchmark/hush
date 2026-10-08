"""Unlabeled Exp005. Transcribes the ESPN dev wav, then scores language. Does not open the ledger."""

from __future__ import annotations

import hashlib
import json
import os
import wave
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

from hush.language import (
    EXPERIMENT_SPEC_VERSION,
    FEATURE_SCHEMA_VERSION,
    PARAMS as LANGUAGE_PARAMS,
    find_transitions,
    find_vocabulary,
)
from hush.semantic_text import (
    EMBEDDING_MODEL_ID,
    MIN_WORDS,
    PARAMS as SEMANTIC_PARAMS,
    WINDOW_S,
    anomaly_scores,
    window_bounds,
)

REPO = Path(__file__).resolve().parents[2]
SESSION = "hush_20260914_212529"
HOLDOUTS = ("hush_20260917_205513", "hush_20260920_200635")
ANALYSIS_START = 0.0
ANALYSIS_END = 6899.0
SOURCE_16K = REPO / "experiments" / "exp001" / "derived" / "hush_20260914_212529_0_6899_16k_mono.wav"
SOURCE_16K_SHA256 = "11e314c1588de6480f070f102f387e0e814f3c5bb89d7b9f3c5b66de500b8a41"
ASR_MODEL = "medium.en"
ASR_COMPUTE = "int8"
DENSITY_S = 10.0


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _refuse(path: Path) -> None:
    if SESSION in HOLDOUTS or any(token in str(path) for token in HOLDOUTS):
        raise SystemExit(f"refusing sealed holdout {SESSION}")


def _espn_source_locked() -> bool:
    return SESSION == "hush_20260914_212529" and ANALYSIS_START == 0.0 and ANALYSIS_END == 6899.0


def transcribe(wav: Path, output: Path) -> pd.DataFrame:
    """Frozen ASR. No initial prompt, no commercial vocabulary, no ledger."""
    _refuse(wav)
    digest = _sha256(wav)
    if _espn_source_locked() and digest != SOURCE_16K_SHA256:
        raise SystemExit(f"refusing {wav}: sha256 is not the Exp001 16 kHz wav")
    from faster_whisper import WhisperModel

    output.mkdir(parents=True, exist_ok=True)
    with wave.open(str(wav), "rb") as handle:
        if handle.getnchannels() != 1 or handle.getframerate() != 16000 or handle.getsampwidth() != 2:
            raise SystemExit(f"refusing {wav}: expected 16 kHz mono 16-bit PCM")
        pcm = np.frombuffer(handle.readframes(handle.getnframes()), dtype=np.int16)
    audio = pcm.astype(np.float32) / 32768.0
    model = WhisperModel(
        ASR_MODEL,
        device="cpu",
        compute_type=ASR_COMPUTE,
        cpu_threads=8,
        download_root=str(REPO / "experiments" / "exp005" / "models"),
    )
    segments, info = model.transcribe(
        audio,
        language="en",
        task="transcribe",
        beam_size=5,
        temperature=0.0,
        condition_on_previous_text=False,
        word_timestamps=True,
        vad_filter=False,
        without_timestamps=False,
        initial_prompt=None,
    )
    words = []
    segment_rows = []
    for segment in segments:
        segment_rows.append(
            {
                "start": float(segment.start),
                "end": float(segment.end),
                "text": segment.text,
            }
        )
        for word in segment.words or []:
            start = float(word.start)
            end = float(word.end)
            if start >= ANALYSIS_END or end < 0:
                continue
            words.append(
                {
                    "start": start,
                    "end": min(end, ANALYSIS_END),
                    "text": word.word,
                    "probability": float(word.probability),
                }
            )
        if len(segment_rows) % 20 == 0:
            print(f"asr_segments={len(segment_rows)} last_end={segment.end:.1f}", flush=True)
    word_frame = pd.DataFrame(words)
    word_frame.to_parquet(output / "words.parquet", index=False)
    pd.DataFrame(segment_rows).to_parquet(output / "segments.parquet", index=False)
    meta = {
        "experiment_spec_version": EXPERIMENT_SPEC_VERSION,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "session_id": SESSION,
        "asr_model": ASR_MODEL,
        "asr_compute_type": ASR_COMPUTE,
        "asr_device": "cpu",
        "language": "en",
        "beam_size": 5,
        "temperature": 0.0,
        "condition_on_previous_text": False,
        "vad_filter": False,
        "initial_prompt": None,
        "word_timestamps": True,
        "duration_after_vad": float(getattr(info, "duration_after_vad", ANALYSIS_END) or ANALYSIS_END),
        "source_wav_sha256": digest,
        "n_words": int(len(word_frame)),
        "n_segments": len(segment_rows),
        "truth_ledger_read": False,
        "note": "This is ASR dictation, not broadcast closed captions.",
    }
    (output / "asr_metadata.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    print(f"words={len(word_frame)} segments={len(segment_rows)}", flush=True)
    return word_frame


def _plot(path: Path, ends: np.ndarray, density: np.ndarray, semantic: np.ndarray, cues: list[dict]) -> None:
    fig, axes = plt.subplots(3, 1, figsize=(14, 8.0), sharex=True)
    minutes = ends / 60.0
    for cue in cues:
        color = "#a33b20" if cue["kind"] == "departure" else "#0b6e4f"
        axes[0].axvline(cue["start"] / 60.0, color=color, lw=0.6, alpha=0.8)
    axes[0].set_ylabel("phrase cues")
    axes[0].set_yticks([])
    axes[1].plot(minutes, density, color="#1f4e79", lw=0.6)
    axes[1].set_ylabel("ad words / 10 s")
    axes[2].plot(minutes, semantic, color="#0b6e4f", lw=0.6)
    axes[2].set_ylabel("semantic distance")
    axes[2].set_xlabel("minutes")
    for ax in axes:
        ax.set_xlim(0, ANALYSIS_END / 60.0)
    axes[0].set_title("Exp005 unlabeled. Red departure cues, green return cues. No commercial shading.")
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=120)
    plt.close(fig)


def score(words: pd.DataFrame, output: Path) -> dict:
    _refuse(output)
    records = words.to_dict(orient="records")
    cues = find_transitions(records)
    vocabulary = find_vocabulary(records)
    starts = np.array([float(row["start"]) for row in vocabulary], dtype=np.float64)
    grid = np.arange(DENSITY_S, ANALYSIS_END + 1e-9, 1.0)
    density = np.array([int(np.sum((starts > item - DENSITY_S) & (starts <= item))) for item in grid])
    window_starts, window_ends = window_bounds(ANALYSIS_END)
    texts = []
    present = []
    counts = []
    for start, end in zip(window_starts, window_ends):
        chosen = words[(words["start"] >= start) & (words["start"] < end)]
        counts.append(int(len(chosen)))
        if len(chosen) < MIN_WORDS:
            texts.append("")
            present.append(False)
        else:
            texts.append(" ".join(str(item).strip() for item in chosen["text"]))
            present.append(True)
    present_mask = np.asarray(present, dtype=bool)
    embeddings = np.zeros((len(texts), 384), dtype=np.float64)
    if np.any(present_mask):
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer(EMBEDDING_MODEL_ID, device="cpu")
        encoded = model.encode(
            [text for text, keep in zip(texts, present_mask) if keep],
            normalize_embeddings=True,
            batch_size=64,
            show_progress_bar=False,
        )
        embeddings[present_mask] = np.asarray(encoded, dtype=np.float64)
    semantic, reference_n, reference_span = anomaly_scores(window_starts, window_ends, embeddings, present_mask)
    defined = semantic[np.isfinite(semantic)]
    summary = {
        "experiment_spec_version": EXPERIMENT_SPEC_VERSION,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "session_id": SESSION,
        "analysis_start_seconds": ANALYSIS_START,
        "analysis_end_seconds": ANALYSIS_START + ANALYSIS_END,
        "timestamps": "seconds since analysis_start_seconds",
        "truth_ledger_read": False,
        "asr_is_closed_captions": False,
        "n_departure_cues": sum(1 for row in cues if row["kind"] == "departure"),
        "n_return_cues": sum(1 for row in cues if row["kind"] == "return"),
        "n_vocabulary_hits": len(vocabulary),
        "n_semantic_scores": int(defined.size),
        "semantic_p50": None if defined.size == 0 else float(np.median(defined)),
        "language_params": LANGUAGE_PARAMS,
        "semantic_params": SEMANTIC_PARAMS,
        "validation_note": (
            "This ESPN session is development data. These scores were computed before the commercial ledger was opened."
            if SESSION == "hush_20260914_212529"
            else "Unlabeled. The commercial ledger was not read."
        ),
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "cues.json").write_text(json.dumps(cues, indent=2) + "\n", encoding="utf-8")
    (output / "vocabulary_hits.json").write_text(json.dumps(vocabulary, indent=2) + "\n", encoding="utf-8")
    pd.DataFrame({"window_end": grid, "ad_words_per_10s": density}).to_parquet(output / "vocabulary_density.parquet", index=False)
    pd.DataFrame(
        {
            "window_start": window_starts,
            "window_end": window_ends,
            "n_words": counts,
            "semantic_distance": semantic,
            "n_reference": reference_n,
            "reference_span_s": reference_span,
        }
    ).to_parquet(output / "semantic.parquet", index=False)
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    np.save(output / "semantic_embeddings.npy", embeddings.astype(np.float32))
    semantic_on_grid = np.full(grid.shape, np.nan)
    for end, value in zip(window_ends, semantic):
        slot = int(round(end - DENSITY_S))
        if 0 <= slot < semantic_on_grid.size:
            semantic_on_grid[slot] = value
    _plot(output / "language.png", grid, density, semantic_on_grid, cues)
    print(
        f"departure={summary['n_departure_cues']} return={summary['n_return_cues']} "
        f"vocab={summary['n_vocabulary_hits']} semantic={summary['n_semantic_scores']}",
        flush=True,
    )
    return summary


def main() -> None:
    global SESSION, ANALYSIS_START, ANALYSIS_END
    parser = argparse.ArgumentParser(description="Unlabeled Exp005 language. Does not open the commercial ledger.")
    parser.add_argument("--session", default=SESSION)
    parser.add_argument("--t0", type=float, default=ANALYSIS_START)
    parser.add_argument("--t1", type=float, default=ANALYSIS_END)
    parser.add_argument("--wav", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--score-only", action="store_true")
    args = parser.parse_args()
    SESSION = args.session
    ANALYSIS_START = args.t0
    ANALYSIS_END = args.t1 - args.t0
    if ANALYSIS_END <= 0:
        raise SystemExit(f"empty span {args.t0}..{args.t1}")
    if args.wav is None and not _espn_source_locked():
        raise SystemExit("--wav is required unless this is the locked ESPN span")
    wav = args.wav if args.wav is not None else SOURCE_16K
    output = args.output if args.output is not None else REPO / "experiments" / "exp005" / SESSION
    if args.score_only:
        words = pd.read_parquet(output / "words.parquet")
    else:
        words = transcribe(wav, output)
    score(words, output)


if __name__ == "__main__":
    main()
