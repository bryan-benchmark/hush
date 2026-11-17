"""Recovery must follow schedule/hierarchy — not bare Atlanta ABC."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from tools.windows_lab.config import ensure_data_layout
from tools.windows_lab.instances import default_registry, save_registry, upsert_instance
from tools.windows_lab.recovery_target import open_recovery_target, resolve_recovery_target
from tools.windows_lab.stream_status import instance_default_network, pick_filler_network


@pytest.fixture()
def data_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "OHushData"
    monkeypatch.setenv("OHUSH_DATA_ROOT", str(root))
    ensure_data_layout(root)
    save_registry(default_registry(), root)
    upsert_instance("Nougat32", {"enabled": True, "source_kind": "streamers"}, root)
    upsert_instance("Nougat32_1", {"enabled": True, "source_kind": "streamers"}, root)
    return root


def test_instance_defaults_are_distinct_not_both_abc():
    assert instance_default_network("Nougat32") == "FOX"
    assert instance_default_network("Nougat32_1") == "CBS"
    assert instance_default_network("Nougat32") != instance_default_network("Nougat32_1")


def test_pick_filler_empty_fleet_not_both_abc(data_root: Path):
    a = pick_filler_network("Nougat32", root=data_root)
    b = pick_filler_network("Nougat32_1", root=data_root)
    assert a != b
    # Concurrent empty fleet must not collapse both to ABC.
    assert not (a == "ABC" and b == "ABC")


def test_resolve_live_preempt_prefers_game_net(data_root: Path):
    hier = {
        "live_preempt": True,
        "fill_order": ["aux_sports", "main_linear"],
        "daypart": "afternoon",
    }
    with patch(
        "tools.windows_lab.coverage_farm.hierarchy_snapshot",
        return_value=hier,
    ), patch(
        "tools.windows_lab.recovery_target._due_or_active_jobs",
        return_value=[],
    ), patch(
        "tools.windows_lab.recovery_target._job_for_lock",
        return_value=None,
    ):
        t0 = resolve_recovery_target("Nougat32", root=data_root)
        t1 = resolve_recovery_target("Nougat32_1", root=data_root)
    assert t0.get("kind") == "live_local"
    assert t0.get("network") in {"FOX", "CBS", "NBC", "ABC"}
    assert t0.get("network") != "ABC" or t1.get("network") != "ABC"
    assert t0.get("network") != t1.get("network")


def test_resolve_due_job_beats_filler(data_root: Path):
    job = {
        "job_id": "abc123",
        "channel_id": "TNF_PRIME",
        "shortcut_id": "TNF_PRIME",
        "label": "TNF",
        "status": "due",
        "instance_id": "Nougat32",
        "start_utc": "2026-11-15T17:00:00+00:00",
        "minutes": 180,
    }
    with patch(
        "tools.windows_lab.recovery_target._due_or_active_jobs",
        return_value=[job],
    ), patch(
        "tools.windows_lab.recovery_target._job_for_lock",
        return_value=None,
    ):
        t = resolve_recovery_target("Nougat32", root=data_root)
    assert t.get("kind") == "scheduled_job"
    assert t.get("channel_id") == "TNF_PRIME"
    assert t.get("why") == "due_or_active_schedule"


def test_open_recovery_uses_live_sports_not_atlanta_home(data_root: Path):
    with patch(
        "tools.windows_lab.recovery_target.resolve_recovery_target",
        return_value={
            "ok": True,
            "kind": "live_local",
            "network": "CBS",
            "live_preempt": True,
            "why": "hierarchy_live_preempt",
            "label": "live:CBS",
        },
    ), patch(
        "tools.windows_lab.us_locals.open_live_sports_local",
        return_value={
            "ok": True,
            "via": "live_sports_section",
            "network": "CBS",
            "selected_title": "FL | PANAMA CITY | CBS - WECP",
            "channel_title": "FL | PANAMA CITY | CBS - WECP",
            "program_title": "NFL Football : Kansas City Chiefs at Atlanta Falcons",
            "program_key": "kansas city chiefs at atlanta falcons",
            "pick": {"network": "CBS", "why": "live_sports_now_playing"},
        },
    ) as live, patch(
        "tools.windows_lab.heartbeat_fix.open_booth_local",
    ) as booth:
        out = open_recovery_target("Nougat32", root=data_root)
    assert out.get("ok") is True
    assert out.get("via") == "live_sports_section"
    assert "chiefs" in str(out.get("program_key") or "")
    assert live.called
    assert not booth.called
