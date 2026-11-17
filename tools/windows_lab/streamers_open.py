"""Open Streamers channels by search, and keep confirmed shortcuts.

Sports default: search the show / team / event name first. Do not scroll
empty AMZN## / event-slot rows hoping for a live card. Save every path that
actually opens a picture so the next take is one command.
"""

from __future__ import annotations

import json
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import ensure_data_layout
from .instances import adb, connect_adb, get_instance, launch_bluestacks, wait_for_adb

SHORTCUTS_NAME = "streamers_open_shortcuts.json"
DEFAULT_INSTANCE = "player 0"  # BlueStacks engine Nougat32

# Prefer these channel-title prefixes when several search hits match.
SPORTS_CHANNEL_PREF = (
    "NFL 01",
    "NFL 02",
    "NFL 03",
    "NFL ",
    "ESPN",
    "TSN+",
    "DAZN",
)

SKIP_TITLE_FRAGMENTS = (
    "no event available",
    "search history",
    "in french",
    "(in french)",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def shortcuts_path(root: Path | None = None) -> Path:
    return ensure_data_layout(root) / "indexes" / SHORTCUTS_NAME


def load_shortcuts(root: Path | None = None) -> dict[str, Any]:
    path = shortcuts_path(root)
    if not path.is_file():
        data = {"updated_utc": _now(), "policy": _default_policy(), "shortcuts": {}}
        save_shortcuts(data, root)
        return data
    data = json.loads(path.read_text(encoding="utf-8"))
    data.setdefault("policy", _default_policy())
    data.setdefault("shortcuts", {})
    return data


def save_shortcuts(data: dict[str, Any], root: Path | None = None) -> Path:
    path = shortcuts_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = dict(data)
    body["updated_utc"] = _now()
    path.write_text(json.dumps(body, indent=2), encoding="utf-8")
    return path


def _default_policy() -> dict[str, Any]:
    return {
        "sports_open": (
            "Events: search show/team → live Channels card (NFL 01…) → keyevent 23. "
            "Linear nets: parent section from tv_groups (US SPORTS) → child row "
            "(US: ESPN / US: ESPN 2) — not ESPNU, not MAX SPORTS."
        ),
        "avoid": [
            "Scrolling AMAZON SPORTS empty AMZN## rows",
            "MAX SPORTS ESPN for national commercials",
            "Fixed x,y taps from an old dump",
            "EXAMPLE channel recipe / keyevent 82",
        ],
        "open_key": 23,
        "back_key": 4,
        "nav": "python -m tools.windows_lab nav teach --route ESPN_US",
    }


def save_shortcut(
    *,
    shortcut_id: str,
    search_query: str,
    channel_title: str,
    channel_number: str | None = None,
    group: str | None = None,
    kind: str = "sports",
    notes: str | None = None,
    session_id: str | None = None,
    open_meta: dict[str, Any] | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Remember a confirmed open path (section child or search → title → center)."""
    data = load_shortcuts(root)
    if open_meta:
        open_block = dict(open_meta)
        open_block.setdefault("method", "search_then_center")
    elif kind == "local" and group and str(group).endswith("SECTION"):
        open_block = {
            "method": "us_section_grouper",
            "section": group,
        }
    else:
        open_block = {
            "method": "search_then_center",
            "prefer_prefixes": list(SPORTS_CHANNEL_PREF) if kind == "sports" else [],
        }
    row = {
        "id": shortcut_id,
        "kind": kind,
        "search_query": search_query,
        "channel_title": channel_title,
        "channel_title_match": channel_title,
        "channel_number": channel_number,
        "group": group,
        "notes": notes,
        "last_session_id": session_id,
        "confirmed_utc": _now(),
        "open": open_block,
    }
    data["shortcuts"][shortcut_id] = row
    save_shortcuts(data, root)
    return row


def list_shortcuts(root: Path | None = None, *, kind: str | None = None) -> list[dict[str, Any]]:
    data = load_shortcuts(root)
    rows = list((data.get("shortcuts") or {}).values())
    if kind:
        rows = [r for r in rows if r.get("kind") == kind]
    rows.sort(key=lambda r: str(r.get("confirmed_utc") or ""), reverse=True)
    return rows


def get_shortcut(shortcut_id: str, root: Path | None = None) -> dict[str, Any]:
    data = load_shortcuts(root)
    row = (data.get("shortcuts") or {}).get(shortcut_id)
    if not row:
        known = sorted((data.get("shortcuts") or {}).keys())
        needle = str(shortcut_id or "").upper()
        tokens = [t for t in re.findall(r"[A-Z0-9]+", needle) if len(t) >= 2]
        near = [k for k in known if any(t in str(k).upper() for t in tokens)][:12]
        if not near:
            near = [
                k
                for k in known
                if any(
                    kt in needle
                    for kt in re.findall(r"[A-Z0-9]+", str(k).upper())
                    if len(kt) >= 3
                )
            ][:12]
        if not near and known:
            near = known[:12]
        raise KeyError(
            f"shortcut not found: {shortcut_id}; near={near}; "
            f"known_count={len(known)}; create via search_open --save-as or "
            f"schedule from an existing id (e.g. FOX_LOCAL / NFL_GERMANY / CBS_LOCAL)"
        )
    return row


def _dump_ui(instance: dict[str, Any], dest: Path) -> ET.Element:
    """Hard dump via ui_dump contract (null-root / empty → raise + emit + heal)."""
    from .ui_dump import dump_ui_hard

    return dump_ui_hard(instance, dest, caller="streamers_open")


def _texts(root: ET.Element) -> list[str]:
    return [
        (n.attrib.get("text") or "").strip()
        for n in root.iter("node")
        if (n.attrib.get("text") or "").strip()
    ]


def _bounds_center(bounds: str) -> tuple[int, int]:
    m = re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)
    if not m:
        raise ValueError(f"bad bounds: {bounds}")
    x1, y1, x2, y2 = map(int, m.groups())
    return (x1 + x2) // 2, (y1 + y2) // 2


def _bounds_wh(bounds: str) -> tuple[int, int, int, int]:
    m = re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)
    if not m:
        raise ValueError(f"bad bounds: {bounds}")
    x1, y1, x2, y2 = map(int, m.groups())
    return x1, y1, x2 - x1, y2 - y1


def _best_tap_target(
    node: ET.Element,
    parents: dict[ET.Element, ET.Element],
) -> tuple[int, int, str]:
    """Tap the text (or smallest tight clickable ancestor) — never a full-screen parent.

    Climbing to the first clickable ancestor used to hit the center of a huge
    list/container, so left-rail labels like ``US SPORTS`` never switched the
    group (grid stayed on CBS/NBC locals while open_section reported ok).
    """
    text_b = node.attrib.get("bounds") or ""
    tx, ty = _bounds_center(text_b)
    _, _, tw, th = _bounds_wh(text_b)
    text_area = max(tw * th, 1)
    best: tuple[int, int, int, str] | None = None  # area, x, y, bounds
    cur: ET.Element | None = node
    while cur is not None:
        b = cur.attrib.get("bounds") or ""
        try:
            x, y = _bounds_center(b)
            _, _, w, h = _bounds_wh(b)
            area = max(w * h, 1)
        except ValueError:
            cur = parents.get(cur)
            continue
        is_self = cur is node
        clickable = cur.attrib.get("clickable") == "true"
        if is_self or clickable:
            # Reject giant containers relative to the label/row text.
            if (
                area <= max(text_area * 14, 120_000)
                and h <= max(th * 5, 160)
                and w <= max(tw * 4, 1000)
            ):
                if best is None or area < best[0]:
                    best = (area, x, y, b)
        cur = parents.get(cur)
    if best:
        return best[1], best[2], best[3]
    return tx, ty, text_b


def _tap_text(
    instance: dict[str, Any],
    root: ET.Element,
    text: str,
    *,
    contains: bool = False,
) -> dict[str, Any] | None:
    parents = {c: p for p in root.iter() for c in list(p)}
    for node in root.iter("node"):
        t = (node.attrib.get("text") or "").strip()
        ok = (text.lower() in t.lower()) if contains else (t == text)
        if not ok:
            continue
        try:
            x, y, b = _best_tap_target(node, parents)
        except ValueError:
            continue
        rc, out = adb(instance, ["shell", "input", "tap", str(x), str(y)])
        return {"ok": rc == 0, "text": t, "bounds": b, "xy": [x, y], "detail": out}
    return None


def _search_field_node(root: ET.Element) -> ET.Element | None:
    """Streamers search is leanback StreamingTextView, not EditText."""
    preferred: ET.Element | None = None
    fallback: ET.Element | None = None
    for node in root.iter("node"):
        cls = node.attrib.get("class") or ""
        if "EditText" in cls or "StreamingTextView" in cls:
            if node.attrib.get("focused") == "true":
                return node
            preferred = preferred or node
            continue
        if (
            node.attrib.get("focused") == "true"
            and node.attrib.get("long-clickable") == "true"
            and node.attrib.get("bounds")
        ):
            fallback = fallback or node
    return preferred or fallback


def _clear_search_field(instance: dict[str, Any], root: ET.Element) -> None:
    node = _search_field_node(root)
    if node is None:
        return
    x, y = _bounds_center(node.attrib["bounds"])
    adb(instance, ["shell", "input", "tap", str(x), str(y)])
    time.sleep(0.35)
    adb(instance, ["shell", "input", "keyevent", "123"])  # MOVE_END
    for _ in range(64):
        adb(instance, ["shell", "input", "keyevent", "67"])  # DEL/backspace
    time.sleep(0.25)


def _type_search_query(instance: dict[str, Any], query: str) -> None:
    """Type into the focused search field (field must already be cleared)."""
    raw = query.strip()
    # Space → %s for `adb shell input text`. No throwaway "x" prefix — that used
    # HOME+backspace, which never deleted the x (backspace is before-cursor) and
    # left queries like "xCBS". Clear first, then type the real query.
    payload = raw.replace(" ", "%s")
    adb(instance, ["shell", "input", "text", payload])
    time.sleep(0.25)


_BIG_DMA_FRAGMENTS = (
    "new york",
    "los angeles",
    "chicago",
    "dallas",
    "atlanta",
    "philadelphia",
    "houston",
    "boston",
    "san francisco",
    "washington",
    "wcbs",
    "wabc",
    "wnbc",
    "wnyw",
    "knbc",
    "kcbs",
    "kabc",
    "wbbm",
    "wls",
)


def _score_channel_title(title: str, *, query: str) -> int:
    low = title.lower()
    if any(s in low for s in SKIP_TITLE_FRAGMENTS):
        return -1000
    if low in {"search", "channels", "programs", "tv", "movies", "shows"}:
        return -1000
    if low.startswith("-------") or low.endswith("-------"):
        return -1000
    if low == query.lower():
        return -50  # search field echo
    # Call-letter queries (WSB/WXIA/…) must not land on ESPNU / Max Sports history chips.
    q_up = query.strip().upper()
    if re.fullmatch(r"[A-Z]{3,5}", q_up):
        if "max sports" in low or low in {"espn", "espn2", "espnu", "espn+"}:
            return -1000
        if not re.search(rf"(?<![A-Z]){re.escape(q_up)}(?![A-Z])", title.upper()):
            return -1000
    score = 0
    for i, pref in enumerate(SPORTS_CHANNEL_PREF):
        if title.startswith(pref) or pref.lower() in low:
            score += 100 - i
            break
    # US local linear: "NY | NEW YORK | CBS - WCBS" / "AK | FAIRBANKS | CBS - KXDF"
    net_m = re.search(r"\|\s*(ABC|CBS|NBC|FOX)\s*-\s*[A-Z0-9-]{3,8}\b", title, re.I)
    if net_m:
        score += 55
        if any(d in low for d in _BIG_DMA_FRAGMENTS):
            score += 35
        q_up = query.strip().upper()
        for net in ("ABC", "CBS", "NBC", "FOX"):
            if q_up == net or q_up.startswith(net + " "):
                if net_m.group(1).upper() != net:
                    score -= 90  # wrong network for this query
                break
    if "news 24/7" in low or "news now" in low:
        score += 45
        q_up = query.strip().upper()
        if "NEWS" in q_up or q_up in {"CNN", "MSNBC", "FOX NEWS"}:
            score += 20
    # Prefer literal network name matches (NFL Network, FOX) over unrelated ESPN hits.
    q_low = query.strip().lower()
    if "nfl network" in q_low or q_low in {"nfln", "nfl net"}:
        if "nfl network" in low or low.strip() in {"nfln", "nfl network"}:
            score += 120
        elif "espn" in low and "nfl" not in low:
            score -= 80
    # Network-name search is a movie trap ("After the Fox"). Only boost affiliate shape.
    net_q = re.match(r"^(abc|cbs|nbc|fox)\b", q_low)
    if net_q:
        want_net = net_q.group(1).upper()
        if net_m and net_m.group(1).upper() == want_net:
            score += 80
        else:
            # Movies / shows / bare "FOX" chips — never prefer these for local opens.
            score -= 200
            if re.search(r"\(\d{4}\)|after the fox|movie|film", low):
                score -= 500
    if " | " in title and re.search(r"\d{1,2}:\d{2}\s*PM|\d{1,2}:\d{2}\s*AM", title):
        score += 40
    if re.search(r"\bvs\.?\b|\bat\b|@", title, re.I):
        score += 30
    if "munich" in low or "germany" in low:
        score += 50
    if "live" in low or "ᴸ" in title:
        score += 20
    qparts = [p for p in re.split(r"\s+", query.strip()) if len(p) > 2]
    score += 5 * sum(1 for p in qparts if p.lower() in low)
    return score


def _pick_channel_title(titles: list[str], *, query: str) -> str | None:
    ranked = sorted(
        (( _score_channel_title(t, query=query), t) for t in titles),
        key=lambda x: x[0],
        reverse=True,
    )
    for score, title in ranked:
        if score < 10:
            break
        return title
    return None


def _open_search_via_longpress(
    instance: dict[str, Any],
    ui: ET.Element,
    probe: Path,
) -> dict[str, Any]:
    """Long-press a guide channel title → context menu → Search."""
    # Prefer real channel rows (CALL / MAX / NFL cards), never the left group rail
    # or empty AMZN## event slots (those swipe-scroll instead of opening the menu).
    candidates: list[tuple[int, str, int, int, int, int]] = []
    for node in ui.iter("node"):
        t = (node.attrib.get("text") or "").strip()
        b = node.attrib.get("bounds") or ""
        if not t or not b:
            continue
        if t.startswith("---") or t in ("No information", "OFF", "ON", "Favorites", "All channels"):
            continue
        if t.endswith("SECTION") or t.endswith("CHANNELS") or t.endswith("SPORTS"):
            continue
        if re.fullmatch(r"\d{1,4}", t):
            continue
        if "min" in t or "—" in t:
            continue
        # Time-stamped sports cards (SN+ 03 | 9:50 AM ET …) still long-press OK —
        # only skip pure clock chrome like "04:00 — 05:00 PM".
        if re.search(r"\b(AM|PM)\b", t) and " | " not in t and not t.startswith("("):
            continue
        if "no event available" in t.lower():
            continue
        if re.match(r"^AMZN\s*\d+", t, re.I):
            continue
        m = re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", b)
        if not m:
            continue
        x1, y1, x2, y2 = map(int, m.groups())
        if y1 < 350:
            continue
        # Pack EPGs (Pluto / FLSP / SN+) put titles in a narrow left column (x2~441).
        # Those are valid long-press targets; only skip the number gutter / true rail.
        narrow_title = (" | " in t or t.startswith("(")) and x2 >= 350
        if x2 < 500 and not narrow_title:
            continue
        if len(t) < 4:
            continue
        rank = 0
        if re.search(r"\|\s*(ABC|CBS|NBC|FOX)\s*-", t, re.I):
            rank += 50
        if t.startswith("(") or t.startswith("NFL"):
            rank += 40
        if re.search(r"\b(ESPN|FOX|CBS|NBC|ABC|NFL|PLUTO|FLSP|SN\+)\b", t, re.I):
            rank += 25
        if " | " in t:
            rank += 20
        if " " in t:
            rank += 5
        candidates.append((rank, t, x1, y1, x2, y2))
    candidates.sort(key=lambda r: r[0], reverse=True)
    if not candidates:
        return {
            "ok": False,
            "error": "no channel title to long-press",
            "seen": [],
            "ui_texts": _texts(ui)[:20],
        }
    if candidates[0][0] <= 0:
        return {
            "ok": False,
            "error": "no channel title to long-press",
            "seen": [c[1] for c in candidates[:8]],
            "ui_texts": _texts(ui)[:20],
        }
    # Prefer NFL A / sports group first so long-press lands on a real card.
    rail = _texts(ui)
    for group_name in ("NFL A", "NFL TEAMS/CHANNELS", "MAX SPORTS"):
        if group_name in rail:
            _tap_text(instance, ui, group_name)
            time.sleep(1.0)
            ui = _dump_ui(instance, probe / "open_group.xml")
            # Rebuild candidates on the new group.
            candidates = []
            for node in ui.iter("node"):
                t = (node.attrib.get("text") or "").strip()
                b = node.attrib.get("bounds") or ""
                if not t or not b:
                    continue
                if t.startswith("---") or t in ("No information", "OFF", "ON", "Favorites", "All channels"):
                    continue
                if t.endswith("SECTION") or t.endswith("CHANNELS") or t.endswith("SPORTS"):
                    continue
                if re.fullmatch(r"\d{1,4}", t) or "no event available" in t.lower():
                    continue
                if re.match(r"^AMZN\s*\d+", t, re.I):
                    continue
                if "min" in t or "—" in t or re.search(r"\b(AM|PM)\b", t):
                    continue
                m = re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", b)
                if not m:
                    continue
                x1, y1, x2, y2 = map(int, m.groups())
                if y1 < 350 or x2 < 500:
                    continue
                if len(t) < 4:
                    continue
                rank = 0
                if t.startswith("NFL") or "NFL" in t:
                    rank += 60
                if t.startswith("("):
                    rank += 40
                if re.search(r"\b(ESPN|FOX|CBS|NBC|ABC|NFL)\b", t, re.I):
                    rank += 25
                if " | " in t:
                    rank += 20
                candidates.append((rank, t, x1, y1, x2, y2))
            candidates.sort(key=lambda r: r[0], reverse=True)
            break

    # Try top candidates until the context menu actually shows Search.
    last_menu_texts: list[str] = []
    for _rank, _t, x1, y1, x2, y2 in candidates[:5]:
        cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
        # Longer hold — short swipes scroll the guide instead of opening the menu.
        adb(instance, ["shell", "input", "swipe", str(cx), str(cy), str(cx), str(cy), "2800"])
        time.sleep(1.6)
        menu = _dump_ui(instance, probe / "open_longpress_menu.xml")
        last_menu_texts = _texts(menu)
        if "Search" not in last_menu_texts:
            # Do not Back here — that exits Streamers when the menu never opened.
            time.sleep(0.3)
            continue
        tapped = _tap_text(instance, menu, "Search")
        if not tapped:
            return {"ok": False, "error": "could not tap Search in long-press menu"}
        time.sleep(0.8)
        search_ui = _dump_ui(instance, probe / "open_search_ready.xml")
        return {"ok": True, "ui": search_ui, "longpress_title": _t, "tap": tapped}
    return {
        "ok": False,
        "error": "long-press menu missing Search",
        "texts": last_menu_texts[:20],
        "tried": [c[1] for c in candidates[:5]],
    }


def search_open(
    *,
    query: str,
    instance_id: str = DEFAULT_INSTANCE,
    title_contains: str | None = None,
    open_player: bool = True,
    save_as: str | None = None,
    kind: str = "sports",
    root: Path | None = None,
) -> dict[str, Any]:
    """Search Streamers for query, select best Channels row, optionally open.

    Bare ABC/CBS/NBC/FOX queries are redirected to US * SECTION parent→child
    (alphabetical affiliates). Network-name search hits movies.
    """
    root = ensure_data_layout(root)
    q_bare = re.fullmatch(r"(?i)(abc|cbs|nbc|fox)(?:\s+(ny|nyc|la|atl|new\s+york))?", query.strip() or "")
    if q_bare:
        from .us_locals import open_local

        net = q_bare.group(1).upper()
        mkt_raw = (q_bare.group(2) or "").strip()
        market = None
        if mkt_raw:
            market = "New York" if mkt_raw.lower() in {"ny", "nyc", "new york"} else mkt_raw
        sid = save_as or (f"{net}_NY" if market == "New York" else f"{net}_LOCAL")
        out = open_local(
            net,
            market=market,
            shortcut_id=str(sid),
            instance_id=instance_id,
            open_player=open_player,
            save=True,
            root=root,
        )
        out["open_via"] = "section_child"
        out["redirected_from_search"] = query
        return out
    instance = get_instance(instance_id, root)
    launch_bluestacks(instance, launch_app=True)
    connect_adb(instance)
    if not wait_for_adb(instance, seconds=60):
        return {"ok": False, "error": "ADB not ready"}

    # Autonomous unstick before search (empty guide / decode error / BS home).
    try:
        from .streamers_recover import ensure_ready_for_open

        recovered = ensure_ready_for_open(instance_id, root=root)
        if not recovered.get("ok") and recovered.get("final_kind") in {
            "welcome_login",
            "credentials_login",
            "bluestacks_home",
        }:
            return {"ok": False, "error": "recover_failed", "recover": recovered}
    except Exception as e:  # noqa: BLE001
        recovered = {"ok": False, "error": str(e)}

    # Per-instance dump dir — parallel opens must not smash a shared XML path.
    iid = str((instance or {}).get("id") or (instance or {}).get("engine") or "unknown")
    probe = root / "work" / "capture" / "bluestacks_probe" / iid
    probe.mkdir(parents=True, exist_ok=True)
    # Back out of player only (one step). Extra backs exit Streamers to BlueStacks home.
    # If chrome is hidden (empty dump) or we are still on a full-frame player, one more Back.
    adb(instance, ["shell", "input", "keyevent", "4"])
    time.sleep(0.8)

    ui = _dump_ui(instance, probe / "open_home.xml")
    texts = _texts(ui)
    if len(texts) < 3 or (
        "Favorites" not in texts
        and "Search" not in texts
        and "Search history" not in texts
        and not any(t.startswith("(") or t.startswith("NFL") or " | " in t for t in texts)
    ):
        adb(instance, ["shell", "input", "keyevent", "4"])
        time.sleep(0.9)
        ui = _dump_ui(instance, probe / "open_home.xml")
        texts = _texts(ui)
        # If we fell out to BlueStacks home, relaunch Streamers once.
        if any("POPULAR GAMES" in t or "Search for games" in t for t in texts):
            adb(
                instance,
                [
                    "shell",
                    "monkey",
                    "-p",
                    "ar.tvplayer.tv",
                    "-c",
                    "android.intent.category.LAUNCHER",
                    "1",
                ],
            )
            time.sleep(3.0)
            ui = _dump_ui(instance, probe / "open_home.xml")
            texts = _texts(ui)
    # Dismiss group-settings overlay (Block/Hide group) that blocks Search.
    if "Block group" in texts or "Hide group" in texts:
        adb(instance, ["shell", "input", "keyevent", "4"])
        time.sleep(0.6)
        ui = _dump_ui(instance, probe / "open_home.xml")
        texts = _texts(ui)

    already_search = "Search history" in texts or (
        "Channels" in texts and "Programs" in texts
    )
    if not already_search:
        tapped = _tap_text(instance, ui, "Search") if "Search" in texts else None
        if not tapped:
            # Guide chrome often hides Search — long-press a channel row, then tap Search.
            opened = _open_search_via_longpress(instance, ui, probe)
            if not opened.get("ok"):
                lp_err = str(opened.get("error") or "longpress_failed")
                lp_tried = opened.get("tried") or opened.get("seen") or []
                lp_menu = opened.get("texts") or []
                place = "guide_or_player"
                if any("POPULAR GAMES" in t or "Search for games" in t for t in texts):
                    place = "bluestacks_home"
                elif "Block group" in texts or "Hide group" in texts:
                    place = "group_settings_overlay"
                detail = (
                    f"Search control not found query={query!r} place={place} "
                    f"Search_in_texts={('Search' in texts)} longpress={lp_err} "
                    f"tried={list(lp_tried)[:5]} menu_texts={list(lp_menu)[:8]} "
                    f"texts={texts[:12]}"
                )
                return {
                    "ok": False,
                    "error": detail,
                    "query": query,
                    "place": place,
                    "texts": texts[:30],
                    "longpress": opened,
                }
            ui = opened["ui"]
        time.sleep(0.9)
        ui = _dump_ui(instance, probe / "open_search.xml")

    _clear_search_field(instance, ui)
    _type_search_query(instance, query)
    adb(instance, ["shell", "input", "keyevent", "66"])
    time.sleep(2.2)

    ui = _dump_ui(instance, probe / "open_results.xml")
    titles = _texts(ui)
    # Team / network queries often land on Movies/Shows — force the Channels tab.
    force_channels = "Channels" in titles and (
        "Movies" in titles
        or "Shows" in titles
        or re.fullmatch(r"(?i)(abc|cbs|nbc|fox)", query.strip() or "") is not None
        or not any(
            t.startswith("(")
            or t.startswith("NFL")
            or " | " in t
            or re.search(r"\b(ESPN|FOX|CBS|NBC|ABC)\b", t, re.I)
            for t in titles
        )
    )
    if force_channels:
        _tap_text(instance, ui, "Channels")
        time.sleep(1.0)
        ui = _dump_ui(instance, probe / "open_results_channels.xml")
        titles = _texts(ui)
    pick = None
    if title_contains:
        # Best-scoring card among title_contains matches (prefer big-DMA locals).
        cand = [
            (_score_channel_title(t, query=query), t)
            for t in titles
            if title_contains.lower() in t.lower()
        ]
        cand = [(s, t) for s, t in cand if s >= 10]
        if cand:
            pick = max(cand, key=lambda x: x[0])[1]
    if not pick:
        # Always score against the typed query (not title_contains needle) —
        # otherwise "Atlanta" can rank ESPNU history chips over WXIA results.
        pick = _pick_channel_title(titles, query=query)
    if not pick:
        return {
            "ok": False,
            "error": "no ranked channel title in search results",
            "query": query,
            "titles": titles[:40],
        }
    # Hard reject sports-pack near-misses for affiliate call-letter opens.
    if re.fullmatch(r"[A-Za-z]{3,5}", query.strip()) and (
        "max sports" in pick.lower()
        or pick.upper() in {"ESPN", "ESPN2", "ESPNU", "ESPN+"}
        or query.strip().upper() not in pick.upper()
    ):
        return {
            "ok": False,
            "error": f"rejected_bad_search_pick:{pick}",
            "query": query,
            "titles": titles[:40],
        }

    sel = _tap_text(instance, ui, pick, contains=True)
    if not sel:
        return {"ok": False, "error": f"could not tap title: {pick}", "query": query}
    time.sleep(0.6)

    opened = False
    player_texts: list[str] = []
    if open_player:
        adb(instance, ["shell", "input", "keyevent", "23"])
        time.sleep(2.0)
        ui2 = _dump_ui(instance, probe / "open_player.xml")
        player_texts = _texts(ui2)
        opened = True

    channel_number = None
    group = None
    for t in player_texts:
        if re.fullmatch(r"\d{3,5}", t):
            channel_number = t
        if t in ("NFL A", "NFL T", "NFL Y", "MAX SPORTS", "AMAZON SPORTS") or t.endswith(" SECTION"):
            group = t

    shortcut = None
    if save_as:
        shortcut = save_shortcut(
            shortcut_id=save_as,
            search_query=query,
            channel_title=pick,
            channel_number=channel_number,
            group=group,
            kind=kind,
            notes="auto-saved from search_open",
            root=root,
        )

    return {
        "ok": True,
        "query": query,
        "selected_title": pick,
        "select": sel,
        "opened": opened,
        "channel_number": channel_number,
        "group": group,
        "player_texts": player_texts[:30],
        "shortcut": shortcut,
    }


# Linear nets: schedule/search must not invent ESPNU — use parent→child nav routes.
LINEAR_NAV_BY_SHORTCUT = {
    "ESPN_US": "ESPN_US",
    "ESPN2_US": "ESPN2_US",
    "MNF_ESPN": "ESPN_US",
    "MNF_MANNINGCAST": "ESPN2_US",
    "MNF_POST_ESPN": "ESPN_US",
    "MNF_COUNTDOWN": "ESPN_US",
}


def nav_route_for_shortcut(shortcut_id: str, row: dict[str, Any] | None = None) -> str | None:
    open_meta = (row or {}).get("open") if row else None
    if isinstance(open_meta, dict):
        rid = open_meta.get("route_id")
        if open_meta.get("method") == "section_route" and rid:
            return str(rid)
    return LINEAR_NAV_BY_SHORTCUT.get(str(shortcut_id).upper())


def open_shortcut(
    shortcut_id: str,
    *,
    instance_id: str = DEFAULT_INSTANCE,
    root: Path | None = None,
) -> dict[str, Any]:
    """Open by parent→child when possible; search only for event cards.

    Priority: linear nav route → US * SECTION alphabetical child → search.
    Missing FOX_NY / CBS_NY ids still resolve via market tokens (no movie search).
    """
    row: dict[str, Any] | None
    try:
        row = get_shortcut(shortcut_id, root)
    except KeyError:
        row = None

    route_id = nav_route_for_shortcut(shortcut_id, row)
    if route_id:
        from .streamers_nav import run_route

        out = run_route(
            route_id,
            instance_id=instance_id,
            root=root,
            open_player=True,
            save_as=shortcut_id,
        )
        out["open_via"] = "nav"
        out["nav_route"] = route_id
        sc = out.get("shortcut") if isinstance(out.get("shortcut"), dict) else {}
        out["selected_title"] = out.get("selected_title") or sc.get("channel_title")
        if not out.get("selected_title"):
            for step in reversed(out.get("atoms") or []):
                chosen = (step.get("result") or {}).get("chosen") or step.get("chosen")
                if chosen:
                    out["selected_title"] = chosen
                    break
        return out

    # Locals / US * SECTION children — never network-name search (After the Fox).
    from .us_locals import open_local_for_shortcut

    local_out = open_local_for_shortcut(
        shortcut_id,
        row=row,
        instance_id=instance_id,
        root=root,
    )
    if local_out is not None:
        return local_out

    if row is None:
        raise KeyError(f"shortcut not found: {shortcut_id}")

    return search_open(
        query=str(row["search_query"]),
        instance_id=instance_id,
        title_contains=str(row.get("channel_title_match") or row.get("channel_title") or ""),
        open_player=True,
        save_as=shortcut_id,
        kind=str(row.get("kind") or "sports"),
        root=root,
    )


def ensure_tnf_shortcut(root: Path | None = None) -> dict[str, Any]:
    """Seed the confirmed 2026-11-12 Giants/Commanders → NFL 01 path."""
    return save_shortcut(
        shortcut_id="TNF_PRIME",
        search_query="Commanders",
        channel_title="NFL 01 | 8:15 PM ET - New York Giants vs Washington Commanders",
        channel_number="542",
        group="NFL A",
        kind="sports",
        notes=(
            "Confirmed 2026-11-12. Search team/show name first. "
            "Prefer NFL 01 English card over DAZNCA French / empty AMZN##."
        ),
        session_id="streamers_20261113T032451Z_TNF_PRIME_Nougat32",
        root=root,
    )


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="Streamers search-open + shortcuts")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("search", help="Search show/team name and open best live row")
    s.add_argument("--query", required=True)
    s.add_argument("--title-contains", default=None, help="Prefer a Channels card containing this")
    s.add_argument("--instance", default=DEFAULT_INSTANCE)
    s.add_argument("--save-as", default=None, help="Shortcut id to write on success")
    s.add_argument("--kind", default="sports")
    s.add_argument("--no-open", action="store_true", help="Select only; skip keyevent 23")

    o = sub.add_parser("play", help="Re-open a saved shortcut")
    o.add_argument("--id", required=True)
    o.add_argument("--instance", default=DEFAULT_INSTANCE)

    sv = sub.add_parser("save", help="Manually record a confirmed shortcut")
    sv.add_argument("--id", required=True)
    sv.add_argument("--query", required=True)
    sv.add_argument("--title", required=True)
    sv.add_argument("--number", default=None)
    sv.add_argument("--group", default=None)
    sv.add_argument("--kind", default="sports")
    sv.add_argument("--notes", default=None)
    sv.add_argument("--session", default=None)

    ls = sub.add_parser("list")
    ls.add_argument("--kind")

    sub.add_parser("policy")
    sub.add_parser("seed-tnf", help="Write the confirmed TNF_PRIME shortcut")

    loc = sub.add_parser(
        "local",
        help="Open purposeful US ABC/CBS/NBC/FOX local (any DMA via US * SECTION)",
    )
    loc.add_argument("--network", required=True, choices=["ABC", "CBS", "NBC", "FOX", "abc", "cbs", "nbc", "fox"])
    loc.add_argument("--market", default=None, help='e.g. "New York" or "Los Angeles"')
    loc.add_argument("--instance", default=DEFAULT_INSTANCE)
    loc.add_argument("--no-open", action="store_true")
    loc.add_argument("--west", action="store_true", help="Prefer West Coast DMA this take")

    rc = sub.add_parser("recover", help="Autonomous unstick (dump→fix→verify)")
    rc.add_argument("--instance", default=DEFAULT_INSTANCE)
    rc.add_argument("--goal", choices=["guide", "picture"], default="guide")
    rc.add_argument("--steps", type=int, default=8)
    hb = sub.add_parser(
        "heartbeat-fix",
        help="Fix stream when picture/audio heartbeat fails (spinner/cloud/error)",
    )
    hb.add_argument("--instance", default=DEFAULT_INSTANCE)
    hb.add_argument("--force", action="store_true")
    sn = sub.add_parser("snap", help="Classify current Streamers screen + save frame")
    sn.add_argument("--instance", default=DEFAULT_INSTANCE)

    args = p.parse_args(argv)
    if args.cmd == "search":
        print(
            json.dumps(
                search_open(
                    query=args.query,
                    instance_id=args.instance,
                    title_contains=args.title_contains,
                    open_player=not args.no_open,
                    save_as=args.save_as,
                    kind=args.kind,
                ),
                indent=2,
            )
        )
        return 0
    if args.cmd == "play":
        print(json.dumps(open_shortcut(args.id, instance_id=args.instance), indent=2))
        return 0
    if args.cmd == "save":
        print(
            json.dumps(
                save_shortcut(
                    shortcut_id=args.id,
                    search_query=args.query,
                    channel_title=args.title,
                    channel_number=args.number,
                    group=args.group,
                    kind=args.kind,
                    notes=args.notes,
                    session_id=args.session,
                ),
                indent=2,
            )
        )
        return 0
    if args.cmd == "list":
        print(json.dumps({"shortcuts": list_shortcuts(kind=args.kind)}, indent=2))
        return 0
    if args.cmd == "policy":
        print(json.dumps(load_shortcuts().get("policy"), indent=2))
        return 0
    if args.cmd == "seed-tnf":
        print(json.dumps(ensure_tnf_shortcut(), indent=2))
        return 0
    if args.cmd == "local":
        from .us_locals import open_local, roster_board

        roster_board()
        report = open_local(
            args.network,
            market=args.market,
            prefer_west_coast=True if args.west else None,
            instance_id=args.instance,
            open_player=not args.no_open,
        )
        print(json.dumps(report, indent=2))
        return 0 if report.get("ok") else 2
    if args.cmd == "recover":
        from .streamers_recover import recover_loop

        report = recover_loop(args.instance, goal=args.goal, max_steps=args.steps)
        print(json.dumps(report, indent=2))
        return 0 if report.get("ok") else 2
    if args.cmd == "heartbeat-fix":
        from .heartbeat_fix import fix_instance_if_failing

        report = fix_instance_if_failing(args.instance, force=bool(args.force))
        print(json.dumps(report, indent=2))
        return 0 if report.get("ok") or report.get("skipped") else 2
    if args.cmd == "snap":
        from .streamers_recover import snapshot

        print(json.dumps(snapshot(args.instance), indent=2))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
