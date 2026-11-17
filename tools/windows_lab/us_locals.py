"""US ABC/CBS/NBC/FOX locals on Streamers — any DMA, used on purpose.

Streamers' US * SECTION groups expose every US affiliate. That is not a
fallback toy: it is how we diversify linear speech (accents, local news,
regional ads) and how we catch national feeds (Sunday FOX NFL) from a
market that actually carries the game.

Prefer big DMAs. Rotate markets across takes. Tag every open with
network + market + call_letters for the dataset.
"""

from __future__ import annotations

import json
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .config import ensure_data_layout
from .instances import adb, connect_adb, get_instance, launch_bluestacks, wait_for_adb
from .streamers_open import (
    DEFAULT_INSTANCE,
    _dump_ui,
    _tap_text,
    _texts,
    save_shortcut,
)

ET_TZ = ZoneInfo("America/New_York")
PT_TZ = ZoneInfo("America/Los_Angeles")

NETWORKS = ("ABC", "CBS", "NBC", "FOX")

SECTION_FOR = {
    "ABC": "US ABC SECTION",
    "CBS": "US CBS SECTION",
    "NBC": "US NBC SECTION",
    "FOX": "US FOX SECTION",
}

# Shortcut / job tokens → FLAGSHIPS market names (FOX_NY, CBS_LA, …).
MARKET_TOKENS: dict[str, str] = {
    "NY": "New York",
    "NYC": "New York",
    "LA": "Los Angeles",
    "CHI": "Chicago",
    "DAL": "Dallas-Fort Worth",
    "DFW": "Dallas-Fort Worth",
    "ATL": "Atlanta",
    "BHM": "Birmingham",
    "PHL": "Philadelphia",
    "PHI": "Philadelphia",
    "HOU": "Houston",
    "BOS": "Boston",
    "SF": "San Francisco",
    "DC": "Washington DC",
    "WASH": "Washington DC",
}

# Reverse: market name → short token used in shortcut ids.
MARKET_TO_TOKEN: dict[str, str] = {
    "New York": "NY",
    "Los Angeles": "LA",
    "Chicago": "CHI",
    "Dallas-Fort Worth": "DAL",
    "Atlanta": "ATL",
    "Birmingham": "BHM",
    "Philadelphia": "PHL",
    "Houston": "HOU",
    "Boston": "BOS",
    "San Francisco": "SF",
    "Washington DC": "DC",
}

# Big-DMA flagships (call letters Streamers titles usually include).
# Order = default preference. Rotate via pick_local().
FLAGSHIPS: dict[str, tuple[dict[str, str], ...]] = {
    "ABC": (
        {"market": "New York", "state": "NY", "calls": "WABC", "city": "NEW YORK"},
        {"market": "Los Angeles", "state": "CA", "calls": "KABC", "city": "Los Angeles"},
        {"market": "Chicago", "state": "IL", "calls": "WLS", "city": "Chicago"},
        {"market": "Dallas-Fort Worth", "state": "TX", "calls": "WFAA", "city": "Dallas"},
        {"market": "Atlanta", "state": "GA", "calls": "WSB", "city": "Atlanta"},
        {"market": "Birmingham", "state": "AL", "calls": "WBMA", "city": "Birmingham"},
        {"market": "Philadelphia", "state": "PA", "calls": "WPVI", "city": "Philadelphia"},
        {"market": "Houston", "state": "TX", "calls": "KTRK", "city": "Houston"},
        {"market": "Boston", "state": "MA", "calls": "WCVB", "city": "Boston"},
        {"market": "San Francisco", "state": "CA", "calls": "KGO", "city": "San Francisco"},
        {"market": "Washington DC", "state": "DC", "calls": "WJLA", "city": "WASHINGTON"},
    ),
    "CBS": (
        {"market": "New York", "state": "NY", "calls": "WCBS", "city": "NEW YORK"},
        {"market": "Los Angeles", "state": "CA", "calls": "KCBS", "city": "Los Angeles"},
        {"market": "Chicago", "state": "IL", "calls": "WBBM", "city": "Chicago"},
        {"market": "Dallas-Fort Worth", "state": "TX", "calls": "KTVT", "city": "Dallas"},
        {"market": "Atlanta", "state": "GA", "calls": "WANF", "city": "Atlanta"},
        {"market": "Birmingham", "state": "AL", "calls": "WIAT", "city": "Birmingham"},
        {"market": "Philadelphia", "state": "PA", "calls": "KYW", "city": "Philadelphia"},
        {"market": "Houston", "state": "TX", "calls": "KHOU", "city": "Houston"},
        {"market": "Boston", "state": "MA", "calls": "WBZ", "city": "Boston"},
        {"market": "San Francisco", "state": "CA", "calls": "KPIX", "city": "San Francisco"},
        {"market": "Washington DC", "state": "DC", "calls": "WUSA", "city": "WASHINGTON"},
    ),
    "NBC": (
        {"market": "New York", "state": "NY", "calls": "WNBC", "city": "NEW YORK"},
        {"market": "Los Angeles", "state": "CA", "calls": "KNBC", "city": "Los Angeles"},
        {"market": "Chicago", "state": "IL", "calls": "WMAQ", "city": "Chicago"},
        {"market": "Dallas-Fort Worth", "state": "TX", "calls": "KXAS", "city": "Dallas"},
        {"market": "Atlanta", "state": "GA", "calls": "WXIA", "city": "Atlanta"},
        {"market": "Birmingham", "state": "AL", "calls": "WVTM", "city": "Birmingham"},
        {"market": "Philadelphia", "state": "PA", "calls": "WCAU", "city": "Philadelphia"},
        {"market": "Houston", "state": "TX", "calls": "KPRC", "city": "Houston"},
        {"market": "Boston", "state": "MA", "calls": "WBTS", "city": "Boston"},
        {"market": "San Francisco", "state": "CA", "calls": "KNTV", "city": "San Jose"},
        {"market": "Washington DC", "state": "DC", "calls": "WRC", "city": "WASHINGTON"},
    ),
    "FOX": (
        {"market": "New York", "state": "NY", "calls": "WNYW", "city": "NEW YORK"},
        {"market": "Los Angeles", "state": "CA", "calls": "KTTV", "city": "Los Angeles"},
        {"market": "Chicago", "state": "IL", "calls": "WFLD", "city": "Chicago"},
        {"market": "Dallas-Fort Worth", "state": "TX", "calls": "KDFW", "city": "Dallas"},
        {"market": "Atlanta", "state": "GA", "calls": "WAGA", "city": "Atlanta"},
        {"market": "Birmingham", "state": "AL", "calls": "WBRC", "city": "Birmingham"},
        {"market": "Philadelphia", "state": "PA", "calls": "WTXF", "city": "Philadelphia"},
        {"market": "Houston", "state": "TX", "calls": "KRIV", "city": "Houston"},
        {"market": "Boston", "state": "MA", "calls": "WFXT", "city": "Boston"},
        {"market": "San Francisco", "state": "CA", "calls": "KTVU", "city": "Oakland"},
        {"market": "Washington DC", "state": "DC", "calls": "WTTG", "city": "WASHINGTON"},
    ),
}

# West-coast markets — use when ET daypart is done but PT still has morning/late news.
WEST_COAST_MARKETS = frozenset({"Los Angeles", "San Francisco"})

# Home booth preference: Atlanta flagships, Alabama (Birmingham) when Atlanta lags.
HOME_MARKET = "Atlanta"
FAILOVER_MARKET = "Birmingham"  # Alabama
HOME_FAILOVER: dict[str, dict[str, dict[str, str]]] = {
    "ABC": {
        "home": {"market": "Atlanta", "state": "GA", "calls": "WSB", "city": "Atlanta"},
        "failover": {"market": "Birmingham", "state": "AL", "calls": "WBMA", "city": "Birmingham"},
    },
    "CBS": {
        "home": {"market": "Atlanta", "state": "GA", "calls": "WANF", "city": "Atlanta"},
        "failover": {"market": "Birmingham", "state": "AL", "calls": "WIAT", "city": "Birmingham"},
    },
    "NBC": {
        "home": {"market": "Atlanta", "state": "GA", "calls": "WXIA", "city": "Atlanta"},
        "failover": {"market": "Birmingham", "state": "AL", "calls": "WVTM", "city": "Birmingham"},
    },
    "FOX": {
        "home": {"market": "Atlanta", "state": "GA", "calls": "WAGA", "city": "Atlanta"},
        "failover": {"market": "Birmingham", "state": "AL", "calls": "WBRC", "city": "Birmingham"},
    },
}


