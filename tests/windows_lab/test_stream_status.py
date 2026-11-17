"""Stream uptime board + identity gate."""

from __future__ import annotations

from pathlib import Path

from tools.windows_lab.stream_status import (
    classify_root_cause,
    record,
    verify_local_identity,
    write_board,
)


def test_verify_local_identity_atlanta_ok():
    out = verify_local_identity(
        "GA | Atlanta | ABC WSB",
        network="ABC",
        calls="WSB",
        city="Atlanta",
    )
    assert out["ok"] is True
    assert out["root_cause"] == "ok"


def test_verify_local_identity_rejects_pluto_and_near_miss():
    bad = verify_local_identity(
        "(PLUTO USA) CBS Sports HQ",
        network="ABC",
        calls="WSB",
    )
    assert bad["ok"] is False
    assert bad["root_cause"] == "pluto_or_pack_epg"

    miss = verify_local_identity(
        "IN | South Bend | CBS WSBT",
        network="ABC",
        calls="WSB",
        city="Atlanta",
    )
    assert miss["ok"] is False
    assert miss["root_cause"] == "wrong_channel"


def test_classify_root_cause_audio_lag_and_spinner():
    assert classify_root_cause(ok=False, reason="audio_lag:peak=12") == "audio_lag"
    assert classify_root_cause(ok=False, picture_state="blue_spinner") == "picture_bad"
    assert classify_root_cause(ok=True) == "ok"
    assert classify_root_cause(ok=False, reason="duplicate_stream:same_number:1353@Nougat32") == "duplicate_stream"


def test_fleet_duplicate_and_filler_rotation(tmp_path: Path, monkeypatch):
    from tools.windows_lab import stream_status as ss
    from tools.windows_lab.stream_status import (
        find_duplicate_streams,
        normalize_program_key,
        pick_filler_network,
        record,
    )

    monkeypatch.setattr(ss, "ensure_data_layout", lambda root=None: tmp_path)
    (tmp_path / "indexes").mkdir(parents=True, exist_ok=True)

    assert normalize_program_key("College Football : Missouri at Georgia") == "missouri at georgia"

    record(
        "Nougat32",
        event="channel_open",
        ok=True,
        selected_title="GA | Atlanta | ABC WSB",
        network="ABC",
        calls="WSB",
        channel_number=1353,
        program_key="missouri at georgia",
        root=tmp_path,
        emit_farm_run=False,
    )
    # Peer must be live (up / locked / identity_live) to count as a duplicate.
    dup = find_duplicate_streams(
        "Nougat32_1",
        {"channel_number": 1353, "calls": "WSB", "program_key": "missouri at georgia"},
        root=tmp_path,
    )
    assert dup["duplicate"] is True
    # Peer on ABC → secondary must not also take ABC (sticky CBS/FOX/NBC ok).
    assert pick_filler_network("Nougat32_1", root=tmp_path, preferred="ABC") != "ABC"

    # Same national game on a different affiliate is still a duplicate.
    record(
        "Nougat32_3",
        event="channel_open",
        ok=True,
        selected_title="AK | Anchorage | NBC KTUU",
        network="NBC",
        calls="KTUU",
        channel_number=2101,
        program_key="notre dame at miami",
        root=tmp_path,
        emit_farm_run=False,
    )
    # Failed open must not leave a live identity that phantoms the fleet.
    record(
        "Nougat32_1",
        event="channel_open",
        ok=False,
        root_cause="open_failed",
        detail="calls_search_no_hit:WBRC",
        selected_title="GA | Atlanta | ABC WSB",
        network="ABC",
        calls="WSB",
        channel_number=1353,
        program_key="missouri at georgia",
        root=tmp_path,
        emit_farm_run=False,
    )
    from tools.windows_lab.stream_status import fleet_rows

    dead = next(r for r in fleet_rows(tmp_path) if r["instance_id"] == "Nougat32_1")
    assert dead.get("identity_live") is False
    assert dead.get("channel_number") is None
    phantom = find_duplicate_streams(
        "Nougat32",
        {"channel_number": 1353, "calls": "WSB", "program_key": "missouri at georgia"},
        root=tmp_path,
    )
    assert not any(c.get("instance_id") == "Nougat32_1" for c in phantom["conflicts"])

    import tools.windows_lab.instances as inst_mod
    import tools.windows_lab.locks as locks_mod

    monkeypatch.setattr(
        inst_mod,
        "list_instances",
        lambda root=None: [
            {"id": "Nougat32", "source_kind": "streamers", "enabled": True},
            {"id": "Nougat32_3", "source_kind": "streamers", "enabled": True},
        ],
    )
    monkeypatch.setattr(
        inst_mod,
        "list_running_engines",
        lambda: ["Nougat32", "Nougat32_3"],
    )
    monkeypatch.setattr(locks_mod, "get_lock", lambda *a, **k: None)

    same_game = find_duplicate_streams(
        "Nougat32",
        {
            "channel_number": 1757,
            "calls": "WXIA",
            "network": "NBC",
            "program_key": "notre dame at miami",
        },
        root=tmp_path,
    )
    assert same_game["duplicate"] is True
    assert any("same_program" in str(c.get("why")) for c in same_game["conflicts"])


