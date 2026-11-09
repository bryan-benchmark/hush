"""Blind transfer of the KEEP research stack onto hush_20261015_210805.

Prime TNF Broncos–Seahawks. Not in train/eval/holdouts. No gold product cells —
cooldown has no accepted non_broadcast ends; voice latch still applies.
Does not retune thresholds. Does not touch ohush_live. Holdouts stay sealed.

Phases: extract → predict → ecapa → side (Palmer/Fitz) → score.
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

CACHE_HF = REPO / "ohush_live" / "cache"
os.environ.setdefault("HF_HOME", str(CACHE_HF / "hf"))
os.environ.setdefault("HUGGINGFACE_HUB_CACHE", str(CACHE_HF / "hf" / "hub"))
os.environ.setdefault("TORCH_HOME", str(CACHE_HF / "torch"))

from experiments.audio_learn.controller import decisions
from experiments.audio_learn.encoder import DATA_ROOT, checkpoint_sha, embed_numpy, load_encoder
from experiments.audio_learn.extract import cache_path, load_cache, stamp_for
from experiments.audio_learn.head import load_head, probabilities
from experiments.audio_learn.research_latch import (
    FITZ_CACHE,
    FITZ_MARGIN,
    PALMER_CACHE,
    PALMER_MARGIN,
    STATUS,
    VOICE_PANELS,
    apply_research_latch,
)
from experiments.audio_learn.splits import CONTEXT_S, HOP_S, SR, WINDOW_S, assert_split
from experiments.audio_learn.studio_fit import CONTROLLER
from experiments.audio_learn.windows import pack_past_batch
from experiments.ledger import RECORDINGS, sha256_file
from experiments.nfl75.protect_embed import (
    MODEL,
    OUT as ECAPA_OUT,
    _clip,
    _eligible,
    _embed_windows,
    _latest_labels,
    _load_encoder,
    _match,
    _speech_regions,
)
from hush.audio import RAW_SR, analysis_pieces, find_session, load_session, read_stereo, resample_concat
from hush.speaker_memory import EMBEDDING_MODEL_ID, embedding_windows
from hush.speaker_memory import SR as ECAPA_SR
from tools.gpu_lab.audio_load import load_coverage
from tools.gpu_lab.decisions import decision_times
from tools.gpu_lab.splits import HOLDOUTS

SESSION = "hush_20261015_210805"
OUT = DATA_ROOT / "blind_prime_1015"
HEAD = DATA_ROOT / "checkpoints" / "frozen_head.pt"
BATCH = 16
# Same five columns as EVAL ECAPA caches (Fitz is side-cache only).
PEOPLE5 = [
    "Al Michaels",
    "Kirk Herbstreit",
    "Clarissa Thompson",
    "Andrew Whitworth",
    "Tony Gonzalez",
]


def _guard() -> None:
    assert_split()
    if SESSION in HOLDOUTS:
        raise RuntimeError(f"refusing sealed holdout {SESSION}")


def _coverage() -> tuple[float, float]:
    folder = find_session(RECORDINGS, SESSION)
    meta = load_session(folder)
    chunks = meta.get("chunks") or []
    if not chunks:
        raise RuntimeError(f"{SESSION} has no audio chunks")
    return float(chunks[0]["start_elapsed_seconds"]), float(chunks[-1]["end_elapsed_seconds"])


def phase_extract() -> Path:
    _guard()
    stamp = stamp_for(None, checkpoint_sha())
    path = cache_path("frozen", SESSION)
    meta = path.with_suffix(".json")
    if path.is_file() and meta.is_file():
        existing = json.loads(meta.read_text(encoding="utf-8"))
        if existing.get("encoder_stamp") == stamp and existing.get("hop_s") == HOP_S:
            print(f"cached emb {path}", flush=True)
            return path
    import torch

    if not torch.cuda.is_available():
        raise RuntimeError("frame_mn10 extraction needs CUDA")
    start, end = _coverage()
    times = decision_times(start, end, WINDOW_S, HOP_S)
    labels = np.full(len(times), -1, dtype=np.int8)
    print(f"extract {SESSION} {end - start:.0f}s -> {len(times)} decisions", flush=True)
    device = torch.device("cuda")
    torch.backends.cudnn.benchmark = True
    model = load_encoder(device, None)
    try:
        audio = load_coverage(SESSION, start, end)
        parts = []
        for i in range(0, len(times), BATCH):
            chunk = times[i : i + BATCH]
            waves = pack_past_batch(audio, start, chunk, WINDOW_S, CONTEXT_S, SR)
            parts.append(embed_numpy(model, device, waves))
            if i % (BATCH * 50) == 0:
                print(f"  {i}/{len(times)}", flush=True)
        emb = np.concatenate(parts, axis=0).astype(np.float16)
    finally:
        del model
        torch.cuda.empty_cache()
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(path, t=np.asarray(times, dtype=np.float64), emb=emb, label=labels)
    meta.write_text(
        json.dumps(
            {
                "session": SESSION,
                "kind": "frozen",
                "encoder_stamp": stamp,
                "window_s": WINDOW_S,
                "context_s": CONTEXT_S,
                "hop_s": HOP_S,
                "sr": SR,
                "n": len(times),
                "causal": "audio [t-window, t) right-aligned in a 10s buffer; front pad is silence",
                "commercial_rows": 0,
                "program_rows": 0,
                "excluded_rows": int(len(times)),
                "blind": True,
                "note": "no gold labels; label column is -1",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"wrote {path}", flush=True)
    return path


def phase_predict() -> Path:
    _guard()
    out = DATA_ROOT / "predictions" / "frozen" / f"{SESSION}.npz"
    if out.is_file():
        print(f"cached pred {out}", flush=True)
        return out
    import torch

    cache = load_cache(cache_path("frozen", SESSION))
    device = torch.device("cuda")
    head = load_head(HEAD, device)
    scores = probabilities(head, cache["emb"], cache["t"], device)
    out.parent.mkdir(parents=True, exist_ok=True)
    np.savez(out, t=cache["t"], p=scores, label=cache["label"])
    print(f"wrote {out} n={len(scores)}", flush=True)
    return out


def _session_audio() -> tuple[np.ndarray, float, float]:
    folder = find_session(RECORDINGS, SESSION)
    meta = load_session(folder)
    chunks = meta["chunks"]
    start = float(chunks[0]["start_elapsed_seconds"])
    end = float(chunks[-1]["end_elapsed_seconds"])
    pieces = analysis_pieces(folder, meta, start, end)
    print(f"load {SESSION} {end - start:.0f}s", flush=True)
    mono = [read_stereo(piece).mean(axis=1) for piece in pieces]
    audio = np.asarray(resample_concat(mono, up=1, down=RAW_SR // ECAPA_SR), dtype=np.float32)
    return audio, start, end


def _enroll_people5(encoder) -> tuple[dict[str, list[np.ndarray]], dict[str, list[float]], list[dict]]:
    vectors: dict[str, list[np.ndarray]] = defaultdict(list)
    ready: dict[str, list[float]] = defaultdict(list)
    used = []
    allow = set(PEOPLE5)
    for row in _latest_labels():
        if row.get("who") not in allow:
            continue
        if not _eligible(row, SESSION):
            continue
        audio = _clip(row["session"], float(row["play_start"]), float(row["duration"]))
        vector = _embed_windows(audio, [(0.0, len(audio) / ECAPA_SR)], encoder, 1)[0]
        end = 0.0 if row["session"] != SESSION else float(row["play_start"]) + float(row["duration"])
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
    missing = [n for n in PEOPLE5 if n not in vectors]
    if missing:
        raise RuntimeError(f"no causal enroll for {missing} on {SESSION}")
    return vectors, ready, used


def phase_ecapa() -> Path:
    _guard()
    dest = ECAPA_OUT / f"{SESSION}.npz"
    receipt = ECAPA_OUT / f"{SESSION}.json"
    if dest.is_file() and receipt.is_file():
        print(f"cached ecapa {dest}", flush=True)
        return dest
    encoder = _load_encoder(MODEL)
    vectors, ready, used = _enroll_people5(encoder)
    audio, start, end = _session_audio()
    regions, vad = _speech_regions(audio)
    windows = embedding_windows(regions)
    print(f"{SESSION} ecapa windows {len(windows)}", flush=True)
    embedded = _embed_windows(audio, windows, encoder, 16)
    units = embedded / np.maximum(np.linalg.norm(embedded, axis=1, keepdims=True), 1e-12)
    window_ends = np.asarray([item[1] + start for item in windows], dtype=np.float64)
    cosine, people = _match(units, window_ends, vectors, ready, PEOPLE5)
    ECAPA_OUT.mkdir(parents=True, exist_ok=True)
    np.savez(
        dest,
        start=np.asarray([item[0] + start for item in windows], dtype=np.float64),
        end=window_ends,
        cosine=cosine.astype(np.float64),
        people=people.astype(np.float32),
    )
    receipt.write_text(
        json.dumps(
            {
                "session": SESSION,
                "model": EMBEDDING_MODEL_ID,
                "coverage": [start, end],
                "vad": vad,
                "windows": len(windows),
                "names": PEOPLE5,
                "enrollment_clips": used,
                "enrollment": "prior games available at kickoff; same-tape clips at their own end",
                "blind": True,
                "sealed_holdouts_read": False,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"wrote {dest} max cosine {float(np.nanmax(cosine)):.3f}", flush=True)
    return dest


def _side_cache(name: str, key: str, enroll: tuple[dict, ...], out_dir: Path) -> Path:
    dest = out_dir / f"{SESSION}_{key}.npz"
    if dest.is_file():
        print(f"cached {dest.name}", flush=True)
        return dest
    encoder = _load_encoder(MODEL)
    vectors = []
    ready = []
    for row in enroll:
        if row["session"] == SESSION:
            audio = _clip(row["session"], float(row["play_start"]), float(row["duration"]))
            vec = _embed_windows(audio, [(0.0, len(audio) / ECAPA_SR)], encoder, 1)[0]
            vectors.append(vec)
            ready.append(float(row["available_at"]))
        elif row["session"] < SESSION:
            audio = _clip(row["session"], float(row["play_start"]), float(row["duration"]))
            vec = _embed_windows(audio, [(0.0, len(audio) / ECAPA_SR)], encoder, 1)[0]
            vectors.append(vec)
            ready.append(0.0)
    base = np.load(ECAPA_OUT / f"{SESSION}.npz")
    ends = np.asarray(base["end"], dtype=np.float64)
    starts = np.asarray(base["start"], dtype=np.float64)
    people5 = np.asarray(base["people"], dtype=np.float64)
    if not vectors:
        out_dir.mkdir(parents=True, exist_ok=True)
        np.savez(
            dest,
            start=starts,
            end=ends,
            **{key: np.full(len(ends), np.nan, dtype=np.float32)},
            people5=people5.astype(np.float32),
            enroll=[],
        )
        print(f"{SESSION}: no {name} enroll vectors", flush=True)
        return dest
    audio, audio_start, _ = _session_audio()
    windows = [(float(s - audio_start), float(e - audio_start)) for s, e in zip(starts, ends)]
    print(f"{SESSION} embed {len(windows)} windows for {name}", flush=True)
    embedded = _embed_windows(audio, windows, encoder, 16)
    units = embedded / np.maximum(np.linalg.norm(embedded, axis=1, keepdims=True), 1e-12)
    scores = np.full(len(ends), np.nan, dtype=np.float64)
    order = np.argsort(ends)
    running = np.zeros(units.shape[1], dtype=np.float64)
    cursor = 0
    ready_arr = np.asarray(ready, dtype=np.float64)
    vec_stack = np.stack(vectors)
    rank = np.argsort(ready_arr)
    ready_arr = ready_arr[rank]
    vec_stack = vec_stack[rank]
    for index in order:
        moment = float(ends[index])
        while cursor < len(ready_arr) and ready_arr[cursor] <= moment + 1e-9:
            running += vec_stack[cursor]
            cursor += 1
        if cursor == 0:
            continue
        proto = running / max(np.linalg.norm(running), 1e-12)
        scores[index] = float(units[index] @ proto)
    out_dir.mkdir(parents=True, exist_ok=True)
    np.savez(
        dest,
        start=starts,
        end=ends,
        **{key: scores.astype(np.float32)},
        people5=people5.astype(np.float32),
        enroll=list(enroll),
    )
    finite = np.isfinite(scores)
    print(
        f"  {key} ge_0.25={int(np.sum(scores[finite] >= 0.25))} / {int(finite.sum())} "
        f"max={float(np.nanmax(scores)):.3f}",
        flush=True,
    )
    return dest


def phase_side() -> dict[str, str]:
    from experiments.audio_learn.fitz_cover_latch import ENROLL as FITZ_ENROLL
    from experiments.audio_learn.palmer_cover_latch import ENROLL as PALMER_ENROLL

    palmer = _side_cache("Palmer", "palmer", PALMER_ENROLL, PALMER_CACHE)
    fitz = _side_cache("Fitz", "fitz", FITZ_ENROLL, FITZ_CACHE)
    return {"palmer": str(palmer), "fitz": str(fitz)}


def _episodes(times: np.ndarray, probs: np.ndarray, coverage: tuple[float, float]) -> list[dict]:
    from experiments.nfl75.score import playback_from_decisions

    rows = decisions(times.tolist(), probs.tolist(), **CONTROLLER)
    spans = playback_from_decisions(coverage, rows)
    # playback_from_decisions emits one piece per decision edge; merge abutting covers.
    merged: list[list[float]] = []
    for span in spans:
        if span.state != "covered":
            continue
        if merged and abs(span.start - merged[-1][1]) <= 1e-6:
            merged[-1][1] = float(span.end)
        else:
            merged.append([float(span.start), float(span.end)])
    out = [
        {"start_s": a, "end_s": b, "length_s": round(b - a, 3)}
        for a, b in merged
        if b > a
    ]
    out.sort(key=lambda r: -r["length_s"])
    return out


def _summary(name: str, times: np.ndarray, probs: np.ndarray, coverage: tuple[float, float]) -> dict:
    eps = _episodes(times, probs, coverage)
    cover_s = round(sum(e["length_s"] for e in eps), 2)
    return {
        "name": name,
        "cover_s": cover_s,
        "cover_share": round(cover_s / (coverage[1] - coverage[0]), 4),
        "episodes": len(eps),
        "longest_s": eps[0]["length_s"] if eps else 0.0,
        "top10": eps[:10],
    }


def phase_score() -> dict:
    _guard()
    OUT.mkdir(parents=True, exist_ok=True)
    pred = np.load(DATA_ROOT / "predictions" / "frozen" / f"{SESSION}.npz")
    times = pred["t"].astype(np.float64)
    frozen_p = pred["p"].astype(np.float64)
    cool_p = apply_research_latch(SESSION, times, frozen_p, with_voice=False)
    stack_p = apply_research_latch(SESSION, times, frozen_p, with_voice=True)
    coverage = _coverage()
    cool = _summary("cooldown_8s_only", times, cool_p, coverage)
    stack = _summary("research_stack", times, stack_p, coverage)
    # seconds voice clears while cool still covers
    cleared = []
    cool_rows = decisions(times.tolist(), cool_p.tolist(), **CONTROLLER)
    stack_rows = decisions(times.tolist(), stack_p.tolist(), **CONTROLLER)
    assert len(cool_rows) == len(stack_rows)
    hop = float(HOP_S)
    cleared_s = 0.0
    for c, s in zip(cool_rows, stack_rows):
        if c["action"] == "cover" and s["action"] != "cover":
            cleared_s += hop
    # largest cool covers that stack shortens
    for ep in cool["top10"]:
        a, b = ep["start_s"], ep["end_s"]
        cool_mute = 0.0
        stack_mute = 0.0
        for c, s, t in zip(cool_rows, stack_rows, times):
            if t < a or t >= b:
                continue
            if c["action"] == "cover":
                cool_mute += hop
            if s["action"] == "cover":
                stack_mute += hop
        if cool_mute - stack_mute > 0.5:
            cleared.append(
                {
                    "start_s": a,
                    "end_s": b,
                    "cool_muted_s": round(cool_mute, 2),
                    "stack_muted_s": round(stack_mute, 2),
                    "freed_s": round(cool_mute - stack_mute, 2),
                }
            )
    delta = {
        "cover_s_delta": round(stack["cover_s"] - cool["cover_s"], 2),
        "episodes_delta": stack["episodes"] - cool["episodes"],
        "longest_delta": round(stack["longest_s"] - cool["longest_s"], 2),
        "voice_cleared_s": round(cleared_s, 2),
    }
    summary = {
        "session": SESSION,
        "show": "TNF Broncos and Seahawks",
        "service": "Prime Video",
        "status": STATUS,
        "blind": True,
        "gold_product_cells": False,
        "cooldown_note": (
            "no accepted non_broadcast ends on this tape; cooldown_8s is a no-op; "
            "cool ≈ frozen controller; stack = cool + Clarissa∪Whit∪Palmer∪Fitz"
        ),
        "panels": [{"name": n, "margin": m} for n, m in VOICE_PANELS]
        + [
            {"name": "James Palmer", "margin": PALMER_MARGIN},
            {"name": "Ryan Fitzpatrick", "margin": FITZ_MARGIN},
        ],
        "coverage": list(coverage),
        "controller": CONTROLLER,
        "thresholds_retuned": False,
        "ohush_live_touched": False,
        "holdouts_opened": False,
        "cooldown_8s_only": cool,
        "research_stack": stack,
        "delta": delta,
        "voice_freed_top": cleared[:10],
        "frozen_head_sha256": sha256_file(HEAD),
        "pred_sha256": sha256_file(DATA_ROOT / "predictions" / "frozen" / f"{SESSION}.npz"),
        "ecapa_sha256": sha256_file(ECAPA_OUT / f"{SESSION}.npz"),
    }
    (OUT / "SUMMARY.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    lines = [
        f"# Blind research stack — {SESSION}",
        "",
        "Prime TNF Broncos–Seahawks. No gold product cells. No threshold retune. Not live.",
        "",
        f"- coverage window {coverage[0]:.0f}–{coverage[1]:.0f}s",
        f"- cool cover_s **{cool['cover_s']}** (episodes {cool['episodes']}, longest {cool['longest_s']})",
        f"- stack cover_s **{stack['cover_s']}** (episodes {stack['episodes']}, longest {stack['longest_s']})",
        f"- delta cover_s {delta['cover_s_delta']}, voice_cleared_s {delta['voice_cleared_s']}",
        f"- cooldown: {summary['cooldown_note']}",
        "",
        "## Top cool covers (listen)",
    ]
    for i, ep in enumerate(cool["top10"], 1):
        lines.append(f"{i}. {ep['start_s']:.1f}–{ep['end_s']:.1f} ({ep['length_s']}s)")
    if cleared:
        lines += ["", "## Cool covers shortened by voice"]
        for row in cleared[:10]:
            lines.append(
                f"- {row['start_s']:.1f}–{row['end_s']:.1f}: cool {row['cool_muted_s']} → "
                f"stack {row['stack_muted_s']} (freed {row['freed_s']})"
            )
    (OUT / "BLIND.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"delta": delta, "cool_cover_s": cool["cover_s"], "stack_cover_s": stack["cover_s"]}, indent=2), flush=True)
    return summary


def main(argv: list[str] | None = None) -> None:
    argv = argv if argv is not None else sys.argv[1:]
    phases = argv or ["extract", "predict", "ecapa", "side", "score"]
    dispatch = {
        "extract": phase_extract,
        "predict": phase_predict,
        "ecapa": phase_ecapa,
        "side": phase_side,
        "score": phase_score,
    }
    for name in phases:
        if name not in dispatch:
            raise SystemExit(f"unknown phase {name}; want {list(dispatch)}")
        print(f"== phase {name} ==", flush=True)
        dispatch[name]()


if __name__ == "__main__":
    main()