def network_from_channel_id(channel_id: str | None) -> str | None:
    """Map job channel_id / shortcut to ABC|CBS|NBC|FOX when it is a local net."""
    raw = (channel_id or "").upper()
    for net in NETWORKS:
        if raw.startswith(net) or f"_{net}_" in f"_{raw}_" or raw.endswith(f"_{net}"):
            return net
    return None


def preferred_local(
    network: str,
    *,
    failover: bool = False,
) -> dict[str, Any]:
    """Atlanta home affiliate, or Birmingham (Alabama) failover — never Pluto/Max."""
    net = network.upper().strip()
    if net not in HOME_FAILOVER:
        raise ValueError(f"unknown network: {network}")
    which = "failover" if failover else "home"
    row = HOME_FAILOVER[net][which]
    return {
        "network": net,
        "section": SECTION_FOR[net],
        **row,
        "shortcut_id": f"{net}_LOCAL",
        "why": f"{which}_market={row['market']}",
        "role": which,
    }


def _now_et() -> datetime:
    return datetime.now(ET_TZ)


def rotation_path(root: Path | None = None) -> Path:
    return ensure_data_layout(root) / "indexes" / "us_locals_rotation.json"


def load_rotation(root: Path | None = None) -> dict[str, Any]:
    path = rotation_path(root)
    if not path.is_file():
        return {"version": 1, "next_index": {}, "history": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"version": 1, "next_index": {}, "history": []}


def save_rotation(data: dict[str, Any], root: Path | None = None) -> Path:
    path = rotation_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return path


def parse_local_title(title: str) -> dict[str, str] | None:
    """Parse Streamers local titles like 'NY | NEW YORK | CBS - WCBS' / 'CA | Los Angeles | FOX KTTV'."""
    t = (title or "").strip()
    if not t or "no event available" in t.lower():
        return None
    m = re.match(
        r"^([A-Z]{2})\s*\|\s*([^|]+)\|\s*(ABC|CBS|NBC|FOX)\s*[- ]\s*([A-Z0-9-]{3,8})\b",
        t,
        re.I,
    )
    if m:
        return {
            "state": m.group(1).upper(),
            "city": m.group(2).strip(),
            "network": m.group(3).upper(),
            "calls": m.group(4).upper().split("-")[0],
            "title": t,
        }
    m2 = re.search(r"\b(ABC|CBS|NBC|FOX)\s*[- ]\s*([A-Z]{3,5})\b", t, re.I)
    if m2:
        return {
            "state": "",
            "city": "",
            "network": m2.group(1).upper(),
            "calls": m2.group(2).upper(),
            "title": t,
        }
    m3 = re.search(r"\b(ABC|CBS|NBC|FOX)\s+([A-Z]{3,5})\b", t, re.I)
    if m3:
        return {
            "state": "",
            "city": "",
            "network": m3.group(1).upper(),
            "calls": m3.group(2).upper(),
            "title": t,
        }
    return None


def _expand_market_query(market: str) -> str:
    raw = str(market or "").strip()
    if not raw:
        return raw
    tok = MARKET_TOKENS.get(raw.upper())
    return tok or raw


def market_token(market: str) -> str | None:
    m = _expand_market_query(market)
    if m in MARKET_TO_TOKEN:
        return MARKET_TO_TOKEN[m]
    for name, tok in MARKET_TO_TOKEN.items():
        if name.lower() == m.lower():
            return tok
    return None


