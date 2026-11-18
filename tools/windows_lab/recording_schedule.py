"""Always-on recording schedule board — desk source of truth + agent overwrite.

Published to:
  indexes/recording_schedule.json
  indexes/RECORDING_SCHEDULE.md
  http://127.0.0.1:3020/schedule  (and https://ohush.co/schedule via farm password)

Agent overwrite (Cursor):
  indexes/recording_schedule_override.json
  or: python -m tools.windows_lab recording_schedule set-override …

Desk reads effective assignments from here; does not retune when the player
is already on the scheduled channel.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .config import ensure_data_layout
from .coverage_farm import indexes_dir
from .major_programs import (
    as_program_meta,
    priority_program_switches,
    upcoming_program_windows,
)

ET = ZoneInfo("America/New_York")

SCHEDULE_NAME = "recording_schedule.json"
OVERRIDE_NAME = "recording_schedule_override.json"
BOOKINGS_NAME = "recording_schedule_bookings.json"
BOARD_MD = "RECORDING_SCHEDULE.md"
BOARD_HTML = "recording_schedule.html"


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _now_et() -> datetime:
    return _now_utc().astimezone(ET)


def schedule_path(root: Path | None = None) -> Path:
    return indexes_dir(root) / SCHEDULE_NAME


def override_path(root: Path | None = None) -> Path:
    return indexes_dir(root) / OVERRIDE_NAME


def board_md_path(root: Path | None = None) -> Path:
    return indexes_dir(root) / BOARD_MD


def board_html_path(root: Path | None = None) -> Path:
    return indexes_dir(root) / BOARD_HTML


def bookings_path(root: Path | None = None) -> Path:
    return indexes_dir(root) / BOOKINGS_NAME


def _parse_et(value: Any) -> datetime | None:
    s = str(value or "").strip()
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ET)
    return dt.astimezone(ET)


def load_bookings(root: Path | None = None) -> list[dict[str, Any]]:
    """Forward + recent booked windows (Calendly-style manual blocks)."""
    raw = _load_json(bookings_path(root))
    if isinstance(raw, dict):
        items = list(raw.get("bookings") or [])
    elif isinstance(raw, list):
        items = list(raw)
    else:
        items = []
    now = _now_et()
    keep: list[dict[str, Any]] = []
    for b in items:
        if not isinstance(b, dict):
            continue
        end = _parse_et(b.get("end_et"))
        if end is None:
            continue
        # Drop blocks that ended more than 6h ago.
        if end < now - timedelta(hours=6):
            continue
        keep.append(b)
    # Always collapse overlaps so the timeline cannot show impossible dual rows.
    return normalize_bookings(keep)


def save_bookings(bookings: list[dict[str, Any]], *, root: Path | None = None) -> Path:
    root = ensure_data_layout(root)
    path = bookings_path(root)
    payload = {
        "version": 1,
        "updated_utc": _now_utc().isoformat(),
        "bookings": bookings,
        "lesson": (
            "Booked windows override the auto regimented plan for that ET range. "
            "Desk uses an active booking as assignments when no now-hold override is set."
        ),
    }
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path


def active_booking_at(
    when: datetime | None = None,
    *,
    root: Path | None = None,
    bookings: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    local = (when or _now_et()).astimezone(ET)
    rows = bookings if bookings is not None else load_bookings(root)
    for b in rows:
        if b.get("skip"):
            continue
        start = _parse_et(b.get("start_et"))
        end = _parse_et(b.get("end_et"))
        if start is None or end is None:
            continue
        if start <= local < end:
            return b
    return None


def _make_channel_assignment(
    instance_id: str,
    channel_id: str,
    *,
    chunk_minutes: int = 20,
) -> dict[str, Any]:
    meta = catalog_lookup(channel_id)
    nav = str(meta.get("nav_route") or "").strip() or None
    if not nav and channel_id.endswith("_US"):
        nav = channel_id
    search_q = meta.get("search_query")
    open_via = meta.get("open_via")
    if not open_via:
        open_via = "nav" if nav else ("search" if search_q else None)
    label = str(meta.get("short") or meta.get("label") or channel_id)
    return {
        "instance_id": instance_id,
        "channel_id": channel_id,
        "shortcut_id": channel_id,
        "nav_route": nav,
        "open_via": open_via,
        "search_query": search_q,
        "label": label,
        "guide_name": label,
        "kind": meta.get("kind"),
        "airs_on": meta.get("airs_on") or "",
        "group": meta.get("group") or "",
        "chunk_minutes": int(chunk_minutes or 20),
        "media": "av",
        "hold_if_on_air": True,
    }


def _fleet_pair(root: Path) -> list[str]:
    try:
        from .instances import nougat_fleet_ids

        fleet = list(nougat_fleet_ids(root))[:2]
    except Exception:
        fleet = []
    if len(fleet) >= 2:
        return fleet
    # Fallback from heartbeat players.
    players = _player_rows(root)
    ids = [p["instance_id"] for p in players if p.get("instance_id")]
    # Prefer Nougat* order.
    ids = sorted(ids, key=lambda x: (0 if str(x).startswith("Nougat") else 1, str(x)))
    while len(ids) < 2:
        ids.append(f"player_{len(ids)}")
    return ids[:2]


def _assignments_from_booking(
    booking: dict[str, Any],
    *,
    root: Path,
) -> list[dict[str, Any]]:
    fleet = _fleet_pair(root)
    start = _parse_et(booking.get("start_et"))
    end = _parse_et(booking.get("end_et"))
    mins = 20
    if start and end:
        mins = max(5, int((end - start).total_seconds() // 60))
    channels = [
        str(booking.get("stream_a") or "").strip(),
        str(booking.get("stream_b") or "").strip(),
    ]
    rows: list[dict[str, Any]] = []
    for iid, cid in zip(fleet, channels):
        if not cid:
            continue
        rows.append(_make_channel_assignment(iid, cid, chunk_minutes=mins))
    return rows


def _booking_set_utc(b: dict[str, Any]) -> datetime:
    raw = str(b.get("set_utc") or "")
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)


def normalize_bookings(bookings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse overlapping bookings into non-overlapping dual-stream windows.

    Frictionless rule: one clock window → at most one row. Later fills win per
    player side (stream_a / stream_b). Skip punches holes. Consecutive identical
    windows merge.
    """
    parsed: list[dict[str, Any]] = []
    for b in bookings:
        if not isinstance(b, dict):
            continue
        start = _parse_et(b.get("start_et"))
        end = _parse_et(b.get("end_et"))
        if start is None or end is None or end <= start:
            continue
        parsed.append({**b, "_start": start, "_end": end, "_set": _booking_set_utc(b)})
    if not parsed:
        return []

    bounds = sorted({t for b in parsed for t in (b["_start"], b["_end"])})
    slices: list[dict[str, Any]] = []
    for i in range(len(bounds) - 1):
        s, e = bounds[i], bounds[i + 1]
        if (e - s).total_seconds() < 60:
            continue
        covering = [b for b in parsed if b["_start"] <= s and b["_end"] >= e]
        if not covering:
            continue
        covering.sort(key=lambda b: b["_set"])
        # Latest skip wins the whole slice as removed.
        if covering[-1].get("skip"):
            latest = covering[-1]
            slices.append(
                {
                    "id": str(latest.get("id") or uuid.uuid4().hex[:12]),
                    "start_et": s.isoformat(),
                    "end_et": e.isoformat(),
                    "stream_a": None,
                    "stream_b": None,
                    "skip": True,
                    "why": latest.get("why") or "removed",
                    "set_by": latest.get("set_by") or "schedule_ui",
                    "set_utc": latest.get("set_utc") or _now_utc().isoformat(),
                }
            )
            continue
        stream_a = None
        stream_b = None
        why_parts: list[str] = []
        set_by = "schedule_ui"
        set_utc = covering[-1].get("set_utc") or _now_utc().isoformat()
        bid = str(covering[-1].get("id") or uuid.uuid4().hex[:12])
        for b in covering:
            if b.get("skip"):
                continue
            a = str(b.get("stream_a") or "").strip() or None
            bb = str(b.get("stream_b") or "").strip() or None
            if a:
                stream_a = a
            if bb:
                stream_b = bb
            if b.get("why"):
                why_parts.append(str(b.get("why")))
            set_by = str(b.get("set_by") or set_by)
            set_utc = str(b.get("set_utc") or set_utc)
            bid = str(b.get("id") or bid)
        if not stream_a and not stream_b:
            continue
        slices.append(
            {
                "id": bid if len(covering) == 1 else uuid.uuid4().hex[:12],
                "start_et": s.isoformat(),
                "end_et": e.isoformat(),
                "stream_a": stream_a,
                "stream_b": stream_b,
                "skip": False,
                "why": " · ".join(dict.fromkeys(why_parts))[:160] or "booked",
                "set_by": set_by,
                "set_utc": set_utc,
            }
        )

    # Merge contiguous identical assignments.
    merged: list[dict[str, Any]] = []
    for sl in slices:
        if not merged:
            merged.append(sl)
            continue
        prev = merged[-1]
        same = (
            bool(prev.get("skip")) == bool(sl.get("skip"))
            and prev.get("stream_a") == sl.get("stream_a")
            and prev.get("stream_b") == sl.get("stream_b")
        )
        try:
            prev_end = datetime.fromisoformat(str(prev.get("end_et")))
            cur_start = datetime.fromisoformat(str(sl.get("start_et")))
            contiguous = abs((cur_start - prev_end).total_seconds()) < 90
        except ValueError:
            contiguous = False
        if same and contiguous:
            prev["end_et"] = sl["end_et"]
            if sl.get("set_utc"):
                prev["set_utc"] = sl["set_utc"]
            continue
        merged.append(sl)
    return merged


def upsert_booking(
    body: dict[str, Any],
    *,
    root: Path | None = None,
) -> dict[str, Any]:
    """Create or update a booked window (or skip/remove a hole in the auto plan).

    Overlaps are normalized frictionlessly: one clock window → one dual-stream
    row; later player fills win on that side only.
    """
    root = ensure_data_layout(root)
    start = _parse_et(body.get("start_et"))
    end = _parse_et(body.get("end_et"))
    if start is None or end is None:
        return {"ok": False, "error": "need_start_et_and_end_et"}
    if end <= start:
        return {"ok": False, "error": "end_must_be_after_start"}
    if (end - start).total_seconds() > 12 * 3600:
        return {"ok": False, "error": "max_12h_block"}
    skip = bool(body.get("skip"))
    stream_a = str(body.get("stream_a") or "").strip()
    stream_b = str(body.get("stream_b") or "").strip()
    fill_side = str(body.get("fill_side") or "").strip().lower()  # "a" | "b" | ""
    if not skip and not stream_a and not stream_b:
        return {"ok": False, "error": "need_at_least_one_channel"}
    bid = str(body.get("id") or "").strip() or uuid.uuid4().hex[:12]
    rows = load_bookings(root)
    # Player-only fill: inherit the other side from whatever already covers this window.
    if fill_side in {"a", "b"} and not skip:
        covering = []
        for b in rows:
            bs = _parse_et(b.get("start_et"))
            be = _parse_et(b.get("end_et"))
            if bs is None or be is None or b.get("skip"):
                continue
            if bs < end and be > start:
                covering.append(b)
        covering.sort(key=_booking_set_utc)
        inherited_a = None
        inherited_b = None
        for b in covering:
            if b.get("stream_a"):
                inherited_a = str(b.get("stream_a"))
            if b.get("stream_b"):
                inherited_b = str(b.get("stream_b"))
        if fill_side == "a":
            stream_b = stream_b or inherited_b or "FOX_NEWS_US"
        else:
            stream_a = stream_a or inherited_a or "FOX_NEWS_US"
    row = {
        "id": bid,
        "start_et": start.isoformat(),
        "end_et": end.isoformat(),
        "stream_a": None if skip else (stream_a or None),
        "stream_b": None if skip else (stream_b or None),
        "skip": skip,
        "why": str(
            body.get("why")
            or ("removed from schedule UI" if skip else "booked in schedule UI")
        ).strip()[:160],
        "set_by": str(body.get("set_by") or "schedule_ui"),
        "set_utc": _now_utc().isoformat(),
    }
    rows = [b for b in rows if str(b.get("id")) != bid]
    rows.append(row)
    rows = normalize_bookings(rows)
    path = save_bookings(rows, root=root)
    board = publish_recording_schedule(root, rebuild_plan=True)
    return {"ok": True, "booking": row, "path": str(path), "board": board, "normalized": True}


def delete_booking(
    booking_id: str,
    *,
    root: Path | None = None,
) -> dict[str, Any]:
    root = ensure_data_layout(root)
    bid = str(booking_id or "").strip()
    if not bid:
        return {"ok": False, "error": "need_id"}
    rows = load_bookings(root)
    keep = [b for b in rows if str(b.get("id")) != bid]
    if len(keep) == len(rows):
        return {"ok": False, "error": "not_found"}
    path = save_bookings(keep, root=root)
    board = publish_recording_schedule(root, rebuild_plan=True)
    return {"ok": True, "deleted": bid, "path": str(path), "board": board}


