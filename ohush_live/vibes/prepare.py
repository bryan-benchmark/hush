"""Decode, normalize, QC, and write processed vibe WAVs + manifest.

Does not touch the commercial detector.
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import soundfile as sf

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from ohush_live.vibes.catalog import TRACKS  # noqa: E402

RATE = 48000
TARGET_RMS = 0.10
PEAK_CAP = 0.90
VIBE_DIR = Path(__file__).resolve().parent
SRC = VIBE_DIR / "src"
OUT = VIBE_DIR / "processed"
RECEIPTS = VIBE_DIR / "receipts"

# source_id → filename in src/
SOURCE_FILES = {
    "wednesday_chill_lofi": "wednesday_chill_lofi.ogg",
    "wednesday_lofi_again": "wednesday_lofi_again.ogg",
    "wednesday_cup_of_tea": "wednesday_cup_of_tea.mp3",
    "friends_funked_up": "friends_funked_up.mp3",
    "friends_funky_disco": "friends_funky_disco.ogg",
    "friends_empty_stretch": "friends_empty_stretch.wav",
    "cocktail_coffee_house": "cocktail_coffee_house.mp3",
    "cocktail_bossa_nova": "cocktail_bossa_nova.mp3",
    "rain_soft_loop": "rain_soft_loop_preview_hq.mp3",
    "stadium_crowd": "stadium_crowd_preview_hq.mp3",
}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    RECEIPTS.mkdir(parents=True, exist_ok=True)
    download = {}
    dl_path = RECEIPTS / "download_receipt.json"
    if dl_path.is_file():
        download = {t["id"]: t for t in json.loads(dl_path.read_text())["tracks"]}

    manifest_tracks = []
    qc_rows = []
    for bed_name, meta in TRACKS.items():
        source_id = meta["source_id"]
        src_name = SOURCE_FILES[source_id]
        src_path = SRC / src_name
        if not src_path.is_file():
            raise FileNotFoundError(src_path)
        audio, rate = sf.read(str(src_path), dtype="float64", always_2d=True)
        audio = _to_stereo(audio)
        if rate != RATE:
            audio = _resample_linear(audio, rate, RATE)
        audio = _trim_edges(audio)
        if bed_name == "stadium_vibe":
            audio, stadium_note = _stadium_calm_segment(audio)
        else:
            stadium_note = None
        # Cap very long beds so gate memory stays reasonable (~90s).
        max_frames = int(90 * RATE)
        if audio.shape[0] > max_frames:
            audio = audio[:max_frames]
        audio = _normalize_rms(audio)
        qc = _qc(audio, bed_name)
        if stadium_note:
            qc["notes"] = stadium_note
        out_path = OUT / f"{bed_name}.wav"
        sf.write(str(out_path), audio, RATE, subtype="PCM_16")
        digest = hashlib.sha256(out_path.read_bytes()).hexdigest()
        dl = download.get(source_id) or {}
        manifest_tracks.append(
            {
                "bed": bed_name,
                "vibe": meta["vibe"],
                "title": meta["title"],
                "creator": meta["creator"],
                "source_id": source_id,
                "source_page": dl.get("source_page"),
                "license": dl.get("license", "CC0"),
                "download_tier": dl.get("download_tier", "original"),
                "source_sha256": dl.get("sha256"),
                "processed_path": str(out_path.relative_to(REPO)),
                "processed_sha256": digest,
                "duration_s": round(audio.shape[0] / RATE, 3),
                "sample_rate": RATE,
                "qc": qc,
            }
        )
        qc_rows.append({"bed": bed_name, **qc})
        print(f"OK {bed_name:32s} {audio.shape[0]/RATE:6.1f}s  peak={qc['peak']:.3f}  speechish={qc['speechish_ratio']:.3f}")

    manifest = {
        "experiment": "VIBE_STARTER_001",
        "scientific_authority": False,
        "dataset_role": "live_dev",
        "default_vibe": "wednesday_night",
        "prepared_at": datetime.now(timezone.utc).isoformat(),
        "target_rms": TARGET_RMS,
        "peak_cap": PEAK_CAP,
        "tracks": manifest_tracks,
    }
    (VIBE_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (RECEIPTS / "qc.json").write_text(json.dumps(qc_rows, indent=2) + "\n")
    print("wrote", VIBE_DIR / "manifest.json")
    return 0


def _to_stereo(audio: np.ndarray) -> np.ndarray:
    if audio.shape[1] == 1:
        return np.concatenate([audio, audio], axis=1)
    return audio[:, :2]


def _resample_linear(audio: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    if src_rate == dst_rate:
        return audio
    n = audio.shape[0]
    new_n = int(round(n * dst_rate / src_rate))
    x = np.linspace(0.0, 1.0, n, endpoint=False)
    xi = np.linspace(0.0, 1.0, new_n, endpoint=False)
    out = np.stack([np.interp(xi, x, audio[:, ch]) for ch in range(audio.shape[1])], axis=1)
    return out.astype(np.float64)


def _trim_edges(audio: np.ndarray, floor: float = 0.002) -> np.ndarray:
    level = np.mean(np.abs(audio), axis=1)
    live = np.flatnonzero(level >= floor)
    if live.size == 0:
        return audio
    pad = int(0.02 * RATE)
    start = max(0, int(live[0]) - pad)
    end = min(audio.shape[0], int(live[-1]) + pad)
    if end - start < RATE:
        return audio
    return audio[start:end]


def _normalize_rms(audio: np.ndarray) -> np.ndarray:
    rms = float(np.sqrt(np.mean(np.square(audio)))) or 1e-6
    scaled = audio * (TARGET_RMS / rms)
    peak = float(np.max(np.abs(scaled))) or 1e-6
    if peak > PEAK_CAP:
        scaled *= PEAK_CAP / peak
    return scaled


def _stadium_calm_segment(audio: np.ndarray) -> tuple[np.ndarray, str]:
    """Prefer a steadier 45s window; flag if still bursty."""
    win = int(45 * RATE)
    if audio.shape[0] <= win:
        return audio, "full file shorter than 45s; no calm crop applied"
    hop = int(1.0 * RATE)
    best_i = 0
    best_score = None
    for i in range(0, audio.shape[0] - win, hop):
        chunk = audio[i : i + win]
        # Prefer moderate RMS with low crest factor (less sudden cheers).
        rms = float(np.sqrt(np.mean(np.square(chunk)))) or 1e-6
        peak = float(np.max(np.abs(chunk))) or 1e-6
        crest = peak / rms
        score = crest + abs(np.log(rms / TARGET_RMS))
        if best_score is None or score < best_score:
            best_score = score
            best_i = i
    return audio[best_i : best_i + win], f"calm_crop_start_s={best_i / RATE:.1f} crest_score={best_score:.3f}"


def _qc(audio: np.ndarray, bed_name: str) -> dict:
    mono = np.mean(audio, axis=1)
    peak = float(np.max(np.abs(mono)))
    rms = float(np.sqrt(np.mean(np.square(mono)))) or 1e-6
    # Crude "speechish": high crest + midband energy bursts.
    frame = int(0.05 * RATE)
    energies = []
    for i in range(0, len(mono) - frame, frame):
        energies.append(float(np.sqrt(np.mean(np.square(mono[i : i + frame])))) )
    energies_a = np.asarray(energies) if energies else np.zeros(1)
    med = float(np.median(energies_a)) or 1e-6
    burst = float(np.mean(energies_a > 3.0 * med))
    # Loop edge click proxy: discontinuity between end and start.
    edge = float(np.mean(np.abs(mono[0] - mono[-1])))
    return {
        "peak": round(peak, 4),
        "rms": round(rms, 4),
        "crest": round(peak / rms, 3),
        "speechish_ratio": round(burst, 4),
        "loop_edge_delta": round(edge, 4),
        "clipped": bool(peak >= PEAK_CAP - 1e-6),
        "suitable_for_default": bed_name.startswith("wednesday_night") and burst < 0.15 and peak < 0.95,
    }


if __name__ == "__main__":
    raise SystemExit(main())
