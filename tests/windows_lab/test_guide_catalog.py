"""Guide channel number database."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from tools.windows_lab.guide_catalog import (
    enrich_row,
    import_legacy,
    lookup,
    parse_guide_grid,
    upsert_channels,
    write_board,
)


SAMPLE_XML = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node text="US ABC SECTION" bounds="[982,86][1560,118]" />
  <node text="1353" bounds="[27,406][83,440]" />
  <node text="GA | Atlanta | ABC WSB" bounds="[188,407][441,439]" />
  <node text="1354" bounds="[27,471][83,505]" />
  <node text="GA | Atlanta | NBC WXIA" bounds="[188,472][441,504]" />
</hierarchy>
"""


def test_parse_guide_grid_numbers_and_titles():
    ui = ET.fromstring(SAMPLE_XML)
    section, rows = parse_guide_grid(ui)
    assert section == "US ABC SECTION"
    assert len(rows) == 2
    assert rows[0]["number"] == 1353
    assert "WSB" in rows[0]["title"]
    assert rows[1]["number"] == 1354


def test_enrich_and_upsert_lookup(tmp_path: Path, monkeypatch):
    from tools.windows_lab import guide_catalog as gc

    monkeypatch.setattr(gc, "ensure_data_layout", lambda root=None: tmp_path)
    (tmp_path / "indexes").mkdir(parents=True)

    row = enrich_row(
        {
            "number": 1353,
            "title": "GA | Atlanta | ABC WSB",
            "group_name": "US ABC SECTION",
            "kind": "channel",
        }
    )
    assert row["network"] == "ABC"
    assert row["calls"] == "WSB"

    n = upsert_channels([row], scan_id="test", root=tmp_path)
    assert n >= 1
    hits = lookup(calls="WSB", network="ABC", market="Atlanta", root=tmp_path)
    assert hits and hits[0]["number"] == 1353
    board = write_board(tmp_path)
    assert board["channel_count"] >= 1
    assert Path(board["board"]).is_file()


def test_import_legacy_if_present():
    # Uses real OHushData if present — soft check.
    from tools.windows_lab.config import ensure_data_layout

    root = ensure_data_layout()
    legacy = root / "indexes" / "streamers_guide_channels.json"
    if not legacy.is_file():
        return
    out = import_legacy(root)
    assert out.get("ok") is True
    assert out.get("total", 0) >= 100