def _overlay_bookings_on_chunks(
    chunks: list[dict[str, Any]],
    bookings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Booked windows win over auto regimented chunks for that ET range.

    ``skip: true`` bookings punch a hole (row removed from auto plan) but still
    appear as a recoverable 'removed' row in the timeline.
    """
    if not bookings:
        return chunks
    booked_rows: list[dict[str, Any]] = []
    intervals: list[tuple[datetime, datetime]] = []
    for b in bookings:
        start = _parse_et(b.get("start_et"))
        end = _parse_et(b.get("end_et"))
        if start is None or end is None or end <= start:
            continue
        intervals.append((start, end))
        mins = max(1, int((end - start).total_seconds() // 60))
        if b.get("skip"):
            booked_rows.append(
                {
                    "start_et": start.isoformat(),
                    "end_et": end.isoformat(),
                    "chunk_minutes": mins,
                    "block_id": "removed",
                    "why": b.get("why") or "removed",
                    "channels": [],
                    "booking_id": b.get("id"),
                    "booked": True,
                    "skip": True,
                }
            )
            continue
        chans = [c for c in [b.get("stream_a"), b.get("stream_b")] if c]
        booked_rows.append(
            {
                "start_et": start.isoformat(),
                "end_et": end.isoformat(),
                "chunk_minutes": mins,
                "block_id": "booked",
                "why": b.get("why") or "booked",
                "channels": chans,
                "booking_id": b.get("id"),
                "booked": True,
                "skip": False,
            }
        )
    if not intervals:
        return chunks

    def free_parts(s: datetime, e: datetime) -> list[tuple[datetime, datetime]]:
        parts = [(s, e)]
        for bs, be in sorted(intervals):
            nxt: list[tuple[datetime, datetime]] = []
            for ps, pe in parts:
                if be <= ps or bs >= pe:
                    nxt.append((ps, pe))
                    continue
                if ps < bs:
                    nxt.append((ps, bs))
                if be < pe:
                    nxt.append((be, pe))
            parts = nxt
        return parts

    out: list[dict[str, Any]] = []
    for c in chunks:
        s = _parse_et(c.get("start_et"))
        e = _parse_et(c.get("end_et"))
        if s is None or e is None:
            continue
        for ps, pe in free_parts(s, e):
            if (pe - ps).total_seconds() < 60:
                continue
            row = dict(c)
            row["start_et"] = ps.isoformat()
            row["end_et"] = pe.isoformat()
            row.pop("booking_id", None)
            row["booked"] = False
            row["skip"] = False
            out.append(row)
    out.extend(booked_rows)
    out.sort(key=lambda r: str(r.get("start_et") or ""))
    return out


def _load_json(path: Path) -> Any:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def load_override(root: Path | None = None) -> dict[str, Any] | None:
    """Active agent overwrite, or None if missing/expired."""
    raw = _load_json(override_path(root))
    if not isinstance(raw, dict) or not raw.get("assignments"):
        return None
    hold = str(raw.get("hold_until_utc") or "").strip()
    if hold:
        try:
            until = datetime.fromisoformat(hold.replace("Z", "+00:00"))
            if until.tzinfo is None:
                until = until.replace(tzinfo=timezone.utc)
            if _now_utc() > until:
                return None
        except ValueError:
            pass
    return raw


def clear_override(root: Path | None = None) -> dict[str, Any]:
    path = override_path(root)
    existed = path.is_file()
    if existed:
        path.unlink()
    return {"ok": True, "cleared": existed, "path": str(path)}


# Programs are not "channels" — they air on a parent network / section.
# Source of truth for majors: major_programs.MAJOR_PROGRAMS (DOW + time + network).
PROGRAM_META: dict[str, dict[str, Any]] = as_program_meta()
PROGRAM_META["REALITY_TV_FILL"] = {
    "label": "Reality / unscripted fill",
    "kind": "program",
    "group": "Programs · live events",
    "airs_on": "Entertainment",
    "airs_group": "US ENTERTAINMENT",
    "home_channel_id": None,
    "open_via": "search",
    "search_query": "Big Brother",
    "keywords": "reality big brother unscripted fill",
    "schedule": "any",
}

GROUP_ORDER: tuple[str, ...] = (
    "Programs · live events",
    "US NEWS",
    "US SPORTS",
    "US ENTERTAINMENT",
    "US ABC SECTION",
    "US CBS SECTION",
    "US NBC SECTION",
    "US FOX SECTION",
    "ROKU TV",
    "PLUTO U.S.A.",
    "Other channels",
)


def catalog_lookup(channel_id: str) -> dict[str, Any]:
    """Resolve id → display metadata (program vs channel + parent group)."""
    cid = str(channel_id or "").strip()
    if not cid:
        return {
            "id": "",
            "label": "—",
            "kind": "empty",
            "group": "",
            "airs_on": "",
            "short": "—",
        }
    if cid in PROGRAM_META:
        meta = PROGRAM_META[cid]
        airs = str(meta.get("airs_on") or "")
        sched = str(meta.get("schedule") or "")
        short = str(meta["label"])
        if airs:
            short += f" · on {airs}"
        if sched and sched not in {"", "any"}:
            short += f" · {sched}"
        return {
            "id": cid,
            "label": str(meta["label"]),
            "kind": "program",
            "group": str(meta["group"]),
            "airs_on": airs,
            "airs_group": str(meta.get("airs_group") or ""),
            "schedule": sched,
            "short": short,
            "nav_route": str(meta.get("nav_route") or "") or "",
            "search_query": meta.get("search_query"),
            "open_via": meta.get("open_via") or "search",
            "home_channel_id": meta.get("home_channel_id"),
        }
    for c in catalog_entries():
        if c["id"] == cid:
            return c
    return {
        "id": cid,
        "label": cid.replace("_", " "),
        "kind": "channel",
        "group": "Other channels",
        "airs_on": "",
        "short": cid.replace("_", " "),
    }


def channel_choices() -> list[dict[str, str]]:
    """Flat picker list (legacy); prefer catalog_entries for UI."""
    out: list[dict[str, str]] = []
    for c in catalog_entries():
        out.append(
            {
                "id": str(c["id"]),
                "label": str(c.get("picker_label") or c.get("label") or c["id"]),
                "nav_route": str(c.get("nav_route") or "") or "",
            }
        )
    return out


def catalog_entries(*, root: Path | None = None) -> list[dict[str, Any]]:
    """Searchable program + channel catalog, sectioned by parent group."""
    from .coverage_farm import SEED_TARGETS

    seen: set[str] = set()
    out: list[dict[str, Any]] = []

    def add(row: dict[str, Any]) -> None:
        cid = str(row.get("id") or "").strip()
        if not cid or cid in seen:
            return
        seen.add(cid)
        group = str(row.get("group") or "Other channels")
        kind = str(row.get("kind") or "channel")
        label = str(row.get("label") or cid)
        airs = str(row.get("airs_on") or "")
        sched = str(row.get("schedule") or "")
        if kind == "program":
            bits = [label]
            if airs:
                bits.append(f"on {airs}")
            if sched and sched not in {"", "any"}:
                bits.append(sched)
            picker = " — ".join(bits) if len(bits) > 1 else label
            # Prefer " · " style for scannability
            picker = " · ".join(bits)
        else:
            picker = label
        keywords = " ".join(
            [
                label,
                cid,
                group,
                airs,
                sched,
                str(row.get("airs_group") or ""),
                str(row.get("keywords") or ""),
                str(row.get("search_query") or ""),
            ]
        ).lower()
        out.append(
            {
                **row,
                "id": cid,
                "label": label,
                "kind": kind,
                "group": group,
                "airs_on": airs,
                "schedule": sched,
                "picker_label": picker,
                "short": picker if kind == "program" else label,
                "keywords": keywords,
            }
        )

    for cid, meta in PROGRAM_META.items():
        add(
            {
                "id": cid,
                "label": meta["label"],
                "kind": "program",
                "group": meta["group"],
                "airs_on": meta.get("airs_on"),
                "airs_group": meta.get("airs_group"),
                "home_channel_id": meta.get("home_channel_id"),
                "nav_route": "",
                "search_query": meta.get("search_query"),
                "open_via": meta.get("open_via") or "search",
                "keywords": meta.get("keywords"),
            }
        )

    for t in SEED_TARGETS:
        cid = str(t.get("channel_id") or "").strip()
        if not cid or cid in PROGRAM_META:
            continue
        if t.get("any_us_local") and "FLAGSHIP" not in cid:
            continue
        add(
            {
                "id": cid,
                "label": str(t.get("guide_name") or cid).replace("US: ", ""),
                "kind": "channel",
                "group": str(t.get("group") or "Other channels"),
                "airs_on": "",
                "nav_route": str(t.get("nav_route") or "") or "",
                "search_query": t.get("search_query"),
                "open_via": t.get("open_via") or ("nav" if t.get("nav_route") else None),
                "keywords": f"{t.get('guide_name')} {t.get('group')} {cid}",
            }
        )

    # Guide catalog nationals / section samples for search.
    try:
        import sqlite3

        from .config import ensure_data_layout as _edl

        db = _edl(root) / "indexes" / "guide_catalog.sqlite"
        if db.is_file():
            con = sqlite3.connect(str(db))
            con.row_factory = sqlite3.Row
            rows = con.execute(
                """
                SELECT number, title, group_name FROM channels
                WHERE demoted IS NULL OR demoted = 0
                ORDER BY
                  CASE
                    WHEN title LIKE 'US: %' THEN 0
                    WHEN group_name LIKE 'US %SECTION' THEN 1
                    WHEN group_name IN ('US NEWS','US SPORTS','US ENTERTAINMENT') THEN 0
                    ELSE 2
                  END,
                  number
                LIMIT 180
                """
            ).fetchall()
            con.close()
            for r in rows:
                title = str(r["title"] or "").strip()
                group = str(r["group_name"] or "Other channels").strip() or "Other channels"
                if not title:
                    continue
                # Skip LAT: noise unless news/sports brand.
                if title.startswith("LAT:") and not any(
                    k in title.upper() for k in ("FOX NEWS", "CNN", "ESPN", "TNT")
                ):
                    continue
                num = r["number"]
                cid = f"GUIDE_{num}"
                add(
                    {
                        "id": cid,
                        "label": title,
                        "kind": "channel",
                        "group": group if group in GROUP_ORDER else group,
                        "airs_on": "",
                        "nav_route": "",
                        "search_query": title.split("|")[-1].strip() if "|" in title else title,
                        "open_via": "search",
                        "guide_number": num,
                        "keywords": f"{title} {group} {num}",
                    }
                )
    except Exception:
        pass

    def group_rank(g: str) -> int:
        try:
            return GROUP_ORDER.index(g)
        except ValueError:
            return len(GROUP_ORDER)

    out.sort(key=lambda r: (group_rank(str(r.get("group") or "")), str(r.get("label") or "")))
    return out


def catalog_grouped(*, root: Path | None = None) -> list[dict[str, Any]]:
    """[{group, items: [...]}] for optgroup / sectioned UI."""
    buckets: dict[str, list[dict[str, Any]]] = {}
    for c in catalog_entries(root=root):
        g = str(c.get("group") or "Other channels")
        buckets.setdefault(g, []).append(c)
    ordered: list[dict[str, Any]] = []
    seen_g: set[str] = set()
    for g in GROUP_ORDER:
        if g in buckets:
            ordered.append({"group": g, "items": buckets[g]})
            seen_g.add(g)
    for g, items in buckets.items():
        if g not in seen_g:
            ordered.append({"group": g, "items": items})
    return ordered


def enrich_timeline_display(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach scannable labels + program airs-on for each stream."""
    by_id = {str(c["id"]): c for c in catalog_entries()}
    for cid, meta in PROGRAM_META.items():
        by_id[cid] = catalog_lookup(cid)
    for r in rows:
        for side in ("a", "b"):
            key = f"stream_{side}"
            cid = str(r.get(key) or "")
            meta = by_id.get(cid) or catalog_lookup(cid)
            r[f"label_{side}"] = meta.get("short") or meta.get("label")
            r[f"kind_{side}"] = meta.get("kind")
            r[f"group_{side}"] = meta.get("group")
            r[f"airs_on_{side}"] = meta.get("airs_on") or ""
        start = _parse_et(r.get("start_et"))
        end = _parse_et(r.get("end_et"))
        if start and end:
            r["day_short"] = f"{start.strftime('%a')} {start.day}"
            r["time_range"] = f"{_fmt_clock(start)}–{_fmt_clock(end)}"
            mins = max(1, int((end - start).total_seconds() // 60))
            r["duration_min"] = mins
            r["duration_label"] = _fmt_duration(mins)
        else:
            r["day_short"] = ""
            r["time_range"] = ""
            r["duration_min"] = 0
            r["duration_label"] = ""
    return rows


def _fmt_clock(dt: datetime) -> str:
    h = dt.hour % 12 or 12
    m = dt.minute
    ap = "a" if dt.hour < 12 else "p"
    return f"{h}:{m:02d}{ap}"


def _fmt_duration(mins: int) -> str:
    mins = int(mins or 0)
    if mins < 60:
        return f"{mins}m"
    h, m = divmod(mins, 60)
    if m == 0:
        return f"{h}h"
    return f"{h}h {m}m"


def priority_switches(now: datetime | None = None) -> list[dict[str, Any]]:
    """Equal-weight sports + live TV presets for the emergency switcher.

    Same ROI band: live NFL / national games / awards / live competition.
    ``hot`` marks windows that match today's live daypart.
    """
    from .coverage_farm import live_windows_et

    local = (now or _now_et()).astimezone(ET)
    weekday = local.weekday()  # Mon=0
    windows = live_windows_et(local)
    hot_ids = {str(w.get("id") or "") for w in windows}

    # Presets: stream_a is the event; stream_b is the paired second player.
    presets: list[dict[str, Any]] = [
        {
            "id": "tnf",
            "label": "Thursday Night Football",
            "kind": "sports",
            "stream_a": "ESPN_US",
            "stream_b": "FOX_NEWS_US",
            "chunk_minutes": 60,
            "hold_hours": 4,
            "hot_when": {"weekdays": (3,), "window_ids": ("tnf_primetime",)},
        },
        {
            "id": "mnf",
            "label": "Monday Night Football",
            "kind": "sports",
            "stream_a": "ESPN_US",
            "stream_b": "ABC_LOCAL_FLAGSHIP",
            "chunk_minutes": 60,
            "hold_hours": 4,
            "hot_when": {"weekdays": (0,), "window_ids": ("mnf_primetime",)},
        },
        {
            "id": "nfl_sunday",
            "label": "NFL Sunday slate",
            "kind": "sports",
            "stream_a": "ESPN_US",
            "stream_b": "FOX_LOCAL_FLAGSHIP",
            "chunk_minutes": 60,
            "hold_hours": 6,
            "hot_when": {"weekdays": (6,), "window_ids": ("nfl_sunday", "nfl_sunday_germany_morning")},
        },
        {
            "id": "cfb",
            "label": "College football",
            "kind": "sports",
            "stream_a": "ESPN_US",
            "stream_b": "ESPN2_US",
            "chunk_minutes": 60,
            "hold_hours": 4,
            "hot_when": {"weekdays": (5,), "window_ids": ("cfb_saturday",)},
        },
        {
            "id": "nba_espn",
            "label": "NBA on ESPN",
            "kind": "sports",
            "stream_a": "ESPN_US",
            "stream_b": "TNT_US",
            "chunk_minutes": 60,
            "hold_hours": 3,
            "hot_when": {"window_ids": ("nba_nhl_evening", "nba_nhl_afternoon")},
        },
        {
            "id": "nba_tnt",
            "label": "NBA / NHL on TNT",
            "kind": "sports",
            "stream_a": "TNT_US",
            "stream_b": "ESPN_US",
            "chunk_minutes": 60,
            "hold_hours": 3,
            "hot_when": {"window_ids": ("nba_nhl_evening", "nba_nhl_afternoon")},
        },
        {
            "id": "cma",
            "label": "CMA Awards (on ABC)",
            "kind": "show",
            "stream_a": "CMA_AWARDS",
            "stream_b": "FOX_NEWS_US",
            "chunk_minutes": 60,
            "hold_hours": 4,
            "hot_when": {"weekdays": (2,), "window_ids": ("cma_awards_wednesday",)},
            "airs_on": "ABC",
            "pair_note": "Program search → ABC live card · P1 FOX NEWS",
        },
        {
            "id": "dwts",
            "label": "Dancing with the Stars (on ABC)",
            "kind": "show",
            "stream_a": "DWTS",
            "stream_b": "ABC_LOCAL_FLAGSHIP",
            "chunk_minutes": 60,
            "hold_hours": 3,
            "hot_when": {"weekdays": (1,), "window_ids": ("dwts_tuesday",)},
            "airs_on": "ABC",
            "pair_note": "Program search → ABC · P1 ABC local",
        },
        {
            "id": "network_primetime",
            "label": "Network primetime (ABC + NBC)",
            "kind": "show",
            "stream_a": "ABC_LOCAL_FLAGSHIP",
            "stream_b": "NBC_LOCAL_FLAGSHIP",
            "chunk_minutes": 60,
            "hold_hours": 3,
            "hot_when": {"weekdays": (0, 1, 2, 3, 4)},
        },
        {
            "id": "cable_news",
            "label": "Cable news dual (FOX NEWS + CNN)",
            "kind": "news",
            "stream_a": "FOX_NEWS_US",
            "stream_b": "CNN_US",
            "chunk_minutes": 20,
            "hold_hours": 2,
            "hot_when": {},
        },
    ]

    out: list[dict[str, Any]] = []
    for p in presets:
        hw = dict(p.get("hot_when") or {})
        wdays = hw.get("weekdays")
        win_ids = tuple(hw.get("window_ids") or ())
        hot = False
        if wdays is not None and weekday in set(wdays):
            hot = True
        if win_ids and any(wid in hot_ids for wid in win_ids):
            hot = True
        # Evening sports presets: only hot in the evening window hours.
        if p["id"] in {"nba_espn", "nba_tnt"} and not (19 <= local.hour < 24 or local.hour < 1):
            if weekday not in {5, 6} or not (12 <= local.hour < 24):
                hot = False
        row = {
            "id": p["id"],
            "label": p["label"],
            "kind": p["kind"],
            "stream_a": p["stream_a"],
            "stream_b": p["stream_b"],
            "chunk_minutes": int(p.get("chunk_minutes") or 60),
            "hold_hours": p.get("hold_hours"),
            "hot": hot,
            "airs_on": p.get("airs_on"),
            "pair_note": p.get("pair_note"),
            "why": f"emergency switch → {p['label']}",
        }
        out.append(row)
    # Merge full major-program catalog (Bachelor, Survivor, Voice, …).
    seen_a = {str(r.get("stream_a")) for r in out}
    for prog in priority_program_switches(local):
        sa = str(prog.get("stream_a") or "")
        if sa in seen_a and not prog.get("hot"):
            # Prefer existing sports presets unless program night is hot.
            continue
        if sa in seen_a:
            out = [r for r in out if str(r.get("stream_a")) != sa]
        out.append(prog)
        seen_a.add(sa)
    # Hot first, then sports, shows, news — stable within band.
    kind_rank = {"sports": 0, "show": 1, "news": 2}
    out.sort(key=lambda r: (0 if r.get("hot") else 1, kind_rank.get(str(r.get("kind")), 9), str(r.get("label"))))
    return out


def apply_schedule_edit(
    body: dict[str, Any],
    *,
    root: Path | None = None,
) -> dict[str, Any]:
    """UI / API edit: now-hold, clear, or Calendly-style book/update/delete.

    Body:
      action: "save" | "clear" | "book" | "delete_booking"
      why: optional note
      chunk_minutes: int (now-hold)
      hold_hours: optional float (now-hold)
      set_by: optional
      assignments: [{instance_id, channel_id, ...}]  (now-hold)
      id / start_et / end_et / stream_a / stream_b     (book)
    """
    root = ensure_data_layout(root)
    action = str(body.get("action") or "save").strip().lower()
    if action == "clear":
        cleared = clear_override(root)
        board = publish_recording_schedule(root, rebuild_plan=True)
        return {"ok": True, "action": "clear", **cleared, "board": board}
    if action in {"book", "update_booking", "upsert_booking"}:
        out = upsert_booking(body, root=root)
        out["action"] = "book"
        return out
    if action == "delete_booking":
        out = delete_booking(str(body.get("id") or ""), root=root)
        out["action"] = "delete_booking"
        return out
    if action == "remove_row":
        # Booked/skip → delete that booking. Auto plan row → punch a skip hole.
        bid = str(body.get("id") or body.get("booking_id") or "").strip()
        if bid:
            out = delete_booking(bid, root=root)
            out["action"] = "remove_row"
            return out
        out = upsert_booking(
            {
                "start_et": body.get("start_et"),
                "end_et": body.get("end_et"),
                "skip": True,
                "why": str(body.get("why") or "removed from schedule UI"),
                "set_by": str(body.get("set_by") or "schedule_ui"),
            },
            root=root,
        )
        out["action"] = "remove_row"
        return out
    if action != "save":
        return {"ok": False, "error": f"unknown_action:{action}"}

    chunk = int(body.get("chunk_minutes") or 20)
    rows_in = list(body.get("assignments") or [])
    rows: list[dict[str, Any]] = []
    for a in rows_in:
        iid = str(a.get("instance_id") or "").strip()
        cid = str(a.get("channel_id") or "").strip()
        if not iid or not cid or cid in {"", "—", "-"}:
            continue
        row = _make_channel_assignment(iid, cid, chunk_minutes=chunk)
        if a.get("nav_route"):
            row["nav_route"] = str(a.get("nav_route") or "").strip() or row.get("nav_route")
        rows.append(row)
    if not rows:
        return {"ok": False, "error": "no_assignments"}
    hold_hours = body.get("hold_hours")
    holds = None
    if hold_hours not in (None, "", 0, "0"):
        try:
            holds = (_now_utc() + timedelta(hours=float(hold_hours))).isoformat()
        except (TypeError, ValueError):
            holds = None
    out = set_override(
        rows,
        why=str(body.get("why") or "edited in schedule UI"),
        set_by=str(body.get("set_by") or "schedule_ui"),
        hold_until_utc=holds,
        chunk_minutes=chunk,
        root=root,
    )
    return {
        "ok": bool(out.get("ok")),
        "action": "save",
        "error": out.get("error"),
        "board": out.get("published"),
        "override": out.get("override"),
    }



def set_override(
    assignments: list[dict[str, Any]],
    *,
    why: str,
    set_by: str = "cursor_agent",
    hold_until_utc: str | None = None,
    chunk_minutes: int | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Write agent overwrite the desk must honor until cleared/expired."""
    root = ensure_data_layout(root)
    rows: list[dict[str, Any]] = []
    for a in assignments:
        iid = str(a.get("instance_id") or "").strip()
        cid = str(a.get("channel_id") or "").strip()
        if not iid or not cid:
            continue
        row = {
            "instance_id": iid,
            "channel_id": cid,
            "shortcut_id": str(a.get("shortcut_id") or cid),
            "nav_route": a.get("nav_route") or None,
            "open_via": a.get("open_via") or ("nav" if a.get("nav_route") else None),
            "search_query": a.get("search_query"),
            "label": str(a.get("label") or a.get("guide_name") or cid),
            "guide_name": a.get("guide_name"),
            "chunk_minutes": int(
                a.get("chunk_minutes") or chunk_minutes or 20
            ),
            "media": str(a.get("media") or "av"),
            "hold_if_on_air": True,
        }
        rows.append(row)
    if not rows:
        return {"ok": False, "error": "no_valid_assignments"}
    payload = {
        "version": 1,
        "set_utc": _now_utc().isoformat(),
        "set_by": set_by,
        "why": why or "agent_overwrite",
        "hold_until_utc": hold_until_utc,
        "assignments": rows,
        "lesson": (
            "Desk uses these assignments instead of auto demand-pool. "
            "Clear with recording_schedule clear-override or delete "
            f"{OVERRIDE_NAME}."
        ),
    }
    path = override_path(root)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    published = publish_recording_schedule(root, rebuild_plan=True)
    return {"ok": True, "path": str(path), "override": payload, "published": published}


def _parse_assign_token(token: str) -> dict[str, Any]:
    """Nougat32:FOX_NEWS_US or Nougat32:FOX_NEWS_US:FOX_NEWS_US (nav)."""
    parts = [p.strip() for p in token.split(":")]
    if len(parts) < 2:
        raise ValueError(f"bad assign token: {token}")
    iid, cid = parts[0], parts[1]
    nav = parts[2] if len(parts) >= 3 else (
        cid if cid.endswith("_US") or cid in {"CMA_AWARDS", "DWTS"} else None
    )
    return {
        "instance_id": iid,
        "channel_id": cid,
        "shortcut_id": cid,
        "nav_route": nav,
        "open_via": "nav" if nav else None,
        "label": cid,
    }


def _display_player(instance_id: str, *, root: Path | None = None) -> str:
    """UI label: Player 0 / Player 1 (engine id stays in data attrs)."""
    try:
        from .instances import player_label

        lab = player_label(instance_id, root=root)
    except Exception:
        lab = str(instance_id or "")
    if lab.lower().startswith("player "):
        return "Player " + lab.split(" ", 1)[1]
    return lab


def _player_rows(root: Path) -> list[dict[str, Any]]:
    """What heartbeat thinks each instance is on."""
    path = indexes_dir(root) / "heartbeat_fix_state.json"
    raw = _load_json(path) or {}
    inst = (raw.get("instances") or {}) if isinstance(raw, dict) else {}
    out: list[dict[str, Any]] = []
    for iid, st in inst.items():
        if not isinstance(st, dict):
            continue
        # Heartbeat keys are engine ids (Nougat32); skip job-id / alias duplicates.
        if len(iid) == 12 and iid.isalnum() and not iid.startswith("Nougat"):
            continue
        if iid.lower().startswith("player "):
            continue
        out.append(
            {
                "instance_id": iid,
                "player_label": _display_player(iid, root=root),
                "local_network": st.get("local_network"),
                "local_calls": st.get("local_calls"),
                "local_market": st.get("local_market"),
                "ui_kind": st.get("ui_kind"),
                "program_key": st.get("program_key"),
                "intended_hold_channel_id": st.get("intended_hold_channel_id"),
                "last_reason": st.get("last_reason") or st.get("reason"),
                "ok": st.get("ok"),
                "updated_utc": st.get("utc"),
            }
        )
    return out


def _jobs_ahead(root: Path, *, hours: int = 48) -> list[dict[str, Any]]:
    try:
        from .scheduler import load_jobs
    except Exception:
        return []
    now = _now_utc()
    end = now + timedelta(hours=hours)
    rows: list[dict[str, Any]] = []
    for job in load_jobs(root).get("jobs") or []:
        status = str(job.get("status") or "")
        if status not in {"scheduled", "due", "running", "starting", "live", "started"}:
            continue
        start_s = str(job.get("start_at") or "")
        try:
            start = datetime.fromisoformat(start_s.replace("Z", "+00:00"))
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if start > end:
            continue
        rows.append(
            {
                "job_id": job.get("job_id"),
                "status": status,
                "instance_id": job.get("instance_id"),
                "channel_id": job.get("channel_id") or job.get("shortcut_id"),
                "nav_route": job.get("nav_route"),
                "label": job.get("label"),
                "start_at": start.isoformat(),
                "minutes": job.get("minutes"),
                "apply_channel": job.get("apply_channel"),
            }
        )
    rows.sort(key=lambda r: (str(r.get("start_at") or ""), str(r.get("instance_id") or "")))
    return rows[:80]


def _collapse_timeline(
    chunks: list[dict[str, Any]],
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Merge consecutive same-block chunks into readable forward slots."""
    local = now or _now_et()
    rows: list[dict[str, Any]] = []
    for c in chunks:
        chans = list(c.get("channels") or [])
        start_s = str(c.get("start_et") or "")
        end_s = str(c.get("end_et") or "")
        try:
            start = datetime.fromisoformat(start_s)
            end = datetime.fromisoformat(end_s)
        except ValueError:
            continue
        key = (
            str(c.get("block_id") or ""),
            tuple(chans),
            int(c.get("chunk_minutes") or 0),
            str(c.get("booking_id") or ""),
            bool(c.get("booked")),
        )
        if rows:
            prev = rows[-1]
            prev_key = (
                str(prev.get("block_id") or ""),
                tuple(prev.get("channels") or []),
                int(prev.get("chunk_minutes") or 0),
                str(prev.get("booking_id") or ""),
                bool(prev.get("booked")),
            )
            # Extend if contiguous same plan.
            try:
                prev_end = datetime.fromisoformat(str(prev.get("end_et") or ""))
            except ValueError:
                prev_end = None
            if prev_key == key and prev_end is not None and abs((start - prev_end).total_seconds()) < 90:
                prev["end_et"] = end.isoformat()
                prev["slots"] = int(prev.get("slots") or 1) + 1
                continue
        is_now = start <= local < end
        is_past = end <= local
        rows.append(
            {
                "block_id": c.get("block_id"),
                "why": c.get("why"),
                "chunk_minutes": c.get("chunk_minutes"),
                "channels": chans,
                "stream_a": chans[0] if chans else None,
                "stream_b": chans[1] if len(chans) > 1 else None,
                "start_et": start.isoformat(),
                "end_et": end.isoformat(),
                "slots": 1,
                "is_now": is_now,
                "is_past": is_past,
                "booked": bool(c.get("booked")),
                "booking_id": c.get("booking_id"),
                "skip": bool(c.get("skip")),
            }
        )
    # Drop past blocks except the current one; keep forward slate.
    forward = [r for r in rows if r.get("is_now") or not r.get("is_past")]
    if forward and not any(r.get("is_now") for r in forward):
        # Chunk snap may start slightly after "now" — still highlight the live block.
        forward[0]["is_now"] = True
    return forward[:36]


def _on_correct_channel(player: dict[str, Any], assignment: dict[str, Any]) -> bool:
    """Cheap hold check: intended id matches hold stamp / non-local for news nav."""
    want = str(assignment.get("channel_id") or "").upper()
    nav = str(assignment.get("nav_route") or "").upper()
    hold = str(player.get("intended_hold_channel_id") or "").upper()
    if want and hold and want == hold and player.get("last_reason") in {
        "already_healthy",
        "identity_on_air_healthy",
        None,
        "",
    }:
        # Weak — prefer not local DMA when news nav is intended.
        pass
    calls = str(player.get("local_calls") or "").upper()
    net = str(player.get("local_network") or "").upper()
    # Named national news/sports: local FOX/CBS/NBC calls mean WRONG.
    if nav in {"FOX_NEWS_US", "CNN_US", "ESPN_US", "ESPN2_US", "TNT_US"}:
        if calls and net in {"FOX", "CBS", "NBC", "ABC"}:
            return False
        if hold == want and player.get("ok") is not False:
            return True
        # Fullscreen dump often blanks identity — treat intended hold + playing as hold.
        if hold == want and str(player.get("ui_kind") or "").startswith("player"):
            return True
        return False
    if want and hold == want:
        return True
    return False


def build_recording_schedule(
    root: Path | None = None,
    *,
    rebuild_plan: bool = True,
) -> dict[str, Any]:
    """Compose the board the desk and /schedule page publish."""
    root = ensure_data_layout(root)
    from .coverage_farm import (
        ROI_LADDER,
        ROI_BAND_LABELS,
        DATA_TARGET_MINUTES,
        active_regimented_block,
        build_capture_plan,
        capture_plan_path,
        record_priority_queue,
        regimented_chunks_ahead,
    )
    from .farm_loop import schedule_window

    override = load_override(root)
    bookings = load_bookings(root)
    plan: dict[str, Any]
    if rebuild_plan and not override:
        plan = build_capture_plan(root, include_listings=True)
    else:
        plan = _load_json(capture_plan_path(root)) or {}
        if not plan:
            plan = build_capture_plan(root, include_listings=True)

    local = _now_et()
    live_booking = active_booking_at(local, root=root, bookings=bookings)

    if override:
        assignments = [dict(a) for a in (override.get("assignments") or [])]
        source = "agent_override"
    elif live_booking:
        assignments = _assignments_from_booking(live_booking, root=root)
        source = "booking"
    else:
        assignments = [dict(a) for a in (plan.get("assignments") or [])]
        source = "capture_plan"

    block = active_regimented_block(local)
    chunks = list(plan.get("regimented_chunks_48h") or [])
    if not chunks:
        chunks = regimented_chunks_ahead(local, hours=48, max_streams=max(len(assignments), 2))
    chunks = _overlay_bookings_on_chunks(chunks, bookings)

    players = _player_rows(root)
    by_iid = {p["instance_id"]: p for p in players}
    for a in assignments:
        iid = str(a.get("instance_id") or "")
        pl = by_iid.get(iid) or {}
        a["player_label"] = _display_player(iid, root=root)
        a["player_state"] = pl or None
        # Keep heartbeat under player_state; avoid clobbering player index int.
        a["on_correct_channel"] = _on_correct_channel(pl, a) if pl else False
        a["action"] = (
            "hold"
            if a["on_correct_channel"]
            else ("retune" if a.get("nav_route") or a.get("search_query") else "open")
        )

    sched = schedule_window(root=root)
    timeline = enrich_timeline_display(_collapse_timeline(chunks, now=local))
    catalog = catalog_grouped(root=root)
    board = {
        "version": 1,
        "ok": True,
        "built_utc": _now_utc().isoformat(),
        "local_et": local.isoformat(),
        "source": source,
        "override_active": bool(override),
        "override": (
            {
                "set_utc": override.get("set_utc"),
                "set_by": override.get("set_by"),
                "why": override.get("why"),
                "hold_until_utc": override.get("hold_until_utc"),
            }
            if override
            else None
        ),
        "booking_active": bool(live_booking) and not bool(override),
        "active_booking": live_booking,
        "bookings": bookings,
        "roi_ladder": list(ROI_LADDER),
        "roi_band_labels": dict(ROI_BAND_LABELS),
        "data_target_minutes": dict(DATA_TARGET_MINUTES),
        "record_priority": record_priority_queue(root, now=local, include_listings=True, limit=20),
        "regimented_block": block,
        "chunk_minutes": plan.get("chunk_minutes")
        or (block or {}).get("chunk_minutes")
        or 20,
        "daypart": plan.get("daypart"),
        "record_window": {
            "mode": sched.get("mode"),
            "do_record": sched.get("do_record"),
            "do_label": sched.get("do_label"),
            "why": sched.get("why"),
        },
        "assignments": assignments,
        "timeline": timeline,
        "regimented_chunks_48h": chunks[:72],
        "jobs_ahead": _jobs_ahead(root),
        "players": players,
        "channel_choices": channel_choices(),
        "catalog_grouped": catalog,
        "catalog_flat": catalog_entries(root=root),
        "priority_switches": priority_switches(local),
        "upcoming_programs": upcoming_program_windows(local, hours=72),
        "urls": {
            "local": "http://127.0.0.1:3020/schedule",
            "public": "https://ohush.co/schedule",
            "api": "http://127.0.0.1:3020/api/schedule",
        },
        "paths": {
            "schedule": str(schedule_path(root)),
            "override": str(override_path(root)),
            "bookings": str(bookings_path(root)),
            "board_md": str(board_md_path(root)),
            "capture_plan": str(capture_plan_path(root)),
        },
        "policy": {
            "hold_if_on_correct": True,
            "agent_overwrite": (
                f"Write {OVERRIDE_NAME} or run "
                "`python -m tools.windows_lab recording_schedule set-override …`"
            ),
            "clear_overwrite": (
                "`python -m tools.windows_lab recording_schedule clear-override`"
            ),
            "desk": (
                "Orchestrator publishes this board each tick and materializes "
                "jobs from effective assignments; skips retune when on_correct_channel."
            ),
        },
    }
    return board


def _render_md(board: dict[str, Any]) -> str:
    lines = [
        "# Recording schedule",
        "",
        f"Updated: `{board.get('built_utc')}` · local ET `{board.get('local_et')}`",
        f"Source: **{board.get('source')}**"
        + (" (agent override)" if board.get("override_active") else ""),
        "",
        f"Monitor: {board.get('urls', {}).get('local')} · {board.get('urls', {}).get('public')}",
        "",
    ]
    ov = board.get("override") or {}
    if ov:
        lines += [
            "## Agent override",
            f"- By: `{ov.get('set_by')}` at `{ov.get('set_utc')}`",
            f"- Why: {ov.get('why')}",
            f"- Until: {ov.get('hold_until_utc') or 'cleared manually'}",
            "",
        ]
    rw = board.get("record_window") or {}
    block = board.get("regimented_block") or {}
    lines += [
        "## Now",
        f"- Record: **{rw.get('do_record')}** ({rw.get('mode')}) — {rw.get('why')}",
        f"- Block: `{block.get('id')}` · chunk **{board.get('chunk_minutes')}m**",
        f"- Why: {block.get('why') or '—'}",
        "",
        "## Forward schedule",
        "",
    ]
    for t in board.get("timeline") or []:
        flag = " **NOW**" if t.get("is_now") else ""
        start = str(t.get("start_et") or "")[5:16].replace("T", " ")
        end = str(t.get("end_et") or "")[11:16]
        lines.append(
            f"- `{start}→{end}`{flag} · A={t.get('stream_a')} · B={t.get('stream_b')} "
            f"— {t.get('why') or t.get('block_id')}"
        )
    lines += [
        "",
        "## Assignments (now)",
        "",
        "| Player | Channel | Action | On air |",
        "|---|---|---|---|",
    ]
    for a in board.get("assignments") or []:
        pl = a.get("player_state") or a.get("player") or {}
        if not isinstance(pl, dict):
            pl = {}
        player_s = (
            f"{pl.get('local_calls') or pl.get('local_network') or '—'} "
            f"({pl.get('ui_kind') or '?'})"
        )
        lines.append(
            f"| {a.get('player_label') or a.get('instance_id')} | {a.get('channel_id')} | "
            f"**{a.get('action')}** | {player_s} |"
        )
    lines += [
        "",
        "## Jobs ahead",
        "",
    ]
    for j in (board.get("jobs_ahead") or [])[:20]:
        lines.append(
            f"- `{j.get('status')}` {j.get('instance_id')} "
            f"{j.get('channel_id')} @ {j.get('start_at')} ({j.get('minutes')}m)"
        )
    lines += [
        "",
        "## Overwrite",
        board.get("policy", {}).get("agent_overwrite") or "",
        board.get("policy", {}).get("clear_overwrite") or "",
        "",
    ]
    return "\n".join(lines) + "\n"


def _render_html(board: dict[str, Any]) -> str:
    """Excel grid + Calendly-style book/edit for time blocks."""
    blob = json.dumps(board, default=str)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover"/>
<meta name="theme-color" content="#e8eef2"/>
<title>Recording schedule</title>
<link rel="preconnect" href="https://fonts.googleapis.com"/>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;600;700&family=IBM+Plex+Mono:wght@500;600&display=swap" rel="stylesheet"/>
<style>
  :root {{
    --bg: #e8eef2; --ink: #14212b; --muted: #5a6b78; --line: #c9d5de; --line2: #a8b8c4;
    --ok: #0f766e; --run: #0369a1; --card: #fff; --now: #ecfdf5; --head: #f1f5f9;
    --book: #fef3c7; --bookink: #92400e;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
    background: var(--bg); color: var(--ink);
    padding-bottom: calc(96px + env(safe-area-inset-bottom));
  }}
  header {{
    display: flex; justify-content: space-between; align-items: flex-start; gap: 12px;
    padding: 12px 14px; border-bottom: 1px solid var(--line);
    background: rgba(255,255,255,.94); position: sticky; top: 0; z-index: 5;
    backdrop-filter: blur(8px);
  }}
  h1 {{ margin: 0; font-size: 15px; }}
  .sub {{ margin: 3px 0 0; color: var(--muted); font-size: 12px; line-height: 1.35; }}
  .nav {{
    text-decoration: none; border: 1px solid var(--line); background: #fff;
    color: var(--ink); border-radius: 8px; padding: 8px 10px; font-weight: 700; font-size: 12px;
  }}
  main {{ max-width: 1100px; margin: 0 auto; padding: 12px 14px 20px; display: grid; gap: 10px; }}
  .banner {{
    border: 1px solid var(--line); background: var(--card); border-radius: 10px;
    padding: 10px 12px; font-size: 13px; line-height: 1.4;
  }}
  .banner.ov {{ border-color: #c4b5fd; background: #f5f3ff; }}
  .banner.bk {{ border-color: #fcd34d; background: #fffbeb; }}
  .hint {{ color: var(--muted); font-size: 12px; margin: 0; }}
  .switch-head {{
    margin: 0 0 6px; font-size: 12px; font-weight: 700; color: var(--muted);
    text-transform: uppercase; letter-spacing: .04em;
  }}
  .switches {{ display: grid; gap: 6px; }}
  button.switch {{
    min-height: 44px; width: 100%; text-align: left; padding: 8px 12px;
    display: grid; gap: 2px; background: #fff; border: 1px solid var(--line);
    border-radius: 10px; font-weight: 600; font-size: 13px;
  }}
  button.switch.hot {{
    border-color: #f59e0b; background: #fffbeb;
  }}
  button.switch .sw-top {{
    display: flex; justify-content: space-between; gap: 8px; align-items: baseline;
  }}
  button.switch .sw-pair {{
    color: var(--muted); font-size: 11px; font-weight: 600;
  }}
  button.switch .sw-kind {{
    font-size: 10px; font-weight: 700; text-transform: uppercase;
    letter-spacing: .04em; color: var(--run);
  }}
  button.switch.hot .sw-kind {{ color: var(--bookink); }}
  .sheet {{
    border: 1px solid var(--line2); border-radius: 10px; background: var(--card);
    overflow: auto; -webkit-overflow-scrolling: touch; max-height: calc(100vh - 260px);
  }}
  table.grid {{
    width: 100%; border-collapse: separate; border-spacing: 0;
    font-size: 13px; min-width: 720px;
  }}
  table.grid th, table.grid td {{
    border-bottom: 1px solid var(--line); border-right: 1px solid var(--line);
    padding: 8px 10px; text-align: left; vertical-align: middle; white-space: nowrap;
  }}
  table.grid th:last-child, table.grid td:last-child {{ border-right: 0; }}
  table.grid thead th {{
    position: sticky; top: 0; z-index: 2; background: var(--head); color: var(--muted);
    font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: .04em;
    border-bottom: 1px solid var(--line2);
  }}
  table.grid tbody tr.row-main {{ cursor: pointer; }}
  table.grid tbody tr.row-main:hover td {{ background: #f8fafc; }}
  table.grid tr.now td {{ background: var(--now); font-weight: 600; }}
  table.grid tr.now:hover td {{ background: #d1fae5; }}
  table.grid tr.booked td {{ background: var(--book); }}
  table.grid tr.booked:hover td {{ background: #fde68a; }}
  table.grid tr.booked.now td {{ background: #fde68a; }}
  table.grid tr.skip td {{ background: #f1f5f9; color: var(--muted); text-decoration: line-through; }}
  table.grid tr.gutter td {{
    padding: 0; border-bottom: 0; background: transparent; height: 28px;
  }}
  .gutter-line {{
    display: flex; align-items: center; justify-content: center; gap: 8px;
    height: 28px; position: relative;
  }}
  .gutter-line::before {{
    content: ""; position: absolute; left: 12px; right: 12px; top: 50%;
    border-top: 1px dashed var(--line); z-index: 0;
  }}
  button.icon {{
    position: relative; z-index: 1; min-height: 28px; min-width: 28px;
    height: 28px; width: 28px; padding: 0; border-radius: 8px;
    border: 1px solid var(--line); background: #fff; color: var(--ink);
    font-size: 16px; font-weight: 700; line-height: 1; cursor: pointer;
  }}
  button.icon.add {{ color: var(--ok); border-color: #99f6e4; }}
  button.icon.del {{ color: #b91c1c; border-color: #fecaca; }}
  .acts {{ display: inline-flex; gap: 6px; }}
  .cards {{ display: none; gap: 8px; }}
  .card {{
    border: 1px solid var(--line); border-radius: 12px; background: #fff;
    padding: 12px; display: grid; gap: 8px;
  }}
  .card.now {{ background: var(--now); border-color: #99f6e4; }}
  .card.booked {{ background: var(--book); border-color: #fcd34d; }}
  .card.skip {{ background: #f1f5f9; opacity: .85; }}
  .card-top {{ display: flex; justify-content: space-between; gap: 8px; align-items: flex-start; }}
  .card-time {{ font-family: "IBM Plex Mono", ui-monospace, monospace; font-weight: 700; font-size: 14px; }}
  .card-day {{ color: var(--muted); font-size: 12px; font-weight: 600; }}
  .card-chans {{ font-weight: 700; font-size: 15px; line-height: 1.3; }}
  .card-meta {{ color: var(--muted); font-size: 12px; }}
  .card-acts {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 6px; }}
  .card-acts button {{ min-height: 44px; font-size: 13px; }}
  .insert-bar {{
    display: flex; justify-content: center; padding: 2px 0;
  }}
  .insert-bar button {{
    min-height: 36px; border-radius: 999px; padding: 0 14px;
    border: 1px dashed var(--line2); background: #fff; color: var(--ok);
    font-size: 12px; font-weight: 700;
  }}
  @media (max-width: 720px) {{
    .sheet {{ max-height: none; overflow: visible; border: 0; background: transparent; }}
    table.grid {{ display: none; }}
    .cards {{ display: grid; }}
    .hint {{ font-size: 13px; }}
    .actions {{ grid-template-columns: 1fr 1.4fr; }}
    .actions #btnBookSaveBar {{ display: none; }}
    .row2 {{ grid-template-columns: 1fr; }}
  }}
  .mono {{
    font-family: "IBM Plex Mono", ui-monospace, monospace;
    font-variant-numeric: tabular-nums; font-weight: 600; font-size: 12.5px;
  }}
  .chan {{ font-weight: 700; }}
  .muted {{ color: var(--muted); font-weight: 500; }}
  .pill {{
    display: inline-block; padding: 1px 7px; border-radius: 999px;
    font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: .03em;
  }}
  .nowp {{ background: #ccfbf1; color: var(--ok); }}
  .nextp {{ background: #e0f2fe; color: var(--run); }}
  .bookp {{ background: #fde68a; color: var(--bookink); }}
  .skipp {{ background: #e2e8f0; color: #475569; }}
  .when {{
    display: grid; gap: 2px; min-width: 7.5rem;
  }}
  .when .day {{
    font-size: 11px; font-weight: 700; color: var(--muted);
    text-transform: uppercase; letter-spacing: .04em;
  }}
  .when .range {{
    font-family: "IBM Plex Mono", ui-monospace, monospace;
    font-weight: 700; font-size: 13px; font-variant-numeric: tabular-nums;
  }}
  .dur {{
    display: grid; gap: 4px; min-width: 4.2rem;
  }}
  .dur .lbl {{
    font-family: "IBM Plex Mono", ui-monospace, monospace;
    font-weight: 700; font-size: 12px;
  }}
  .dur .bar {{
    height: 6px; border-radius: 99px; background: #e2e8f0; overflow: hidden;
  }}
  .dur .bar > i {{
    display: block; height: 100%; border-radius: 99px; background: var(--run);
  }}
  .dur .bar.long > i {{ background: var(--ok); }}
  .stream {{
    display: grid; gap: 2px; white-space: normal; min-width: 8rem; max-width: 14rem;
    width: 100%; text-align: left; border: 1px solid transparent; background: transparent;
    border-radius: 10px; padding: 6px 8px; cursor: pointer; min-height: 52px;
    font: inherit; color: inherit;
  }}
  button.stream:hover, button.stream:focus {{
    border-color: var(--run); background: #f0f9ff; outline: none;
  }}
  .stream .name {{ font-weight: 700; line-height: 1.25; }}
  .stream .meta {{
    font-size: 10px; font-weight: 700; color: var(--muted);
    text-transform: uppercase; letter-spacing: .03em;
  }}
  .stream.program .meta {{ color: var(--bookink); }}
  .stream .tap {{
    font-size: 10px; font-weight: 700; color: var(--run); margin-top: 2px;
  }}
  .player-pick {{
    display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 8px;
  }}
  .player-pick button {{
    min-height: 56px; border-radius: 12px; border: 1px solid var(--line);
    background: #fff; font-weight: 700; font-size: 15px; display: grid; gap: 2px;
  }}
  .player-pick button.primary {{ background: var(--ok); color: #fff; border-color: var(--ok); }}
  .player-pick .pp-sub {{ font-size: 11px; font-weight: 600; opacity: .85; }}
  #fillHits {{ display: block; max-height: 45vh; margin-top: 8px; }}
  .fill-now {{
    border: 1px solid var(--line); border-radius: 10px; padding: 8px 10px;
    background: #f8fafc; font-size: 12px; color: var(--muted); margin-bottom: 8px;
  }}
  .chip {{
    display: inline-block; padding: 1px 6px; border-radius: 6px;
    font-size: 10px; font-weight: 700; background: #e2e8f0; color: #334155;
  }}
  .chip.program {{ background: #fde68a; color: var(--bookink); }}
  .chip.channel {{ background: #e0f2fe; color: var(--run); }}
  .search-wrap {{
    display: grid; gap: 6px; border: 1px solid var(--line); border-radius: 10px;
    background: var(--card); padding: 10px 12px;
  }}
  .search-wrap input {{
    width: 100%; min-height: 44px; font: inherit; font-size: 16px; font-weight: 600;
    border: 1px solid var(--line); border-radius: 10px; padding: 10px 12px;
  }}
  .search-hits {{
    display: none; max-height: 240px; overflow: auto; border: 1px solid var(--line);
    border-radius: 10px; background: #fff;
  }}
  .search-hits.open {{ display: block; }}
  .search-hits button {{
    width: 100%; text-align: left; min-height: 44px; border: 0; border-bottom: 1px solid var(--line);
    border-radius: 0; background: #fff; padding: 8px 12px; display: grid; gap: 2px;
  }}
  .search-hits button:last-child {{ border-bottom: 0; }}
  .search-hits .h-top {{ display: flex; justify-content: space-between; gap: 8px; font-weight: 700; font-size: 13px; }}
  .search-hits .h-sub {{ color: var(--muted); font-size: 11px; font-weight: 600; }}
  .prio-ladder {{
    display: flex; flex-wrap: wrap; gap: 4px; margin-bottom: 8px;
  }}
  .prio-ladder span {{
    font-size: 10px; font-weight: 700; padding: 3px 7px; border-radius: 6px;
    background: #e2e8f0; color: #334155;
  }}
  .prio-ladder span.top {{ background: #ccfbf1; color: var(--ok); }}
  .prio-ladder span.mid {{ background: #e0f2fe; color: var(--run); }}
  .need-crit {{ color: #b91c1c; }}
  .need-more {{ color: var(--bookink); }}
  .need-ok {{ color: var(--ok); }}
  .pick-search {{ margin-bottom: 6px; }}
  table.grid {{ min-width: 640px; }}
  .drawer {{
    position: fixed; inset: 0; z-index: 20; display: none;
    align-items: flex-end; justify-content: center;
    background: rgba(20,33,43,.35);
  }}
  .drawer.open {{ display: flex; }}
  .panel {{
    width: min(560px, 100%); max-height: min(92vh, 720px); overflow: auto;
    background: #fff; border-radius: 16px 16px 0 0;
    padding: 16px 16px calc(16px + env(safe-area-inset-bottom));
    box-shadow: 0 -8px 32px rgba(20,33,43,.18);
  }}
  .panel h2 {{ margin: 0 0 4px; font-size: 17px; }}
  .panel .sub2 {{ margin: 0 0 12px; color: var(--muted); font-size: 12px; }}
  .edit-body {{ display: grid; gap: 10px; }}
  .row2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }}
  label.field {{ display: grid; gap: 4px; font-size: 12px; font-weight: 600; color: var(--muted); }}
  select, input[type="text"], input[type="datetime-local"] {{
    width: 100%; min-height: 44px; font: inherit; font-size: 16px; font-weight: 600;
    color: var(--ink); border: 1px solid var(--line); border-radius: 10px;
    padding: 10px 12px; background: #fff;
  }}
  .panel-actions {{ display: grid; grid-template-columns: 1fr 1fr 1.3fr; gap: 8px; margin-top: 6px; }}
  details.edit {{
    border: 1px solid var(--line); border-radius: 10px; background: var(--card); padding: 10px 12px;
  }}
  details.edit summary {{
    cursor: pointer; font-size: 12px; font-weight: 700; color: var(--muted);
    text-transform: uppercase; letter-spacing: .04em; list-style: none;
  }}
  details.edit summary::-webkit-details-marker {{ display: none; }}
  .player-row {{ display: grid; gap: 6px; padding-top: 8px; border-top: 1px solid var(--line); }}
  .player-row:first-of-type {{ border-top: 0; padding-top: 0; }}
  .slot-top {{ display: flex; justify-content: space-between; gap: 8px; align-items: baseline; }}
  .meta {{ margin: 0; color: var(--muted); font-size: 12px; }}
  .actions {{
    position: fixed; left: 0; right: 0; bottom: 0; z-index: 4;
    padding: 10px 14px calc(10px + env(safe-area-inset-bottom));
    background: rgba(255,255,255,.94); border-top: 1px solid var(--line);
    backdrop-filter: blur(8px); display: grid; grid-template-columns: 1fr 1.2fr 1.2fr; gap: 8px;
    max-width: 1100px; margin: 0 auto;
  }}
  @media (min-width: 1100px) {{
    .actions {{ left: 50%; transform: translateX(-50%); width: 1100px; }}
  }}
  button {{
    min-height: 48px; border-radius: 10px; border: 1px solid var(--line);
    font: inherit; font-weight: 700; font-size: 14px; cursor: pointer;
  }}
  button.primary {{ background: var(--ok); color: #fff; border-color: var(--ok); }}
  button.ghost {{ background: #fff; color: var(--ink); }}
  button.danger {{ background: #fff; color: #b91c1c; border-color: #fecaca; }}
  button:disabled {{ opacity: .55; cursor: wait; }}
  .toast {{
    position: fixed; left: 50%; bottom: calc(84px + env(safe-area-inset-bottom));
    transform: translateX(-50%); background: #14212b; color: #fff;
    padding: 10px 14px; border-radius: 10px; font-size: 13px; font-weight: 600;
    z-index: 30; max-width: min(92vw, 420px); display: none;
  }}
  .toast.show {{ display: block; }}
</style>
</head>
<body>
<header>
  <div>
    <h1>Recording schedule</h1>
    <p class="sub" id="sub">Loading…</p>
  </div>
  <a class="nav" id="linkDash" href="/dashboard">Desk</a>
</header>
<main>
  <div id="status" class="banner">Loading…</div>
  <div class="search-wrap">
    <label class="field" style="margin:0">Search any program or channel
      <input id="globalSearch" type="search" placeholder="Bachelor, DWTS, Survivor, Voice, ESPN…" autocomplete="off"/>
    </label>
    <div class="search-hits" id="searchHits"></div>
    <p class="hint" style="margin:0">Guide knows major shows (network + night + time). You don’t have to.</p>
  </div>
  <div class="search-wrap" id="upcomingBox">
    <p class="switch-head" style="margin:0">Upcoming majors (next 72h) — tap to book</p>
    <div class="switches" id="upcoming"></div>
  </div>
  <div class="sheet">
    <table class="grid" id="grid">
      <thead>
        <tr>
          <th></th><th>When</th><th>Length</th>
          <th>Player 0</th><th>Player 1</th><th>Block</th><th></th>
        </tr>
      </thead>
      <tbody id="tbody"></tbody>
    </table>
    <div class="cards" id="cards"></div>
  </div>
  <details class="edit" id="editBox" open>
    <summary>Emergency: lock what’s on now</summary>
    <div class="edit-body" style="margin-top:10px">
      <p class="switch-head">Lock now — sports &amp; majors (hot night highlighted)</p>
      <div class="switches" id="switches"></div>
      <div class="row2" style="margin-top:4px">
        <label class="field">Chunk
          <select id="chunk">
            <option value="20">20 min</option>
            <option value="60">60 min</option>
            <option value="120">2 hours</option>
          </select>
        </label>
        <label class="field">Auto-expire
          <select id="holdHours">
            <option value="">Until I clear</option>
            <option value="1">1 hour</option>
            <option value="3">3 hours</option>
            <option value="6">6 hours</option>
            <option value="12">12 hours</option>
            <option value="24">24 hours</option>
          </select>
        </label>
      </div>
      <label class="field">Note<input id="why" type="text" maxlength="120" placeholder="optional"/></label>
      <div id="players"></div>
      <div class="row2">
        <button type="button" class="ghost" id="btnClear">Use auto</button>
        <button type="button" class="primary" id="btnSaveNow">Lock now</button>
      </div>
    </div>
  </details>
  <details class="edit" id="prioBox">
    <summary>Record priority — viewers × data need</summary>
    <div class="edit-body" style="margin-top:10px">
      <p class="hint" id="prioFormula" style="margin:0 0 6px">Loading…</p>
      <div class="prio-ladder" id="prioLadder"></div>
      <div class="switches" id="prioQueue"></div>
    </div>
  </details>
</main>
<div class="actions">
  <button type="button" class="ghost" id="btnRefresh">Refresh</button>
  <button type="button" class="primary" id="btnBook">+ Add row</button>
  <button type="button" class="ghost" id="btnBookSaveBar">Save booking</button>
</div>

<div class="drawer" id="drawer" aria-hidden="true">
  <div class="panel" role="dialog" aria-labelledby="drawerTitle">
    <h2 id="drawerTitle">Book a block</h2>
    <p class="sub2" id="drawerSub">Pick start, end, and channels — like Calendly for the two players.</p>
    <div class="edit-body">
      <input type="hidden" id="bookId"/>
      <div class="row2">
        <label class="field">Start (local)
          <input type="datetime-local" id="bookStart"/>
        </label>
        <label class="field">End (local)
          <input type="datetime-local" id="bookEnd"/>
        </label>
      </div>
      <label class="field">Duration shortcut
        <select id="bookDur">
          <option value="">Keep times above</option>
          <option value="20">20 minutes</option>
          <option value="60">1 hour</option>
          <option value="120">2 hours</option>
          <option value="180">3 hours</option>
        </select>
      </label>
      <label class="field pick-search">Filter catalog
        <input id="bookFilter" type="search" placeholder="type to filter programs & channels"/>
      </label>
      <div class="row2">
        <label class="field">Player 0
          <select id="bookA" size="6"></select>
        </label>
        <label class="field">Player 1
          <select id="bookB" size="6"></select>
        </label>
      </div>
      <p class="meta" id="bookHint">Programs are labeled with the network they air on.</p>
      <label class="field">Note
        <input id="bookWhy" type="text" maxlength="120" placeholder="e.g. MNF / CMA / news hour"/>
      </label>
      <div class="panel-actions">
        <button type="button" class="ghost" id="btnClose">Close</button>
        <button type="button" class="danger" id="btnDelete" style="display:none">Delete</button>
        <button type="button" class="primary" id="btnBookSave">Save</button>
      </div>
    </div>
  </div>
</div>
<div class="drawer" id="fillDrawer" aria-hidden="true">
  <div class="panel" role="dialog" aria-labelledby="fillTitle">
    <h2 id="fillTitle">Fill Player 0</h2>
    <p class="sub2" id="fillSub">Search and tap a program or channel for this player only.</p>
    <div class="fill-now" id="fillContext">—</div>
    <label class="field">Search
      <input id="fillSearch" type="search" placeholder="CMA, Bachelor, ESPN, FOX NEWS…" autocomplete="off"/>
    </label>
    <div class="search-hits open" id="fillHits"></div>
    <div class="panel-actions" style="grid-template-columns:1fr">
      <button type="button" class="ghost" id="btnFillClose">Close</button>
    </div>
  </div>
</div>
<div class="drawer" id="assignDrawer" aria-hidden="true">
  <div class="panel" role="dialog" aria-labelledby="assignTitle">
    <h2 id="assignTitle">Put on which player?</h2>
    <p class="sub2" id="assignSub">Choose Player 0 or Player 1 for the current / next block.</p>
    <div class="fill-now" id="assignContext">—</div>
    <div class="player-pick">
      <button type="button" class="primary" id="assignP0">Player 0<span class="pp-sub" id="assignP0cur">—</span></button>
      <button type="button" class="primary" id="assignP1">Player 1<span class="pp-sub" id="assignP1cur">—</span></button>
    </div>
    <div class="panel-actions" style="grid-template-columns:1fr;margin-top:10px">
      <button type="button" class="ghost" id="btnAssignClose">Cancel</button>
    </div>
  </div>
</div>
<div class="toast" id="toast"></div>
<script>
const BOOT = {blob};
const BASE = (location.pathname.startsWith('/verdict/')) ? '/verdict' : '';
function api(path) {{ return BASE + path; }}
let state = BOOT;
let dirty = false;
const pretty = {{}};
function catalogFlat() {{ return state.catalog_flat || []; }}
function catalogGrouped() {{ return state.catalog_grouped || []; }}
function entryFor(id) {{
  const cid = id || '';
  return catalogFlat().find(c => c.id === cid) || null;
}}
function label(id) {{
  const e = entryFor(id);
  if (e) return e.short || e.label || id;
  return pretty[id] || (id || '—').replace(/_/g,' ');
}}
function streamCell(id, kind, airs, lab, {{idx, side}} = {{}}) {{
  const e = entryFor(id) || {{}};
  const k = kind || e.kind || (id ? 'channel' : 'empty');
  const name = lab || e.short || label(id);
  const air = airs || e.airs_on || '';
  const group = e.group || '';
  let meta = '';
  if (k === 'program') meta = 'program · on ' + (air || '?');
  else if (group) meta = 'channel · ' + group.replace(/^US /,'');
  else if (!id) meta = 'empty · tap to fill';
  else meta = 'channel';
  const who = side === 'b' ? 'Player 1' : 'Player 0';
  const attrs = (idx != null && side)
    ? ' type="button" data-fill-idx="'+idx+'" data-fill-side="'+side+'"'
    : ' type="button" disabled';
  return '<button class="stream '+k+'"'+attrs+'>'
    + '<div class="name">'+name+'</div>'
    + (meta ? '<div class="meta">'+meta+'</div>' : '')
    + '<div class="tap">tap · change '+who+'</div>'
    + '</button>';
}}
let fillCtx = null; // {{idx, side, row}}
let assignCtx = null; // {{id, entry}}
function targetRow() {{
  const rows = state.timeline || [];
  return rows.find(r => r.is_now && !r.skip) || rows.find(r => !r.skip) || rows[0] || null;
}}
function openFillPlayer(idx, side) {{
  const row = (state.timeline || [])[idx];
  if (!row || row.skip) return;
  fillCtx = {{ idx, side, row }};
  const who = side === 'b' ? 'Player 1' : 'Player 0';
  const cur = side === 'b' ? row.stream_b : row.stream_a;
  document.getElementById('fillTitle').textContent = 'Fill ' + who;
  document.getElementById('fillSub').textContent =
    'Only changes ' + who + ' for this block. The other player stays put.';
  document.getElementById('fillContext').textContent =
    (row.day_short || '') + ' · ' + (row.time_range || '') + ' · now: ' + label(cur);
  document.getElementById('fillSearch').value = '';
  renderFillHits('');
  document.getElementById('fillDrawer').classList.add('open');
  document.getElementById('fillDrawer').setAttribute('aria-hidden', 'false');
  setTimeout(() => document.getElementById('fillSearch').focus(), 50);
}}
function closeFill() {{
  document.getElementById('fillDrawer').classList.remove('open');
  document.getElementById('fillDrawer').setAttribute('aria-hidden', 'true');
  fillCtx = null;
}}
function renderFillHits(q) {{
  const box = document.getElementById('fillHits');
  const query = String(q || '').trim().toLowerCase();
  let hits = catalogFlat();
  if (query) hits = hits.filter(c => String(c.keywords || '').includes(query));
  hits = hits.slice(0, 40);
  if (!hits.length) {{
    box.innerHTML = '<button type="button" disabled><span class="h-top">No matches</span></button>';
    return;
  }}
  box.innerHTML = hits.map(c => {{
    const tag = c.kind === 'program'
      ? '<span class="chip program">program · '+(c.airs_on||'?')+'</span>'
      : '<span class="chip channel">channel</span>';
    const sub = c.kind === 'program'
      ? ('on '+(c.airs_on||'?')+' · '+(c.schedule||''))
      : (c.group || '');
    return '<button type="button" data-fill-pick="'+c.id+'">'
      + '<span class="h-top"><span>'+c.label+'</span>'+tag+'</span>'
      + '<span class="h-sub">'+sub+'</span></button>';
  }}).join('');
  box.querySelectorAll('[data-fill-pick]').forEach(btn => {{
    btn.addEventListener('click', () => applyFillPick(btn.getAttribute('data-fill-pick')));
  }});
}}
async function applyFillPick(id) {{
  if (!fillCtx || !fillCtx.row) return;
  const row = fillCtx.row;
  const side = fillCtx.side;
  const stream_a = side === 'a' ? id : (row.stream_a || '');
  const stream_b = side === 'b' ? id : (row.stream_b || '');
  const who = side === 'b' ? 'Player 1' : 'Player 0';
  try {{
    await post({{
      action: 'book',
      set_by: 'schedule_ui',
      // New id so normalize merges by time; avoid stomping unrelated booking ids.
      id: null,
      start_et: row.start_et,
      end_et: row.end_et,
      stream_a: stream_a || null,
      stream_b: stream_b || null,
      fill_side: side,
      why: 'fill ' + who + ' → ' + label(id),
    }});
    closeFill();
    toast(who + ' → ' + label(id));
  }} catch (err) {{ toast(String(err.message || err)); }}
}}
function openAssignPlayer(id) {{
  const e = entryFor(id);
  const row = targetRow();
  assignCtx = {{ id, entry: e, row }};
  document.getElementById('assignTitle').textContent = 'Put on which player?';
  document.getElementById('assignSub').textContent =
    (e && e.label ? e.label : id) + (e && e.airs_on ? (' · on ' + e.airs_on) : '');
  if (row) {{
    document.getElementById('assignContext').textContent =
      'Block: ' + (row.day_short||'') + ' · ' + (row.time_range||'');
    document.getElementById('assignP0cur').textContent = 'now: ' + label(row.stream_a);
    document.getElementById('assignP1cur').textContent = 'now: ' + label(row.stream_b);
  }} else {{
    document.getElementById('assignContext').textContent = 'No schedule row — will book the next hour';
    document.getElementById('assignP0cur').textContent = 'empty';
    document.getElementById('assignP1cur').textContent = 'empty';
  }}
  document.getElementById('assignDrawer').classList.add('open');
  document.getElementById('assignDrawer').setAttribute('aria-hidden', 'false');
}}
function closeAssign() {{
  document.getElementById('assignDrawer').classList.remove('open');
  document.getElementById('assignDrawer').setAttribute('aria-hidden', 'true');
  assignCtx = null;
}}
async function assignToSide(side) {{
  if (!assignCtx) return;
  const id = assignCtx.id;
  let row = assignCtx.row;
  if (!row) {{
    const start = new Date();
    start.setMinutes(Math.ceil(start.getMinutes() / 10) * 10, 0, 0);
    const end = new Date(start.getTime() + 60 * 60000);
    row = {{
      start_et: start.toISOString(),
      end_et: end.toISOString(),
      stream_a: 'FOX_NEWS_US',
      stream_b: 'CNN_US',
    }};
  }}
  fillCtx = {{ idx: -1, side, row }};
  closeAssign();
  await applyFillPick(id);
}}
function whenCell(r) {{
  return '<div class="when"><div class="day">'+(r.day_short||'')+'</div>'
    + '<div class="range">'+(r.time_range||'')+'</div></div>';
}}
function durCell(r) {{
  const mins = Number(r.duration_min || 0);
  const pct = Math.max(8, Math.min(100, Math.round(mins / 180 * 100)));
  const long = mins >= 60 ? ' long' : '';
  return '<div class="dur"><div class="lbl">'+(r.duration_label||'')+'</div>'
    + '<div class="bar'+long+'"><i style="width:'+pct+'%"></i></div></div>';
}}
function choicesHtml(selected, {{filter, blank}} = {{}}) {{
  const q = String(filter || '').trim().toLowerCase();
  let html = blank ? '<option value="">—</option>' : '';
  for (const g of catalogGrouped()) {{
    const items = (g.items || []).filter(c => {{
      if (!q) return true;
      return String(c.keywords || c.picker_label || c.label || '').toLowerCase().includes(q);
    }});
    if (!items.length) continue;
    html += '<optgroup label="'+g.group+'">';
    for (const c of items) {{
      html += '<option value="'+c.id+'"'+(c.id===selected?' selected':'')+'>'
        + (c.picker_label || c.label) + '</option>';
    }}
    html += '</optgroup>';
  }}
  if (selected && !catalogFlat().some(c => c.id === selected)) {{
    html = '<option value="'+selected+'" selected>'+label(selected)+'</option>' + html;
  }}
  return html;
}}
function fillBookSelects(a, b, filter) {{
  document.getElementById('bookA').innerHTML = choicesHtml(a || '', {{filter}});
  document.getElementById('bookB').innerHTML = choicesHtml(b || '', {{filter}});
  const ea = entryFor(a);
  const tip = document.getElementById('bookHint');
  if (tip) {{
    tip.textContent = ea && ea.kind === 'program'
      ? (ea.label + ' is a program — airs on ' + (ea.airs_on||'?') + ' (' + (ea.airs_group||ea.group) + '). Opens via guide search.')
      : 'Programs are labeled with the network they air on. Channels are under Streamers parent groups.';
  }}
}}
function toast(msg) {{
  const el = document.getElementById('toast');
  el.textContent = msg; el.classList.add('show');
  clearTimeout(toast._t);
  toast._t = setTimeout(() => el.classList.remove('show'), 2400);
}}
function pad(n) {{ return String(n).padStart(2,'0'); }}
function parts(iso) {{
  const d = new Date(iso);
  return {{
    day: d.toLocaleDateString(undefined, {{ weekday: 'short', month: 'short', day: 'numeric' }}),
    hm: pad(d.getHours()) + ':' + pad(d.getMinutes()),
  }};
}}
function minsBetween(a, b) {{
  return Math.round((new Date(b) - new Date(a)) / 60000);
}}
function toLocalInput(iso) {{
  const d = iso ? new Date(iso) : new Date();
  return d.getFullYear() + '-' + pad(d.getMonth()+1) + '-' + pad(d.getDate())
    + 'T' + pad(d.getHours()) + ':' + pad(d.getMinutes());
}}
function fromLocalInput(v) {{
  if (!v) return null;
  const d = new Date(v);
  if (Number.isNaN(d.getTime())) return null;
  // Keep local wall-clock as America/New_York-ish ISO without Z (naive ET for desk).
  return d.getFullYear() + '-' + pad(d.getMonth()+1) + '-' + pad(d.getDate())
    + 'T' + pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':00';
}}
function openDrawer(row) {{
  const title = document.getElementById('drawerTitle');
  const sub = document.getElementById('drawerSub');
  const del = document.getElementById('btnDelete');
  if (row && row.booking_id) {{
    title.textContent = row.skip ? 'Removed block' : 'Edit booked block';
    sub.textContent = row.skip
      ? 'Delete to restore the auto plan for this window, or set channels to re-book.'
      : 'Change times or channels. This window overrides the auto plan.';
    document.getElementById('bookId').value = row.booking_id;
    document.getElementById('bookStart').value = toLocalInput(row.start_et);
    document.getElementById('bookEnd').value = toLocalInput(row.end_et);
    document.getElementById('bookWhy').value = row.why || '';
    document.getElementById('bookDur').value = '';
    document.getElementById('bookFilter').value = ''; fillBookSelects(row.stream_a, row.stream_b);
    del.style.display = '';
  }} else if (row) {{
    title.textContent = 'Replace this slot';
    sub.textContent = 'Books over the auto plan for this window. Adjust times if you want longer/shorter.';
    document.getElementById('bookId').value = '';
    document.getElementById('bookStart').value = toLocalInput(row.start_et);
    document.getElementById('bookEnd').value = toLocalInput(row.end_et);
    document.getElementById('bookWhy').value = '';
    document.getElementById('bookDur').value = '';
    document.getElementById('bookFilter').value = ''; fillBookSelects(row.stream_a, row.stream_b);
    del.style.display = 'none';
  }} else {{
    title.textContent = 'Book a block';
    sub.textContent = 'Pick start, end, and channels — like Calendly for the two players.';
    const start = new Date();
    start.setMinutes(Math.ceil(start.getMinutes() / 10) * 10, 0, 0);
    const end = new Date(start.getTime() + 60 * 60000);
    document.getElementById('bookId').value = '';
    document.getElementById('bookStart').value = toLocalInput(start.toISOString());
    document.getElementById('bookEnd').value = toLocalInput(end.toISOString());
    document.getElementById('bookWhy').value = '';
    document.getElementById('bookDur').value = '60';
    const nowRow = (state.timeline || []).find(r => r.is_now) || (state.timeline || [])[0] || {{}};
    document.getElementById('bookFilter').value = ''; fillBookSelects(nowRow.stream_a, nowRow.stream_b);
    del.style.display = 'none';
  }}
  document.getElementById('drawer').classList.add('open');
  document.getElementById('drawer').setAttribute('aria-hidden', 'false');
}}
function closeDrawer() {{
  document.getElementById('drawer').classList.remove('open');
  document.getElementById('drawer').setAttribute('aria-hidden', 'true');
}}
function renderGrid(b) {{
  const tb = document.getElementById('tbody');
  const cards = document.getElementById('cards');
  const rows = b.timeline || [];
  if (!rows.length) {{
    tb.innerHTML = '<tr><td colspan="7" class="muted">No forward slots yet — tap + Add row</td></tr>';
    cards.innerHTML = '<p class="meta">No forward slots yet.</p>';
    return;
  }}
  let html = '';
  html += '<tr class="gutter"><td colspan="7"><div class="gutter-line">'
    + '<button type="button" class="icon add" data-insert="0" title="Add row before">+</button>'
    + '</div></td></tr>';
  rows.forEach((r, idx) => {{
    let st = '';
    if (r.skip) st = '<span class="pill skipp">removed</span>';
    else if (r.booked) st = '<span class="pill bookp">booked</span>';
    else if (r.is_now) st = '<span class="pill nowp">now</span>';
    else st = '<span class="pill nextp">auto</span>';
    const block = r.skip ? 'removed' : (r.booked ? (r.why || 'booked') : (r.block_id || '').replace(/_/g,' '));
    const cls = ['row-main', r.is_now ? 'now' : '', r.booked ? 'booked' : '', r.skip ? 'skip' : ''].filter(Boolean).join(' ');
    html += '<tr class="'+cls+'" data-idx="'+idx+'">'
      + '<td><div class="acts"><button type="button" class="icon del" data-del="'+idx+'" title="Remove">−</button></div></td>'
      + '<td>'+whenCell(r)+'</td>'
      + '<td>'+durCell(r)+'</td>'
      + '<td>'+(r.skip ? '—' : streamCell(r.stream_a, r.kind_a, r.airs_on_a, r.label_a, {{idx, side:'a'}}))+'</td>'
      + '<td>'+(r.skip ? '—' : streamCell(r.stream_b, r.kind_b, r.airs_on_b, r.label_b, {{idx, side:'b'}}))+'</td>'
      + '<td class="muted">'+block+'</td>'
      + '<td>'+st+'</td>'
      + '</tr>';
    html += '<tr class="gutter"><td colspan="7"><div class="gutter-line">'
      + '<button type="button" class="icon add" data-insert="'+(idx+1)+'" title="Add after">+</button>'
      + '</div></td></tr>';
  }});
  tb.innerHTML = html;

  let cardHtml = '<div class="insert-bar"><button type="button" data-insert="0">+ Add before first</button></div>';
  rows.forEach((r, idx) => {{
    let st = '';
    if (r.skip) st = '<span class="pill skipp">removed</span>';
    else if (r.booked) st = '<span class="pill bookp">booked</span>';
    else if (r.is_now) st = '<span class="pill nowp">now</span>';
    else st = '<span class="pill nextp">auto</span>';
    const cls = ['card', r.is_now ? 'now' : '', r.booked ? 'booked' : '', r.skip ? 'skip' : ''].filter(Boolean).join(' ');
    const block = r.skip ? 'removed' : (r.booked ? (r.why || 'booked') : (r.block_id || '').replace(/_/g,' '));
    cardHtml += '<article class="'+cls+'" data-idx="'+idx+'">'
      + '<div class="card-top"><div>'+whenCell(r)+'<div style="margin-top:6px">'+durCell(r)+'</div></div>'+st+'</div>'
      + '<div>'+(r.skip ? '<div class="card-chans">Row removed</div>' :
          streamCell(r.stream_a, r.kind_a, r.airs_on_a, r.label_a, {{idx, side:'a'}})
          + '<div style="height:8px"></div>'
          + streamCell(r.stream_b, r.kind_b, r.airs_on_b, r.label_b, {{idx, side:'b'}}))+'</div>'
      + '<div class="card-meta">'+block+'</div>'
      + '<div class="card-acts" style="grid-template-columns:1fr 1fr 1fr 1fr">'
      + '<button type="button" class="primary" data-fill-idx="'+idx+'" data-fill-side="a">P0</button>'
      + '<button type="button" class="primary" data-fill-idx="'+idx+'" data-fill-side="b">P1</button>'
      + '<button type="button" class="ghost" data-edit="'+idx+'">Edit</button>'
      + '<button type="button" class="ghost" data-del="'+idx+'">−</button>'
      + '</div></article>'
      + '<div class="insert-bar"><button type="button" data-insert="'+(idx+1)+'">+ Insert here</button></div>';
  }});
  cards.innerHTML = cardHtml;

  function bindInsert(el) {{
    el.querySelectorAll('[data-insert]').forEach(btn => {{
      btn.addEventListener('click', (ev) => {{
        ev.stopPropagation();
        openInsertAt(Number(btn.getAttribute('data-insert')));
      }});
    }});
  }}
  function bindDel(el) {{
    el.querySelectorAll('[data-del]').forEach(btn => {{
      btn.addEventListener('click', (ev) => {{
        ev.stopPropagation();
        removeRowAt(Number(btn.getAttribute('data-del')));
      }});
    }});
  }}
  bindInsert(tb); bindDel(tb);
  bindInsert(cards); bindDel(cards);
  function bindFill(el) {{
    el.querySelectorAll('[data-fill-idx]').forEach(btn => {{
      btn.addEventListener('click', (ev) => {{
        ev.stopPropagation();
        openFillPlayer(Number(btn.getAttribute('data-fill-idx')), btn.getAttribute('data-fill-side'));
      }});
    }});
  }}
  bindFill(tb); bindFill(cards);
  tb.querySelectorAll('tr.row-main').forEach(tr => {{
    tr.addEventListener('click', (ev) => {{
      if (ev.target.closest('[data-fill-idx]')) return;
      const row = (state.timeline || [])[Number(tr.dataset.idx)];
      if (row) openDrawer(row);
    }});
  }});
  cards.querySelectorAll('[data-edit]').forEach(btn => {{
    btn.addEventListener('click', (ev) => {{
      ev.stopPropagation();
      const row = (state.timeline || [])[Number(btn.getAttribute('data-edit'))];
      if (row) openDrawer(row);
    }});
  }});
  cards.querySelectorAll('article.card').forEach(card => {{
    card.addEventListener('click', (ev) => {{
      if (ev.target.closest('[data-fill-idx],[data-del],[data-insert],[data-edit]')) return;
      const row = (state.timeline || [])[Number(card.dataset.idx)];
      if (row) openDrawer(row);
    }});
  }});
}}
function openInsertAt(at) {{
  const rows = state.timeline || [];
  const prev = at > 0 ? rows[at - 1] : null;
  const next = at < rows.length ? rows[at] : null;
  let startIso, endIso;
  if (prev && next) {{
    startIso = prev.end_et;
    const gap = new Date(next.start_et) - new Date(prev.end_et);
    if (gap >= 5 * 60000) endIso = next.start_et;
    else endIso = new Date(new Date(prev.end_et).getTime() + 60 * 60000).toISOString();
  }} else if (prev) {{
    startIso = prev.end_et;
    endIso = new Date(new Date(prev.end_et).getTime() + 60 * 60000).toISOString();
  }} else if (next) {{
    endIso = next.start_et;
    startIso = new Date(new Date(next.start_et).getTime() - 60 * 60000).toISOString();
  }} else {{
    openDrawer(null);
    return;
  }}
  openDrawer({{
    start_et: startIso,
    end_et: endIso,
    stream_a: (prev && prev.stream_a) || (next && next.stream_a) || 'FOX_NEWS_US',
    stream_b: (prev && prev.stream_b) || (next && next.stream_b) || 'CNN_US',
    why: '',
  }});
}}
async function removeRowAt(idx) {{
  const row = (state.timeline || [])[idx];
  if (!row) return;
  const msg = row.booked || row.skip
    ? 'Remove this booked/removed row?'
    : 'Remove this auto block from the schedule?';
  if (!confirm(msg)) return;
  try {{
    await post({{
      action: 'remove_row',
      set_by: 'schedule_ui',
      id: row.booking_id || null,
      start_et: row.start_et,
      end_et: row.end_et,
      why: 'removed from schedule UI',
    }});
    toast(row.booked || row.skip ? 'Row removed' : 'Auto block removed');
  }} catch (err) {{ toast(String(err.message || err)); }}
}}
function renderSwitches(b) {{
  const box = document.getElementById('switches');
  const rows = b.priority_switches || [];
  if (!rows.length) {{
    box.innerHTML = '<p class="meta">No presets.</p>';
    return;
  }}
  box.innerHTML = rows.map(s => {{
    const kind = s.hot ? 'today' : (s.kind || '');
    const note = s.pair_note || s.schedule || ('P0 '+label(s.stream_a)+' · P1 '+label(s.stream_b));
    return '<button type="button" class="switch'+(s.hot?' hot':'')+'" data-id="'+s.id+'">'
      + '<span class="sw-top"><span>'+s.label+'</span><span class="sw-kind">'+kind+'</span></span>'
      + '<span class="sw-pair">'+note+'</span>'
      + '</button>';
  }}).join('');
  box.querySelectorAll('button.switch').forEach(btn => {{
    btn.addEventListener('click', () => applySwitch(btn.dataset.id));
  }});
}}
function renderPriority(b) {{
  const rp = b.record_priority || {{}};
  const formula = document.getElementById('prioFormula');
  if (formula) formula.textContent = rp.formula || 'Viewers first, then fill data holes.';
  const ladder = document.getElementById('prioLadder');
  const hier = rp.hierarchy || (b.roi_ladder || []).map((band, i) => ({{ rank: i, band, label: (b.roi_band_labels||{{}})[band] || band }}));
  if (ladder) {{
    ladder.innerHTML = hier.map((h, i) => {{
      const cls = i < 4 ? 'top' : (i < 7 ? 'mid' : '');
      return '<span class="'+cls+'">'+(i+1)+'. '+(h.label || h.band)+'</span>';
    }}).join('');
  }}
  const box = document.getElementById('prioQueue');
  const rows = rp.queue || [];
  if (!box) return;
  if (!rows.length) {{
    box.innerHTML = '<p class="meta">No priority rows.</p>';
    return;
  }}
  box.innerHTML = rows.slice(0, 12).map(r => {{
    const need = r.data || '';
    const needCls = need.indexOf('critical') >= 0 ? 'need-crit' : (need.indexOf('more') >= 0 ? 'need-more' : 'need-ok');
    return '<button type="button" class="switch" data-prio="'+r.channel_id+'">'
      + '<span class="sw-top"><span>#'+r.rank+' '+ (r.label || r.channel_id) +'</span>'
      + '<span class="sw-kind">'+ (r.kind || '') +'</span></span>'
      + '<span class="sw-pair">'+ (r.viewers || '') +' · <span class="'+needCls+'">'+need
      + ' ('+ (r.have_minutes||0) +'/'+ (r.target_minutes||0) +'m)</span></span>'
      + '</button>';
  }}).join('');
  box.querySelectorAll('[data-prio]').forEach(btn => {{
    btn.addEventListener('click', () => {{
      const id = btn.getAttribute('data-prio');
      const row = (state.record_priority && state.record_priority.queue || []).find(x => x.channel_id === id);
      openAssignPlayer(id);
    }});
  }});
}}
function renderUpcoming(b) {{

  const box = document.getElementById('upcoming');
  const rows = b.upcoming_programs || [];
  if (!rows.length) {{
    box.innerHTML = '<p class="meta">No catalog windows in the next 72h.</p>';
    return;
  }}
  box.innerHTML = rows.slice(0, 16).map((u, idx) => {{
    const when = (u.start_et || '').replace('T',' ').slice(0, 16);
    return '<button type="button" class="switch'+(u.hot?' hot':'')+'" data-up="'+idx+'">'
      + '<span class="sw-top"><span>'+u.label+'</span><span class="sw-kind">'+(u.hot?'today':'soon')+'</span></span>'
      + '<span class="sw-pair">on '+(u.airs_on||'?')+' · '+(u.schedule||'')+' · '+when+'</span>'
      + '</button>';
  }}).join('');
  box.querySelectorAll('[data-up]').forEach(btn => {{
    btn.addEventListener('click', () => {{
      const u = (state.upcoming_programs || [])[Number(btn.getAttribute('data-up'))];
      if (!u) return;
      // Prefill times on the upcoming window, then ask which player.
      const fake = {{
        start_et: u.start_et,
        end_et: u.end_et,
        stream_a: u.stream_a || u.id,
        stream_b: u.stream_b || 'FOX_NEWS_US',
        booking_id: null,
        day_short: '',
        time_range: u.schedule || '',
      }};
      openAssignPlayer(u.stream_a || u.id);
      if (assignCtx) assignCtx.row = fake;
      document.getElementById('assignContext').textContent =
        'Upcoming: ' + u.label + ' · ' + (u.schedule || '');
    }});
  }});
}}
async function applySwitch(id) {{
  const s = (state.priority_switches || []).find(x => x.id === id);
  if (!s) return;
  const chans = [s.stream_a, s.stream_b].filter(Boolean);
  let instances = (state.assignments || []).map(a => a.instance_id).filter(Boolean);
  if (instances.length < 2) {{
    const fromPlayers = (state.players || []).map(p => p.instance_id).filter(Boolean);
    for (const iid of fromPlayers) {{
      if (!instances.includes(iid)) instances.push(iid);
    }}
  }}
  instances = instances.slice(0, Math.max(chans.length, 2));
  const sels = Array.from(document.querySelectorAll('select.ch'));
  sels.forEach((sel, i) => {{
    const want = chans[i];
    if (!want) return;
    if (![...sel.options].some(o => o.value === want)) {{
      const opt = document.createElement('option');
      opt.value = want; opt.textContent = label(want);
      sel.appendChild(opt);
    }}
    sel.value = want;
  }});
  document.getElementById('chunk').value = String(s.chunk_minutes || 60);
  if (s.hold_hours != null) {{
    const h = String(s.hold_hours);
    const hold = document.getElementById('holdHours');
    if (![...hold.options].some(o => o.value === h)) {{
      const opt = document.createElement('option');
      opt.value = h; opt.textContent = h + ' hours';
      hold.appendChild(opt);
    }}
    hold.value = h;
  }}
  document.getElementById('why').value = s.why || s.label;
  dirty = true;
  const assignments = instances.map((iid, i) => ({{
    instance_id: iid,
    channel_id: chans[i] || chans[0],
  }})).filter(a => a.instance_id && a.channel_id);
  if (!assignments.length) {{ toast('No players to assign'); return; }}
  try {{
    await post({{
      action: 'save',
      set_by: 'schedule_ui',
      why: s.why || ('emergency switch → ' + s.label),
      chunk_minutes: Number(s.chunk_minutes || 60),
      hold_hours: s.hold_hours != null ? s.hold_hours : null,
      assignments,
    }});
    toast('Locked: ' + s.label);
  }} catch (err) {{ toast(String(err.message || err)); }}
}}
function render(b, {{preserveEdits}} = {{}}) {{
  state = b;
  const et = String(b.local_et || '').replace('T', ' ').slice(0, 16);
  const nBook = (b.bookings || []).length;
  document.getElementById('sub').textContent =
    (b.override_active ? 'Manual now · ' : (b.booking_active ? 'Booked now · ' : 'Auto · '))
    + 'ET ' + et + ' · ' + ((b.timeline||[]).length) + ' blocks'
    + (nBook ? (' · ' + nBook + ' booked') : '');
  const st = document.getElementById('status');
  const rw = b.record_window || {{}};
  if (b.override_active) {{
    st.className = 'banner ov';
    st.innerHTML = '<strong>Manual hold on now</strong> — booked forward blocks still show in the grid.';
  }} else if (b.booking_active) {{
    st.className = 'banner bk';
    const ab = b.active_booking || {{}};
    st.innerHTML = '<strong>Inside a booked window</strong> — '
      + label(ab.stream_a) + ' / ' + label(ab.stream_b)
      + (ab.why ? (' · ' + ab.why) : '');
  }} else {{
    st.className = 'banner';
    st.innerHTML = 'Forward plan · record=<strong>'+rw.do_record+'</strong>'
      + ' · tap a row to book over it.';
  }}
  renderGrid(b);
  renderSwitches(b);
  renderUpcoming(b);
  renderPriority(b);
  if (!preserveEdits) {{
    document.getElementById('chunk').value = String(b.chunk_minutes || 20);
  }}
  const box = document.getElementById('players');
  box.innerHTML = (b.assignments || []).map(a => {{
    const pl = (a.player_state && typeof a.player_state === 'object') ? a.player_state : {{}};
    const who = pl.local_calls || pl.local_network || '—';
    const name = a.player_label || a.instance_id;
    const pill = a.action === 'hold'
      ? '<span class="pill nowp">on target</span>'
      : '<span class="pill nextp">needs tune</span>';
    return '<div class="player-row">'
      + '<div class="slot-top"><strong>'+name+'</strong>'+pill+'</div>'
      + '<p class="meta">Now: '+who+' · '+(pl.ui_kind||'?')+'</p>'
      + '<label class="field">Channel<select class="ch" data-instance="'+a.instance_id+'">'
      + choicesHtml(a.channel_id) + '</select></label></div>';
  }}).join('') || '<p class="meta">No players.</p>';
  box.querySelectorAll('select.ch').forEach(sel => sel.addEventListener('change', () => {{ dirty = true; }}));
  dirty = false;
}}
function collectAssignments() {{
  return Array.from(document.querySelectorAll('select.ch')).map(sel => ({{
    instance_id: sel.dataset.instance,
    channel_id: sel.value,
  }}));
}}
async function post(body) {{
  const res = await fetch(api('/api/schedule'), {{
    method: 'POST',
    headers: {{ 'Content-Type': 'application/json' }},
    body: JSON.stringify(body),
    cache: 'no-store',
  }});
  const data = await res.json();
  if (!data.ok) throw new Error(data.error || 'save failed');
  render(data.board || state);
  return data;
}}
async function saveNow() {{
  try {{
    await post({{
      action: 'save',
      set_by: 'schedule_ui',
      why: document.getElementById('why').value.trim() || 'edited in schedule UI',
      chunk_minutes: Number(document.getElementById('chunk').value || 20),
      hold_hours: document.getElementById('holdHours').value || null,
      assignments: collectAssignments(),
    }});
    toast('Now locked');
  }} catch (err) {{ toast(String(err.message || err)); }}
}}
async function clearNow() {{
  if (!confirm('Clear manual now-hold and return to auto/booking?')) return;
  try {{
    await post({{ action: 'clear', set_by: 'schedule_ui' }});
    toast('Back to auto plan');
  }} catch (err) {{ toast(String(err.message || err)); }}
}}
async function saveBooking() {{
  const start = fromLocalInput(document.getElementById('bookStart').value);
  const end = fromLocalInput(document.getElementById('bookEnd').value);
  if (!start || !end) {{ toast('Need start and end'); return; }}
  try {{
    await post({{
      action: 'book',
      set_by: 'schedule_ui',
      id: document.getElementById('bookId').value || null,
      start_et: start,
      end_et: end,
      stream_a: document.getElementById('bookA').value,
      stream_b: document.getElementById('bookB').value,
      why: document.getElementById('bookWhy').value.trim() || 'booked in schedule UI',
    }});
    closeDrawer();
    toast('Block booked');
  }} catch (err) {{ toast(String(err.message || err)); }}
}}
async function deleteBooking() {{
  const id = document.getElementById('bookId').value;
  if (!id || !confirm('Delete this booked block?')) return;
  try {{
    await post({{ action: 'delete_booking', id, set_by: 'schedule_ui' }});
    closeDrawer();
    toast('Booking deleted');
  }} catch (err) {{ toast(String(err.message || err)); }}
}}
document.getElementById('bookDur').addEventListener('change', () => {{
  const mins = Number(document.getElementById('bookDur').value || 0);
  if (!mins) return;
  const startV = document.getElementById('bookStart').value;
  if (!startV) return;
  const start = new Date(startV);
  const end = new Date(start.getTime() + mins * 60000);
  document.getElementById('bookEnd').value = toLocalInput(end.toISOString());
}});
document.getElementById('linkDash').href = api('/dashboard');
document.getElementById('btnSaveNow').onclick = saveNow;
document.getElementById('btnClear').onclick = clearNow;
document.getElementById('btnBook').onclick = () => openDrawer(null);
document.getElementById('btnBookSaveBar').onclick = () => {{
  if (!document.getElementById('drawer').classList.contains('open')) openDrawer(null);
  else saveBooking();
}};
document.getElementById('btnBookSave').onclick = saveBooking;
document.getElementById('btnDelete').onclick = deleteBooking;
document.getElementById('btnClose').onclick = closeDrawer;
document.getElementById('drawer').addEventListener('click', (e) => {{
  if (e.target.id === 'drawer') closeDrawer();
}});
document.getElementById('btnRefresh').onclick = () => refresh(true);
function renderSearchHits(q) {{
  const box = document.getElementById('searchHits');
  const query = String(q || '').trim().toLowerCase();
  if (!query) {{ box.classList.remove('open'); box.innerHTML = ''; return; }}
  const hits = catalogFlat().filter(c => String(c.keywords || '').includes(query)).slice(0, 24);
  if (!hits.length) {{
    box.classList.add('open');
    box.innerHTML = '<button type="button" disabled><span class="h-top">No matches</span></button>';
    return;
  }}
  box.classList.add('open');
  box.innerHTML = hits.map(c => {{
    const tag = c.kind === 'program'
      ? '<span class="chip program">program · '+(c.airs_on||'?')+'</span>'
      : '<span class="chip channel">channel</span>';
    const sub = c.kind === 'program'
      ? ('on '+(c.airs_on||'?')+' · '+(c.schedule||c.airs_group||c.group||''))
      : (c.group || '');
    return '<button type="button" data-pick="'+c.id+'">'
      + '<span class="h-top"><span>'+c.label+'</span>'+tag+'</span>'
      + '<span class="h-sub">'+sub+'</span></button>';
  }}).join('');
  box.querySelectorAll('[data-pick]').forEach(btn => {{
    btn.addEventListener('click', () => {{
      const id = btn.getAttribute('data-pick');
      document.getElementById('globalSearch').value = '';
      box.classList.remove('open');
      openAssignPlayer(id);
    }});
  }});
}}
document.getElementById('globalSearch').addEventListener('input', (e) => renderSearchHits(e.target.value));
document.getElementById('fillSearch').addEventListener('input', (e) => renderFillHits(e.target.value));
document.getElementById('btnFillClose').onclick = closeFill;
document.getElementById('fillDrawer').addEventListener('click', (e) => {{
  if (e.target.id === 'fillDrawer') closeFill();
}});
document.getElementById('assignP0').onclick = () => assignToSide('a');
document.getElementById('assignP1').onclick = () => assignToSide('b');
document.getElementById('btnAssignClose').onclick = closeAssign;
document.getElementById('assignDrawer').addEventListener('click', (e) => {{
  if (e.target.id === 'assignDrawer') closeAssign();
}});
document.getElementById('bookFilter').addEventListener('input', (e) => {{
  const a = document.getElementById('bookA').value;
  const b = document.getElementById('bookB').value;
  fillBookSelects(a, b, e.target.value);
}});
document.getElementById('bookA').addEventListener('change', () => {{
  fillBookSelects(document.getElementById('bookA').value, document.getElementById('bookB').value, document.getElementById('bookFilter').value);
}});
render(BOOT);
async function refresh(force) {{
  if (dirty && !force) return;
  try {{
    const res = await fetch(api('/api/schedule'), {{ cache: 'no-store' }});
    const b = await res.json();
    if (b && b.ok !== false) render(b);
  }} catch (_) {{}}
}}
setInterval(() => refresh(false), 30000);
</script>
</body>
</html>
"""

def publish_recording_schedule(
    root: Path | None = None,
    *,
    rebuild_plan: bool = True,
) -> dict[str, Any]:
    """Write JSON + MD + HTML; return the board."""
    root = ensure_data_layout(root)
    # Heal overlapping bookings on disk so impossible dual rows cannot persist.
    raw = _load_json(bookings_path(root))
    if isinstance(raw, dict):
        raw_items = list(raw.get("bookings") or [])
    elif isinstance(raw, list):
        raw_items = list(raw)
    else:
        raw_items = []
    healed = normalize_bookings(raw_items)

    def _sig(rows: list[dict[str, Any]]) -> list[tuple[Any, ...]]:
        return [
            (
                str(r.get("start_et") or ""),
                str(r.get("end_et") or ""),
                r.get("stream_a"),
                r.get("stream_b"),
                bool(r.get("skip")),
            )
            for r in rows
        ]

    if _sig(healed) != _sig(raw_items):
        save_bookings(healed, root=root)
    board = build_recording_schedule(root, rebuild_plan=rebuild_plan)
    schedule_path(root).write_text(json.dumps(board, indent=2, default=str), encoding="utf-8")
    board_md_path(root).write_text(_render_md(board), encoding="utf-8")
    board_html_path(root).write_text(_render_html(board), encoding="utf-8")
    return board


def effective_assignments(
    root: Path | None = None,
    *,
    rebuild_plan: bool = False,
) -> list[dict[str, Any]]:
    """Assignments desk/schedule_from_plan should materialize."""
    board = build_recording_schedule(root, rebuild_plan=rebuild_plan)
    return list(board.get("assignments") or [])


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="Recording schedule board + agent overwrite")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("publish", help="Rebuild and write schedule board")
    sub.add_parser("show", help="Print schedule JSON to stdout")
    sub.add_parser("clear-override", help="Remove agent overwrite")
    so = sub.add_parser("set-override", help="Agent overwrite desk must honor")
    so.add_argument(
        "--assign",
        action="append",
        default=[],
        help="instance:channel[:nav] e.g. Nougat32:FOX_NEWS_US:FOX_NEWS_US",
    )
    so.add_argument("--why", required=True)
    so.add_argument("--set-by", default="cursor_agent")
    so.add_argument("--chunk-minutes", type=int, default=20)
    so.add_argument("--hold-hours", type=float, default=None, help="Auto-expire override")
    args = p.parse_args(argv)

    if args.cmd == "publish":
        board = publish_recording_schedule(rebuild_plan=True)
        print(json.dumps({
            "ok": True,
            "source": board.get("source"),
            "assignments": [
                {"instance_id": a.get("instance_id"), "channel_id": a.get("channel_id"), "action": a.get("action")}
                for a in (board.get("assignments") or [])
            ],
            "urls": board.get("urls"),
            "paths": board.get("paths"),
        }, indent=2))
        return 0
    if args.cmd == "show":
        print(json.dumps(build_recording_schedule(rebuild_plan=False), indent=2, default=str))
        return 0
    if args.cmd == "clear-override":
        print(json.dumps(clear_override(), indent=2))
        publish_recording_schedule(rebuild_plan=True)
        return 0
    if args.cmd == "set-override":
        if not args.assign:
            print(json.dumps({"ok": False, "error": "need --assign"}, indent=2))
            return 2
        holds = None
        if args.hold_hours is not None:
            holds = (_now_utc() + timedelta(hours=float(args.hold_hours))).isoformat()
        rows = [_parse_assign_token(t) for t in args.assign]
        for r in rows:
            r["chunk_minutes"] = args.chunk_minutes
        out = set_override(
            rows,
            why=args.why,
            set_by=args.set_by,
            hold_until_utc=holds,
            chunk_minutes=args.chunk_minutes,
        )
        print(json.dumps({
            "ok": out.get("ok"),
            "path": out.get("path"),
            "override": out.get("override"),
            "urls": (out.get("published") or {}).get("urls"),
        }, indent=2, default=str))
        return 0 if out.get("ok") else 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
