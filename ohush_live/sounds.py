"""Replacement beds for a family listen.

Older beds (stadium/rain/fireplace) prefer Mixkit files in ohush_live/beds when
present. Soft beds: hush (light shush), neon/charge/volt/drop (instrumental EDM —
no vocals), ocean, stream, birds, breeze, night, chimes, piano, pad, harp, meadow.

All non-silence beds are RMS-matched so cover loudness tracks the TV.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf

RATE = 48000
LOOP_S = 12.0
# Target RMS in float [-1, 1]. ~-20 dBFS — present, not crushingly loud.
BED_RMS = 0.10
BED_PEAK_CAP = 0.90
# Kept for callers/tests that imported the old peak constant.
BED_PEAK = BED_RMS * 0.5
BED_DIR = Path(__file__).resolve().parent / "beds"

# Soft defaults first — the vetoed sports/noise set stays available at the end.
GENERATED_BEDS = (
    "hush",
    "neon",
    "charge",
    "volt",
    "drop",
    "ocean",
    "stream",
    "birds",
    "breeze",
    "night",
    "chimes",
    "piano",
    "pad",
    "harp",
    "meadow",
    "stadium",
    "rain",
    "fireplace",
    "pink",
    "brown",
)
RECORDING_BEDS = ("stadium", "rain", "fireplace")


def make_beds(rate: int = RATE, use_recordings: bool = True) -> dict[str, np.ndarray]:
    frames = int(LOOP_S * rate)
    makers = {
        "hush": _hush,
        "neon": _neon,
        "charge": _charge,
        "volt": _volt,
        "drop": _drop,
        "ocean": _ocean,
        "stream": _stream,
        "birds": _birds,
        "breeze": _breeze,
        "night": _night,
        "chimes": _chimes,
        "piano": _piano,
        "pad": _pad,
        "harp": _harp,
        "meadow": _meadow,
        "stadium": _stadium,
        "rain": _rain,
        "fireplace": _fireplace,
        "pink": lambda f, r: _colored(np.random.default_rng(11), f, 1.0),
        "brown": lambda f, r: _colored(np.random.default_rng(13), f, 2.0),
    }
    beds: dict[str, np.ndarray] = {
        "silence": np.zeros((frames, 2), dtype=np.int16),
    }
    for name in GENERATED_BEDS:
        beds[name] = _stereo(makers[name](frames, rate), rate)
    if use_recordings:
        for name in RECORDING_BEDS:
            loaded = _read_recording(name)
            if loaded is not None:
                beds[name] = loaded
    return beds


def _read_recording(name: str) -> np.ndarray | None:
    path = BED_DIR / f"{name}.wav"
    if not path.is_file():
        return None
    audio, rate = sf.read(path, dtype="float64", always_2d=True)
    if rate != RATE or audio.shape[1] != 2:
        raise RuntimeError(f"{path.name} must be {RATE} Hz stereo")
    audio = _trim_edges(audio, rate)
    audio = _densest_loop(audio, rate, LOOP_S)
    audio = _flatten_dynamics(audio)
    return _to_int16(_normalize_rms(audio))


def _trim_edges(audio: np.ndarray, rate: int, floor: float = 0.003) -> np.ndarray:
    """Drop leading/trailing near-silence so beds do not start mute."""
    level = np.mean(np.abs(audio), axis=1)
    live = np.flatnonzero(level >= floor)
    if live.size == 0:
        return audio
    pad = int(0.05 * rate)
    start = max(0, int(live[0]) - pad)
    end = min(audio.shape[0], int(live[-1]) + pad)
    if end - start < rate:
        return audio
    return audio[start:end]


def _densest_loop(audio: np.ndarray, rate: int, seconds: float) -> np.ndarray:
    """Keep the loudest contiguous loop so sparse rain/fire files stay present."""
    want = int(seconds * rate)
    if audio.shape[0] <= want:
        return audio
    power = np.mean(np.square(audio), axis=1)
    csum = np.concatenate([[0.0], np.cumsum(power)])
    window = csum[want:] - csum[:-want]
    best_i = int(np.argmax(window))
    return audio[best_i : best_i + want]


def _flatten_dynamics(audio: np.ndarray) -> np.ndarray:
    """Mild compression so crackle/drops do not steal the RMS budget."""
    peak = np.maximum(np.max(np.abs(audio), axis=1, keepdims=True), 1e-6)
    gain = np.power(peak, -0.35)
    return audio * gain


def make_earcon(rate: int = RATE) -> np.ndarray:
    tone = np.concatenate([_tone(880, 0.12, rate), _tone(660, 0.16, rate)])
    stereo = np.column_stack([tone, tone])
    return _to_int16(_normalize_rms(stereo, target_rms=0.06, peak_cap=0.25))


def _hush(frames: int, rate: int) -> np.ndarray:
    """Light shush bed — soft breathy noise, not pink/brown wall."""
    rng = np.random.default_rng(20261030)
    t = np.arange(frames) / rate
    # Gentle under-bed + a "shh" band that breathes slowly.
    under = _band(_colored(rng, frames, 1.3), rate, 120, 1200) * 0.45
    shush = _band(_colored(rng, frames, 0.55), rate, 1800, 7000)
    breath = 0.72 + 0.28 * np.sin(2 * np.pi * t / 8.5)
    # Tiny irregular softens so it does not sound like a fan stuck on.
    flutter = 0.92 + 0.08 * _band(_leaky(rng, frames, 0.995), rate, 0.2, 8)
    return under + 0.7 * shush * breath * flutter


def _neon(frames: int, rate: int) -> np.ndarray:
    """Instrumental progressive house — 128 BPM, supersaw + sidechain, no vocals."""
    rng = np.random.default_rng(20261050)
    return _edm_bed(
        rng,
        frames,
        rate,
        bpm=128.0,
        bass_notes=(55.0, 55.0, 65.41, 73.42),
        lead_notes=(220.0, 277.18, 329.63, 370.0),
        style="progress",
        drive=1.35,
    )


def _charge(frames: int, rate: int) -> np.ndarray:
    """Big-room instrumental — 130 BPM, wide saws, hard clap, festival energy."""
    rng = np.random.default_rng(20261051)
    return _edm_bed(
        rng,
        frames,
        rate,
        bpm=130.0,
        bass_notes=(49.0, 49.0, 61.74, 55.0),
        lead_notes=(196.0, 246.94, 293.66, 392.0),
        style="bigroom",
        drive=1.55,
    )


def _volt(frames: int, rate: int) -> np.ndarray:
    """Peak-time techno — 136 BPM, rolling bass, industrial hats, no vocals."""
    rng = np.random.default_rng(20261052)
    return _edm_bed(
        rng,
        frames,
        rate,
        bpm=136.0,
        bass_notes=(55.0, 58.27, 55.0, 65.41),
        lead_notes=(110.0, 164.81, 220.0, 246.94),
        style="techno",
        drive=1.45,
    )


def _drop(frames: int, rate: int) -> np.ndarray:
    """Festival drop loop — 128 BPM, supersaw stabs + sub hits, instrumental only."""
    rng = np.random.default_rng(20261053)
    return _edm_bed(
        rng,
        frames,
        rate,
        bpm=128.0,
        bass_notes=(41.2, 41.2, 55.0, 61.74),
        lead_notes=(329.63, 392.0, 493.88, 587.33),
        style="drop",
        drive=1.65,
    )


def _edm_bed(
    rng: np.random.Generator,
    frames: int,
    rate: int,
    *,
    bpm: float,
    bass_notes: tuple[float, ...],
    lead_notes: tuple[float, ...],
    style: str,
    drive: float,
) -> np.ndarray:
    """Instrumental EDM bed — kick/bass/hats/synths only. No voices, no samples of speech."""
    out = np.zeros(frames, dtype=np.float64)
    beat = max(1, int(round(rate * 60.0 / bpm)))
    pump = np.ones(frames, dtype=np.float64)
    t_all = np.arange(frames) / rate
    gain = 1.15

    # Supersaw lead (detuned sines) — the EDM "no words" hook.
    lead = np.zeros(frames, dtype=np.float64)
    detune = (-0.012, -0.005, 0.0, 0.005, 0.012)
    for note in lead_notes[:3]:
        for cents in detune:
            lead += np.sin(2 * np.pi * note * (1.0 + cents) * t_all)
    lead /= max(1, 3 * len(detune))
    # Gate pattern by style.
    if style == "techno":
        gate_steps = [0.0, 0.5]
        gate_len = 0.12
    elif style == "drop":
        gate_steps = [0.0, 0.25, 0.5, 0.75]
        gate_len = 0.09
    elif style == "bigroom":
        gate_steps = [0.0, 0.5]
        gate_len = 0.16
    else:
        gate_steps = [0.0, 0.5]
        gate_len = 0.14
    gate = np.zeros(frames, dtype=np.float64)
    n_beats = max(1, (frames + beat - 1) // beat)
    for beat_i in range(n_beats):
        start = beat_i * beat
        for frac in gate_steps:
            hit = start + int(frac * beat)
            n = min(int(gate_len * rate), frames - hit)
            if n > 8:
                gate[hit : hit + n] = np.maximum(gate[hit : hit + n], np.hanning(n))
    # Slow filter swell so it feels alive across the 12s loop.
    sweep = 0.55 + 0.45 * (0.5 + 0.5 * np.sin(2 * np.pi * t_all / 6.0))
    lead = _band(lead * gate * sweep, rate, 180, 5200 if style != "techno" else 2800)
    lead *= 0.72 * gain * drive

    # Air / noise riser texture (instrumental hiss, not speech).
    air = _band(_colored(rng, frames, 0.7), rate, 800, 10000) * (0.05 * gain)
    if style in ("drop", "bigroom"):
        # Short noise whoosh every 4 beats.
        for beat_i in range(0, n_beats, 4):
            hit = beat_i * beat
            n = min(int(0.35 * rate), frames - hit)
            if n > 16:
                whoosh = _band(rng.standard_normal(n), rate, 2000, 12000) * np.linspace(0.05, 1.0, n)
                out[hit : hit + n] += 0.12 * gain * whoosh

    for beat_i in range(n_beats):
        start = beat_i * beat
        if start >= frames:
            break
        step = beat_i % 4

        # Four-on-the-floor kick.
        n_kick = min(int(0.16 * rate), frames - start)
        if n_kick > 8:
            t = np.arange(n_kick) / rate
            env = np.exp(-t * (22.0 if style == "techno" else 16.0))
            freq = (110.0 if style == "drop" else 95.0) * np.exp(-t * 32.0) + 40.0
            kick = np.tanh(drive * 1.8 * np.sin(2 * np.pi * np.cumsum(freq) / rate) * env)
            click_n = min(int(0.014 * rate), n_kick)
            click = _band(rng.standard_normal(click_n), rate, 3000, 11000) * np.hanning(click_n)
            out[start : start + n_kick] += 1.05 * gain * kick
            out[start : start + click_n] += 0.18 * gain * click
            duck_n = min(int(0.2 * rate), frames - start)
            duck_t = np.arange(duck_n) / rate
            pump[start : start + duck_n] *= 0.18 + 0.82 * (1.0 - np.exp(-duck_t * 18.0))

        # Clap / snare on 2 and 4.
        if step in (1, 3):
            n = min(int(0.13 * rate), frames - start)
            if n > 8:
                body = _band(rng.standard_normal(n), rate, 800, 5500)
                top = _band(rng.standard_normal(n), rate, 5000, 12000)
                t = np.arange(n) / rate
                env = np.exp(-t * 24.0)
                tone = np.sin(2 * np.pi * 200.0 * t) * np.exp(-t * 45.0)
                level = 0.38 if style == "bigroom" else 0.3
                out[start : start + n] += level * gain * drive * (0.7 * body + 0.35 * top + 0.25 * tone) * env

        # Hats — 16ths for energy.
        for frac in (0.0, 0.25, 0.5, 0.75):
            hit = start + int(frac * beat)
            if hit + 40 >= frames:
                continue
            n_hat = min(int(0.03 * rate), frames - hit)
            hat = _band(rng.standard_normal(n_hat), rate, 7500, 16000)
            t = np.arange(n_hat) / rate
            level = 0.14 * gain * (1.0 if frac in (0.0, 0.5) else 0.7)
            if style == "techno":
                level *= 1.15
            out[hit : hit + n_hat] += level * hat * np.exp(-t * 90.0)

        # Offbeat open hat.
        oh = start + int(0.5 * beat)
        n_oh = min(int(0.1 * rate), frames - oh)
        if n_oh > 16:
            hat = _band(rng.standard_normal(n_oh), rate, 5500, 14000)
            t = np.arange(n_oh) / rate
            out[oh : oh + n_oh] += 0.09 * gain * hat * np.exp(-t * 16.0)

        # Rolling / pumping bass — instrumental only.
        note = bass_notes[(beat_i // 4) % len(bass_notes)]
        bass_hits = [0.0, 0.5] if style != "techno" else [0.0, 0.25, 0.5, 0.75]
        for frac in bass_hits:
            hit = start + int(frac * beat)
            if hit >= frames:
                continue
            n = min(int(0.38 * 60.0 / bpm * rate), frames - hit)
            if n < 16:
                continue
            t = np.arange(n) / rate
            env = (1.0 - np.exp(-t * 50.0)) * np.exp(-t * (4.5 if style == "techno" else 3.0))
            tone = 0.75 * np.sin(2 * np.pi * note * t) + 0.3 * np.sin(2 * np.pi * note * 2.0 * t)
            if style == "drop":
                tone += 0.15 * np.sin(2 * np.pi * note * 0.5 * t)
            tone = np.tanh(drive * 2.0 * tone)
            out[hit : hit + n] += (0.58 if frac == 0.0 else 0.42) * gain * tone * env

    out += (lead + air) * pump
    out = 0.65 * out + 0.35 * _band(out, rate, 45, 220)
    out = np.tanh(0.95 * drive * out)
    return out


def _ocean(frames: int, rate: int) -> np.ndarray:
    rng = np.random.default_rng(20261021)
    t = np.arange(frames) / rate
    surf = _band(_colored(rng, frames, 0.7), rate, 80, 900)
    swell = 0.55 + 0.45 * (0.5 + 0.5 * np.sin(2 * np.pi * t / 9.0))
    foam = _band(np.diff(_leaky(rng, frames, 0.55), prepend=0.0), rate, 600, 4000) * 0.25
    return surf * swell + foam * (0.7 + 0.3 * swell)


def _stream(frames: int, rate: int) -> np.ndarray:
    rng = np.random.default_rng(20261022)
    flow = _band(_colored(rng, frames, 0.4), rate, 200, 3500)
    gurgle = _band(np.diff(_leaky(rng, frames, 0.7), prepend=0.0), rate, 800, 6000)
    pulse = 0.8 + 0.2 * np.sin(2 * np.pi * np.arange(frames) / (rate * 5.5))
    return (0.7 * flow + 0.3 * gurgle) * pulse


def _birds(frames: int, rate: int) -> np.ndarray:
    rng = np.random.default_rng(20261023)
    air = _band(_colored(rng, frames, 1.2), rate, 100, 600) * 0.15
    out = np.array(air, copy=True)
    cursor = int(0.4 * rate)
    while cursor < frames - int(0.4 * rate):
        freq = float(rng.uniform(1800, 4200))
        chirp_n = int(rng.uniform(0.06, 0.16) * rate)
        t = np.arange(chirp_n) / rate
        sweep = freq * (1.0 + 0.12 * np.sin(2 * np.pi * 18 * t))
        env = np.hanning(chirp_n) ** 1.4
        out[cursor : cursor + chirp_n] += 0.55 * np.sin(2 * np.pi * np.cumsum(sweep) / rate) * env
        cursor += int(rng.uniform(0.7, 2.2) * rate)
    return out


def _breeze(frames: int, rate: int) -> np.ndarray:
    rng = np.random.default_rng(20261024)
    air = _band(_colored(rng, frames, 1.4), rate, 120, 1800)
    slow = 0.7 + 0.3 * np.sin(2 * np.pi * np.arange(frames) / (rate * 13.0))
    return air * slow


def _night(frames: int, rate: int) -> np.ndarray:
    rng = np.random.default_rng(20261025)
    bed = _band(_colored(rng, frames, 1.6), rate, 80, 700) * 0.35
    out = np.array(bed, copy=True)
    # Soft cricket-like ticks — present enough to hold loudness after RMS match.
    cursor = int(0.15 * rate)
    while cursor < frames - 200:
        n = int(rng.integers(50, 110))
        t = np.arange(n) / rate
        tick = np.sin(2 * np.pi * rng.uniform(3600, 5000) * t) * np.hanning(n)
        out[cursor : cursor + n] += 0.35 * tick
        cursor += int(rng.uniform(0.05, 0.22) * rate)
        if rng.random() < 0.08:
            cursor += int(rng.uniform(0.35, 0.9) * rate)
    return out


def _chimes(frames: int, rate: int) -> np.ndarray:
    rng = np.random.default_rng(20261026)
    # Soft pentatonic metal — sparse, not doorbell spam.
    notes = np.array([523.25, 587.33, 659.25, 783.99, 880.0, 1046.5])
    air = _band(_colored(rng, frames, 1.8), rate, 100, 400) * 0.05
    out = np.array(air, copy=True)
    cursor = int(0.5 * rate)
    while cursor < frames - int(1.5 * rate):
        freq = float(rng.choice(notes))
        n = int(rng.uniform(1.2, 2.8) * rate)
        t = np.arange(n) / rate
        env = np.exp(-t * rng.uniform(1.2, 2.0))
        partial = (
            0.7 * np.sin(2 * np.pi * freq * t)
            + 0.22 * np.sin(2 * np.pi * freq * 2.01 * t)
            + 0.08 * np.sin(2 * np.pi * freq * 3.02 * t)
        )
        out[cursor : cursor + n] += 0.45 * partial * env
        cursor += int(rng.uniform(1.6, 3.4) * rate)
    return out


def _piano(frames: int, rate: int) -> np.ndarray:
    rng = np.random.default_rng(20261027)
    # Quiet open fifths / soft keys — ambient, not a song.
    chord_sets = [
        (261.63, 392.00, 523.25),
        (220.00, 329.63, 440.00),
        (196.00, 293.66, 392.00),
        (246.94, 369.99, 493.88),
    ]
    felt = _band(_colored(rng, frames, 2.0), rate, 40, 200) * 0.04
    out = np.array(felt, copy=True)
    cursor = int(0.3 * rate)
    idx = 0
    while cursor < frames - int(2.0 * rate):
        freqs = chord_sets[idx % len(chord_sets)]
        idx += 1
        n = int(2.4 * rate)
        t = np.arange(n) / rate
        env = np.exp(-t * 0.9) * (1.0 - 0.35 * t / t[-1])
        tone = sum(np.sin(2 * np.pi * f * t) * (0.5 / (i + 1)) for i, f in enumerate(freqs))
        out[cursor : cursor + n] += 0.5 * tone * env
        cursor += int(rng.uniform(2.0, 3.2) * rate)
    return out


def _pad(frames: int, rate: int) -> np.ndarray:
    rng = np.random.default_rng(20261028)
    t = np.arange(frames) / rate
    # Warm low pad — least likely to get a veto.
    a = np.sin(2 * np.pi * 110.0 * t)
    b = np.sin(2 * np.pi * 164.81 * t + 0.2)
    c = np.sin(2 * np.pi * 220.0 * t + 0.4)
    slow = 0.75 + 0.25 * np.sin(2 * np.pi * t / 11.0)
    breath = _band(_colored(rng, frames, 1.5), rate, 80, 500) * 0.12
    return (0.45 * a + 0.35 * b + 0.2 * c) * slow + breath


def _harp(frames: int, rate: int) -> np.ndarray:
    rng = np.random.default_rng(20261029)
    scale = np.array([261.63, 293.66, 329.63, 392.00, 440.00, 523.25, 587.33])
    air = _band(_colored(rng, frames, 1.7), rate, 80, 350) * 0.06
    out = np.array(air, copy=True)
    cursor = int(0.25 * rate)
    while cursor < frames - int(0.8 * rate):
        run = int(rng.integers(3, 6))
        start = int(rng.integers(0, len(scale) - run))
        for step in range(run):
            freq = float(scale[start + step])
            n = int(0.55 * rate)
            if cursor + n >= frames:
                break
            t = np.arange(n) / rate
            env = np.exp(-t * 3.2)
            out[cursor : cursor + n] += 0.35 * np.sin(2 * np.pi * freq * t) * env
            cursor += int(0.09 * rate)
        cursor += int(rng.uniform(1.4, 2.6) * rate)
    return out


def _meadow(frames: int, rate: int) -> np.ndarray:
    # Light air + distant soft life — calmer than stadium, less hiss than rain.
    return 0.55 * _breeze(frames, rate) + 0.30 * _birds(frames, rate) + 0.15 * _night(frames, rate)


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


def _band(mono: np.ndarray, rate: int, low_hz: float, high_hz: float) -> np.ndarray:
    spec = np.fft.rfft(mono)
    freqs = np.fft.rfftfreq(mono.size, d=1.0 / rate)
    mask = (freqs >= low_hz) & (freqs <= high_hz)
    # Soft edges
    soft = np.ones_like(freqs)
    soft[freqs < low_hz] = 0.0
    soft[freqs > high_hz] = 0.0
    width = max(20.0, (high_hz - low_hz) * 0.08)
    rise = (freqs >= low_hz) & (freqs < low_hz + width)
    fall = (freqs <= high_hz) & (freqs > high_hz - width)
    soft[rise] = (freqs[rise] - low_hz) / width
    soft[fall] = (high_hz - freqs[fall]) / width
    soft[~mask & ~rise & ~fall] = 0.0
    return np.fft.irfft(spec * soft, n=mono.size)


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


def _stereo(mono: np.ndarray, rate: int) -> np.ndarray:
    looped = _loop(mono, rate)
    other = np.roll(looped, rate // 200)
    return _to_int16(_normalize_rms(np.column_stack([looped, 0.85 * other])))


def _loop(mono: np.ndarray, rate: int, fade_s: float = 0.3) -> np.ndarray:
    fade = int(fade_s * rate)
    if mono.size <= fade * 2:
        return mono
    audio = np.array(mono, dtype=np.float64, copy=True)
    ramp = np.linspace(0.0, 1.0, fade)
    audio[:fade] = audio[:fade] * ramp + audio[-fade:] * (1.0 - ramp)
    return audio[:-fade]


def _normalize_rms(
    audio: np.ndarray,
    target_rms: float = BED_RMS,
    peak_cap: float = BED_PEAK_CAP,
) -> np.ndarray:
    """Match loudness by RMS. Soft-clip peaks so sparse beds stay present."""
    samples = np.asarray(audio, dtype=np.float64)
    rms = float(np.sqrt(np.mean(np.square(samples)))) or 1.0
    scaled = samples * (target_rms / rms)
    peak = float(np.max(np.abs(scaled))) or 1.0
    if peak > peak_cap:
        scaled = peak_cap * np.tanh(scaled / peak_cap)
        rms2 = float(np.sqrt(np.mean(np.square(scaled)))) or 1.0
        scaled *= target_rms / rms2
        peak2 = float(np.max(np.abs(scaled))) or 1.0
        if peak2 > 0.99:
            scaled *= 0.99 / peak2
    return scaled


def _to_int16(audio: np.ndarray) -> np.ndarray:
    return np.clip(np.rint(audio * 32767.0), -32768, 32767).astype(np.int16)
