"""Thursday Night Football capture — weekly schedule + farm-loop hold.

TNF jobs record Streamers already tuned to Amazon / Prime football
(`--no-channel-apply`). The farm loop yields Thu 19:00–23:59 ET so
`OHushCaptureFarmRunDue` can own the box.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .channel import save_recipe
from .config import ensure_data_layout
from .scheduler import add_job, list_jobs, load_jobs, save_jobs

ET = ZoneInfo("America/New_York")
CHANNEL_ID = "TNF_PRIME"
INSTANCE_ID = "Nougat32"
# Pregame through postgame window (kickoff typically ~20:15 ET).
START_HOUR = 19
START_MINUTE = 30
DURATION_MINUTES = 270.0  # 19:30 → 00:00 ET
HOLD_START_HOUR = 19
HOLD_END_HOUR = 24  # exclusive via weekday rollover check
WEEKS_AHEAD = 12


def _now_et(now: datetime | None = None) -> datetime:
    return (now or datetime.now(timezone.utc)).astimezone(ET)


def next_thursday_start(now: datetime | None = None, *, include_today: bool = True) -> datetime:
    """Next Thu 19:30 ET (or tonight if still before/during the window)."""
    local = _now_et(now)
    # weekday: Mon=0 … Thu=3
    days_ahead = (3 - local.weekday()) % 7
    if days_ahead == 0 and not include_today:
        days_ahead = 7
    if days_ahead == 0 and include_today:
        # If past the TNF window tonight, jump to next week.
        end = local.replace(hour=23, minute=59, second=59, microsecond=0)
        start = local.replace(hour=START_HOUR, minute=START_MINUTE, second=0, microsecond=0)
        if local > end:
            days_ahead = 7
        elif local > start + timedelta(minutes=DURATION_MINUTES):
            days_ahead = 7
    target = (local + timedelta(days=days_ahead)).replace(
        hour=START_HOUR, minute=START_MINUTE, second=0, microsecond=0
    )
    return target


def thursday_starts(weeks: int = WEEKS_AHEAD, now: datetime | None = None) -> list[datetime]:
    first = next_thursday_start(now, include_today=True)
    return [first + timedelta(days=7 * i) for i in range(max(1, weeks))]


def tnf_hold_active(now: datetime | None = None) -> dict[str, Any]:
    """True Thu 19:00–23:59 ET so farm loop does not steal the instance."""
    local = _now_et(now)
    active = local.weekday() == 3 and HOLD_START_HOUR <= local.hour < HOLD_END_HOUR
    return {
        "active": active,
        "local_et": local.isoformat(),
        "why": (
            "Thu 19:00–23:59 ET — farm loop yields for TNF_PRIME schedule"
            if active
            else "outside TNF hold"
        ),
    }


def ensure_tnf_recipe(root: Path | None = None) -> Path:
    """Document TNF_PRIME. apply_allowed=false — search team, then no-channel-apply."""
    from .streamers_open import ensure_tnf_shortcut

    ensure_tnf_shortcut(root)
    recipe = {
        "channel_id": CHANNEL_ID,
        "source_kind": "streamers",
        "label": "Thursday Night Football (Prime / NFL 01)",
        "verified": True,
        "verified_mode": "no_channel_apply",
        "apply_allowed": False,
        "do_not_apply_example_recipe": True,
        "shortcut_id": CHANNEL_ID,
        "group_hint": "NFL A",
        "search_hint": "home or away team name (sports: search show/team first)",
        "open_path_confirmed_2026_11_12": (
            "python -m tools.windows_lab open play --id TNF_PRIME  OR  "
            "open search --query Commanders --title-contains 'NFL 01' --save-as TNF_PRIME"
        ),
        "launch": {"package": "ar.tvplayer.tv"},
        "steps": [
            {
                "action": "note",
                "text": (
                    "Do not apply this recipe. Sports open = search team/show name first "
                    "(streamers_open), pick NFL 01 live card, keyevent 23, then "
                    "session --no-channel-apply --channel TNF_PRIME. Shortcut lives in "
                    "indexes/streamers_open_shortcuts.json. Skip empty AMZN## slots."
                ),
            }
        ],
        "open_hint": "open play --id TNF_PRIME (search team → NFL 01 → center).",
    }
    return save_recipe(CHANNEL_ID, recipe, root)


def _existing_tnf_starts(root: Path | None = None) -> set[str]:
    starts: set[str] = set()
    for job in list_jobs(root):
        if str(job.get("channel_id") or "") != CHANNEL_ID:
            continue
        if job.get("status") not in ("scheduled", "running", "started", "due"):
            continue
        starts.add(str(job.get("start_utc") or ""))
    return starts


def enqueue_thursdays(
    *,
    weeks: int = WEEKS_AHEAD,
    instance_id: str = INSTANCE_ID,
    minutes: float = DURATION_MINUTES,
    root: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Ensure the next N Thursday TNF jobs exist (idempotent by start_utc)."""
    ensure_tnf_recipe(root)
    existing = _existing_tnf_starts(root)
    added: list[dict[str, Any]] = []
    skipped: list[str] = []
    for start_et in thursday_starts(weeks, now):
        start_utc = start_et.astimezone(timezone.utc).isoformat()
        if start_utc in existing:
            skipped.append(start_utc)
            continue
        job = add_job(
            source_kind="streamers",
            channel_id=CHANNEL_ID,
            start_at=start_utc,
            minutes=minutes,
            media="av",
            instance_id=instance_id,
            rights_status="authorized",
            label=f"TNF {start_et.date().isoformat()}",
            apply_channel=False,
            weekly=True,
            guide={
                "search_query": "Commanders",
                "channel_title": "NFL 01",
                "group": "NFL A",
                "source": "tnf_thursday",
                "note": "Sports: search team/show first; title changes weekly — prefer NFL 01 live card",
            },
            shortcut_id=CHANNEL_ID,
            open_via="search",
            root=root,
        )
        added.append(job)
        existing.add(start_utc)
    return {
        "ok": True,
        "channel_id": CHANNEL_ID,
        "added": len(added),
        "skipped_existing": len(skipped),
        "jobs": added,
        "next_start_et": thursday_starts(1, now)[0].isoformat(),
        "hold": tnf_hold_active(now),
    }


