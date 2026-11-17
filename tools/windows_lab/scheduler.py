"""Schedule capture jobs and run due ones (source-aware)."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import MEDIA_MODES, SOURCE_KINDS, ensure_data_layout, schedule_path
from .locks import acquire, get_lock, reclaim_dead_locks, release
from .session_capture import start_session


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _python() -> Path:
    venv = _repo_root() / ".venv" / "Scripts" / "python.exe"
    return venv if venv.is_file() else Path(sys.executable)


def _parse_when(text: str) -> datetime:
    raw = text.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def load_jobs(root: Path | None = None) -> dict[str, Any]:
    ensure_data_layout(root)
    path = schedule_path(root)
    if not path.is_file():
        data = {"updated_utc": _now_iso(), "jobs": []}
        save_jobs(data, root)
        return data
    return json.loads(path.read_text(encoding="utf-8"))


def save_jobs(data: dict[str, Any], root: Path | None = None) -> Path:
    ensure_data_layout(root)
    path = schedule_path(root)
    data = dict(data)
    data["updated_utc"] = _now_iso()
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def add_job(
    *,
    source_kind: str,
    channel_id: str,
    start_at: str,
    minutes: float,
    media: str = "av",
    instance_id: str | None = None,
    tuner_id: str | None = None,
    rights_status: str = "authorized",
    label: str | None = None,
    apply_channel: bool = True,
    weekly: bool = False,
    detach: bool = True,
    guide: dict[str, Any] | None = None,
    shortcut_id: str | None = None,
    open_via: str | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    if source_kind not in SOURCE_KINDS:
        raise ValueError(f"source_kind must be one of {sorted(SOURCE_KINDS)}")
    if media not in MEDIA_MODES:
        raise ValueError(f"media must be one of {sorted(MEDIA_MODES)}")
    if source_kind == "streamers" and not instance_id:
        raise ValueError("instance_id required for streamers jobs")
    start_utc = _parse_when(start_at)
    # Guide-backed jobs default to search-open then no-channel-apply.
    if guide and open_via is None:
        open_via = "search"
    if guide and apply_channel is True and open_via == "search":
        apply_channel = False
    job = {
        "job_id": uuid.uuid4().hex[:12],
        "source_kind": source_kind,
        "channel_id": channel_id,
        "instance_id": instance_id,
        "tuner_id": tuner_id,
        "start_utc": start_utc.isoformat(),
        "minutes": float(minutes),
        "media": media,
        "rights_status": rights_status,
        "label": label or channel_id,
        "apply_channel": bool(apply_channel),
        "weekly": bool(weekly),
        "detach": bool(detach),
        "guide": guide,
        "shortcut_id": shortcut_id,
        "open_via": open_via,
        "status": "scheduled",
        "created_utc": _now_iso(),
        "last_error": None,
        "session_id": None,
    }
    data = load_jobs(root)
    jobs = list(data.get("jobs") or [])
    jobs.append(job)
    data["jobs"] = jobs
    save_jobs(data, root)
    return job


def _open_via_for_shortcut(shortcut_id: str, sc: dict[str, Any] | None = None) -> str:
    """Locals / section routes must not schedule as search (movie / random-affiliate trap)."""
    sc = sc or {}
    open_meta = sc.get("open") if isinstance(sc.get("open"), dict) else {}
    method = str(open_meta.get("method") or "")
    kind = str(sc.get("kind") or "")
    group = str(sc.get("group") or open_meta.get("section") or "")
    if method == "section_route" or open_meta.get("route_id"):
        return "nav"
    if method in ("us_section_grouper", "section_child") or kind == "local":
        return "section_child"
    if group in {
        "US FOX SECTION",
        "US CBS SECTION",
        "US NBC SECTION",
        "US ABC SECTION",
    }:
        return "section_child"
    try:
        from .us_locals import resolve_local_pick

        if resolve_local_pick(shortcut_id, row=sc):
            return "section_child"
    except Exception:
        pass
    try:
        from .streamers_open import LINEAR_NAV_BY_SHORTCUT, nav_route_for_shortcut

        if LINEAR_NAV_BY_SHORTCUT.get(str(shortcut_id).upper()) or nav_route_for_shortcut(
            str(shortcut_id), sc
        ):
            return "nav"
    except Exception:
        pass
    return "search"


def _is_movie_poison_title(title: str | None) -> bool:
    """Movies-tab hits that must never overwrite affiliate guide titles."""
    t = str(title or "").strip()
    if not t:
        return False
    low = t.lower()
    if re.search(r"\(\d{4}\)", t):
        return True
    if "after the fox" in low:
        return True
    if re.search(r"\b(movie|film|cinema)\b", low) and " | " not in t:
        return True
    # Affiliate shape: ST | CITY | NET - CALLS
    if re.search(r"\|\s*(ABC|CBS|NBC|FOX)\s*-\s*[A-Z0-9-]{3,8}\b", t, re.I):
        return False
    return False


def add_job_from_shortcut(
    *,
    shortcut_id: str,
    start_at: str,
    minutes: float,
    instance_id: str = "player 0",
    weekly: bool = False,
    label: str | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Schedule a capture that re-opens a saved shortcut at start time.

    Fails at schedule time if the shortcut is missing (not at kickoff).
    Locals use ``open_via=section_child`` — never network-name search.
    """
    from .streamers_open import get_shortcut

    # Fail here — not at 23:37 when the booth is live.
    try:
        sc = get_shortcut(shortcut_id, root)
    except KeyError:
        # Market tokens (FOX_NY) can be synthesized + seeded, then required.
        try:
            from .us_locals import ensure_market_local_shortcuts, resolve_local_pick

            ensure_market_local_shortcuts(root=root)
            if resolve_local_pick(shortcut_id, root=root):
                sc = get_shortcut(shortcut_id, root)
            else:
                raise
        except KeyError as exc:
            raise KeyError(
                f"shortcut not found at schedule time: {shortcut_id}. "
                "Create via `open local` / `olympics` seed before scheduling."
            ) from exc
    open_via = _open_via_for_shortcut(shortcut_id, sc)
    guide = {
        "search_query": sc.get("search_query"),
        "channel_title": sc.get("channel_title"),
        "channel_number": sc.get("channel_number"),
        "group": sc.get("group") or (sc.get("open") or {}).get("section"),
        "source": "shortcut",
        "shortcut_id": shortcut_id,
        "open_method": (sc.get("open") or {}).get("method"),
    }
    return add_job(
        source_kind="streamers",
        channel_id=str(sc.get("id") or shortcut_id),
        start_at=start_at,
        minutes=minutes,
        media="av",
        instance_id=instance_id,
        rights_status="authorized",
        label=label or f"{shortcut_id} {start_at[:10]}",
        apply_channel=False,
        weekly=weekly,
        detach=True,
        guide=guide,
        shortcut_id=shortcut_id,
        open_via=open_via,
        root=root,
    )


