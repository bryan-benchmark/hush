"""Overnight verdict audit board."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.windows_lab.config import ensure_data_layout
from tools.windows_lab.farm_verdict_audit import (
    append_verdict_tick,
    backlog_hierarchy,
    write_overnight_board,
)


@pytest.fixture()
def data_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "OHushData"
    monkeypatch.setenv("OHUSH_DATA_ROOT", str(root))
    ensure_data_layout(root)
    return root


def test_append_tick_writes_board(data_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OHUSH_DATA_ROOT", str(data_root))
    path = append_verdict_tick(
        {
            "ok": True,
            "trigger": "overnight",
            "sessions": ["sess_a"],
            "sessions_n": 1,
            "consensus_locked": 3,
            "disagree_hops": 2,
            "skip_reason": None,
            "why": "test",
        },
        root=data_root,
    )
    assert path.is_file()
    rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(rows) == 1
    assert rows[0]["consensus_locked"] == 3
    board = write_overnight_board(root=data_root)
    assert board["ticks_today"] >= 1
    md = data_root / "indexes" / "farm_labels" / "OVERNIGHT_VERDICT.md"
    assert md.is_file()
    assert "Consensus locked today" in md.read_text(encoding="utf-8")


def test_backlog_hierarchy_funnel(data_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OHUSH_DATA_ROOT", str(data_root))
    cap = data_root / "work" / "capture" / "streamers"
    for name in ("sess_done", "sess_gap", "sess_run"):
        d = cap / name
        d.mkdir(parents=True)
        (d / "label_manifest.json").write_text("{}", encoding="utf-8")
        (d / "audio.wav").write_bytes(b"RIFF")
    audit = data_root / "indexes" / "farm_labels" / "audit"
    done = audit / "sess_done"
    done.mkdir(parents=True)
    for f in ("hops_vision.jsonl", "hops_acoustic.jsonl", "hops.jsonl"):
        (done / f).write_text("{}\n", encoding="utf-8")
    (done / "CONSENSUS_LOCK.json").write_text(
        json.dumps({"locked_n": 2, "hop_summary": {"n_hops": 10, "n_disagree_hops": 1}}),
        encoding="utf-8",
    )
    h = backlog_hierarchy(
        root=data_root,
        live_job={"active": True, "session": "sess_run", "phase": "vision"},
        queue_limit=10,
    )
    assert h["prepared_n"] == 3
    funnel = h["funnel"]
    assert funnel["finished"] == 1
    assert funnel["working_now"] == 1
    assert funnel["waiting_for_pictures"] == 1
    assert funnel["left"] == 2
    assert "12 of" not in funnel["plain"]  # uses real counts
    assert "1 of 3" in funnel["plain"] or "finished" in funnel["plain"].lower()
    assert h["stages"]["running"] == 1
    assert h["stages"]["need_vision"] == 1
    assert h["stages"]["done"] == 1
    assert h["queue"][0]["session"] == "sess_run"
    assert h["queue"][0]["status"] == "running"
