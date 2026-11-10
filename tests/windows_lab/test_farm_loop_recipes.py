"""Farm loop recipe stubs refuse unsafe apply."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from tools.windows_lab.channel import apply_recipe, load_recipe
from tools.windows_lab.config import ensure_data_layout
from tools.windows_lab.farm_loop import ensure_local_recipe_stubs, ensure_on_air_recipe


@pytest.fixture()
def data_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "OHushData"
    monkeypatch.setenv("OHUSH_DATA_ROOT", str(root))
    ensure_data_layout(root)
    return root


def test_on_air_and_stubs(data_root: Path):
    ensure_on_air_recipe(data_root)
    ensure_local_recipe_stubs(data_root)
    on_air = load_recipe("ON_AIR_CONTINUE", data_root)
    assert on_air["verified"] is True
    assert on_air["apply_allowed"] is False
    stub = load_recipe("CBS_LOCAL_FLAGSHIP", data_root)
    assert stub["apply_allowed"] is False
    with pytest.raises(RuntimeError, match="not apply-safe"):
        apply_recipe(channel_id="CBS_LOCAL_FLAGSHIP", instance_id="Nougat32", root=data_root, dry_run=True)