def pick_local(
    network: str,
    *,
    prefer_west_coast: bool | None = None,
    market: str | None = None,
    shortcut_id: str | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Choose the next purposeful affiliate for this network."""
    net = network.upper().strip()
    if net not in FLAGSHIPS:
        raise ValueError(f"unknown network: {network}")
    roster = list(FLAGSHIPS[net])
    if market:
        want = _expand_market_query(market)
        wlow = want.lower()
        for row in roster:
            if (
                row["market"].lower() == wlow
                or wlow in row["city"].lower()
                or row["state"].lower() == wlow
                or row["calls"].lower() == wlow
            ):
                tok = market_token(row["market"])
                sid = shortcut_id or (f"{net}_{tok}" if tok else f"{net}_LOCAL")
                return {
                    "network": net,
                    "section": SECTION_FOR[net],
                    **row,
                    "shortcut_id": sid,
                    "why": f"explicit_market={market}",
                }
        raise KeyError(f"market not in {net} roster: {market}")

    et = _now_et()
    if prefer_west_coast is None:
        # After ~1pm ET, West Coast still has morning; after 11pm ET, PT late news.
        prefer_west_coast = et.hour >= 13 or et.hour >= 23 or et.hour < 2

    rot = load_rotation(root)
    idx_map = dict(rot.get("next_index") or {})
    start = int(idx_map.get(net) or 0) % len(roster)

    ordered = roster[start:] + roster[:start]
    if prefer_west_coast:
        west = [r for r in ordered if r["market"] in WEST_COAST_MARKETS]
        east = [r for r in ordered if r["market"] not in WEST_COAST_MARKETS]
        ordered = west + east

    chosen = ordered[0]
    # Advance rotation for next take on this network.
    next_i = (roster.index(chosen) + 1) % len(roster)
    idx_map[net] = next_i
    hist = list(rot.get("history") or [])
    hist.append(
        {
            "utc": datetime.now(timezone.utc).isoformat(),
            "network": net,
            "market": chosen["market"],
            "calls": chosen["calls"],
            "prefer_west_coast": prefer_west_coast,
        }
    )
    rot["next_index"] = idx_map
    rot["history"] = hist[-80:]
    save_rotation(rot, root)

    why = "rotate"
    if prefer_west_coast and chosen["market"] in WEST_COAST_MARKETS:
        why = "west_coast_daypart_extend"
    return {
        "network": net,
        "section": SECTION_FOR[net],
        **chosen,
        "shortcut_id": shortcut_id or f"{net}_LOCAL",
        "why": why,
    }


def resolve_local_pick(
    shortcut_id: str | None = None,
    *,
    row: dict[str, Any] | None = None,
    channel_id: str | None = None,
    root: Path | None = None,
) -> dict[str, Any] | None:
    """Map shortcut/job id → parent section + child affiliate (or None if not a local).

    Prefer parent→child under US * SECTION. Ids like FOX_NY / CBS_LA encode
    network + market; *_LOCAL and kind=local rows use stored calls/market.
    """
    sid = str(shortcut_id or channel_id or "").strip().upper()
    row = row or {}
    open_meta = row.get("open") if isinstance(row.get("open"), dict) else {}

    def _from_parts(
        net: str,
        *,
        market: str | None = None,
        calls: str | None = None,
        sid_out: str | None = None,
        why: str = "resolved_local",
    ) -> dict[str, Any] | None:
        net_u = net.upper().strip()
        if net_u not in FLAGSHIPS:
            return None
        if market or calls:
            try:
                pick = pick_local(
                    net_u,
                    market=str(market or calls or ""),
                    shortcut_id=sid_out or sid or None,
                    root=root,
                )
            except Exception:
                pick = None
            if pick:
                pick["why"] = why
                return pick
        # Fall back to first flagship when only network is known.
        try:
            pick = pick_local(net_u, market=FLAGSHIPS[net_u][0]["market"], shortcut_id=sid_out or sid or None, root=root)
            pick["why"] = why
            return pick
        except Exception:
            return None

    # FOX_NY / CBS_LA / NBC_LOCAL / …
    m = re.fullmatch(r"(ABC|CBS|NBC|FOX)_([A-Z0-9]+)", sid)
    if m:
        net, tok = m.group(1), m.group(2)
        if tok == "LOCAL":
            market = (
                open_meta.get("market")
                or row.get("market")
                or None
            )
            calls = open_meta.get("calls") or row.get("search_query")
            title = str(row.get("channel_title") or "")
            parsed = parse_local_title(title) if title else None
            if parsed and not market:
                market = parsed.get("city") or None
            if parsed and not calls:
                calls = parsed.get("calls")
            if market or calls:
                return _from_parts(net, market=market, calls=calls, sid_out=sid, why="local_shortcut_row")
            # Rotating *_LOCAL stays section-first via open_local(network).
            return {
                "network": net,
                "section": SECTION_FOR[net],
                "market": None,
                "calls": None,
                "state": None,
                "city": None,
                "shortcut_id": sid,
                "why": "local_rotate",
                "rotate": True,
            }
        market = MARKET_TOKENS.get(tok) or tok
        return _from_parts(net, market=market, sid_out=sid, why=f"id_token={tok}")

    # Row stamped as local / US * SECTION child.
    kind = str(row.get("kind") or "")
    group = str(row.get("group") or open_meta.get("section") or "")
    method = str(open_meta.get("method") or "")
    is_local = (
        kind == "local"
        or method in ("us_section_grouper", "section_child")
        or group in SECTION_FOR.values()
        or group.endswith(" SECTION")
        and any(n in group for n in NETWORKS)
    )
    if not is_local:
        return None
    net = str(open_meta.get("network") or "").upper()
    if not net:
        for n, section in SECTION_FOR.items():
            if group == section or n in group:
                net = n
                break
    if not net:
        parsed = parse_local_title(str(row.get("channel_title") or ""))
        if parsed:
            net = str(parsed.get("network") or "")
    if not net:
        return None
    return _from_parts(
        net,
        market=str(open_meta.get("market") or row.get("market") or "") or None,
        calls=str(open_meta.get("calls") or row.get("search_query") or "") or None,
        sid_out=sid or str(row.get("id") or f"{net}_LOCAL"),
        why="row_section_child",
    )


def dataset_tags(pick: dict[str, Any], *, channel_title: str | None = None) -> dict[str, Any]:
    """Tags to stamp on sessions / schedule jobs for corpus diversity."""
    parsed = parse_local_title(channel_title or "") if channel_title else None
    return {
        "source_kind": "streamers_us_local",
        "network": pick.get("network"),
        "market": pick.get("market"),
        "state": pick.get("state"),
        "call_letters": pick.get("calls"),
        "section": pick.get("section"),
        "channel_title": channel_title,
        "parsed": parsed,
        "diversity": "multi_dma_linear",
    }


def _on_guide_rail(texts: list[str]) -> bool:
    if any(t.endswith("SECTION") for t in texts):
        return True
    if "Favorites" in texts or "All channels" in texts:
        return True
    if any(t.startswith("US ") for t in texts):
        return True
    return False


def _in_pack_epg(texts: list[str]) -> bool:
    """Sports/Pluto/Tubi grids that hide Favorites / All channels / US * SECTION."""
    if _on_guide_rail(texts):
        return False
    joined = " ".join(texts).upper()
    needles = (
        "PLUTO",
        "TUBI",
        "FLSP",
        "SPORTSNET",
        "TSN+",
        "MAX SPORTS",
        "AMZN",
        "ROKU TV",
        "ESPN+",
        "ESPN PLUS",
        "ESPN UNLIMITED",
    )
    return any(n in joined for n in needles)


def _ensure_guide(instance: dict[str, Any], probe: Path) -> ET.Element:
    """Leave sports-event EPGs / players and land on the All-channels rail.

    Heartbeat fix needs US ABC/CBS/NBC/FOX SECTION — not SN+/FLSP/Pluto grids.
    Pack EPGs often have no rail labels; caller falls back to call-letter search.
    """
    ui = _dump_ui(instance, probe / "local_home.xml")
    texts = _texts(ui)
    if _on_guide_rail(texts):
        return ui
    for i in range(5):
        # Prefer explicit TV guide chrome when visible.
        if any(t.lower() == "tv guide" or t.lower() == "guide" for t in texts):
            try:
                _tap_text(instance, ui, "TV guide")
            except Exception:
                try:
                    _tap_text(instance, ui, "Guide")
                except Exception:
                    adb(instance, ["shell", "input", "keyevent", "4"])
        else:
            adb(instance, ["shell", "input", "keyevent", "4"])
        time.sleep(0.9)
        ui = _dump_ui(instance, probe / f"local_home_{i}.xml")
        texts = _texts(ui)
        if _on_guide_rail(texts):
            return ui
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
            adb(instance, ["shell", "input", "keyevent", "4"])
            time.sleep(1.0)
            ui = _dump_ui(instance, probe / "local_home.xml")
            texts = _texts(ui)
            if _on_guide_rail(texts):
                return ui
        # Pack EPG (ESPN+/Pluto/…) — keep BACKing for rail; do not stop early.
        # Stopping here forced calls_search, which leaves search_ui with no hit.
        if _in_pack_epg(texts) and not _on_guide_rail(texts):
            continue
    return ui


def _open_section(instance: dict[str, Any], section: str, probe: Path) -> ET.Element:
    ui = _ensure_guide(instance, probe)
    texts = _texts(ui)
    # Inside a single US * SECTION channel grid the left rail is hidden — BACK out
    # until Favorites/All channels (or the target section chip) is visible.
    # Without this, open_home_local falsely "succeeds" staying on ABC while asking for FOX.
    for _ in range(8):
        on_rail = "All channels" in texts or "Favorites" in texts
        only_current = (
            any(t.endswith("SECTION") for t in texts)
            and not on_rail
            and section not in texts
        )
        if on_rail or section in texts:
            break
        if only_current or _in_pack_epg(texts) or any(t.endswith("SECTION") for t in texts):
            adb(instance, ["shell", "input", "keyevent", "4"])
            time.sleep(0.55)
            ui = _dump_ui(instance, probe / "local_back.xml")
            texts = _texts(ui)
            continue
        break
    # Scroll the left rail WHILE Favorites/All channels are still in the dump.
    # Tapping All channels often focuses the pack grid and drops rail labels from
    # accessibility — then swipes only scroll ESPN+ rows and never find US ABC.
    if section not in texts and ("All channels" in texts or "Favorites" in texts):
        for _ in range(24):
            if section in texts:
                break
            adb(instance, ["shell", "input", "swipe", "180", "780", "180", "250", "450"])
            time.sleep(0.45)
            ui = _dump_ui(instance, probe / "local_rail_pre.xml")
            texts = _texts(ui)
            if "All channels" not in texts and "Favorites" not in texts:
                # Lost rail — BACK once and continue.
                adb(instance, ["shell", "input", "keyevent", "4"])
                time.sleep(0.5)
                ui = _dump_ui(instance, probe / "local_rail_re.xml")
                texts = _texts(ui)
    # Prefer All channels once the target chip is visible (or as last rail focus).
    if "All channels" in texts and section in texts:
        _tap_text(instance, ui, "All channels")
        time.sleep(0.7)
        ui = _dump_ui(instance, probe / "local_all.xml")
        texts = _texts(ui)
    elif "All channels" in texts and section not in texts:
        _tap_text(instance, ui, "All channels")
        time.sleep(1.0)
        ui = _dump_ui(instance, probe / "local_all.xml")
        texts = _texts(ui)
    if section not in texts:
        can_scroll_rail = "All channels" in texts or "Favorites" in texts
        scrolls = 22 if can_scroll_rail else 0
        if not can_scroll_rail and (_in_pack_epg(texts) or any(t.endswith("SECTION") for t in texts)):
            # One more BACK to restore rail labels, then scroll.
            adb(instance, ["shell", "input", "keyevent", "4"])
            time.sleep(0.6)
            ui = _dump_ui(instance, probe / "local_rail_rescue.xml")
            texts = _texts(ui)
            can_scroll_rail = "All channels" in texts or "Favorites" in texts
            scrolls = 22 if can_scroll_rail else 0
        if not can_scroll_rail and section not in texts:
            raise RuntimeError(f"section not in rail: {section}; seen={texts[:25]}")
        empty_streak = 0
        for _ in range(scrolls):
            adb(instance, ["shell", "input", "swipe", "180", "780", "180", "250", "450"])
            time.sleep(0.5)
            ui = _dump_ui(instance, probe / "local_rail.xml")
            texts = _texts(ui)
            if not texts:
                empty_streak += 1
                if empty_streak >= 3:
                    raise RuntimeError(
                        f"section not in rail: {section}; empty_ui_dumps={empty_streak}"
                    )
                continue
            empty_streak = 0
            if section in texts:
                break
        if section not in texts:
            raise RuntimeError(f"section not in rail: {section}; seen={texts[:25]}")
    _tap_text(instance, ui, section)
    time.sleep(1.2)
    return _dump_ui(instance, probe / "local_section.xml")


def _score_local_search_title(title: str, *, calls: str, network: str, city: str) -> int:
    """Rank Channels-tab hits; reject Pluto/Tubi and near-miss call letters (WSBT)."""
    t = (title or "").strip()
    if not t:
        return -10_000
    tl = t.lower()
    if any(
        bad in tl
        for bad in (
            "pluto",
            "tubi",
            "roku",
            "freevee",
            "max sports",
            "espn+",
            "espn plus",
            "espn unlimited",
            "espnu",
        )
    ):
        return -10_000
    calls_u = calls.upper()
    net_u = network.upper()
    # Search-field / history chip alone is not a channel row.
    if t.upper().strip() == calls_u:
        return -10_000
    # Exact call token (WSB not WSBT / WSBK).
    if not re.search(rf"(?<![A-Z]){re.escape(calls_u)}(?![A-Z])", t.upper()):
        return -10_000
    score = 50
    if net_u in t.upper():
        score += 40
    city_u = (city or "").upper()
    if city_u and city_u in t.upper():
        score += 40
    parsed = parse_local_title(t)
    if parsed and parsed.get("calls") == calls_u and parsed.get("network") == net_u:
        score += 30
    if " | " in t:
        score += 10
    return score


def _open_via_calls_search(
    instance: dict[str, Any],
    pick: dict[str, Any],
    probe: Path,
    *,
    open_player: bool = True,
) -> dict[str, Any]:
    """When the grouper rail is hidden (Pluto / SN+ / FLSP), open via call-letter search.

    Still targets the Atlanta/Alabama affiliate title (e.g. GA | Atlanta | ABC WSB),
    never Pluto fillers. After open, player chrome shows US * SECTION context.
    """
    from .streamers_open import (
        _clear_search_field,
        _open_search_via_longpress,
        _type_search_query,
    )

    ui = _dump_ui(instance, probe / "calls_home.xml")
    texts = _texts(ui)
    if "Search history" not in texts and "Channels" not in texts:
        opened = _open_search_via_longpress(instance, ui, probe)
        if not opened.get("ok"):
            # Narrow pack-title column (x≈300) — long-press filter used to skip these.
            adb(instance, ["shell", "input", "swipe", "300", "450", "300", "450", "3000"])
            time.sleep(1.6)
            menu = _dump_ui(instance, probe / "calls_lp_menu.xml")
            if "Search" not in _texts(menu):
                return {
                    "ok": False,
                    "error": "calls_search_no_menu",
                    "longpress": opened,
                    "via": "calls_search",
                }
            _tap_text(instance, menu, "Search")
            time.sleep(0.9)
            ui = _dump_ui(instance, probe / "calls_search.xml")
        else:
            ui = opened["ui"]

    calls = str(pick["calls"])
    _clear_search_field(instance, ui)
    _type_search_query(instance, calls)
    adb(instance, ["shell", "input", "keyevent", "66"])
    time.sleep(2.2)
    ui = _dump_ui(instance, probe / "calls_results.xml")
    texts = _texts(ui)
    if "Channels" in texts:
        _tap_text(instance, ui, "Channels")
        time.sleep(1.0)
        ui = _dump_ui(instance, probe / "calls_channels.xml")
        texts = _texts(ui)

    ranked = [
        (_score_local_search_title(t, calls=calls, network=str(pick["network"]), city=str(pick.get("city") or "")), t)
        for t in texts
    ]
    ranked = [(s, t) for s, t in ranked if s >= 50]
    if not ranked:
        return {
            "ok": False,
            "error": f"calls_search_no_hit:{calls}",
            "titles": texts[:30],
            "via": "calls_search",
        }
    score, title = max(ranked, key=lambda x: x[0])
    if not _tap_text(instance, ui, title, contains=True):
        return {"ok": False, "error": f"could not tap {title}", "via": "calls_search"}
    time.sleep(0.5)
    player_texts: list[str] = []
    opened = False
    if open_player:
        adb(instance, ["shell", "input", "keyevent", "23"])
        time.sleep(2.5)
        player_texts = _texts(_dump_ui(instance, probe / "calls_player.xml"))
        opened = True
    return {
        "ok": True,
        "selected_title": title,
        "opened": opened,
        "player_texts": player_texts[:25],
        "via": "calls_search",
        "score": score,
    }


def _find_row(
    ui: ET.Element,
    *,
    calls: str,
    city: str,
    network: str,
) -> tuple[str, int, int, int, int] | None:
    """Pick the section child row. Calls must match — city/network alone is not enough
    (that was tapping WBNG/neighbors when hunting WCBS)."""
    calls_u = calls.upper().strip()
    city_u = (city or "").upper()
    net_u = network.upper()
    if not calls_u:
        return None
    best: tuple[int, str, int, int, int, int] | None = None
    for node in ui.iter("node"):
        t = (node.attrib.get("text") or "").strip()
        b = node.attrib.get("bounds") or ""
        if not t or not b:
            continue
        parsed = parse_local_title(t)
        if not parsed:
            continue
        if parsed["network"] != net_u:
            continue
        got_calls = str(parsed.get("calls") or "").upper()
        # Exact call letters only — never city-only (WBNG vs WCBS).
        tokens = re.findall(r"[A-Z0-9]{3,8}", t.upper())
        if got_calls != calls_u and calls_u not in tokens:
            continue
        m = re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", b)
        if not m:
            continue
        x1, y1, x2, y2 = map(int, m.groups())
        if y1 < 350 or x2 < 500:
            continue
        score = 100
        if city_u and city_u in (parsed.get("city") or "").upper():
            score += 40
        cand = (score, t, x1, y1, x2, y2)
        if best is None or cand[0] > best[0]:
            best = cand
    if not best:
        return None
    _, t, x1, y1, x2, y2 = best
    return t, x1, y1, x2, y2


def _visible_state_letters(ui: ET.Element) -> list[str]:
    """State prefixes on affiliate rows (NY|, GA|, …) — children sort A→Z by these."""
    letters: list[str] = []
    for node in ui.iter("node"):
        t = (node.attrib.get("text") or "").strip()
        parsed = parse_local_title(t)
        if not parsed:
            continue
        st = str(parsed.get("state") or "").strip().upper()
        if len(st) >= 1:
            letters.append(st[0])
    return letters


def _scroll_section_for_child(
    instance: dict[str, Any],
    ui: ET.Element,
    probe: Path,
    *,
    pick: dict[str, Any],
) -> tuple[tuple[str, int, int, int, int] | None, ET.Element]:
    """Parent section is open; hunt the child in alphabetical grid order.

    US * SECTION rows are usually ``ST | CITY | NET - CALLS``. Jump toward A,
    then scroll toward Z until calls/city match (same idea as ESPN child scroll).
    """
    calls = str(pick.get("calls") or "")
    city = str(pick.get("city") or "")
    network = str(pick.get("network") or "")
    want_letter = str(pick.get("state") or market_token(str(pick.get("market") or "")) or "A")[:1].upper()

    row = _find_row(ui, calls=calls, city=city, network=network)
    if row:
        return row, ui

    # Jump toward top of section (A…).
    for i in range(6):
        adb(instance, ["shell", "input", "swipe", "900", "280", "900", "820", "380"])
        time.sleep(0.35 + i * 0.02)
    ui = _dump_ui(instance, probe / "local_alpha_top.xml")
    row = _find_row(ui, calls=calls, city=city, network=network)
    if row:
        return row, ui

    # Scroll toward Z; nudge back if visible states overshoot the target letter.
    for attempt in range(28):
        letters = _visible_state_letters(ui)
        row = _find_row(ui, calls=calls, city=city, network=network)
        if row:
            return row, ui
        if letters and all(L > want_letter for L in letters) and attempt > 2:
            adb(instance, ["shell", "input", "swipe", "900", "320", "900", "780", "400"])
            time.sleep(0.55)
            ui = _dump_ui(instance, probe / "local_alpha_back.xml")
            row = _find_row(ui, calls=calls, city=city, network=network)
            if row:
                return row, ui
        adb(instance, ["shell", "input", "swipe", "900", "820", "900", "320", "420"])
        time.sleep(0.55)
        ui = _dump_ui(instance, probe / f"local_alpha_{attempt}.xml")
    return _find_row(ui, calls=calls, city=city, network=network), ui


def open_home_local(
    network: str,
    *,
    failover: bool = False,
    instance_id: str = DEFAULT_INSTANCE,
    open_player: bool = True,
    save: bool = True,
    root: Path | None = None,
) -> dict[str, Any]:
    """Booth/heartbeat path: Atlanta affiliate, or Birmingham (AL) on failover.

    Never Pluto / Max / free ad junk — US * SECTION grouper only.
    """
    return open_local(
        network,
        market=(FAILOVER_MARKET if failover else HOME_MARKET),
        prefer_west_coast=False,
        instance_id=instance_id,
        open_player=open_player,
        save=save,
        root=root,
    )


_NFL_LIVE_RE = re.compile(r"\bNFL\s+Football\b|\bNFL\s*:", re.I)
_SPORTS_LIVE_RE = re.compile(
    r"\bNFL\s+Football\b|\bCollege Football\b|\bNBA\b|\bNHL\b|\bUFC\b",
    re.I,
)
# Booth home region: use the guide, but stay on GA/AL affiliates (not AK filler, not
# Atlanta flagship when neighbors carry the game).
HOME_SPORTS_STATES = ("GA", "AL")
_SE_NEIGHBOR_STATES = frozenset({"FL", "SC", "TN", "MS", "NC"})
_FAR_FILLER_STATES = frozenset({"AK", "HI", "WA", "OR", "CA", "NV", "AZ", "ID", "MT"})


def _guide_rows_with_bounds(ui: ET.Element) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for node in ui.iter("node"):
        t = (node.attrib.get("text") or "").strip()
        b = node.attrib.get("bounds") or ""
        if not t or not b:
            continue
        m = re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", b)
        if not m:
            continue
        x1, y1, x2, y2 = map(int, m.groups())
        rows.append({"text": t, "x1": x1, "y1": y1, "x2": x2, "y2": y2})
    rows.sort(key=lambda r: (r["y1"], r["x1"]))
    return rows


def _find_live_sports_station(
    ui: ET.Element,
    *,
    network: str,
    avoid_program_keys: set[str] | None = None,
    prefer_states: tuple[str, ...] | None = None,
    require_prefer_states: bool = False,
) -> tuple[str, str, int, int, int, int] | None:
    """Find a US * SECTION station whose *now* cell is live NFL/CFB (not Opry/news).

    Uses the guide cell, not the channel name. Prefer GA/AL (booth region); skip
    Atlanta flagship when neighbors carry the game; do not grab AK just because
    the section scrolls from A.
    """
    from .stream_status import normalize_program_key

    net_u = network.upper()
    prefer = {s.upper() for s in (prefer_states or HOME_SPORTS_STATES)}
    avoid = {str(x).lower() for x in (avoid_program_keys or set()) if x}
    rows = _guide_rows_with_bounds(ui)
    best: tuple[int, str, str, int, int, int, int] | None = None
    for i, row in enumerate(rows):
        prog = row["text"]
        if not _SPORTS_LIVE_RE.search(prog):
            continue
        if re.search(r"\bopry\b|\bno information\b|\bpaid programming\b", prog, re.I):
            continue
        pk = normalize_program_key(prog) or ""
        if pk and pk in avoid:
            continue
        # Station title is usually the nearest prior row with NETWORK + calls.
        station = None
        parsed_st: dict[str, str] | None = None
        for j in range(i - 1, max(-1, i - 8), -1):
            parsed = parse_local_title(rows[j]["text"])
            if parsed and parsed.get("network") == net_u:
                station = rows[j]
                parsed_st = parsed
                break
        if not station or not parsed_st:
            continue
        state = str(parsed_st.get("state") or "").upper()
        city = str(parsed_st.get("city") or "").upper()
        if require_prefer_states and state not in prefer:
            continue
        # Prefer NFL over other sports; prefer GA/AL guide rows hard.
        score = 50
        if _NFL_LIVE_RE.search(prog):
            score += 100
        if "live" in prog.lower() or "ᴸ" in prog:
            score += 20
        if state in prefer:
            score += 500
            # Atlanta flagship airing sports is fine; still prefer other GA/AL
            # when tied so we rotate off WANF/WSB when possible.
            if "ATLANTA" in city:
                score -= 40
        elif state in _SE_NEIGHBOR_STATES:
            score += 80
        elif state in _FAR_FILLER_STATES:
            score -= 400
        # Tap the *program* now-cell (not the station label). Station labels sit
        # in a tight column; a slight miss selects the AK row above.
        cand = (
            score,
            station["text"],
            prog,
            row["x1"],
            row["y1"],
            row["x2"],
            row["y2"],
        )
        if best is None or cand[0] > best[0]:
            best = cand
    if not best:
        return None
    _, title, prog, x1, y1, x2, y2 = best
    return title, prog, x1, y1, x2, y2


def open_live_sports_local(
    network: str,
    *,
    instance_id: str = DEFAULT_INSTANCE,
    open_player: bool = True,
    avoid_program_keys: set[str] | None = None,
    prefer_states: tuple[str, ...] | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Open a *live sports* affiliate using the guide now-cell — prefer GA/AL.

    Scrolls US * SECTION for ``NFL Football`` / CFB on Georgia/Alabama rows first.
    Does not open Atlanta home when that cell is Opry/news.
    """
    root = ensure_data_layout(root)
    net = network.upper().strip()
    prefer = tuple(prefer_states or HOME_SPORTS_STATES)
    if net not in SECTION_FOR:
        return {"ok": False, "error": f"unknown_network:{network}"}
    section = SECTION_FOR[net]
    instance = get_instance(instance_id, root)
    launch_bluestacks(instance, launch_app=True)
    connect_adb(instance)
    if not wait_for_adb(instance, seconds=60):
        return {"ok": False, "error": "ADB not ready", "network": net}

    # Soft prep only — recover_loop can hang for minutes on a sticky dump.
    try:
        from .streamers_recover import snapshot

        snap = snapshot(instance_id)
        kind = str(snap.get("kind") or "")
        if kind in {"bluestacks_home", "login", "crash", "black", "unknown"}:
            from .streamers_recover import ensure_ready_for_open

            ensure_ready_for_open(instance_id, root=root)
    except Exception:
        pass

    probe = root / "work" / "capture" / "bluestacks_probe" / str(instance_id)
    probe.mkdir(parents=True, exist_ok=True)
    try:
        ui = _open_section(instance, section, probe)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"section_open:{exc}", "network": net}

    def _scroll_for(*, require_home: bool, scrolls: int, tag: str):
        nonlocal ui
        for scroll in range(scrolls):
            hit = _find_live_sports_station(
                ui,
                network=net,
                avoid_program_keys=avoid_program_keys,
                prefer_states=prefer,
                require_prefer_states=require_home,
            )
            if hit:
                return hit
            adb(instance, ["shell", "input", "swipe", "900", "780", "900", "360", "420"])
            time.sleep(0.55)
            ui = _dump_ui(instance, probe / f"{tag}_{scroll}.xml")
        return None

    # Pass 1: GA/AL only — scroll past AK filler until a home-region NFL cell.
    hit = _scroll_for(require_home=True, scrolls=24, tag="live_ga_al")
    # Pass 2: SE/any live NFL if no GA/AL row carried the game this pass.
    if not hit:
        try:
            ui = _open_section(instance, section, probe)
        except Exception:
            pass
        hit = _scroll_for(require_home=False, scrolls=16, tag="live_any")

    if not hit:
        return {
            "ok": False,
            "error": f"no_live_sports_in_{section}",
            "network": net,
            "via": "live_sports_section",
            "prefer_states": list(prefer),
        }

    title, prog, x1, y1, x2, y2 = hit
    cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
    adb(instance, ["shell", "input", "tap", str(cx), str(cy)])
    time.sleep(0.5)
    player_texts: list[str] = []
    if open_player:
        adb(instance, ["shell", "input", "keyevent", "23"])
        time.sleep(3.0)
        ui2 = _dump_ui(instance, probe / "live_player.xml")
        player_texts = _texts(ui2)

        def _still_on_chrome(texts: list[str]) -> bool:
            joined = " ".join(texts).lower()
            if "search history" in joined or "search" == (texts[0].lower() if texts else ""):
                return True
            if any(t.endswith("SECTION") for t in texts) and "Channels list" not in texts:
                return True
            if any(t.lower() == "channels list" for t in texts):
                return True
            return False

        # Still on section/search chrome → back out of search if needed, re-tap, center.
        if _still_on_chrome(player_texts):
            if any("search" in t.lower() for t in player_texts[:8]):
                adb(instance, ["shell", "input", "keyevent", "4"])
                time.sleep(0.6)
            adb(instance, ["shell", "input", "tap", str(cx), str(cy)])
            time.sleep(0.4)
            adb(instance, ["shell", "input", "keyevent", "23"])
            time.sleep(3.0)
            player_texts = _texts(_dump_ui(instance, probe / "live_player2.xml"))
        if _still_on_chrome(player_texts):
            adb(instance, ["shell", "input", "keyevent", "23"])
            time.sleep(3.0)
            player_texts = _texts(_dump_ui(instance, probe / "live_player3.xml"))

    from .stream_status import identity_from_texts, normalize_program_key, record

    playing = identity_from_texts(player_texts) if player_texts else {}
    play_title = str(playing.get("selected_title") or title)
    pk = playing.get("program_key") or normalize_program_key(prog)
    parsed = parse_local_title(play_title) or parse_local_title(title) or {}
    record(
        instance_id,
        event="channel_open",
        ok=True,
        detail=f"live_sports:{prog[:60]}",
        selected_title=play_title,
        via="live_sports_section",
        network=str(parsed.get("network") or net),
        market=str(parsed.get("city") or parsed.get("market") or ""),
        calls=str(parsed.get("calls") or ""),
        program_key=pk,
        program_title=prog,
        root=root,
        emit_farm_run=True,
    )
    return {
        "ok": True,
        "via": "live_sports_section",
        "network": str(parsed.get("network") or net),
        "selected_title": play_title,
        "channel_title": play_title,
        "program_title": prog,
        "program_key": pk,
        "calls": parsed.get("calls"),
        "pick": {
            "network": net,
            "section": section,
            "calls": parsed.get("calls"),
            "market": parsed.get("city"),
            "state": parsed.get("state"),
            "why": "guide_live_sports_ga_al",
        },
        "player_texts": player_texts[:20],
    }


