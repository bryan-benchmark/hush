"""Overnight/pause label gate — Bug 6 stale capture lock reclaim."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from tools.windows_lab.config import ensure_data_layout
from tools.windows_lab.farm_loop import lock_audio_still_capturing, prepare_label_gate
from tools.windows_lab.locks import acquire, get_lock


@pytest.fixture()
def data_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "OHushData"
    monkeypatch.setenv("OHUSH_DATA_ROOT", str(root))
    ensure_data_layout(root)
    return root


def _session(root: Path, sid: str) -> Path:
    d = root / "authorized_sources" / sid
    d.mkdir(parents=True, exist_ok=True)
    return d


def test_audio_heartbeat_stale_not_capturing(data_root: Path) -> None:
    sid = "streamers_20261117T014601Z_MNF_ESPN_Nougat32"
    sd = _session(data_root, sid)
    hb = sd / "_audio_heartbeat.json"
    hb.write_text(json.dumps({"state": "recording"}), encoding="utf-8")
    # Age the file beyond stale window
    old = time.time() - 2000
    import os

    os.utime(hb, (old, old))
    lock = {"session_id": sid, "resource_id": "Nougat32"}
    out = lock_audio_still_capturing(lock, data_root)
    assert out["capturing"] is False
    assert "stale" in str(out["why"])


def test_audio_done_not_capturing(data_root: Path) -> None:
    sid = "streamers_done"
    sd = _session(data_root, sid)
    (sd / "_audio_heartbeat.json").write_text(json.dumps({"state": "done"}), encoding="utf-8")
    out = lock_audio_still_capturing({"session_id": sid}, data_root)
    assert out["capturing"] is False


def test_overnight_releases_stale_lock(data_root: Path) -> None:
    sid = "streamers_stale_mnf"
    sd = _session(data_root, sid)
    hb = sd / "_audio_heartbeat.json"
    hb.write_text(json.dumps({"state": "recording"}), encoding="utf-8")
    old = time.time() - 2000
    import os

    os.utime(hb, (old, old))
    ok, row = acquire(
        "streamers",
        "Nougat32",
        session_id=sid,
        job_id="job1",
        holder_pid=os.getpid(),
        root=data_root,
    )
    assert ok
    assert get_lock("streamers", "Nougat32", root=data_root)

    gate = prepare_label_gate("Nougat32", data_root, overnight=True, pause_active=False)
    assert gate["allow_label"] is True
    assert gate["busy"] is None
    assert gate["released_stale"] is not None
    assert get_lock("streamers", "Nougat32", root=data_root) is None


def test_overnight_keeps_live_audio_lock(data_root: Path) -> None:
    sid = "streamers_live"
    sd = _session(data_root, sid)
    (sd / "_audio_heartbeat.json").write_text(json.dumps({"state": "recording"}), encoding="utf-8")
    import os

    ok, _ = acquire(
        "streamers",
        "Nougat32",
        session_id=sid,
        job_id="job2",
        holder_pid=os.getpid(),
        root=data_root,
    )
    assert ok
    gate = prepare_label_gate("Nougat32", data_root, overnight=True, pause_active=False)
    assert gate["allow_label"] is False
    assert gate["skip_for_live_capture"] is True
    assert get_lock("streamers", "Nougat32", root=data_root) is not None
