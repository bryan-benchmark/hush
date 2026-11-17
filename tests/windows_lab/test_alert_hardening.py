"""Alert hardening: auto-close, clone retarget, warm-up / stale streak."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from tools.windows_lab.config import ensure_data_layout
from tools.windows_lab.instances import default_registry, save_registry, upsert_instance
from tools.windows_lab.locks import acquire, release
from tools.windows_lab.notify import _hush_brand_text, notify_from_audit
from tools.windows_lab.schedule_audit import (
    audit_job,
    inspect_session,
    remediate_started_jobs,
)
from tools.windows_lab.scheduler import _free_streamers_instance, add_job, load_jobs, run_due


@pytest.fixture()
def data_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "OHushData"
    monkeypatch.setenv("OHUSH_DATA_ROOT", str(root))
    ensure_data_layout(root)
    save_registry(default_registry(), root)
    upsert_instance("Nougat32_1", {"enabled": True, "source_kind": "streamers"}, root)
    return root


def test_inspect_counts_legacy_loopback(data_root: Path):
    sid = "streamers_test_NEWS"
    session = data_root / "authorized_sources" / sid
    session.mkdir(parents=True)
    (session / "stills").mkdir()
    # Minimal valid WAV header via wave module
    import wave
    import struct

    wav_path = session / "_process_loopback_full.wav"
    with wave.open(str(wav_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        frames = b"\x00\x00" * 16000  # 1 second
        wf.writeframes(frames)
    (session / "stills" / "0001.jpg").write_bytes(b"x")

    tape = inspect_session(sid, root=data_root)
    assert tape["legacy_wav_count"] == 1
    assert tape["audio_seconds"] >= 0.9
    assert tape["checks"]["has_audio"] is True
    assert tape["checks"]["has_legacy_loopback"] is True


def test_warming_not_broken_in_first_minutes(data_root: Path):
    sid = "streamers_warm_ABC"
    session = data_root / "authorized_sources" / sid
    session.mkdir(parents=True)
    (session / "stills").mkdir()
    now = datetime.now(timezone.utc)
    job = {
        "job_id": "warm1",
        "label": "warm",
        "channel_id": "ABC_LOCAL",
        "status": "started",
        "start_utc": (now - timedelta(minutes=1)).isoformat(),
        "started_utc": (now - timedelta(minutes=1)).isoformat(),
        "minutes": 60,
        "pid": None,
        "session_id": sid,
        "source_kind": "streamers",
        "instance_id": "Nougat32",
    }
    row = audit_job(job, root=data_root, now=now)
    assert row["verdict"] == "warming"


def test_remediate_closes_audio_done_zombie(data_root: Path):
    sid = "streamers_done_FOX"
    session = data_root / "authorized_sources" / sid
    (session / "stills").mkdir(parents=True)
    import wave

    for i in range(2):
        with wave.open(str(session / f"audio_{i:04d}.wav"), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(b"\x00\x00" * 16000 * 60)  # 60s each
        (session / "stills" / f"{i:04d}.jpg").write_bytes(b"x")
    # Make stills look old
    import os
    import time

    old = time.time() - 1000
    for p in (session / "stills").glob("*"):
        os.utime(p, (old, old))

    now = datetime.now(timezone.utc)
    job = {
        "job_id": "fox1",
        "label": "FOX",
        "channel_id": "FOX_LOCAL",
        "status": "started",
        "start_utc": (now - timedelta(hours=3)).isoformat(),
        "started_utc": (now - timedelta(hours=3)).isoformat(),
        "minutes": 2,  # requested 120s; we have ~120s audio
        "pid": 999999,
        "session_id": sid,
        "source_kind": "streamers",
        "instance_id": "Nougat32_1",
    }
    data = {"jobs": [job]}
    row = audit_job(job, root=data_root, now=now)
    assert row["verdict"] in {"stale_live", "dead"}
    actions = remediate_started_jobs(data, [row], now=now)
    assert actions
    assert data["jobs"][0]["status"] in {"completed", "failed"}
    assert data["jobs"][0]["closed_reason"].startswith("auto_remediate")


def test_free_instance_retargets_to_clone(data_root: Path):
    ok, _ = acquire(
        "streamers",
        "Nougat32",
        session_id="streamers_busy_ON_AIR_CONTINUE_Nougat32",
        root=data_root,
    )
    assert ok
    try:
        alt = _free_streamers_instance("Nougat32", root=data_root)
        assert alt == "Nougat32_1"
    finally:
        release("streamers", "Nougat32", root=data_root)


def test_run_due_retargets_when_primary_busy(data_root: Path):
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
        label="NBC retarget",
    )
    try:
        preview = run_due(root=data_root, execute=False)
        # Dry preview still retargets the job record before dry_preview skip
        data = load_jobs(data_root)
        updated = next(j for j in data["jobs"] if j["job_id"] == job["job_id"])
        assert updated["instance_id"] == "Nougat32_1"
        assert updated.get("retargeted_from") == "Nougat32"
        assert any(r.get("to") == "Nougat32_1" for r in preview.get("retargeted") or [])
    finally:
        release("streamers", "Nougat32", root=data_root)


def test_hush_brand_scrubs_benchmark_from_copy():
    dirty = "Alert from Benchmark / bryan@benchmark.care (not HUSH)"
    clean = _hush_brand_text(dirty)
    assert "benchmark" not in clean.lower()
    assert "HUSH" in clean
    assert "[redacted]" in clean


def test_stale_streak_suppresses_first_pages(data_root: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("HUSH_NOTIFY_STALE_STREAK", "3")
    monkeypatch.setenv("HUSH_NOTIFY_ONCE", "1")
    # Force notify sends to no-op channels
    monkeypatch.setenv("SENDGRID_API_KEY", "")
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "")

    job = {
        "job_id": "stale1",
        "label": "TNF",
        "channel_id": "TNF_PRIME",
        "verdict": "stale_live",
        "pid_alive": True,
        "status": "started",
        "issues": ["session exists but stills/audio not fresh"],
        "tape": {"still_count": 100, "audio_seconds": 0},
        "recover": {"attempted": True, "ok": False},
        "verdict_streak": 1,
    }
    out1 = notify_from_audit({"jobs": [job]}, root=data_root)
    assert not any(r.get("event") == "capture_stale" and not r.get("skipped") for r in out1 if isinstance(r, dict))

    job["verdict_streak"] = 3
    out3 = notify_from_audit({"jobs": [job]}, root=data_root)
    # May be skipped for channel config, but should attempt (not streak-suppressed)
    assert any(
        r.get("event") == "capture_stale" for r in out3 if isinstance(r, dict) and r.get("event")
    )