def open_local(
    network: str,
    *,
    market: str | None = None,
    prefer_west_coast: bool | None = None,
    shortcut_id: str | None = None,
    pick: dict[str, Any] | None = None,
    instance_id: str = DEFAULT_INSTANCE,
    open_player: bool = True,
    save: bool = True,
    root: Path | None = None,
) -> dict[str, Any]:
    """Open a purposeful US local via US * SECTION (not movie search / Pluto)."""
    root = ensure_data_layout(root)
    if pick is not None:
        net = str(pick.get("network") or network).upper()
        pick = {
            "network": net,
            "section": pick.get("section") or SECTION_FOR.get(net),
            "market": pick.get("market"),
            "calls": pick.get("calls"),
            "state": pick.get("state") or "",
            "city": pick.get("city") or pick.get("market") or "",
            "shortcut_id": shortcut_id or pick.get("shortcut_id") or f"{net}_LOCAL",
            "why": pick.get("why") or "explicit_pick",
        }
    else:
        pick = pick_local(
            network,
            prefer_west_coast=prefer_west_coast,
            market=market,
            shortcut_id=shortcut_id,
            root=root,
        )
    instance = get_instance(instance_id, root)
    launch_bluestacks(instance, launch_app=True)
    connect_adb(instance)
    def _status_fail(error: str, *, via_s: str | None = None, title_s: str | None = None) -> dict[str, Any]:
        out = {
            "ok": False,
            "error": error,
            "pick": pick,
            "via": via_s,
            "selected_title": title_s,
            "channel_title": title_s,
        }
        try:
            from .stream_status import record

            record(
                instance_id,
                event="channel_open",
                ok=False,
                detail=error,
                intended={
                    "network": pick.get("network"),
                    "market": pick.get("market"),
                    "calls": pick.get("calls"),
                    "section": pick.get("section"),
                },
                selected_title=title_s,
                via=via_s,
                network=str(pick.get("network") or ""),
                market=str(pick.get("market") or ""),
                calls=str(pick.get("calls") or ""),
                root=root,
            )
        except Exception:
            pass
        return out

    if not wait_for_adb(instance, seconds=60):
        return _status_fail("ADB not ready")

    # Soft prep — never unconditional ensure_ready_for_open (that storms for
    # minutes on fullscreen empty dumps and kills Channel Olympics budget).
    try:
        from .streamers_recover import snapshot

        snap = snapshot(instance_id, root=root, take_frame=False)
        kind = str(snap.get("kind") or "")
        if kind in {
            "bluestacks_home",
            "welcome_login",
            "credentials_login",
            "service_list_login",
            "playlist_name_login",
            "overlay_permission",
            "crash",
            "black",
            "unknown_app",
        }:
            from .streamers_recover import ensure_ready_for_open

            ensure_ready_for_open(instance_id, root=root)
        elif kind in {"dump_dead", "player_fullscreen", "player_chrome", "player_or_blank"} or kind.startswith(
            "player_"
        ):
            for _ in range(2):
                adb(instance, ["shell", "input", "keyevent", "4"])
                time.sleep(0.35)
    except Exception:
        try:
            for _ in range(2):
                adb(instance, ["shell", "input", "keyevent", "4"])
                time.sleep(0.35)
        except Exception:
            pass

    probe = root / "work" / "capture" / "bluestacks_probe"
    via = "us_section_grouper"
    title: str | None = None
    opened = False
    player_texts: list[str] = []
    section_err: str | None = None

    try:
        ui = _open_section(instance, pick["section"], probe)
    except Exception as e:
        section_err = str(e)
        ui = None

    if ui is not None:
        # Children under the parent section are alphabetical (ST | CITY | …).
        row, ui = _scroll_section_for_child(instance, ui, probe, pick=pick)

        if row:
            title, x1, y1, x2, y2 = row
            cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
            adb(instance, ["shell", "input", "tap", str(cx), str(cy)])
            time.sleep(0.5)
            if open_player:
                adb(instance, ["shell", "input", "keyevent", "23"])
                time.sleep(2.0)
                ui2 = _dump_ui(instance, probe / "local_player.xml")
                player_texts = _texts(ui2)
                opened = True
        else:
            section_err = f"could not find {pick['calls']} in {pick['section']}"
            # One more chance: BACK to rail and reopen section (player/empty dump
            # often made the first hunt miss). Prefer this over calls_search.
            try:
                for _ in range(3):
                    adb(instance, ["shell", "input", "keyevent", "4"])
                    time.sleep(0.4)
                ui_retry = _open_section(instance, pick["section"], probe)
                row2, ui_retry = _scroll_section_for_child(
                    instance, ui_retry, probe, pick=pick
                )
                if row2:
                    title, x1, y1, x2, y2 = row2
                    cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
                    adb(instance, ["shell", "input", "tap", str(cx), str(cy)])
                    time.sleep(0.5)
                    if open_player:
                        adb(instance, ["shell", "input", "keyevent", "23"])
                        time.sleep(2.0)
                        player_texts = _texts(_dump_ui(instance, probe / "local_player_retry.xml"))
                        opened = True
                    section_err = None
                    via = "us_section_grouper_retry"
                    ui = ui_retry
            except Exception as exc:  # noqa: BLE001
                section_err = f"{section_err}; retry:{exc}"

    # Pack EPGs (Pluto / SN+ / FLSP) hide the grouper rail — open by call letters.
    # Never search while still on an empty fullscreen dump (nodes=48, no texts).
    if not title:
        rail_texts = _texts(ui) if ui is not None else []
        if not rail_texts or not _on_guide_rail(rail_texts):
            try:
                for _ in range(3):
                    adb(instance, ["shell", "input", "keyevent", "4"])
                    time.sleep(0.4)
                ui = _ensure_guide(instance, probe)
                rail_texts = _texts(ui)
            except Exception:
                rail_texts = []
        if not _on_guide_rail(rail_texts):
            return _status_fail(
                section_err or "section_miss_no_rail_for_search",
                via_s="us_section_grouper",
            ) | {"section_error": section_err, "lesson": "BACK to parent rail; refused calls_search on empty/player dump"}
        try:
            fb = _open_via_calls_search(instance, pick, probe, open_player=open_player)
        except Exception as exc:  # noqa: BLE001
            # uiautomator dump flakes must not kill desk/open-model retune loops.
            return _status_fail(
                f"calls_search_exception:{exc}",
                via_s="calls_search",
            ) | {"section_error": section_err}
        if not fb.get("ok"):
            return _status_fail(
                str(fb.get("error") or section_err or "open_local_failed"),
                via_s=str(fb.get("via") or via),
            ) | {"section_error": section_err, "seen": fb.get("titles")}
        title = str(fb.get("selected_title") or "")
        opened = bool(fb.get("opened"))
        player_texts = list(fb.get("player_texts") or [])
        via = str(fb.get("via") or "calls_search")

    # Post-open identity gate — must match what is *playing*, not just the tapped row.
    # (Tapping WXIA while still on WHAS previously returned ok and wasted a stream.)
    try:
        from .stream_status import identity_from_texts, verify_local_identity

        playing = identity_from_texts(player_texts)
        want_calls = str(pick["calls"]).upper()
        # If dump still lists guide neighbors, prefer a text that matches wanted calls.
        for t in player_texts:
            parsed = parse_local_title(t)
            if parsed and str(parsed.get("calls") or "").upper() == want_calls:
                playing = {
                    **playing,
                    "selected_title": parsed.get("title") or t,
                    "network": parsed.get("network"),
                    "calls": parsed.get("calls"),
                    "city": parsed.get("city"),
                }
                break
        play_title = str(playing.get("selected_title") or title or "")
        if playing.get("calls") and str(playing.get("calls")).upper() != want_calls:
            return _status_fail(
                f"landed_on_{playing.get('calls')}_wanted_{pick['calls']}",
                via_s=via,
                title_s=play_title,
            ) | {
                "identity": playing,
                "section_error": section_err,
                "wanted": pick.get("calls"),
            }
        if playing.get("network") and str(playing.get("network")).upper() != str(pick["network"]).upper():
            return _status_fail(
                f"landed_on_{playing.get('network')}_wanted_{pick['network']}",
                via_s=via,
                title_s=play_title,
            ) | {"identity": playing, "section_error": section_err}
        if play_title:
            title = play_title
        ident = verify_local_identity(
            title,
            network=str(pick["network"]),
            calls=str(pick["calls"]),
            city=str(pick.get("city") or ""),
            market=str(pick.get("market") or ""),
        )
    except Exception as exc:  # noqa: BLE001
        ident = {"ok": False, "error": f"identity_check_failed:{exc}", "root_cause": "unknown"}
    if not ident.get("ok"):
        return _status_fail(
            str(ident.get("error") or "wrong_channel"),
            via_s=via,
            title_s=title,
        ) | {"identity": ident, "section_error": section_err}

    tags = dataset_tags(pick, channel_title=title)
    channel_number = None
    try:
        from .guide_catalog import best_local, lookup

        hit = best_local(str(pick["network"]), market=str(pick.get("market") or "Atlanta"), root=root)
        if not hit or str(hit.get("calls") or "").upper() != str(pick["calls"]).upper():
            rows = lookup(
                calls=str(pick["calls"]),
                network=str(pick["network"]),
                market=str(pick.get("market") or ""),
                limit=1,
                root=root,
            )
            hit = rows[0] if rows else hit
        if hit and hit.get("number") is not None:
            channel_number = int(hit["number"])
            tags["channel_number"] = channel_number
    except Exception:
        pass
    shortcut = None
    if save:
        shortcut = save_shortcut(
            shortcut_id=str(pick["shortcut_id"]),
            search_query=pick["calls"],
            channel_title=title,
            channel_number=channel_number,
            group=pick["section"],
            kind="local",
            notes=(
                f"Purposeful multi-DMA local. network={pick['network']} "
                f"market={pick['market']} calls={pick['calls']}"
                f"{f' number={channel_number}' if channel_number else ''}. "
                f"Open via {via} / {pick['section']} (not Pluto). why={pick['why']}"
            ),
            open_meta={
                "method": "us_section_grouper",
                "section": pick["section"],
                "network": pick["network"],
                "market": pick["market"],
                "calls": pick["calls"],
                "state": pick.get("state"),
                "city": pick.get("city"),
                "last_via": via,
            },
            root=root,
        )

    # Append dataset index row for corpus accounting.
    idx = root / "indexes" / "US_LOCALS_TAKES.jsonl"
    with idx.open("a", encoding="utf-8") as f:
        f.write(
            json.dumps(
                {
                    "utc": datetime.now(timezone.utc).isoformat(),
                    "instance_id": instance_id,
                    "opened": opened,
                    "via": via,
                    **tags,
                    "why": pick.get("why"),
                }
            )
            + "\n"
        )

    try:
        from .stream_status import record

        record(
            instance_id,
            event="channel_open",
            ok=True,
            detail=f"{pick.get('market')} {pick.get('calls')} via {via}",
            intended={
                "network": pick.get("network"),
                "market": pick.get("market"),
                "calls": pick.get("calls"),
                "section": pick.get("section"),
                "channel_number": channel_number,
            },
            selected_title=title,
            via=via,
            network=str(pick.get("network") or ""),
            market=str(pick.get("market") or ""),
            calls=str(pick.get("calls") or ""),
            channel_number=channel_number,
            program_title=next(
                (t for t in player_texts if " at " in t.lower() or " vs " in t.lower()),
                None,
            ),
            failover=bool(pick.get("role") == "failover" or pick.get("market") == FAILOVER_MARKET),
            root=root,
        )
    except Exception:
        pass

    return {
        "ok": True,
        "pick": pick,
        "selected_title": title,
        "channel_title": title,
        "opened": opened,
        "player_texts": player_texts[:25],
        "tags": tags,
        "shortcut": shortcut,
        "via": via,
        "section_error": section_err,
        "identity": ident,
        "channel_number": channel_number,
        "open_via": "section_child",
    }


