"""Point the labeler at the October live-desk captures as separate sittings.

The desk saved Thursday, Saturday, Sunday night, and Monday night under
ohush_live/sessions/, and it kept writing Monday into the Sunday folder.
This builds recordings/ sessions the labeler already knows how to open.
Audio stays where it was. Each chunk is a symlink. Elapsed time is the
captured audio in birth order. Wall-clock gaps are named, not filled.
"""

from __future__ import annotations

import json
import wave
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LIVE = REPO / "ohush_live" / "sessions"
RECORDINGS = REPO / "recordings"
OFFSET = timezone(timedelta(hours=-4))
MIN_SECONDS = 0.5

SITTINGS = [
    {
        "session": "hush_20261008_205100",
        "day": "2026-10-08",
        "source": "2026-10-08-tnf",
        "show": "Bucs at Cowboys",
        "service": "Prime Video",
        "delivery": "tv-optical",
        "content_type": "sports",
        "title": "Thu Oct 8 · Prime · Bucs at Cowboys",
        "after": None,
        "before": None,
    },
    {
        "session": "hush_20261010_222400",
        "day": "2026-10-10",
        "source": "2026-10-10-tnf",
        "show": "Browns at Jets",
        "service": "Cable / antenna",
        "delivery": "tv-optical",
        "content_type": "sports",
        "title": "Sat Oct 10 · cable · Browns at Jets",
        "after": None,
        "before": "2026-10-11T12:00:00-04:00",
    },
    {
        "session": "hush_20261011_135700",
        "day": "2026-10-11",
        "source": "2026-10-10-tnf",
        "show": "Sunday afternoon football",
        "service": "Cable / antenna",
        "delivery": "tv-optical",
        "content_type": "sports",
        "title": "Sun Oct 11 afternoon · cable",
        "after": "2026-10-11T12:00:00-04:00",
        "before": None,
    },
    {
        "session": "hush_20261011_204300",
        "day": "2026-10-11",
        "source": "2026-10-11-tnf",
        "show": "Sunday night",
        "service": "Cable / antenna",
        "delivery": "tv-optical",
        "content_type": "sports",
        "title": "Sun Oct 11 night",
        "after": None,
        "before": "2026-10-12T12:00:00-04:00",
    },
    {
        "session": "hush_20261012_204200",
        "day": "2026-10-12",
        "source": "2026-10-11-tnf",
        "show": "Monday Night Football",
        "service": "Cable / antenna",
        "delivery": "tv-optical",
        "content_type": "sports",
        "title": "Mon Oct 12 · Monday Night Football",
        "after": "2026-10-12T12:00:00-04:00",
        "before": None,
    },
]


def local(ts: float) -> datetime:
    return datetime.fromtimestamp(ts, OFFSET)


def iso(dt: datetime) -> str:
    return dt.isoformat()


def duration_s(path: Path) -> float:
    with wave.open(str(path), "rb") as handle:
        rate = handle.getframerate()
        if rate <= 0:
            return 0.0
        return handle.getnframes() / float(rate)


def sitting_files(spec: dict) -> list[Path]:
    folder = LIVE / spec["source"]
    after = datetime.fromisoformat(spec["after"]) if spec["after"] else None
    before = datetime.fromisoformat(spec["before"]) if spec["before"] else None
    chosen = []
    for path in sorted(folder.glob("audio_*.wav")):
        born = local(path.stat().st_birthtime)
        if after and born < after:
            continue
        if before and born >= before:
            continue
        if duration_s(path) < MIN_SECONDS:
            continue
        chosen.append(path)
    chosen.sort(key=lambda path: path.stat().st_birthtime)
    return chosen


def build(spec: dict) -> dict:
    files = sitting_files(spec)
    if not files:
        raise SystemExit(f"no audio for {spec['session']}")
    dest = RECORDINGS / spec["day"] / spec["session"]
    if dest.exists():
        for child in dest.iterdir():
            if child.is_symlink() or child.is_file():
                child.unlink()
    dest.mkdir(parents=True, exist_ok=True)
    chunks = []
    elapsed = 0.0
    gaps = []
    previous_end = None
    for source in files:
        seconds = round(duration_s(source), 3)
        born = local(source.stat().st_birthtime)
        ended = born + timedelta(seconds=seconds)
        if previous_end is not None:
            hole = (born - previous_end).total_seconds()
            if hole > 60:
                gaps.append(
                    {
                        "after_elapsed_s": round(elapsed, 3),
                        "wall_gap_s": round(hole, 1),
                        "resumes": iso(born),
                    }
                )
        link = dest / source.name
        link.symlink_to(source.resolve())
        chunks.append(
            {
                "file": source.name,
                "seconds": seconds,
                "start_elapsed_seconds": round(elapsed, 3),
                "end_elapsed_seconds": round(elapsed + seconds, 3),
                "started_at": iso(born),
                "ended_at": iso(ended),
            }
        )
        elapsed += seconds
        previous_end = ended
    started = chunks[0]["started_at"]
    meta = {
        "session": spec["session"],
        "started_at": started,
        "ended_at": chunks[-1]["ended_at"],
        "audio_seconds": round(elapsed, 3),
        "timezone_note": "Elapsed time is captured audio in birth order. started_at on each chunk is when that file was opened. A wall-clock gap is listed in gaps and is not silent audio inside the file.",
        "sample_rate_hz": 48000,
        "channels": 2,
        "format": "16-bit PCM WAV",
        "chunk_minutes": 15,
        "show": spec["show"],
        "service": spec["service"],
        "delivery": spec["delivery"],
        "content_type": spec["content_type"],
        "source_folder": f"ohush_live/sessions/{spec['source']}",
        "dataset_role": "dev",
        "scientific_authority": False,
        "gaps": gaps,
        "chunks": chunks,
    }
    (dest / "session.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return {
        "session": spec["session"],
        "title": spec["title"],
        "day": spec["day"],
        "show": spec["show"],
        "service": spec["service"],
        "started_at": started,
        "audio_seconds": meta["audio_seconds"],
        "chunks": len(chunks),
        "gaps": gaps,
        "source_folder": meta["source_folder"],
    }


def main() -> None:
    built = [build(spec) for spec in SITTINGS]
    out = REPO / "experiments" / "gold" / "live_label_sessions.json"
    out.write_text(
        json.dumps(
            {
                "id": "LIVE_LABEL_SESSIONS",
                "note": "Symlinked sittings for the labeler. Audio remains in ohush_live/sessions. Not interval gold.",
                "sittings": built,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps(built, indent=2))


if __name__ == "__main__":
    main()
