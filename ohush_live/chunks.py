"""15-minute raw chunks. The open file is never handed to the uploader."""

from __future__ import annotations

import wave
from datetime import datetime
from pathlib import Path


class ChunkWriter:
    def __init__(
        self,
        folder: Path,
        frames_per_chunk: int,
        rate: int = 48000,
        channels: int = 2,
        start_number: int = 0,
    ) -> None:
        self.folder = folder
        self.frames_per_chunk = frames_per_chunk
        self.rate = rate
        self.channels = channels
        self.number = start_number
        self.frames = 0
        self.path: Path | None = None
        self.opened_at: dict[str, datetime] = {}
        self._wav: wave.Wave_write | None = None
        folder.mkdir(parents=True, exist_ok=True)
        self._open_next()

    def write(self, pcm: bytes) -> list[Path]:
        if not pcm:
            return []
        frame_bytes = self.channels * 2
        if len(pcm) % frame_bytes != 0:
            raise ValueError("pcm is not a whole number of stereo frames")
        view = memoryview(pcm)
        offset = 0
        closed: list[Path] = []
        while offset < len(view):
            room = self.frames_per_chunk - self.frames
            take = min(room * frame_bytes, len(view) - offset)
            assert self._wav is not None
            self._wav.writeframes(view[offset : offset + take])
            self.frames += take // frame_bytes
            offset += take
            if self.frames >= self.frames_per_chunk:
                closed.append(self._close_full())
                self._open_next()
        return closed

    def close(self) -> Path | None:
        if self._wav is None or self.path is None:
            return None
        path = self.path
        frames = self.frames
        self._wav.close()
        self._wav = None
        self.path = None
        if frames == 0:
            path.unlink(missing_ok=True)
            return None
        return path

    def _open_next(self) -> None:
        self.number += 1
        self.frames = 0
        self.path = self.folder / f"audio_{self.number:04d}.wav"
        self.opened_at[self.path.name] = datetime.now().astimezone()
        handle = wave.open(str(self.path), "wb")
        handle.setnchannels(self.channels)
        handle.setsampwidth(2)
        handle.setframerate(self.rate)
        self._wav = handle

    def _close_full(self) -> Path:
        assert self._wav is not None and self.path is not None
        path = self.path
        self._wav.close()
        self._wav = None
        return path