def test_enforce_unique_programs_dry_run(tmp_path: Path, monkeypatch):
    from tools.windows_lab import stream_status as ss
    from tools.windows_lab.stream_status import enforce_unique_programs, record

    monkeypatch.setattr(ss, "ensure_data_layout", lambda root=None: tmp_path)
    (tmp_path / "indexes").mkdir(parents=True, exist_ok=True)

    record(
        "Nougat32",
        event="channel_open",
        ok=True,
        selected_title="GA | Atlanta | NBC WXIA",
        network="NBC",
        calls="WXIA",
        program_key="notre dame at miami",
        root=tmp_path,
        emit_farm_run=False,
    )
    record(
        "Nougat32_3",
        event="channel_open",
        ok=True,
        selected_title="AK | Anchorage | NBC KTUU",
        network="NBC",
        calls="KTUU",
        program_key="notre dame at miami",
        root=tmp_path,
        emit_farm_run=False,
    )

    def fake_probe(instance_id, *, root=None, tap_for_chrome=True):
        row = next(r for r in ss.fleet_rows(root) if r.get("instance_id") == instance_id)
        return {
            "ok": True,
            "identity": {
                "program_key": row.get("program_key"),
                "calls": row.get("calls"),
                "network": row.get("network"),
                "selected_title": row.get("selected_title"),
            },
        }

    monkeypatch.setattr(ss, "probe_instance_identity", fake_probe)
    import tools.windows_lab.locks as locks_mod

    monkeypatch.setattr(locks_mod, "get_lock", lambda *a, **k: None)

    out = enforce_unique_programs(
        root=tmp_path,
        instance_ids=["Nougat32", "Nougat32_3"],
        execute=False,
    )
    assert out["duplicates_found"] >= 1
    actions = {a["instance_id"]: a["action"] for a in out["actions"]}
    assert "keep" in actions.values()
    assert "would_retune" in actions.values()


def test_enforce_unique_same_network_null_program(tmp_path: Path, monkeypatch):
    """Two ABCs with null program_key must still count as duplicates."""
    from tools.windows_lab import stream_status as ss
    from tools.windows_lab.stream_status import enforce_unique_programs, find_duplicate_streams, record

    monkeypatch.setattr(ss, "ensure_data_layout", lambda root=None: tmp_path)
    (tmp_path / "indexes").mkdir(parents=True, exist_ok=True)

    record(
        "Nougat32",
        event="channel_open",
        ok=True,
        selected_title="GA | Atlanta | ABC WSB",
        network="ABC",
        calls="WSB",
        program_key=None,
        root=tmp_path,
        emit_farm_run=False,
    )
    record(
        "Nougat32_1",
        event="channel_open",
        ok=True,
        selected_title="GA | Atlanta | ABC WSB",
        network="ABC",
        calls="WSB",
        program_key=None,
        root=tmp_path,
        emit_farm_run=False,
    )

    dup = find_duplicate_streams(
        "Nougat32_1",
        {"network": "ABC", "calls": "WSB", "selected_title": "GA | Atlanta | ABC WSB"},
        root=tmp_path,
    )
    assert dup["duplicate"] is True

    def fake_probe(instance_id, *, root=None, tap_for_chrome=True):
        row = next(r for r in ss.fleet_rows(root) if r.get("instance_id") == instance_id)
        return {
            "ok": True,
            "identity": {
                "program_key": row.get("program_key"),
                "calls": row.get("calls"),
                "network": row.get("network"),
                "selected_title": row.get("selected_title"),
            },
        }

    monkeypatch.setattr(ss, "probe_instance_identity", fake_probe)
    import tools.windows_lab.locks as locks_mod

    monkeypatch.setattr(locks_mod, "get_lock", lambda *a, **k: None)
    import tools.windows_lab.instances as inst_mod

    monkeypatch.setattr(
        inst_mod,
        "list_instances",
        lambda root=None: [
            {"id": "Nougat32", "source_kind": "streamers", "enabled": True},
            {"id": "Nougat32_1", "source_kind": "streamers", "enabled": True},
        ],
    )

    out = enforce_unique_programs(
        root=tmp_path,
        instance_ids=["Nougat32", "Nougat32_1"],
        execute=False,
    )
    assert out["duplicates_found"] >= 1
    assert any(a.get("action") == "would_retune" for a in out["actions"])


