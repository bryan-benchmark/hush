"""Full Streamers guide catalog — channel number + title + group database.

Deep-dives the All-channels rail group-by-group, records every numbered row,
and keeps a SQLite DB + daily JSONL so scheduling can target exact channels
(Atlanta WSB = number N, not a Pluto near-miss).

Daily: ``python -m tools.windows_lab guide-catalog daily``
Lookup: ``python -m tools.windows_lab guide-catalog lookup --calls WSB``
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import ensure_data_layout
from .instances import adb, connect_adb, get_instance, launch_bluestacks, wait_for_adb
from .streamers_open import DEFAULT_INSTANCE, _dump_ui, _tap_text, _texts

# Booth / national first — full playlist (~20k) continues after these.
PRIORITY_GROUPS = (
    "US ABC SECTION",
    "US CBS SECTION",
    "US NBC SECTION",
    "US FOX SECTION",
    "US SPORTS",
    "US NEWS",
    "US ENTERTAINMENT",
    "NFL A",
    "NFL TEAMS/CHANNELS",
    "NFL Y",
    "NFL T",
    "ROKU TV",
    "US CW/MY/PBS SECTION",
    "ESPN+ SECTION",
    "ESPN UNLIMITED",
    "NBA SECTION",
    "NHL SECTION",
    "NCAA CHANNELS",
)

# Still cataloged, but never preferred for booth/national ads.
DEMOTE_GROUPS = frozenset(
    {
        "PLUTO U.S.A.",
        "TUBI TV",
        "MAX SPORTS",
        "MAX SPORTS UK",
        "AMAZON SPORTS",
        "TSN+ SPORTS",
        "SPORTSNET+",
        "FLO SPORTS",
        "FLO HOCKEY",
        "FLO COLLEGE",
        "ESPN+ SECTION",
        "ESPN UNLIMITED",
    }
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def catalog_dir(root: Path | None = None) -> Path:
    d = ensure_data_layout(root) / "indexes" / "guide_catalog"
    d.mkdir(parents=True, exist_ok=True)
    return d


def db_path(root: Path | None = None) -> Path:
    return ensure_data_layout(root) / "indexes" / "guide_catalog.sqlite"


def groups_path(root: Path | None = None) -> Path:
    return ensure_data_layout(root) / "indexes" / "streamers_tv_groups.json"


def board_path(root: Path | None = None) -> Path:
    return ensure_data_layout(root) / "indexes" / "GUIDE_CATALOG.md"


def scan_state_path(root: Path | None = None) -> Path:
    return catalog_dir(root) / "scan_state.json"


def connect_db(root: Path | None = None) -> sqlite3.Connection:
    path = db_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path))
    con.row_factory = sqlite3.Row
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS channels (
            number INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            group_name TEXT,
            kind TEXT,
            network TEXT,
            calls TEXT,
            state TEXT,
            city TEXT,
            market TEXT,
            demoted INTEGER DEFAULT 0,
            first_seen_utc TEXT,
            last_seen_utc TEXT,
            last_scan_id TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_channels_group ON channels(group_name);
        CREATE INDEX IF NOT EXISTS idx_channels_calls ON channels(calls);
        CREATE INDEX IF NOT EXISTS idx_channels_network ON channels(network);
        CREATE INDEX IF NOT EXISTS idx_channels_title ON channels(title);

        CREATE TABLE IF NOT EXISTS scans (
            scan_id TEXT PRIMARY KEY,
            started_utc TEXT,
            finished_utc TEXT,
            instance_id TEXT,
            mode TEXT,
            channel_count INTEGER,
            groups_done TEXT,
            notes TEXT
        );

        CREATE TABLE IF NOT EXISTS scan_rows (
            scan_id TEXT,
            number INTEGER,
            title TEXT,
            group_name TEXT,
            kind TEXT,
            PRIMARY KEY (scan_id, number)
        );
        """
    )
    return con


def load_groups(root: Path | None = None) -> list[str]:
    path = groups_path(root)
    if not path.is_file():
        return list(PRIORITY_GROUPS)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        groups = [str(g) for g in (data.get("groups") or []) if str(g).strip()]
        return groups or list(PRIORITY_GROUPS)
    except Exception:
        return list(PRIORITY_GROUPS)


