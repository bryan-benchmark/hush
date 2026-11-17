"""Label audit trail + morning review batch."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from tools.windows_lab.config import ensure_data_layout
from tools.windows_lab.coverage_farm import farm_label_dir
from tools.windows_lab.farm_label_audit import (
    append_draft_events,
    apply_morning_batch,
    atomic_write_jsonl,
    review_priority,
    write_daily_digest,
)
from tools.windows_lab.farm_worker import backlog_report


@pytest.fixture()
def data_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "OHushData"
    monkeypatch.setenv("OHUSH_DATA_ROOT", str(root))
    ensure_data_layout(root)
    return root


def test_atomic_write_and_append_audit(data_root: Path):
    label = farm_label_dir(data_root)
    key = label / "key.jsonl"
    atomic_write_jsonl(key, [{"clip": "a", "ask": "review"}, {"clip": "b", "ask": "needs_human"}])
    rows = [json.loads(l) for l in key.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert [r["clip"] for r in rows] == ["a", "b"]

    path = append_draft_events(
        [
            {"clip": "a", "ask": "review", "bucket": "paid_ad", "confidence": "high", "session": "s1"},
            {"clip": "b", "ask": "needs_human", "bucket": "uncertain", "session": "s1"},
        ],
        root=data_root,
        tick_id="tick-1",
    )
    assert path.is_file()
    events = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(events) == 2
    assert events[0]["tick_id"] == "tick-1"
    assert events[0]["clip"] == "a"
    # Second tick appends — never rewrites history.
    append_draft_events([{"clip": "c", "ask": "review"}], root=data_root, tick_id="tick-2")
    events2 = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(events2) == 3


def test_review_priority_tiers():
    assert review_priority({"ask": "review", "bucket": "paid_ad", "confidence": "high"}) == 8
    assert review_priority({"ask": "review", "bucket": "uncertain"}) == 24
    assert (
        review_priority({"ask": "needs_human", "why": "no_transcript_and_no_visual"}) == 48
    )
    assert review_priority({"ask": "skip", "why": "skip_black_silent"}) == 99
    assert review_priority({"ask": "optional_confirm"}) == 90
    assert review_priority({"ask": "locked", "gold": True}) is None


def test_black_still_helper(tmp_path: Path):
    from PIL import Image

    from tools.windows_lab.farm_draft import is_black_or_corrupt_still

    black = tmp_path / "black.jpg"
    Image.new("RGB", (64, 36), (0, 0, 0)).save(black)
    assert is_black_or_corrupt_still(black) == "black"
    green = tmp_path / "green.jpg"
    Image.new("RGB", (64, 36), (20, 200, 20)).save(green)
    assert is_black_or_corrupt_still(green) == "green_corrupt"
    pic = tmp_path / "pic.jpg"
    Image.new("RGB", (64, 36), (180, 90, 40)).save(pic)
    assert is_black_or_corrupt_still(pic) is None


def test_retriage_lifts_boundary_with_asr(data_root: Path):
    from tools.windows_lab.farm_label_audit import retriage_needs_human

    label = farm_label_dir(data_root)
    (label / "key.jsonl").write_text(
        json.dumps(
            {
                "clip": "b1",
                "ask": "needs_human",
                "bucket": "uncertain",
                "kind": "unknown",
                "confidence": "low",
                "why": "stills_disagree_possible_boundary",
                "whisper_text": "It's hump day. Get happy to get Geico.",
                "visual_text": "camel office commercial",
                "asr_empty": False,
            }
        )
        + "\n"
        + json.dumps(
            {
                "clip": "b2",
                "ask": "needs_human",
                "bucket": "uncertain",
                "why": "no_transcript_and_no_visual",
                "whisper_text": "",
                "asr_empty": True,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (label / "queue.jsonl").write_text(
        json.dumps({"clip": "b1", "session": "s", "t0": 0, "t1": 10, "priority": 10, "ask": "needs_human"})
        + "\n"
        + json.dumps({"clip": "b2", "session": "s", "t0": 10, "t1": 20, "priority": 10, "ask": "needs_human"})
        + "\n",
        encoding="utf-8",
    )
    out = retriage_needs_human(data_root)
    assert out["lifted_to_review"] == 1
    assert out["lexicon_rescued"] >= 1
    keys = {
        json.loads(l)["clip"]: json.loads(l)
        for l in (label / "key.jsonl").read_text(encoding="utf-8").splitlines()
        if l.strip()
    }
    assert keys["b1"]["ask"] == "review"
    assert keys["b1"]["bucket"] == "paid_ad"
    # Empty evidence with no still → skip (black/silent dead air), not /farm work.
    assert keys["b2"]["ask"] == "skip"


def test_morning_batch_parks_overflow():
    rows = [
        {"clip": f"c{i}", "ask": "needs_human", "priority": 10, "session": "s", "t0": float(i)}
        for i in range(5)
    ]
    batch = apply_morning_batch(rows, budget=2, day_et="2026-11-15")
    assert batch["active"] == 2
    assert batch["parked"] == 3
    assert sum(1 for r in rows if r.get("review_batch") == "active") == 2
    assert all(r["priority"] >= 40 for r in rows if r.get("review_batch") == "parked")


def test_backlog_gpu_flag_is_prepare_not_review(data_root: Path):
    label = farm_label_dir(data_root)
    # Huge review pile alone must not mean "need GPU".
    lines = []
    for i in range(130):
        lines.append(
            json.dumps(
                {
                    "clip": f"clip_{i}",
                    "ask": "review",
                    "bucket": "program",
                    "confidence": "medium",
                    "model": "qwen2.5:14b",
                }
            )
        )
    (label / "key.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    report = backlog_report(data_root)
    assert report["level"] == "critical"
    assert report["more_gpu_needed"] is False
    digest = write_daily_digest(data_root, budget=50)
    assert digest["backlog"]["help_asks"] == 130
    assert (label / "DAILY_LABEL.md").is_file()


def test_backfill_and_human_lock(data_root: Path):
    from tools.windows_lab.farm_label_audit import (
        apply_human_lock,
        backfill_draft_audit,
        refresh_trust_gate,
    )

    label = farm_label_dir(data_root)
    (label / "key.jsonl").write_text(
        json.dumps(
            {
                "clip": "c1",
                "ask": "review",
                "bucket": "paid_ad",
                "kind": "dry_vo",
                "confidence": "high",
                "model": "qwen2.5:14b",
                "session": "s1",
                "t0": 0,
                "t1": 20,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    bf = backfill_draft_audit(data_root)
    assert bf["backfilled"] == 1
    audit = (label / "label_draft.jsonl").read_text(encoding="utf-8")
    assert "c1" in audit
    # Second backfill is idempotent.
    assert backfill_draft_audit(data_root)["backfilled"] == 0

    out = apply_human_lock("c1", bucket="paid_ad", kind="dry_vo", note="GEICO", root=data_root)
    assert out["locked"]["ask"] == "locked"
    assert out["locked"]["source"] == "human"
    trust = refresh_trust_gate(data_root)
    assert trust["gold_clips"] >= 1
    assert "human_lock" in (label / "label_draft.jsonl").read_text(encoding="utf-8")
