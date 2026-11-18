"""Agent-owned Streamers coverage: guide plan, board, capacity, dispatch report.

Farm corpus stays under OHUSH_DATA_ROOT as authorized_stream_reference.
Never merges into sealed optical football gold.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
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

# Top-down US appointment/viewership value (lower index = more people watch).
# Record priority = this ladder × data scarcity (see record_priority_queue).
ROI_LADDER: tuple[str, ...] = (
    "live_nfl",  # TNF / MNF / Sunday — largest US audiences
    "live_nba_nhl_mlb",  # National game cards
    "live_awards",  # CMA / Oscars / Grammys
    "live_competition",  # DWTS / The Voice / Idol / AGT (live voting)
    "appointment_reality",  # Bachelor / Survivor / Amazing Race / Big Brother
    "primetime_network",  # ABC/CBS/NBC/FOX scripted + primetime linear
    "news_cable",  # FOX NEWS / CNN — all-day density
    "local_news",  # Morning/evening DMA news
    "daytime_tv",  # Soaps / daytime talk
    "sports_studio",  # ESPN / TNT studio when no game
    "reality_tv",  # Thin unscripted fill
    "fast_free",  # Pluto/Roku — thin ROI
)

# How much inventory we want per band before deprioritizing.
DATA_TARGET_MINUTES: dict[str, float] = {
    "live_nfl": 180.0,
    "live_nba_nhl_mlb": 120.0,
    "live_awards": 120.0,
    "live_competition": 120.0,
    "appointment_reality": 90.0,
    "primetime_network": 60.0,
    "news_cable": 90.0,
    "local_news": 45.0,
    "daytime_tv": 30.0,
    "sports_studio": 45.0,
    "reality_tv": 30.0,
    "fast_free": 15.0,
}

ROI_BAND_LABELS: dict[str, str] = {
    "live_nfl": "NFL live (biggest audience)",
    "live_nba_nhl_mlb": "National sports live",
    "live_awards": "Awards / specials",
    "live_competition": "Live competition (DWTS/Voice/Idol)",
    "appointment_reality": "Appointment reality (Bachelor/Survivor)",
    "primetime_network": "Network primetime",
    "news_cable": "Cable news",
    "local_news": "Local news",
    "daytime_tv": "Daytime TV",
    "sports_studio": "Sports studio / fill",
    "reality_tv": "Reality fill",
    "fast_free": "FAST / free",
}

# Regimented dual-stream blocks (ET). chunk_minutes 20 = rotate often; 60 = hold event.
# K streams take the first K distinct channel_ids in the active block.
REGIMENTED_BLOCKS: tuple[dict[str, Any], ...] = (
    {
        "id": "weekday_morning_news",
        "weekdays": (0, 1, 2, 3, 4),
        "start": "06:00",
        "end": "12:00",
        "chunk_minutes": 20,
        "channels": ("FOX_NEWS_US", "CNN_US", "NBC_LOCAL_FLAGSHIP", "ABC_LOCAL_FLAGSHIP"),
        "why": "Morning: cable news + big-DMA morning shows (highest daytime news ROI)",
    },
    {
        "id": "weekday_afternoon_news",
        "weekdays": (0, 1, 2, 3, 4),
        "start": "12:00",
        "end": "17:00",
        "chunk_minutes": 20,
        "channels": ("FOX_NEWS_US", "CNN_US", "ESPN_US", "CBS_LOCAL_FLAGSHIP"),
        "why": "Afternoon: FOX NEWS + CNN primary; ESPN studio if news saturated",
    },
    {
        "id": "weekday_early_fringe",
        "weekdays": (0, 1, 2, 3, 4),
        "start": "17:00",
        "end": "19:00",
        "chunk_minutes": 20,
        "channels": ("FOX_NEWS_US", "CNN_US", "NBC_LOCAL_FLAGSHIP", "ABC_LOCAL_FLAGSHIP"),
        "why": "Early fringe: cable news + local evening news",
    },
    {
        "id": "wed_cma_primetime",
        "weekdays": (2,),
        "start": "19:00",
        "end": "23:30",
        "chunk_minutes": 60,
        "channels": ("CMA_AWARDS", "FOX_NEWS_US", "CNN_US", "TNT_US"),
        "why": "Wed awards night: CMA first stream; news/TNT second",
    },
    {
        "id": "thu_tnf_primetime",
        "weekdays": (3,),
        "start": "19:00",
        "end": "23:45",
        "chunk_minutes": 60,
        "channels": ("ESPN_US", "FOX_NEWS_US", "CNN_US", "TNT_US"),
        "why": "Thu: TNF/ESPN first; cable news second until game ends",
    },
    {
        "id": "weekday_primetime_default",
        "weekdays": (0, 1, 4),
        "start": "19:00",
        "end": "23:00",
        "chunk_minutes": 20,
        "channels": ("ABC_LOCAL_FLAGSHIP", "NBC_LOCAL_FLAGSHIP", "FOX_NEWS_US", "CNN_US", "TNT_US"),
        "why": "Mon/Tue/Fri primetime: network linear + news; TNT if NBA/NHL",
    },
    {
        "id": "late_news",
        "weekdays": (0, 1, 2, 3, 4, 5, 6),
        "start": "23:00",
        "end": "02:00",
        "chunk_minutes": 20,
        "channels": ("FOX_NEWS_US", "CNN_US", "ESPN_US", "NBC_LOCAL_FLAGSHIP"),
        "why": "Late: cable news + SportsCenter-style studio",
    },
    {
        "id": "overnight_hold",
        "weekdays": (0, 1, 2, 3, 4, 5, 6),
        "start": "02:00",
        "end": "06:00",
        "chunk_minutes": 60,
        "channels": ("FOX_NEWS_US", "CNN_US"),
        "why": "Overnight hold: cable news only (desk may skip record 02–16 ET)",
    },
    {
        "id": "weekend_morning",
        "weekdays": (5, 6),
        "start": "06:00",
        "end": "11:00",
        "chunk_minutes": 20,
        "channels": ("FOX_NEWS_US", "CNN_US", "ESPN_US", "NBC_LOCAL_FLAGSHIP"),
        "why": "Weekend morning: news + ESPN until day sports block",
    },
    {
        "id": "weekend_day_sports",
        "weekdays": (5, 6),
        "start": "11:00",
        "end": "19:00",
        "chunk_minutes": 60,
        "channels": ("ESPN_US", "FOX_LOCAL_FLAGSHIP", "CBS_LOCAL_FLAGSHIP", "NBC_LOCAL_FLAGSHIP", "CNN_US"),
        "why": "Sat/Sun day: sports + game-carrying locals before news fill",
    },
    {
        "id": "weekend_primetime",
        "weekdays": (5, 6),
        "start": "19:00",
        "end": "23:45",
        "chunk_minutes": 60,
        "channels": ("ESPN_US", "TNT_US", "ABC_LOCAL_FLAGSHIP", "FOX_NEWS_US", "CNN_US"),
        "why": "Sat/Sun night: live sports nets first, then network/news",
    },
)

# Always-on demand seeds. Ranked by gap + live preempt; top-K assigned to streams.
# Prefer nav_route (national linear) over any_us_local — recover must not WAGA-substitute.
SEED_TARGETS: list[dict[str, Any]] = [
    {
        "channel_id": "FOX_NEWS_US",
        "guide_name": "US: FOX NEWS",
        "group": "US NEWS",
        "slot": "main_news",
        "prominence": "main_news",
        "genres": ["news_cable"],
        "nav_route": "FOX_NEWS_US",
        "open_via": "nav",
        "open_hint": "Parent US NEWS → child US: FOX NEWS (nav). Never US FOX SECTION / WAGA.",
        "live_sensitive": False,
        "verified_play": True,
    },
    {
        "channel_id": "CNN_US",
        "guide_name": "US: CNN",
        "group": "US NEWS",
        "slot": "main_news",
        "prominence": "main_news",
        "genres": ["news_cable"],
        "nav_route": "CNN_US",
        "open_via": "nav",
        "open_hint": "Parent US NEWS → child US: CNN (nav).",
        "live_sensitive": False,
        "verified_play": True,
    },
    {
        "channel_id": "ESPN_US",
        "guide_name": "US: ESPN",
        "group": "US SPORTS",
        "slot": "aux_sports",
        "prominence": "aux_sports",
        "genres": ["sports_studio", "nfl", "nba", "nhl"],
        "nav_route": "ESPN_US",
        "open_via": "nav",
        "open_hint": "Parent US SPORTS → child US: ESPN. Not ESPNU / MAX.",
        "live_sensitive": True,
        "verified_play": True,
    },
    {
        "channel_id": "ESPN2_US",
        "guide_name": "US: ESPN 2",
        "group": "US SPORTS",
        "slot": "aux_sports",
        "prominence": "aux_sports",
        "genres": ["sports_studio"],
        "nav_route": "ESPN2_US",
        "open_via": "nav",
        "open_hint": "Parent US SPORTS → child US: ESPN 2.",
        "live_sensitive": True,
        "verified_play": True,
    },
    {
        "channel_id": "TNT_US",
        "guide_name": "US: TNT",
        "group": "US ENTERTAINMENT",
        "slot": "aux_sports",
        "prominence": "aux_sports",
        "genres": ["nhl", "nba", "nighttime_tv"],
        "nav_route": "TNT_US",
        "open_via": "nav",
        "open_hint": "Parent US ENTERTAINMENT → child US: TNT (NHL/NBA nights).",
        "live_sensitive": True,
        "verified_play": False,
    },
    {
        "channel_id": "CMA_AWARDS",
        "guide_name": "CMA Awards",
        "group": "US ENTERTAINMENT",
        "slot": "live_event",
        "prominence": "live_event",
        "genres": ["live_awards"],
        "search_query": "CMA",
        "open_via": "search",
        "open_hint": "Guide search CMA / Country Music Awards — confirm live card, not movie.",
        "live_sensitive": True,
        "verified_play": False,
    },
    {
        "channel_id": "DWTS",
        "guide_name": "Dancing with the Stars",
        "group": "US ENTERTAINMENT",
        "slot": "live_event",
        "prominence": "live_event",
        "genres": ["live_competition"],
        "search_query": "Dancing with the Stars",
        "open_via": "search",
        "open_hint": "ABC Tue 8–10p ET — guide search DWTS; confirm live card.",
        "live_sensitive": True,
        "verified_play": False,
    },
    {
        "channel_id": "THE_BACHELOR",
        "guide_name": "The Bachelor",
        "group": "US ENTERTAINMENT",
        "slot": "live_event",
        "prominence": "live_event",
        "genres": ["appointment_reality", "reality_tv"],
        "roi_band": "appointment_reality",
        "search_query": "The Bachelor",
        "open_via": "search",
        "open_hint": "ABC Mon 8–10p ET when in season — guide search The Bachelor.",
        "live_sensitive": True,
        "verified_play": False,
    },
    {
        "channel_id": "THE_BACHELORETTE",
        "guide_name": "The Bachelorette",
        "group": "US ENTERTAINMENT",
        "slot": "live_event",
        "prominence": "live_event",
        "genres": ["appointment_reality", "reality_tv"],
        "roi_band": "appointment_reality",
        "search_query": "The Bachelorette",
        "open_via": "search",
        "open_hint": "ABC when in season — guide search The Bachelorette.",
        "live_sensitive": True,
        "verified_play": False,
    },
    {
        "channel_id": "SURVIVOR",
        "guide_name": "Survivor",
        "group": "US ENTERTAINMENT",
        "slot": "live_event",
        "prominence": "live_event",
        "genres": ["appointment_reality", "reality_tv"],
        "roi_band": "appointment_reality",
        "search_query": "Survivor",
        "open_via": "search",
        "open_hint": "CBS Wed 8–9:30p ET — guide search Survivor.",
        "live_sensitive": True,
        "verified_play": False,
    },
    {
        "channel_id": "THE_AMAZING_RACE",
        "guide_name": "The Amazing Race",
        "group": "US ENTERTAINMENT",
        "slot": "live_event",
        "prominence": "live_event",
        "genres": ["appointment_reality", "reality_tv"],
        "roi_band": "appointment_reality",
        "search_query": "Amazing Race",
        "open_via": "search",
        "open_hint": "CBS Wed 9:30–11p ET — guide search Amazing Race.",
        "live_sensitive": True,
        "verified_play": False,
    },
    {
        "channel_id": "THE_VOICE",
        "guide_name": "The Voice",
        "group": "US ENTERTAINMENT",
        "slot": "live_event",
        "prominence": "live_event",
        "genres": ["live_competition"],
        "roi_band": "live_competition",
        "search_query": "The Voice",
        "open_via": "search",
        "open_hint": "NBC Mon 8–10p ET — guide search The Voice.",
        "live_sensitive": True,
        "verified_play": False,
    },
    {
        "channel_id": "BIG_BROTHER",
        "guide_name": "Big Brother",
        "group": "US ENTERTAINMENT",
        "slot": "live_event",
        "prominence": "live_event",
        "genres": ["appointment_reality", "reality_tv"],
        "roi_band": "appointment_reality",
        "search_query": "Big Brother",
        "open_via": "search",
        "open_hint": "CBS summer evenings — guide search Big Brother.",
        "live_sensitive": True,
        "verified_play": False,
    },
    {
        "channel_id": "AMERICAN_IDOL",
        "guide_name": "American Idol",
        "group": "US ENTERTAINMENT",
        "slot": "live_event",
        "prominence": "live_event",
        "genres": ["live_competition"],
        "roi_band": "live_competition",
        "search_query": "American Idol",
        "open_via": "search",
        "open_hint": "ABC Sun/Mon when in season — guide search American Idol.",
        "live_sensitive": True,
        "verified_play": False,
    },
    {
        "channel_id": "HELLS_KITCHEN",
        "guide_name": "Hell's Kitchen",
        "group": "US ENTERTAINMENT",
        "slot": "live_event",
        "prominence": "live_event",
        "genres": ["appointment_reality", "reality_tv"],
        "roi_band": "appointment_reality",
        "search_query": "Hell's Kitchen",
        "open_via": "search",
        "open_hint": "FOX Thu 8p ET — guide search Hell's Kitchen.",
        "live_sensitive": True,
        "verified_play": False,
    },
    {
        "channel_id": "REALITY_TV_FILL",
        "guide_name": "Reality / unscripted fill",
        "group": "US ENTERTAINMENT",
        "slot": "talk_entertainment",
        "prominence": "talk_entertainment",
        "genres": ["reality_tv"],
        "search_query": "Big Brother",
        "open_via": "search",
        "open_hint": "US ENTERTAINMENT reality fill when no live sports/awards card.",
        "live_sensitive": False,
        "verified_play": False,
    },
    {
        "channel_id": "NBC_NEWS_NOW",
        "guide_name": "(RK) NBC News NOW",
        "group": "ROKU TV",
        "number": 2513,
        "slot": "main_news",
        "prominence": "main_news",
        "genres": ["news_cable"],
        "open_hint": "Search NBC News NOW in Roku TV / US NEWS.",
        "live_sensitive": False,
        "verified_play": True,
    },
    {
        "channel_id": "PLUTO_CBS_SPORTS_HQ",
        "guide_name": "(PLUTO USA) CBS Sports HQ",
        "group": "PLUTO U.S.A.",
        "number": 2702,
        "slot": "fast",
        "prominence": "fast",
        "genres": ["sports_studio"],
        "open_hint": "Pluto U.S.A. — CBS Sports HQ.",
        "live_sensitive": False,
        "verified_play": True,
    },
    {
        "channel_id": "NBC_LOCAL_FLAGSHIP",
        "guide_name": "US NBC SECTION local / flagship",
        "group": "US NBC SECTION",
        "slot": "main_linear",
        "prominence": "main_linear",
        "genres": ["local_linear", "daytime_tv", "nighttime_tv"],
        "open_hint": "US NBC SECTION — rotate big-DMA locals. Not movie search.",
        "live_sensitive": False,
        "verified_play": False,
        "any_us_local": True,
    },
    {
        "channel_id": "CBS_LOCAL_FLAGSHIP",
        "guide_name": "US CBS SECTION local / flagship",
        "group": "US CBS SECTION",
        "slot": "main_linear",
        "prominence": "main_linear",
        "genres": ["local_linear", "daytime_tv", "nighttime_tv"],
        "open_hint": "US CBS SECTION — big-DMA locals with picture.",
        "live_sensitive": False,
        "verified_play": False,
        "any_us_local": True,
    },
    {
        "channel_id": "ABC_LOCAL_FLAGSHIP",
        "guide_name": "US ABC SECTION local / flagship",
        "group": "US ABC SECTION",
        "slot": "main_linear",
        "prominence": "main_linear",
        "genres": ["local_linear", "daytime_tv", "nighttime_tv"],
        "open_hint": "US ABC SECTION — rotate NY/LA/CHI/DFW/ATL.",
        "live_sensitive": False,
        "verified_play": False,
        "any_us_local": True,
    },
    {
        "channel_id": "FOX_LOCAL_FLAGSHIP",
        "guide_name": "US FOX SECTION local / flagship",
        "group": "US FOX SECTION",
        "slot": "main_linear",
        "prominence": "main_linear",
        "genres": ["local_linear", "daytime_tv", "nighttime_tv"],
        "open_hint": "US FOX SECTION locals only — never substitute for FOX NEWS nav.",
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
    live_kind = ""
    if active:
        # Entertainment preempt (CMA/DWTS) beats sports when both flagged.
        kinds = {str(w.get("kind") or "sports") for w in active}
        live_kind = "entertainment" if "entertainment" in kinds else "sports"
    return {
        "local_et": local.isoformat(),
        "weekday": local.strftime("%A"),
        "daypart": daypart_for(local),
        "live_preempt": bool(active),
        "live_kind": live_kind,
        "live_windows": windows,
        "fill_order": fill_order_for(local),
        "priority_markets": list(PRIORITY_MARKETS),
        "roi_ladder": list(ROI_LADDER),
        "roi_band_labels": dict(ROI_BAND_LABELS),
        "data_target_minutes": dict(DATA_TARGET_MINUTES),
        "record_formula": (
            "Record what more people watch first (roi_ladder). "
            "Within a band, prefer what we have the least of "
            "(data target − captured minutes)."
        ),
        "rule": (
            "If a live window is active and a real game/event is on air, capture that first. "
            "Entertainment live (awards/DWTS) must not fall through to Atlanta FOX local. "
            "Otherwise: viewers ladder × data scarcity. National news uses nav (FOX_NEWS/CNN), not WAGA."
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


def _hhmm_to_minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _local_minutes(dt: datetime) -> int:
    return dt.hour * 60 + dt.minute


def _block_covers(local: datetime, block: dict[str, Any]) -> bool:
    """True if local ET falls in block window (end may wrap past midnight)."""
    if local.weekday() not in set(block.get("weekdays") or ()):
        return False
    start = _hhmm_to_minutes(str(block["start"]))
    end = _hhmm_to_minutes(str(block["end"]))
    now_m = _local_minutes(local)
    if end > start:
        return start <= now_m < end
    # wraps midnight (e.g. 23:00–02:00)
    return now_m >= start or now_m < end


def active_regimented_block(now: datetime | None = None) -> dict[str, Any] | None:
    """First matching REGIMENTED_BLOCKS entry for this ET clock."""
    local = now.astimezone(ET) if now else _now_et()
    for block in REGIMENTED_BLOCKS:
        if _block_covers(local, block):
            return dict(block)
    return None


def roi_band_for_target(target: dict[str, Any]) -> str:
    """Map seed/listings → ROI_LADDER band name."""
    if target.get("roi_band") and str(target["roi_band"]) in ROI_LADDER:
        return str(target["roi_band"])
    # Explicit roi from major_programs
    if target.get("roi") and str(target["roi"]) in ROI_LADDER:
        return str(target["roi"])
    genres = {str(g) for g in (target.get("genres") or [])}
    cid = str(target.get("channel_id") or "").upper()
    if "live_nfl" in genres or cid in {"TNF", "MNF"}:
        return "live_nfl"
    if "live_awards" in genres:
        return "live_awards"
    if "live_competition" in genres or "competition" in genres:
        return "live_competition"
    if "appointment_reality" in genres:
        return "appointment_reality"
    # Named appointment reality ids (Bachelor Nation / CBS unscripted, etc.)
    if cid in {
        "THE_BACHELOR",
        "THE_BACHELORETTE",
        "BACHELOR_IN_PARADISE",
        "SURVIVOR",
        "THE_AMAZING_RACE",
        "BIG_BROTHER",
        "THE_TRAITORS",
        "HELLS_KITCHEN",
        "SPECIAL_FORCES",
        "SHARK_TANK",
        "MASTERCHEF",
    }:
        return "appointment_reality"
    if cid in {"DWTS", "THE_VOICE", "AMERICAN_IDOL", "AMERICAS_GOT_TALENT", "THE_MASKED_SINGER"}:
        return "live_competition"
    if cid in {"CMA_AWARDS", "OSCARS"}:
        return "live_awards"
    if "news_cable" in genres:
        return "news_cable"
    if "local_news" in genres or (
        target.get("any_us_local") and "FLAGSHIP" in cid and "NEWS" not in cid
    ):
        if target.get("any_us_local"):
            return "primetime_network" if target.get("slot") == "main_linear" else "local_news"
        return "local_news"
    if "daytime" in genres or "soap" in genres:
        return "daytime_tv"
    if "nba" in genres or "nhl" in genres or "mlb" in genres:
        return "live_nba_nhl_mlb"
    if "sports" in genres or target.get("slot") == "aux_sports":
        if "ESPN" in cid or cid.startswith("TNT"):
            return "sports_studio"
        return "live_nba_nhl_mlb"
    if "reality_tv" in genres or "reality" in genres:
        return "appointment_reality" if target.get("live_sensitive") else "reality_tv"
    if "fast" in genres or target.get("slot") == "fast":
        return "fast_free"
    if target.get("slot") == "main_linear":
        return "primetime_network"
    if target.get("slot") == "main_news":
        return "news_cable"
    return "reality_tv"


def roi_rank_for_target(target: dict[str, Any]) -> int:
    """Map seed/listings → ROI_LADDER index (lower = more viewers)."""
    band = roi_band_for_target(target)
    try:
        return ROI_LADDER.index(band)
    except ValueError:
        return len(ROI_LADDER)


def data_scarcity_for(
    channel_id: str,
    *,
    roi_band: str,
    channel_minutes: float,
    target_minutes: float | None = None,
) -> dict[str, Any]:
    """How badly we still need this feed (viewers band × inventory hole)."""
    target = float(
        target_minutes
        if target_minutes is not None
        else DATA_TARGET_MINUTES.get(roi_band, 45.0)
    )
    have = max(0.0, float(channel_minutes or 0.0))
    need = max(0.0, target - have)
    scarcity = (need / target) if target > 0 else 0.0
    # 0 = empty/critical, 1 = partial, 2 = saturated enough to deprioritize
    if scarcity >= 0.85:
        bucket = 0
        label = "critical gap"
    elif scarcity >= 0.35:
        bucket = 1
        label = "needs more"
    else:
        bucket = 2
        label = "enough for now"
    return {
        "channel_id": channel_id,
        "roi_band": roi_band,
        "target_minutes": round(target, 1),
        "have_minutes": round(have, 1),
        "need_minutes": round(need, 1),
        "scarcity": round(scarcity, 3),
        "scarcity_bucket": bucket,
        "scarcity_label": label,
    }


def regimented_chunks_ahead(
    now: datetime | None = None,
    *,
    hours: int = 48,
    max_streams: int = 2,
) -> list[dict[str, Any]]:
    """Expand regimented blocks into discrete 20m/60m chunks for the next N hours."""
    local = now.astimezone(ET) if now else _now_et()
    # Align to chunk boundary of the active (or next) block.
    cursor = local.replace(second=0, microsecond=0)
    end = cursor + timedelta(hours=hours)
    chunks: list[dict[str, Any]] = []
    guard = 0
    while cursor < end and guard < 500:
        guard += 1
        block = active_regimented_block(cursor)
        if not block:
            # Jump to next half-hour and retry.
            cursor += timedelta(minutes=30 - (cursor.minute % 30 or 30))
            continue
        chunk_m = int(block.get("chunk_minutes") or 20)
        # Snap cursor down to chunk grid within the hour when possible.
        snap = cursor.minute - (cursor.minute % chunk_m) if chunk_m else cursor.minute
        chunk_start = cursor.replace(minute=snap, second=0, microsecond=0)
        if chunk_start < cursor:
            chunk_start += timedelta(minutes=chunk_m)
        if not _block_covers(chunk_start, block):
            cursor = chunk_start
            continue
        channels = list(block.get("channels") or [])[: max(1, max_streams)]
        chunks.append(
            {
                "start_et": chunk_start.isoformat(),
                "end_et": (chunk_start + timedelta(minutes=chunk_m)).isoformat(),
                "chunk_minutes": chunk_m,
                "block_id": block.get("id"),
                "why": block.get("why"),
                "channels": channels,
            }
        )
        cursor = chunk_start + timedelta(minutes=chunk_m)
    return chunks


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
                "kind": "sports",
                "note": "Prefer ESPN / Prime / NFL feeds only if a real game is on air.",
            }
        )
    # Sun — Germany / London-style morning internationals, then US slate
    if weekday == 6:
        windows.append(
            {
                "id": "nfl_sunday_germany_morning",
                "label": "NFL international morning (Germany/London)",
                "start_local": "09:00",
                "end_local": "13:00",
                "priority": "live_event",
                "note": (
                    "Munich/London kickoffs ~9:30 ET. Prefer live NFL 01 / FOX / NFL Network "
                    "card with team names; confirm with schedule guide-refresh."
                ),
            }
        )
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
    # Wed awards / live entertainment (CMA night 2026-11-18 and similar).
    if weekday == 2:
        windows.append(
            {
                "id": "cma_awards_wednesday",
                "label": "CMA Awards / Wednesday live entertainment",
                "start_local": "19:00",
                "end_local": "23:30",
                "priority": "live_event",
                "kind": "entertainment",
                "note": (
                    "Confirm CMA / awards card via guide search. "
                    "Do not open Atlanta FOX local as substitute."
                ),
            }
        )
    # Midweek live competition (DWTS often Tue).
    if weekday == 1:
        windows.append(
            {
                "id": "dwts_tuesday",
                "label": "Dancing with the Stars window",
                "start_local": "20:00",
                "end_local": "23:00",
                "priority": "live_event",
                "kind": "entertainment",
                "note": "Confirm DWTS live card; else fall through to next gap.",
            }
        )
    # NBA / NHL — most evenings (was missing; overnight label window ate Tue/Wed games).
    windows.append(
        {
            "id": "nba_nhl_evening",
            "label": "NBA / NHL evening window",
            "start_local": "19:00",
            "end_local": "23:45",
            "priority": "live_event",
            "kind": "sports",
            "note": (
                "Prefer live NBA/NHL cards (ESPN/TNT/ABC/NBC/sports nets). "
                "Skip empty section rows; confirm team names on air."
            ),
        }
    )
    # Afternoon NBA matinees / early tips (weekends + holidays often).
    if weekday in {5, 6}:
        windows.append(
            {
                "id": "nba_nhl_afternoon",
                "label": "NBA / NHL afternoon window",
                "start_local": "12:30",
                "end_local": "18:59",
                "priority": "live_event",
                "note": "Weekend matinees — only if a real game card is live.",
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
    if any(k in text for k in ("cma", "awards", "dancing with the stars", "dwts")):
        return "live_event"
    if any(k in text for k in ("nfl", "prime", "mnf", "tnf")) and "news" not in text:
        return "live_event"
    if any(k in text for k in ("espn", "fs1", "fs2", "sec network", "big ten", "mlb network")):
        return "aux_sports"
    if any(k in text for k in ("reality", "big brother", "survivor", "bachelor")):
        return "talk_entertainment"
    # National cable news BEFORE bare "fox" (FOX NEWS ≠ FOX local).
    if "fox news" in text or "cnn" in text or ("news" in text and "fox" not in text):
        return "main_news"
    if "news" in text:
        return "main_news"
    if any(k in text for k in ("pluto", "roku", "tubi", "peacock")):
        return "fast"
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


def _desk_max_streams(root: Path | None = None) -> int:
    """K cap from progressive capacity when present, else registry."""
    root = ensure_data_layout(root)
    limits = root / "farm" / "desk_limits.json"
    if limits.is_file():
        try:
            data = json.loads(limits.read_text(encoding="utf-8"))
            for key in ("max_streams", "max_concurrent", "clean_concurrent"):
                if data.get(key) is not None:
                    return max(1, int(data[key]))
        except Exception:
            pass
    reg = load_registry(root)
    return max(1, int(reg.get("max_concurrent_streamers") or 3))


def ready_instances(
    root: Path | None = None, *, max_n: int | None = None
) -> list[dict[str, Any]]:
    cap = int(max_n) if max_n is not None else _desk_max_streams(root)
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
                "player_label": row.get("player_label") or row["id"],
                "player": row.get("player"),
                "loopback_device": loopback,
                "adb_serial": row.get("adb_serial"),
                "ready": bool(loopback),
                "audio_route_note": row.get("audio_route_note"),
            }
        )
    ready = [r for r in rows if r["ready"]]
    # If nothing marked ready (no loopback yet), still expose enabled ids for planning.
    if not ready:
        ready = [
            {
                "id": r["id"],
                "player_label": r.get("player_label") or r["id"],
                "player": r.get("player"),
                "loopback_device": "",
                "adb_serial": r.get("adb_serial"),
                "ready": False,
                "audio_route_note": r.get("audio_route_note"),
            }
            for r in list_instances(root)
            if r.get("source_kind", "streamers") in (None, "streamers") and r.get("enabled", True)
        ]
    return ready[:cap]


def _channel_minutes(root: Path | None = None) -> dict[str, float]:
    """Rough captured minutes by channel_id from catalog sessions."""
    out: dict[str, float] = {}
    for row in list_sessions(root, label_status=None, limit=5000):
        cid = str(row.get("channel_id") or "").strip().upper()
        if not cid:
            continue
        minutes = float(row.get("duration_minutes") or row.get("minutes") or 0.0)
        if minutes <= 0 and row.get("duration_s"):
            minutes = float(row["duration_s"]) / 60.0
        out[cid] = out.get(cid, 0.0) + minutes
    return out


def build_demand_pool(
    root: Path | None = None,
    *,
    now: datetime | None = None,
    include_listings: bool = True,
) -> list[dict[str, Any]]:
    """Score always-on seeds (+ listings overlays) for top-K assignment."""
    local = now.astimezone(ET) if now else _now_et()
    windows = live_windows_et(local)
    active_live = [w for w in windows if w.get("active_now")]
    active_kinds = {str(w.get("kind") or "sports") for w in active_live}
    gaps = coverage_gaps(root)
    gap_slots = {g["slot"] for g in gaps if g["gap_validated_minutes"] > 0}
    fill = fill_order_for(local)
    fill_rank = {slot: i for i, slot in enumerate(fill)}
    channel_mins = _channel_minutes(root)
    block = active_regimented_block(local)
    block_rank = {
        str(cid).upper(): i for i, cid in enumerate(list((block or {}).get("channels") or []))
    }

    pool: list[dict[str, Any]] = [dict(t) for t in SEED_TARGETS]
    if include_listings:
        try:
            from .listings_enrich import listings_demand_overlays

            for overlay in listings_demand_overlays(root):
                cid = str(overlay.get("channel_id") or "")
                existing = next((p for p in pool if p.get("channel_id") == cid), None)
                if existing:
                    existing.update({k: v for k, v in overlay.items() if v is not None})
                    existing["from_listings"] = True
                else:
                    pool.append(overlay)
        except Exception:
            pass

    scored: list[dict[str, Any]] = []
    for t in pool:
        cid = str(t.get("channel_id") or "")
        slot = str(t.get("slot") or "other")
        live_boost = 0
        if active_live and t.get("live_sensitive"):
            live_boost = 0
            if "entertainment" in active_kinds and "live_awards" in (t.get("genres") or []):
                live_boost = -2  # sort key: lower is better
            elif "sports" in active_kinds and t.get("nav_route") in {
                "ESPN_US",
                "ESPN2_US",
                "TNT_US",
            }:
                live_boost = -1
            else:
                live_boost = 0
        elif active_live and not t.get("live_sensitive"):
            live_boost = 2
        mins = float(channel_mins.get(cid.upper(), 0.0))
        # Named nav/search always beats DMA locals (WAGA must not win over FOX NEWS).
        named_open = 0 if (t.get("nav_route") or t.get("search_query")) else 1
        local_penalty = 1 if t.get("any_us_local") else 0
        regimen = block_rank.get(cid.upper(), 50)
        band = roi_band_for_target(t)
        roi = roi_rank_for_target(t)
        scarcity = data_scarcity_for(cid, roi_band=band, channel_minutes=mins)
        slot_gap = 0 if slot in gap_slots else 1
        # Hierarchy: live preempt → viewership band → data scarcity → regimen → named.
        # Within the same audience band, empty inventory climbs above saturated.
        score_tuple = (
            live_boost,
            roi,  # fewer viewers → later
            int(scarcity["scarcity_bucket"]),  # critical gap first
            -float(scarcity["need_minutes"]),  # more need first (negated)
            regimen,
            named_open,
            local_penalty,
            fill_rank.get(slot, 99),
            slot_gap,
            0 if t.get("verified_play") else 1,
            cid,
        )
        row = dict(t)
        row["_score"] = score_tuple
        row["roi_rank"] = roi
        row["roi_band"] = band
        row["roi_label"] = ROI_BAND_LABELS.get(band, band)
        row["regimen_rank"] = regimen
        row["channel_minutes"] = round(mins, 2)
        row["data_need"] = scarcity
        scored.append(row)
    scored.sort(key=lambda r: r["_score"])
    return scored


def record_priority_queue(
    root: Path | None = None,
    *,
    now: datetime | None = None,
    include_listings: bool = True,
    limit: int = 24,
) -> dict[str, Any]:
    """Human-readable record queue: viewers band × how little data we have.

    Returns hierarchy definition + ranked rows with why_viewers / why_data.
    """
    local = now.astimezone(ET) if now else _now_et()
    ranked = build_demand_pool(root, now=local, include_listings=include_listings)
    hierarchy = [
        {
            "rank": i,
            "band": band,
            "label": ROI_BAND_LABELS.get(band, band),
            "data_target_minutes": DATA_TARGET_MINUTES.get(band, 45.0),
        }
        for i, band in enumerate(ROI_LADDER)
    ]
    queue: list[dict[str, Any]] = []
    for i, t in enumerate(ranked[: max(1, limit)]):
        need = dict(t.get("data_need") or {})
        band = str(t.get("roi_band") or roi_band_for_target(t))
        queue.append(
            {
                "rank": i + 1,
                "channel_id": t.get("channel_id"),
                "label": t.get("guide_name") or t.get("label") or t.get("channel_id"),
                "kind": "program" if t.get("search_query") and not t.get("nav_route") else "channel",
                "roi_band": band,
                "roi_rank": t.get("roi_rank"),
                "roi_label": t.get("roi_label") or ROI_BAND_LABELS.get(band, band),
                "viewers": t.get("roi_label") or ROI_BAND_LABELS.get(band, band),
                "data": need.get("scarcity_label"),
                "have_minutes": need.get("have_minutes"),
                "need_minutes": need.get("need_minutes"),
                "target_minutes": need.get("target_minutes"),
                "scarcity": need.get("scarcity"),
                "why": (
                    f"viewers={ROI_BAND_LABELS.get(band, band)} · "
                    f"data={need.get('scarcity_label')} "
                    f"({need.get('have_minutes')}m / {need.get('target_minutes')}m)"
                ),
                "nav_route": t.get("nav_route"),
                "search_query": t.get("search_query"),
                "slot": t.get("slot"),
                "live_sensitive": bool(t.get("live_sensitive")),
            }
        )
    return {
        "ok": True,
        "built_et": local.isoformat(),
        "formula": (
            "Record first what more people watch, then within that band "
            "prefer what we have the least of (target − captured minutes)."
        ),
        "hierarchy": hierarchy,
        "queue": queue,
    }


def build_capture_plan(
    root: Path | None = None,
    *,
    chunk_minutes: int = 20,
    max_streams: int | None = None,
    include_listings: bool = True,
) -> dict[str, Any]:
    ensure_data_layout(root)
    now = _now_utc()
    local = _now_et()
    dp = daypart_for(local)
    windows = live_windows_et(local)
    active_live = [w for w in windows if w.get("active_now")]
    gaps = coverage_gaps(root)
    k = int(max_streams) if max_streams is not None else _desk_max_streams(root)
    instances = ready_instances(root, max_n=k)
    iso = isolation_report(root)
    hier = hierarchy_snapshot(local)
    ranked = build_demand_pool(root, now=local, include_listings=include_listings)
    gap_slots = {g["slot"] for g in gaps if g["gap_validated_minutes"] > 0}
    block = active_regimented_block(local)
    effective_chunk = int((block or {}).get("chunk_minutes") or chunk_minutes)
    regimen_chunks = regimented_chunks_ahead(local, hours=48, max_streams=max(k, 2))

    assignments: list[dict[str, Any]] = []
    used_channels: set[str] = set()
    for inst in instances:
        pick = None
        for target in ranked:
            cid = str(target.get("channel_id") or "")
            if not cid or cid in used_channels:
                continue
            pick = target
            break
        if not pick:
            break
        used_channels.add(str(pick["channel_id"]))
        reason_parts = [
            f"prominence={pick.get('prominence')}",
            f"slot={pick.get('slot')}",
            f"daypart={dp}",
            f"top_k={len(instances)}",
            f"roi={pick.get('roi_rank', '?')}",
        ]
        if block:
            reason_parts.append(f"block={block.get('id')}")
        if pick.get("slot") in gap_slots:
            reason_parts.append("fills_coverage_gap")
        if active_live and pick.get("live_sensitive"):
            reason_parts.append("live_window_active")
        if pick.get("from_listings"):
            reason_parts.append("listings_enrich")
        if pick.get("nav_route"):
            reason_parts.append(f"nav={pick['nav_route']}")
        if pick.get("search_query"):
            reason_parts.append(f"search={pick['search_query']}")
        local_pick = None
        if pick.get("any_us_local"):
            reason_parts.append("any_us_local_ok")
            from .us_locals import NETWORKS, pick_local

            net = next(
                (n for n in NETWORKS if n in str(pick.get("channel_id") or "").upper()),
                None,
            )
            if net:
                local_pick = pick_local(net, root=root)
                reason_parts.append(
                    f"dma={local_pick['market']}/{local_pick['calls']}/{local_pick['why']}"
                )
        assignments.append(
            {
                "instance_id": inst["id"],
                "player_label": inst.get("player_label") or inst["id"],
                "player": inst.get("player"),
                "loopback_device": inst.get("loopback_device") or "",
                "channel_id": pick["channel_id"],
                "shortcut_id": pick.get("shortcut_id") or pick["channel_id"],
                "guide_name": pick.get("guide_name"),
                "group": pick.get("group"),
                "number": pick.get("number"),
                "slot": pick.get("slot"),
                "prominence": pick.get("prominence"),
                "genres": list(pick.get("genres") or []),
                "nav_route": pick.get("nav_route"),
                "open_via": pick.get("open_via")
                or ("nav" if pick.get("nav_route") else ("search" if pick.get("search_query") else None)),
                "search_query": pick.get("search_query"),
                "any_us_local": bool(pick.get("any_us_local")),
                "preferred_markets": list(PRIORITY_MARKETS[:5]) if pick.get("any_us_local") else [],
                "local": local_pick,
                "open_command": (
                    f"python -m tools.windows_lab open local --network {local_pick['network']}"
                    f" --market \"{local_pick['market']}\" --instance {inst['id']}"
                    if local_pick
                    else (
                        f"python -m tools.windows_lab nav run --route {pick['nav_route']}"
                        f" --instance {inst['id']}"
                        if pick.get("nav_route")
                        else None
                    )
                ),
                "chunk_minutes": effective_chunk,
                "media": "av",
                "open_hint": pick.get("open_hint"),
                "label": pick.get("guide_name") or pick["channel_id"],
                "why": ", ".join(reason_parts),
                "do_not_apply_example_recipe": True,
                "dataset_tags": (
                    {
                        "source_kind": "streamers_us_local",
                        "network": local_pick["network"],
                        "market": local_pick["market"],
                        "call_letters": local_pick["calls"],
                        "diversity": "multi_dma_linear",
                    }
                    if local_pick
                    else {
                        "source_kind": "streamers_demand",
                        "channel_id": pick["channel_id"],
                        "genres": list(pick.get("genres") or []),
                    }
                ),
            }
        )

    plan = {
        "version": 3,
        "built_utc": now.isoformat(),
        "local_et": local.isoformat(),
        "daypart": dp,
        "hierarchy": hier,
        "roi_ladder": list(ROI_LADDER),
        "record_priority": record_priority_queue(
            root, now=local, include_listings=include_listings, limit=16
        ),
        "regimented_block": block,
        "regimented_chunks_48h": regimen_chunks[:72],
        "chunk_minutes": effective_chunk,
        "live_windows": windows,
        "live_preempt": bool(active_live),
        "live_kind": hier.get("live_kind"),
        "coverage_gaps": gaps[:8],
        "demand_pool_top": [
            {
                "channel_id": r.get("channel_id"),
                "slot": r.get("slot"),
                "nav_route": r.get("nav_route"),
                "search_query": r.get("search_query"),
                "channel_minutes": r.get("channel_minutes"),
                "roi_rank": r.get("roi_rank"),
                "roi_band": r.get("roi_band"),
                "data_need": r.get("data_need"),
                "regimen_rank": r.get("regimen_rank"),
                "from_listings": bool(r.get("from_listings")),
            }
            for r in ranked[:12]
        ],
        "capacity": {
            "k": len(instances),
            "ready_instances": len(instances),
            "max_concurrent_streamers": k,
            "isolation_ok": bool(iso.get("ok")),
            "guidance": (
                "Assign exactly K distinct feeds by viewers×data-need. "
                "20m chunks for news/day fill; 60m for live sports/awards/majors. "
                "Idle capacity is a bug."
            ),
        },
        "assignments": assignments,
        "deferred": [
            "PPV / Holiday loading cards",
            "Empty NCAA/NFL numbered event slots",
            "Full listings API for every DMA tip",
        ],
        "owner_action": (
            "Agent owns guide confirm + capture plan. Listings propose; guide disposes. "
            "Do not merge farm labels into optical gold."
        ),
        "next_commands": [
            "python -m tools.windows_lab farm plan",
            "python -m tools.windows_lab farm schedule-from-plan",
            "python -m tools.windows_lab farm listings-refresh",
            "python -m tools.windows_lab farm board",
            "python -m tools.windows_lab farm capacity",
        ],
    }
    path = capture_plan_path(root)
    path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    return plan


def _active_plan_job_for_instance(
    instance_id: str, channel_id: str, root: Path | None
) -> dict[str, Any] | None:
    """Return an in-window scheduled job already targeting this channel on the instance."""
    try:
        from .scheduler import load_jobs
    except Exception:
        return None
    now = _now_utc()
    cid = str(channel_id or "").upper()
    for job in load_jobs(root).get("jobs") or []:
        if str(job.get("instance_id") or "") != instance_id:
            continue
        if str(job.get("channel_id") or job.get("shortcut_id") or "").upper() != cid:
            continue
        if str(job.get("status") or "") not in {
            "scheduled",
            "due",
            "running",
            "live",
            "starting",
            "started",
        }:
            continue
        try:
            start = datetime.fromisoformat(str(job.get("start_utc")).replace("Z", "+00:00"))
        except Exception:
            continue
        mins = float(job.get("minutes") or 20.0)
        if start - timedelta(minutes=15) <= now <= start + timedelta(minutes=mins + 30):
            return job
    return None


def schedule_from_plan(
    root: Path | None = None,
    *,
    chunk_minutes: int | None = None,
    dry_run: bool = False,
    rebuild_plan: bool = True,
) -> dict[str, Any]:
    """Materialize recording-schedule assignments as locked scheduler jobs (idempotent).

    Honors agent overwrite in ``recording_schedule_override.json``. Skips retune
    materialization noise when assignment already says ``on_correct_channel``.
    """
    root = ensure_data_layout(root)
    from .recording_schedule import publish_recording_schedule
    from .scheduler import add_job
    from .locks import acquire, get_lock, release

    board = publish_recording_schedule(root, rebuild_plan=rebuild_plan)
    plan = _load_json(capture_plan_path(root)) or {}
    assignments = list(board.get("assignments") or [])
    created: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    start_at = _now_utc().isoformat()
    for a in assignments:
        iid = str(a.get("instance_id") or "")
        cid = str(a.get("channel_id") or "")
        if not iid or not cid:
            skipped.append({"reason": "missing_instance_or_channel", "row": a})
            continue
        hold_correct = bool(a.get("on_correct_channel") or a.get("action") == "hold")
        existing = _active_plan_job_for_instance(iid, cid, root)
        if existing:
            skipped.append(
                {
                    "reason": (
                        "already_on_correct_channel"
                        if hold_correct
                        else "already_scheduled"
                    ),
                    "instance_id": iid,
                    "channel_id": cid,
                    "job_id": existing.get("job_id"),
                    "hold": hold_correct,
                }
            )
            # Ensure soft lock points at this job when free / starting_*.
            # Never nav — player already correct or job already locked.
            if not dry_run:
                lock = get_lock("streamers", iid, root=root)
                sess = str((lock or {}).get("session_id") or "")
                if not lock or sess.startswith("starting_"):
                    if lock and str(lock.get("job_id") or "") != str(existing.get("job_id")):
                        release("streamers", iid, root=root)
                    ok, _row = acquire(
                        "streamers",
                        iid,
                        session_id=f"starting_{existing['job_id']}",
                        job_id=str(existing["job_id"]),
                        root=root,
                        allow_upgrade_job_id=str(existing["job_id"]),
                    )
                    if not ok and sess.startswith("starting_"):
                        release("streamers", iid, root=root)
                        acquire(
                            "streamers",
                            iid,
                            session_id=f"starting_{existing['job_id']}",
                            job_id=str(existing["job_id"]),
                            root=root,
                        )
            continue
        mins = float(chunk_minutes or a.get("chunk_minutes") or 20)
        guide = None
        if a.get("search_query"):
            guide = {"search_query": a["search_query"], "title_hint": a.get("guide_name")}
        payload = {
            "source_kind": "streamers",
            "channel_id": cid,
            "start_at": start_at,
            "minutes": mins,
            "media": str(a.get("media") or "av"),
            "instance_id": iid,
            "label": str(a.get("label") or a.get("guide_name") or cid),
            "shortcut_id": str(a.get("shortcut_id") or cid),
            "open_via": a.get("open_via"),
            "nav_route": a.get("nav_route"),
            "guide": guide,
            "apply_channel": False,
        }
        if dry_run:
            created.append({"dry_run": True, **payload})
            continue
        # Don't steal a live capture session — only replace soft starting_ locks.
        lock = get_lock("streamers", iid, root=root)
        if lock and not str(lock.get("session_id") or "").startswith("starting_"):
            skipped.append(
                {
                    "reason": "live_lock_held",
                    "instance_id": iid,
                    "channel_id": cid,
                    "lock_session": lock.get("session_id"),
                    "lock_job_id": lock.get("job_id"),
                }
            )
            continue
        if lock and str(lock.get("session_id") or "").startswith("starting_"):
            release("streamers", iid, root=root)
        job = add_job(
            source_kind="streamers",
            channel_id=cid,
            start_at=start_at,
            minutes=mins,
            media=str(a.get("media") or "av"),
            instance_id=iid,
            label=str(a.get("label") or a.get("guide_name") or cid),
            shortcut_id=str(a.get("shortcut_id") or cid),
            open_via=str(a.get("open_via") or "") or None,
            nav_route=str(a.get("nav_route") or "") or None,
            guide=guide,
            apply_channel=False,
            root=root,
        )
        try:
            ok, row = acquire(
                "streamers",
                iid,
                session_id=f"starting_{job['job_id']}",
                job_id=job["job_id"],
                root=root,
                allow_upgrade_job_id=job["job_id"],
            )
            if not ok:
                job = {**job, "lock_error": "acquire_failed", "existing_lock": row}
        except Exception as exc:  # noqa: BLE001
            job = {**job, "lock_error": str(exc)}
        created.append(job)

    out = {
        "ok": True,
        "dry_run": dry_run,
        "plan_built_utc": plan.get("built_utc") or board.get("built_utc"),
        "schedule_source": board.get("source"),
        "override_active": bool(board.get("override_active")),
        "assignments": len(assignments),
        "jobs": created,
        "skipped": skipped,
        "schedule_url": (board.get("urls") or {}).get("local"),
    }
    out_path = indexes_dir(root) / "schedule_from_plan.json"
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    return out


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

    sp = sub.add_parser("plan", help="Build capture_plan.json from demand pool + gaps")
    sp.add_argument("--chunk-minutes", type=int, default=20)
    sp.add_argument("--max-streams", type=int, default=None, help="Override top-K stream count")
    sp.add_argument("--no-listings", action="store_true", help="Skip internet listings enrich")

    sub.add_parser("board", help="Rebuild coverage board JSON + markdown")
    sub.add_parser("capacity", help="Report parallel instance capacity")
    dp = sub.add_parser("dispatch", help="Write per-instance capture dispatch sheet")
    dp.add_argument("--dry-run", action="store_true", default=True)
    dp.add_argument("--execute", action="store_true", help="Also schedule-from-plan (locked jobs)")

    sfp = sub.add_parser(
        "schedule-from-plan",
        help="Materialize capture_plan assignments as locked scheduler jobs",
    )
    sfp.add_argument("--dry-run", action="store_true")
    sfp.add_argument("--chunk-minutes", type=int, default=None)
    sfp.add_argument("--no-rebuild", action="store_true")

    lr = sub.add_parser("listings-refresh", help="Fetch internet listings into listings_cache.json")
    lr.add_argument("--days", type=int, default=3)
    lr.add_argument("--force", action="store_true")

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
        plan = build_capture_plan(
            root,
            chunk_minutes=args.chunk_minutes,
            max_streams=args.max_streams,
            include_listings=not bool(args.no_listings),
        )
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
        report = dispatch_report(root, dry_run=dry)
        if args.execute:
            report["schedule_from_plan"] = schedule_from_plan(root, dry_run=False)
        print(json.dumps(report, indent=2))
        return 0
    if args.cmd == "schedule-from-plan":
        print(
            json.dumps(
                schedule_from_plan(
                    root,
                    chunk_minutes=args.chunk_minutes,
                    dry_run=bool(args.dry_run),
                    rebuild_plan=not bool(args.no_rebuild),
                ),
                indent=2,
            )
        )
        return 0
    if args.cmd == "listings-refresh":
        from .listings_enrich import fetch_listings

        print(
            json.dumps(
                fetch_listings(root, days=int(args.days), force=bool(args.force)),
                indent=2,
            )
        )
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
