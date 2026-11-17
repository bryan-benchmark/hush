"""Vision mid-run checkpoint / resume helpers."""

from __future__ import annotations

import json
from pathlib import Path

from tools.windows_lab.farm_vision_timeline import (
    _append_vision_hops,
    _vision_hop_done,
)


def test_vision_hop_done_ok_and_dead() -> None:
    assert _vision_hop_done(None) is False
    assert _vision_hop_done({"channels": {}}) is False
    assert _vision_hop_done({"channels": {"vision": {"ok": True, "visual": "scorebug"}}}) is True
    assert _vision_hop_done({"channels": {"vision": {"ok": False, "error": "black_still"}}}) is True
    assert _vision_hop_done({"channels": {"vision": {"ok": False, "error": "empty_vision"}}}) is False


def test_append_vision_hops_survives_reread(tmp_path: Path) -> None:
    path = tmp_path / "hops_vision.jsonl"
    _append_vision_hops(path, [{"t": 0.0, "channels": {"vision": {"ok": True, "visual": "a"}}}])
    _append_vision_hops(path, [{"t": 5.0, "channels": {"vision": {"ok": True, "visual": "b"}}}])
    rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert [r["t"] for r in rows] == [0.0, 5.0]
    assert _vision_hop_done(rows[0]) is True