def open_local_for_shortcut(
    shortcut_id: str,
    *,
    row: dict[str, Any] | None = None,
    instance_id: str = DEFAULT_INSTANCE,
    open_player: bool = True,
    save: bool = True,
    root: Path | None = None,
) -> dict[str, Any] | None:
    """If shortcut/id is a US local, open parent section → alphabetical child.

    Returns None when the id is not a local (caller may fall through to search).
    """
    pick = resolve_local_pick(shortcut_id, row=row, root=root)
    if not pick:
        return None
    net = str(pick.get("network") or "")
    if pick.get("rotate") or not pick.get("market"):
        out = open_local(
            net,
            shortcut_id=str(pick.get("shortcut_id") or shortcut_id),
            instance_id=instance_id,
            open_player=open_player,
            save=save,
            root=root,
        )
    else:
        out = open_local(
            net,
            market=str(pick.get("market")),
            shortcut_id=str(pick.get("shortcut_id") or shortcut_id),
            instance_id=instance_id,
            open_player=open_player,
            save=save,
            root=root,
        )
    out["open_via"] = "section_child"
    out["shortcut_id"] = str(pick.get("shortcut_id") or shortcut_id)
    out["section"] = pick.get("section") or SECTION_FOR.get(net)
    out.setdefault("selected_title", out.get("channel_title"))
    return out


