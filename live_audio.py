"""Live stereo pass-through for OHush.

Three invariants:

- Muting never stops input capture.
- Muting never stops ring consumption. MUTE discards the block it just read
  and writes zeros. It does not pause the ring.
- A dropped recording block never shortens session time. The WAV gets the
  same number of zero frames, and the gap is logged on the input sample clock.

The output callback does not wait on disk, HTTP, or a detector. A scheduled
mute deadline is applied from the input sample clock inside the callbacks so
unmute stays on that clock. Operator modes are pass-through, manual, and auto. AUTO cannot mute: the frozen
detector stays offline until a causal detector exists.

Transport health (stopped, priming, running) is not an operator mode.
"""

from __future__ import annotations

import json
import math
import queue
import select
import signal
import sys
import threading
import time
import wave
from array import array
from datetime import datetime
from pathlib import Path
from typing import Any

import sounddevice as sd

BYTES_PER_SAMPLE = 2
CHANNELS = 2
BYTES_PER_FRAME = CHANNELS * BYTES_PER_SAMPLE
DEFAULT_RATE = 48000
BLOCK_FRAMES = 480
PRIME_MS = 40.0
CAPACITY_MS = 250.0
RAMP_FRAMES = 64
SILENCE_DBFS = -80.0
SILENCE_SECONDS = 5.0
STALL_SECONDS = 0.5

MODES = ("pass_through", "manual", "auto")
MODE_LABELS = {
    "pass_through": "PASS-THROUGH",
    "manual": "MANUAL",
    "auto": "AUTO",
}


class LiveControlError(RuntimeError):
    """Operator command rejected. The audio thread keeps running."""


def silence_bytes(frames: int, channels: int = CHANNELS) -> bytes:
    return bytes(frames * channels * BYTES_PER_SAMPLE)


def peak_dbfs(data: bytes) -> float:
    samples = array("h")
    samples.frombytes(data)
    if not samples:
        return -100.0
    peak = max(abs(sample) for sample in samples)
    if peak == 0:
        return -100.0
    return 20.0 * math.log10(peak / 32768.0)


def near_zero_fraction(data: bytes) -> float:
    samples = array("h")
    samples.frombytes(data)
    if not samples:
        return 1.0
    quiet = sum(1 for sample in samples if abs(sample) <= 1)
    return quiet / len(samples)


def timeline_bytes(
    written_samples: int,
    start_session_sample: int,
    data: bytes,
    channels: int = CHANNELS,
) -> tuple[int, bytes]:
    """Insert zero frames so a dropped block does not compress session time."""
    bytes_per_frame = channels * BYTES_PER_SAMPLE
    if bytes_per_frame <= 0 or len(data) % bytes_per_frame != 0:
        raise ValueError("record block is not a whole number of frames")
    frames = len(data) // bytes_per_frame
    hole = start_session_sample - written_samples
    if hole < 0:
        raise RuntimeError(
            f"record block at sample {start_session_sample} overlaps "
            f"the WAV timeline at {written_samples}"
        )
    if hole:
        data = silence_bytes(hole, channels) + data
    return written_samples + hole + frames, data


def latency_seconds(value: Any) -> float | None:
    if value is None or isinstance(value, (tuple, list)):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def rates_mismatch(
    requested: int,
    input_rate: int | None,
    output_rate: int | None,
    input_default: float | None,
    output_default: float | None,
) -> bool:
    observed: list[int] = [int(requested)]
    for rate in (input_rate, output_rate):
        if rate is not None:
            observed.append(int(rate))
    for rate in (input_default, output_default):
        if rate is not None:
            observed.append(int(round(rate)))
    if any(rate != DEFAULT_RATE for rate in observed):
        return True
    if input_rate is not None and output_rate is not None and input_rate != output_rate:
        return True
    return False


def host_resampling(
    input_rate: int | None,
    output_rate: int | None,
    input_default: float | None,
    output_default: float | None,
) -> bool:
    pairs = (
        (input_rate, input_default),
        (output_rate, output_default),
    )
    for active, default in pairs:
        if active is None or default is None:
            continue
        if int(active) != int(round(default)):
            return True
    return False


def query_audio_devices() -> list[dict[str, Any]]:
    found = []
    for index, device in enumerate(sd.query_devices()):
        found.append(
            {
                "index": index,
                "name": device["name"],
                "max_input_channels": int(device["max_input_channels"]),
                "max_output_channels": int(device["max_output_channels"]),
                "default_samplerate": float(device["default_samplerate"]),
            }
        )
    return found


