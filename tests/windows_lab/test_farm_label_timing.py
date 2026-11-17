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
    label_rate_history,
    load_summary,
    rebuild_snapshot,
    record_vision_rate_sample,
    rolling_vision_rate,
    timed_step,
)
import time


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
    # Content pace: live pictures at 5s wall / 5s hop = 1×; backlog includes tails.
    assert etas["pace"]["live_wall_per_content"] == pytest.approx(1.0, rel=0.01)
    assert etas["pace"]["wall_per_content"] is not None
    assert etas["pace"]["wall_per_content"] >= etas["pace"]["live_wall_per_content"]
    assert etas["total"]["content_left_h"] is not None
    assert etas["current_tape"]["content_left_s"] == pytest.approx(300 * 5.0, rel=0.01)
    assert "through a" in (etas["current_tape"].get("progress_plain") or "")
    assert "pictures" in (etas["current_tape"].get("progress_plain") or "")
    from tools.windows_lab.farm_label_timing import tape_through_plain

    assert tape_through_plain(pos_s=37.5 * 60, total_s=2 * 3600) == "~37.5 min through a ~2h recording"


def test_estimate_rejects_absurd_tiny_elapsed(data_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """1s elapsed with hundreds of hops must not report thousands of pictures/min."""
    monkeypatch.setenv("OHUSH_DATA_ROOT", str(data_root))
    live = {
        "active": True,
        "phase": "vision",
        "session": "sess_run",
        "hop_i": 200,
        "hop_of": 1440,
        "pct": 13.9,
        "step_elapsed_s": 1.0,
        "lock_age_s": 220.0,  # ~1.1s/picture — plausible after a restart
        "hop_s": 5.0,
    }
    etas = estimate_label_etas(live_job=live, hierarchy={"stages": {}, "queue": []}, timing={}, root=data_root)
    assert etas["assumptions"]["source"] == "lock_age"
    assert etas["sec_per_hop"] == pytest.approx(1.1, rel=0.05)
    assert etas["speed"]["pictures"]["live_per_min"] == pytest.approx(54.5, rel=0.1)
    assert etas["speed"]["pictures"]["live_per_min"] < 200


def test_estimate_resume_uses_hops_this_run(data_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Checkpoint resume: hop_i includes prior work; rate uses only new hops."""
    monkeypatch.setenv("OHUSH_DATA_ROOT", str(data_root))
    live = {
        "active": True,
        "phase": "vision",
        "session": "sess_run",
        "hop_i": 900,
        "hop_of": 1440,
        "resumed_hops": 700,
        "step_elapsed_s": 100.0,  # 200 new hops in 100s → 0.5s each → 120/min
        "hop_s": 5.0,
    }
    etas = estimate_label_etas(live_job=live, hierarchy={"stages": {}, "queue": []}, timing={}, root=data_root)
    assert etas["assumptions"]["source"] == "step_elapsed"
    assert etas["sec_per_hop"] == pytest.approx(0.5, rel=0.01)
    assert etas["speed"]["pictures"]["live_per_min"] == pytest.approx(120.0, rel=0.01)


def test_rolling_vision_rate_window(data_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OHUSH_DATA_ROOT", str(data_root))
    record_vision_rate_sample(hop_i=100, session="s1", root=data_root)
    time.sleep(0.05)
    # Backdate first sample so span ≥ RATE_MIN_SPAN_S without waiting 15s in CI.
    from tools.windows_lab.farm_label_timing import rate_ring_path
    import json

    path = rate_ring_path(data_root)
    blob = json.loads(path.read_text(encoding="utf-8"))
    blob["samples"][0]["t"] = float(blob["samples"][0]["t"]) - 20.0
    blob["samples"][0]["hop_i"] = 100
    path.write_text(json.dumps(blob) + "\n", encoding="utf-8")
    record_vision_rate_sample(hop_i=140, session="s1", root=data_root)  # +40 hops / ~20s → 120/min
    rate = rolling_vision_rate(window_s=60.0, root=data_root)
    assert rate is not None
    assert rate["hops"] == 40
    assert rate["hops_per_min"] == pytest.approx(120.0, rel=0.2)
    live = {
        "active": True,
        "phase": "vision",
        "session": "s1",
        "hop_i": 140,
        "hop_of": 1440,
        "resumed_hops": 100,
        "step_elapsed_s": 5.0,  # would be wrong alone; rolling should win
        "hop_s": 5.0,
    }
    etas = estimate_label_etas(live_job=live, hierarchy={"stages": {}, "queue": []}, timing={}, root=data_root)
    assert etas["assumptions"]["source"] == "rolling_window"
    assert etas["speed"]["pictures"]["live_per_min"] == pytest.approx(120.0, rel=0.25)
    hist = etas["speed"]["pictures"]["history"]
    assert isinstance(hist, list)
    assert len(hist) >= 1
    assert hist[-1]["per_min"] == pytest.approx(120.0, rel=0.25)


def test_label_rate_history_series(data_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OHUSH_DATA_ROOT", str(data_root))
    from tools.windows_lab.farm_label_timing import rate_ring_path

    # Seed a short climb: 10 hops every 20s wall → 30/min.
    t0 = time.monotonic()
    samples = []
    for i in range(6):
        samples.append(
            {
                "t": t0 - 100.0 + i * 20.0,
                "hop_i": 100 + i * 10,
                "session": "s_hist",
                "kind": "pictures",
            }
        )
    path = rate_ring_path(data_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"samples": samples}) + "\n", encoding="utf-8")
    hist = label_rate_history(lookback_s=20.0, root=data_root, kind="pictures")
    assert len(hist) >= 3
    assert all("age_s" in p and "per_min" in p for p in hist)
    assert hist[-1]["per_min"] == pytest.approx(30.0, rel=0.2)
    assert hist[0]["age_s"] >= hist[-1]["age_s"]
