"""Consensus voter → auto-lock helpers."""

from __future__ import annotations

import json
from pathlib import Path

from tools.windows_lab.farm_consensus import (
    apply_consensus_locks,
    consensus_at_hop,
    consensus_ranges_for_session,
)


def test_consensus_at_hop_agree_and_conflict() -> None:
    agree = consensus_at_hop(
        {
            "votes": {"vision": "program", "asr": "program", "acoustic_action": "play"},
        }
    )
    assert agree["label"] == "play"
    assert not agree["disagree"]

    conflict = consensus_at_hop(
        {
            "votes": {"vision": "paid_ad", "asr": "program"},
        }
    )
    assert conflict["label"] is None
    assert conflict["disagree"]


def test_apply_consensus_locks_covers_review_clips(tmp_path: Path, monkeypatch) -> None:
    from tools.windows_lab import farm_consensus as fc

    label = tmp_path / "indexes" / "farm_labels"
    audit = label / "audit" / "sess_a"
    audit.mkdir(parents=True)
    cap = tmp_path / "work" / "capture" / "streamers" / "sess_a"
    cap.mkdir(parents=True)

    hops = []
    for t in range(0, 20, 5):
        hops.append(
            {
                "t": float(t),
                "votes": {
                    "vision": "paid_ad" if t < 10 else "program",
                    "asr": "ad" if t < 10 else "program",
                    "acoustic_action": "cover" if t < 10 else "play",
                },
                "disagreement": False,
            }
        )
    (audit / "hops.jsonl").write_text(
        "\n".join(json.dumps(h) for h in hops) + "\n", encoding="utf-8"
    )
    keys = [
        {
            "clip": "sess_a_2_8",
            "session": "sess_a",
            "t0": 2.0,
            "t1": 8.0,
            "ask": "review",
            "bucket": "uncertain",
        },
        {
            "clip": "sess_a_12_18",
            "session": "sess_a",
            "t0": 12.0,
            "t1": 18.0,
            "ask": "needs_human",
            "bucket": "uncertain",
        },
        {
            "clip": "sess_a_9_11",
            "session": "sess_a",
            "t0": 9.0,
            "t1": 11.0,
            "ask": "review",
            "bucket": "uncertain",
        },
    ]
    (label / "key.jsonl").write_text(
        "\n".join(json.dumps(k) for k in keys) + "\n", encoding="utf-8"
    )

    monkeypatch.setattr(fc, "farm_label_dir", lambda root=None: label)
    monkeypatch.setattr(fc, "streamers_capture_root", lambda root=None: cap.parent)

    ranges = consensus_ranges_for_session("sess_a")
    assert ranges["n_agree_hops"] == 4
    assert len(ranges["ranges"]) == 2

    out = apply_consensus_locks("sess_a", dry_run=False)
    assert out["ok"]
    assert out["locked_n"] >= 2
    locked = {
        json.loads(l)["clip"]: json.loads(l)
        for l in (label / "key.jsonl").read_text(encoding="utf-8").splitlines()
        if l.strip()
    }
    assert locked["sess_a_2_8"]["ask"] == "locked"
    assert locked["sess_a_2_8"]["bucket"] == "paid_ad"
    assert locked["sess_a_12_18"]["ask"] == "locked"
    assert locked["sess_a_12_18"]["bucket"] == "program"
    # Boundary straddler should remain for verdict
    assert locked["sess_a_9_11"]["ask"] == "review"
