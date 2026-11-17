"""UI dump contract: no silent empty hierarchy; emit + dump_dead classify."""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from tools.windows_lab.config import ensure_data_layout
from tools.windows_lab.instances import default_registry, save_registry
from tools.windows_lab.streamers_nav import classify_place
from tools.windows_lab.ui_dump import (
    DUMP_FAILED_MARKER,
    dump_health_summary,
    dump_meta_from_ui,
    dump_ui_hard,
    dump_ui_soft,
    is_dump_failed_ui,
    write_dump_failed_xml,
)


@pytest.fixture()
def data_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "OHushData"
    monkeypatch.setenv("OHUSH_DATA_ROOT", str(root))
    ensure_data_layout(root)
    save_registry(default_registry(), root)
    return root


def _inst() -> dict:
    return {"id": "Nougat32", "adb_serial": "127.0.0.1:5555", "adb_port": 5555}


def test_write_dump_failed_is_not_player(data_root: Path):
    dest = data_root / "work" / "probe" / "dead.xml"
    root = write_dump_failed_xml(dest, reason="null_root", error="null root node")
    texts = [
        (n.attrib.get("text") or "").strip()
        for n in root.iter("node")
        if (n.attrib.get("text") or "").strip()
    ]
    assert DUMP_FAILED_MARKER in texts[0]
    assert is_dump_failed_ui(root, texts)
    meta = dump_meta_from_ui(root)
    assert meta["dump_ok"] is False
    assert meta["dump_fabricated"] is True
    place = classify_place(texts, dump_ok=False, dump_reason="null_root")
    assert place["place"] == "dump_dead"
    assert place["place"] != "player_or_blank"


def test_empty_texts_without_marker_still_player_or_blank():
    # Real fullscreen may have empty a11y — only tagged soft-fail is dump_dead.
    place = classify_place([])
    assert place["place"] == "player_or_blank"


def test_hard_dump_null_root_raises_and_emits(data_root: Path):
    dest = data_root / "work" / "probe" / "hard.xml"
    calls: list[str] = []

    def fake_adb(_inst, argv, **_kw):
        if argv[:2] == ["shell", "uiautomator"]:
            return 0, "ERROR: null root node returned by UiAutomator."
        return 0, ""

    def fake_emit(event, **kwargs):
        calls.append(event)
        return {}

    with (
        patch("tools.windows_lab.instances.adb", side_effect=fake_adb),
        patch("tools.windows_lab.farm_ops.emit", side_effect=fake_emit),
        patch("tools.windows_lab.ui_dump.heal_adb_for_dump", return_value={"heal": "none", "streak": 1}),
    ):
        with pytest.raises(RuntimeError, match="null root|dump failed"):
            dump_ui_hard(_inst(), dest, root=data_root, caller="test", heal=True)
    assert "ui_dump_fail" in calls or "ui_dump_retry" in calls


def test_soft_dump_fabricates_tagged_not_silent(data_root: Path):
    dest = data_root / "work" / "probe" / "soft.xml"
    emits: list[str] = []

    def fake_hard(*_a, **_k):
        raise RuntimeError("uiautomator dump empty hierarchy dest=soft.xml nodes=1")

    def fake_emit(event, **kwargs):
        emits.append(event)
        return {}

    with (
        patch("tools.windows_lab.ui_dump.dump_ui_hard", side_effect=fake_hard),
        patch("tools.windows_lab.farm_ops.emit", side_effect=fake_emit),
        patch(
            "tools.windows_lab.ui_dump.heal_adb_for_dump",
            return_value={"heal": "connect_adb", "streak": 3, "steps": []},
        ),
        patch("tools.windows_lab.ui_dump.time.sleep", return_value=None),
    ):
        root = dump_ui_soft(_inst(), dest, tries=2, root=data_root, caller="test_soft")
    assert is_dump_failed_ui(root)
    assert dump_meta_from_ui(root)["dump_ok"] is False
    assert "ui_dump_soft_empty" in emits
    # Must not look like a healthy empty player dump (no marker).
    texts = [
        (n.attrib.get("text") or "").strip()
        for n in root.iter("node")
        if (n.attrib.get("text") or "").strip()
    ]
    assert any(DUMP_FAILED_MARKER in t for t in texts)
    place = classify_place(texts, dump_ok=False, dump_reason="empty_hierarchy")
    assert place["place"] == "dump_dead"


def test_dump_health_summary_reads_events(data_root: Path):
    log = data_root / "work" / "logs" / "farm_run.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    rows = [
        {"utc": now, "event": "ui_dump_soft_empty", "instance_id": "Nougat32", "detail": "null_root", "ok": False},
        {"utc": now, "event": "ui_dump_soft_empty", "instance_id": "Nougat32", "detail": "null_root", "ok": False},
        {"utc": now, "event": "ui_dump_soft_empty", "instance_id": "Nougat32", "detail": "null_root", "ok": False},
        {"utc": now, "event": "ui_dump_fail", "instance_id": "Nougat32_1", "detail": "empty_hierarchy", "ok": False},
    ]
    log.write_text("\n".join(__import__("json").dumps(r) for r in rows) + "\n", encoding="utf-8")
    summary = dump_health_summary(data_root, hours=24.0)
    assert summary["totals"]["soft_empty"] == 3
    assert "Nougat32" in summary["sick_instances"]


def test_ingest_ui_dump_health_todo(data_root: Path):
    from tools.windows_lab.open_model_todos import ingest_ui_dump_health, load

    summary = {
        "sick_instances": ["Nougat32"],
        "by_instance": {"Nougat32": {"soft_empty": 5, "fail": 2}},
        "circuits": {"Nougat32": {"circuit": "open", "streak": 5, "last_reason": "null_root"}},
    }
    out = ingest_ui_dump_health(summary, root=data_root)
    assert out
    data = load(data_root)
    events = [i.get("event") for i in (data.get("items") or [])]
    assert "ui_dump_sick" in events
