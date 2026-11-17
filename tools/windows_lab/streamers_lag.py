"""Streamers lags a lot — watch for it in capture + farm record.

The app already lags on one BlueStacks instance. A third concurrent instance
makes it worse. gdigrab fails when the window drops; UI dumps go stale mid-tap.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import ensure_data_layout
from .instances import find_window_title

# Soft caps for this PC. Two clean; never plan a third while lag is hot.
CLEAN_CONCURRENT = 2
LAG_RETRY_TRIES = 6
LAG_RETRY_SLEEP_SEC = 5.0
STILL_YIELD_FLOOR = 0.55  # stills vs expected before warn
DURATION_FLOOR = 0.70  # actual vs requested before warn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def wait_for_window(
    pattern: str,
    *,
    tries: int = LAG_RETRY_TRIES,
    sleep_sec: float = LAG_RETRY_SLEEP_SEC,
) -> tuple[str | None, list[str]]:
    """Re-resolve BlueStacks title; wait out Streamers lag before giving up."""
    notes: list[str] = []
    for i in range(max(1, tries)):
        title = find_window_title(pattern)
        if title:
            if i:
                notes.append(f"window_recovered_after_{i * sleep_sec:.0f}s_lag_wait")
            return title, notes
        if i + 1 < tries:
            notes.append(f"window_missing_try_{i + 1}")
            time.sleep(sleep_sec)
    notes.append("window_lost_after_lag_waits")
    return None, notes


def assess_session_lag(
    meta: dict[str, Any] | None,
    *,
    still_count: int | None = None,
) -> dict[str, Any]:
    """Score a finished (or in-progress) session for Streamers lag damage."""
    meta = meta or {}
    warnings = [str(w) for w in (meta.get("warnings") or [])]
    requested_min = float(meta.get("requested_minutes") or 0.0)
    interval = float(meta.get("still_interval_sec") or 1.0) or 1.0
    chunks = list(meta.get("chunks") or [])
    stills = still_count
    if stills is None:
        stills = int((meta.get("visual_archive") or {}).get("still_count") or 0)
        if not stills:
            stills = sum(int(c.get("stills") or 0) for c in chunks)

    start = meta.get("capture_utc_start")
    end = meta.get("capture_utc_end")
    actual_sec = 0.0
    if start and end:
        try:
            t0 = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
            t1 = datetime.fromisoformat(str(end).replace("Z", "+00:00"))
            actual_sec = max(0.0, (t1 - t0).total_seconds())
        except ValueError:
            actual_sec = 0.0
    if not actual_sec:
        actual_sec = sum(float(c.get("duration_sec") or 0.0) for c in chunks)

    requested_sec = requested_min * 60.0
    expected_stills = int(requested_sec / interval) if requested_sec > 0 else 0
    duration_ratio = (actual_sec / requested_sec) if requested_sec > 0 else 1.0
    still_ratio = (stills / expected_stills) if expected_stills > 0 else 1.0

    zero_still_chunks = sum(1 for c in chunks if int(c.get("stills") or 0) == 0 and "audio" not in c)
    # Count empty still chunks even when audio merged in
    empty_visual = sum(1 for c in chunks if int(c.get("stills") or 0) == 0)
    window_errs = [
        w
        for w in warnings
        if "Can't find window" in w
        or "window_lost" in w
        or "stills_chunk_" in w
        or "Error opening input" in w
    ]

    signals: list[str] = []
    if window_errs:
        signals.append("window_grab_failed")
    if empty_visual:
        signals.append(f"empty_still_chunks={empty_visual}")
    if requested_sec > 60 and duration_ratio < DURATION_FLOOR:
        signals.append(f"short_session ratio={duration_ratio:.2f}")
    if expected_stills >= 30 and still_ratio < STILL_YIELD_FLOOR:
        signals.append(f"still_shortfall ratio={still_ratio:.2f}")
    for w in warnings:
        if "lag" in w.lower():
            signals.append(w)

    if window_errs or (requested_sec > 60 and duration_ratio < 0.4) or still_ratio < 0.25:
        level = "critical"
    elif signals:
        level = "warn"
    else:
        level = "ok"

    return {
        "level": level,
        "signals": signals,
        "requested_sec": round(requested_sec, 1),
        "actual_sec": round(actual_sec, 1),
        "duration_ratio": round(duration_ratio, 3),
        "still_count": stills,
        "expected_stills": expected_stills,
        "still_ratio": round(still_ratio, 3),
        "empty_still_chunks": empty_visual,
        "zero_still_chunks_legacy": zero_still_chunks,
        "guidance": _guidance(level),
    }


def _guidance(level: str) -> str:
    if level == "critical":
        return (
            "Streamers lag / window loss wrecked this take. "
            "Keep ≤2 instances, wait for picture, fresh UI dump before taps, "
            "prefer device screenrecord probes; retry shorter chunk."
        )
    if level == "warn":
        return (
            "Streamers lag symptoms. Do not add a third instance. "
            "Wait+re-dump before channel changes; watch still yield."
        )
    return "Lag watch clear on this take. Still assume Streamers can stutter anytime."


def scan_recent_lag(
    root: Path | None = None,
    *,
    limit: int = 12,
) -> dict[str, Any]:
    """Summarize lag on recent streamers sessions under authorized_sources."""
    root = ensure_data_layout(root)
    src = root / "authorized_sources"
    rows: list[dict[str, Any]] = []
    if src.is_dir():
        dirs = sorted(
            [p for p in src.iterdir() if p.is_dir() and p.name.startswith("streamers_")],
            key=lambda p: p.name,
            reverse=True,
        )[:limit]
        for d in dirs:
            meta_path = d / "meta.json"
            if not meta_path.is_file():
                continue
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            assess = meta.get("streamers_lag") or assess_session_lag(meta)
            rows.append(
                {
                    "session_id": meta.get("session_id") or d.name,
                    "channel_id": meta.get("channel_id"),
                    "level": assess.get("level"),
                    "signals": assess.get("signals") or [],
                    "still_ratio": assess.get("still_ratio"),
                    "duration_ratio": assess.get("duration_ratio"),
                }
            )

    levels = [r["level"] for r in rows]
    if "critical" in levels:
        overall = "critical"
    elif "warn" in levels:
        overall = "warn"
    else:
        overall = "ok"

    hot = overall in {"warn", "critical"}
    return {
        "checked_utc": _now(),
        "overall": overall,
        "sessions_scanned": len(rows),
        "recent": rows,
        "rule": (
            "Streamers lags on one instance already. Cap concurrent at "
            f"{CLEAN_CONCURRENT}. Never open a third while lag overall is warn/critical."
        ),
        "max_concurrent_while_hot": CLEAN_CONCURRENT if hot else CLEAN_CONCURRENT,
        "avoid_third_instance": True,
        "ui_ops": "Wait. Dump. If texts ≠ screenshot, wait and dump again before any tap.",
    }


def attach_lag_to_meta(meta: dict[str, Any], *, still_count: int | None = None) -> dict[str, Any]:
    """Mutate meta with streamers_lag assessment."""
    assess = assess_session_lag(meta, still_count=still_count)
    meta["streamers_lag"] = assess
    if assess["level"] != "ok":
        tag = f"streamers_lag:{assess['level']}"
        warns = list(meta.get("warnings") or [])
        if tag not in warns:
            warns.append(tag)
            meta["warnings"] = warns
    return assess
