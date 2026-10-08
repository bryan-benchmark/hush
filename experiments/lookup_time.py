#!/usr/bin/env python3
"""
Lookup a handwritten wall-clock time inside an OHush session.

Examples:
  python experiments/lookup_time.py 14:12:05
  python experiments/lookup_time.py 2:12:05 PM
  python experiments/lookup_time.py --session recordings/2026-08-27/hush_20260827_135935 15:01:20
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path


def parse_clock(text: str, session_start: datetime) -> datetime:
    text = text.strip()
    # Full ISO
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        pass

    # HH:MM:SS or H:MM:SS with optional AM/PM
    m = re.match(
        r"^(\d{1,2}):(\d{2})(?::(\d{2}))?\s*(AM|PM|am|pm)?$",
        text,
    )
    if not m:
        raise SystemExit(f"Could not parse time: {text!r}")

    h = int(m.group(1))
    mi = int(m.group(2))
    s = int(m.group(3) or 0)
    ampm = m.group(4)
    if ampm:
        ampm = ampm.upper()
        if ampm == "PM" and h != 12:
            h += 12
        if ampm == "AM" and h == 12:
            h = 0

    return session_start.replace(
        hour=h, minute=mi, second=s, microsecond=0
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("time", help="Wall clock time, e.g. 14:12:05 or 2:12:05 PM")
    ap.add_argument(
        "--session",
        default="recordings/2026-08-27/hush_20260827_135935",
    )
    args = ap.parse_args()

    session = Path(args.session)
    meta = json.loads((session / "session.json").read_text(encoding="utf-8"))
    start = datetime.fromisoformat(meta["started_at"])
    target = parse_clock(args.time, start)
    elapsed = (target - start).total_seconds()

    if elapsed < 0:
        raise SystemExit(
            f"{target.isoformat()} is before session start {start.isoformat()}"
        )

    # Prefer stamped chunks; else assume 15-min files in order
    chunks = meta.get("chunks") or []
    if not chunks:
        wavs = sorted(session.glob("audio_*.wav"))
        chunk_minutes = float(meta.get("chunk_minutes") or 15)
        offset = 0.0
        for w in wavs:
            chunks.append(
                {
                    "file": w.name,
                    "seconds": chunk_minutes * 60,
                    "start_elapsed_seconds": offset,
                }
            )
            offset += chunk_minutes * 60

    # Backfill offsets if missing
    running = 0.0
    for c in chunks:
        if "start_elapsed_seconds" not in c:
            c["start_elapsed_seconds"] = running
        running = c["start_elapsed_seconds"] + float(c.get("seconds") or 0)

    hit = None
    for c in chunks:
        a = float(c["start_elapsed_seconds"])
        b = a + float(c["seconds"])
        if a <= elapsed < b or (
            c is chunks[-1] and abs(elapsed - b) < 0.5
        ):
            hit = c
            local = elapsed - a
            break

    print(f"Session start: {start.isoformat()}")
    print(f"Your time:     {target.isoformat()}")
    print(f"Elapsed:       {elapsed:.3f}s  ({elapsed/60:.2f} min)")
    if not hit:
        print("Not inside recorded audio range.")
        return

    local = elapsed - float(hit["start_elapsed_seconds"])
    print(f"File:          {hit['file']}")
    print(f"In-file:       {local:.3f}s")
    if hit.get("started_at"):
        print(f"Chunk window:  {hit['started_at']} → {hit.get('ended_at')}")


if __name__ == "__main__":
    main()
