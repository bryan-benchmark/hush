"""Quiet replacement beds for a family listen.

Pink, brown, and silence are generated. Stadium, rain, and fireplace prefer
local Mixkit recordings in ohush_live/beds when those files are present.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf

RATE = 48000
LOOP_S = 12.0
BED_PEAK = 0.05
BED_DIR = Path(__file__).resolve().parent / "beds"


def make_beds(rate: int = RATE, use_recordings: bool = True) -> dict[str, np.ndarray]:
    frames = int(LOOP_S * rate)
    beds = {
        "silence": np.zeros((frames, 2), dtype=np.int16),
        "stadium": _stereo(_stadium(frames, rate), rate, BED_PEAK),
        "rain": _stereo(_rain(frames, rate), rate, BED_PEAK * 0.85),
        "fireplace": _stereo(_fireplace(frames, rate), rate, BED_PEAK),
        "pink": _stereo(_colored(np.random.default_rng(11), frames, 1.0), rate, BED_PEAK * 0.7),
        "brown": _stereo(_colored(np.random.default_rng(13), frames, 2.0), rate, BED_PEAK * 0.8),
    }
    if use_recordings:
        for name in ("stadium", "rain", "fireplace"):
            loaded = _read_recording(name)
            if loaded is not None:
                beds[name] = loaded
    return beds


def _read_recording(name: str) -> np.ndarray | None:
    path = BED_DIR / f"{name}.wav"
    if not path.is_file():
        return None
    audio, rate = sf.read(path, dtype="int16", always_2d=True)
    if rate != RATE or audio.shape[1] != 2:
        raise RuntimeError(f"{path.name} must be {RATE} Hz stereo")
    return np.ascontiguousarray(audio)


def make_earcon(rate: int = RATE) -> np.ndarray:
    tone = np.concatenate([_tone(880, 0.12, rate), _tone(660, 0.16, rate)])
    stereo = np.column_stack([tone, tone])
    return _scale(stereo, 0.08)


def _stadium(frames: int, rate: int) -> np.ndarray:
    rng = np.random.default_rng(20261008)
    low = _leaky(rng, frames, 0.985)
    air = _leaky(rng, frames, 0.92)
    wobble = 0.85 + 0.15 * np.sin(2 * np.pi * np.arange(frames) / (rate * 7.0))
    return (0.82 * low + 0.18 * air) * wobble


def _rain(frames: int, rate: int) -> np.ndarray:
    rng = np.random.default_rng(20261009)
    hiss = np.diff(_leaky(rng, frames, 0.6), prepend=0.0)
    slow = 0.75 + 0.25 * np.sin(2 * np.pi * np.arange(frames) / (rate * 11.0))
    return hiss * slow


def _fireplace(frames: int, rate: int) -> np.ndarray:
    rng = np.random.default_rng(20261010)
    rumble = _leaky(rng, frames, 0.97)
    crackle = np.zeros(frames, dtype=np.float64)
    cursor = rate // 3
    while cursor < frames - 80:
        width = int(rng.integers(12, 48))
        burst = rng.standard_normal(width) * np.hanning(width)
        crackle[cursor : cursor + width] += burst
        cursor += int(rng.uniform(0.45, 1.6) * rate)
    return 0.55 * rumble + 0.45 * crackle


def _colored(rng: np.random.Generator, frames: int, slope: float) -> np.ndarray:
    spec = np.fft.rfft(rng.standard_normal(frames))
    freqs = np.arange(spec.size, dtype=np.float64)
    freqs[0] = 1.0
    spec /= freqs ** (slope / 2.0)
    spec[0] = 0.0
    return np.fft.irfft(spec, n=frames)


def _leaky(rng: np.random.Generator, frames: int, keep: float) -> np.ndarray:
    white = rng.standard_normal(frames)
    out = np.empty(frames, dtype=np.float64)
    acc = 0.0
    gain = 1.0 - keep
    for index, sample in enumerate(white):
        acc = keep * acc + gain * sample
        out[index] = acc
    return out


def _tone(freq: float, seconds: float, rate: int) -> np.ndarray:
    t = np.arange(int(seconds * rate)) / rate
    return np.sin(2 * np.pi * freq * t) * np.hanning(t.size)


def _stereo(mono: np.ndarray, rate: int, peak: float) -> np.ndarray:
    looped = _loop(mono, rate)
    other = np.roll(looped, rate // 200)
    return _scale(np.column_stack([looped, 0.85 * other]), peak)


def _loop(mono: np.ndarray, rate: int, fade_s: float = 0.3) -> np.ndarray:
    fade = int(fade_s * rate)
    if mono.size <= fade * 2:
        return mono
    audio = np.array(mono, dtype=np.float64, copy=True)
    ramp = np.linspace(0.0, 1.0, fade)
    audio[:fade] = audio[:fade] * ramp + audio[-fade:] * (1.0 - ramp)
    return audio[:-fade]


def _scale(audio: np.ndarray, peak: float) -> np.ndarray:
    loudest = float(np.max(np.abs(audio))) or 1.0
    scaled = audio / loudest * peak
    return np.clip(np.rint(scaled * 32767.0), -32768, 32767).astype(np.int16)
