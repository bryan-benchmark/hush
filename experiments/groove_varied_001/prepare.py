"""Prepare three CC0 recordings for GROOVE_VARIED_001.

Full length. No trim. One shared loudness. Not installed in the gate.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy import signal

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
OUT = ROOT / "prepared"
RECEIPT = ROOT / "receipt.json"
RATE = 48000
TARGET_RMS = 0.10
PEAK_CAP = 0.90

TRACKS = (
    {
        "id": "ascend",
        "title": "Ascend",
        "filename": "1_ascend.wav",
        "stated_bpm": 130,
        "rotation": 1,
    },
    {
        "id": "starting_over",
        "title": "Starting Over",
        "filename": "2_starting_over.wav",
        "stated_bpm": 122,
        "rotation": 2,
    },
    {
        "id": "lost_utopia",
        "title": "Lost Utopia",
        "filename": "7_lost_utopia.wav",
        "stated_bpm": 127,
        "rotation": 3,
    },
)


def main() -> None:
    loaded = [_load(item) for item in TRACKS]
    target = _shared_target(loaded)
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for item, audio, info in loaded:
        scaled = audio * (target / info["rms"])
        peak = float(np.max(np.abs(scaled)))
        if peak > PEAK_CAP + 1e-6:
            raise SystemExit(f"{item['id']} peak {peak} after the shared gain")
        path = OUT / f"{item['id']}.wav"
        sf.write(str(path), scaled, RATE, subtype="PCM_16")
        rows.append(
            {
                **item,
                "source_sha256": info["sha256"],
                "source_bytes": info["bytes"],
                "source_rate": info["source_rate"],
                "source_channels": info["source_channels"],
                "source_duration_s": info["duration_s"],
                "prepared_path": str(path.relative_to(ROOT.parent.parent)),
                "prepared_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "prepared_duration_s": round(scaled.shape[0] / RATE, 3),
                "prepared_rate": RATE,
                "prepared_channels": 2,
                "rms": round(float(np.sqrt(np.mean(np.square(scaled)))), 5),
                "peak": round(peak, 4),
                "trimmed": False,
                "installed_in_gate": False,
            }
        )
        print(f"{item['id']:16} {rows[-1]['prepared_duration_s']:7.1f}s  rms={rows[-1]['rms']:.4f}  peak={rows[-1]['peak']:.3f}")
    rms_values = [row["rms"] for row in rows]
    if max(rms_values) - min(rms_values) > 0.002:
        raise SystemExit(f"loudness spread {rms_values}")
    RECEIPT.write_text(
        json.dumps(
            {
                "experiment": "GROOVE_VARIED_001",
                "source_page": "https://opengameart.org/content/free-rhythm-game-music-pack-1",
                "author": "tricksntraps",
                "license": "CC0",
                "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
                "target_rms": target,
                "peak_cap": PEAK_CAP,
                "break_order": ["B", "A", "A", "B", "A", "B", "B", "A"],
                "music_rotation": [row["id"] for row in rows],
                "tracks": rows,
            },
            indent=2,
        )
        + "\n"
    )
    print("wrote", RECEIPT)


def _load(item: dict) -> tuple[dict, np.ndarray, dict]:
    path = SRC / item["filename"]
    if not path.is_file():
        raise SystemExit(f"missing {path}")
    raw = path.read_bytes()
    if raw[:4] != b"RIFF" or raw[8:12] != b"WAVE":
        raise SystemExit(f"{path.name} is not a WAV")
    audio, rate = sf.read(str(path), dtype="float64", always_2d=True)
    channels = int(audio.shape[1])
    if channels == 1:
        audio = np.column_stack([audio[:, 0], audio[:, 0]])
    else:
        audio = audio[:, :2]
    if rate != RATE:
        audio = _resample(audio, rate, RATE)
    duration = audio.shape[0] / RATE
    rms = float(np.sqrt(np.mean(np.square(audio))))
    if rms < 1e-4:
        raise SystemExit(f"{item['id']} is silent")
    info = {
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
        "source_rate": int(rate),
        "source_channels": channels,
        "duration_s": round(duration, 3),
        "rms": rms,
    }
    return item, audio, info


def _shared_target(loaded: list[tuple[dict, np.ndarray, dict]]) -> float:
    """One RMS that every file can reach without crossing the peak cap."""
    target = TARGET_RMS
    for _, audio, info in loaded:
        peak = float(np.max(np.abs(audio)))
        allowed = PEAK_CAP * info["rms"] / peak
        target = min(target, allowed)
    return target


def _resample(audio: np.ndarray, src: int, dst: int) -> np.ndarray:
    gcd = np.gcd(src, dst)
    up = dst // gcd
    down = src // gcd
    return np.stack([signal.resample_poly(audio[:, ch], up, down) for ch in range(audio.shape[1])], axis=1)


if __name__ == "__main__":
    main()
