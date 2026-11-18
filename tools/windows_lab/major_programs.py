"""Major US appointment-TV programs the schedule UI / farm should know cold.

Owner does not need to remember channel, DOW, or time — this catalog does.
Desk still opens via Streamers guide search; network + schedule are hints for
humans and for hot-window highlighting.

Times are Eastern wall-clock typical slots (seasonal shows may be dark).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

# weekdays: Mon=0 … Sun=6 (Python datetime)
# start/end: "HH:MM" ET typical air window
MAJOR_PROGRAMS: dict[str, dict[str, Any]] = {
    # —— ABC ——
    "DWTS": {
        "label": "Dancing with the Stars",
        "airs_on": "ABC",
        "airs_group": "US ABC SECTION",
        "home_channel_id": "ABC_LOCAL_FLAGSHIP",
        "search_query": "Dancing with the Stars",
        "weekdays": (1,),  # Tue
        "start": "20:00",
        "end": "22:00",
        "genres": ["live_competition"],
        "roi": "live_competition",
        "seasonal": True,
        "keywords": "dwts dancing with the stars abc tuesday",
    },
    "THE_BACHELOR": {
        "label": "The Bachelor",
        "airs_on": "ABC",
        "airs_group": "US ABC SECTION",
        "home_channel_id": "ABC_LOCAL_FLAGSHIP",
        "search_query": "The Bachelor",
        "weekdays": (0,),  # Mon (typical); midseason when ordered
        "start": "20:00",
        "end": "22:00",
        "genres": ["appointment_reality", "reality_tv"],
        "roi": "appointment_reality",
        "seasonal": True,
        "keywords": "bachelor nation abc monday romance",
    },
    "THE_BACHELORETTE": {
        "label": "The Bachelorette",
        "airs_on": "ABC",
        "airs_group": "US ABC SECTION",
        "home_channel_id": "ABC_LOCAL_FLAGSHIP",
        "search_query": "The Bachelorette",
        "weekdays": (0,),
        "start": "20:00",
        "end": "22:00",
        "genres": ["appointment_reality", "reality_tv"],
        "roi": "appointment_reality",
        "seasonal": True,
        "keywords": "bachelorette bachelor nation abc",
    },
    "BACHELOR_IN_PARADISE": {
        "label": "Bachelor in Paradise",
        "airs_on": "ABC",
        "airs_group": "US ABC SECTION",
        "home_channel_id": "ABC_LOCAL_FLAGSHIP",
        "search_query": "Bachelor in Paradise",
        "weekdays": (0,),
        "start": "20:00",
        "end": "22:00",
        "genres": ["appointment_reality", "reality_tv"],
        "roi": "appointment_reality",
        "seasonal": True,
        "keywords": "bachelor in paradise bip abc summer",
    },
    "AMERICAN_IDOL": {
        "label": "American Idol",
        "airs_on": "ABC",
        "airs_group": "US ABC SECTION",
        "home_channel_id": "ABC_LOCAL_FLAGSHIP",
        "search_query": "American Idol",
        "weekdays": (6, 0),  # Sun + Mon typical
        "start": "20:00",
        "end": "22:00",
        "genres": ["live_competition"],
        "roi": "live_competition",
        "seasonal": True,
        "keywords": "american idol abc singing competition",
    },
    "SHARK_TANK": {
        "label": "Shark Tank",
        "airs_on": "ABC",
        "airs_group": "US ABC SECTION",
        "home_channel_id": "ABC_LOCAL_FLAGSHIP",
        "search_query": "Shark Tank",
        "weekdays": (4,),  # often Fri; also Wed blocks
        "start": "20:00",
        "end": "21:00",
        "genres": ["appointment_reality", "reality_tv"],
        "roi": "appointment_reality",
        "seasonal": True,
        "keywords": "shark tank abc business",
    },
    "CMA_AWARDS": {
        "label": "CMA Awards",
        "airs_on": "ABC",
        "airs_group": "US ABC SECTION",
        "home_channel_id": "ABC_LOCAL_FLAGSHIP",
        "search_query": "CMA",
        "weekdays": (2,),  # Wed special
        "start": "20:00",
        "end": "23:00",
        "genres": ["live_awards"],
        "roi": "live_awards",
        "seasonal": True,
        "special": True,
        "keywords": "cma awards country music abc",
    },
    "OSCARS": {
        "label": "Academy Awards (Oscars)",
        "airs_on": "ABC",
        "airs_group": "US ABC SECTION",
        "home_channel_id": "ABC_LOCAL_FLAGSHIP",
        "search_query": "Oscars",
        "weekdays": (6,),  # Sun special (Mar)
        "start": "19:00",
        "end": "23:00",
        "genres": ["live_awards"],
        "roi": "live_awards",
        "seasonal": True,
        "special": True,
        "keywords": "oscars academy awards abc",
    },
    # —— CBS ——
    "SURVIVOR": {
        "label": "Survivor",
        "airs_on": "CBS",
        "airs_group": "US CBS SECTION",
        "home_channel_id": "CBS_LOCAL_FLAGSHIP",
        "search_query": "Survivor",
        "weekdays": (2,),  # Wed
        "start": "20:00",
        "end": "21:30",
        "genres": ["appointment_reality", "reality_tv"],
        "roi": "appointment_reality",
        "seasonal": True,
        "keywords": "survivor cbs wednesday",
    },
    "THE_AMAZING_RACE": {
        "label": "The Amazing Race",
        "airs_on": "CBS",
        "airs_group": "US CBS SECTION",
        "home_channel_id": "CBS_LOCAL_FLAGSHIP",
        "search_query": "Amazing Race",
        "weekdays": (2,),  # Wed after Survivor
        "start": "21:30",
        "end": "23:00",
        "genres": ["appointment_reality", "reality_tv"],
        "roi": "appointment_reality",
        "seasonal": True,
        "keywords": "amazing race cbs wednesday",
    },
    "BIG_BROTHER": {
        "label": "Big Brother",
        "airs_on": "CBS",
        "airs_group": "US CBS SECTION",
        "home_channel_id": "CBS_LOCAL_FLAGSHIP",
        "search_query": "Big Brother",
        "weekdays": (3, 6, 2),  # Thu / Sun / Wed summer pattern
        "start": "20:00",
        "end": "21:00",
        "genres": ["appointment_reality", "reality_tv"],
        "roi": "appointment_reality",
        "seasonal": True,
        "keywords": "big brother cbs summer reality",
    },
    "SIXTY_MINUTES": {
        "label": "60 Minutes",
        "airs_on": "CBS",
        "airs_group": "US CBS SECTION",
        "home_channel_id": "CBS_LOCAL_FLAGSHIP",
        "search_query": "60 Minutes",
        "weekdays": (6,),
        "start": "19:00",
        "end": "20:00",
        "genres": ["news_cable", "primetime_network"],
        "roi": "primetime_network",
        "seasonal": False,
        "keywords": "60 minutes cbs sunday news magazine",
    },
    # —— NBC ——
    "THE_VOICE": {
        "label": "The Voice",
        "airs_on": "NBC",
        "airs_group": "US NBC SECTION",
        "home_channel_id": "NBC_LOCAL_FLAGSHIP",
        "search_query": "The Voice",
        "weekdays": (0,),  # Mon (sometimes Tue too)
        "start": "20:00",
        "end": "22:00",
        "genres": ["live_competition"],
        "roi": "live_competition",
        "seasonal": True,
        "keywords": "the voice nbc monday singing",
    },
    "AMERICAS_GOT_TALENT": {
        "label": "America's Got Talent",
        "airs_on": "NBC",
        "airs_group": "US NBC SECTION",
        "home_channel_id": "NBC_LOCAL_FLAGSHIP",
        "search_query": "America's Got Talent",
        "weekdays": (1, 2),  # Tue/Wed summer
        "start": "20:00",
        "end": "22:00",
        "genres": ["live_competition"],
        "roi": "live_competition",
        "seasonal": True,
        "keywords": "agt americas got talent nbc summer",
    },
    "THE_TRAITORS": {
        "label": "The Traitors",
        "airs_on": "NBC",
        "airs_group": "US NBC SECTION",
        "home_channel_id": "NBC_LOCAL_FLAGSHIP",
        "search_query": "The Traitors",
        "weekdays": (3,),  # Thu
        "start": "20:00",
        "end": "22:00",
        "genres": ["appointment_reality", "reality_tv"],
        "roi": "appointment_reality",
        "seasonal": True,
        "keywords": "traitors nbc thursday peacocks",
    },
    "SNL": {
        "label": "Saturday Night Live",
        "airs_on": "NBC",
        "airs_group": "US NBC SECTION",
        "home_channel_id": "NBC_LOCAL_FLAGSHIP",
        "search_query": "Saturday Night Live",
        "weekdays": (5,),  # Sat
        "start": "23:30",
        "end": "01:00",
        "genres": ["live_competition", "primetime_network"],
        "roi": "primetime_network",
        "seasonal": True,
        "keywords": "snl saturday night live nbc",
    },
    # —— FOX ——
    "HELLS_KITCHEN": {
        "label": "Hell's Kitchen",
        "airs_on": "FOX",
        "airs_group": "US FOX SECTION",
        "home_channel_id": "FOX_LOCAL_FLAGSHIP",
        "search_query": "Hell's Kitchen",
        "weekdays": (3,),  # Thu
        "start": "20:00",
        "end": "21:00",
        "genres": ["appointment_reality", "reality_tv"],
        "roi": "appointment_reality",
        "seasonal": True,
        "keywords": "hells kitchen fox thursday gordon ramsay",
    },
    "THE_MASKED_SINGER": {
        "label": "The Masked Singer",
        "airs_on": "FOX",
        "airs_group": "US FOX SECTION",
        "home_channel_id": "FOX_LOCAL_FLAGSHIP",
        "search_query": "Masked Singer",
        "weekdays": (2,),
        "start": "20:00",
        "end": "21:00",
        "genres": ["live_competition"],
        "roi": "live_competition",
        "seasonal": True,
        "keywords": "masked singer fox",
    },
    "MASTERCHEF": {
        "label": "MasterChef",
        "airs_on": "FOX",
        "airs_group": "US FOX SECTION",
        "home_channel_id": "FOX_LOCAL_FLAGSHIP",
        "search_query": "MasterChef",
        "weekdays": (2,),
        "start": "20:00",
        "end": "21:00",
        "genres": ["appointment_reality", "reality_tv"],
        "roi": "appointment_reality",
        "seasonal": True,
        "keywords": "masterchef fox cooking",
    },
    "SPECIAL_FORCES": {
        "label": "Special Forces: World's Toughest Test",
        "airs_on": "FOX",
        "airs_group": "US FOX SECTION",
        "home_channel_id": "FOX_LOCAL_FLAGSHIP",
        "search_query": "Special Forces",
        "weekdays": (3,),
        "start": "21:00",
        "end": "22:00",
        "genres": ["appointment_reality", "reality_tv"],
        "roi": "appointment_reality",
        "seasonal": True,
        "keywords": "special forces fox toughest test",
    },
    # —— Sports appointment (program-shaped, not just nav channel) ——
    "TNF": {
        "label": "Thursday Night Football",
        "airs_on": "ESPN / Prime",
        "airs_group": "US SPORTS",
        "home_channel_id": "ESPN_US",
        "search_query": "Thursday Night Football",
        "nav_route": "ESPN_US",
        "weekdays": (3,),
        "start": "20:00",
        "end": "23:30",
        "genres": ["nfl", "live_nfl"],
        "roi": "live_nfl",
        "seasonal": True,
        "keywords": "tnf thursday night football espn nfl",
    },
    "MNF": {
        "label": "Monday Night Football",
        "airs_on": "ESPN / ABC",
        "airs_group": "US SPORTS",
        "home_channel_id": "ESPN_US",
        "search_query": "Monday Night Football",
        "nav_route": "ESPN_US",
        "weekdays": (0,),
        "start": "20:00",
        "end": "23:45",
        "genres": ["nfl", "live_nfl"],
        "roi": "live_nfl",
        "seasonal": True,
        "keywords": "mnf monday night football espn abc nfl",
    },
}


_DOW = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def _parse_hhmm(value: str) -> tuple[int, int]:
    h, m = str(value or "20:00").split(":")
    return int(h), int(m)


def schedule_label(meta: dict[str, Any]) -> str:
    """e.g. 'Tue 8–10p' or 'seasonal'."""
    days = tuple(meta.get("weekdays") or ())
    if not days and meta.get("special"):
        return "special"
    if not days:
        return "seasonal" if meta.get("seasonal") else ""
    day_s = "/".join(_DOW[d] for d in days if 0 <= int(d) <= 6)
    sh, sm = _parse_hhmm(str(meta.get("start") or "20:00"))
    eh, em = _parse_hhmm(str(meta.get("end") or "22:00"))

    def clock(h: int, m: int) -> str:
        ap = "a" if h < 12 else "p"
        h12 = h % 12 or 12
        return f"{h12}{(':' + f'{m:02d}') if m else ''}{ap}"

    return f"{day_s} {clock(sh, sm)}–{clock(eh, em)}"


def program_short(meta: dict[str, Any]) -> str:
    label = str(meta.get("label") or "")
    airs = str(meta.get("airs_on") or "")
    sched = schedule_label(meta)
    parts = [label]
    if airs:
        parts.append(f"on {airs}")
    if sched:
        parts.append(sched)
    return " · ".join(parts)


def as_program_meta() -> dict[str, dict[str, Any]]:
    """Shape used by recording_schedule.PROGRAM_META / catalog."""
    out: dict[str, dict[str, Any]] = {}
    for cid, raw in MAJOR_PROGRAMS.items():
        sched = schedule_label(raw)
        out[cid] = {
            "label": raw["label"],
            "kind": "program",
            "group": "Programs · live events",
            "airs_on": raw.get("airs_on"),
            "airs_group": raw.get("airs_group"),
            "home_channel_id": raw.get("home_channel_id"),
            "open_via": "nav" if raw.get("nav_route") else "search",
            "nav_route": raw.get("nav_route") or "",
            "search_query": raw.get("search_query"),
            "weekdays": tuple(raw.get("weekdays") or ()),
            "start": raw.get("start"),
            "end": raw.get("end"),
            "schedule": sched,
            "seasonal": bool(raw.get("seasonal")),
            "special": bool(raw.get("special")),
            "genres": list(raw.get("genres") or []),
            "roi": raw.get("roi"),
            "keywords": f"{raw.get('keywords') or ''} {sched}".strip(),
        }
    return out


def listing_hooks() -> list[tuple[tuple[str, ...], dict[str, Any]]]:
    """Needles → seed overlays for listings_enrich."""
    hooks: list[tuple[tuple[str, ...], dict[str, Any]]] = []
    for cid, raw in MAJOR_PROGRAMS.items():
        label = str(raw["label"]).lower()
        needles = [label]
        # short aliases
        if cid == "DWTS":
            needles += ["dancing with the stars", "dwts"]
        elif cid == "CMA_AWARDS":
            needles += ["cma awards", "cma country", "country music association"]
        elif cid == "THE_AMAZING_RACE":
            needles += ["amazing race"]
        elif cid == "AMERICAS_GOT_TALENT":
            needles += ["america's got talent", "americas got talent", "agt"]
        elif cid == "THE_MASKED_SINGER":
            needles += ["masked singer"]
        elif cid == "HELLS_KITCHEN":
            needles += ["hell's kitchen", "hells kitchen"]
        elif cid == "SIXTY_MINUTES":
            needles += ["60 minutes"]
        elif cid == "SNL":
            needles += ["saturday night live", "snl"]
        elif cid == "TNF":
            needles += ["thursday night football"]
        elif cid == "MNF":
            needles += ["monday night football"]
        hooks.append(
            (
                tuple(dict.fromkeys(needles)),
                {
                    "channel_id": cid,
                    "slot": "live_event",
                    "genres": list(raw.get("genres") or ["reality_tv"]),
                    "search_query": raw.get("search_query"),
                    "nav_route": raw.get("nav_route"),
                    "open_via": "nav" if raw.get("nav_route") else "search",
                    "live_sensitive": True,
                    "listing_network_hint": raw.get("airs_on"),
                },
            )
        )
    return hooks


def is_hot_now(meta: dict[str, Any], when: datetime | None = None) -> bool:
    """True if this ET clock falls on a typical air weekday (evening window ±1h)."""
    local = (when or datetime.now(tz=ET)).astimezone(ET)
    days = tuple(meta.get("weekdays") or ())
    if not days or local.weekday() not in set(days):
        return False
    sh, sm = _parse_hhmm(str(meta.get("start") or "20:00"))
    eh, em = _parse_hhmm(str(meta.get("end") or "22:00"))
    start = local.replace(hour=sh, minute=sm, second=0, microsecond=0) - timedelta(hours=1)
    end = local.replace(hour=eh, minute=em, second=0, microsecond=0) + timedelta(minutes=30)
    if end <= start:
        end += timedelta(days=1)
    return start <= local <= end


def upcoming_program_windows(
    when: datetime | None = None,
    *,
    hours: int = 48,
) -> list[dict[str, Any]]:
    """Next airings from the static catalog (for schedule board / queue)."""
    local = (when or datetime.now(tz=ET)).astimezone(ET)
    horizon = local + timedelta(hours=hours)
    rows: list[dict[str, Any]] = []
    for cid, raw in MAJOR_PROGRAMS.items():
        days = tuple(raw.get("weekdays") or ())
        if not days:
            continue
        sh, sm = _parse_hhmm(str(raw.get("start") or "20:00"))
        eh, em = _parse_hhmm(str(raw.get("end") or "22:00"))
        # Scan next 8 days for matching DOW.
        for i in range(0, 9):
            day = (local + timedelta(days=i)).replace(
                hour=sh, minute=sm, second=0, microsecond=0
            )
            if day.weekday() not in set(days):
                continue
            end = day.replace(hour=eh, minute=em, second=0, microsecond=0)
            if end <= day:
                end += timedelta(days=1)
            if end < local or day > horizon:
                continue
            rows.append(
                {
                    "id": cid,
                    "label": raw["label"],
                    "airs_on": raw.get("airs_on"),
                    "airs_group": raw.get("airs_group"),
                    "home_channel_id": raw.get("home_channel_id"),
                    "search_query": raw.get("search_query"),
                    "nav_route": raw.get("nav_route"),
                    "start_et": day.isoformat(),
                    "end_et": end.isoformat(),
                    "schedule": schedule_label(raw),
                    "short": program_short(raw),
                    "hot": day.date() == local.date(),
                    "stream_a": cid,
                    "stream_b": (
                        "FOX_NEWS_US"
                        if not str(raw.get("airs_on") or "").startswith("ESPN")
                        else "FOX_NEWS_US"
                    ),
                }
            )
    rows.sort(key=lambda r: str(r.get("start_et") or ""))
    return rows[:40]


def priority_program_switches(when: datetime | None = None) -> list[dict[str, Any]]:
    """Emergency-tap presets for major programs (hot night first)."""
    local = when or datetime.now(tz=ET)
    out: list[dict[str, Any]] = []
    for cid, raw in MAJOR_PROGRAMS.items():
        if raw.get("roi") in {"news_cable"}:
            continue
        hot = is_hot_now(raw, local)
        # Pair: program on P0, news or second sports on P1
        stream_b = "FOX_NEWS_US"
        if raw.get("home_channel_id") and cid in {"TNF", "MNF"}:
            stream_b = "FOX_NEWS_US"
        elif str(raw.get("airs_on")) in {"CBS", "NBC", "FOX"}:
            # keep news as second stream for dual ROI
            stream_b = "FOX_NEWS_US"
        out.append(
            {
                "id": f"prog_{cid.lower()}",
                "program_id": cid,
                "label": f"{raw['label']} (on {raw.get('airs_on')})",
                "kind": "show" if "nfl" not in (raw.get("genres") or []) else "sports",
                # Sports often nav to ESPN; other majors open via guide search id.
                "stream_a": raw.get("nav_route") or cid,
                "stream_b": stream_b,
                "chunk_minutes": 60,
                "hold_hours": 3,
                "hot": hot,
                "airs_on": raw.get("airs_on"),
                "schedule": schedule_label(raw),
                "pair_note": f"{schedule_label(raw)} · search “{raw.get('search_query')}”",
                "why": f"emergency switch → {raw['label']}",
            }
        )
    out.sort(key=lambda r: (0 if r.get("hot") else 1, str(r.get("label"))))
    return out
