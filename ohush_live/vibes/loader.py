"""Load processed vibe WAVs into ListenerGate bed dicts."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import soundfile as sf

from ohush_live.vibes.catalog import DEFAULT_VIBE, TRACKS, resolve_vibe_track, vibe_bed_names

VIBE_DIR = Path(__file__).resolve().parent
PROCESSED = VIBE_DIR / "processed"
MANIFEST = VIBE_DIR / "manifest.json"
RATE = 48000


def load_vibe_beds(*, require_all: bool = False) -> dict[str, np.ndarray]:
    """Return int16 stereo beds for silence + available vibe tracks."""
    beds: dict[str, np.ndarray] = {
        "silence": np.zeros((int(2.0 * RATE), 2), dtype=np.int16),
    }
    missing = []
    for name in TRACKS:
        path = PROCESSED / f"{name}.wav"
        if not path.is_file():
            missing.append(name)
            continue
        audio, rate = sf.read(str(path), dtype="int16", always_2d=True)
        if rate != RATE:
            raise RuntimeError(f"{path} must be {RATE} Hz (got {rate})")
        beds[name] = np.ascontiguousarray(audio[:, :2])
    if require_all and missing:
        raise FileNotFoundError(f"missing processed vibes: {missing}; run python -m ohush_live.vibes.prepare")
    return beds


def available_replacements() -> list[str]:
    names = ["silence"]
    for name in vibe_bed_names():
        if name == "silence":
            continue
        if (PROCESSED / f"{name}.wav").is_file():
            names.append(name)
    return names


def default_replacement() -> str:
    return resolve_vibe_track(DEFAULT_VIBE)


def manifest() -> dict:
    if not MANIFEST.is_file():
        return {}
    return json.loads(MANIFEST.read_text(encoding="utf-8"))
