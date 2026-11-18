"""Checkpoint tests: recover won't WAGA-substitute; demand pool top-K; listings hooks."""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from tools.windows_lab.config import ensure_data_layout
from tools.windows_lab.coverage_farm import (
    ROI_LADDER,
    _infer_slot,
    active_regimented_block,
    build_capture_plan,
    build_demand_pool,
    hierarchy_snapshot,
    live_windows_et,
    regimented_chunks_ahead,
    schedule_from_plan,
)
from tools.windows_lab.listings_enrich import fetch_listings, match_hooks
from tools.windows_lab.recovery_target import resolve_recovery_target
from tools.windows_lab.streamers_recover import _intended_guide_labels

ET = ZoneInfo("America/New_York")


@pytest.fixture()
def data_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "OHushData"
    monkeypatch.setenv("OHUSH_DATA_ROOT", str(root))
    ensure_data_layout(root)
    # Minimal instance registry (dict keyed by id) for top-K assignment tests.
    from tools.windows_lab.instances import instance_registry_path, save_registry

    reg = {
        "instances": {
            "Nougat32": {
                "enabled": True,
                "source_kind": "streamers",
                "loopback_device": "VB-Cable",
            },
            "Nougat32_1": {
                "enabled": True,
                "source_kind": "streamers",
                "loopback_device": "VB-Cable-2",
            },
            "Nougat32_2": {
                "enabled": True,
                "source_kind": "streamers",
                "loopback_device": "VB-Cable-3",
            },
            "Nougat32_3": {
                "enabled": True,
                "source_kind": "streamers",
                "loopback_device": "VB-Cable-4",
            },
            "Nougat32_4": {
                "enabled": True,
                "source_kind": "streamers",
                "loopback_device": "VB-Cable-5",
            },
        },
        "max_concurrent_streamers": 5,
    }
    save_registry(reg, root)
    assert instance_registry_path(root).is_file()
    return root


def test_infer_slot_fox_news_not_local():
    assert _infer_slot("US: FOX NEWS") == "main_news"
    assert _infer_slot("FOX NEWS") == "main_news"
    assert _infer_slot("CMA Awards") == "live_event"
    assert _infer_slot("Dancing with the Stars") == "live_event"
    assert _infer_slot("Big Brother") == "talk_entertainment"


def test_intended_labels_fox_news_and_cnn():
    assert "US: FOX NEWS" in _intended_guide_labels({"nav_route": "FOX_NEWS_US"})
    assert "US: CNN" in _intended_guide_labels({"channel_id": "CNN_US"})
    labels = _intended_guide_labels({"label": "main_linear:FOX", "channel_id": "FOX_NEWS_US"})
    assert "US: FOX NEWS" in labels
    assert "main_linear:FOX" not in labels


def test_resolve_honors_capture_plan_not_waga(data_root: Path):
    plan = {
        "version": 2,
        "built_utc": datetime.now().astimezone().isoformat(),
        "assignments": [
            {
                "instance_id": "Nougat32",
                "channel_id": "FOX_NEWS_US",
                "nav_route": "FOX_NEWS_US",
                "open_via": "nav",
                "slot": "main_news",
                "guide_name": "US: FOX NEWS",
            }
        ],
    }
    (data_root / "indexes" / "capture_plan.json").write_text(
        json.dumps(plan), encoding="utf-8"
    )
    tgt = resolve_recovery_target("Nougat32", root=data_root)
    assert tgt["ok"] is True
    assert tgt["kind"] == "plan_assignment"
    assert tgt["nav_route"] == "FOX_NEWS_US"
    assert tgt["channel_id"] == "FOX_NEWS_US"
    assert tgt.get("network") in (None, "")
    assert "WAGA" not in str(tgt)


def test_resolve_main_news_nav_fill(data_root: Path, monkeypatch: pytest.MonkeyPatch):
    # No plan / jobs → main_news top of fill should still be nav, not FOX local.
    monkeypatch.setattr(
        "tools.windows_lab.coverage_farm.hierarchy_snapshot",
        lambda now=None: {
            "daypart": "afternoon",
            "fill_order": ["main_news", "main_linear"],
            "live_preempt": False,
            "live_kind": "",
        },
    )
    tgt = resolve_recovery_target("Nougat32", root=data_root)
    assert tgt["kind"] == "nav_fill"
    assert tgt["nav_route"] in {"FOX_NEWS_US", "CNN_US"}
    assert tgt.get("network") in (None, "")


