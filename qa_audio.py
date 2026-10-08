#!/usr/bin/env python3
"""Quick WAV quality QA for OHush research captures."""

from __future__ import annotations

import json
import math
import struct
import sys
import wave
from array import array
from pathlib import Path

import numpy as np
from scipy import signal


def read_wav(path: Path):
    """Read PCM; tolerate in-progress files with bad headers."""
    raw = path.read_bytes()
    if len(raw) < 44:
        raise RuntimeError(f"{path}: too small")

    # Prefer stdlib wave for finalized files
    try:
        with wave.open(str(path), "rb") as w:
            rate = w.getframerate()
            ch = w.getnchannels()
            sw = w.getsampwidth()
            nframes = w.getnframes()
            data = w.readframes(nframes)
            if sw == 2 and nframes > 1000 and len(data) >= nframes * ch * 2:
                x = np.frombuffer(data, dtype="<i2").astype(np.float64)
                x = x.reshape(-1, ch) / 32768.0
                return rate, ch, x, "wave-header"
    except Exception:
        pass

    # Fallback: assume standard 16-bit PCM WAV, data from byte 44
    if raw[0:4] != b"RIFF" or raw[8:12] != b"WAVE":
        raise RuntimeError(f"{path}: not a RIFF/WAVE file")

    # Find 'data' chunk
    pos = 12
    data_offset = None
    while pos + 8 <= len(raw):
        chunk_id = raw[pos : pos + 4]
        chunk_size = struct.unpack_from("<I", raw, pos + 4)[0]
        if chunk_id == b"fmt ":
            (
                audio_format,
                ch,
                rate,
                _byte_rate,
                _block_align,
                bits,
            ) = struct.unpack_from("<HHIIHH", raw, pos + 8)
            if audio_format != 1 or bits != 16:
                raise RuntimeError(
                    f"{path}: expected PCM 16-bit, got format={audio_format} bits={bits}"
                )
        if chunk_id == b"data":
            data_offset = pos + 8
            # For in-progress files, use remaining file bytes
            payload = raw[data_offset:]
            break
        pos += 8 + chunk_size + (chunk_size % 2)

    if data_offset is None:
        # Common in-progress case: header says data size 0 but bytes follow
        data_offset = 44
        payload = raw[data_offset:]
        ch = struct.unpack_from("<H", raw, 22)[0]
        rate = struct.unpack_from("<I", raw, 24)[0]

    usable = len(payload) - (len(payload) % (ch * 2))
    x = np.frombuffer(payload[:usable], dtype="<i2").astype(np.float64)
    x = x.reshape(-1, ch) / 32768.0
    return rate, ch, x, "raw-fallback"


def true_peak_dbfs(x: np.ndarray) -> float:
    peak = float(np.max(np.abs(x)))
    if peak <= 0:
        return -100.0
    return 20.0 * math.log10(peak)


def rms_dbfs(x: np.ndarray) -> float:
    rms = float(np.sqrt(np.mean(np.square(x))))
    if rms <= 0:
        return -100.0
    return 20.0 * math.log10(rms)


