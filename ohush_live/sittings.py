"""One TV sitting, one labeler session.

A start within half an hour, with the same name and provider, continues
that recording and marks the hole. A later start, or a different name,
is a new session under recordings/. Elapsed time is captured audio.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

CONTINUE_WITHIN_S = 30 * 60
GAP_NOTE_S = 60


def _norm(value: object) -> str:
    return str(value or "").strip().casefold()


def parse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def gap_seconds(active: dict | None, now: datetime) -> float | None:
    if not active:
        return None
    then = parse_time(active.get("last_audio_at") or active.get("updated_at"))
    if then is None:
        return None
    if then.tzinfo is None and now.tzinfo is not None:
        then = then.replace(tzinfo=now.tzinfo)
    return (now - then).total_seconds()


def should_continue(
    active: dict | None,
    *,
    show: str,
    service: str,
    content: str,
    now: datetime,
    fresh: bool,
) -> bool:
    """True when this start should append to the sitting already on disk."""
    if fresh or not active:
        return False
    folder = active.get("folder")
    if not isinstance(folder, str) or not folder:
        return False
    path = Path(folder)
    if path.name.startswith(".") or not path.is_dir() or not (path / "session.json").is_file():
        return False
    if _norm(active.get("show")) != _norm(show):
        return False
    if _norm(active.get("service")) != _norm(service):
        return False
    if _norm(active.get("content") or "sports") != _norm(content or "sports"):
        return False
    gap = gap_seconds(active, now)
    if gap is None or gap < -5 or gap > CONTINUE_WITHIN_S:
        return False
    return True


def new_sitting_dir(recordings: Path, when: datetime) -> Path:
    day = recordings / when.strftime("%Y-%m-%d")
    day.mkdir(parents=True, exist_ok=True)
    stem = when.strftime("hush_%Y%m%d_%H%M%S")
    dest = day / stem
    suffix = 2
    while dest.exists():
        dest = day / f"{stem}_{suffix}"
        suffix += 1
    dest.mkdir()
    return dest


def append_chunk(
    meta: dict,
    *,
    file: str,
    seconds: float,
    opened_at: datetime,
    closed_at: datetime,
) -> None:
    """Add one closed WAV. Elapsed time skips wall-clock holes longer than a minute."""
    chunks = meta.setdefault("chunks", [])
    if not isinstance(chunks, list):
        chunks = []
        meta["chunks"] = chunks
    if any(isinstance(row, dict) and row.get("file") == file for row in chunks):
        return
    elapsed = 0.0
    if chunks and isinstance(chunks[-1], dict):
        elapsed = float(chunks[-1].get("end_elapsed_seconds") or 0.0)
        previous = parse_time(chunks[-1].get("ended_at"))
        if previous is not None:
            if previous.tzinfo is None and opened_at.tzinfo is not None:
                previous = previous.replace(tzinfo=opened_at.tzinfo)
            hole = (opened_at - previous).total_seconds()
            if hole > GAP_NOTE_S:
                gaps = meta.setdefault("gaps", [])
                if not isinstance(gaps, list):
                    gaps = []
                    meta["gaps"] = gaps
                gaps.append(
                    {
                        "after_elapsed_s": round(elapsed, 3),
                        "wall_gap_s": round(hole, 1),
                        "resumes": opened_at.isoformat(),
                    }
                )
    seconds = round(float(seconds), 3)
    chunks.append(
        {
            "file": file,
            "seconds": seconds,
            "start_elapsed_seconds": round(elapsed, 3),
            "end_elapsed_seconds": round(elapsed + seconds, 3),
            "started_at": opened_at.isoformat(),
            "ended_at": closed_at.isoformat(),
        }
    )
    meta["audio_seconds"] = round(elapsed + seconds, 3)
    meta["ended_at"] = closed_at.isoformat()
    meta["label_queue"] = True