def ensure_market_local_shortcuts(
    *,
    markets: tuple[str, ...] = ("New York", "Atlanta", "Los Angeles"),
    root: Path | None = None,
) -> list[dict[str, Any]]:
    """Seed NET_TOKEN shortcuts (FOX_NY, CBS_NY, …) with section-child open meta.

    Does not open the player — only writes the parent→child recipe so schedule
    / reopen never movie-search ``FOX`` / ``CBS``.
    """
    root = ensure_data_layout(root)
    from .streamers_open import get_shortcut, save_shortcut

    written: list[dict[str, Any]] = []
    for net in NETWORKS:
        for market in markets:
            try:
                pick = pick_local(net, market=market, root=root)
            except Exception:
                continue
            sid = str(pick["shortcut_id"])
            title = (
                f"{pick['state']} | {pick['city']} | {net} - {pick['calls']}"
            )
            try:
                existing = get_shortcut(sid, root)
            except KeyError:
                existing = None
            # Upgrade search_then_center locals; leave richer confirmed titles.
            if existing and str((existing.get("open") or {}).get("method") or "") == "us_section_grouper":
                if existing.get("channel_title") and " | " in str(existing.get("channel_title")):
                    written.append(existing)
                    continue
            row = save_shortcut(
                shortcut_id=sid,
                search_query=str(pick["calls"]),
                channel_title=str(existing.get("channel_title") if existing else title),
                channel_number=existing.get("channel_number") if existing else None,
                group=pick["section"],
                kind="local",
                notes=(
                    f"Section-child local. network={net} market={pick['market']} "
                    f"calls={pick['calls']}. Open via us_section_grouper / {pick['section']} "
                    f"(alphabetical children; not network-name search)."
                ),
                open_meta={
                    "method": "us_section_grouper",
                    "section": pick["section"],
                    "network": net,
                    "market": pick["market"],
                    "calls": pick["calls"],
                    "state": pick.get("state"),
                    "city": pick.get("city"),
                },
                root=root,
            )
            written.append(row)
        # Also stamp generic *_LOCAL toward section-first when present.
        local_id = f"{net}_LOCAL"
        try:
            existing = get_shortcut(local_id, root)
        except KeyError:
            existing = None
        if existing:
            open_meta = dict(existing.get("open") or {})
            if open_meta.get("method") != "us_section_grouper":
                parsed = parse_local_title(str(existing.get("channel_title") or ""))
                calls = open_meta.get("calls") or existing.get("search_query") or (parsed or {}).get("calls")
                market = open_meta.get("market")
                if not market and parsed:
                    # Best-effort: match city to roster.
                    city = str(parsed.get("city") or "").lower()
                    for r in FLAGSHIPS[net]:
                        if city and city in r["city"].lower():
                            market = r["market"]
                            break
                if not market:
                    market = HOME_MARKET
                try:
                    pick = pick_local(net, market=str(market), shortcut_id=local_id, root=root)
                except Exception:
                    pick = {
                        "network": net,
                        "section": SECTION_FOR[net],
                        "market": market,
                        "calls": calls,
                        "state": (parsed or {}).get("state"),
                        "city": (parsed or {}).get("city"),
                        "shortcut_id": local_id,
                    }
                row = save_shortcut(
                    shortcut_id=local_id,
                    search_query=str(pick.get("calls") or calls or ""),
                    channel_title=str(existing.get("channel_title") or ""),
                    channel_number=existing.get("channel_number"),
                    group=str(pick.get("section") or SECTION_FOR[net]),
                    kind="local",
                    notes=str(existing.get("notes") or "") + " [upgraded to us_section_grouper]",
                    open_meta={
                        "method": "us_section_grouper",
                        "section": pick.get("section") or SECTION_FOR[net],
                        "network": net,
                        "market": pick.get("market") or market,
                        "calls": pick.get("calls") or calls,
                        "state": pick.get("state"),
                        "city": pick.get("city"),
                    },
                    root=root,
                )
                written.append(row)
    return written


