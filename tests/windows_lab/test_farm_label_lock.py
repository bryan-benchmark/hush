"""Single-flight verdict label lock."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tools.windows_lab.config import ensure_data_layout
from tools.windows_lab import farm_label_lock as fl


@pytest.fixture()
def data_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "OHushData"
    monkeypatch.setenv("OHUSH_DATA_ROOT", str(root))
    ensure_data_layout(root)
    return root


def test_acquire_release(data_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OHUSH_DATA_ROOT", str(data_root))
    a = fl.acquire(root=data_root, reason="test")
    assert a["ok"] is True
    b = fl.acquire(root=data_root, reason="test2")
    assert b["ok"] is False
    assert fl.status(root=data_root)["held"] is True
    assert fl.release(root=data_root)["ok"] is True
    assert fl.status(root=data_root)["held"] is False


def test_stale_dead_pid_reclaimed(data_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OHUSH_DATA_ROOT", str(data_root))
    lock_path, meta_path = fl._paths(data_root)
    lock_path.write_text("1", encoding="utf-8")
    meta_path.write_text('{"pid": 1, "utc": "2020-01-01T00:00:00+00:00", "reason": "old"}\n', encoding="utf-8")
    # pid 1 is usually not alive as a user python holder on Windows; treat as dead/stale.
    st = fl.status(root=data_root)
    assert st["held"] is True
    got = fl.acquire(root=data_root, reason="reclaim")
    assert got["ok"] is True
    fl.release(root=data_root)
