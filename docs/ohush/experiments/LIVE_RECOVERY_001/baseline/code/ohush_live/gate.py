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
        self._cap = prime_frames * 4
        self._ring = np.zeros((self._cap, 2), dtype=np.int16)
        self._read = 0
        self._write = 0
        self._count = 0
        self._beds = beds
        self._pos = 0
        self._earcon = earcon
        self._earcon_at = 0
        self._earcon_left = 0
        self.input_peak = 0
        self._idx = np.arange(16384)
        self._lock = threading.Lock()

    def push(self, frames: np.ndarray) -> None:
        audio = np.ascontiguousarray(frames, dtype=np.int16)
        if audio.ndim != 2 or audio.shape[1] != 2 or audio.shape[0] == 0:
            return
        with self._lock:
            self.input_peak = int(np.max(np.abs(audio)))
            self._write_ring(audio)

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
                self._discard_down_to_prime()
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

    def _discard_down_to_prime(self) -> None:
        extra = self._count - self._prime
        if extra <= 0:
            return
        self._read = (self._read + extra) % self._cap
        self._count -= extra

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
        out[:] = bed[idx]
        self._pos = (self._pos + count) % len(bed)

    def _mix_earcon(self, out: np.ndarray) -> None:
        if self._earcon_left <= 0:
            return
        count = min(out.shape[0], self._earcon_left)
        piece = self._earcon[self._earcon_at : self._earcon_at + count]
        mixed = out[:count].astype(np.int32) + piece.astype(np.int32)
        out[:count] = np.clip(mixed, -32768, 32767).astype(np.int16)
        self._earcon_at += count
        self._earcon_left -= count
