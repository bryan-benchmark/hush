"""Agent-owned Streamers coverage: guide plan, board, capacity, dispatch report.

Farm corpus stays under OHUSH_DATA_ROOT as authorized_stream_reference.
Never merges into sealed optical football gold.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .catalog import list_sessions
from .config import data_root, ensure_data_layout, farm_dir
from .instances import list_instances, load_registry
from .multi_instance import isolation_report

ET = ZoneInfo("America/New_York")

# How people watch TV: main first, then aux, then deeper. Live preempts fill.
PROMINENCE = (
    "live_event",
    "main_linear",
    "main_news",
    "aux_sports",
    "fast",
    "deeper",
)

SLOTS = (
    "live_event",
    "main_linear",
    "main_news",
    "aux_sports",
    "fast",
    "talk_entertainment",
    "other",
)

DAYPARTS = ("morning", "afternoon", "primetime", "late")

# Big-market locals first (Streamers can open any US DMA anytime — rotate these).
PRIORITY_MARKETS = (
    "New York",
    "Los Angeles",
    "Chicago",
    "Dallas-Fort Worth",
    "Atlanta",
    "Philadelphia",
    "Houston",
    "Boston",
    "San Francisco",
    "Washington DC",
)

# Daypart × weekday fill order after live preempt. Values are coverage slots.
# Streamers US * SECTION groups work for any market clock — use West Coast
# locals to extend "morning show" / "late news" windows when ET has moved on.
WEEKDAY_FILL: dict[str, tuple[str, ...]] = {
    "morning": ("main_linear", "main_news", "fast", "aux_sports", "talk_entertainment"),
    "afternoon": ("main_linear", "main_news", "talk_entertainment", "fast", "aux_sports"),
    "primetime": ("main_linear", "aux_sports", "main_news", "fast", "talk_entertainment"),
    "late": ("main_linear", "main_news", "fast", "talk_entertainment", "aux_sports"),
}

WEEKEND_FILL: dict[str, tuple[str, ...]] = {
    # Sat/Sun: sports climb when not in an active live window
    "morning": ("main_linear", "main_news", "aux_sports", "fast", "talk_entertainment"),
    "afternoon": ("aux_sports", "main_linear", "main_news", "fast", "talk_entertainment"),
    "primetime": ("aux_sports", "main_linear", "main_news", "fast", "talk_entertainment"),
    "late": ("main_news", "main_linear", "fast", "aux_sports", "talk_entertainment"),
}

# Seed targets from verified probes + lineup doctrine (not stale tap coords).
SEED_TARGETS: list[dict[str, Any]] = [
    {
        "channel_id": "NBC_NEWS_NOW",
        "guide_name": "(RK) NBC News NOW",
        "group": "ROKU TV",
        "number": 2513,
        "slot": "main_news",
        "prominence": "main_news",
        "open_hint": "Search NBC News NOW in Roku TV / US NEWS. D-pad center after row selected.",
        "live_sensitive": False,
        "verified_play": True,
    },
    {
        "channel_id": "CBS_NEWS_247",
        "guide_name": "(RK) CBS News 24/7",
        "group": "ROKU TV",
        "number": None,
        "slot": "main_news",
        "prominence": "main_news",
        "open_hint": "Search CBS News 24/7 under Roku TV. Avoid movie hits named CBS.",
        "live_sensitive": False,
        "verified_play": False,
    },
    {
        "channel_id": "PLUTO_CBS_SPORTS_HQ",
        "guide_name": "(PLUTO USA) CBS Sports HQ",
        "group": "PLUTO U.S.A.",
        "number": 2702,
        "slot": "fast",
        "prominence": "fast",
        "open_hint": "Pluto U.S.A. group or search CBS Sports HQ under Pluto.",
        "live_sensitive": False,
        "verified_play": True,
    },
    {
        "channel_id": "PLUTO_CNN_HEADLINES",
        "guide_name": "(PLUTO USA) CNN HEADLINES",
        "group": "PLUTO U.S.A.",
        "number": None,
        "slot": "fast",
        "prominence": "fast",
        "open_hint": "Pluto U.S.A. — CNN HEADLINES.",
        "live_sensitive": False,
        "verified_play": False,
    },
    {
        "channel_id": "ESPNU",
        "guide_name": "(MAX SPORTS) ESPNU",
        "group": "MAX SPORTS",
        "number": 6170,
        "slot": "aux_sports",
        "prominence": "aux_sports",
        "open_hint": "MAX SPORTS / US SPORTS. Skip if black or 'No event available'.",
        "live_sensitive": True,
        "verified_play": True,
    },
    {
        "channel_id": "ESPN",
        "guide_name": "(MAX SPORTS) ESPN",
        "group": "MAX SPORTS",
        "number": None,
        "slot": "aux_sports",
        "prominence": "aux_sports",
        "open_hint": "MAX SPORTS ESPN. Prefer when a live game or studio show is on air.",
        "live_sensitive": True,
        "verified_play": False,
    },
    {
        "channel_id": "NBC_LOCAL_FLAGSHIP",
        "guide_name": "US NBC SECTION local / flagship",
        "group": "US NBC SECTION",
        "number": None,
        "slot": "main_linear",
        "prominence": "main_linear",
        "open_hint": (
            "US NBC SECTION — any US market anytime. Prefer NY/LA/CHI/DFW/ATL locals "
            "with picture. Not movie search."
        ),
        "live_sensitive": False,
        "verified_play": False,
        "any_us_local": True,
    },
    {
        "channel_id": "CBS_LOCAL_FLAGSHIP",
        "guide_name": "US CBS SECTION local / flagship",
        "group": "US CBS SECTION",
        "number": None,
        "slot": "main_linear",
        "prominence": "main_linear",
        "open_hint": (
            "US CBS SECTION — any US market anytime. Prefer big-DMA locals with picture."
        ),
        "live_sensitive": False,
        "verified_play": False,
        "any_us_local": True,
    },
    {
        "channel_id": "ABC_LOCAL_FLAGSHIP",
        "guide_name": "US ABC SECTION local / flagship",
        "group": "US ABC SECTION",
        "number": None,
        "slot": "main_linear",
        "prominence": "main_linear",
        "open_hint": (
            "US ABC SECTION group (search 'ABC' hits movies). Any US market anytime; "
            "rotate NY/LA/CHI/DFW/ATL."
        ),
        "live_sensitive": False,
        "verified_play": False,
        "any_us_local": True,
    },
    {
        "channel_id": "FOX_LOCAL_FLAGSHIP",
        "guide_name": "US FOX SECTION local / flagship",
        "group": "US FOX SECTION",
        "number": None,
        "slot": "main_linear",
        "prominence": "main_linear",
        "open_hint": (
            "US FOX SECTION group (search 'FOX' hits movies). Any US market anytime; "
            "rotate big DMAs."
        ),
        "live_sensitive": False,
        "verified_play": False,
        "any_us_local": True,
    },
]


def fill_order_for(now: datetime | None = None) -> list[str]:
    """Coverage-slot order for the current weekday + daypart (after live preempt)."""
    local = now.astimezone(ET) if now else _now_et()
    dp = daypart_for(local)
    table = WEEKEND_FILL if local.weekday() >= 5 else WEEKDAY_FILL
    return list(table.get(dp, WEEKDAY_FILL["morning"]))


def hierarchy_snapshot(now: datetime | None = None) -> dict[str, Any]:
    local = now.astimezone(ET) if now else _now_et()
    windows = live_windows_et(local)
    active = [w for w in windows if w.get("active_now")]
    return {
        "local_et": local.isoformat(),
        "weekday": local.strftime("%A"),
        "daypart": daypart_for(local),
        "live_preempt": bool(active),
        "live_windows": windows,
        "fill_order": fill_order_for(local),
        "priority_markets": list(PRIORITY_MARKETS),
        "rule": (
            "If a live window is active and a real game/event is on air, capture that first. "
            "Otherwise follow fill_order. US ABC/CBS/NBC/FOX SECTION locals can be any DMA "
            "anytime — rotate priority_markets; use West Coast clocks to stretch morning-show "
            "and late-news dayparts."
        ),
    }


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _now_et() -> datetime:
    return datetime.now(ET)


def daypart_for(dt: datetime | None = None) -> str:
    local = dt.astimezone(ET) if dt else _now_et()
    h = local.hour
    if 5 <= h < 12:
        return "morning"
    if 12 <= h < 17:
        return "afternoon"
    if 17 <= h < 23:
        return "primetime"
    return "late"


def indexes_dir(root: Path | None = None) -> Path:
    return ensure_data_layout(root) / "indexes"


def capture_plan_path(root: Path | None = None) -> Path:
    return indexes_dir(root) / "capture_plan.json"


def coverage_board_path(root: Path | None = None) -> Path:
    return indexes_dir(root) / "coverage_board.json"


def coverage_board_md_path(root: Path | None = None) -> Path:
    return indexes_dir(root) / "COVERAGE_BOARD.md"


def farm_label_dir(root: Path | None = None) -> Path:
    """Labeled farm review artifacts (queue/drafts/judgments)."""
    path = ensure_data_layout(root) / "indexes" / "farm_labels"
    path.mkdir(parents=True, exist_ok=True)
    return path


def streamers_capture_root(root: Path | None = None) -> Path:
    return ensure_data_layout(root) / "work" / "capture" / "streamers"


def _load_json(path: Path) -> Any:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _prominence_rank(name: str) -> int:
    try:
        return PROMINENCE.index(name)
    except ValueError:
        return len(PROMINENCE)


def live_windows_et(now: datetime | None = None) -> list[dict[str, Any]]:
    """Heuristic upcoming live windows the agent should watch for.

    Not a full listings API — flags likely sports live dayparts so dispatch
    can preempt daytime fill. Empty event slots are still not content.
    """
    local = now.astimezone(ET) if now else _now_et()
    weekday = local.weekday()  # Mon=0
    windows: list[dict[str, Any]] = []
    # Thu night football-ish
    if weekday == 3:
        windows.append(
            {
                "id": "tnf_primetime",
                "label": "Thursday night football window",
                "start_local": "20:00",
                "end_local": "23:30",
                "priority": "live_event",
                "note": "Prefer ESPN / Prime / NFL feeds only if a real game is on air.",
            }
        )
    # Sun
    if weekday == 6:
        windows.append(
            {
                "id": "nfl_sunday",
                "label": "NFL Sunday window",
                "start_local": "12:00",
                "end_local": "23:30",
                "priority": "live_event",
                "note": "Main linear + sports nets; skip empty numbered NFL/NCAA rows.",
            }
        )
    # Mon
    if weekday == 0:
        windows.append(
            {
                "id": "mnf_primetime",
                "label": "Monday night football window",
                "start_local": "20:00",
                "end_local": "23:45",
                "priority": "live_event",
                "note": "ESPN/ABC when a game is actually playing.",
            }
        )
    # Sat college
    if weekday == 5:
        windows.append(
            {
                "id": "cfb_saturday",
                "label": "College football Saturday",
                "start_local": "11:00",
                "end_local": "23:30",
                "priority": "live_event",
                "note": "ESPNU/ESPN/ABC/FOX only with picture; skip 'No event available'.",
            }
        )
    in_window = []
    hhmm = f"{local.hour:02d}:{local.minute:02d}"
    for w in windows:
        if w["start_local"] <= hhmm <= w["end_local"]:
            in_window.append({**w, "active_now": True})
        else:
            in_window.append({**w, "active_now": False})
    return in_window


def _slot_minutes_from_catalog(root: Path | None = None) -> dict[str, dict[str, float]]:
    """Approximate captured minutes by slot/daypart from catalog + streamers takes."""
    cells: dict[str, dict[str, float]] = {s: {d: 0.0 for d in DAYPARTS} for s in SLOTS}

    for row in list_sessions(root, label_status=None, limit=5000):
        slot = str(row.get("coverage_slot") or row.get("slot") or _infer_slot(row.get("channel_id")))
        if slot not in cells:
            slot = "other"
        minutes = float(row.get("duration_minutes") or row.get("minutes") or 0.0)
        if minutes <= 0 and row.get("duration_s"):
            minutes = float(row["duration_s"]) / 60.0
        dp = str(row.get("daypart") or "other")
        if dp not in DAYPARTS:
            # try capture time
            ts = row.get("capture_utc_start") or row.get("indexed_utc")
            try:
                dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                dp = daypart_for(dt)
            except Exception:  # noqa: BLE001
                dp = "morning"
        cells[slot][dp] += minutes

    # Also fold work/capture/streamers takes that have label_aid
    for take_dir in _iter_streamers_takes(root):
        aid = _load_json(take_dir / "label_aid.json") or {}
        guide = aid.get("guide") or {}
        slot = _infer_slot(guide.get("name") or take_dir.name)
        media = aid.get("media") or {}
        minutes = float(media.get("duration_s") or 180.0) / 60.0
        ts = aid.get("recorded_utc") or take_dir.name[:16]
        try:
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            dp = daypart_for(dt)
        except Exception:  # noqa: BLE001
            dp = "morning"
        cells.setdefault(slot, {d: 0.0 for d in DAYPARTS})
        cells[slot][dp] = cells[slot].get(dp, 0.0) + minutes

    return cells


def _infer_slot(name: Any) -> str:
    text = str(name or "").lower()
    if any(k in text for k in ("nfl", "prime", "mnf", "tnf")) and "news" not in text:
        return "live_event"
    if any(k in text for k in ("espn", "fs1", "fs2", "sec network", "big ten")):
        return "aux_sports"
    if any(k in text for k in ("pluto", "roku", "tubi", "peacock")):
        return "fast"
    if "news" in text or "cnn" in text:
        return "main_news"
    if any(k in text for k in ("abc", "cbs", "nbc", "fox")):
        return "main_linear"
    return "other"


def _iter_streamers_takes(root: Path | None = None) -> list[Path]:
    base = streamers_capture_root(root)
    if not base.is_dir():
        return []
    return sorted(p for p in base.iterdir() if p.is_dir() and (p / "label_aid.json").is_file())


def _validated_minutes(root: Path | None = None) -> dict[str, float]:
    judgments_path = farm_label_dir(root) / "judgments.json"
    judgments = _load_json(judgments_path) or {}
    queue_path = farm_label_dir(root) / "queue.jsonl"
    by_clip: dict[str, dict[str, Any]] = {}
    if queue_path.is_file():
        for line in queue_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            by_clip[row["clip"]] = row
    out: dict[str, float] = {s: 0.0 for s in SLOTS}
    for clip, judgment in judgments.items():
        row = by_clip.get(clip) or {}
        slot = str(row.get("slot") or judgment.get("slot") or "other")
        if slot not in out:
            slot = "other"
        dur = float(row.get("t1", 0) or 0) - float(row.get("t0", 0) or 0)
        if dur <= 0:
            dur = 8.0
        out[slot] += dur / 60.0
    return out


def _open_review_count(root: Path | None = None) -> int:
    queue_path = farm_label_dir(root) / "queue.jsonl"
    judgments = _load_json(farm_label_dir(root) / "judgments.json") or {}
    if not queue_path.is_file():
        return 0
    n = 0
    for line in queue_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("clip") not in judgments:
            n += 1
    return n


def coverage_gaps(root: Path | None = None, *, target_minutes: float = 30.0) -> list[dict[str, Any]]:
    cells = _slot_minutes_from_catalog(root)
    validated = _validated_minutes(root)
    dp = daypart_for()
    order = fill_order_for()
    gaps: list[dict[str, Any]] = []
    # Prefer filling slots in the current daypart/weekday hierarchy
    for rank, slot in enumerate(order):
        captured = cells.get(slot, {}).get(dp, 0.0)
        val = validated.get(slot, 0.0)
        need = max(0.0, target_minutes - val)
        if need > 0 or captured < target_minutes:
            gaps.append(
                {
                    "slot": slot,
                    "daypart": dp,
                    "hierarchy_rank": rank,
                    "captured_minutes": round(captured, 2),
                    "validated_minutes": round(val, 2),
                    "target_minutes": target_minutes,
                    "gap_validated_minutes": round(need, 2),
                }
            )
    gaps.sort(key=lambda g: (g["hierarchy_rank"], -g["gap_validated_minutes"]))
    return gaps


def ready_instances(root: Path | None = None) -> list[dict[str, Any]]:
    reg = load_registry(root)
    max_n = int(reg.get("max_concurrent_streamers") or 3)
    rows = []
    for row in list_instances(root):
        if row.get("source_kind", "streamers") not in (None, "streamers"):
            continue
        if not row.get("enabled", True):
            continue
        loopback = str(row.get("loopback_device") or "").strip()
        rows.append(
            {
                "id": row["id"],
                "loopback_device": loopback,
                "adb_serial": row.get("adb_serial"),
                "ready": bool(loopback),
                "audio_route_note": row.get("audio_route_note"),
            }
        )
    # Prefer ready ones; cap by max concurrent
    ready = [r for r in rows if r["ready"]]
    return ready[:max_n]


def build_capture_plan(root: Path | None = None, *, chunk_minutes: int = 20) -> dict[str, Any]:
    ensure_data_layout(root)
    now = _now_utc()
    local = _now_et()
    dp = daypart_for(local)
    windows = live_windows_et(local)
    active_live = [w for w in windows if w.get("active_now")]
    gaps = coverage_gaps(root)
    instances = ready_instances(root)
    iso = isolation_report(root)

    # Rank by live preempt, then weekday/daypart fill order, then gap / verified
    gap_slots = {g["slot"] for g in gaps if g["gap_validated_minutes"] > 0}
    fill = fill_order_for(local)
    fill_rank = {slot: i for i, slot in enumerate(fill)}
    hier = hierarchy_snapshot(local)
    ranked = sorted(
        SEED_TARGETS,
        key=lambda t: (
            0 if (active_live and t.get("live_sensitive")) else 1,
            fill_rank.get(str(t["slot"]), 99),
            _prominence_rank(str(t["prominence"])),
            0 if t["slot"] in gap_slots else 1,
            0 if t.get("verified_play") else 1,
            t["channel_id"],
        ),
    )

    assignments: list[dict[str, Any]] = []
    used_channels: set[str] = set()
    for inst in instances:
        pick = None
        for target in ranked:
            cid = target["channel_id"]
            if cid in used_channels:
                continue
            if active_live and not target.get("live_sensitive") and target["prominence"] not in (
                "main_linear",
                "main_news",
                "live_event",
            ):
                # During live windows still allow main linear/news fill on spare instances
                # but prefer live_sensitive first (already sorted).
                pass
            pick = target
            break
        if not pick:
            break
        used_channels.add(pick["channel_id"])
        reason_parts = [
            f"prominence={pick['prominence']}",
            f"slot={pick['slot']}",
            f"daypart={dp}",
            f"weekday={local.strftime('%A')}",
        ]
        if pick["slot"] in gap_slots:
            reason_parts.append("fills_coverage_gap")
        if active_live and pick.get("live_sensitive"):
            reason_parts.append("live_window_active")
        if pick.get("verified_play"):
            reason_parts.append("verified_play")
        if pick.get("any_us_local"):
            reason_parts.append("any_us_local_ok")
        assignments.append(
            {
                "instance_id": inst["id"],
                "loopback_device": inst["loopback_device"],
                "channel_id": pick["channel_id"],
                "guide_name": pick["guide_name"],
                "group": pick["group"],
                "number": pick.get("number"),
                "slot": pick["slot"],
                "prominence": pick["prominence"],
                "preferred_markets": list(PRIORITY_MARKETS[:5]) if pick.get("any_us_local") else [],
                "chunk_minutes": chunk_minutes,
                "media": "av",
                "open_hint": pick["open_hint"],
                "why": ", ".join(reason_parts),
                "do_not_apply_example_recipe": True,
            }
        )

    plan = {
        "version": 1,
        "built_utc": now.isoformat(),
        "local_et": local.isoformat(),
        "daypart": dp,
        "hierarchy": hier,
        "live_windows": windows,
        "live_preempt": bool(active_live),
        "coverage_gaps": gaps[:8],
        "capacity": {
            "ready_instances": len(instances),
            "max_concurrent_streamers": int(load_registry(root).get("max_concurrent_streamers") or 3),
            "isolation_ok": bool(iso.get("ok")),
            "guidance": (
                "Streamers already lags on one instance. Two clean max with distinct "
                "VB-Cables. Never open a third while farm status streamers_lag is hot."
            ),
        },
        "assignments": assignments,
        "deferred": [
            "PPV / Holiday loading cards",
            "Empty NCAA/NFL numbered event slots",
            "Country packs and most 24/7 loops until mains validated",
        ],
        "owner_action": (
            "Agent owns guide + capture plan. Owner opens http://127.0.0.1:3010/farm "
            "when the review queue has work. Do not merge farm labels into optical gold."
        ),
        "next_commands": [
            "python -m tools.windows_lab farm plan",
            "python -m tools.windows_lab farm board",
            "python -m tools.windows_lab farm capacity",
            "python -m tools.windows_lab farm dispatch --dry-run",
            "python -m tools.windows_lab farm seed-queue",
            "python -m tools.windows_lab farm draft --model qwen2.5:14b",
        ],
    }
    path = capture_plan_path(root)
    path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    return plan


def build_coverage_board(root: Path | None = None) -> dict[str, Any]:
    ensure_data_layout(root)
    cells = _slot_minutes_from_catalog(root)
    validated = _validated_minutes(root)
    open_n = _open_review_count(root)
    board = {
        "version": 1,
        "updated_utc": _now_utc().isoformat(),
        "daypart_now": daypart_for(),
        "open_review_clips": open_n,
        "slots": {},
        "first_week_goal": "≥30 human-validated minutes in main_linear, main_news, and fast",
    }
    for slot in SLOTS:
        board["slots"][slot] = {
            "captured_by_daypart": {d: round(cells.get(slot, {}).get(d, 0.0), 2) for d in DAYPARTS},
            "validated_minutes_total": round(validated.get(slot, 0.0), 2),
        }
    coverage_board_path(root).write_text(json.dumps(board, indent=2), encoding="utf-8")

    lines = [
        "# Coverage board",
        "",
        f"Updated: {board['updated_utc']}",
        f"Daypart now: {board['daypart_now']}",
        f"Open review clips: {open_n}",
        "",
        board["first_week_goal"],
        "",
        "| Slot | Morning | Afternoon | Primetime | Late | Validated min |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for slot in SLOTS:
        c = board["slots"][slot]["captured_by_daypart"]
        lines.append(
            f"| {slot} | {c['morning']} | {c['afternoon']} | {c['primetime']} | {c['late']} | "
            f"{board['slots'][slot]['validated_minutes_total']} |"
        )
    hier = hierarchy_snapshot()
    lines.extend(
        [
            "",
            "## Hierarchy now",
            f"- {hier['weekday']} · {hier['daypart']} · live_preempt={hier['live_preempt']}",
            f"- Fill order: {', '.join(hier['fill_order'])}",
            f"- Local markets (any US DMA anytime): {', '.join(hier['priority_markets'][:5])}…",
            "",
            "Full doctrine: `indexes/CAPTURE_HIERARCHY.md` and `docs/ohush/research/COVERAGE_FARM_001/HIERARCHY.md`.",
            "",
            "Plan: `indexes/capture_plan.json`. Labels: `indexes/farm_labels/`.",
            "Farm never merges into sealed optical football gold.",
            "",
        ]
    )
    coverage_board_md_path(root).write_text("\n".join(lines), encoding="utf-8")
    return board


def capacity_report(root: Path | None = None) -> dict[str, Any]:
    reg = load_registry(root)
    iso = isolation_report(root)
    ready = ready_instances(root)
    all_rows = [
        {
            "id": r["id"],
            "enabled": r.get("enabled", True),
            "loopback_device": r.get("loopback_device") or "",
            "ready": bool(str(r.get("loopback_device") or "").strip()),
        }
        for r in list_instances(root)
        if r.get("source_kind", "streamers") in (None, "streamers")
    ]
    return {
        "checked_utc": _now_utc().isoformat(),
        "max_concurrent_streamers": int(reg.get("max_concurrent_streamers") or 3),
        "clean_target_now": 2,
        "ready_count": len(ready),
        "instances": all_rows,
        "isolation": iso,
        "streamers_lag_note": (
            "App lags heavily even solo. Cap concurrent at clean_target_now. "
            "Wait+re-dump when UI texts disagree with the screenshot."
        ),
        "roadmap": [
            {"stage": "now", "concurrent": 2, "requirement": "Distinct VB-Cable; watch Streamers lag"},
            {"stage": "blocked", "concurrent": 3, "requirement": "Avoid — third instance worsens lag on this PC"},
            {"stage": "later", "concurrent": "4+", "requirement": "Second machine"},
        ],
        "checklist_path": str(farm_dir(root) / "MULTI_INSTANCE_SETUP.md"),
    }


def dispatch_report(root: Path | None = None, *, dry_run: bool = True) -> dict[str, Any]:
    """Turn the capture plan into per-instance instructions.

    Live tune+record still requires a confirmed channel open (fresh UI dump).
    This writes the assignment sheet and optional session start commands once a
    real recipe exists — it never applies EXAMPLE.json.
    """
    plan = _load_json(capture_plan_path(root)) or build_capture_plan(root)
    steps = []
    for a in plan.get("assignments") or []:
        steps.append(
            {
                "instance_id": a["instance_id"],
                "channel_id": a["channel_id"],
                "slot": a["slot"],
                "actions": [
                    f"Ensure instance {a['instance_id']} is logged into Streamers (salvation home).",
                    f"Open channel via fresh UI dump: {a['open_hint']}",
                    "Confirm picture is not black/silent.",
                    (
                        "Record with probe atoms or session start only after a confirmed recipe "
                        f"(media=av, {a['chunk_minutes']} min, loopback={a['loopback_device']})."
                    ),
                    "Discard black/silent takes. Catalog appends as unlabeled.",
                ],
                "session_cli_when_recipe_ready": (
                    f'python -m tools.windows_lab session start --source streamers '
                    f'--instance {a["instance_id"]} --channel {a["channel_id"]} '
                    f'--minutes {a["chunk_minutes"]} --media av --no-channel-apply'
                ),
                "why": a.get("why"),
            }
        )
    report = {
        "built_utc": _now_utc().isoformat(),
        "dry_run": dry_run,
        "live_preempt": plan.get("live_preempt"),
        "daypart": plan.get("daypart"),
        "steps": steps,
        "note": (
            "Dispatch is agent-directed. Automating taps requires a fresh dump each time; "
            "do not reuse coordinates or EXAMPLE recipes."
        ),
    }
    out = indexes_dir(root) / "capture_dispatch.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def _map_aid_kind(kind: str) -> tuple[str, str]:
    k = (kind or "").lower()
    if k in ("commercial", "dry_vo", "music_bed_ad"):
        return "paid_ad", k if k != "commercial" else "dry_vo"
    if k in ("promo_show", "show_promo"):
        return "show_promo", "show_promo"
    if k in ("sponsor_bug", "program_mention", "in_show_sponsorship"):
        return "program_mention", "in_show_sponsorship"
    if k in ("pip_ad_over_sports", "pip_ad"):
        # Split / PiP ad over live play — not a clean standalone paid_ad.
        return "program_mention", "pip_ad_over_sports"
    if k.startswith("program"):
        return "program", k if k.startswith("program") else "program_sports"
    return "uncertain", "unknown"


def seed_queue_from_streamers_takes(root: Path | None = None) -> dict[str, Any]:
    """Build farm review queue from boundary cuts; lock gold from rich label_aid."""
    from .farm_boundaries import rebuild_queue_and_gold

    out_dir = farm_label_dir(root)
    judgments_path = out_dir / "judgments.json"
    if not judgments_path.is_file():
        judgments_path.write_text("{}\n", encoding="utf-8")
    result = rebuild_queue_and_gold(root, lock_rich_aid=True)
    return {
        "queue_path": result["queue_path"],
        "key_path": result["key_path"],
        "gold_path": result.get("gold_path"),
        "clips": result["queue_clips"],
        "gold_locked": result["gold_locked"],
        "takes": result["takes"],
        "trust_gate": result.get("trust_gate"),
        "review_url": result["review_url"],
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="Streamers coverage farm (guide plan / board / capacity)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("plan", help="Build capture_plan.json from guide doctrine + gaps")
    sp.add_argument("--chunk-minutes", type=int, default=20)

    sub.add_parser("board", help="Rebuild coverage board JSON + markdown")
    sub.add_parser("capacity", help="Report parallel instance capacity")
    dp = sub.add_parser("dispatch", help="Write per-instance capture dispatch sheet")
    dp.add_argument("--dry-run", action="store_true", default=True)
    dp.add_argument("--execute", action="store_true", help="Mark dispatch as execute intent (still no EXAMPLE recipe)")

    sub.add_parser(
        "seed-queue",
        help="Seed /farm queue from boundary cuts (label_aid + still diffs); lock gold",
    )
    sub.add_parser(
        "gold-lock",
        help="Rebuild boundary queue + lock gold labels from rich label_aid takes",
    )
    gc = sub.add_parser(
        "gold-confirm",
        help="Promote gold_candidates.jsonl rows into locked gold (after /farm check)",
    )
    gc.add_argument(
        "--all-candidates",
        action="store_true",
        help="Lock every gold_candidate expect_bucket (only after you reviewed them)",
    )
    gc.add_argument("--clip", action="append", default=[], help="Lock one candidate clip id")
    dr = sub.add_parser("draft", help="Whisper + Ollama drafts into farm key.jsonl")
    dr.add_argument("--model", default="qwen2.5:14b")
    dr.add_argument("--limit", type=int, default=None)
    dr.add_argument("--no-whisper", action="store_true")
    sub.add_parser("hierarchy", help="Print weekday/daypart capture + label hierarchy")
    dens = sub.add_parser(
        "densify-stills",
        help="Extract 1 fps stills/ from take video.mp4/av.mp4 (local labeling only)",
    )
    dens.add_argument("--session-dir", action="append", default=[])
    dens.add_argument("--interval", type=float, default=1.0)

    prep = sub.add_parser(
        "prepare",
        help="Densify stills, write timeline_facts.jsonl, delete video (retain audio+JSON)",
    )
    prep.add_argument("--keep-video", action="store_true")
    prep.add_argument(
        "--purge-stills",
        action="store_true",
        help="Delete local stills after facts (only after /farm grab is done)",
    )

    sub.add_parser("package", help="Write B2 package manifest (audio+JSON only)")
    up = sub.add_parser("upload-b2", help="rclone sync retain set to Backblaze (dry-run default)")
    up.add_argument("--execute", action="store_true")
    sub.add_parser("score", help="Score Ollama drafts against /farm grab judgments")
    sub.add_parser("status", help="Plan + board + capacity summary")

    args = p.parse_args(argv)
    root = data_root()

    if args.cmd == "plan":
        plan = build_capture_plan(root, chunk_minutes=args.chunk_minutes)
        print(json.dumps(plan, indent=2))
        return 0
    if args.cmd == "board":
        board = build_coverage_board(root)
        print(json.dumps(board, indent=2))
        print(f"wrote {coverage_board_md_path(root)}")
        return 0
    if args.cmd == "capacity":
        print(json.dumps(capacity_report(root), indent=2))
        return 0
    if args.cmd == "dispatch":
        dry = not bool(args.execute)
        print(json.dumps(dispatch_report(root, dry_run=dry), indent=2))
        return 0
    if args.cmd == "seed-queue":
        print(json.dumps(seed_queue_from_streamers_takes(root), indent=2))
        return 0
    if args.cmd == "gold-lock":
        from .farm_boundaries import rebuild_queue_and_gold

        print(json.dumps(rebuild_queue_and_gold(root, lock_rich_aid=True), indent=2))
        return 0
    if args.cmd == "gold-confirm":
        from .farm_boundaries import confirm_gold_candidates

        print(
            json.dumps(
                confirm_gold_candidates(
                    root,
                    clips=list(args.clip or []),
                    all_candidates=bool(args.all_candidates),
                ),
                indent=2,
            )
        )
        return 0
    if args.cmd == "draft":
        from .farm_draft import draft_queue

        print(
            json.dumps(
                draft_queue(
                    model=args.model,
                    use_whisper=not args.no_whisper,
                    root=root,
                    limit=args.limit,
                ),
                indent=2,
            )
        )
        return 0
    if args.cmd == "hierarchy":
        print(json.dumps(hierarchy_snapshot(), indent=2))
        return 0
    if args.cmd == "densify-stills":
        from .visual_archive import distill_video_to_stills

        interval = float(args.interval)
        if interval <= 0 or interval > 1.0:
            print(json.dumps({"ok": False, "error": "interval must be in (0, 1.0]"}))
            return 2
        targets: list[Path] = []
        if args.session_dir:
            targets = [Path(p) for p in args.session_dir]
        else:
            base = streamers_capture_root(root)
            if base.is_dir():
                for d in sorted(base.iterdir()):
                    if d.is_dir() and ((d / "video.mp4").is_file() or (d / "av.mp4").is_file()):
                        targets.append(d)
        results = []
        for session_dir in targets:
            video = session_dir / "video.mp4"
            if not video.is_file():
                video = session_dir / "av.mp4"
            if not video.is_file():
                results.append({"session_dir": str(session_dir), "ok": False, "error": "no video"})
                continue
            out = distill_video_to_stills(
                video, session_dir=session_dir, interval_sec=interval, delete_video=False
            )
            results.append({"session_dir": str(session_dir), **out})
        print(json.dumps({"ok": all(r.get("ok") for r in results), "results": results}, indent=2))
        return 0 if results and all(r.get("ok") for r in results) else 2
    if args.cmd == "prepare":
        from .farm_archive import prepare_all

        print(
            json.dumps(
                prepare_all(
                    root,
                    delete_video=not args.keep_video,
                    purge_stills=bool(args.purge_stills),
                ),
                indent=2,
            )
        )
        return 0
    if args.cmd == "package":
        from .farm_archive import write_package_index

        print(json.dumps(write_package_index(root), indent=2))
        return 0
    if args.cmd == "upload-b2":
        from .farm_archive import upload_b2

        print(json.dumps(upload_b2(execute=bool(args.execute), root=root), indent=2))
        return 0
    if args.cmd == "score":
        from .farm_archive import score_drafts_vs_grab

        print(json.dumps(score_drafts_vs_grab(root), indent=2))
        return 0
    if args.cmd == "status":
        plan = build_capture_plan(root)
        board = build_coverage_board(root)
        cap = capacity_report(root)
        print(
            json.dumps(
                {
                    "daypart": plan.get("daypart"),
                    "hierarchy": plan.get("hierarchy"),
                    "live_preempt": plan.get("live_preempt"),
                    "assignments": plan.get("assignments"),
                    "open_review_clips": board.get("open_review_clips"),
                    "ready_instances": cap.get("ready_count"),
                    "max_concurrent": cap.get("max_concurrent_streamers"),
                    "capture_plan": str(capture_plan_path(root)),
                    "board_md": str(coverage_board_md_path(root)),
                },
                indent=2,
            )
        )
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
