"""Original 60-second cover sketches. Not installed as live beds.

Does not change the listener gate, the detector, or the vibe library.
Silence is digital silence. The other six are synthesized here.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy import signal

RATE = 48000
DURATION_S = 60.0
TARGET_RMS = 0.08
PEAK_CAP = 0.90
OUT = Path(__file__).resolve().parent / "renders"
RECEIPT = Path(__file__).resolve().parent / "receipt.json"


def main() -> None:
    n = int(DURATION_S * RATE)
    sketches = {
        "warm_air": warm_air(n, RATE),
        "velvet_beat": velvet_beat(n, RATE),
        "light_shuffle": light_shuffle(n, RATE),
        "slow_current": slow_current(n, RATE),
        "sparse_mallets": sparse_mallets(n, RATE),
        "synthetic_arena": synthetic_arena(n, RATE),
        "silence": np.zeros((n, 2), dtype=np.float64),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for name, audio in sketches.items():
        if name != "silence":
            audio = _normalize(audio)
            audio = _loop_seam(audio, RATE)
        _check(name, audio)
        path = OUT / f"{name}.wav"
        sf.write(str(path), audio, RATE, subtype="PCM_16")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        rows.append(_measure(name, audio, digest))
        print(
            f"{name:16} rms={rows[-1]['rms']:.4f}  peak={rows[-1]['peak']:.3f}  "
            f"centroid={rows[-1]['centroid_hz']:.0f}  low_pulses={rows[-1]['low_pulses']}"
        )
    RECEIPT.write_text(json.dumps({"experiment": "SOUND_IDENTITY_001", "sketches": rows}, indent=2) + "\n")
    print("wrote", RECEIPT)


def warm_air(n: int, rate: int) -> np.ndarray:
    rng = np.random.default_rng(20261015)
    t = np.arange(n) / rate
    left = _lowpass(rng.normal(0, 1, n), rate, 420)
    right = _lowpass(rng.normal(0, 1, n), rate, 360)
    drift_l = 0.82 + 0.18 * np.sin(2 * np.pi * t / 27.0)
    drift_r = 0.78 + 0.22 * np.sin(2 * np.pi * t / 41.0 + 1.2)
    return np.column_stack([left * drift_l, right * drift_r])


def velvet_beat(n: int, rate: int) -> np.ndarray:
    bed = warm_air(n, rate) * 0.55
    pulse = _soft_pulse(n, rate, bpm=72.0, swing=0.0, hat=0.08)
    return bed + pulse


def light_shuffle(n: int, rate: int) -> np.ndarray:
    bed = warm_air(n, rate) * 0.40
    pulse = _soft_pulse(n, rate, bpm=88.0, swing=0.18, hat=0.22)
    return bed + pulse


def slow_current(n: int, rate: int) -> np.ndarray:
    rng = np.random.default_rng(20261016)
    t = np.arange(n) / rate
    layers = []
    for cutoff, period, phase in ((240, 19.0, 0.0), (480, 31.0, 1.4), (860, 47.0, 2.2)):
        noise = _lowpass(rng.normal(0, 1, n), rate, cutoff)
        gain = 0.35 + 0.65 * (0.5 + 0.5 * np.sin(2 * np.pi * t / period + phase))
        layers.append(noise * gain)
    mono = sum(layers)
    right = _lowpass(rng.normal(0, 1, n), rate, 520) * (0.7 + 0.3 * np.sin(2 * np.pi * t / 23.0))
    return np.column_stack([mono, right])


def sparse_mallets(n: int, rate: int) -> np.ndarray:
    rng = np.random.default_rng(20261017)
    bed = warm_air(n, rate) * 0.45
    notes = (174.61, 196.00, 220.00, 261.63, 293.66)
    mono = np.zeros(n, dtype=np.float64)
    t_cursor = 2.5
    while t_cursor < DURATION_S - 2.0:
        start = int(t_cursor * rate)
        freq = float(rng.choice(notes))
        length = int(2.4 * rate)
        end = min(n, start + length)
        tt = np.arange(end - start) / rate
        env = np.exp(-tt / 0.85)
        tone = np.sin(2 * np.pi * freq * tt) + 0.12 * np.sin(2 * np.pi * freq * 2 * tt)
        mono[start:end] += 0.55 * tone * env
        t_cursor += float(rng.uniform(4.5, 8.5))
    widened = np.column_stack([mono, np.roll(mono, int(0.012 * rate))])
    return bed + widened


def synthetic_arena(n: int, rate: int) -> np.ndarray:
    """Distant murmur made of filtered noise. Not a crowd recording."""
    rng = np.random.default_rng(20261018)
    t = np.arange(n) / rate
    band = _bandpass(rng.normal(0, 1, n), rate, 180, 640)
    other = _bandpass(rng.normal(0, 1, n), rate, 220, 700)
    swell = _lowpass(rng.normal(0, 1, n), rate, 1.5)
    swell = 0.55 + 0.45 * (swell - swell.min()) / (np.ptp(swell) + 1e-9)
    breath = 0.75 + 0.25 * np.sin(2 * np.pi * t / 13.0)
    return np.column_stack([band * swell * breath, other * swell])


def _soft_pulse(n: int, rate: int, bpm: float, swing: float, hat: float) -> np.ndarray:
    rng = np.random.default_rng(int(bpm * 1000) + 7)
    mono = np.zeros(n, dtype=np.float64)
    hat_bus = np.zeros(n, dtype=np.float64)
    period = 60.0 / bpm
    t_cursor = 0.05
    beat = 0
    while t_cursor < DURATION_S:
        offset = period * swing if beat % 2 else 0.0
        start = int((t_cursor + offset) * rate)
        if start >= n:
            break
        thump_n = int(0.18 * rate)
        end = min(n, start + thump_n)
        tt = np.arange(end - start) / rate
        body = np.sin(2 * np.pi * 52.0 * tt) * np.exp(-tt / 0.045)
        mono[start:end] += body * (0.85 if beat % 2 == 0 else 0.35)
        if hat:
            tick_n = int(0.04 * rate)
            tick_end = min(n, start + tick_n)
            noise = rng.normal(0, 1, tick_end - start)
            hat_bus[start:tick_end] += noise * np.exp(-np.arange(tick_end - start) / (0.008 * rate))
        beat += 1
        if beat % 2 == 0:
            t_cursor += period
    if hat:
        hat_bus = _bandpass(hat_bus, rate, 900, 2800) * hat
    stereo = np.column_stack([mono + hat_bus, mono * 0.85 + np.roll(hat_bus, 80)])
    return stereo


def _lowpass(audio: np.ndarray, rate: int, cutoff: float) -> np.ndarray:
    sos = signal.butter(2, cutoff, btype="low", fs=rate, output="sos")
    return signal.sosfilt(sos, audio)


def _bandpass(audio: np.ndarray, rate: int, low: float, high: float) -> np.ndarray:
    sos = signal.butter(2, [low, high], btype="band", fs=rate, output="sos")
    return signal.sosfilt(sos, audio)


def _normalize(audio: np.ndarray) -> np.ndarray:
    rms = float(np.sqrt(np.mean(np.square(audio))))
    scaled = audio * (TARGET_RMS / max(rms, 1e-9))
    peak = float(np.max(np.abs(scaled)))
    if peak > PEAK_CAP:
        scaled *= PEAK_CAP / peak
    return scaled


def _loop_seam(audio: np.ndarray, rate: int) -> np.ndarray:
    fade = int(0.04 * rate)
    ramp = np.linspace(0.0, 1.0, fade)[:, None]
    head = audio[:fade].copy()
    audio[:fade] = audio[:fade] * ramp + audio[-fade:] * (1.0 - ramp)
    audio[-fade:] = audio[-fade:] * (1.0 - ramp) + head * ramp
    return audio


def _check(name: str, audio: np.ndarray) -> None:
    if audio.shape != (int(DURATION_S * RATE), 2):
        raise SystemExit(f"{name} shape {audio.shape}")
    peak = float(np.max(np.abs(audio)))
    rms = float(np.sqrt(np.mean(np.square(audio))))
    if name == "silence":
        if peak != 0.0:
            raise SystemExit("silence is not digital silence")
        return
    if peak > PEAK_CAP + 1e-6:
        raise SystemExit(f"{name} peak {peak}")
    if not 0.9 * TARGET_RMS <= rms <= TARGET_RMS * 1.02:
        raise SystemExit(f"{name} rms {rms}")
    pulses = _low_pulses(audio, RATE)
    if name == "warm_air" and pulses > 4:
        raise SystemExit(f"warm air has {pulses} low pulses")
    if name == "velvet_beat" and not 60 <= pulses <= 84:
        raise SystemExit(f"velvet beat pulses {pulses}")
    if name == "light_shuffle" and not 70 <= pulses <= 110:
        raise SystemExit(f"shuffle pulses {pulses}")
    if name == "synthetic_arena" and pulses > 8:
        raise SystemExit(f"arena pulses {pulses}")


def _low_pulses(audio: np.ndarray, rate: int) -> int:
    low = _lowpass(audio.mean(axis=1), rate, 80)
    win = int(0.05 * rate)
    energy = np.convolve(np.square(low), np.ones(win) / win, mode="valid")
    step = win
    sampled = energy[::step]
    threshold = max(float(np.median(sampled)) * 4.0, 1e-8)
    peaks = 0
    armed = True
    for value in sampled:
        if armed and value > threshold:
            peaks += 1
            armed = False
        elif value < threshold * 0.5:
            armed = True
    return peaks


def _measure(name: str, audio: np.ndarray, digest: str) -> dict:
    mono = audio.mean(axis=1)
    rms = float(np.sqrt(np.mean(np.square(audio))))
    spectrum = np.abs(np.fft.rfft(mono[: RATE * 8]))
    freqs = np.fft.rfftfreq(RATE * 8, 1.0 / RATE)
    centroid = float(np.sum(freqs * spectrum) / max(np.sum(spectrum), 1e-12))
    return {
        "name": name,
        "sha256": digest,
        "duration_s": DURATION_S,
        "sample_rate": RATE,
        "channels": 2,
        "rms": round(rms, 5),
        "peak": round(float(np.max(np.abs(audio))), 4),
        "centroid_hz": round(centroid, 1),
        "low_pulses": _low_pulses(audio, RATE),
        "installed_in_gate": False,
    }


if __name__ == "__main__":
    main()
