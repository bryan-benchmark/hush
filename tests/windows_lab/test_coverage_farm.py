"""Coverage farm plan/board/seed (no BlueStacks / Ollama required)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from tools.windows_lab.config import ensure_data_layout
from tools.windows_lab.coverage_farm import (
    build_capture_plan,
    build_coverage_board,
    capacity_report,
    daypart_for,
    dispatch_report,
    farm_label_dir,
    fill_order_for,
    hierarchy_snapshot,
    seed_queue_from_streamers_takes,
)


@pytest.fixture()
def data_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "OHushData"
    monkeypatch.setenv("OHUSH_DATA_ROOT", str(root))
    ensure_data_layout(root)
    return root


def test_daypart_buckets():
    assert daypart_for.__name__ == "daypart_for"
    dp = daypart_for()
    assert dp in {"morning", "afternoon", "primetime", "late"}


def test_hierarchy_has_fill_order():
    snap = hierarchy_snapshot()
    assert snap["fill_order"][0] in {"main_linear", "aux_sports", "main_news"}
    assert "New York" in snap["priority_markets"]
    assert fill_order_for() == snap["fill_order"]


def test_plan_and_board(data_root: Path):
    plan = build_capture_plan(data_root, chunk_minutes=15)
    assert plan["version"] == 1
    assert "assignments" in plan
    assert (data_root / "indexes" / "capture_plan.json").is_file()
    board = build_coverage_board(data_root)
    assert "slots" in board
    assert (data_root / "indexes" / "COVERAGE_BOARD.md").is_file()
    cap = capacity_report(data_root)
    assert cap["max_concurrent_streamers"] >= 2
    disp = dispatch_report(data_root, dry_run=True)
    assert "steps" in disp


def test_seed_queue_from_synthetic_take(data_root: Path):
    take = data_root / "work" / "capture" / "streamers" / "20261110T1200Z_test"
    take.mkdir(parents=True)
    aid = {
        "session": "20261110T1200Z_test",
        "recorded_utc": "2026-11-10T12:00:00Z",
        "guide": {"name": "(PLUTO USA) CBS Sports HQ", "group": "PLUTO U.S.A."},
        "media": {"duration_s": 60},
        "timeline": [
            {"t_s": 0, "kind": "commercial", "brand": "TestCo", "notes": "ad"},
            {"t_s": 20, "kind": "program_studio", "notes": "desk"},
            {"t_s": 40, "kind": "promo_show", "notes": "promo"},
        ],
    }
    (take / "label_aid.json").write_text(json.dumps(aid), encoding="utf-8")
    (take / "audio.wav").write_bytes(b"RIFF")  # placeholder; UI needs real wav later
    out = seed_queue_from_streamers_takes(data_root)
    assert out["clips"] == 3
    queue = (farm_label_dir(data_root) / "queue.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(queue) == 3
    key = (farm_label_dir(data_root) / "key.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(key) == 3