def roll_weekly_job(job: dict[str, Any], root: Path | None = None) -> dict[str, Any] | None:
    """After a weekly TNF job starts, ensure the next Thu 19:30 ET slot exists.

    Uses calendar Thursday 19:30 ET — not +7 days from a mid-game restart clock.
    """
    if not job.get("weekly"):
        return None
    if str(job.get("channel_id") or "") != CHANNEL_ID:
        return None
    # Next Thursday after "now", excluding today (tonight already consumed).
    nxt_et = next_thursday_start(include_today=False)
    nxt = nxt_et.astimezone(timezone.utc).isoformat()
    if nxt in _existing_tnf_starts(root):
        return None
    label_date = nxt_et.date().isoformat()
    guide = job.get("guide") or {
        "search_query": "Commanders",
        "channel_title": "NFL 01",
        "group": "NFL A",
        "source": "tnf_thursday",
    }
    return add_job(
        source_kind=str(job["source_kind"]),
        channel_id=str(job["channel_id"]),
        start_at=nxt,
        minutes=float(DURATION_MINUTES),
        media=str(job.get("media") or "av"),
        instance_id=job.get("instance_id"),
        tuner_id=job.get("tuner_id"),
        rights_status=str(job.get("rights_status") or "authorized"),
        label=f"TNF {label_date}",
        apply_channel=bool(job.get("apply_channel", False)),
        weekly=True,
        guide=guide,
        shortcut_id=str(job.get("shortcut_id") or CHANNEL_ID),
        open_via="search",
        root=root,
    )


def status(root: Path | None = None) -> dict[str, Any]:
    jobs = [
        j
        for j in list_jobs(root)
        if str(j.get("channel_id") or "") == CHANNEL_ID
        and j.get("status") in ("scheduled", "running", "started", "due")
    ]
    jobs.sort(key=lambda j: str(j.get("start_utc") or ""))
    return {
        "channel_id": CHANNEL_ID,
        "hold": tnf_hold_active(),
        "scheduled_count": len(jobs),
        "upcoming": jobs[:4],
        "recipe": str(ensure_data_layout(root) / "channel_recipes" / f"{CHANNEL_ID}.json"),
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="TNF Thursday schedule")
    sub = p.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("enqueue", help="Ensure next N Thursday TNF jobs")
    e.add_argument("--weeks", type=int, default=WEEKS_AHEAD)
    e.add_argument("--instance", default=INSTANCE_ID)
    e.add_argument("--minutes", type=float, default=DURATION_MINUTES)
    sub.add_parser("status")
    sub.add_parser("hold")
    sub.add_parser("ensure-recipe")

    args = p.parse_args(argv)
    if args.cmd == "enqueue":
        print(json.dumps(enqueue_thursdays(weeks=args.weeks, instance_id=args.instance, minutes=args.minutes), indent=2))
        return 0
    if args.cmd == "status":
        print(json.dumps(status(), indent=2))
        return 0
    if args.cmd == "hold":
        print(json.dumps(tnf_hold_active(), indent=2))
        return 0
    if args.cmd == "ensure-recipe":
        path = ensure_tnf_recipe()
        print(json.dumps({"ok": True, "path": str(path)}, indent=2))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
