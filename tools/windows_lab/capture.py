"""Lossless PCM capture helpers for Node 01.

Preferred path: record from an explicit Windows input (Stereo Mix / loopback
equivalent). Does not use Mac --live mute paths. Does not auto-pick the mic.
"""

from __future__ import annotations

import json
import queue
import threading
import time
import wave
from array import array
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import sounddevice as sd

from .config import ensure_data_layout


def list_input_devices() -> list[dict]:
    out = []
    for i, d in enumerate(sd.query_devices()):
        if int(d.get("max_input_channels") or 0) > 0:
            out.append(
                {
                    "index": i,
                    "name": d["name"],
                    "channels": int(d["max_input_channels"]),
                    "default_samplerate": float(d["default_samplerate"]),
                    "hostapi": sd.query_hostapis()[int(d["hostapi"])]["name"],
                }
            )
    return out


def find_device(name_substr: str) -> int:
    needle = name_substr.lower()
    for d in list_input_devices():
        if needle in d["name"].lower():
            return int(d["index"])
    raise LookupError(f"no input device matching {name_substr!r}: {list_input_devices()}")


def capture_pcm(
    *,
    device: int | str,
    seconds: float = 60.0,
    samplerate: int = 48000,
    channels: int = 2,
    outfile: Path | None = None,
    source_label: str = "unspecified",
    rights_status: str = "test_public",
) -> dict:
    if isinstance(device, str):
        device = find_device(device)

    info = sd.query_devices(device)
    max_ch = int(info["max_input_channels"])
    if max_ch < 1:
        raise RuntimeError(f"device {device} has no inputs")
    channels = min(channels, max_ch)

    root = ensure_data_layout()
    work = root / "work" / "capture"
    work.mkdir(parents=True, exist_ok=True)
    if outfile is None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        outfile = work / f"capture_{stamp}.wav"
    outfile = Path(outfile)

    q: queue.Queue[bytes] = queue.Queue()
    warnings: list[str] = []

    def callback(indata, frames, time_info, status):  # noqa: ARG001
        if status:
            warnings.append(str(status))
        q.put(bytes(indata))

    frames_target = int(round(seconds * samplerate))
    collected = array("h")
    utc_start = datetime.now(timezone.utc).isoformat()
    t0 = time.perf_counter()

    with sd.RawInputStream(
        samplerate=samplerate,
        channels=channels,
        dtype="int16",
        device=device,
        callback=callback,
        blocksize=0,
    ):
        while len(collected) // channels < frames_target:
            try:
                block = q.get(timeout=2.0)
            except queue.Empty:
                warnings.append("queue_timeout")
                continue
            collected.frombytes(block)

    elapsed = time.perf_counter() - t0
    # Trim to exact frame count
    n = frames_target * channels
    data = collected[:n]
    if len(data) < n:
        warnings.append(f"short_capture frames={len(data)//channels} expected={frames_target}")

    with wave.open(str(outfile), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(samplerate)
        w.writeframes(data.tobytes())

    x = np.frombuffer(data.tobytes(), dtype="<i2").astype(np.float64)
    if channels > 1:
        x = x.reshape(-1, channels)
    peak = float(np.max(np.abs(x))) / 32768.0 if len(x) else 0.0

    manifest = {
        "outfile": str(outfile),
        "device_index": int(device),
        "device_name": info["name"],
        "sample_rate_hz": samplerate,
        "channels": channels,
        "requested_seconds": seconds,
        "sample_count": len(data) // channels,
        "wall_clock_elapsed_sec": round(elapsed, 3),
        "capture_utc_start": utc_start,
        "capture_utc_end": datetime.now(timezone.utc).isoformat(),
        "peak_abs": round(peak, 6),
        "nonzero": peak > 1e-5,
        "warnings": warnings,
        "source_label": source_label,
        "rights_status": rights_status,
        "source_type": "authorized_stream_reference",
        "capture_software": "sounddevice RawInputStream int16 PCM",
    }
    side = outfile.with_suffix(".capture_manifest.json")
    side.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    manifest["manifest_path"] = str(side)
    return manifest


def write_public_fixture(path: Path, seconds: float = 60.0, sr: int = 48000) -> Path:
    """Generate a licensed-safe synthetic stereo fixture (not TV content)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    t = np.arange(int(seconds * sr), dtype=np.float64) / sr
    # Speech-ish midband + slow amplitude envelope (deterministic)
    left = 0.2 * np.sin(2 * np.pi * 440 * t) * (0.5 + 0.5 * np.sin(2 * np.pi * 0.5 * t))
    left += 0.08 * np.sin(2 * np.pi * 880 * t)
    right = 0.2 * np.sin(2 * np.pi * 554.37 * t) * (0.5 + 0.5 * np.sin(2 * np.pi * 0.5 * t + 0.3))
    right += 0.05 * np.sin(2 * np.pi * 1108 * t)
    stereo = np.stack([left, right], axis=1)
    pcm = np.clip(stereo * 32767.0, -32768, 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    return path


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="List devices or capture PCM")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list-devices")

    c = sub.add_parser("record")
    c.add_argument("--device", required=True, help="Device index or name substring")
    c.add_argument("--seconds", type=float, default=60.0)
    c.add_argument("--outfile", type=Path)
    c.add_argument("--source-label", default="manual_capture")
    c.add_argument("--rights-status", default="test_public")

    f = sub.add_parser("fixture")
    f.add_argument("--outfile", type=Path, required=True)
    f.add_argument("--seconds", type=float, default=60.0)

    args = p.parse_args(argv)
    if args.cmd == "list-devices":
        print(json.dumps(list_input_devices(), indent=2))
        return 0
    if args.cmd == "fixture":
        path = write_public_fixture(args.outfile, seconds=args.seconds)
        print(json.dumps({"ok": True, "path": str(path)}))
        return 0
    if args.cmd == "record":
        device: int | str
        try:
            device = int(args.device)
        except ValueError:
            device = args.device
        man = capture_pcm(
            device=device,
            seconds=args.seconds,
            outfile=args.outfile,
            source_label=args.source_label,
            rights_status=args.rights_status,
        )
        print(json.dumps({"ok": True, "manifest": man}, indent=2))
        return 0 if man.get("nonzero") else 3
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
