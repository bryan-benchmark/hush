"""Player 0 / player 1 aliases for BlueStacks Nougat fleet engines."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.windows_lab.config import ensure_data_layout
from tools.windows_lab.instances import (
    get_instance,
    list_instances,
    normalize_instance_id,
    player_index,
    player_label,
    save_registry,
)
from tools.windows_lab.locks import acquire, get_lock, release


@pytest.fixture()
def data_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "OHushData"
    monkeypatch.setenv("OHUSH_DATA_ROOT", str(root))
    ensure_data_layout(root)
    save_registry(
        {
            "instances": {
                "Nougat32": {"engine": "Nougat32", "enabled": True, "source_kind": "streamers"},
                "Nougat32_1": {"engine": "Nougat32_1", "enabled": True, "source_kind": "streamers"},
                "Nougat32_3": {"engine": "Nougat32_3", "enabled": False, "source_kind": "streamers"},
                "Tiramisu64": {"engine": "Tiramisu64", "enabled": False, "source_kind": "streamers"},
            }
        },
        root,
    )
    return root


def test_player_indices_are_contiguous(data_root: Path) -> None:
    assert player_index("Nougat32", data_root) == 0
    assert player_index("Nougat32_1", data_root) == 1
    assert player_index("Nougat32_3", data_root) == 2
    assert player_label("Nougat32_3", data_root) == "player 2"
    assert player_index("Tiramisu64", data_root) is None


def test_aliases_resolve(data_root: Path) -> None:
    assert normalize_instance_id("player 0", data_root) == "Nougat32"
    assert normalize_instance_id("player1", data_root) == "Nougat32_1"
    assert normalize_instance_id("p2", data_root) == "Nougat32_3"
    assert normalize_instance_id("Nougat32_1", data_root) == "Nougat32_1"
    row = get_instance("player 0", data_root)
    assert row["id"] == "Nougat32"
    assert row["player"] == 0
    assert row["player_label"] == "player 0"
    assert row["requested_as"] == "player 0"


def test_list_instances_includes_player_fields(data_root: Path) -> None:
    rows = list_instances(data_root)
    by_id = {r["id"]: r for r in rows}
    assert by_id["Nougat32"]["player_label"] == "player 0"
    assert by_id["Nougat32_1"]["player"] == 1


def test_locks_share_engine_key(data_root: Path) -> None:
    ok, row = acquire("streamers", "player 0", session_id="starting_test", root=data_root)
    assert ok
    assert row["resource_id"] == "Nougat32"
    assert get_lock("streamers", "Nougat32", root=data_root)
    assert get_lock("streamers", "player 0", root=data_root)
    release("streamers", "player 0", root=data_root)
    assert get_lock("streamers", "Nougat32", root=data_root) is None
