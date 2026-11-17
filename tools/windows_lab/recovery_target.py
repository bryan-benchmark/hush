"""What heartbeat/recover should re-open: the schedule + coverage hierarchy.

Recovery used to ignore the plan and dump every dead stream on Atlanta ABC/WSB.
This module answers: *what would we schedule right now?* — then open that.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .config import ensure_data_layout

# Slots that mean "put a broadcast local on" (US * SECTION).
_LINEAR_SLOTS = frozenset({"main_linear", "main_news", "talk_entertainment"})
# During live windows, prefer game-carrying nets over ABC daytime filler.
_LIVE_NET_ORDER = ("FOX", "CBS", "NBC", "ABC")
_FILLER_ON_AIR = frozenset({"", "ON_AIR_CONTINUE", "ON_AIR"})


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_utc(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except Exception:
        return None


def _is_filler_channel(channel_id: str | None) -> bool:
    cid = str(channel_id or "").strip().upper()
    return (not cid) or cid in _FILLER_ON_AIR or cid.startswith("ON_AIR")


def _job_for_lock(instance_id: str, root: Path | None) -> dict[str, Any] | None:
    try:
        from .locks import get_lock
        from .scheduler import load_jobs

        lock = get_lock("streamers", instance_id, root=root)
        if not lock:
            return None
        jid = lock.get("job_id")
        if not jid:
            return None
        data = load_jobs(root)
        return next(
            (j for j in (data.get("jobs") or []) if str(j.get("job_id")) == str(jid)),
            None,
        )
    except Exception:
        return None


def _due_or_active_jobs(root: Path | None, *, instance_id: str) -> list[dict[str, Any]]:
    """Scheduled / due / running jobs that should own the picture now."""
    try:
        from .scheduler import load_jobs
    except Exception:
        return []
    now = _now()
    out: list[dict[str, Any]] = []
    for job in load_jobs(root).get("jobs") or []:
        status = str(job.get("status") or "")
        if status not in {"scheduled", "due", "running", "live", "starting", "started"}:
            continue
        if _is_filler_channel(str(job.get("channel_id") or job.get("shortcut_id") or "")):
            continue
        start = _parse_utc(str(job.get("start_utc") or ""))
        if start is None:
            continue
        # Own the window from 15m before start through end (+minutes).
        mins = float(job.get("minutes") or 120.0)
        window_start = start - timedelta(minutes=15)
        window_end = start + timedelta(minutes=mins + 15)
        if not (window_start <= now <= window_end):
            continue
        iid = str(job.get("instance_id") or "")
        # Prefer jobs assigned to this instance; allow unassigned / same-fleet steal.
        if iid and iid != instance_id:
            # Other instance's live job — still useful as *what content* to open
            # when this clone is the free filler that should match hierarchy.
            pass
        out.append(job)
    out.sort(
        key=lambda j: (
            0 if str(j.get("instance_id") or "") == instance_id else 1,
            0 if str(j.get("status")) in {"running", "live", "due"} else 1,
            abs((_parse_utc(str(j.get("start_utc"))) or now) - now).total_seconds(),
        )
    )
    return out


def resolve_recovery_target(
    instance_id: str,
    *,
    job: dict[str, Any] | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Pick the schedule/hierarchy target for a dead or stuck stream.

    Priority:
      1. Named lock/job channel (TNF, CMA, CBS_LOCAL, …) — not ON_AIR filler
      2. Due/active scheduled job in its time window
      3. Live-preempt window → game-carrying local net (FOX/CBS/NBC first)
      4. Daypart fill_order → distinct Atlanta/big-DMA local via pick_filler
    """
    root = ensure_data_layout(root)
    job = dict(job or {})
    if not job:
        locked = _job_for_lock(instance_id, root)
        if locked:
            job = dict(locked)

    for blob in (job,):
        cid = str(blob.get("channel_id") or "")
        sid = str(blob.get("shortcut_id") or "")
        if not _is_filler_channel(cid) or (sid and not _is_filler_channel(sid)):
            return {
                "ok": True,
                "kind": "scheduled_job",
                "channel_id": cid or None,
                "shortcut_id": sid or None,
                "search_query": ((blob.get("guide") or {}).get("search_query")),
                "open_via": blob.get("open_via"),
                "nav_route": blob.get("nav_route"),
                "job_id": blob.get("job_id"),
                "label": blob.get("label") or cid or sid,
                "why": "lock_or_passed_job",
                "job": blob,
            }

    due = _due_or_active_jobs(root, instance_id=instance_id)
    if due:
        j = due[0]
        return {
            "ok": True,
            "kind": "scheduled_job",
            "channel_id": j.get("channel_id"),
            "shortcut_id": j.get("shortcut_id"),
            "search_query": ((j.get("guide") or {}).get("search_query")),
            "open_via": j.get("open_via"),
            "nav_route": j.get("nav_route"),
            "job_id": j.get("job_id"),
            "label": j.get("label") or j.get("channel_id"),
            "why": "due_or_active_schedule",
            "job": j,
        }

    hier: dict[str, Any] = {}
    try:
        from .coverage_farm import hierarchy_snapshot

        hier = hierarchy_snapshot()
    except Exception as exc:  # noqa: BLE001
        hier = {"error": str(exc)}

    live = bool(hier.get("live_preempt"))
    fill = list(hier.get("fill_order") or ["main_linear"])
    top_slot = str(fill[0] if fill else "main_linear")

    from .stream_status import pick_filler_network

    if live or top_slot in {"aux_sports", "live_event"}:
        # Sunday/Thu/Mon sports window: sticky unused net (FOX/CBS/…), never dual ABC.
        net = pick_filler_network(instance_id, root=root)
        # If sticky still ABC (higher-index clone), nudge to a game-carrying net.
        if net == "ABC":
            for cand in _LIVE_NET_ORDER:
                if cand == "ABC":
                    continue
                alt = pick_filler_network(instance_id, root=root, preferred=cand)
                if alt != "ABC":
                    net = alt
                    break
        return {
            "ok": True,
            "kind": "live_local",
            "network": net,
            "slot": top_slot,
            "live_preempt": True,
            "label": f"live:{net}",
            "why": "hierarchy_live_preempt",
            "hierarchy": {
                "daypart": hier.get("daypart"),
                "fill_order": fill[:5],
                "live_preempt": True,
            },
        }

    # Non-live: follow fill order. Linear/news → distinct local net.
    preferred = None
    if top_slot in _LINEAR_SLOTS or top_slot == "main_news":
        preferred = None  # sticky per-instance
    net = pick_filler_network(instance_id, root=root, preferred=preferred)
    return {
        "ok": True,
        "kind": "fill_local",
        "network": net,
        "slot": top_slot,
        "live_preempt": False,
        "label": f"{top_slot}:{net}",
        "why": "hierarchy_fill_order",
        "hierarchy": {
            "daypart": hier.get("daypart"),
            "fill_order": fill[:5],
            "live_preempt": False,
        },
    }