def analyze(path: Path) -> dict:
    rate, ch, x, how = read_wav(path)
    n = x.shape[0]
    dur = n / rate

    mono = x.mean(axis=1) if ch > 1 else x[:, 0]
    left = x[:, 0]
    right = x[:, 1] if ch > 1 else left

    # Clipping: samples at full scale
    abs_i16 = np.abs((x * 32768.0).astype(np.int32))
    clip_frac = float(np.mean(abs_i16 >= 32767))

    # Near-silence frames (50 ms)
    hop = max(1, int(0.05 * rate))
    frame_rms = []
    for i in range(0, len(mono) - hop, hop):
        frame_rms.append(float(np.sqrt(np.mean(mono[i : i + hop] ** 2))))
    frame_rms = np.array(frame_rms) if frame_rms else np.array([0.0])
    silent_frac = float(np.mean(frame_rms < 10 ** (-60 / 20)))  # < -60 dBFS

    # DC offset
    dc = float(np.mean(mono))

    # Crest factor
    peak = true_peak_dbfs(mono)
    rms = rms_dbfs(mono)
    crest = peak - rms if peak > -99 else float("nan")

    # Spectrum on a mid-file 10s window (or all if shorter)
    win_sec = min(10.0, dur)
    start = int(max(0, (dur / 2 - win_sec / 2) * rate))
    seg = mono[start : start + int(win_sec * rate)]
    if len(seg) < rate // 2:
        seg = mono

    freqs, psd = signal.welch(seg, fs=rate, nperseg=min(4096, len(seg)))
    psd = np.maximum(psd, 1e-20)
    psd_db = 10 * np.log10(psd)
    # Band energies
    def band_power(f0, f1):
        m = (freqs >= f0) & (freqs < f1)
        return float(np.sum(psd[m]))

    total = float(np.sum(psd))
    bands = {
        "sub_20_60": band_power(20, 60) / total,
        "low_60_250": band_power(60, 250) / total,
        "mid_250_4k": band_power(250, 4000) / total,
        "high_4k_12k": band_power(4000, 12000) / total,
        "air_12k_20k": band_power(12000, 20000) / total,
        "nyquist_edge_20k_24k": band_power(20000, min(24000, rate / 2)) / total,
    }

    # Stereo correlation
    if ch > 1 and np.std(left) > 1e-8 and np.std(right) > 1e-8:
        corr = float(np.corrcoef(left, right)[0, 1])
    else:
        corr = 1.0

    # Heuristic: Dolby/bitstream garbage often looks like near-full-scale noise-ish
    # or ultra-high HF energy with little speech band — flag oddities
    speech_like = bands["mid_250_4k"] > 0.25
    has_air = bands["air_12k_20k"] > 0.01  # some HF present = not brickwalled telephony
    mostly_silent = silent_frac > 0.95 or peak < -80

    verdicts = []
    if mostly_silent:
        verdicts.append("FAIL: effectively silence")
    else:
        verdicts.append("PASS: has measurable signal")

    if clip_frac > 0.001:
        verdicts.append(f"WARN: clipping fraction {clip_frac:.4%}")
    else:
        verdicts.append("PASS: no significant clipping")

    if abs(dc) > 0.01:
        verdicts.append(f"WARN: DC offset {dc:.4f}")
    else:
        verdicts.append("PASS: DC offset negligible")

    if peak > -1.0:
        verdicts.append("WARN: peaks near 0 dBFS (hot)")
    elif peak > -60:
        verdicts.append(f"PASS: peak level healthy ({peak:.1f} dBFS)")

    if speech_like:
        verdicts.append("PASS: energy concentrated in speech/music midband")
    elif not mostly_silent:
        verdicts.append("WARN: unusual spectral balance (check source)")

    if ch == 2 and corr > 0.98:
        verdicts.append("INFO: near-mono stereo (normal for many TV mixes)")
    elif ch == 2:
        verdicts.append(f"INFO: stereo correlation {corr:.3f}")

    if rate == 48000 and ch in (1, 2):
        verdicts.append("PASS: archival format 48 kHz PCM")
    else:
        verdicts.append(f"WARN: unexpected format {rate} Hz / {ch} ch")

    hist_peak = float(np.percentile(np.abs(mono), 99.9))

    return {
        "file": str(path),
        "read_via": how,
        "sample_rate_hz": rate,
        "channels": ch,
        "duration_sec": round(dur, 3),
        "peak_dbfs": round(peak, 2),
        "rms_dbfs": round(rms, 2),
        "crest_db": round(crest, 2) if crest == crest else None,
        "clip_fraction": round(clip_frac, 6),
        "silent_frame_fraction": round(silent_frac, 4),
        "dc_offset": round(dc, 6),
        "stereo_correlation": round(corr, 4),
        "band_energy_frac": {k: round(v, 4) for k, v in bands.items()},
        "p99_9_abs_amplitude": round(hist_peak, 4),
        "verdicts": verdicts,
    }


def main():
    root = Path("recordings")
    files = sorted(root.rglob("audio_*.wav"))
    if not files:
        print("No WAV files found.")
        sys.exit(1)

    reports = []
    for f in files:
        try:
            reports.append(analyze(f))
        except Exception as e:
            reports.append({"file": str(f), "error": str(e)})

    out = Path("recordings/qa_report.json")
    out.write_text(json.dumps(reports, indent=2), encoding="utf-8")

    print("OHUSH AUDIO QA\n")
    for r in reports:
        print("=" * 72)
        if "error" in r:
            print(r["file"])
            print("ERROR:", r["error"])
            continue
        print(r["file"])
        print(
            f"  {r['duration_sec']}s | {r['sample_rate_hz']} Hz | "
            f"{r['channels']} ch | peak {r['peak_dbfs']} dBFS | "
            f"rms {r['rms_dbfs']} dBFS"
        )
        print(
            f"  silent_frames={r['silent_frame_fraction']:.1%}  "
            f"clip={r['clip_fraction']:.4%}  "
            f"stereo_corr={r['stereo_correlation']}"
        )
        b = r["band_energy_frac"]
        print(
            "  bands: "
            f"low={b['low_60_250']:.2%}  "
            f"mid={b['mid_250_4k']:.2%}  "
            f"high={b['high_4k_12k']:.2%}  "
            f"air={b['air_12k_20k']:.2%}"
        )
        for v in r["verdicts"]:
            print(f"  - {v}")

    print("\nWrote", out)


if __name__ == "__main__":
    # Fix accidental unicode in source if any — rewrite clean main without typo
    main()
