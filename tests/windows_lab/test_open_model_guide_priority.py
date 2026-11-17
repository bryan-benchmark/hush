"""Open-model: prefer guide_stuck; never resolve while still on guide; skip disabled."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from tools.windows_lab.config import ensure_data_layout
from tools.windows_lab.instances import default_registry, save_registry, upsert_instance
from tools.windows_lab.open_model_todos import (
    attempt_fix,
    ingest_hush,
    next_open,
    reprioritize,
    resolve_disabled_instance_todos,
)


@pytest.fixture()
def data_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "OHushData"
    monkeypatch.setenv("OHUSH_DATA_ROOT", str(root))
    ensure_data_layout(root)
    save_registry(default_registry(), root)
    upsert_instance("Nougat32", {"enabled": True, "source_kind": "streamers"}, root)
    upsert_instance("Nougat32_1", {"enabled": True, "source_kind": "streamers"}, root)
    upsert_instance("Nougat32_3", {"enabled": False, "source_kind": "streamers"}, root)
    return root


def test_next_open_prefers_guide_stuck_when_on_guide(data_root: Path):
    ingest_hush(
        "wrong_channel",
        key="Nougat32_1",
        detail="landed_on_WTVT",
        meta={"instance_id": "Nougat32_1"},
        root=data_root,
    )
    ingest_hush(
        "guide_stuck",
        key="Nougat32_1",
        detail="guide_stuck:guide:200s",
        meta={"instance_id": "Nougat32_1"},
        root=data_root,
    )
    with patch(
        "tools.windows_lab.open_model_todos._instance_guide_ui",
        side_effect=lambda iid, root=None: "guide" if iid == "Nougat32_1" else None,
    ):
        top = next_open(data_root)
    assert top is not None
    assert top.get("event") == "guide_stuck"


def test_resolve_disabled_instance_todos(data_root: Path):
    ingest_hush(
        "wrong_channel",
        key="Nougat32_3",
        detail="parked ghost",
        meta={"instance_id": "Nougat32_3"},
        root=data_root,
    )
    out = resolve_disabled_instance_todos(data_root)
    assert out["count"] >= 1
    top = next_open(data_root)
    assert top is None or _todo_key_instance(top) != "Nougat32_3"


def _todo_key_instance(todo: dict) -> str:
    return str((todo.get("meta") or {}).get("instance_id") or todo.get("key") or "")


def test_attempt_fix_does_not_resolve_while_on_guide(data_root: Path):
    row = ingest_hush(
        "guide_stuck",
        key="Nougat32_1",
        detail="guide_stuck",
        meta={"instance_id": "Nougat32_1"},
        root=data_root,
    )["todo"]
    with (
        patch(
            "tools.windows_lab.heartbeat_fix.fix_instance_if_failing",
            return_value={"ok": True, "reason": "ok"},
        ),
        patch(
            "tools.windows_lab.heartbeat_fix.probe_heartbeat",
            return_value={
                "ok": True,
                "ui_kind": "guide",
                "reason": "ok",
                "identity": {},
            },
        ),
    ):
        out = attempt_fix(row, root=data_root)
    assert out.get("resolved") is not True
    assert "still_on_guide" in str(out.get("lesson") or "")


def test_reprioritize_skips_disabled_fleet_keys(data_root: Path):
    ingest_hush(
        "duplicate_stream",
        key="Nougat32_3",
        detail="ghost",
        meta={"instance_id": "Nougat32_3"},
        root=data_root,
    )
    with patch(
        "tools.windows_lab.open_model_todos.ingest_from_audit",
        return_value=[],
    ), patch(
        "tools.windows_lab.open_model_todos.ingest_from_fleet",
        return_value=[],
    ):
        out = reprioritize(data_root)
    assert int(out.get("disabled_resolved") or 0) >= 1