def open_recovery_target(
    instance_id: str,
    *,
    job: dict[str, Any] | None = None,
    root: Path | None = None,
    failover: bool = False,
) -> dict[str, Any]:
    """Resolve + open the schedule/hierarchy target on this instance."""
    root = ensure_data_layout(root)
    target = resolve_recovery_target(instance_id, job=job, root=root)
    steps: list[dict[str, Any]] = [{"step": "resolve_target", **{k: target.get(k) for k in ("kind", "why", "label", "network", "channel_id", "shortcut_id", "slot")}}]

    kind = str(target.get("kind") or "")
    if kind == "scheduled_job":
        from .heartbeat_fix import _reopen_channel

        job_blob = dict(target.get("job") or job or {})
        if target.get("nav_route") and not job_blob.get("nav_route"):
            job_blob["nav_route"] = target["nav_route"]
        if target.get("open_via") and not job_blob.get("open_via"):
            job_blob["open_via"] = target["open_via"]
        opened = _reopen_channel(
            instance_id,
            job=job_blob,
            channel_id=str(target.get("channel_id") or "") or None,
            shortcut_id=str(target.get("shortcut_id") or "") or None,
            root=root,
        )
        # Search query stamped on guide when shortcut missing.
        if not opened.get("ok") and target.get("search_query"):
            try:
                from .streamers_open import search_open

                q = str(target["search_query"])
                so = search_open(query=q, instance_id=instance_id, root=root)
                opened = {
                    "ok": bool(so.get("ok")),
                    "via": "schedule_search",
                    "query": q,
                    "result": so,
                }
            except Exception as exc:  # noqa: BLE001
                opened = {"ok": False, "via": "schedule_search", "error": str(exc)}
        steps.append(
            {
                "step": "open_scheduled",
                **{
                    k: opened.get(k)
                    for k in ("ok", "via", "error", "shortcut_id", "channel_id", "query", "nav_route")
                },
            }
        )
        if opened.get("ok") and not opened.get("skipped"):
            return {
                "ok": True,
                "via": "schedule",
                "target": target,
                "steps": steps,
                "network": None,
                "selected_title": None,
                "channel_title": None,
            }
        # Named capture (MNF_ESPN / ESPN2 / …) must NEVER fall through to Atlanta
        # FOX/NBC — that is how locked boxes lost the game feed.
        return {
            "ok": False,
            "via": "schedule_failed_no_local_fallback",
            "error": opened.get("error") or "scheduled_open_failed",
            "target": target,
            "steps": steps,
            "opened": opened,
        }

    net = str(target.get("network") or "")
    if not net:
        from .stream_status import pick_filler_network

        net = pick_filler_network(instance_id, root=root)

    # Live window: open from the *guide* now-cell (GA/AL NFL/CFB). Never fall
    # through to Atlanta flagship — that is how dual recovery kept landing on Opry.
    live_window = kind == "live_local" or bool(target.get("live_preempt"))
    if live_window:
        avoid: set[str] = set()
        try:
            from .stream_status import fleet_rows

            for row in fleet_rows(root):
                if str(row.get("instance_id") or "") == instance_id:
                    continue
                if row.get("program_key"):
                    avoid.add(str(row["program_key"]))
        except Exception:
            pass
        nets: list[str] = []
        if net:
            nets.append(net)
        for n in _LIVE_NET_ORDER:
            if n not in nets:
                nets.append(n)
        from .us_locals import open_live_sports_local

        for try_net in nets:
            try:
                live = open_live_sports_local(
                    try_net,
                    instance_id=instance_id,
                    open_player=True,
                    avoid_program_keys=avoid,
                    root=root,
                )
            except Exception as exc:  # noqa: BLE001
                steps.append(
                    {
                        "step": "open_live_sports",
                        "ok": False,
                        "network": try_net,
                        "error": str(exc),
                    }
                )
                continue
            steps.append(
                {
                    "step": "open_live_sports",
                    "ok": bool(live.get("ok")),
                    "network": try_net,
                    "via": live.get("via"),
                    "error": live.get("error"),
                    "title": live.get("selected_title") or live.get("channel_title"),
                    "program": live.get("program_title"),
                }
            )
            if live.get("ok"):
                return {
                    "ok": True,
                    "via": "live_sports_section",
                    "target": target,
                    "steps": steps,
                    "network": live.get("network") or try_net,
                    "pick": live.get("pick"),
                    "selected_title": live.get("selected_title"),
                    "channel_title": live.get("channel_title"),
                    "program_key": live.get("program_key"),
                    "program_title": live.get("program_title"),
                    "error": None,
                }
        return {
            "ok": False,
            "via": "live_sports_section",
            "target": target,
            "steps": steps,
            "network": net,
            "error": "no_ga_al_live_sports_in_guide",
            "selected_title": None,
            "channel_title": None,
            "program_key": None,
        }

    from .heartbeat_fix import open_booth_local

    local = open_booth_local(
        instance_id,
        network=net,
        failover=failover,
        root=root,
    )
    steps.append(
        {
            "step": "open_hierarchy_local",
            "ok": bool(local.get("ok")),
            "network": net,
            "via": local.get("via"),
            "error": local.get("error"),
            "title": local.get("channel_title")
            or local.get("selected_title")
            or local.get("title"),
        }
    )
    return {
        "ok": bool(local.get("ok")),
        "via": "hierarchy_local",
        "target": target,
        "steps": steps,
        "network": net,
        "pick": local.get("pick"),
        "selected_title": local.get("selected_title") or local.get("channel_title"),
        "channel_title": local.get("channel_title") or local.get("selected_title"),
        "error": local.get("error"),
        "program_key": local.get("program_key"),
    }