def devices_payload(devices: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    rows = query_audio_devices() if devices is None else devices
    return {
        "inputs": [row for row in rows if row["max_input_channels"] > 0],
        "outputs": [row for row in rows if row["max_output_channels"] > 0],
    }


def resolve_live_device(
    value: Any,
    kind: str,
    devices: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Exact name or index. Never fall back to the default device."""
    if kind not in ("input", "output"):
        raise LiveControlError(f"unknown device kind {kind}")
    rows = query_audio_devices() if devices is None else devices
    channel_key = "max_input_channels" if kind == "input" else "max_output_channels"
    eligible = [row for row in rows if row[channel_key] > 0]
    if value is None or (isinstance(value, str) and not value.strip()):
        raise LiveControlError(
            f"Choose an {kind} device. Refusing to use the default device."
        )

    index: int | None = None
    if isinstance(value, int):
        index = value
    elif isinstance(value, str) and value.strip().lstrip("-").isdigit():
        index = int(value.strip())

    if index is not None:
        matches = [row for row in eligible if row["index"] == index]
        if len(matches) != 1:
            raise LiveControlError(
                f"No {kind} device at index {index}. Refusing to use the default device."
            )
        return matches[0]

    name = str(value)
    matches = [row for row in eligible if row["name"] == name]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise LiveControlError(
            f'{kind.title()} device "{name}" is not available. '
            "Refusing to use the default device."
        )
    raise LiveControlError(
        f'Multiple {kind} devices are named "{name}". Use a device index.'
    )


class StereoRing:
    """Interleaved int16 stereo ring. Overflow drops the oldest frames."""

    def __init__(self, capacity_frames: int) -> None:
        if capacity_frames < 1:
            raise ValueError("ring capacity must be positive")
        self.capacity = capacity_frames
        self._buf = bytearray(capacity_frames * BYTES_PER_FRAME)
        self._read = 0
        self._write = 0
        self._fill = 0
        self.overruns = 0
        self._lock = threading.Lock()

    def fill_frames(self) -> int:
        with self._lock:
            return self._fill

    def overrun_count(self) -> int:
        with self._lock:
            return self.overruns

    def write(self, data: bytes) -> None:
        frames = len(data) // BYTES_PER_FRAME
        if frames <= 0:
            return
        if len(data) != frames * BYTES_PER_FRAME:
            raise ValueError("ring write is not a whole number of stereo frames")
        with self._lock:
            if frames > self.capacity:
                data = data[-self.capacity * BYTES_PER_FRAME :]
                frames = self.capacity
                self._read = 0
                self._write = 0
                self._fill = 0
                self.overruns += 1
                self._blit(data)
                self._fill = frames
                return
            extra = self._fill + frames - self.capacity
            if extra > 0:
                self._read = (self._read + extra) % self.capacity
                self._fill -= extra
                self.overruns += 1
            self._blit(data)
            self._fill += frames

    def read_if_available(self, frames: int) -> bytes | None:
        if frames <= 0:
            return None
        with self._lock:
            if frames > self._fill:
                return None
            out = self._take(frames)
            self._fill -= frames
            return out

    def _blit(self, data: bytes) -> None:
        nbytes = len(data)
        capacity_bytes = self.capacity * BYTES_PER_FRAME
        start = self._write * BYTES_PER_FRAME
        first = min(nbytes, capacity_bytes - start)
        self._buf[start : start + first] = data[:first]
        rest = nbytes - first
        if rest:
            self._buf[:rest] = data[first:]
        self._write = (self._write + (nbytes // BYTES_PER_FRAME)) % self.capacity

    def _take(self, frames: int) -> bytes:
        nbytes = frames * BYTES_PER_FRAME
        capacity_bytes = self.capacity * BYTES_PER_FRAME
        start = self._read * BYTES_PER_FRAME
        first = min(nbytes, capacity_bytes - start)
        if first == nbytes:
            out = bytes(self._buf[start : start + first])
        else:
            out = bytes(self._buf[start : start + first]) + bytes(self._buf[: nbytes - first])
        self._read = (self._read + frames) % self.capacity
        return out


class LiveEngine:
    """Hardware-free transport. push_input and render_output are the callbacks."""

    def __init__(
        self,
        sample_rate: int = DEFAULT_RATE,
        prime_ms: float = PRIME_MS,
        capacity_ms: float = CAPACITY_MS,
        ramp_frames: int = RAMP_FRAMES,
        record_queue_size: int = 256,
        silence_dbfs: float = SILENCE_DBFS,
        silence_seconds: float = SILENCE_SECONDS,
        stall_seconds: float = STALL_SECONDS,
    ) -> None:
        self.sample_rate = sample_rate
        self.prime_ms = prime_ms
        self.capacity_ms = capacity_ms
        self.ramp_frames = ramp_frames
        self.record_queue_size = record_queue_size
        self.silence_dbfs = silence_dbfs
        self.silence_seconds = silence_seconds
        self.stall_seconds = stall_seconds
        self.requested_rate = sample_rate
        self._lock = threading.Lock()
        self._reset_locked(keep_mode=False)

    def _reset_locked(self, keep_mode: bool) -> None:
        mode = self.mode if keep_mode else "pass_through"
        self.mode = mode
        self.gate = "play"
        self._mute_until: int | None = None
        self._gate_applied = "play"
        self._ramp_left = 0
        self._ramp_up = False
        self.transport = "stopped"
        self.session_samples = 0
        self.prime_frames = max(1, int(round(self.sample_rate * self.prime_ms / 1000.0)))
        self.capacity_frames = max(
            self.prime_frames + 1,
            int(round(self.sample_rate * self.capacity_ms / 1000.0)),
        )
        self.ring = StereoRing(self.capacity_frames)
        self._record_q: queue.Queue[tuple[int, bytes]] = queue.Queue(
            maxsize=self.record_queue_size
        )
        self.record_queue_drops = 0
        self.recording_gaps: list[dict[str, Any]] = []
        self.manual_mute_events: list[dict[str, Any]] = []
        self._open_mute: dict[str, Any] | None = None
        self.ring_underruns = 0
        self.reprime_count = 0
        self.input_portaudio_flags = 0
        self.output_portaudio_flags = 0
        self.last_input_status: str | None = None
        self.last_output_status: str | None = None
        self.warnings: list[str] = []
        self.input_dbfs = -100.0
        self.output_dbfs = -100.0
        self.near_zero = 0.0
        self._silent_samples = 0
        self.silence_samples = max(1, int(round(self.silence_seconds * self.sample_rate)))
        self.input_silent = False
        self.input_disconnected = False
        self.output_disconnected = False
        self.engine_stalled = False
        self.error: str | None = None
        self.buffer_ms = 0.0
        self.buffer_min_ms: float | None = None
        self.buffer_max_ms: float | None = None
        self.last_input_callback: float | None = None
        self.last_output_callback: float | None = None
        self.input_device_name: str | None = None
        self.output_device_name: str | None = None
        self.input_device_index: int | None = None
        self.output_device_index: int | None = None
        self.input_default_rate: float | None = None
        self.output_default_rate: float | None = None
        self.input_rate: int | None = None
        self.output_rate: int | None = None
        self.input_latency_s: float | None = None
        self.output_latency_s: float | None = None
        self.last_fail_safe: str | None = None

    def begin_session(
        self,
        input_device: dict[str, Any],
        output_device: dict[str, Any],
        requested_rate: int,
    ) -> None:
        with self._lock:
            self.sample_rate = requested_rate
            self.requested_rate = requested_rate
            self._reset_locked(keep_mode=True)
            self.input_device_name = input_device["name"]
            self.output_device_name = output_device["name"]
            self.input_device_index = int(input_device["index"])
            self.output_device_index = int(output_device["index"])
            self.input_default_rate = float(input_device["default_samplerate"])
            self.output_default_rate = float(output_device["default_samplerate"])
            self.input_rate = requested_rate
            self.output_rate = requested_rate

    def note_stream_opened(
        self,
        input_rate: int,
        output_rate: int,
        input_latency_s: float | None,
        output_latency_s: float | None,
    ) -> None:
        with self._lock:
            self.input_rate = int(input_rate)
            self.output_rate = int(output_rate)
            self.input_latency_s = input_latency_s
            self.output_latency_s = output_latency_s

    def open_transport(self, at: float | None = None) -> None:
        with self._lock:
            self.transport = "priming"
            self.input_disconnected = False
            self.output_disconnected = False
            self.engine_stalled = False
            now = time.monotonic() if at is None else at
            self.last_input_callback = now
            self.last_output_callback = now

    def stop_transport(self) -> None:
        with self._lock:
            if self.gate == "mute":
                self._end_mute_locked()
            self.gate = "play"
            self._mute_until = None
            self.transport = "stopped"

    def push_input(self, data: bytes) -> None:
        frames = len(data) // BYTES_PER_FRAME
        if frames <= 0 or len(data) != frames * BYTES_PER_FRAME:
            return
        with self._lock:
            if self.transport == "stopped":
                return
            start = self.session_samples
            self.session_samples = start + frames
            self._note_input_level_locked(data)
            self.last_input_callback = time.monotonic()
            self._expire_mute_locked()
            try:
                self._record_q.put_nowait((start, data))
            except queue.Full:
                self.record_queue_drops += 1
                self.recording_gaps.append(self._gap_locked(start, frames))
            self.ring.write(data)
            self._note_fill_locked()

    def render_output(self, frames: int) -> bytes:
        with self._lock:
            self.last_output_callback = time.monotonic()
            if self.transport == "stopped" or frames <= 0:
                self.output_dbfs = -100.0
                return silence_bytes(max(frames, 0))
            self._expire_mute_locked()
            if self.transport == "priming":
                self._note_fill_locked()
                if self.ring.fill_frames() < max(self.prime_frames, frames):
                    self.output_dbfs = -100.0
                    return silence_bytes(frames)
                self.transport = "running"
            consumed = self.ring.read_if_available(frames)
            if consumed is None:
                self.ring_underruns += 1
                self.reprime_count += 1
                self.transport = "priming"
                self._note_fill_locked()
                self.output_dbfs = -100.0
                return silence_bytes(frames)
            rendered = self._apply_gate_locked(consumed)
            self.output_dbfs = peak_dbfs(rendered)
            self._note_fill_locked()
            return rendered

    def pop_record(self) -> tuple[int, bytes] | None:
        try:
            return self._record_q.get_nowait()
        except queue.Empty:
            return None

    def tick(self) -> None:
        with self._lock:
            self._expire_mute_locked()

    def set_mode(self, mode: str) -> None:
        if mode not in MODES:
            raise LiveControlError(
                'Mode must be "pass_through", "manual", or "auto".'
            )
        with self._lock:
            self.mode = mode
            if mode != "manual" and self.gate == "mute":
                self._end_mute_locked()

    def mute(self) -> None:
        with self._lock:
            self._require_manual_locked()
            if self.gate != "mute":
                self._begin_mute_locked()

    def unmute(self) -> None:
        with self._lock:
            self._require_manual_locked()
            if self.gate == "mute":
                self._end_mute_locked()

    def test_mute(self, seconds: float = 2.0) -> None:
        with self._lock:
            self._require_manual_locked()
            if self.gate != "mute":
                self._begin_mute_locked()
            self._mute_until = self.session_samples + int(round(seconds * self.sample_rate))

    def fail_safe(self, reason: str) -> None:
        with self._lock:
            self.last_fail_safe = reason
            if self.gate == "mute":
                self._end_mute_locked()
            self.gate = "play"
            self._mute_until = None

    def mark_disconnected(self, kind: str) -> None:
        with self._lock:
            if kind == "input":
                self.input_disconnected = True
            elif kind == "output":
                self.output_disconnected = True
            self.last_fail_safe = f"{kind} device disconnected"
            if self.gate == "mute":
                self._end_mute_locked()
            self.gate = "play"
            self._mute_until = None

    def mark_stalled(self) -> None:
        with self._lock:
            self.engine_stalled = True
            self.last_fail_safe = "audio engine stalled"
            if self.gate == "mute":
                self._end_mute_locked()
            self.gate = "play"
            self._mute_until = None

    def clear_runtime_faults(self) -> None:
        with self._lock:
            self.input_disconnected = False
            self.output_disconnected = False
            self.engine_stalled = False
            self.error = None

    def note_input_status(self, status: Any) -> None:
        if not status:
            return
        text = str(status)
        with self._lock:
            self.input_portaudio_flags += 1
            self.last_input_status = text
            self._remember_warning_locked(f"input: {text}")

    def note_output_status(self, status: Any) -> None:
        if not status:
            return
        text = str(status)
        with self._lock:
            self.output_portaudio_flags += 1
            self.last_output_status = text
            self._remember_warning_locked(f"output: {text}")

    def note_heartbeats(self, at: float) -> None:
        with self._lock:
            self.last_input_callback = at
            self.last_output_callback = at

    def callback_stalled(self, now: float | None = None) -> bool:
        with self._lock:
            if self.transport == "stopped":
                return False
            if self.last_input_callback is None or self.last_output_callback is None:
                return False
            moment = time.monotonic() if now is None else now
            limit = self.stall_seconds
            return (moment - self.last_input_callback) > limit or (
                moment - self.last_output_callback
            ) > limit

    def clear_stall(self) -> None:
        with self._lock:
            self.engine_stalled = False

    def warning_lines(self) -> list[str]:
        with self._lock:
            return list(self.warnings)

    def set_error(self, message: str | None) -> None:
        with self._lock:
            self.error = message

    @property
    def recording_integrity(self) -> str:
        return "degraded" if self.record_queue_drops else "ok"

    @property
    def xruns(self) -> int:
        return (
            self.input_portaudio_flags
            + self.output_portaudio_flags
            + self.ring.overrun_count()
            + self.ring_underruns
        )

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            buffer_ms = self.buffer_ms
            input_latency_ms = (
                None if self.input_latency_s is None else self.input_latency_s * 1000.0
            )
            output_latency_ms = (
                None if self.output_latency_s is None else self.output_latency_s * 1000.0
            )
            estimated = None
            if self.transport != "stopped" or input_latency_ms is not None or output_latency_ms is not None:
                estimated = buffer_ms
                if input_latency_ms is not None:
                    estimated += input_latency_ms
                if output_latency_ms is not None:
                    estimated += output_latency_ms
            mismatch = rates_mismatch(
                self.requested_rate,
                self.input_rate,
                self.output_rate,
                self.input_default_rate,
                self.output_default_rate,
            )
            resampling = host_resampling(
                self.input_rate,
                self.output_rate,
                self.input_default_rate,
                self.output_default_rate,
            )
            elapsed = self.session_samples / self.sample_rate if self.sample_rate else 0.0
            return {
                "mode": self.mode,
                "gate": self.gate,
                "gate_reason": "manual" if self.gate == "mute" else None,
                "transport": self.transport,
                "prime_ms": self.prime_ms,
                "buffer_ms": round(buffer_ms, 2),
                "buffer_frames": self.ring.fill_frames(),
                "buffer_target_ms": self.prime_ms,
                "buffer_min_ms": None
                if self.buffer_min_ms is None
                else round(self.buffer_min_ms, 2),
                "buffer_max_ms": None
                if self.buffer_max_ms is None
                else round(self.buffer_max_ms, 2),
                "input_dbfs": round(self.input_dbfs, 1),
                "output_dbfs": round(self.output_dbfs, 1),
                "dbfs": round(self.input_dbfs, 1),
                "elapsed_seconds": round(elapsed, 3),
                "session_samples": self.session_samples,
                "input_device_name": self.input_device_name,
                "output_device_name": self.output_device_name,
                "input_device_index": self.input_device_index,
                "output_device_index": self.output_device_index,
                "input_channels": CHANNELS if self.input_device_name else None,
                "output_channels": CHANNELS if self.output_device_name else None,
                "input_rate_hz": self.input_rate,
                "output_rate_hz": self.output_rate,
                "input_default_rate_hz": self.input_default_rate,
                "output_default_rate_hz": self.output_default_rate,
                "requested_rate_hz": self.requested_rate,
                "sample_rate_mismatch": mismatch if self.input_rate is not None else False,
                "host_resampling": resampling if self.input_rate is not None else False,
                "input_portaudio_flags": self.input_portaudio_flags,
                "output_portaudio_flags": self.output_portaudio_flags,
                "ring_overruns": self.ring.overrun_count(),
                "ring_underruns": self.ring_underruns,
                "record_queue_drops": self.record_queue_drops,
                "reprime_count": self.reprime_count,
                "xruns": (
                    self.input_portaudio_flags
                    + self.output_portaudio_flags
                    + self.ring.overrun_count()
                    + self.ring_underruns
                ),
                "recording_integrity": "degraded" if self.record_queue_drops else "ok",
                "input_silent": self.input_silent,
                "input_disconnected": self.input_disconnected,
                "output_disconnected": self.output_disconnected,
                "engine_stalled": self.engine_stalled,
                "estimated_transport_latency_ms": None
                if estimated is None
                else round(estimated, 2),
                "input_stream_latency_ms": None
                if input_latency_ms is None
                else round(input_latency_ms, 2),
                "output_stream_latency_ms": None
                if output_latency_ms is None
                else round(output_latency_ms, 2),
                "near_zero_fraction": round(self.near_zero, 4),
                "error": self.error,
                "sample_rate_hz": self.input_rate or self.requested_rate,
                "channels": CHANNELS,
                "device_index": self.input_device_index,
                "device_name": self.input_device_name,
            }

    def session_metadata(self) -> dict[str, Any]:
        snap = self.snapshot()
        with self._lock:
            gaps = [dict(gap) for gap in self.recording_gaps]
            events = [dict(event) for event in self.manual_mute_events]
            last_input_status = self.last_input_status
            last_output_status = self.last_output_status
        return {
            "input_device": snap["input_device_name"],
            "output_device": snap["output_device_name"],
            "input_rate": snap["input_rate_hz"],
            "output_rate": snap["output_rate_hz"],
            "requested_rate": snap["requested_rate_hz"],
            "input_default_rate": snap["input_default_rate_hz"],
            "output_default_rate": snap["output_default_rate_hz"],
            "channels": CHANNELS,
            "mode": snap["mode"],
            "input_portaudio_flags": snap["input_portaudio_flags"],
            "output_portaudio_flags": snap["output_portaudio_flags"],
            "ring_overruns": snap["ring_overruns"],
            "ring_underruns": snap["ring_underruns"],
            "record_queue_drops": snap["record_queue_drops"],
            "reprime_count": snap["reprime_count"],
            "xruns": snap["xruns"],
            "min_buffer_ms": snap["buffer_min_ms"],
            "max_buffer_ms": snap["buffer_max_ms"],
            "recording_integrity": snap["recording_integrity"],
            "recording_gaps": gaps,
            "manual_mute_events": events,
            "host_resampling": snap["host_resampling"],
            "sample_rate_mismatch": snap["sample_rate_mismatch"],
            "last_input_status": last_input_status,
            "last_output_status": last_output_status,
        }

    def _require_manual_locked(self) -> None:
        if self.transport == "stopped":
            raise LiveControlError("Audio is not running.")
        if self.mode == "manual":
            return
        if self.mode == "auto":
            raise LiveControlError(
                "AUTO cannot mute. discontinuity_causal_v1 is not connected."
            )
        raise LiveControlError("PASS-THROUGH disables the gate.")

    def _begin_mute_locked(self) -> None:
        self.gate = "mute"
        event = {
            "start_session_sample": self.session_samples,
            "end_session_sample": None,
            "start_elapsed_seconds": self._elapsed_locked(self.session_samples),
            "end_elapsed_seconds": None,
            "trigger": "manual",
            "start_monotonic": time.monotonic(),
            "end_monotonic": None,
        }
        self.manual_mute_events.append(event)
        self._open_mute = event

    def _end_mute_locked(self, end_sample: int | None = None) -> None:
        sample = self.session_samples if end_sample is None else end_sample
        event = self._open_mute
        if event is not None:
            event["end_session_sample"] = sample
            event["end_elapsed_seconds"] = self._elapsed_locked(sample)
            event["end_monotonic"] = time.monotonic()
        self._open_mute = None
        self.gate = "play"
        self._mute_until = None

    def _expire_mute_locked(self) -> None:
        if (
            self.gate == "mute"
            and self._mute_until is not None
            and self.session_samples >= self._mute_until
        ):
            self._end_mute_locked(end_sample=self._mute_until)

    def _elapsed_locked(self, sample: int) -> float:
        if not self.sample_rate:
            return 0.0
        return round(sample / self.sample_rate, 6)

    def _gap_locked(self, start: int, frames: int) -> dict[str, Any]:
        return {
            "start_session_sample": start,
            "frames_missing": frames,
            "duration_ms": round(frames / self.sample_rate * 1000.0, 3),
        }

    def _note_input_level_locked(self, data: bytes) -> None:
        level = peak_dbfs(data)
        self.input_dbfs = level
        self.near_zero = near_zero_fraction(data)
        frames = len(data) // BYTES_PER_FRAME
        if level < self.silence_dbfs:
            self._silent_samples += frames
        else:
            self._silent_samples = 0
        self.input_silent = self._silent_samples >= self.silence_samples

    def _note_fill_locked(self) -> None:
        frames = self.ring.fill_frames()
        ms = frames / self.sample_rate * 1000.0 if self.sample_rate else 0.0
        self.buffer_ms = ms
        if self.transport != "running":
            return
        if self.buffer_min_ms is None or ms < self.buffer_min_ms:
            self.buffer_min_ms = ms
        if self.buffer_max_ms is None or ms > self.buffer_max_ms:
            self.buffer_max_ms = ms

    def _apply_gate_locked(self, consumed: bytes) -> bytes:
        if self.gate != self._gate_applied:
            self._ramp_left = self.ramp_frames
            self._ramp_up = self.gate == "play"
            self._gate_applied = self.gate
        if self._ramp_left <= 0 or self.ramp_frames <= 0:
            if self.gate == "mute":
                return silence_bytes(len(consumed) // BYTES_PER_FRAME)
            return consumed
        samples = array("h")
        samples.frombytes(consumed)
        frames = len(samples) // CHANNELS
        for index in range(frames):
            if self._ramp_left <= 0:
                if self.gate == "mute":
                    samples[index * 2] = 0
                    samples[index * 2 + 1] = 0
                continue
            done = self.ramp_frames - self._ramp_left
            if self._ramp_up:
                gain = (done + 1) / self.ramp_frames
            else:
                gain = 1.0 - ((done + 1) / self.ramp_frames)
            samples[index * 2] = int(samples[index * 2] * gain)
            samples[index * 2 + 1] = int(samples[index * 2 + 1] * gain)
            self._ramp_left -= 1
        return samples.tobytes()

    def _remember_warning_locked(self, text: str) -> None:
        if text in self.warnings:
            return
        self.warnings.append(text)
        del self.warnings[:-20]


class WavSession:
    """Pre-gate WAV chunks whose frame count matches the input sample clock."""

    def __init__(
        self,
        folder: Path,
        sample_rate: int,
        channels: int,
        started_at: datetime,
        chunk_minutes: float = 15.0,
        frames_per_chunk: int | None = None,
    ) -> None:
        self.folder = folder
        self.sample_rate = sample_rate
        self.channels = channels
        self.started_at = started_at
        self.frames_per_chunk = frames_per_chunk or int(chunk_minutes * 60 * sample_rate)
        if self.frames_per_chunk < 1:
            raise ValueError("chunk size must be positive")
        self.chunks: list[dict[str, Any]] = []
        self.written = 0
        self.chunk_no = 1
        self.frames_in_chunk = 0
        self.wav, self.wav_path = self._open(self.chunk_no)

    def write_block(self, start_session_sample: int, data: bytes) -> None:
        _expected, blob = timeline_bytes(
            self.written,
            start_session_sample,
            data,
            self.channels,
        )
        self._write_bytes(blob)
        if self.written != _expected:
            raise RuntimeError(
                f"WAV committed {self.written} samples, expected {_expected}"
            )

    def finish(self, session_samples: int) -> None:
        hole = session_samples - self.written
        if hole > 0:
            self._write_bytes(silence_bytes(hole, self.channels))
        elif hole < 0:
            raise RuntimeError(
                f"WAV timeline {self.written} is ahead of session samples {session_samples}"
            )
        self._close_current(unlink_if_empty=True)

    def _open(self, number: int) -> tuple[wave.Wave_write, Path]:
        path = self.folder / f"audio_{number:04d}.wav"
        handle = wave.open(str(path), "wb")
        handle.setnchannels(self.channels)
        handle.setsampwidth(BYTES_PER_SAMPLE)
        handle.setframerate(self.sample_rate)
        return handle, path

    def _write_bytes(self, data: bytes) -> None:
        view = memoryview(data)
        offset = 0
        bytes_per_frame = self.channels * BYTES_PER_SAMPLE
        while offset < len(view):
            room = self.frames_per_chunk - self.frames_in_chunk
            if room <= 0:
                self._rotate()
                room = self.frames_per_chunk
            take_frames = min(room, (len(view) - offset) // bytes_per_frame)
            take = take_frames * bytes_per_frame
            self.wav.writeframesraw(view[offset : offset + take])
            self.frames_in_chunk += take_frames
            self.written += take_frames
            offset += take
            if self.frames_in_chunk >= self.frames_per_chunk:
                self._rotate()

    def _rotate(self) -> None:
        self._close_current(unlink_if_empty=False)
        self.chunk_no += 1
        self.frames_in_chunk = 0
        self.wav, self.wav_path = self._open(self.chunk_no)

    def _close_current(self, unlink_if_empty: bool) -> None:
        self.wav.close()
        if self.frames_in_chunk:
            seconds = self.frames_in_chunk / self.sample_rate
            start_elapsed = (self.written - self.frames_in_chunk) / self.sample_rate
            start_wall = self.started_at.timestamp() + start_elapsed
            end_wall = start_wall + seconds
            self.chunks.append(
                {
                    "file": self.wav_path.name,
                    "seconds": round(seconds, 3),
                    "start_elapsed_seconds": round(start_elapsed, 3),
                    "end_elapsed_seconds": round(start_elapsed + seconds, 3),
                    "started_at": datetime.fromtimestamp(start_wall).astimezone().isoformat(),
                    "ended_at": datetime.fromtimestamp(end_wall).astimezone().isoformat(),
                }
            )
        elif unlink_if_empty:
            self.wav_path.unlink(missing_ok=True)


class HardwareStreams:
    """Two independent CoreAudio devices. Not one duplex stream."""

    def __init__(self, engine: LiveEngine) -> None:
        self.engine = engine
        self.input_stream: Any = None
        self.output_stream: Any = None
        self.input_name: str | None = None
        self.output_name: str | None = None

    def start(
        self,
        input_device: dict[str, Any],
        output_device: dict[str, Any],
        rate: int,
        block_frames: int,
    ) -> None:
        if int(input_device["max_input_channels"]) < CHANNELS:
            raise LiveControlError(
                f'{input_device["name"]} exposes '
                f'{int(input_device["max_input_channels"])} input channel(s). '
                "Live pass-through needs stereo."
            )
        if int(output_device["max_output_channels"]) < CHANNELS:
            raise LiveControlError(
                f'{output_device["name"]} exposes '
                f'{int(output_device["max_output_channels"])} output channel(s). '
                "Live pass-through needs stereo."
            )
        self.close()
        self.engine.begin_session(input_device, output_device, rate)
        self.input_name = input_device["name"]
        self.output_name = output_device["name"]
        try:
            sd.check_input_settings(
                device=input_device["index"],
                channels=CHANNELS,
                dtype="int16",
                samplerate=rate,
            )
            sd.check_output_settings(
                device=output_device["index"],
                channels=CHANNELS,
                dtype="int16",
                samplerate=rate,
            )
            self.input_stream = sd.RawInputStream(
                device=input_device["index"],
                samplerate=rate,
                channels=CHANNELS,
                dtype="int16",
                blocksize=block_frames,
                latency="low",
                callback=self._on_input,
            )
            self.output_stream = sd.RawOutputStream(
                device=output_device["index"],
                samplerate=rate,
                channels=CHANNELS,
                dtype="int16",
                blocksize=block_frames,
                latency="low",
                callback=self._on_output,
            )
            self.engine.open_transport()
            self.input_stream.start()
            self.output_stream.start()
            self.engine.note_stream_opened(
                int(self.input_stream.samplerate),
                int(self.output_stream.samplerate),
                latency_seconds(self.input_stream.latency),
                latency_seconds(self.output_stream.latency),
            )
        except Exception:
            self.close()
            self.engine.stop_transport()
            raise

    def close(self) -> None:
        for stream in (self.output_stream, self.input_stream):
            if stream is None:
                continue
            try:
                stream.stop()
            except Exception:
                pass
            try:
                stream.close()
            except Exception:
                pass
        self.input_stream = None
        self.output_stream = None

    def connected(self, devices: list[dict[str, Any]] | None = None) -> tuple[bool, bool]:
        rows = query_audio_devices() if devices is None else devices
        inputs = {row["name"] for row in rows if row["max_input_channels"] > 0}
        outputs = {row["name"] for row in rows if row["max_output_channels"] > 0}
        input_ok = self.input_name is not None and self.input_name in inputs
        output_ok = self.output_name is not None and self.output_name in outputs
        return input_ok, output_ok

    def _on_input(self, indata: Any, frames: int, _time_info: Any, status: Any) -> None:
        try:
            self.engine.note_input_status(status)
            self.engine.push_input(bytes(indata))
        except Exception as exc:
            self.engine.fail_safe(f"input callback failed: {exc}")

    def _on_output(self, outdata: Any, frames: int, _time_info: Any, status: Any) -> None:
        try:
            self.engine.note_output_status(status)
            rendered = self.engine.render_output(frames)
            if len(rendered) != frames * BYTES_PER_FRAME:
                rendered = silence_bytes(frames)
            outdata[:] = rendered
        except Exception as exc:
            self.engine.fail_safe(f"output callback failed: {exc}")
            try:
                outdata[:] = silence_bytes(frames)
            except Exception:
                return


def _save_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _parse_mark_text(text: str) -> tuple[str | None, str | None]:
    lower = text.lower()
    if lower in ("a", "ad", "ad_start"):
        return "ad_start", None
    if lower in ("c", "content", "content_start"):
        return "content_start", None
    if lower.startswith("n "):
        return "note", text[2:].strip()
    if lower == "note":
        return "note", ""
    return None, None


class LiveHost:
    """Record pre-gate stereo WAV and expose the monitor command API."""

    def __init__(self, args: Any) -> None:
        self.args = args
        self.engine = LiveEngine(sample_rate=int(args.samplerate))
        self.hardware = HardwareStreams(self.engine)
        self.commands: queue.Queue[tuple[Any, ...]] = queue.Queue()
        self.stop = threading.Event()
        self.session: dict[str, Any] | None = None
        self.server: Any = None
        self.live: Any = None
        self._last_device_poll = 0.0
        self._last_save = 0.0
        self._last_print = 0.0
        self._last_publish = 0.0

    def serve(self) -> None:
        from live_server import LiveState, start_live_server

        if int(self.args.channels) != CHANNELS:
            raise LiveControlError("Live pass-through records and plays stereo.")
        if int(self.args.samplerate) <= 0:
            raise LiveControlError("Sample rate must be positive.")

        self.live = LiveState()
        self.server = start_live_server(
            self.live,
            self._on_mark,
            host=self.args.live_host,
            port=int(self.args.live_port),
            on_command=self._on_command,
            devices_provider=devices_payload,
        )
        signal.signal(signal.SIGINT, self._on_signal)
        signal.signal(signal.SIGTERM, self._on_signal)
        self._publish(force=True)
        self._print_banner()

        try:
            if self.args.input_device or self.args.output_device:
                if not (self.args.input_device and self.args.output_device):
                    message = (
                        "Pass both --input-device and --output-device, "
                        "or neither and choose them in the monitor."
                    )
                    self.engine.set_error(message)
                    print(message, file=sys.stderr)
                else:
                    result = self.start_session(
                        {
                            "input_device": self.args.input_device,
                            "output_device": self.args.output_device,
                        }
                    )
                    if not result.get("ok"):
                        print(result.get("error"), file=sys.stderr)
            self._loop()
        finally:
            if self.session is not None:
                self._finalize("complete")
            self._publish(force=True)
            if self.server is not None:
                self.server.shutdown()
                self.server.server_close()

    def start_session(self, body: dict[str, Any]) -> dict[str, Any]:
        if self.session is not None:
            return {"ok": False, "error": "A session is already running."}
        try:
            devices = query_audio_devices()
            input_device = resolve_live_device(body.get("input_device"), "input", devices)
            output_device = resolve_live_device(body.get("output_device"), "output", devices)
        except LiveControlError as exc:
            self.engine.set_error(str(exc))
            self._publish(force=True)
            return {"ok": False, "error": str(exc)}

        start_dt = datetime.now().astimezone()
        session_name = "hush_" + start_dt.strftime("%Y%m%d_%H%M%S")
        folder = Path(self.args.output) / start_dt.strftime("%Y-%m-%d") / session_name
        suffix = 2
        while folder.exists():
            folder = folder.with_name(f"{session_name}_{suffix}")
            suffix += 1
        folder.mkdir(parents=True)
        metadata: dict[str, Any] = {
            "session": folder.name,
            "started_at": start_dt.isoformat(),
            "timezone_note": "All wall times are local ISO-8601 with offset. "
            "Map handwritten clock times with: started_at + elapsed_seconds. "
            "Live mute events use input session samples as the clock.",
            "device_index": input_device["index"],
            "device_name": input_device["name"],
            "sample_rate_hz": int(self.args.samplerate),
            "channels": CHANNELS,
            "format": "16-bit PCM WAV",
            "chunk_minutes": self.args.chunk_minutes,
            "chunks": [],
            "warnings": [],
        }
        metadata_path = folder / "session.json"
        writer = WavSession(
            folder,
            int(self.args.samplerate),
            CHANNELS,
            start_dt,
            chunk_minutes=float(self.args.chunk_minutes),
        )
        self.session = {
            "folder": folder,
            "name": folder.name,
            "metadata": metadata,
            "metadata_path": metadata_path,
            "writer": writer,
            "markers": folder / "markers.jsonl",
            "started_at": start_dt,
            "mono": time.monotonic(),
        }
        (folder / "ad_times.txt").write_text(
            (
                f"# OHush ad time log for {folder.name}\n"
                f"# Session started: {start_dt.isoformat()}\n"
                "# Write wall-clock times from your phone/TV clock.\n"
                "#   14:12:05 ad start\n"
                "#   14:14:40 content back\n"
            ),
            encoding="utf-8",
        )
        try:
            self.hardware.start(
                input_device,
                output_device,
                int(self.args.samplerate),
                BLOCK_FRAMES,
            )
        except Exception as exc:
            self.engine.set_error(str(exc))
            self._finalize("error")
            self._publish(force=True)
            return {"ok": False, "error": str(exc)}

        self.engine.set_error(None)
        self._save_metadata()
        self._print_running()
        self._publish(force=True)
        return {"ok": True, "session": folder.name, "folder": str(folder)}

    def _loop(self) -> None:
        while not self.stop.is_set():
            commanded = self._drain_commands()
            session = self.session
            if (
                session is not None
                and self.args.seconds
                and (time.monotonic() - session["mono"]) >= float(self.args.seconds)
            ):
                self._finalize("complete")
                break
            self._health()
            wrote = self._drain_audio()
            now = time.monotonic()
            if session is not None and now - self._last_save >= 15:
                self._save_metadata()
                self._last_save = now
            if now - self._last_print >= 0.5:
                self._print_status()
                self._last_print = now
            if commanded or now - self._last_publish >= 0.1:
                self._publish()
                self._last_publish = now
            self._read_stdin()
            if not wrote:
                time.sleep(0.05)

    def _health(self) -> None:
        self.engine.tick()
        if self.session is None:
            return
        if self.engine.callback_stalled():
            self.engine.mark_stalled()
            self.engine.set_error("AUDIO ENGINE STALLED")
        elif self.engine.engine_stalled:
            self.engine.clear_stall()
            if self.engine.error == "AUDIO ENGINE STALLED":
                self.engine.set_error(None)
        now = time.monotonic()
        if now - self._last_device_poll < 1:
            return
        self._last_device_poll = now
        try:
            input_ok, output_ok = self.hardware.connected()
        except Exception as exc:
            self.engine.set_error(str(exc))
            return
        if input_ok and output_ok:
            return
        if not input_ok:
            self.engine.mark_disconnected("input")
            self.engine.set_error("INPUT DEVICE DISCONNECTED")
        if not output_ok:
            self.engine.mark_disconnected("output")
            if input_ok:
                self.engine.set_error("OUTPUT DEVICE DISCONNECTED")
        self._finalize("complete")

    def _drain_commands(self) -> bool:
        handled = False
        while True:
            try:
                name, body, box, done = self.commands.get_nowait()
            except queue.Empty:
                return handled
            try:
                box["result"] = self._handle(name, body)
            except Exception as exc:
                self.engine.fail_safe(str(exc))
                box["result"] = {"ok": False, "error": str(exc)}
            finally:
                done.set()
            handled = True

    def _handle(self, name: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            if name == "start":
                return self.start_session(body)
            if name == "stop":
                if self.session is None:
                    return {"ok": True, "stopped": False}
                self._finalize("complete")
                self._publish(force=True)
                return {"ok": True, "stopped": True}
            if name == "mode":
                self.engine.set_mode(str(body.get("mode") or ""))
                return {"ok": True, "mode": self.engine.mode}
            if name == "gate":
                action = str(body.get("action") or "")
                if action == "mute":
                    self.engine.mute()
                elif action == "unmute":
                    self.engine.unmute()
                elif action == "test_mute":
                    self.engine.test_mute(float(body.get("seconds") or 2))
                else:
                    return {
                        "ok": False,
                        "error": 'Use action "mute", "unmute", or "test_mute".',
                    }
                return {"ok": True, "gate": self.engine.gate}
            return {"ok": False, "error": f"Unknown command {name}."}
        except LiveControlError as exc:
            return {"ok": False, "error": str(exc)}

    def _drain_audio(self) -> bool:
        session = self.session
        if session is None:
            return False
        writer: WavSession = session["writer"]
        wrote = False
        while True:
            item = self.engine.pop_record()
            if item is None:
                break
            writer.write_block(item[0], item[1])
            wrote = True
        return wrote

    def _finalize(self, status: str) -> None:
        session = self.session
        if session is None:
            return
        self.hardware.close()
        self.engine.stop_transport()
        writer: WavSession = session["writer"]
        while True:
            item = self.engine.pop_record()
            if item is None:
                break
            writer.write_block(item[0], item[1])
        writer.finish(self.engine.session_samples)
        metadata = session["metadata"]
        metadata["chunks"] = writer.chunks
        metadata["ended_at"] = datetime.now().astimezone().isoformat()
        metadata["audio_seconds"] = round(writer.written / int(self.args.samplerate), 3)
        metadata["warnings"] = self.engine.warning_lines()
        metadata["status"] = status
        metadata["live_audio"] = self.engine.session_metadata()
        _save_json(session["metadata_path"], metadata)
        print(f"\nSaved: {session['folder']}")
        self.session = None
        self._publish(force=True)

    def _save_metadata(self) -> None:
        session = self.session
        if session is None:
            return
        writer: WavSession = session["writer"]
        metadata = session["metadata"]
        metadata["chunks"] = list(writer.chunks)
        metadata["warnings"] = self.engine.warning_lines()
        metadata["live_audio"] = self.engine.session_metadata()
        _save_json(session["metadata_path"], metadata)
        self._last_save = time.monotonic()

    def _publish(self, force: bool = False) -> None:
        if self.live is None:
            return
        if not force:
            self._last_publish = time.monotonic()
        snap = self.engine.snapshot()
        session = self.session
        self.live.update(
            **snap,
            recording=session is not None,
            pipeline="live",
            standby=session is None,
            chunk=session["writer"].chunk_no if session else 0,
            folder=str(session["folder"]) if session else None,
            session=session["name"] if session else None,
            warnings_count=len(self.engine.warning_lines()),
            monitor_url=f"http://{self.args.live_host}:{self.args.live_port}",
        )

    def _on_command(self, name: str, body: dict[str, Any]) -> dict[str, Any]:
        done = threading.Event()
        box: dict[str, Any] = {}
        self.commands.put((name, body, box, done))
        if not done.wait(5):
            return {"ok": False, "error": "Command timed out."}
        return box.get("result") or {"ok": False, "error": "No command result."}

    def _on_mark(self, kind: str, note: str | None) -> dict[str, Any] | None:
        normalized = kind
        if kind in ("a", "ad"):
            normalized = "ad_start"
        elif kind in ("c", "content"):
            normalized = "content_start"
        elif kind == "n":
            normalized = "note"
        if normalized not in ("ad_start", "content_start", "note"):
            return None
        if normalized == "note" and not (note or "").strip():
            return None
        return self._write_marker(normalized, note)

    def _write_marker(self, kind: str, note: str | None) -> dict[str, Any] | None:
        session = self.session
        if session is None or self.live is None:
            return None
        elapsed = round(self.engine.session_samples / self.engine.sample_rate, 3)
        marker = {
            "type": kind,
            "elapsed_seconds": elapsed,
            "wall_time": datetime.now().astimezone().isoformat(),
            "note": note,
        }
        with session["markers"].open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(marker) + "\n")
        self.live.append_marker(marker)
        print(f"\nMARKED {kind} at {elapsed}s")
        return marker

    def _read_stdin(self) -> None:
        if self.session is None:
            return
        try:
            readable, _, _ = select.select([sys.stdin], [], [], 0)
        except (OSError, ValueError):
            return
        if not readable:
            return
        text = sys.stdin.readline().strip()
        if not text:
            return
        kind, note = _parse_mark_text(text)
        if kind:
            self._write_marker(kind, note)
        else:
            print('\nUse "a", "c", or "n your note".')

    def _on_signal(self, *_args: Any) -> None:
        self.stop.set()

    def _print_banner(self) -> None:
        print("\nOHUSH LIVE")
        print("PASS-THROUGH keeps the gate open. Audio still runs through OHush.")
        print(f"Live:    http://{self.args.live_host}:{self.args.live_port}")
        print("Monitor: http://localhost:3010")
        if self.session is None:
            print("Choose the USB input and headphone output in the monitor.\n")

    def _print_running(self) -> None:
        session = self.session
        if session is None:
            return
        print(f"\nInput:   {self.engine.input_device_name}")
        print(f"Output:  {self.engine.output_device_name}")
        print(
            f"Format:  {self.args.samplerate} Hz, stereo, 16-bit PCM, "
            f"block {BLOCK_FRAMES} frames"
        )
        print(f"Folder:  {session['folder']}")
        print("Ctrl+C stops.\n")

    def _print_status(self) -> None:
        if self.session is None:
            return
        snap = self.engine.snapshot()
        transport = str(snap["transport"]).upper()
        if snap["transport"] == "priming":
            transport = f"PRIMING {snap['buffer_ms']:.0f}/{snap['buffer_target_ms']:.0f} ms"
        print(
            f"\r{snap['elapsed_seconds']:8.1f}s  "
            f"in {snap['input_dbfs']:6.1f}  "
            f"out {snap['output_dbfs']:6.1f}  "
            f"{snap['gate'].upper():6}  "
            f"{transport:22}  "
            f"buf {snap['buffer_ms']:5.1f} ms  "
            f"xruns {snap['xruns']}",
            end="",
            flush=True,
        )


def serve_live(args: Any) -> None:
    LiveHost(args).serve()

