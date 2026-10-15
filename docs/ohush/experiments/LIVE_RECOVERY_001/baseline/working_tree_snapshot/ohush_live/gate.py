"""Listener gate. The recording path never reads this output."""

from __future__ import annotations

import math
import threading

import numpy as np

from ohush_live.sports import DEFAULT_REPLACEMENT


class ListenerGate:
    def __init__(self, beds: dict[str, np.ndarray], earcon: np.ndarray, prime_frames: int = 9600) -> None:
        self.mode = "program"
        self.replacement = DEFAULT_REPLACEMENT
        self.auto = True
        self._prime = prime_frames
        # Keep only a little slack past prime. Separate in/out streams used to
        # let the ring grow to 4x prime (~800 ms) and lip-sync fell apart.
        self._cap = prime_frames * 2
        self._slack = max(2048, prime_frames // 4)
        self._ring = np.zeros((self._cap, 2), dtype=np.int16)
        self._read = 0
        self._write = 0
        self._count = 0
        self._beds = beds
        # Whole-bed RMS so quiet intros (rain fade-in) do not starve the gain stage.
        self._bed_rms = {
            name: float(np.sqrt(np.mean(np.square(audio.astype(np.float64) / 32768.0)))) or 1e-6
            for name, audio in beds.items()
        }
        self._pos = 0
        self._earcon = earcon
        self._earcon_at = 0
        self._earcon_left = 0
        self.input_peak = 0
        self._input_rms = 0.0
        self._match_rms = 0.10
        self._dropped = 0
        self._idx = np.arange(16384)
        self._lock = threading.Lock()

    def push(self, frames: np.ndarray) -> None:
        audio = np.ascontiguousarray(frames, dtype=np.int16)
        if audio.ndim != 2 or audio.shape[1] != 2 or audio.shape[0] == 0:
            return
        with self._lock:
            self.input_peak = int(np.max(np.abs(audio)))
            # Cheap RMS from int16 — avoid float cast of every sample in the callback.
            block_rms = float(np.sqrt(np.mean(np.square(audio.astype(np.float32))))) / 32768.0
            # Fast rise / slow fall so we lock onto TV loudness without chasing dips.
            alpha = 0.35 if block_rms >= self._input_rms else 0.05
            self._input_rms = ((1.0 - alpha) * self._input_rms) + (alpha * block_rms)
            # Follow the TV level while program is live; freeze that target on mute
            # so a loud commercial does not shove the bed up further mid-break.
            if self.mode == "program" and self._input_rms > 0.01:
                self._match_rms = self._input_rms
            self._write_ring(audio)
            # Drop oldest samples when input outruns output so delay stays near prime.
            self._discard_down_to(self._prime + self._slack)

    def render(self, out: np.ndarray) -> None:
        count = out.shape[0]
        with self._lock:
            if self.mode == "program":
                taken = self._take(count)
                if taken is None:
                    out.fill(0)
                else:
                    out[:] = taken
            else:
                self._discard_down_to(self._prime)
                self._fill_bed(out)
                self._mix_earcon(out)

    def play_program(self) -> str:
        with self._lock:
            prior = self.mode
            self.mode = "program"
            return prior

    def play_replacement(self) -> str:
        with self._lock:
            prior = self.mode
            self.mode = "replacement"
            return prior

    def set_replacement(self, name: str) -> str:
        with self._lock:
            self.replacement = name
            self._pos = 0
            return self.replacement

    def cycle_replacement(self) -> str:
        with self._lock:
            from ohush_live.sports import next_replacement

            self.replacement = next_replacement(self.replacement)
            self._pos = 0
            return self.replacement

    def cue_return(self) -> None:
        with self._lock:
            self._earcon_at = 0
            self._earcon_left = len(self._earcon)

    def input_dbfs(self) -> float:
        with self._lock:
            peak = self.input_peak
        if peak <= 0:
            return -100.0
        return 20.0 * math.log10(peak / 32768.0)

    def lag_ms(self, rate: int = 48000) -> float:
        with self._lock:
            return 1000.0 * self._count / float(rate)

    def dropped_frames(self) -> int:
        with self._lock:
            return self._dropped

    def _write_ring(self, audio: np.ndarray) -> None:
        count = audio.shape[0]
        if count >= self._cap:
            audio = audio[-self._cap :]
            count = audio.shape[0]
        end = self._write + count
        if end <= self._cap:
            self._ring[self._write:end] = audio
        else:
            first = self._cap - self._write
            self._ring[self._write:] = audio[:first]
            self._ring[: count - first] = audio[first:]
        self._write = end % self._cap
        self._count = min(self._cap, self._count + count)
        if self._count == self._cap:
            self._read = self._write

    def _take(self, count: int) -> np.ndarray | None:
        if self._count < max(self._prime, count):
            return None
        return self._read_from_ring(count)

    def _discard_down_to(self, keep: int) -> None:
        extra = self._count - keep
        if extra <= 0:
            return
        self._read = (self._read + extra) % self._cap
        self._count -= extra
        self._dropped += extra

    def _read_from_ring(self, count: int) -> np.ndarray:
        end = self._read + count
        if end <= self._cap:
            taken = self._ring[self._read:end].copy()
        else:
            first = self._cap - self._read
            taken = np.concatenate([self._ring[self._read:], self._ring[: count - first]])
        self._read = end % self._cap
        self._count -= count
        return taken

    def _fill_bed(self, out: np.ndarray) -> None:
        bed = self._beds[self.replacement]
        count = out.shape[0]
        idx = (self._idx[:count] + self._pos) % len(bed)
        chunk = bed[idx]
        self._pos = (self._pos + count) % len(bed)
        if self.replacement == "silence":
            out.fill(0)
            return
        # Match bed loudness to the recent program level so cover sounds track the TV.
        bed_rms = self._bed_rms.get(self.replacement, 0.1)
        target = max(0.05, min(0.28, self._match_rms))
        gain = min(8.0, target / bed_rms)
        scaled = np.rint(chunk.astype(np.float64) * gain)
        out[:] = np.clip(scaled, -32768, 32767).astype(np.int16)

    def _mix_earcon(self, out: np.ndarray) -> None:
        if self._earcon_left <= 0:
            return
        count = min(out.shape[0], self._earcon_left)
        piece = self._earcon[self._earcon_at : self._earcon_at + count]
        mixed = out[:count].astype(np.int32) + piece.astype(np.int32)
        out[:count] = np.clip(mixed, -32768, 32767).astype(np.int16)
        self._earcon_at += count
        self._earcon_left -= count
