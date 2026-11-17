"""Open-model policy todos + identity health receipts."""

from __future__ import annotations

from pathlib import Path


def test_ingest_policy_and_fleet(tmp_path: Path, monkeypatch):
    from tools.windows_lab import open_model_todos as om
    from tools.windows_lab import stream_status as ss

    monkeypatch.setattr(om, "ensure_data_layout", lambda root=None: tmp_path)
    monkeypatch.setattr(ss, "ensure_data_layout", lambda root=None: tmp_path)
    (tmp_path / "indexes").mkdir(parents=True, exist_ok=True)

    created = om.ingest_policy(
        "duplicate_stream",
        instance_id="Nougat32_3",
        detail="same_program:notre dame",
        root=tmp_path,
    )
    assert created["ok"] is True
    assert created["todo"]["event"] == "duplicate_stream"
    assert created["todo"]["priority"] >= 93

    ss.record(
        "Nougat32_1",
        event="channel_open",
        ok=False,
        root_cause="pluto_or_pack_epg",
        selected_title="(PLUTO USA) junk",
        detail="pluto",
        root=tmp_path,
        emit_farm_run=False,
    )
    # Force bad root on fleet for ingest_from_fleet
    row = ss.record(
        "Nougat32",
        event="heartbeat_probe",
        ok=False,
        root_cause="audio_lag",
        detail="audio_lag:peak=1",
        root=tmp_path,
        emit_farm_run=False,
    )
    assert row["root_cause"] == "audio_lag"

    fleet = om.ingest_from_fleet(tmp_path)
    events = {x["todo"]["event"] for x in fleet}
    assert "audio_lag" in events or "pluto_or_pack_epg" in events


def test_failed_claim_releases_for_retry(tmp_path: Path, monkeypatch):
    from tools.windows_lab import open_model_todos as om

    monkeypatch.setattr(om, "ensure_data_layout", lambda root=None: tmp_path)
    (tmp_path / "indexes").mkdir(parents=True, exist_ok=True)

    om.ingest_policy("duplicate_stream", instance_id="Nougat32", detail="dup", root=tmp_path)

    def boom(todo, *, root=None):
        return {"ok": False, "lesson": "still duplicate", "steps": []}

    monkeypatch.setattr(om, "attempt_fix", boom)
    out = om.desk_work_once(root=tmp_path, owner="desk")
    assert out["ok"] is False
    data = om.load(tmp_path)
    item = data["items"][0]
    assert item["status"] == "open", "failed fix must release claim"
    assert item.get("claim") is None


def test_identity_on_air_health_requires_probe(tmp_path: Path, monkeypatch):
    from tools.windows_lab import farm_loop as fl

    monkeypatch.setattr(fl, "ensure_data_layout", lambda root=None: tmp_path)
    (tmp_path / "indexes").mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(
        fl,
        "on_air_health",
        lambda instance_id, root=None: {
            "ok": True,
            "instance_id": instance_id,
            "reason": "base ok",
        },
    )

    class FakeHb:
        @staticmethod
        def probe_heartbeat(instance_id, **kwargs):
            return {
                "ok": False,
                "failing": True,
                "reason": "duplicate_stream:same_program:x@Nougat32",
                "identity": {"program_key": "x", "calls": "KTUU"},
                "duplicate": {"duplicate": True},
            }

    monkeypatch.setitem(__import__("sys").modules, "tools.windows_lab.heartbeat_fix", FakeHb)
    # Also patch import path used inside identity_on_air_health
    import tools.windows_lab.heartbeat_fix as hb

    monkeypatch.setattr(
        hb,
        "probe_heartbeat",
        FakeHb.probe_heartbeat,
    )

    # Avoid real stream_status side effects exploding
    import tools.windows_lab.stream_status as ss

    monkeypatch.setattr(ss, "ensure_data_layout", lambda root=None: tmp_path)
    monkeypatch.setattr(
        ss,
        "record",
        lambda *a, **k: {"ok": False},
    )
    monkeypatch.setattr(ss, "classify_root_cause", lambda **k: "duplicate_stream")

    out = fl.identity_on_air_health("Nougat32_3", root=tmp_path)
    assert out["ok"] is False
    assert "duplicate_stream" in str(out["reason"])
    assert out["receipt"]["probe_ok"] is False
    assert out["receipt"]["base_ok"] is True