def add_job_from_guide_search(
    *,
    query: str,
    start_at: str,
    minutes: float,
    channel_id: str,
    title_contains: str | None = None,
    instance_id: str = "player 0",
    save_as: str | None = None,
    weekly: bool = False,
    label: str | None = None,
    open_now: bool = False,
    root: Path | None = None,
) -> dict[str, Any]:
    """Schedule from a guide search card; optionally open+save shortcut now."""
    guide = {
        "search_query": query,
        "channel_title": title_contains,
        "channel_number": None,
        "group": None,
        "source": "guide_search",
    }
    shortcut_id = save_as or channel_id
    if open_now:
        from .streamers_open import search_open

        opened = search_open(
            query=query,
            instance_id=instance_id,
            title_contains=title_contains,
            open_player=True,
            save_as=shortcut_id,
            kind="sports",
            root=root,
        )
        if not opened.get("ok"):
            raise RuntimeError(opened.get("error") or "guide search open failed")
        guide["channel_title"] = opened.get("selected_title")
        guide["channel_number"] = opened.get("channel_number")
        guide["group"] = opened.get("group")
        guide["opened_utc"] = _now_iso()
    else:
        from .streamers_open import save_shortcut

        save_shortcut(
            shortcut_id=shortcut_id,
            search_query=query,
            channel_title=title_contains or query,
            kind="sports",
            notes="scheduled from guide search (not opened yet)",
            root=root,
        )
    return add_job(
        source_kind="streamers",
        channel_id=channel_id,
        start_at=start_at,
        minutes=minutes,
        media="av",
        instance_id=instance_id,
        label=label or channel_id,
        apply_channel=False,
        weekly=weekly,
        detach=True,
        guide=guide,
        shortcut_id=shortcut_id,
        open_via="search",
        root=root,
    )


