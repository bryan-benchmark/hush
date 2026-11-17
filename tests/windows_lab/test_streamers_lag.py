"""Streamers lag watch scoring."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from tools.windows_lab.config import ensure_data_layout
from tools.windows_lab.streamers_lag import assess_session_lag, attach_lag_to_meta, scan_recent_lag


def test_assess_critical_window_loss():
    meta = {
        "requested_minutes": 20,
        "still_interval_sec": 1.0,
        "capture_utc_start": "2026-11-10T15:11:21+00:00",
        "capture_utc_end": "2026-11-10T15:16:20+00:00",
        "chunks": [{"index": 0, "stills": 294}, {"index": 1, "stills": 0}],
        "warnings": ["stills_chunk_1: Can't find window 'BlueStacks App Player'"],
        "visual_archive": {"still_count": 294},
    }
    a = assess_session_lag(meta)
    assert a["level"] == "critical"
    assert "window_grab_failed" in a["signals"]
    attach_lag_to_meta(meta)
    assert meta["streamers_lag"]["level"] == "critical"
    assert "streamers_lag:critical" in meta["warnings"]


def test_assess_ok_full_take():
    meta = {
        "requested_minutes": 5,
        "still_interval_sec": 1.0,
        "capture_utc_start": "2026-11-10T15:00:00+00:00",
        "capture_utc_end": "2026-11-10T15:05:00+00:00",
        "chunks": [{"index": 0, "stills": 300}],
        "warnings": [],
        "visual_archive": {"still_count": 300},
    }
    assert assess_session_lag(meta)["level"] == "ok"


def test_scan_recent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "OHushData"
    monkeypatch.setenv("OHUSH_DATA_ROOT", str(root))
    ensure_data_layout(root)
    sid = root / "authorized_sources" / "streamers_test_lag"
    sid.mkdir(parents=True)
    (sid / "meta.json").write_text(
        json.dumps(
            {
                "session_id": "streamers_test_lag",
                "channel_id": "X",
                "requested_minutes": 20,
                "still_interval_sec": 1.0,
                "capture_utc_start": "2026-11-10T15:11:21+00:00",
                "capture_utc_end": "2026-11-10T15:16:20+00:00",
                "chunks": [{"stills": 10}],
                "warnings": ["Can't find window"],
                "visual_archive": {"still_count": 10},
            }
        ),
        encoding="utf-8",
    )
    rep = scan_recent_lag(root)
    assert rep["overall"] == "critical"
    assert rep["avoid_third_instance"] is True
