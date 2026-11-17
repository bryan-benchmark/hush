"""Heartbeat fix route: skip healthy, detect failing picture."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from tools.windows_lab.config import ensure_data_layout
from tools.windows_lab.heartbeat_fix import fix_heartbeat, probe_heartbeat
from tools.windows_lab.instances import default_registry, save_registry


@pytest.fixture()
def data_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "OHushData"
    monkeypatch.setenv("OHUSH_DATA_ROOT", str(root))
    ensure_data_layout(root)
    save_registry(default_registry(), root)
    return root


def test_fix_skips_healthy(data_root: Path):
    healthy = {
        "ok": True,
        "failing": False,
        "reason": "ok",
        "instance_id": "Nougat32",
        "picture": {"down": False, "ok": True},
        "audio": None,
        "session_picture": None,
    }
    with patch("tools.windows_lab.heartbeat_fix.probe_heartbeat", return_value=healthy):
        out = fix_heartbeat("Nougat32", root=data_root)
    assert out.get("ok") is True
    assert out.get("skipped") is True
    assert out.get("reason") == "already_healthy"


def test_probe_marks_picture_down(data_root: Path):
    fake = {
        "ok": False,
        "down": True,
        "reason": "picture_blue_spinner",
        "frame_score": {"verdict": "blue_spinner"},
        "picture_verdict": "blue_spinner",
        "texts": [],
        "activity": "",
    }
    with patch(
        "tools.windows_lab.streamers_alive.probe_streamers_down",
        return_value=fake,
    ):
        out = probe_heartbeat("Nougat32_3", root=data_root, save_shot=False)
    assert out.get("failing") is True
    assert "spinner" in str(out.get("reason") or "") or out.get("ok") is False


def test_preferred_local_atlanta_then_alabama():
    from tools.windows_lab.us_locals import preferred_local

    home = preferred_local("ABC", failover=False)
    assert home["market"] == "Atlanta"
    assert home["calls"] == "WSB"
    al = preferred_local("ABC", failover=True)
    assert al["market"] == "Birmingham"
    assert al["state"] == "AL"
    assert al["calls"] == "WBMA"


def test_score_local_search_prefers_atlanta_rejects_pluto():
    from tools.windows_lab.us_locals import _in_pack_epg, _score_local_search_title

    assert (
        _score_local_search_title(
            "GA | Atlanta | ABC WSB",
            calls="WSB",
            network="ABC",
            city="Atlanta",
        )
        >= 100
    )
    assert (
        _score_local_search_title(
            "IN | South Bend | CBS WSBT",
            calls="WSB",
            network="ABC",
            city="Atlanta",
        )
        < 0
    )
    assert (
        _score_local_search_title(
            "(PLUTO USA) CBS Sports HQ",
            calls="WSB",
            network="ABC",
            city="Atlanta",
        )
        < 0
    )
    assert _in_pack_epg(["PLUTO U.S.A.", "(PLUTO USA) Cheers", "No information"])
    assert not _in_pack_epg(["Favorites", "All channels", "US ABC SECTION"])


def test_guide_stuck_after_threshold(data_root: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("HUSH_GUIDE_STUCK_S", "10")
    monkeypatch.setenv("HUSH_FRAME_FREEZE_S", "999")
    from tools.windows_lab import heartbeat_fix as hb

    guide_probe = {
        "ok": True,
        "down": False,
        "reason": "streamers playing / home",
        "texts": ["SPORTSNET+", "No information", "6893", "SN+ 01 | 7:35 AM ET - Foo"],
        "activity": "mCurrentFocus=Window{x u0 ar.tvplayer.tv/ar.tvplayer.tv.ui.MainActivity}",
        "screenshot": None,
        "frame_score": {"verdict": "uncertain", "freeze": {"frozen": False}},
    }
    with patch(
        "tools.windows_lab.streamers_alive.probe_streamers_down",
        return_value=guide_probe,
    ):
        first = probe_heartbeat("Nougat32_1", root=data_root, save_shot=False)
        assert first.get("ui_kind") in {"guide", "guide_like", "empty_event_guide"}
        # Backdate kind_since past threshold.
        state = hb._load_state(data_root)
        state["instances"]["Nougat32_1"]["ui_kind_since"] = hb._now().timestamp() - 30
        hb._save_state(state, data_root)
        second = probe_heartbeat("Nougat32_1", root=data_root, save_shot=False)
    assert second.get("failing") is True
    assert "guide_stuck" in str(second.get("reason") or "")


def test_audio_peak_float_scaled_to_i16():
    """Process-loopback float peaks must not compare raw against int16 floor 500."""
    from tools.windows_lab.heartbeat_fix import _peak_as_i16

    assert _peak_as_i16(0.34) is not None
    assert _peak_as_i16(0.34) > 500.0  # would be false-lag without scale
    assert abs(_peak_as_i16(0.34) - 0.34 * 32767.0) < 1.0
    assert _peak_as_i16(11235.0) == 11235.0
    assert _peak_as_i16(None) is None


def test_menu_frozen_same_frames_one_minute(data_root: Path, monkeypatch: pytest.MonkeyPatch):
    """Identical search/menu frames for FRAME_FREEZE_S must fail (owner: 1 min static)."""
    monkeypatch.setenv("HUSH_GUIDE_STUCK_S", "999")
    monkeypatch.setenv("HUSH_SEARCH_STUCK_S", "999")
    monkeypatch.setenv("HUSH_FRAME_FREEZE_S", "60")
    from tools.windows_lab import heartbeat_fix as hb

    search_probe = {
        "ok": True,
        "down": False,
        "reason": "streamers playing / home",
        "texts": ["Search history", "Channels", "Programs", "Search", "No information"],
        "activity": "mCurrentFocus=Window{x u0 ar.tvplayer.tv/ar.tvplayer.tv.ui.MainActivity}",
        "screenshot": None,
        "frame_score": {"verdict": "uncertain", "freeze": {"frozen": True}},
    }
    with patch(
        "tools.windows_lab.streamers_alive.probe_streamers_down",
        return_value=search_probe,
    ):
        first = probe_heartbeat("Nougat32_3", root=data_root, save_shot=False)
        assert first.get("ui_kind") in {"search_ui", "search_hub"}
        state = hb._load_state(data_root)
        state["instances"]["Nougat32_3"]["freeze_since"] = hb._now().timestamp() - 65
        hb._save_state(state, data_root)
        second = probe_heartbeat("Nougat32_3", root=data_root, save_shot=False)
    assert second.get("failing") is True
    assert "menu_frozen" in str(second.get("reason") or "") or "frozen" in str(
        second.get("reason") or ""
    )


def test_fix_still_on_guide_runs_finish_open_and_fails(data_root: Path):
    """Retune that leaves the guide must finish-open then fail closed (never ok)."""
    from tools.windows_lab import heartbeat_fix as hb

    failing = {
        "ok": False,
        "failing": True,
        "reason": "guide_stuck:guide:120s>=90s",
        "instance_id": "Nougat32_1",
        "ui_kind": "guide",
        "picture": {"down": False, "ok": True, "final_kind": "guide"},
        "audio": None,
        "session_picture": None,
        "identity": {"network": "FOX", "calls": "WAGA"},
        "duplicate": {"duplicate": False, "conflicts": []},
    }
    after_guide = {
        "ok": True,
        "failing": False,
        "reason": "ok",
        "instance_id": "Nougat32_1",
        "ui_kind": "guide",
        "picture": {"down": False, "ok": True},
        "audio": None,
        "session_picture": None,
        "identity": {"network": "FOX", "calls": "WAGA"},
        "duplicate": {"duplicate": False, "conflicts": []},
        "audio_lag": {},
    }

    calls = {"n": 0}

    def fake_probe(instance_id, **kwargs):
        calls["n"] += 1
        return failing if calls["n"] == 1 else after_guide

    with (
        patch.object(hb, "probe_heartbeat", side_effect=fake_probe),
        patch(
            "tools.windows_lab.streamers_alive.recover_streamers",
            return_value={"ok": True, "after": {"reason": "ok"}},
        ),
        patch(
            "tools.windows_lab.streamers_recover.ensure_ready_for_open",
            return_value={"ok": True, "final_kind": "guide"},
        ),
        patch(
            "tools.windows_lab.heartbeat_fix.open_booth_local",
            return_value={
                "ok": True,
                "via": "us_section_grouper",
                "channel_title": "GA | Atlanta | FOX WAGA",
                "pick": {"market": "Atlanta", "calls": "WAGA", "network": "FOX"},
            },
        ),
        patch(
            "tools.windows_lab.streamers_recover.recover_loop",
            return_value={"ok": False, "final_kind": "guide"},
        ) as rec,
    ):
        out = fix_heartbeat("Nougat32_1", root=data_root, force=True)
    assert out.get("ok") is False
    report_steps = out.get("steps") or []
    assert any(s.get("step") == "finish_open_picture" for s in report_steps)
    assert "still_on_guide" in str((out.get("after") or {}).get("reason") or "")
    assert rec.called
