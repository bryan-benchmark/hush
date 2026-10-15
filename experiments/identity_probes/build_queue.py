"""Cut short identity clips for the questions that still need an ear.

WAV files are local only. The manifest is what the /identity page plays.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import soundfile as sf

from hush.audio import RAW_SR, analysis_pieces, find_session, load_session, read_stereo, write_mono_wav

REPO = Path(__file__).resolve().parents[2]
RECORDINGS = REPO / "recordings"
LIVE = REPO / "ohush_live" / "sessions"
OUT = REPO / "experiments" / "identity_probes"
CLIP_S = 18.0
SILENCE_PEAK = 1e-3

GAME = [
    {"id": "game", "label": "Still the 49ers game"},
    {"id": "other", "label": "A different show"},
    {"id": "unsure", "label": "Can't tell"},
]
FOOTBALL = [
    {"id": "football", "label": "Football"},
    {"id": "other", "label": "Not football"},
    {"id": "unsure", "label": "Can't tell"},
]
SAME = [
    {"id": "same", "label": "Same game as the last clip"},
    {"id": "different_game", "label": "Football, a different game"},
    {"id": "other", "label": "Not football"},
    {"id": "unsure", "label": "Can't tell"},
]
SHOW = [
    {"id": "cable", "label": "Cable or antenna, one show, normal ads"},
    {"id": "no", "label": "Not that"},
    {"id": "unsure", "label": "Can't tell"},
]


def _clock(seconds: float) -> str:
    total = int(round(seconds))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _wall(start: datetime, seconds: float) -> str:
    moment = start + timedelta(seconds=seconds)
    return moment.strftime("%a %-I:%M %p").replace("AM", "am").replace("PM", "pm")


def _live_meta(folder: Path) -> tuple[dict, datetime]:
    wavs = sorted(folder.glob("audio_*.wav"))
    if not wavs:
        raise RuntimeError(f"no wavs in {folder}")
    chunks = []
    t = 0.0
    first_start = None
    for wav in wavs:
        info = sf.info(str(wav))
        if info.samplerate != RAW_SR or info.channels != 2:
            raise RuntimeError(f"unexpected format {wav}")
        dur = info.frames / info.samplerate
        end_wall = datetime.fromtimestamp(wav.stat().st_mtime)
        start_wall = end_wall - timedelta(seconds=dur)
        if first_start is None:
            first_start = start_wall
        chunks.append(
            {
                "file": wav.name,
                "seconds": dur,
                "start_elapsed_seconds": t,
                "end_elapsed_seconds": t + dur,
                "wall_start": start_wall.isoformat(timespec="seconds"),
            }
        )
        t += dur
    meta = {"sample_rate_hz": RAW_SR, "channels": 2, "chunks": chunks, "audio_seconds": t}
    return meta, first_start


def _wall_at(meta: dict, session_start: datetime | None, seconds: float) -> str:
    if session_start is not None and "wall_start" not in meta["chunks"][0]:
        return _wall(session_start, seconds)
    for chunk in meta["chunks"]:
        if chunk["start_elapsed_seconds"] <= seconds < chunk["end_elapsed_seconds"]:
            base = datetime.fromisoformat(chunk["wall_start"])
            return _wall(base, seconds - chunk["start_elapsed_seconds"])
    last = meta["chunks"][-1]
    base = datetime.fromisoformat(last["wall_start"])
    return _wall(base, seconds - last["start_elapsed_seconds"])


def _slice(session_dir: Path, meta: dict, center: float) -> tuple[float, np.ndarray]:
    audio_end = float(meta["chunks"][-1]["end_elapsed_seconds"])
    start = min(max(0.0, center - CLIP_S / 2), max(0.0, audio_end - CLIP_S))
    audio = _read(session_dir, meta, start)
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    if peak >= SILENCE_PEAK:
        return start, audio
    for delta in (30, 60, 90, 120):
        for candidate in (center + delta, center - delta):
            if candidate < 0 or candidate > audio_end:
                continue
            alt_start = min(max(0.0, candidate - CLIP_S / 2), max(0.0, audio_end - CLIP_S))
            alt = _read(session_dir, meta, alt_start)
            if alt.size and float(np.max(np.abs(alt))) >= SILENCE_PEAK:
                return alt_start, alt
    return start, audio


def _read(session_dir: Path, meta: dict, start: float) -> np.ndarray:
    pieces = analysis_pieces(session_dir, meta, start, start + CLIP_S)
    parts = [read_stereo(piece) for piece in pieces]
    audio = parts[0] if len(parts) == 1 else np.concatenate(parts)
    return audio.mean(axis=1) if audio.ndim == 2 else audio


def _add(clips: list[dict], *, session_dir: Path, meta: dict, session_start: datetime | None, center: float, group: str, ask: str, choices: list[dict], note: str) -> None:
    start, audio = _slice(session_dir, meta, center)
    clip_id = f"{group}-{len(clips)+1:02d}"
    dest = OUT / "clips" / f"{clip_id}.wav"
    write_mono_wav(dest, audio, RAW_SR)
    clips.append(
        {
            "id": clip_id,
            "file": f"clips/{clip_id}.wav",
            "session": session_dir.name,
            "start_seconds": round(start, 3),
            "clock": _clock(start),
            "wall": _wall_at(meta, session_start, start),
            "group": group,
            "ask": ask,
            "note": note,
            "choices": choices,
        }
    )


def main() -> None:
    clips: list[dict] = []

    netflix = find_session(RECORDINGS, "hush_20260910_205330")
    netflix_meta = load_session(netflix)
    netflix_start = datetime.fromisoformat(netflix_meta["started_at"])
    for center, note in (
        (20 * 60, "Early in the Netflix capture."),
        (90 * 60, "Around 90 minutes, last time this was heard as football."),
        (135 * 60, "Looking for the handoff out of the game."),
        (180 * 60, "Looking for the handoff out of the game."),
        (225 * 60, "Looking for the handoff out of the game."),
        (270 * 60, "Looking for the handoff out of the game."),
        (360 * 60, "Well after a normal game length."),
        (495 * 60, "Late in the 9-hour file."),
    ):
        _add(
            clips,
            session_dir=netflix,
            meta=netflix_meta,
            session_start=netflix_start,
            center=center,
            group="netflix",
            ask="Is this still the 49ers game?",
            choices=GAME,
            note=note,
        )

    oct11 = LIVE / "2026-10-11-tnf"
    oct11_meta, _ = _live_meta(oct11)
    # Sunday block is the first ~4.0 h. Monday starts after the 19-hour wall gap.
    for center, note in (
        (5 * 60, "Sunday night. This folder is labeled MNF."),
        (2 * 3600, "Sunday night, two hours later."),
        (3.75 * 3600, "End of the Sunday-night block, about 1am."),
        (4.1 * 3600, "Monday night. Same folder, after a 19-hour gap."),
        (5.5 * 3600, "Monday night, middle of that block."),
        (7.2 * 3600, "Monday night, near the end."),
    ):
        _add(
            clips,
            session_dir=oct11,
            meta=oct11_meta,
            session_start=None,
            center=center,
            group="oct11",
            ask="What is playing?",
            choices=FOOTBALL if center < 10 * 60 else SAME,
            note=note,
        )

    oct10 = LIVE / "2026-10-10-tnf"
    oct10_meta, _ = _live_meta(oct10)
    for center, note in (
        (5 * 60, "Saturday night. This folder is labeled Browns at Jets."),
        (90 * 60, "Saturday night, near the end of that block."),
        (2.1 * 3600, "Sunday afternoon. Same folder, after a 14-hour gap."),
        (2.9 * 3600, "Sunday afternoon, near the end of that block."),
    ):
        _add(
            clips,
            session_dir=oct10,
            meta=oct10_meta,
            session_start=None,
            center=center,
            group="oct10",
            ask="What is playing?",
            choices=FOOTBALL if center < 10 * 60 else SAME,
            note=note,
        )

    short = find_session(RECORDINGS, "hush_20260827_214906")
    short_meta = load_session(short)
    _add(
        clips,
        session_dir=short,
        meta=short_meta,
        session_start=datetime.fromisoformat(short_meta["started_at"]),
        center=300,
        group="cable",
        ask="Is this the missing cable show?",
        choices=SHOW,
        note="Aug 27, about 10 minutes, scripted. No show or channel named yet.",
    )

    sep1 = find_session(RECORDINGS, "hush_20260901_221145")
    sep1_meta = load_session(sep1)
    for center, note in (
        (2 * 60, "Sep 1, start of the hour."),
        (25 * 60, "Sep 1, middle of the hour."),
        (50 * 60, "Sep 1, late in the hour. Family Guy and Desperate Housewives were both heard in this file."),
    ):
        _add(
            clips,
            session_dir=sep1,
            meta=sep1_meta,
            session_start=datetime.fromisoformat(sep1_meta["started_at"]),
            center=center,
            group="cable",
            ask="Is this the missing cable show?",
            choices=SHOW,
            note=note,
        )

    rick = find_session(RECORDINGS, "hush_20260912_215850")
    rick_meta = load_session(rick)
    _add(
        clips,
        session_dir=rick,
        meta=rick_meta,
        session_start=datetime.fromisoformat(rick_meta["started_at"]),
        center=30 * 60,
        group="cable",
        ask="Is this the missing cable show?",
        choices=SHOW,
        note="Sep 12. Previously heard as a Rick and Morty stream with no ads.",
    )

    manifest = {
        "purpose": "identity probes only. not commercial boundaries.",
        "clip_seconds": CLIP_S,
        "clips": clips,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(clips)} clips")


if __name__ == "__main__":
    main()