def _bounds(raw: str) -> tuple[int, int, int, int] | None:
    m = re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", raw or "")
    if not m:
        return None
    return tuple(map(int, m.groups()))  # type: ignore[return-value]


def parse_guide_grid(ui: ET.Element) -> tuple[str, list[dict[str, Any]]]:
    """Parse channel number gutter + title column from a guide dump."""
    texts: list[tuple[str, tuple[int, int, int, int]]] = []
    for node in ui.iter("node"):
        text = (node.attrib.get("text") or "").strip()
        box = _bounds(node.attrib.get("bounds") or "")
        if not text or not box or text == "No information":
            continue
        texts.append((text, box))

    section = ""
    for text, box in texts:
        x1, y1, x2, y2 = box
        if y1 < 140 and x1 > 900 and "AM" not in text and "PM" not in text:
            # Prefer SECTION / pack headers over program blurbs.
            if (
                text.endswith("SECTION")
                or text.endswith("CHANNELS")
                or text.endswith("SPORTS")
                or text.startswith("US ")
                or "PLUTO" in text.upper()
                or "TUBI" in text.upper()
                or "NFL" in text.upper()
                or "ROKU" in text.upper()
            ):
                section = text
                break
            if not section and len(text) < 40:
                section = text

    numbers = [
        (text, box)
        for text, box in texts
        if text.isdigit() and box[0] < 120 and box[1] > 350
    ]
    rows: list[dict[str, Any]] = []
    for number, box in numbers:
        mid = (box[1] + box[3]) / 2
        name = ""
        for text, other in texts:
            if text == number:
                continue
            if other[0] < 140 or other[0] > 520:
                continue
            if other[1] - 8 <= mid <= other[3] + 8:
                name = text
                break
        if not name:
            continue
        kind = "section" if name.startswith("-------") or set(name) <= set("- ") else "channel"
        rows.append(
            {
                "number": int(number),
                "title": name,
                "group_name": section,
                "kind": kind,
            }
        )
    return section, rows


def enrich_row(row: dict[str, Any]) -> dict[str, Any]:
    """Attach network/calls/city when title looks like a US local."""
    from .us_locals import parse_local_title

    out = dict(row)
    parsed = parse_local_title(str(out.get("title") or ""))
    if parsed:
        out["network"] = parsed.get("network")
        out["calls"] = parsed.get("calls")
        out["state"] = parsed.get("state") or None
        out["city"] = parsed.get("city") or None
        out["market"] = parsed.get("city") or None
    group = str(out.get("group_name") or "")
    out["demoted"] = 1 if group in DEMOTE_GROUPS else 0
    return out


