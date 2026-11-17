"""Spinner / picture-dead ladder: stages, ESPN skip local, notify quiet until exhausted."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from tools.windows_lab.config import ensure_data_layout
from tools.windows_lab.heartbeat_fix import (
    SPINNER_LADDER_STAGES,
    _job_is_local_capture,
    _job_is_named_linear,
    _run_spinner_ladder,
    fix_heartbeat,
)
from tools.windows_lab.instances import default_registry, save_registry
from tools.windows_lab.notify import notify_from_audit


@pytest.fixture()
def data_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "OHushData"
    monkeypatch.setenv("OHUSH_DATA_ROOT", str(root))
    monkeypatch.setenv("HUSH_SPINNER_WAIT_S", "0.05")
    monkeypatch.setenv("HUSH_SPINNER_STAGE_COOLDOWN_S", "0")
    monkeypatch.setenv("HUSH_NOTIFY_STALE_STREAK", "2")
    monkeypatch.setenv("SENDGRID_API_KEY", "")
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "")
    ensure_data_layout(root)
    save_registry(default_registry(), root)
    return root


def _failing_probe(**extra):
    base = {
        "ok": False,
        "failing": True,
        "reason": "picture_blue_spinner",
        "instance_id": "Nougat32",
        "picture": {
            "down": True,
            "picture_verdict": "blue_spinner",
            "frame_score": {"verdict": "blue_spinner"},
        },
        "session_picture": {"picture_ok": False, "state": "blue_spinner"},
        "audio": {"ok": True},
        "ui_kind": "player_fullscreen",
    }
    base.update(extra)
    return base


def _healthy_probe():
    return {
        "ok": True,
        "failing": False,
        "reason": "ok",
        "instance_id": "Nougat32",
        "picture": {"down": False, "picture_verdict": "likely_playing"},
        "session_picture": {"picture_ok": True, "state": "likely_playing"},
        "audio": {"ok": True},
        "ui_kind": "player_fullscreen",
    }


def test_named_linear_vs_local_helpers():
    espn = {"nav_route": "ESPN_US", "open_via": "nav", "shortcut_id": "MNF_ESPN"}
    assert _job_is_named_linear(espn, "MNF_ESPN", "MNF_ESPN") is True
    assert _job_is_local_capture(espn, "MNF_ESPN", "MNF_ESPN") is False

    fox = {"shortcut_id": "FOX_NY", "channel_id": "FOX_NY", "open_via": "search"}
    assert _job_is_named_linear(fox, "FOX_NY", "FOX_NY") is False
    assert _job_is_local_capture(fox, "FOX_NY", "FOX_NY") is True


def test_ladder_includes_channel_hop_and_alternate_local():
    assert "channel_hop" in SPINNER_LADDER_STAGES
    assert "alternate_local" in SPINNER_LADDER_STAGES
    assert SPINNER_LADDER_STAGES.index("channel_hop") < SPINNER_LADDER_STAGES.index(
        "alternate_local"
    )


def test_espn_skips_alternate_local(data_root: Path):
    job = {
        "job_id": "mnf1",
        "shortcut_id": "MNF_ESPN",
        "channel_id": "MNF_ESPN",
        "nav_route": "ESPN_US",
        "open_via": "nav",
        "session_id": "sess_mnf",
    }
    # Force ladder to alternate_local stage.
    from tools.windows_lab import heartbeat_fix as hb

    key = hb._spinner_ladder_key("Nougat32", job)
    alt_i = SPINNER_LADDER_STAGES.index("alternate_local")
    hb._save_spinner_ladder(
        data_root,
        key,
        {
            "next_stage_i": alt_i,
            "stage_i": alt_i - 1,
            "stage": SPINNER_LADDER_STAGES[alt_i - 1],
            "ts": 0,
            "history": [],
        },
    )
    failing = _failing_probe()
    with (
        patch("tools.windows_lab.heartbeat_fix.probe_heartbeat", return_value=failing),
        patch("tools.windows_lab.heartbeat_fix.open_booth_local") as open_local,
    ):
        out = _run_spinner_ladder(
            "Nougat32",
            root=data_root,
            job=job,
            session_id="sess_mnf",
            channel_id="MNF_ESPN",
            shortcut_id="MNF_ESPN",
            before=failing,
            force=True,
        )
    open_local.assert_not_called()
    assert out.get("ok") is False
    assert out.get("ladder_continue") is True
    hist = out.get("steps") or []
    assert hist
    assert hist[-1].get("step") == "alternate_local"
    assert hist[-1].get("skipped") is True
    assert "named" in str(hist[-1].get("lesson") or "").lower() or hist[-1].get(
        "detail"
    ) == "skipped_not_local"


def test_fix_heartbeat_routes_spinner_to_ladder(data_root: Path):
    failing = _failing_probe()
    job = {
        "job_id": "post1",
        "shortcut_id": "MNF_POST_ESPN",
        "channel_id": "MNF_POST_ESPN",
        "nav_route": "ESPN_US",
        "open_via": "nav",
    }
    with (
        patch("tools.windows_lab.heartbeat_fix.probe_heartbeat", return_value=failing),
        patch("tools.windows_lab.heartbeat_fix.time.sleep", return_value=None),
        patch(
            "tools.windows_lab.streamers_recover.jiggle_stuck_player",
            return_value={"ok": True, "keys": [19, 20]},
        ),
        patch(
            "tools.windows_lab.streamers_recover.channel_hop_and_back",
            return_value={"ok": True, "keys": [166, 167], "dwell_s": 1},
        ),
        patch("tools.windows_lab.instances.get_instance", return_value={"id": "Nougat32"}),
    ):
        out = fix_heartbeat("Nougat32", root=data_root, job=job, force=True)
    assert str(out.get("reason") or "").startswith("spinner_ladder")
    assert out.get("ladder_continue") is True or out.get("ok") is False


def test_notify_picture_dead_quiet_until_exhausted(data_root: Path):
    job = {
        "job_id": "spin1",
        "label": "MNF post",
        "channel_id": "MNF_POST_ESPN",
        "verdict": "picture_dead_live",
        "pid_alive": True,
        "status": "started",
        "issues": ["picture dead while capturing: blue_spinner"],
        "tape": {"still_count": 900, "audio_seconds": 900},
        "recover": {
            "attempted": True,
            "ok": False,
            "ladder_continue": True,
            "ladder_exhausted": False,
            "stage": "channel_hop",
        },
        "verdict_streak": 5,
    }
    out = notify_from_audit({"jobs": [job]}, root=data_root)
    assert not any(
        r.get("event") == "capture_picture_dead" and not r.get("skipped")
        for r in out
        if isinstance(r, dict)
    )

    job["recover"] = {
        "attempted": True,
        "ok": False,
        "ladder_continue": False,
        "ladder_exhausted": True,
        "stage": "exhausted",
    }
    job["verdict_streak"] = 3
    out2 = notify_from_audit({"jobs": [job]}, root=data_root)
    assert any(
        r.get("event") == "capture_picture_dead" for r in out2 if isinstance(r, dict) and r.get("event")
    )


def test_channel_hop_helper_keys():
    from tools.windows_lab.streamers_recover import channel_hop_and_back

    calls: list[list[str]] = []

    def fake_adb(_inst, argv, **_kw):
        calls.append(list(argv))
        return 0, ""

    with (
        patch("tools.windows_lab.streamers_recover.adb", side_effect=fake_adb),
        patch("tools.windows_lab.streamers_recover.time.sleep", return_value=None),
    ):
        out = channel_hop_and_back({"id": "Nougat32"}, dwell_s=1.0)
    assert out.get("keys") == [166, 167]
    assert any("166" in c for c in calls)
    assert any("167" in c for c in calls)
