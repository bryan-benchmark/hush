"""Internet listings enrichment for the capture demand pool.

Listings *propose* jobs (24–72h look-ahead). Streamers guide still confirms
and opens — never treat a web title as proof of picture.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .config import ensure_data_layout

ET = ZoneInfo("America/New_York")
TVMAZE_SCHEDULE = "https://api.tvmaze.com/schedule?country=US&date={date}"
CACHE_NAME = "listings_cache.json"
USER_AGENT = "ohush-coverage-farm/1.0"

def _build_show_hooks() -> list[tuple[tuple[str, ...], dict[str, Any]]]:
    """Major programs + cable news needles → demand overlays."""
    from .major_programs import listing_hooks

    hooks = list(listing_hooks())
    hooks.extend(
        [
            (
                ("fox news",),
                {
                    "channel_id": "FOX_NEWS_US",
                    "slot": "main_news",
                    "genres": ["news_cable"],
                    "nav_route": "FOX_NEWS_US",
                    "open_via": "nav",
                    "live_sensitive": False,
                },
            ),
            (
                ("cnn",),
                {
                    "channel_id": "CNN_US",
                    "slot": "main_news",
                    "genres": ["news_cable"],
                    "nav_route": "CNN_US",
                    "open_via": "nav",
                    "live_sensitive": False,
                },
            ),
        ]
    )
    return hooks


_SHOW_HOOKS: list[tuple[tuple[str, ...], dict[str, Any]]] = _build_show_hooks()


def listings_cache_path(root: Path | None = None) -> Path:
    return ensure_data_layout(root) / "indexes" / CACHE_NAME


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _fetch_tvmaze_day(day: datetime, *, timeout: float = 12.0) -> list[dict[str, Any]]:
    url = TVMAZE_SCHEDULE.format(date=day.strftime("%Y-%m-%d"))
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        raw = json.loads(resp.read().decode("utf-8"))
    return list(raw) if isinstance(raw, list) else []


def fetch_listings(
    root: Path | None = None,
    *,
    days: int = 3,
    force: bool = False,
    rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Fetch or load US schedule listings; cache under indexes/listings_cache.json.

    ``rows`` injects fixture data (unit tests) and skips the network.
    """
    root = ensure_data_layout(root)
    path = listings_cache_path(root)
    if rows is None and not force and path.is_file():
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
            fetched = datetime.fromisoformat(str(cached.get("fetched_utc")).replace("Z", "+00:00"))
            if _now_utc() - fetched < timedelta(hours=6):
                return cached
        except Exception:
            pass

    events: list[dict[str, Any]] = []
    errors: list[str] = []
    if rows is not None:
        events = list(rows)
    else:
        local = datetime.now(ET)
        for offset in range(max(1, int(days))):
            day = (local + timedelta(days=offset)).date()
            day_dt = datetime(day.year, day.month, day.day, tzinfo=ET)
            try:
                for item in _fetch_tvmaze_day(day_dt):
                    events.append(_normalize_tvmaze(item))
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
                errors.append(f"{day.isoformat()}:{exc}")

    out = {
        "version": 1,
        "fetched_utc": _now_utc().isoformat(),
        "source": "fixture" if rows is not None else "tvmaze",
        "horizon_days": int(days),
        "events": [e for e in events if e],
        "errors": errors,
    }
    path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    return out


def _normalize_tvmaze(item: dict[str, Any]) -> dict[str, Any] | None:
    show = item.get("show") or {}
    name = str(show.get("name") or item.get("name") or "").strip()
    if not name:
        return None
    network = ((show.get("network") or {}) or {}).get("name") or (
        (show.get("webChannel") or {}) or {}
    ).get("name")
    airtime = str(item.get("airtime") or "") or None
    airstamp = str(item.get("airstamp") or "") or None
    return {
        "title": name,
        "network": network,
        "airtime_local": airtime,
        "start_utc": airstamp,
        "runtime_min": item.get("runtime"),
        "genres": list(show.get("genres") or []),
        "source": "tvmaze",
    }


def match_hooks(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map listing titles onto demand-pool seed overlays."""
    hits: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ev in events:
        title = str(ev.get("title") or "").lower()
        for needles, meta in _SHOW_HOOKS:
            if not any(n in title for n in needles):
                continue
            cid = str(meta["channel_id"])
            if cid in seen:
                continue
            seen.add(cid)
            hits.append(
                {
                    **meta,
                    "guide_name": ev.get("title"),
                    "listing_network": ev.get("network"),
                    "listing_start_utc": ev.get("start_utc"),
                    "from_listings": True,
                    "prominence": meta.get("slot") or "live_event",
                    "verified_play": False,
                }
            )
            break
    return hits


def listings_demand_overlays(root: Path | None = None) -> list[dict[str, Any]]:
    cache = fetch_listings(root, days=3, force=False)
    return match_hooks(list(cache.get("events") or []))