def upsert_channels(
    rows: list[dict[str, Any]],
    *,
    scan_id: str,
    root: Path | None = None,
    jsonl: Path | None = None,
) -> int:
    """Upsert enriched rows into SQLite (+ optional daily JSONL). Returns new/changed count."""
    if not rows:
        return 0
    con = connect_db(root)
    now = _now_iso()
    changed = 0
    try:
        for raw in rows:
            if raw.get("kind") == "section":
                continue
            row = enrich_row(raw)
            num = int(row["number"])
            title = str(row["title"])
            group = str(row.get("group_name") or "") or None
            cur = con.execute("SELECT title, group_name FROM channels WHERE number=?", (num,))
            prev = cur.fetchone()
            if prev is None:
                con.execute(
                    """
                    INSERT INTO channels(
                        number, title, group_name, kind, network, calls, state, city, market,
                        demoted, first_seen_utc, last_seen_utc, last_scan_id
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        num,
                        title,
                        group,
                        row.get("kind") or "channel",
                        row.get("network"),
                        row.get("calls"),
                        row.get("state"),
                        row.get("city"),
                        row.get("market"),
                        int(row.get("demoted") or 0),
                        now,
                        now,
                        scan_id,
                    ),
                )
                changed += 1
            else:
                con.execute(
                    """
                    UPDATE channels SET
                        title=?, group_name=COALESCE(?, group_name), kind=?,
                        network=COALESCE(?, network), calls=COALESCE(?, calls),
                        state=COALESCE(?, state), city=COALESCE(?, city),
                        market=COALESCE(?, market), demoted=?,
                        last_seen_utc=?, last_scan_id=?
                    WHERE number=?
                    """,
                    (
                        title,
                        group,
                        row.get("kind") or "channel",
                        row.get("network"),
                        row.get("calls"),
                        row.get("state"),
                        row.get("city"),
                        row.get("market"),
                        int(row.get("demoted") or 0),
                        now,
                        scan_id,
                        num,
                    ),
                )
                if prev["title"] != title or (prev["group_name"] or "") != (group or ""):
                    changed += 1
            con.execute(
                """
                INSERT OR REPLACE INTO scan_rows(scan_id, number, title, group_name, kind)
                VALUES (?,?,?,?,?)
                """,
                (scan_id, num, title, group, row.get("kind") or "channel"),
            )
            if jsonl is not None:
                with jsonl.open("a", encoding="utf-8") as fh:
                    fh.write(
                        json.dumps(
                            {
                                "scan_utc": now,
                                "scan_id": scan_id,
                                "number": num,
                                "title": title,
                                "group": group,
                                "kind": row.get("kind"),
                                "network": row.get("network"),
                                "calls": row.get("calls"),
                                "demoted": bool(row.get("demoted")),
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
        con.commit()
    finally:
        con.close()
    return changed


def import_legacy(root: Path | None = None) -> dict[str, Any]:
    """Seed DB from Nov-10 partial NCAA JSON if present."""
    root = ensure_data_layout(root)
    legacy = root / "indexes" / "streamers_guide_channels.json"
    if not legacy.is_file():
        return {"ok": False, "error": "no_legacy"}
    data = json.loads(legacy.read_text(encoding="utf-8"))
    scan_id = f"legacy_{str(data.get('collected_utc') or 'import')[:10]}"
    rows = [
        {
            "number": int(c["number"]),
            "title": c.get("name") or c.get("title"),
            "group_name": c.get("section_on_screen") or c.get("group"),
            "kind": c.get("kind") or "channel",
        }
        for c in (data.get("channels") or [])
        if c.get("number") is not None
    ]
    n = upsert_channels(rows, scan_id=scan_id, root=root)
    con = connect_db(root)
    try:
        total = con.execute("SELECT COUNT(*) FROM channels").fetchone()[0]
        con.execute(
            """
            INSERT OR REPLACE INTO scans(scan_id, started_utc, finished_utc, instance_id, mode, channel_count, notes)
            VALUES (?,?,?,?,?,?,?)
            """,
            (scan_id, data.get("collected_utc"), _now_iso(), None, "legacy_import", total, str(legacy)),
        )
        con.commit()
    finally:
        con.close()
    return {"ok": True, "imported": len(rows), "changed": n, "total": total, "scan_id": scan_id}


def _ensure_all_channels(instance: dict[str, Any], probe: Path) -> ET.Element:
    ui = _dump_ui(instance, probe / "catalog_home.xml")
    texts = _texts(ui)
    if "All channels" in texts:
        _tap_text(instance, ui, "All channels")
        time.sleep(1.0)
        ui = _dump_ui(instance, probe / "catalog_all.xml")
    elif "Favorites" in texts:
        # Favorites hides most groups — try All channels after peek.
        adb(instance, ["shell", "input", "tap", "40", "200"])
        time.sleep(0.6)
        ui = _dump_ui(instance, probe / "catalog_peek.xml")
        if "All channels" in _texts(ui):
            _tap_text(instance, ui, "All channels")
            time.sleep(1.0)
            ui = _dump_ui(instance, probe / "catalog_all.xml")
    return ui


def _open_group(instance: dict[str, Any], group: str, probe: Path) -> dict[str, Any]:
    ui = _ensure_all_channels(instance, probe)
    texts = _texts(ui)
    if group in texts:
        _tap_text(instance, ui, group)
        time.sleep(1.1)
        return {"ok": True, "via": "visible"}
    # Scroll left rail
    for i in range(28):
        adb(instance, ["shell", "input", "swipe", "180", "780", "180", "250", "450"])
        time.sleep(0.45)
        ui = _dump_ui(instance, probe / f"catalog_rail_{i}.xml")
        texts = _texts(ui)
        if "All channels" in texts and i == 0:
            _tap_text(instance, ui, "All channels")
            time.sleep(0.8)
            ui = _dump_ui(instance, probe / "catalog_all2.xml")
            texts = _texts(ui)
        if group in texts:
            _tap_text(instance, ui, group)
            time.sleep(1.1)
            return {"ok": True, "via": f"rail_scroll_{i}"}
    # Also try dashed in-grid header
    for i in range(20):
        ui = _dump_ui(instance, probe / f"catalog_grid_{i}.xml")
        texts = _texts(ui)
        hit = next((t for t in texts if group.lower() in t.lower() and t.startswith("-------")), None)
        if hit or group in texts:
            _tap_text(instance, ui, hit or group)
            time.sleep(1.0)
            return {"ok": True, "via": f"grid_header_{i}"}
        adb(instance, ["shell", "input", "swipe", "900", "820", "900", "280", "480"])
        time.sleep(0.4)
    return {"ok": False, "error": f"group_not_found:{group}", "seen": texts[:20]}


def scan_linear(
    *,
    instance_id: str = DEFAULT_INSTANCE,
    root: Path | None = None,
    scan_id: str | None = None,
    max_swipes: int = 400,
    label: str = "ALL_CHANNELS",
) -> dict[str, Any]:
    """Scroll the All-channels number gutter end-to-end (most reliable full census).

    Does not depend on left-rail SECTION taps. Records chrome group labels when visible.
    """
    return scan_group(
        label,
        instance_id=instance_id,
        root=root,
        scan_id=scan_id,
        max_swipes=max_swipes,
        linear=True,
    )


def scan_group(
    group: str,
    *,
    instance_id: str = DEFAULT_INSTANCE,
    root: Path | None = None,
    scan_id: str | None = None,
    max_swipes: int = 120,
    linear: bool = False,
) -> dict[str, Any]:
    """Walk one group grid (or linear All-channels) and upsert every numbered channel."""
    root = ensure_data_layout(root)
    scan_id = scan_id or f"scan_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}"
    instance = get_instance(instance_id, root)
    launch_bluestacks(instance, launch_app=True)
    connect_adb(instance)
    if not wait_for_adb(instance, seconds=60):
        return {"ok": False, "error": "ADB not ready", "group": group}

    try:
        from .streamers_recover import ensure_ready_for_open

        ensure_ready_for_open(instance_id, root=root)
    except Exception:
        pass

    probe = root / "work" / "guide_catalog" / scan_id
    probe.mkdir(parents=True, exist_ok=True)
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    jsonl = catalog_dir(root) / f"{day}.jsonl"

    if linear:
        _ensure_all_channels(instance, probe)
        # Jump toward low channel numbers (swipe down repeatedly).
        for _ in range(8):
            adb(instance, ["shell", "input", "swipe", "400", "400", "400", "820", "320"])
            time.sleep(0.35)
        opened = {"ok": True, "via": "linear_all_channels"}
    else:
        opened = _open_group(instance, group, probe)
        if not opened.get("ok"):
            # Fall back to linear walk — still grows the number DB.
            _ensure_all_channels(instance, probe)
            opened = {"ok": True, "via": "linear_fallback", "section_error": opened.get("error")}
            linear = True

    by_number: dict[int, dict[str, Any]] = {}
    still = 0
    last_top = None
    passes = 0
    dump_fails = 0
    for i in range(max_swipes):
        ui = None
        for attempt in range(3):
            try:
                ui = _dump_ui(instance, probe / f"g_{i:03d}.xml")
                dump_fails = 0
                break
            except Exception:
                time.sleep(0.8 + attempt)
                try:
                    from .ui_dump import heal_adb_for_dump

                    heal_adb_for_dump(instance, root=root, allow_recover_streamers=False)
                except Exception:
                    try:
                        connect_adb(instance)
                    except Exception:
                        pass
        if ui is None:
            dump_fails += 1
            if dump_fails >= 4:
                return {
                    "ok": False,
                    "group": group,
                    "scan_id": scan_id,
                    "error": "uiautomator_dump_failed",
                    "channels": len(by_number),
                    "passes": passes,
                }
            adb(instance, ["shell", "input", "swipe", "400", "820", "400", "500", "280"])
            time.sleep(0.5)
            continue
        section, rows = parse_guide_grid(ui)
        # Only fill blank chrome; never overwrite a different section label.
        for r in rows:
            if not r.get("group_name"):
                r["group_name"] = group
        added = 0
        for r in rows:
            n = int(r["number"])
            if n not in by_number:
                by_number[n] = r
                added += 1
            else:
                by_number[n] = r
        if rows:
            upsert_channels(rows, scan_id=scan_id, root=root, jsonl=jsonl)
        top = rows[0]["number"] if rows else None
        passes += 1
        if added == 0 and top == last_top:
            still += 1
            if still >= 3:
                break
        else:
            still = 0
        last_top = top
        adb(instance, ["shell", "input", "swipe", "400", "820", "400", "500", "280"])
        time.sleep(0.4)

    return {
        "ok": True,
        "group": group,
        "scan_id": scan_id,
        "passes": passes,
        "channels": len(by_number),
        "open": opened,
        "sample": list(by_number.values())[:5],
    }


def _ordered_groups(*, priority_only: bool, root: Path | None = None) -> list[str]:
    all_groups = load_groups(root)
    if priority_only:
        return list(PRIORITY_GROUPS)
    # Priority first, then remaining (demoted last).
    rest = [g for g in all_groups if g not in PRIORITY_GROUPS]
    demoted = [g for g in rest if g in DEMOTE_GROUPS]
    normal = [g for g in rest if g not in DEMOTE_GROUPS]
    seen: set[str] = set()
    out: list[str] = []
    for g in list(PRIORITY_GROUPS) + normal + demoted:
        if g not in seen:
            seen.add(g)
            out.append(g)
    return out


def scan(
    *,
    instance_id: str = DEFAULT_INSTANCE,
    root: Path | None = None,
    priority_only: bool = False,
    groups: list[str] | None = None,
    resume: bool = True,
    max_groups: int | None = None,
) -> dict[str, Any]:
    """Scan many groups into the channel DB. Resumable via scan_state.json."""
    root = ensure_data_layout(root)
    import_legacy(root)
    scan_id = f"scan_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}"
    target = groups or _ordered_groups(priority_only=priority_only, root=root)
    state = {"scan_id": scan_id, "done": [], "failed": [], "started_utc": _now_iso()}
    if resume and scan_state_path(root).is_file():
        try:
            prev = json.loads(scan_state_path(root).read_text(encoding="utf-8"))
            done = set(prev.get("done") or [])
            target = [g for g in target if g not in done]
            state["done"] = list(done)
            state["prior_scan_id"] = prev.get("scan_id")
        except Exception:
            pass
    if max_groups is not None:
        target = target[: int(max_groups)]

    con = connect_db(root)
    try:
        con.execute(
            """
            INSERT OR REPLACE INTO scans(scan_id, started_utc, instance_id, mode, channel_count, groups_done, notes)
            VALUES (?,?,?,?,?,?,?)
            """,
            (
                scan_id,
                state["started_utc"],
                instance_id,
                "priority" if priority_only else "full",
                0,
                "[]",
                f"queued={len(target)}",
            ),
        )
        con.commit()
    finally:
        con.close()

    results: list[dict[str, Any]] = []
    for g in target:
        try:
            from .farm_ops import emit

            emit(
                "guide_catalog_group",
                detail=g,
                instance_id=instance_id,
                ok=None,
                extra={"scan_id": scan_id},
                root=root,
            )
        except Exception:
            pass
        try:
            out = scan_group(g, instance_id=instance_id, root=root, scan_id=scan_id)
        except Exception as exc:  # noqa: BLE001
            out = {"ok": False, "group": g, "error": str(exc)}
        results.append(out)
        if out.get("ok"):
            state["done"].append(g)
        else:
            state["failed"].append({"group": g, "error": out.get("error")})
        state["updated_utc"] = _now_iso()
        scan_state_path(root).write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")

    con = connect_db(root)
    try:
        total = con.execute("SELECT COUNT(*) FROM channels").fetchone()[0]
        con.execute(
            """
            UPDATE scans SET finished_utc=?, channel_count=?, groups_done=?, notes=?
            WHERE scan_id=?
            """,
            (
                _now_iso(),
                total,
                json.dumps(state["done"]),
                json.dumps({"failed": state["failed"], "results": len(results)}),
                scan_id,
            ),
        )
        con.commit()
    finally:
        con.close()

    board = write_board(root)
    try:
        from .farm_ops import emit

        emit(
            "guide_catalog_scan",
            detail=f"groups={len(state['done'])} total_channels={board.get('channel_count')}",
            instance_id=instance_id,
            ok=True,
            extra={"scan_id": scan_id, "failed": state["failed"][:10]},
            root=root,
        )
    except Exception:
        pass
    return {
        "ok": True,
        "scan_id": scan_id,
        "groups_done": state["done"],
        "failed": state["failed"],
        "channel_count": board.get("channel_count"),
        "board": board.get("board"),
        "db": str(db_path(root)),
    }


def lookup(
    *,
    number: int | None = None,
    calls: str | None = None,
    network: str | None = None,
    market: str | None = None,
    group: str | None = None,
    q: str | None = None,
    limit: int = 25,
    root: Path | None = None,
    prefer_home: bool = True,
) -> list[dict[str, Any]]:
    """Query the channel DB for scheduling / open hints."""
    con = connect_db(root)
    try:
        clauses: list[str] = []
        args: list[Any] = []
        if number is not None:
            clauses.append("number=?")
            args.append(int(number))
        if calls:
            clauses.append("UPPER(calls)=?")
            args.append(calls.upper().strip())
        if network:
            clauses.append("UPPER(network)=?")
            args.append(network.upper().strip())
        if market:
            clauses.append("(UPPER(COALESCE(city,'')) LIKE ? OR UPPER(COALESCE(market,'')) LIKE ? OR UPPER(title) LIKE ?)")
            m = f"%{market.upper().strip()}%"
            args.extend([m, m, m])
        if group:
            clauses.append("group_name=?")
            args.append(group)
        if q:
            clauses.append("(UPPER(title) LIKE ? OR UPPER(COALESCE(calls,'')) LIKE ?)")
            qq = f"%{q.upper().strip()}%"
            args.extend([qq, qq])
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        order = " demoted ASC, number ASC"
        if prefer_home and (calls or network):
            order = " demoted ASC, CASE WHEN UPPER(COALESCE(city,'')) LIKE '%ATLANTA%' THEN 0 WHEN UPPER(COALESCE(city,'')) LIKE '%BIRMINGHAM%' THEN 1 ELSE 2 END, number ASC"
        sql = f"SELECT * FROM channels{where} ORDER BY{order} LIMIT ?"
        args.append(int(limit))
        rows = con.execute(sql, args).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def best_local(network: str, *, market: str = "Atlanta", root: Path | None = None) -> dict[str, Any] | None:
    """Exact channel number for a market affiliate from the DB."""
    rows = lookup(network=network, market=market, limit=5, root=root, prefer_home=True)
    if rows:
        return rows[0]
    # Fallback to calls from HOME_FAILOVER without market filter.
    from .us_locals import HOME_FAILOVER

    net = network.upper()
    if net in HOME_FAILOVER:
        calls = HOME_FAILOVER[net]["home" if market.lower() == "atlanta" else "failover"]["calls"]
        rows = lookup(calls=calls, network=net, limit=3, root=root)
        return rows[0] if rows else None
    return None


def write_board(root: Path | None = None) -> dict[str, Any]:
    root = ensure_data_layout(root)
    con = connect_db(root)
    try:
        total = con.execute("SELECT COUNT(*) FROM channels").fetchone()[0]
        by_group = con.execute(
            """
            SELECT group_name, COUNT(*) AS n FROM channels
            GROUP BY group_name ORDER BY n DESC LIMIT 40
            """
        ).fetchall()
        locals_n = con.execute(
            "SELECT COUNT(*) FROM channels WHERE network IS NOT NULL AND calls IS NOT NULL"
        ).fetchone()[0]
        demoted_n = con.execute("SELECT COUNT(*) FROM channels WHERE demoted=1").fetchone()[0]
        samples = con.execute(
            """
            SELECT number, title, group_name, network, calls FROM channels
            WHERE network IS NOT NULL
            ORDER BY CASE WHEN UPPER(COALESCE(city,'')) LIKE '%ATLANTA%' THEN 0 ELSE 1 END, number
            LIMIT 12
            """
        ).fetchall()
        last_scan = con.execute(
            "SELECT scan_id, finished_utc, channel_count, mode FROM scans ORDER BY started_utc DESC LIMIT 1"
        ).fetchone()
    finally:
        con.close()

    state = {}
    if scan_state_path(root).is_file():
        try:
            state = json.loads(scan_state_path(root).read_text(encoding="utf-8"))
        except Exception:
            state = {}

    lines = [
        "# Guide catalog",
        "",
        f"Checked `{_now_iso()}`",
        "",
        f"- **Channels in DB:** {total}",
        f"- **US locals parsed (network+calls):** {locals_n}",
        f"- **Demoted (Pluto/Tubi/Max packs):** {demoted_n}",
        f"- **DB:** `{db_path(root)}`",
        f"- **Groups file:** `{groups_path(root)}` ({len(load_groups(root))} names)",
        "",
    ]
    if last_scan:
        lines.append(
            f"- **Last scan:** `{last_scan['scan_id']}` mode={last_scan['mode']} "
            f"finished={last_scan['finished_utc']} count={last_scan['channel_count']}"
        )
        lines.append("")
    if state.get("done"):
        lines.append(f"- **Groups done (resume):** {len(state['done'])} — " + ", ".join(state["done"][:12]) + ("…" if len(state["done"]) > 12 else ""))
        lines.append("")
    lines.extend(
        [
            "## Sample locals (for schedule)",
            "",
            "| # | Title | Group | Net | Calls |",
            "|---:|---|---|---|---|",
        ]
    )
    for r in samples:
        lines.append(
            f"| {r['number']} | {r['title']} | {r['group_name'] or '—'} | "
            f"{r['network'] or '—'} | {r['calls'] or '—'} |"
        )
    lines.extend(
        [
            "",
            "## Top groups by count",
            "",
            "| Group | Channels |",
            "|---|---:|",
        ]
    )
    for r in by_group:
        lines.append(f"| {r['group_name'] or '(none)'} | {r['n']} |")
    lines.extend(
        [
            "",
            "## Commands",
            "",
            "```powershell",
            "python -m tools.windows_lab guide-catalog board",
            "python -m tools.windows_lab guide-catalog lookup --calls WSB",
            "python -m tools.windows_lab guide-catalog lookup --network ABC --market Atlanta",
            "python -m tools.windows_lab guide-catalog best-local --network ABC",
            "python -m tools.windows_lab guide-catalog scan --linear --instance Nougat32_1",
            "python -m tools.windows_lab guide-catalog daily --instance Nougat32_1",
            "```",
            "",
            "Daily desk tick (05:05 / 06:05) runs `guide-catalog daily` when not yet scanned today.",
            "",
        ]
    )
    path = board_path(root)
    path.write_text("\n".join(lines), encoding="utf-8")
    payload = {
        "checked_utc": _now_iso(),
        "channel_count": total,
        "locals_count": locals_n,
        "demoted_count": demoted_n,
        "board": str(path),
        "db": str(db_path(root)),
        "groups_done": state.get("done") or [],
    }
    (catalog_dir(root) / "latest.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def needs_daily_scan(root: Path | None = None) -> bool:
    """True if no successful scan finished today (UTC)."""
    con = connect_db(root)
    try:
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        row = con.execute(
            """
            SELECT scan_id FROM scans
            WHERE finished_utc IS NOT NULL AND finished_utc LIKE ?
            ORDER BY finished_utc DESC LIMIT 1
            """,
            (f"{day}%",),
        ).fetchone()
        return row is None
    finally:
        con.close()


def daily(
    *,
    instance_id: str = DEFAULT_INSTANCE,
    root: Path | None = None,
    force: bool = False,
    linear: bool = True,
) -> dict[str, Any]:
    """Once-a-day catalog refresh.

    Default: linear All-channels number scroll (most complete). Optional group
    priority pass still available with linear=False.
    """
    root = ensure_data_layout(root)
    if not force and not needs_daily_scan(root):
        board = write_board(root)
        return {"ok": True, "skipped": True, "reason": "already_scanned_today", **board}
    if linear:
        import_legacy(root)
        scan_id = f"daily_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}"
        out = scan_linear(instance_id=instance_id, root=root, scan_id=scan_id, max_swipes=500)
        board = write_board(root)
        try:
            from .farm_ops import emit

            emit(
                "guide_catalog_daily",
                detail=f"linear channels={out.get('channels')} total={board.get('channel_count')}",
                instance_id=instance_id,
                ok=bool(out.get("ok")),
                extra={"scan_id": scan_id, **{k: out.get(k) for k in ("channels", "passes", "error")}},
                root=root,
            )
        except Exception:
            pass
        return {"ok": bool(out.get("ok")), "mode": "linear", **out, **board}
    if scan_state_path(root).is_file() and force:
        scan_state_path(root).unlink()
    return scan(instance_id=instance_id, root=root, priority_only=True, resume=not force)


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="Streamers guide channel number database")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("board", help="Write GUIDE_CATALOG.md")
    sub.add_parser("import-legacy", help="Seed from streamers_guide_channels.json")
    sc = sub.add_parser("scan", help="Scan groups into SQLite")
    sc.add_argument("--instance", default=DEFAULT_INSTANCE)
    sc.add_argument("--priority", action="store_true", help="Booth/national groups first")
    sc.add_argument("--group", action="append", default=[], help="Only these groups")
    sc.add_argument("--max-groups", type=int, default=None)
    sc.add_argument("--no-resume", action="store_true")
    sc.add_argument(
        "--linear",
        action="store_true",
        help="Scroll All-channels number gutter (full census, no section taps)",
    )
    sc.add_argument("--max-swipes", type=int, default=400)
    dy = sub.add_parser("daily", help="Once-per-day priority scan")
    dy.add_argument("--instance", default=DEFAULT_INSTANCE)
    dy.add_argument("--force", action="store_true")
    dy.add_argument(
        "--groups-only",
        action="store_true",
        help="Scan priority SECTION groups instead of linear All-channels",
    )
    lk = sub.add_parser("lookup", help="Query channel DB")
    lk.add_argument("--number", type=int)
    lk.add_argument("--calls")
    lk.add_argument("--network")
    lk.add_argument("--market")
    lk.add_argument("--group")
    lk.add_argument("--q")
    lk.add_argument("--limit", type=int, default=25)
    bl = sub.add_parser("best-local", help="Best Atlanta/Alabama affiliate number")
    bl.add_argument("--network", required=True)
    bl.add_argument("--market", default="Atlanta")
    args = p.parse_args(argv)

    if args.cmd == "board":
        print(json.dumps(write_board(), indent=2))
        return 0
    if args.cmd == "import-legacy":
        print(json.dumps(import_legacy(), indent=2))
        write_board()
        return 0
    if args.cmd == "scan":
        if args.linear:
            out = scan_linear(
                instance_id=args.instance,
                max_swipes=int(args.max_swipes),
            )
        else:
            out = scan(
                instance_id=args.instance,
                priority_only=bool(args.priority),
                groups=list(args.group) or None,
                resume=not bool(args.no_resume),
                max_groups=args.max_groups,
            )
        print(json.dumps(out, indent=2)[:4000])
        return 0 if out.get("ok") else 2
    if args.cmd == "daily":
        out = daily(
            instance_id=args.instance,
            force=bool(args.force),
            linear=not bool(args.groups_only),
        )
        print(json.dumps(out, indent=2)[:4000])
        return 0 if out.get("ok") else 2
    if args.cmd == "lookup":
        rows = lookup(
            number=args.number,
            calls=args.calls,
            network=args.network,
            market=args.market,
            group=args.group,
            q=args.q,
            limit=args.limit,
        )
        print(json.dumps({"ok": True, "count": len(rows), "rows": rows}, indent=2))
        return 0
    if args.cmd == "best-local":
        row = best_local(args.network, market=args.market)
        print(json.dumps({"ok": bool(row), "channel": row}, indent=2))
        return 0 if row else 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
