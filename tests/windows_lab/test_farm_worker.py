"""Farm worker backlog thresholds."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from tools.windows_lab.config import ensure_data_layout
from tools.windows_lab.farm_worker import backlog_report


@pytest.fixture()
def data_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "OHushData"
    monkeypatch.setenv("OHUSH_DATA_ROOT", str(root))
    ensure_data_layout(root)
    return root


def test_backlog_ok_when_empty(data_root: Path):
    report = backlog_report(data_root)
    assert report["level"] == "ok"
    assert report["human_needed"] is False
    assert report["more_gpu_needed"] is False