def test_demand_pool_includes_fox_news_cnn(data_root: Path):
    pool = build_demand_pool(data_root, include_listings=False)
    ids = {r["channel_id"] for r in pool}
    assert "FOX_NEWS_US" in ids
    assert "CNN_US" in ids
    assert "CMA_AWARDS" in ids


def test_top_k_plan_sizes(data_root: Path):
    plan2 = build_capture_plan(
        data_root, chunk_minutes=15, max_streams=2, include_listings=False
    )
    assert len(plan2["assignments"]) == 2
    cids2 = [a["channel_id"] for a in plan2["assignments"]]
    assert len(cids2) == len(set(cids2))
    # Prefer national news/nav over dual local FOX when gaps are empty.
    assert any(a.get("nav_route") for a in plan2["assignments"])

    plan5 = build_capture_plan(
        data_root, chunk_minutes=15, max_streams=5, include_listings=False
    )
    assert len(plan5["assignments"]) == 5
    assert len({a["channel_id"] for a in plan5["assignments"]}) == 5


def test_cma_window_wednesday_evening():
    # 2026-11-18 is a Wednesday.
    local = datetime(2026, 11, 18, 20, 30, tzinfo=ET)
    windows = live_windows_et(local)
    active = [w for w in windows if w.get("active_now")]
    assert any(w.get("id") == "cma_awards_wednesday" for w in active)
    hier = hierarchy_snapshot(local)
    assert hier["live_preempt"] is True
    assert hier["live_kind"] == "entertainment"


def test_regimented_afternoon_news_20m():
    local = datetime(2026, 11, 18, 14, 10, tzinfo=ET)
    block = active_regimented_block(local)
    assert block is not None
    assert block["id"] == "weekday_afternoon_news"
    assert block["chunk_minutes"] == 20
    assert block["channels"][:2] == ("FOX_NEWS_US", "CNN_US")


def test_regimented_wed_cma_60m():
    local = datetime(2026, 11, 18, 20, 0, tzinfo=ET)
    block = active_regimented_block(local)
    assert block is not None
    assert block["id"] == "wed_cma_primetime"
    assert block["chunk_minutes"] == 60
    assert block["channels"][0] == "CMA_AWARDS"


def test_regimented_chunks_48h_nonempty():
    local = datetime(2026, 11, 18, 13, 40, tzinfo=ET)
    chunks = regimented_chunks_ahead(local, hours=48, max_streams=2)
    assert len(chunks) >= 24
    assert all(c["chunk_minutes"] in (20, 60) for c in chunks)
    assert ROI_LADDER[0] == "live_nfl"


def test_plan_uses_regimented_chunk(data_root: Path):
    plan = build_capture_plan(
        data_root, chunk_minutes=15, max_streams=2, include_listings=False
    )
    assert plan["version"] == 3
    assert "roi_ladder" in plan
    assert plan.get("regimented_chunks_48h")
    for a in plan["assignments"]:
        assert a["chunk_minutes"] == plan["chunk_minutes"]


def test_listings_hooks_cma():
    events = [
        {
            "title": "The 59th Annual CMA Awards",
            "network": "ABC",
            "start_utc": "2026-11-19T01:00:00+00:00",
        }
    ]
    hits = match_hooks(events)
    assert hits and hits[0]["channel_id"] == "CMA_AWARDS"
    assert hits[0]["search_query"] == "CMA"


def test_listings_fixture_cache(data_root: Path):
    cache = fetch_listings(
        data_root,
        rows=[
            {
                "title": "Dancing with the Stars",
                "network": "ABC",
                "start_utc": "2026-11-18T01:00:00+00:00",
            }
        ],
    )
    assert cache["source"] == "fixture"
    assert (data_root / "indexes" / "listings_cache.json").is_file()
    hits = match_hooks(cache["events"])
    assert any(h["channel_id"] == "DWTS" for h in hits)


def test_schedule_from_plan_dry_run(data_root: Path):
    out = schedule_from_plan(data_root, dry_run=True, rebuild_plan=True)
    assert out["ok"] is True
    assert out["dry_run"] is True
    assert out["jobs"]
    assert any(j.get("nav_route") or j.get("guide") for j in out["jobs"])


def test_schedule_from_plan_idempotent(data_root: Path):
    first = schedule_from_plan(data_root, dry_run=False, rebuild_plan=True)
    assert first["ok"] is True
    assert first["jobs"]
    second = schedule_from_plan(data_root, dry_run=False, rebuild_plan=True)
    assert second["ok"] is True
    assert second["jobs"] == []
    assert any(s.get("reason") == "already_scheduled" for s in second["skipped"])
