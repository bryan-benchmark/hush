"""Unit tests for the multi-source capture farm (no live BlueStacks required)."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from tools.windows_lab.catalog import append_session, list_sessions
from tools.windows_lab.channel import apply_recipe, example_recipe, load_recipe, save_recipe
from tools.windows_lab.config import (
    capture_sessions_index_path,
    ensure_data_layout,
    instance_registry_path,
    schedule_path,
)
from tools.windows_lab.instances import (
    crosstalk_check,
    default_registry,
    get_instance,
    load_registry,
    save_registry,
    upsert_instance,
)
from tools.windows_lab.locks import acquire, get_lock, release
from tools.windows_lab.multi_instance import isolation_report, write_setup_checklist
from tools.windows_lab.ota import doctor as ota_doctor
from tools.windows_lab.ota import get_ota_config, upsert_channel
from tools.windows_lab.scheduler import add_job, cancel_job, list_jobs, run_due
from tools.windows_lab.session_capture import start_session


@pytest.fixture()
def data_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "OHushData"
    monkeypatch.setenv("OHUSH_DATA_ROOT", str(root))
    ensure_data_layout(root)
    return root


def test_registry_seeds_and_upsert(data_root: Path):
    reg = load_registry(data_root)
    assert instance_registry_path(data_root).is_file()
    assert "Nougat32" in reg["instances"]
    row = upsert_instance(
        "Nougat32_1",
        {
            "adb_port": 5565,
            "adb_serial": "127.0.0.1:5565",
            "loopback_device": "CABLE-2 Input",
            "window_title": "BlueStacks",
        },
        root=data_root,
    )
    assert row["adb_port"] == 5565
    assert get_instance("Nougat32_1", data_root)["loopback_device"] == "CABLE-2 Input"


def test_crosstalk_requires_distinct_loopbacks(data_root: Path):
    save_registry(default_registry(), data_root)
    upsert_instance("A", {"loopback_device": "CABLE Input"}, data_root)
    upsert_instance("B", {"loopback_device": "CABLE Input"}, data_root)
    bad = crosstalk_check("A", "B", root=data_root)
    assert bad["ok"] is False
    upsert_instance("B", {"loopback_device": "CABLE-2 Input"}, data_root)
    good = crosstalk_check("A", "B", root=data_root)
    assert good["ok"] is True


def test_channel_recipe_roundtrip_and_dry_run(data_root: Path, monkeypatch: pytest.MonkeyPatch):
    save_registry(default_registry(), data_root)
    path = save_recipe("ESPN", example_recipe("ESPN"), data_root)
    assert path.is_file()
    recipe = load_recipe("ESPN", data_root)
    assert recipe["channel_id"] == "ESPN"
    # Avoid launching BlueStacks: dry_run skips ADB.
    result = apply_recipe(
        channel_id="ESPN",
        instance_id="Nougat32",
        root=data_root,
        dry_run=True,
        launch=False,
    )
    assert result["ok"] is True
    assert result["dry_run"] is True
    assert len(result["steps"]) >= 1


def test_locks_and_busy_session(data_root: Path):
    save_registry(default_registry(), data_root)
    ok, row = acquire("streamers", "Nougat32", session_id="s1", root=data_root)
    assert ok is True
    assert get_lock("streamers", "Nougat32", data_root)["session_id"] == "s1"
    busy = start_session(
        source_kind="streamers",
        channel_id="ESPN",
        minutes=1,
        instance_id="Nougat32",
        dry_run=True,
        root=data_root,
    )
    assert busy["ok"] is False
    assert busy["error"] == "resource busy"
    release("streamers", "Nougat32", data_root)
    free = start_session(
        source_kind="streamers",
        channel_id="ESPN",
        minutes=1,
        instance_id="Nougat32",
        dry_run=True,
        apply_channel=False,
        root=data_root,
    )
    assert free["ok"] is True
    assert free["dry_run"] is True
    meta_path = Path(free["session_dir"]) / "meta.json"
    assert meta_path.is_file()
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["source_kind"] == "streamers"
    assert meta["media"] == "av"
    assert meta["credentials"] is None


def test_catalog_index(data_root: Path):
    append_session(
        {
            "session_id": "streamers_test",
            "source_kind": "streamers",
            "channel_id": "ESPN",
            "label_status": "unlabeled",
        },
        root=data_root,
    )
    rows = list_sessions(data_root, label_status="unlabeled")
    assert len(rows) == 1
    assert capture_sessions_index_path(data_root).is_file()


def test_scheduler_add_cancel_run_due_preview(data_root: Path):
    save_registry(default_registry(), data_root)
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    job = add_job(
        source_kind="streamers",
        channel_id="ESPN",
        start_at=past,
        minutes=1,
        media="audio",
        instance_id="Nougat32",
        root=data_root,
    )
    assert job["status"] == "scheduled"
    assert schedule_path(data_root).is_file()
    preview = run_due(root=data_root, execute=False)
    assert any(s["job_id"] == job["job_id"] for s in preview["skipped"])
    cancelled = cancel_job(job["job_id"], root=data_root)
    assert cancelled["status"] == "cancelled"
    assert list_jobs(data_root, status="cancelled")


def test_ota_config_and_channel_map(data_root: Path):
    cfg = get_ota_config(data_root)
    assert "tuners" in cfg
    row = upsert_channel("7.1", major=7, minor=1, label="ABC", root=data_root)
    assert row["major"] == 7
    report = ota_doctor(data_root)
    assert "tuners" in report
    assert report["ok"] is False  # no USB tuner configured yet


def test_multi_instance_checklist(data_root: Path):
    save_registry(default_registry(), data_root)
    upsert_instance("Nougat32", {"loopback_device": "CABLE Input"}, data_root)
    upsert_instance("Nougat32_1", {"loopback_device": "CABLE-2 Input"}, data_root)
    report = isolation_report(data_root)
    assert report["ok"] is True
    path = write_setup_checklist(data_root)
    assert path.is_file()
    assert "VB-Audio" in path.read_text(encoding="utf-8")
