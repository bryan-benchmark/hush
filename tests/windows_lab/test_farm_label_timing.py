"""Per-step label timing ledger."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.windows_lab.config import ensure_data_layout
from tools.windows_lab.farm_label_timing import (
    begin_step,
    end_step,
    estimate_label_etas,
    load_summary,
    rebuild_snapshot,
    timed_step,
)


@pytest.fixture()
def data_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "OHushData"
    monkeypatch.setenv("OHUSH_DATA_ROOT", str(root))
    ensure_data_layout(root)
    return root


def test_timed_steps_rollup(data_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OHUSH_DATA_ROOT", str(data_root))
    begin_step("sess_a", "vision", hop_of=10)
    row = end_step("sess_a", "vision", ok=True, hop_of=10)
    assert row["duration_s"] is not None
    assert row["duration_s"] >= 0
    with timed_step("sess_a", "acoustic"):
        pass
    with timed_step("sess_a", "combine"):
        pass
    with timed_step("sess_a", "consensus"):
        pass
    snap = rebuild_snapshot(root=data_root)
    assert snap["by_step"]["vision"]["n"] == 1
    assert snap["by_session"]["sess_a"]["complete"] is True
    assert snap["totals"]["sessions_complete"] == 1
    ledger = data_root / "indexes" / "farm_labels" / "audit" / "LABEL_TIMING.jsonl"
    lines = [json.loads(l) for l in ledger.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lines) == 4
    loaded = load_summary(root=data_root)
    assert loaded["totals"]["rows"] == 4


def test_end_without_begin_accepts_duration(data_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OHUSH_DATA_ROOT", str(data_root))
    row = end_step("sess_b", "asr", ok=True, duration_s=12.5, source="manual")
    assert row["duration_s"] == 12.5
    snap = load_summary(root=data_root)
    assert snap["by_step"]["asr"]["n"] == 1


def test_estimate_label_etas_current_and_total(data_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OHUSH_DATA_ROOT", str(data_root))
    live = {
        "active": True,
        "phase": "vision",
        "session": "sess_run",
        "hop_i": 100,
        "hop_of": 400,
        "pct": 25.0,
        "step_elapsed_s": 500.0,
        "hop_s": 5.0,
    }
    hierarchy = {
        "stages": {"need_vision": 2, "left": 3, "running": 1, "done": 0},
        "queue": [
            {"session": "sess_run", "status": "running", "next": "vision", "n_hops": 400},
            {"session": "sess_b", "status": "queued", "next": "vision", "n_hops": 200},
            {"session": "sess_c", "status": "queued", "next": "vision", "n_hops": 200},
        ],
    }
    etas = estimate_label_etas(live_job=live, hierarchy=hierarchy, timing={}, root=data_root)
    assert etas["current_session"]["remaining_s"] > 0
    assert etas["sec_per_hop"] == pytest.approx(5.0, rel=0.01)
    assert etas["total"]["remaining_s"] > etas["current_session"]["remaining_s"]
    assert etas["per_session_avg_s"] is not None
    assert hierarchy["queue"][1]["eta_s"] > 0
