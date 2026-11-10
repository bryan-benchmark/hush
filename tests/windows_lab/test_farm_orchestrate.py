"""Three-op farm orchestration dashboard."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from tools.windows_lab.config import ensure_data_layout
from tools.windows_lab.farm_orchestrate import op1_record, op2_label, op3_human, orchestrate_status


@pytest.fixture()
def data_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "OHushData"
    monkeypatch.setenv("OHUSH_DATA_ROOT", str(root))
    ensure_data_layout(root)
    return root


def test_three_ops(data_root: Path):
    r = op1_record(data_root)
    assert r["op"] == 1 and "assignments" in r and "hierarchy" in r
    lab = op2_label(data_root, run_tick=False)
    assert lab["op"] == 2 and "behind" in lab
    hum = op3_human(data_root)
    assert hum["op"] == 3 and hum["required"] is False
    dash = orchestrate_status(data_root)
    assert "1_record" in dash["operations"]
    assert "2_label" in dash["operations"]
    assert "3_human" in dash["operations"]