def roster_board(root: Path | None = None) -> Path:
    """Write a human board of the DMA roster + rotation tip."""
    root = ensure_data_layout(root)
    rot = load_rotation(root)
    lines = [
        "# US locals (any DMA) — purposeful dataset use",
        "",
        "Streamers `US ABC/CBS/NBC/FOX SECTION` = every US affiliate, anytime.",
        "We rotate big DMAs so the corpus is not one Alaska filler forever.",
        "",
        f"Rotation file: `{rotation_path(root)}`",
        "",
        "| Network | Section | Flagships (calls) | Next index |",
        "|---|---|---|---|",
    ]
    for net in NETWORKS:
        calls = ", ".join(f"{r['calls']} ({r['market']})" for r in FLAGSHIPS[net][:5])
        nxt = (rot.get("next_index") or {}).get(net, 0)
        lines.append(f"| {net} | {SECTION_FOR[net]} | {calls}… | {nxt} |")
    lines.extend(
        [
            "",
            "Open next purposeful local:",
            "",
            "```",
            "python -m tools.windows_lab open local --network FOX",
            "python -m tools.windows_lab open local --network ABC --market \"Los Angeles\"",
            "```",
            "",
            "West Coast preference kicks in after ~1pm ET (still morning out west) "
            "and late night (PT late news).",
            "",
        ]
    )
    out = root / "indexes" / "US_LOCALS.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="Purposeful US ABC/CBS/NBC/FOX locals")
    sub = p.add_subparsers(dest="cmd", required=True)
    o = sub.add_parser("open", help="Open next rotated (or named) local")
    o.add_argument("--network", required=True, choices=[*NETWORKS, *[n.lower() for n in NETWORKS]])
    o.add_argument("--market", default=None)
    o.add_argument("--instance", default=DEFAULT_INSTANCE)
    o.add_argument("--no-open", action="store_true")
    o.add_argument("--west", action="store_true", help="Force West Coast preference")
    b = sub.add_parser("board", help="Write US_LOCALS.md roster board")
    pk = sub.add_parser("pick", help="Show next pick without opening")
    pk.add_argument("--network", required=True)
    pk.add_argument("--market", default=None)
    pk.add_argument("--west", action="store_true")
    args = p.parse_args(argv)

    if args.cmd == "board":
        path = roster_board()
        print(json.dumps({"ok": True, "board": str(path)}, indent=2))
        return 0
    if args.cmd == "pick":
        row = pick_local(
            args.network,
            market=args.market,
            prefer_west_coast=True if args.west else None,
        )
        print(json.dumps(row, indent=2))
        return 0
    if args.cmd == "open":
        report = open_local(
            args.network,
            market=args.market,
            prefer_west_coast=True if args.west else None,
            instance_id=args.instance,
            open_player=not args.no_open,
        )
        print(json.dumps(report, indent=2))
        return 0 if report.get("ok") else 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
