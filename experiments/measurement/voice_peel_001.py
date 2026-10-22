"""Peel the song off a few seconds, then ask SpeechBrain who is talking.

The clips are the sports way-back misses where someone was still talking,
and the sports ads where the announcer score already crossed 0.25. The line
stays 0.25. This does not mute anything.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy.signal import istft, resample_poly, stft

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from experiments.broadcast_intelligence.batch1 import read_span  # noqa: E402
from experiments.measurement.break_trace_001 import booth_bank  # noqa: E402
from experiments.measurement.verified_speaker_001 import load_windows  # noqa: E402
from hush.audio import RAW_SR, find_session, load_session  # noqa: E402
from hush.experiment002 import EMBEDDING_MODEL_ID, _embed_windows, _load_encoder  # noqa: E402
from hush.speaker_memory import MATCH_COSINE, SR  # noqa: E402

OUT = REPO / "docs/ohush/research/VOICE_PEEL_001"
RECEIPTS = REPO / "docs/ohush/research/START_END_001/receipts.jsonl"
DECISIONS = REPO / "docs/ohush/research/BREAK_TRACE_001/decisions.jsonl"
MODEL = REPO / "experiments/exp002/models" / EMBEDDING_MODEL_ID.split("/")[-1]
SPORTS = {"NBC", "ESPN", "Prime", "Prime Video"}


def decisions_by_session() -> dict[str, list[dict]]:
    grouped = defaultdict(list)
    for line in DECISIONS.read_text().splitlines():
        if line.strip():
            row = json.loads(line)
            grouped[row["session"]].append(row)
    for rows in grouped.values():
        rows.sort(key=lambda row: row["t"])
    return grouped


def targets(banks: dict) -> list[dict]:
    rows = decisions_by_session()
    windows = {}
    found = []
    receipts = [json.loads(line) for line in RECEIPTS.read_text().splitlines() if line.strip()]
    for pod in receipts:
        if pod["network"] not in SPORTS:
            continue
        session = pod["session"]
        show = rows[session][0].get("show") if rows.get(session) else None
        bank = banks.get(show) or {}
        if not bank:
            continue
        if session not in windows:
            windows[session] = load_windows(session)
        names = list(bank)
        matrix = np.vstack([bank[name] for name in names])
        grid = windows[session]
        mids = (grid["start"] + grid["end"]) / 2
        scores = grid["vector"] @ matrix.T
        back = [row for row in rows[session] if pod["end"] < row["t"] <= pod["end"] + 12 and row["booth_over_line"]]
        if not back:
            span = (mids > pod["end"]) & (mids <= pod["end"] + 12)
            speech = [row["speech"] for row in rows[session] if pod["end"] < row["t"] <= pod["end"] + 12]
            if span.any() and speech and max(speech) >= 0.5:
                slot = int(np.flatnonzero(span)[int(np.argmax(scores[span].max(axis=1)))])
                found.append(clip(pod, "miss", grid, scores, names, slot))
        early = [row for row in rows[session] if pod["start"] + 30 <= row["t"] <= pod["end"] - 8 and row["booth_over_line"]]
        if early:
            t = early[0]["t"]
            span = (mids > t - 4) & (mids <= t)
            if span.any():
                slot = int(np.flatnonzero(span)[int(np.argmax(scores[span].max(axis=1)))])
                found.append(clip(pod, "ad", grid, scores, names, slot))
    return found


def clip(pod, kind, grid, scores, names, slot) -> dict:
    best = int(np.argmax(scores[slot]))
    return {
        "kind": kind,
        "session": pod["session"],
        "network": pod["network"],
        "boundary": round(float(pod["end"] if kind == "miss" else pod["start"]), 3),
        "start": float(grid["start"][slot]),
        "end": float(grid["end"][slot]),
        "stored": round(float(scores[slot, best]), 3),
        "stored_name": names[best],
    }


def to_16k(stereo: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
    left = stereo[:, 0].astype(np.float32)
    right = stereo[:, 1].astype(np.float32)
    mid = ((left + right) * 0.5).astype(np.float32)
    side = ((left - right) * 0.5).astype(np.float32)
    balance = float(np.sqrt(np.mean(side**2)) / (np.sqrt(np.mean(mid**2)) + 1e-8))
    return resample_poly(mid, 1, 3).astype(np.float32), resample_poly(left, 1, 3).astype(np.float32), balance


def harmonic_peel(audio: np.ndarray) -> np.ndarray:
    """Keep the steady speaking pitch and turn the rest down."""
    freqs, _times, spec = stft(audio, fs=SR, nperseg=512, noverlap=384, boundary=None, padded=False)
    mag = np.abs(spec)
    bed = np.median(mag, axis=1, keepdims=True)
    cleaned = spec * np.clip(1.0 - (0.9 * bed) / (mag + 1e-8), 0.05, 1.0)
    bins = np.arange(mag.shape[0])
    for index in range(mag.shape[1]):
        frame = mag[:, index]
        lo = max(2, int(80 * 512 / SR))
        hi = min(len(frame) - 2, int(280 * 512 / SR))
        peak = lo + int(np.argmax(frame[lo:hi]))
        if frame[peak] < 2.5 * (np.median(frame) + 1e-8):
            cleaned[:, index] *= 0.25
            continue
        mask = np.zeros(len(frame), dtype=np.float32)
        harmonic = peak
        while harmonic < len(frame) - 2:
            mask[max(0, harmonic - 1) : harmonic + 2] = 1.0
            harmonic += peak
        cleaned[:, index] *= 0.15 + 0.85 * mask
        _ = bins
    _unused, wave = istft(cleaned, fs=SR, nperseg=512, noverlap=384, input_onesided=True, boundary=False)
    if len(wave) < len(audio):
        wave = np.pad(wave, (0, len(audio) - len(wave)))
    return wave[: len(audio)].astype(np.float32)


def embed(encoder, audio: np.ndarray) -> np.ndarray:
    if len(audio) < int(0.5 * SR):
        audio = np.pad(audio, (0, int(0.5 * SR) - len(audio)))
    return _embed_windows(audio, [(0.0, len(audio) / SR)], encoder, "cpu", 1)[0]


def main() -> None:
    banks = booth_bank()
    chosen = targets(banks)
    encoder = _load_encoder(MODEL, "cpu")
    sessions = {}
    scored = []
    for row in chosen:
        if row["session"] not in sessions:
            folder = find_session(REPO / "recordings", row["session"])
            sessions[row["session"]] = (folder, load_session(folder))
        folder, meta = sessions[row["session"]]
        stereo = read_span(folder, meta, row["start"], row["end"])
        mid, left, balance = to_16k(stereo)
        peeled = harmonic_peel(mid)
        show = decisions_by_session()[row["session"]][0]["show"]
        bank = banks[show]
        names = list(bank)
        matrix = np.vstack([bank[name] for name in names])

        def best(vector: np.ndarray) -> tuple[str, float]:
            scores = vector @ matrix.T
            slot = int(np.argmax(scores))
            return names[slot], round(float(scores[slot]), 3)

        raw_name, raw_score = best(embed(encoder, mid))
        left_name, left_score = best(embed(encoder, left))
        peel_name, peel_score = best(embed(encoder, peeled))
        scored.append({
            **row,
            "side_vs_center": round(balance, 3),
            "again": raw_score,
            "again_name": raw_name,
            "left_only": left_score,
            "left_name": left_name,
            "peeled": peel_score,
            "peeled_name": peel_name,
            "stored_over": row["stored"] >= MATCH_COSINE,
            "again_over": raw_score >= MATCH_COSINE,
            "peeled_over": peel_score >= MATCH_COSINE,
        })
        print(row["kind"], row["network"], row["stored"], "->", peel_score, peel_name, flush=True)
    summary = {}
    for kind in ("miss", "ad"):
        group = [row for row in scored if row["kind"] == kind]
        summary[kind] = {
            "clips": len(group),
            "stored_at_or_over_0.25": sum(1 for row in group if row["stored_over"]),
            "same_mix_again_at_or_over_0.25": sum(1 for row in group if row["again_over"]),
            "peeled_at_or_over_0.25": sum(1 for row in group if row["peeled_over"]),
        }
    OUT.mkdir(parents=True, exist_ok=True)
    payload = {"line": MATCH_COSINE, "summary": summary, "clips": scored}
    (OUT / "results.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
