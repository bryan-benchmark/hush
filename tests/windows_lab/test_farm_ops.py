"""Farm ops: run log, board, ON_AIR preempt helpers."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from tools.windows_lab.config import ensure_data_layout
from tools.windows_lab.farm_ops import (
    emit,
    preempt_on_air,
    run_log_path,
    write_ops_board,
)
from tools.windows_lab.instances import default_registry, save_registry, upsert_instance
from tools.windows_lab.locks import acquire, get_lock, release
from tools.windows_lab.scheduler import add_job, load_jobs, save_jobs


@pytest.fixture()
def data_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "OHushData"
    monkeypatch.setenv("OHUSH_DATA_ROOT", str(root))
    ensure_data_layout(root)
    save_registry(default_registry(), root)
    upsert_instance("Nougat32_1", {"enabled": True, "source_kind": "streamers"}, root)
    return root


def test_emit_and_board(data_root: Path):
    emit("test_event", detail="hello", job_id="abc", instance_id="Nougat32", ok=True, root=data_root)
    path = run_log_path(data_root)
    assert path.is_file()
    row = json.loads(path.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert row["event"] == "test_event"
    assert row["job_id"] == "abc"

    past = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    add_job(
        source_kind="streamers",
        channel_id="NBC_LOCAL",
        start_at=past,
        minutes=30,
        instance_id="Nougat32",
        root=data_root,
        label="test due",
    )
    snap = write_ops_board(data_root)
    assert Path(snap["board"]).is_file()
    text = Path(snap["board"]).read_text(encoding="utf-8")
    assert "Farm ops" in text
    assert "test due" in text


def test_preempt_only_on_air(data_root: Path):
    ok, _ = acquire(
        "streamers",
        "Nougat32",
        session_id="streamers_x_SPORTS_Nougat32",
        root=data_root,
    )
    assert ok
    try:
        refused = preempt_on_air("Nougat32", root=data_root)
        assert refused.get("ok") is False
        assert get_lock("streamers", "Nougat32", root=data_root) is not None
    finally:
        release("streamers", "Nougat32", root=data_root)

    ok, _ = acquire(
        "streamers",
        "Nougat32",
        session_id="streamers_x_ON_AIR_CONTINUE_Nougat32",
        root=data_root,
    )
    assert ok
    out = preempt_on_air("Nougat32", root=data_root, reason="test")
    assert out.get("ok") is True
    assert get_lock("streamers", "Nougat32", root=data_root) is None


def test_restart_job_dry_run_clears_lock(data_root: Path):
    from tools.windows_lab.farm_ops import restart_job

    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    job = add_job(
        source_kind="streamers",
        channel_id="NBC_LOCAL",
        start_at=past,
        minutes=1,
        media="audio",
        instance_id="Nougat32",
        root=data_root,
        label="restart me",
    )
    jid = job["job_id"]
    data = load_jobs(data_root)
    for j in data["jobs"]:
        if j["job_id"] == jid:
            j["status"] = "started"
            j["session_id"] = "streamers_old_NBC_LOCAL_Nougat32"
            j["pid"] = 111
    save_jobs(data, data_root)
    ok, _ = acquire(
        "streamers",
        "Nougat32",
        session_id="streamers_old_NBC_LOCAL_Nougat32",
        job_id=jid,
        root=data_root,
    )
    assert ok
    out = restart_job(jid, root=data_root, execute=False, reason="test")
    assert out.get("ok") is True
    assert out.get("dry_preview") is True
    assert get_lock("streamers", "Nougat32", root=data_root) is None
    data = load_jobs(data_root)
    updated = next(j for j in data["jobs"] if j["job_id"] == jid)
    assert updated["status"] == "scheduled"
    assert updated.get("prior_session_id") == "streamers_old_NBC_LOCAL_Nougat32"


def test_run_due_preempts_on_air_when_execute(data_root: Path, monkeypatch: pytest.MonkeyPatch):
    """Live execute clears ON_AIR_CONTINUE and keeps the preferred instance."""
    from tools.windows_lab.scheduler import run_due

    ok, _ = acquire(
        "streamers",
        "Nougat32",
        session_id="streamers_busy_ON_AIR_CONTINUE_Nougat32",
        root=data_root,
    )
    assert ok
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    job = add_job(
        source_kind="streamers",
        channel_id="NBC_LOCAL",
        start_at=past,
        minutes=1,
        media="audio",
        instance_id="Nougat32",
        root=data_root,
        label="NBC preempt",
    )

    def _fake_start(job_arg, root=None):  # noqa: ANN001
        return {
            "ok": True,
            "session_id": "streamers_fake_NBC_LOCAL_Nougat32",
            "pid": 4242,
            "log": None,
        }

    monkeypatch.setattr(
        "tools.windows_lab.scheduler._start_session_detached",
        _fake_start,
    )
    monkeypatch.setattr(
        "tools.windows_lab.scheduler._open_guide_before_record",
        lambda *a, **k: {"ok": True, "skipped": True},
    )
    try:
        out = run_due(root=data_root, execute=True)
        data = load_jobs(data_root)
        updated = next(j for j in data["jobs"] if j["job_id"] == job["job_id"])
        assert updated["instance_id"] == "Nougat32"
        assert updated.get("retargeted_from") is None
        assert updated["status"] == "started"
        assert any(s.get("job_id") == job["job_id"] for s in out.get("started") or [])
        assert get_lock("streamers", "Nougat32", root=data_root) is None
    finally:
        release("streamers", "Nougat32", root=data_root)
