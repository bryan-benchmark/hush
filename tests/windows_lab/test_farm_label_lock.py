"""Label-pass lock: dead PID reclaim + labeler heartbeats."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from tools.windows_lab.config import ensure_data_layout
from tools.windows_lab.farm_label_lock import (
    HEARTBEAT_STALE_SEC,
    acquire,
    heartbeat,
    release,
    status,
)


@pytest.fixture()
def data_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "OHushData"
    monkeypatch.setenv("OHUSH_DATA_ROOT", str(root))
    ensure_data_layout(root)
    return root


def test_acquire_heartbeat_and_release(data_root: Path) -> None:
    got = acquire(data_root, reason="test")
    assert got["ok"] is True
    assert status(data_root)["held"] is True
    assert status(data_root)["alive"] is True
    beat = heartbeat(data_root, phase="vision", session="sess_a", hop_i=3, hop_of=10, note="vision_hop")
    assert beat["ok"] is True
    cur = status(data_root)
    assert cur["meta"]["hop_i"] == 3
    assert cur["meta"]["note"] == "vision_hop"
    assert cur["beat_age_s"] is not None
    assert cur["beat_age_s"] < 5
    assert release(data_root)["ok"] is True
    assert status(data_root)["held"] is False


def test_dead_pid_is_stale(data_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    acquire(data_root, reason="dead_pid")
    # Forge a dead holder PID in meta (OpenProcess used to false-positive these).
    from tools.windows_lab.farm_label_lock import _paths

    lock_path, meta_path = _paths(data_root)
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["pid"] = 67700  # known-dead in prior incident shape
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    monkeypatch.setattr("tools.windows_lab.farm_label_lock._pid_alive", lambda pid: False)
    cur = status(data_root)
    assert cur["alive"] is False
    assert cur["stale"] is True
    # Next acquire reclaims.
    got = acquire(data_root, reason="reclaim")
    assert got["ok"] is True
    assert got["pid"] == os.getpid()
    release(data_root)


def test_silent_heartbeat_becomes_stale(data_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    acquire(data_root, reason="quiet")
    from tools.windows_lab import farm_label_lock as mod

    real = mod._beat_age_s

    def _old(*args, **kwargs):
        return float(HEARTBEAT_STALE_SEC + 30)

    monkeypatch.setattr(mod, "_beat_age_s", _old)
    cur = status(data_root)
    assert cur["heartbeat_stale"] is True
    assert cur["stale"] is True
    monkeypatch.setattr(mod, "_beat_age_s", real)
    release(data_root, force=True)