def test_find_duplicate_ignores_disabled_clone(tmp_path: Path, monkeypatch):
    """Parked enabled=false peers must not phantom-dup the live fleet."""
    from tools.windows_lab import stream_status as ss
    from tools.windows_lab.stream_status import find_duplicate_streams, record
    import tools.windows_lab.instances as inst_mod

    monkeypatch.setattr(ss, "ensure_data_layout", lambda root=None: tmp_path)
    (tmp_path / "indexes").mkdir(parents=True, exist_ok=True)

    record(
        "Nougat32",
        event="channel_open",
        ok=True,
        selected_title="GA | Atlanta | FOX WAGA",
        network="FOX",
        calls="WAGA",
        program_key="new england patriots vs detroit lions",
        root=tmp_path,
        emit_farm_run=False,
    )
    record(
        "Nougat32_3",
        event="channel_open",
        ok=True,
        selected_title="FL | Tampa | FOX WTVT",
        network="FOX",
        calls="WTVT",
        program_key="new england patriots vs detroit lions",
        root=tmp_path,
        emit_farm_run=False,
    )
    monkeypatch.setattr(
        inst_mod,
        "list_instances",
        lambda root=None: [
            {"id": "Nougat32", "source_kind": "streamers", "enabled": True},
            {"id": "Nougat32_3", "source_kind": "streamers", "enabled": False},
        ],
    )
    monkeypatch.setattr(inst_mod, "list_running_engines", lambda: ["Nougat32"])
    import tools.windows_lab.locks as locks_mod

    monkeypatch.setattr(locks_mod, "get_lock", lambda *a, **k: None)

    dup = find_duplicate_streams(
        "Nougat32",
        {
            "network": "FOX",
            "calls": "WAGA",
            "program_key": "new england patriots vs detroit lions",
        },
        root=tmp_path,
    )
    assert not any(c.get("instance_id") == "Nougat32_3" for c in dup["conflicts"])
    assert dup["duplicate"] is False


def test_record_and_board(tmp_path: Path, monkeypatch):
    from tools.windows_lab import stream_status as ss

    monkeypatch.setattr(ss, "ensure_data_layout", lambda root=None: tmp_path)
    (tmp_path / "indexes").mkdir(parents=True, exist_ok=True)
    (tmp_path / "work" / "logs").mkdir(parents=True, exist_ok=True)

    row = record(
        "Nougat32_1",
        event="channel_open",
        ok=True,
        detail="Atlanta WSB via calls_search",
        selected_title="GA | Atlanta | ABC WSB",
        via="calls_search",
        network="ABC",
        market="Atlanta",
        calls="WSB",
        root=tmp_path,
        emit_farm_run=False,
    )
    assert row["up"] is True
    assert row["root_cause"] == "ok"
    board = write_board(tmp_path)
    assert Path(board["board"]).is_file()
    text = Path(board["board"]).read_text(encoding="utf-8")
    assert "Nougat32_1" in text
    assert "Atlanta" in text