def _start_session_detached(job: dict[str, Any], root: Path | None = None) -> dict[str, Any]:
    """Launch session in a child process so run-due returns in seconds, not hours."""
    root = ensure_data_layout(root)
    env = os.environ.copy()
    env["OHUSH_DATA_ROOT"] = str(root)
    cmd = [
        str(_python()),
        "-m",
        "tools.windows_lab",
        "session",
        "start",
        "--source",
        str(job["source_kind"]),
        "--channel",
        str(job["channel_id"]),
        "--minutes",
        str(job["minutes"]),
        "--media",
        str(job.get("media") or "av"),
        "--still-interval",
        "1",
        "--rights-status",
        str(job.get("rights_status") or "authorized"),
    ]
    if job.get("instance_id"):
        cmd.extend(["--instance", str(job["instance_id"])])
    if job.get("tuner_id"):
        cmd.extend(["--tuner", str(job["tuner_id"])])
    if not job.get("apply_channel", True):
        cmd.append("--no-channel-apply")
    if job.get("job_id"):
        cmd.extend(["--job-id", str(job["job_id"])])
    log_dir = root / "work" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"schedule_{job['job_id']}.log"
    with log_path.open("a", encoding="utf-8") as log:
        log.write(f"\n--- {_now_iso()} detach {job['channel_id']} {job['minutes']}m ---\n")
        log.flush()
        proc = subprocess.Popen(
            cmd,
            cwd=str(_repo_root()),
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
    # Wait for the detached session to upgrade starting_* → real session_id.
    # Do not accept starting_* itself (that is the pre-guide hold from this tick).
    session_id = None
    kind, resource_id = _resource_for(job)
    job_id = str(job.get("job_id") or "")
    for _ in range(80):  # ~20s — PID resolve + lock upgrade can be slow under load
        time.sleep(0.25)
        lock = get_lock(kind, resource_id, root=root)
        if lock:
            sid = str(lock.get("session_id") or "")
            lock_job = str(lock.get("job_id") or "")
            holder = int(lock.get("holder_pid") or 0)
            if sid and not sid.startswith("starting_"):
                # Accept our job even when session start re-parents to a worker PID.
                if lock_job == job_id or holder in (0, int(proc.pid)):
                    session_id = sid
                    break
        if proc.poll() is not None and not session_id:
            # Process exited — one last lock read (child may have claimed then parent died).
            lock = get_lock(kind, resource_id, root=root)
            if lock and str(lock.get("job_id") or "") == job_id:
                sid = str(lock.get("session_id") or "")
                if sid and not sid.startswith("starting_"):
                    session_id = sid
            break
    if not session_id:
        return {
            "ok": False,
            "detached": True,
            "error": "detached session did not claim lock (still starting_ or exited)",
            "pid": proc.pid,
            "session_id": None,
            "log": str(log_path),
            "cmd": cmd,
        }
    return {
        "ok": True,
        "detached": True,
        "pid": proc.pid,
        "session_id": session_id,
        "log": str(log_path),
        "cmd": cmd,
    }


def _nav_route_for_job(job: dict[str, Any]) -> str | None:
    """Linear ESPN* jobs open parent→child; never search (ESPNU poisons scoring)."""
    if job.get("nav_route"):
        return str(job["nav_route"])
    from .streamers_open import LINEAR_NAV_BY_SHORTCUT, nav_route_for_shortcut

    sid = str(job.get("shortcut_id") or job.get("channel_id") or "")
    mapped = LINEAR_NAV_BY_SHORTCUT.get(sid.upper())
    if mapped:
        return mapped
    if job.get("open_via") == "nav" and sid:
        try:
            from .streamers_open import get_shortcut

            return nav_route_for_shortcut(sid, get_shortcut(sid))
        except Exception:  # noqa: BLE001
            return nav_route_for_shortcut(sid, None)
    return None


def _job_fail_extra(
    job: dict[str, Any],
    *,
    err: str | None = None,
    guide_open: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Fields every job_failed / schedule fail log should carry."""
    guide = job.get("guide") or {}
    go = guide_open if guide_open is not None else (job.get("guide_open") or {})
    extra: dict[str, Any] = {
        "label": job.get("label"),
        "channel_id": job.get("channel_id"),
        "shortcut_id": job.get("shortcut_id"),
        "open_via": job.get("open_via") or go.get("open_via"),
        "nav_route": job.get("nav_route") or go.get("nav_route"),
        "instance_id": job.get("instance_id"),
        "search_query": guide.get("search_query") or go.get("query"),
        "guide_title": guide.get("channel_title"),
        "guide_source": guide.get("source"),
        "selected_title": go.get("selected_title"),
        "place": go.get("place"),
        "guide_error": go.get("error"),
        "longpress_error": (go.get("longpress") or {}).get("error")
        if isinstance(go.get("longpress"), dict)
        else None,
        "ui_texts": (go.get("texts") or [])[:12] if isinstance(go.get("texts"), list) else None,
        "error": err or job.get("last_error") or go.get("error"),
    }
    return {k: v for k, v in extra.items() if v is not None}


def _append_schedule_log(job: dict[str, Any], payload: dict[str, Any]) -> None:
    """Write structured fail/start context into schedule_<job_id>.log."""
    log_path = job.get("log")
    if not log_path:
        root = ensure_data_layout()
        log_path = str(root / "work" / "logs" / f"schedule_{job.get('job_id')}.log")
        job["log"] = log_path
    try:
        path = Path(str(log_path))
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(f"\n--- {_now_iso()} {payload.get('event') or 'note'} ---\n")
            fh.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
    except Exception:  # noqa: BLE001
        pass


def _open_guide_before_record(job: dict[str, Any], root: Path | None = None) -> dict[str, Any]:
    """Open the live card before session start (nav parent→child or search)."""
    open_via = str(job.get("open_via") or "")
    shortcut_id = job.get("shortcut_id")
    guide = job.get("guide") or {}
    nav_route = _nav_route_for_job(job)
    # Linear ESPN shortcuts always use nav even if an old job still says search.
    if nav_route:
        open_via = "nav"
    if open_via not in ("search", "nav"):
        return {"ok": True, "skipped": True}
    try:
        if open_via == "nav" and nav_route:
            from .streamers_nav import run_route

            out = run_route(
                nav_route,
                instance_id=str(job.get("instance_id") or "player 0"),
                root=root,
                open_player=True,
                save_as=str(shortcut_id or job.get("channel_id") or nav_route),
            )
            chosen = None
            for step in reversed(out.get("atoms") or []):
                if (step.get("result") or {}).get("chosen") or step.get("chosen"):
                    chosen = (step.get("result") or {}).get("chosen") or step.get("chosen")
                    break
            out["selected_title"] = chosen or out.get("selected_title")
            out["open_via"] = "nav"
            out["nav_route"] = nav_route
            return out
        # Parent→child locals (FOX_NY / CBS_LOCAL / US FOX SECTION) before search.
        sid = str(shortcut_id or job.get("channel_id") or "")
        if sid:
            from .us_locals import open_local_for_shortcut, resolve_local_pick
            from .streamers_open import get_shortcut

            row = None
            try:
                if shortcut_id:
                    row = get_shortcut(str(shortcut_id), root)
            except Exception:
                row = None
            if resolve_local_pick(sid, row=row, channel_id=str(job.get("channel_id") or ""), root=root):
                out = open_local_for_shortcut(
                    sid,
                    row=row,
                    instance_id=str(job.get("instance_id") or "player 0"),
                    root=root,
                )
                if out is not None:
                    out.setdefault("open_via", "section_child")
                    out.setdefault("shortcut_id", sid)
                    return out
        if shortcut_id:
            from .streamers_open import open_shortcut

            out = open_shortcut(
                str(shortcut_id),
                instance_id=str(job.get("instance_id") or "player 0"),
                root=root,
            )
            out.setdefault("open_via", out.get("open_via") or "search")
            out.setdefault("shortcut_id", str(shortcut_id))
            return out
        query = guide.get("search_query")
        if not query:
            return {"ok": False, "error": "guide.search_query missing", "open_via": open_via}
        from .streamers_open import search_open

        # search_open itself redirects bare FOX/ABC/… to section_child.
        out = search_open(
            query=str(query),
            instance_id=str(job.get("instance_id") or "player 0"),
            title_contains=guide.get("channel_title"),
            open_player=True,
            save_as=str(job.get("channel_id")),
            root=root,
        )
        out.setdefault("open_via", out.get("open_via") or "search")
        out.setdefault("query", str(query))
        return out
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "error": str(exc).strip("'"),
            "open_via": open_via or None,
            "nav_route": nav_route,
            "shortcut_id": shortcut_id,
            "exc_type": type(exc).__name__,
        }


def list_jobs(root: Path | None = None, *, status: str | None = None) -> list[dict[str, Any]]:
    data = load_jobs(root)
    jobs = list(data.get("jobs") or [])
    if status:
        jobs = [j for j in jobs if j.get("status") == status]
    return jobs


def cancel_job(job_id: str, root: Path | None = None) -> dict[str, Any]:
    data = load_jobs(root)
    found = None
    for job in data.get("jobs") or []:
        if job.get("job_id") == job_id:
            if job.get("status") in ("scheduled", "due"):
                job["status"] = "cancelled"
                job["cancelled_utc"] = _now_iso()
            found = job
            break
    if not found:
        raise KeyError(f"job not found: {job_id}")
    save_jobs(data, root)
    return found


def refresh_guide_for_upcoming(
    root: Path | None = None,
    *,
    horizon_hours: float = 72.0,
    instance_id: str = "player 0",
    execute_search: bool = True,
) -> dict[str, Any]:
    """Re-check Streamers guide cards for upcoming scheduled jobs.

    For each unique search_query on jobs starting within ``horizon_hours``, run a
    no-open guide search and stamp the best Channels title back onto those jobs.
    Write ``indexes/GUIDE_REFRESH.md`` so the desk can see what changed.
    """
    from .config import ensure_data_layout
    from .streamers_open import _pick_channel_title, _score_channel_title, search_open

    root = ensure_data_layout(root)
    now = _now()
    horizon = now.timestamp() + float(horizon_hours) * 3600.0
    data = load_jobs(root)
    jobs = [j for j in (data.get("jobs") or []) if j.get("status") == "scheduled"]
    upcoming: list[dict[str, Any]] = []
    for job in jobs:
        try:
            start = datetime.fromisoformat(str(job.get("start_utc")).replace("Z", "+00:00"))
        except Exception:  # noqa: BLE001
            continue
        if now.timestamp() <= start.timestamp() <= horizon:
            upcoming.append(job)

    # Dedupe by search query (and optional title hint). Skip section/nav locals —
    # refreshing those via search_open("FOX") is how "After the Fox" poisons titles.
    queries: dict[str, dict[str, Any]] = {}
    skipped_local: list[dict[str, Any]] = []
    for job in upcoming:
        guide = job.get("guide") or {}
        sid = str(job.get("shortcut_id") or job.get("channel_id") or "")
        open_via = str(job.get("open_via") or "")
        is_section = open_via in ("section_child", "local", "nav")
        try:
            from .us_locals import resolve_local_pick

            is_section = is_section or bool(resolve_local_pick(sid, root=root))
        except Exception:
            pass
        q = str(guide.get("search_query") or "").strip()
        # Network-only queries always skip refresh (movie / random DMA trap).
        if re.fullmatch(r"(?i)(abc|cbs|nbc|fox)", q or ""):
            skipped_local.append(
                {
                    "job_id": job.get("job_id"),
                    "reason": "network_name_query_no_refresh",
                    "search_query": q,
                    "shortcut_id": sid,
                }
            )
            continue
        if is_section:
            # Restamp title from shortcut row if current guide looks movie-poisoned.
            try:
                from .streamers_open import get_shortcut

                sc = get_shortcut(sid, root) if sid else None
            except Exception:
                sc = None
            if sc and _is_movie_poison_title(guide.get("channel_title")):
                prev = guide.get("channel_title")
                guide = dict(guide)
                guide["channel_title"] = sc.get("channel_title") or guide.get("channel_title")
                guide["channel_title_match"] = guide["channel_title"]
                guide["group"] = sc.get("group") or guide.get("group")
                guide["guide_checked_utc"] = _now_iso()
                guide["previous_channel_title"] = prev
                guide["repaired"] = "section_shortcut_title"
                job["guide"] = guide
                if job.get("open_via") == "search":
                    job["open_via"] = _open_via_for_shortcut(sid, sc)
                skipped_local.append(
                    {
                        "job_id": job.get("job_id"),
                        "reason": "repaired_poisoned_local_title",
                        "previous": prev,
                        "selected_title": guide.get("channel_title"),
                    }
                )
            else:
                skipped_local.append(
                    {
                        "job_id": job.get("job_id"),
                        "reason": "section_child_no_search_refresh",
                        "shortcut_id": sid,
                        "open_via": open_via or "section_child",
                    }
                )
            continue
        if not q:
            continue
        key = q.lower()
        queries.setdefault(
            key,
            {
                "search_query": q,
                "title_contains": guide.get("channel_title"),
                "job_ids": [],
                "labels": [],
            },
        )
        queries[key]["job_ids"].append(job.get("job_id"))
        queries[key]["labels"].append(job.get("label") or job.get("channel_id"))

    results: list[dict[str, Any]] = list(skipped_local)
    for row in queries.values():
        entry: dict[str, Any] = {
            "search_query": row["search_query"],
            "job_ids": row["job_ids"],
            "labels": row["labels"],
            "ok": False,
        }
        if not execute_search:
            entry["skipped"] = True
            entry["reason"] = "dry_run"
            results.append(entry)
            continue
        try:
            opened = search_open(
                query=row["search_query"],
                instance_id=instance_id,
                title_contains=str(row.get("title_contains") or "") or None,
                open_player=False,
                save_as=None,
                kind="sports",
                root=root,
            )
        except Exception as e:  # noqa: BLE001
            entry["error"] = str(e)
            results.append(entry)
            continue
        entry["ok"] = bool(opened.get("ok"))
        entry["selected_title"] = opened.get("selected_title")
        entry["channel_number"] = opened.get("channel_number")
        entry["group"] = opened.get("group")
        entry["error"] = opened.get("error")
        # If search returned a bag of titles in error payload, still try to pick.
        titles = opened.get("titles") or []
        if not entry["selected_title"] and titles:
            entry["selected_title"] = _pick_channel_title(titles, query=row["search_query"])
            if entry["selected_title"]:
                entry["ok"] = True
                entry["score"] = _score_channel_title(entry["selected_title"], query=row["search_query"])
        # Never stamp Movies-tab poison over an affiliate-shaped previous title.
        if entry.get("selected_title") and _is_movie_poison_title(entry["selected_title"]):
            entry["ok"] = False
            entry["error"] = f"rejected_movie_poison:{entry['selected_title']}"
            entry["selected_title"] = None
            results.append(entry)
            continue
        if entry["ok"] and entry.get("selected_title"):
            for job in data.get("jobs") or []:
                if job.get("job_id") not in row["job_ids"]:
                    continue
                guide = dict(job.get("guide") or {})
                prev = guide.get("channel_title")
                # Keep a good affiliate title if the new pick is worse/poison.
                if _is_movie_poison_title(entry["selected_title"]) and not _is_movie_poison_title(prev):
                    continue
                guide["channel_title"] = entry["selected_title"]
                guide["channel_title_match"] = entry["selected_title"]
                if entry.get("channel_number"):
                    guide["channel_number"] = entry["channel_number"]
                if entry.get("group"):
                    guide["group"] = entry["group"]
                guide["guide_checked_utc"] = _now_iso()
                guide["previous_channel_title"] = prev
                job["guide"] = guide
                entry["updated"] = True
                entry["previous_channel_title"] = prev
                entry["changed"] = prev != entry["selected_title"]
        results.append(entry)

    save_jobs(data, root)
    board_path = root / "indexes" / "GUIDE_REFRESH.md"
    lines = [
        "# Guide refresh",
        "",
        f"Checked `{_now_iso()}` · horizon **{horizon_hours:g}h** · instance `{instance_id}`",
        "",
        f"Upcoming jobs scanned: **{len(upcoming)}** · unique queries: **{len(queries)}**",
        "",
        "| Query | Selected card | Changed | Jobs |",
        "|---|---|---|---|",
    ]
    for r in results:
        chg = "yes" if r.get("changed") else ("—" if not r.get("ok") else "no")
        sel = r.get("selected_title") or r.get("error") or r.get("reason") or "—"
        q = r.get("search_query") or r.get("shortcut_id") or r.get("job_id") or "—"
        job_bits = r.get("labels") or ([r.get("job_id")] if r.get("job_id") else [])
        lines.append(
            f"| {q} | {sel} | {chg} | {', '.join(str(x) for x in (job_bits or [])[:3])} |"
        )
    lines.append("")
    lines.append("Re-run: `python -m tools.windows_lab schedule guide-refresh`")
    lines.append("")
    board_path.write_text("\n".join(lines), encoding="utf-8")
    return {
        "ok": all(r.get("ok") or r.get("skipped") for r in results) if results else True,
        "checked_utc": _now_iso(),
        "horizon_hours": horizon_hours,
        "upcoming_jobs": len(upcoming),
        "queries": len(queries),
        "results": results,
        "board": str(board_path),
    }


def _resource_for(job: dict[str, Any]) -> tuple[str, str]:
    kind = str(job["source_kind"])
    if kind == "streamers":
        return kind, str(job["instance_id"])
    return kind, str(job.get("tuner_id") or "default")


def _free_streamers_instance(
    preferred: str,
    root: Path | None = None,
    *,
    exclude: set[str] | None = None,
) -> str | None:
    """Pick a free player (Nougat fleet). Prefer free clones when preferred is busy."""
    from .instances import list_instances, normalize_instance_id, player_index

    blocked = set(exclude or ())
    preferred = normalize_instance_id(str(preferred or "player 0"), root)
    if preferred not in blocked and not get_lock("streamers", preferred, root=root):
        return preferred

    candidates: list[str] = []
    for row in list_instances(root):
        if not row.get("enabled", True):
            continue
        if str(row.get("source_kind") or "streamers") not in ("streamers", ""):
            continue
        iid = str(row.get("id") or "")
        if row.get("player") is None and not str(iid).startswith("Nougat32"):
            continue
        if iid in blocked or iid == preferred:
            continue
        if get_lock("streamers", iid, root=root):
            continue
        candidates.append(iid)

    def _sort_key(iid: str) -> tuple[int, str]:
        idx = player_index(iid, root)
        return (idx if idx is not None else 999, iid)

    candidates.sort(key=_sort_key)
    return candidates[0] if candidates else None


def _lock_is_preemptible_filler(lock: dict[str, Any] | None, job: dict[str, Any]) -> bool:
    """Due sports may take a box from continue/pre/filler — not from the same job."""
    if not lock:
        return False
    lock_job = str(lock.get("job_id") or "")
    if lock_job and lock_job == str(job.get("job_id") or ""):
        return False
    sid = str(lock.get("session_id") or "").upper()
    markers = (
        "ON_AIR_CONTINUE",
        "ON_AIR",
        "PRE_MNF",
        "PRE-MNF",
        "FOX_PRE",
        "FILL",
        "CONTINUE",
        "STARTING_",
    )
    return any(m in sid for m in markers)


def run_due(
    root: Path | None = None,
    *,
    now: datetime | None = None,
    execute: bool = True,
) -> dict[str, Any]:
    """Start any scheduled job whose start time has passed and whose resource is free."""
    now = now or _now()
    data = load_jobs(root)
    started: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    retargeted: list[dict[str, Any]] = []
    claimed_this_tick: set[str] = set()
    # Forever: dead holders must not block before the busy check (was after → stuck forever).
    reclaimed_dead = reclaim_dead_locks(root=root)

    # Overnight verdict window + owner pause: do not start new TV captures.
    # Farm loop owns 02:00–06:00 ET for multichannel; run-due starting takes
    # recreates Bug 6 (lock held → label starved).
    hold_new_captures: dict[str, Any] | None = None
    try:
        from .capture_pause import is_paused
        from .farm_loop import schedule_window

        sched = schedule_window(now)
        pause = is_paused(root)
        if pause.get("active"):
            hold_new_captures = {"why": "capture_pause", "pause": pause}
        elif str(sched.get("mode") or "").startswith("overnight"):
            hold_new_captures = {"why": "overnight_verdict_window", "schedule": sched}
    except Exception as exc:  # noqa: BLE001
        hold_new_captures = None
        skipped.append({"job_id": None, "reason": f"overnight_gate_error:{exc}"})

    if hold_new_captures and execute:
        return {
            "ok": True,
            "now": now.isoformat(),
            "started": [],
            "skipped": [
                {
                    "reason": "hold_new_captures",
                    **hold_new_captures,
                }
            ],
            "failed": [],
            "retargeted": [],
            "reclaimed_dead": reclaimed_dead,
            "hold_new_captures": hold_new_captures,
        }

    for job in data.get("jobs") or []:
        if job.get("status") != "scheduled":
            continue
        start = _parse_when(str(job["start_utc"]))
        if start > now:
            continue
        kind, resource_id = _resource_for(job)
        lock = get_lock(kind, resource_id, root=root)
        preempted = None
        # Live execute: reclaim already dropped dead PIDs; also preempt continue/pre/filler
        # so overdue MNF is not stuck behind a ghost or ads-fill session.
        if (
            execute
            and kind == "streamers"
            and lock
            and resource_id not in claimed_this_tick
            and (
                "ON_AIR_CONTINUE" in str((lock or {}).get("session_id") or "")
                or _lock_is_preemptible_filler(lock, job)
            )
        ):
            try:
                from .farm_ops import emit, preempt_on_air

                busy_sid = str((lock or {}).get("session_id") or "")
                force = "ON_AIR_CONTINUE" not in busy_sid
                preempted = preempt_on_air(
                    resource_id,
                    root=root,
                    reason=f"scheduled_job:{job.get('job_id')}",
                    force=force,
                )
                emit(
                    "resource_decision",
                    detail="preempt_on_air" if not force else "preempt_filler",
                    job_id=str(job.get("job_id")),
                    instance_id=resource_id,
                    session_id=busy_sid,
                    ok=bool(preempted.get("ok")),
                    extra={"label": job.get("label"), "reclaimed_dead": len(reclaimed_dead)},
                    root=root,
                )
                if preempted.get("ok"):
                    lock = get_lock(kind, resource_id, root=root)
            except Exception as exc:  # noqa: BLE001
                preempted = {"ok": False, "error": str(exc)}

        if lock or resource_id in claimed_this_tick:
            alt = None
            if kind == "streamers":
                alt = _free_streamers_instance(
                    resource_id,
                    root=root,
                    exclude=claimed_this_tick,
                )
            if alt and alt != resource_id:
                retargeted.append(
                    {
                        "job_id": job["job_id"],
                        "from": resource_id,
                        "to": alt,
                        "busy_lock": (lock or {}).get("session_id") if lock else None,
                        "preempted": preempted,
                    }
                )
                job["retargeted_from"] = resource_id
                job["retargeted_utc"] = _now_iso()
                job["instance_id"] = alt
                resource_id = alt
                save_jobs(data, root)
                try:
                    from .farm_ops import emit

                    emit(
                        "resource_decision",
                        detail="retarget_clone",
                        job_id=str(job.get("job_id")),
                        instance_id=alt,
                        ok=True,
                        extra={"from": job.get("retargeted_from"), "label": job.get("label")},
                        root=root,
                    )
                except Exception:  # noqa: BLE001
                    pass
            else:
                skipped.append(
                    {
                        "job_id": job["job_id"],
                        "reason": "resource_busy",
                        "lock": lock,
                        "preempted": preempted,
                    }
                )
                try:
                    from .farm_ops import emit

                    emit(
                        "resource_decision",
                        detail="busy_no_clone",
                        job_id=str(job.get("job_id")),
                        instance_id=resource_id,
                        ok=False,
                        extra={"lock": lock},
                        root=root,
                    )
                except Exception:  # noqa: BLE001
                    pass
                continue
        if not execute:
            skipped.append({"job_id": job["job_id"], "reason": "dry_preview"})
            continue

        # Refuse two live captures of the same channel / affiliate / program at once.
        cid = str(job.get("channel_id") or job.get("shortcut_id") or "").upper()
        job_prog = str(job.get("program_key") or job.get("title") or "").strip().lower()
        live_same = []
        if cid and cid not in {"ON_AIR_CONTINUE", ""}:
            for other in data.get("jobs") or []:
                if other.get("job_id") == job.get("job_id"):
                    continue
                ost = str(other.get("status") or "")
                ocid = str(other.get("channel_id") or other.get("shortcut_id") or "").upper()
                if ost in {"running", "started", "recording"} and ocid == cid:
                    live_same.append(other.get("job_id"))
            try:
                from .stream_status import fleet_rows, normalize_program_key

                want_pk = normalize_program_key(job_prog) if job_prog else None
                for row in fleet_rows(root):
                    if row.get("instance_id") == resource_id:
                        continue
                    if not (row.get("up") or row.get("locked") or row.get("selected_title")):
                        continue
                    row_cid = str(
                        (row.get("intended") or {}).get("shortcut_id")
                        or row.get("calls")
                        or ""
                    ).upper()
                    if cid in {row_cid, f"{row.get('network')}_LOCAL".upper()} and row.get("calls"):
                        # Same affiliate calls already on another player.
                        if any(
                            x in cid
                            for x in (
                                str(row.get("calls") or "").upper(),
                                str(row.get("network") or "").upper(),
                            )
                        ):
                            live_same.append(f"fleet:{row.get('instance_id')}:{row.get('calls')}")
                    # Same national game on any affiliate is still a waste.
                    row_pk = row.get("program_key") or normalize_program_key(
                        str(row.get("program_title") or row.get("selected_title") or "")
                    )
                    if want_pk and row_pk and want_pk == row_pk:
                        live_same.append(
                            f"fleet_program:{row.get('instance_id')}:{row_pk}"
                        )
            except Exception:
                pass
        if live_same:
            skipped.append(
                {
                    "job_id": job["job_id"],
                    "reason": "duplicate_channel_live",
                    "channel_id": cid,
                    "conflicts": live_same[:8],
                }
            )
            try:
                from .farm_ops import emit

                emit(
                    "resource_decision",
                    detail="duplicate_channel_live",
                    job_id=str(job.get("job_id")),
                    instance_id=resource_id,
                    ok=False,
                    extra={"channel_id": cid, "conflicts": live_same[:8]},
                    root=root,
                )
            except Exception:
                pass
            continue

        claimed_this_tick.add(resource_id)
        job["status"] = "running"
        job["started_utc"] = _now_iso()
        save_jobs(data, root)
        # Hold the instance through guide-open so desk cannot steal mid-search.
        starting_sid = f"starting_{job['job_id']}"
        held_starting = False
        reclaim_dead_locks(root=root)
        got_start, start_lock = acquire(
            kind,
            resource_id,
            session_id=starting_sid,
            job_id=str(job["job_id"]),
            holder_pid=os.getpid(),
            root=root,
        )
        if not got_start:
            job["status"] = "scheduled"
            job["started_utc"] = None
            skipped.append(
                {
                    "job_id": job["job_id"],
                    "reason": "resource_busy_before_guide",
                    "lock": start_lock,
                }
            )
            claimed_this_tick.discard(resource_id)
            save_jobs(data, root)
            continue
        held_starting = True
        try:
            detach = bool(job.get("detach", True))
            apply_channel = bool(job.get("apply_channel", True))
            guide_open = _open_guide_before_record(job, root=root)
            # Keep diagnostic fields (texts/place/longpress) — not just ok/error.
            job["guide_open"] = {
                k: guide_open.get(k)
                for k in (
                    "ok",
                    "selected_title",
                    "error",
                    "skipped",
                    "open_via",
                    "nav_route",
                    "shortcut_id",
                    "query",
                    "place",
                    "texts",
                    "longpress",
                    "exc_type",
                )
                if guide_open.get(k) is not None
            }
            if guide_open.get("ok") is False and not guide_open.get("skipped"):
                raise RuntimeError(guide_open.get("error") or "guide open failed")
            if detach:
                result = _start_session_detached(job, root=root)
            else:
                result = start_session(
                    source_kind=kind,
                    channel_id=str(job["channel_id"]),
                    minutes=float(job["minutes"]),
                    media=str(job.get("media") or "av"),
                    instance_id=job.get("instance_id"),
                    tuner_id=job.get("tuner_id"),
                    rights_status=str(job.get("rights_status") or "authorized"),
                    apply_channel=apply_channel,
                    root=root,
                    job_id=str(job["job_id"]),
                )
            if result.get("ok"):
                # Detached takes keep status "started" — session owns the lock.
                job["status"] = "started" if detach else "completed"
                job["session_id"] = result.get("session_id")
                job["pid"] = result.get("pid")
                job["log"] = result.get("log")
                job["completed_utc"] = None if detach else _now_iso()
                job["last_error"] = None
                started.append(
                    {
                        "job_id": job["job_id"],
                        "session_id": job["session_id"],
                        "pid": job.get("pid"),
                        "detached": detach,
                        "guide_open": job.get("guide_open"),
                    }
                )
                _append_schedule_log(
                    job,
                    {
                        "event": "job_started",
                        **_job_fail_extra(job, guide_open=guide_open),
                        "session_id": job.get("session_id"),
                        "pid": job.get("pid"),
                    },
                )
                try:
                    from .farm_ops import emit

                    emit(
                        "job_started",
                        detail=str(job.get("label") or job.get("channel_id") or ""),
                        job_id=str(job["job_id"]),
                        session_id=str(job.get("session_id") or "") or None,
                        instance_id=str(resource_id),
                        pid=job.get("pid"),
                        ok=True,
                        extra={
                            "preempted": preempted,
                            "retargeted_from": job.get("retargeted_from"),
                            **_job_fail_extra(job, guide_open=guide_open),
                        },
                        root=root,
                    )
                except Exception:  # noqa: BLE001
                    pass
                if job.get("weekly"):
                    try:
                        from .tnf_thursday import roll_weekly_job

                        rolled = roll_weekly_job(job, root=root)
                        if rolled:
                            started.append({"rolled_weekly": rolled.get("job_id"), "start_utc": rolled.get("start_utc")})
                    except Exception as roll_exc:  # noqa: BLE001
                        job["roll_error"] = str(roll_exc)
            else:
                job["status"] = "failed"
                job["last_error"] = result.get("error") or "session failed"
                job["failed_utc"] = _now_iso()
                fail_extra = _job_fail_extra(job, err=str(job["last_error"]), guide_open=guide_open)
                failed.append({"job_id": job["job_id"], "error": job["last_error"], **fail_extra})
                _append_schedule_log(job, {"event": "job_failed", **fail_extra})
                try:
                    from .farm_ops import emit

                    emit(
                        "job_failed",
                        detail=str(job["last_error"]),
                        job_id=str(job["job_id"]),
                        instance_id=str(resource_id),
                        ok=False,
                        extra=fail_extra,
                        root=root,
                    )
                except Exception:  # noqa: BLE001
                    pass
        except Exception as e:  # noqa: BLE001
            job["status"] = "failed"
            job["last_error"] = str(e).strip("'")
            job["failed_utc"] = _now_iso()
            fail_extra = _job_fail_extra(
                job,
                err=str(job["last_error"]),
                guide_open=job.get("guide_open") if isinstance(job.get("guide_open"), dict) else None,
            )
            failed.append({"job_id": job["job_id"], "error": job["last_error"], **fail_extra})
            _append_schedule_log(job, {"event": "job_failed", **fail_extra})
            try:
                from .farm_ops import emit

                emit(
                    "job_failed",
                    detail=str(job["last_error"]),
                    job_id=str(job["job_id"]),
                    instance_id=str(resource_id),
                    ok=False,
                    extra=fail_extra,
                    root=root,
                )
            except Exception:  # noqa: BLE001
                pass
            if held_starting:
                try:
                    release(kind, resource_id, root=root)
                except Exception:  # noqa: BLE001
                    pass
                held_starting = False
        # If session start failed without exception path, drop starting lock.
        if held_starting and job.get("status") == "failed":
            try:
                release(kind, resource_id, root=root)
            except Exception:  # noqa: BLE001
                pass
        save_jobs(data, root)

    return {
        "checked_utc": _now_iso(),
        "started": started,
        "skipped": skipped,
        "failed": failed,
        "retargeted": retargeted,
    }


def install_task_scheduler_script(repo: Path, root: Path | None = None) -> Path:
    """Write a PowerShell helper that registers a 1-minute Task Scheduler job."""
    ensure_data_layout(root)
    out = ensure_data_layout(root) / "farm" / "register_capture_scheduler.ps1"
    py = repo / ".venv" / "Scripts" / "python.exe"
    if not py.is_file():
        py = Path("python")
    data_root = ensure_data_layout(root)
    # Double braces for PowerShell; only {repo}/{python}/{data_root} are Python inserts.
    script = f"""# Register OHush capture farm run-due (every 1 minute)
$ErrorActionPreference = "Stop"
$taskName = "OHushCaptureFarmRunDue"
$repo = {json.dumps(str(repo))}
$python = {json.dumps(str(py))}
$dataRoot = {json.dumps(str(data_root))}
$wrapper = Join-Path $dataRoot "farm\\run_due_wrapper.cmd"
$hidden = Join-Path $dataRoot "farm\\run_due_hidden.vbs"
@"
@echo off
set OHUSH_DATA_ROOT=$dataRoot
cd /d $repo
$python -m tools.windows_lab schedule run-due >> "$dataRoot\\work\\logs\\schedule_run_due.log" 2>&1
$python -m tools.windows_lab schedule audit --active-only >> "$dataRoot\\work\\logs\\schedule_audit.log" 2>&1
rem Guide refresh twice an hour (min 00 / 30) so upcoming cards stay current.
set M=%TIME:~3,2%
if "%M%"=="00" $python -m tools.windows_lab schedule guide-refresh --horizon-hours 96 >> "$dataRoot\\work\\logs\\schedule_guide_refresh.log" 2>&1
if "%M%"=="30" $python -m tools.windows_lab schedule guide-refresh --horizon-hours 96 >> "$dataRoot\\work\\logs\\schedule_guide_refresh.log" 2>&1
"@ | Set-Content -Path $wrapper -Encoding ASCII
$q = [char]34
$vbs = @(
  "' Hidden launcher - window style 0 (no console flash every minute)"
  ("Set sh = CreateObject(" + $q + "WScript.Shell" + $q + ")")
  ("sh.Run " + $q + "cmd /c " + $q + $q + $wrapper + $q + $q + $q + ", 0, True")
) -join "`r`n"
Set-Content -Path $hidden -Value $vbs -Encoding ASCII
# wscript+VBS so Interactive logon does not pop a terminal every minute.
$action = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "//B //Nologo `"$hidden`""
# Indefinite MaxValue is rejected by Task Scheduler; 10 years is enough.
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 1) -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew -Hidden
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
Write-Output "Registered $taskName (hidden via $hidden)"
"""
    out.write_text(script, encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="Capture schedule")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add")
    a.add_argument(
        "--source",
        required=True,
        choices=sorted(SOURCE_KINDS | {"ota", "antenna"}),
        help="streamers | ota_antenna (aliases: ota, antenna)",
    )
    a.add_argument("--channel", required=True)
    a.add_argument("--at", required=True, help="ISO8601 start time")
    a.add_argument("--minutes", type=float, required=True)
    a.add_argument("--media", default="av", choices=sorted(MEDIA_MODES))
    a.add_argument("--instance")
    a.add_argument("--tuner")
    a.add_argument("--rights-status", default="authorized")
    a.add_argument("--label")
    a.add_argument("--no-channel-apply", action="store_true")
    a.add_argument("--weekly", action="store_true", help="Re-enqueue +7 days after start")
    a.add_argument("--foreground", action="store_true", help="Block until session ends")
    a.add_argument("--shortcut-id", help="Link a streamers_open shortcut id")
    a.add_argument("--search", help="Guide search query stamped on the job")
    a.add_argument("--guide-title", help="Expected Channels card title")

    fs = sub.add_parser("from-shortcut", help="Schedule from a saved guide search shortcut")
    fs.add_argument("--id", required=True, help="Shortcut id (e.g. TNF_PRIME)")
    fs.add_argument("--at", required=True)
    fs.add_argument("--minutes", type=float, required=True)
    fs.add_argument("--instance", default="player 0")
    fs.add_argument("--weekly", action="store_true")
    fs.add_argument("--label")

    fg = sub.add_parser("from-guide", help="Schedule from a guide search (sports: team/show name)")
    fg.add_argument("--query", required=True)
    fg.add_argument("--channel", required=True, help="channel_id / shortcut id to stamp")
    fg.add_argument("--at", required=True)
    fg.add_argument("--minutes", type=float, required=True)
    fg.add_argument("--title-contains")
    fg.add_argument("--instance", default="player 0")
    fg.add_argument("--save-as")
    fg.add_argument("--weekly", action="store_true")
    fg.add_argument("--label")
    fg.add_argument("--open-now", action="store_true", help="Open+confirm the card before enqueue")

    l = sub.add_parser("list")
    l.add_argument("--status")

    c = sub.add_parser("cancel")
    c.add_argument("--job-id", required=True)

    r = sub.add_parser("run-due")
    r.add_argument("--dry-run", action="store_true")

    au = sub.add_parser("audit", help="Audit scheduled jobs: started? tape healthy?")
    au.add_argument("--active-only", action="store_true")

    gr = sub.add_parser(
        "guide-refresh",
        help="Re-check Streamers guide cards for upcoming jobs (periodic)",
    )
    gr.add_argument("--horizon-hours", type=float, default=72.0)
    gr.add_argument("--instance", default="player 0")
    gr.add_argument("--dry-run", action="store_true")

    i = sub.add_parser("install-task")
    i.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])

    tnf = sub.add_parser("tnf-enqueue", help="Ensure weekly Thursday TNF_PRIME jobs")
    tnf.add_argument("--weeks", type=int, default=12)
    tnf.add_argument("--instance", default="player 0")
    tnf.add_argument("--minutes", type=float, default=270.0)

    args = p.parse_args(argv)
    if args.cmd == "add":
        source = {
            "ota": "ota_antenna",
            "antenna": "ota_antenna",
            "ota_antenna": "ota_antenna",
            "streamers": "streamers",
        }.get(args.source, args.source)
        guide = None
        if args.search or args.guide_title:
            guide = {
                "search_query": args.search,
                "channel_title": args.guide_title,
                "source": "manual",
            }
        try:
            job = add_job(
                source_kind=source,
                channel_id=args.channel,
                start_at=args.at,
                minutes=args.minutes,
                media=args.media,
                instance_id=args.instance,
                tuner_id=args.tuner,
                rights_status=args.rights_status,
                label=args.label,
                apply_channel=not args.no_channel_apply,
                weekly=bool(args.weekly),
                detach=not args.foreground,
                guide=guide,
                shortcut_id=args.shortcut_id,
                open_via="search" if guide else None,
            )
        except Exception as e:  # noqa: BLE001
            print(json.dumps({"ok": False, "error": str(e)}))
            return 1
        print(json.dumps({"ok": True, "job": job}, indent=2))
        return 0
    if args.cmd == "from-shortcut":
        try:
            job = add_job_from_shortcut(
                shortcut_id=args.id,
                start_at=args.at,
                minutes=args.minutes,
                instance_id=args.instance,
                weekly=bool(args.weekly),
                label=args.label,
            )
        except Exception as e:  # noqa: BLE001
            print(json.dumps({"ok": False, "error": str(e)}))
            return 1
        print(json.dumps({"ok": True, "job": job}, indent=2))
        return 0
    if args.cmd == "from-guide":
        try:
            job = add_job_from_guide_search(
                query=args.query,
                start_at=args.at,
                minutes=args.minutes,
                channel_id=args.channel,
                title_contains=args.title_contains,
                instance_id=args.instance,
                save_as=args.save_as,
                weekly=bool(args.weekly),
                label=args.label,
                open_now=bool(args.open_now),
            )
        except Exception as e:  # noqa: BLE001
            print(json.dumps({"ok": False, "error": str(e)}))
            return 1
        print(json.dumps({"ok": True, "job": job}, indent=2))
        return 0
    if args.cmd == "list":
        print(json.dumps({"jobs": list_jobs(status=args.status)}, indent=2))
        return 0
    if args.cmd == "cancel":
        try:
            job = cancel_job(args.job_id)
        except KeyError as e:
            print(json.dumps({"ok": False, "error": str(e)}))
            return 1
        print(json.dumps({"ok": True, "job": job}, indent=2))
        return 0
    if args.cmd == "run-due":
        result = run_due(execute=not args.dry_run)
        print(json.dumps(result, indent=2))
        return 0
    if args.cmd == "audit":
        from .schedule_audit import audit_schedule

        report = audit_schedule(include_finished=not args.active_only)
        print(json.dumps(report, indent=2))
        return 0 if report.get("ok") else 2
    if args.cmd == "guide-refresh":
        report = refresh_guide_for_upcoming(
            horizon_hours=args.horizon_hours,
            instance_id=args.instance,
            execute_search=not args.dry_run,
        )
        print(json.dumps(report, indent=2))
        return 0 if report.get("ok") else 2
    if args.cmd == "install-task":
        path = install_task_scheduler_script(args.repo)
        print(json.dumps({"ok": True, "script": str(path)}, indent=2))
        return 0
    if args.cmd == "tnf-enqueue":
        from .tnf_thursday import enqueue_thursdays

        print(
            json.dumps(
                enqueue_thursdays(
                    weeks=args.weeks,
                    instance_id=args.instance,
                    minutes=args.minutes,
                ),
                indent=2,
            )
        )
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
