"""Open-model work queue driven by HUSH ERRORS + schedule audit.

Every hush alert becomes a prioritized todo the desk / open model can claim
and resolve. Humans still get SMS/email; the farm also gets a machine-readable
punch list.

Store: ``C:\\OHushData\\indexes\\open_model_todos.json``
Board: ``C:\\OHushData\\indexes\\OPEN_MODEL_TODO.md``
Log:   ``C:\\OHushData\\indexes\\open_model_todos.jsonl``
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import ensure_data_layout

TODO_JSON = "open_model_todos.json"
TODO_BOARD = "OPEN_MODEL_TODO.md"
TODO_LOG = "open_model_todos.jsonl"

# Higher = work sooner. Align with how bad the failure is for the corpus.
PRIORITY = {
    "capture_dead": 100,
    "audit_broken_live": 95,
    "duplicate_stream": 93,
    "pluto_or_pack_epg": 92,
    "wrong_channel": 91,
    "streamers_down": 90,
    "audio_lag": 88,
    "capture_stale": 85,
    "capture_picture_dead": 86,
    "ui_dump_sick": 87,
    "picture_bad": 84,
    "audit_overdue": 80,
    "guide_stuck": 78,
    "guide_open_failed": 75,
    "crosstalk": 70,
    "disk_pressure": 65,
    "upload_failed": 55,
    "shadow_stalled": 50,
    "label_backlog_critical": 40,
}

# What the open model / desk should try first (wired scripts — no improvisation).
ACTIONS = {
    "audit_overdue": [
        "schedule run-due (prefer free player, not busy lock)",
        "if player 0 busy: retarget job to player 1 / next free player",
        "open via shortcut/guide on free instance; start session",
        "re-run schedule audit; resolve todo when verdict leaves overdue",
    ],
    "capture_stale": [
        "heartbeat-fix fix on instance (picture + home local)",
        "if lock dead: release stale capture lock and restart take",
        "verify stills/audio advancing",
    ],
    "capture_picture_dead": [
        "Read spinner_ladder history in farm_run.jsonl (wait → jiggle → channel_hop → reopen)",
        "Named linear (ESPN/MNF): reopen intended only — never alternate local",
        "Local jobs: alternate affiliate / failover market after hop fails",
        "If ladder exhausted: keep tape; escalate human only if picture stays dead",
    ],
    "ui_dump_sick": [
        "Read ui_dump_* in farm_run.jsonl (null_root / empty_hierarchy / soft_empty)",
        "adb connect + recover_streamers; do not swipe-hunt on dump_dead",
        "Wait circuit half-open; re-run nav only after dump_ok",
        "capacity_probe_3 dump latency if systemic",
    ],
    "capture_dead": [
        "inspect capture lock + PID",
        "release dead lock; restart on-air or scheduled take",
        "notify quiet once healthy",
    ],
    "audit_broken_live": [
        "heartbeat-fix fix on instance",
        "schedule audit detail for job",
        "re-open guide card; resume or mark failed with reason",
    ],
    "duplicate_stream": [
        "streams enforce-unique (keep primary; retune secondary)",
        "heartbeat-fix if still same program_key",
        "resolve when fleet program_keys are unique",
    ],
    "wrong_channel": [
        "If lock has named job (MNF_ESPN/ESPN2): jiggle then nav reopen — never Atlanta FOX/NBC",
        "Else heartbeat-fix → hierarchy local; verify calls/network receipt",
    ],
    "pluto_or_pack_epg": [
        "reject pack EPG; open_booth_local Atlanta affiliate (filler only)",
        "heartbeat-fix — but refuse local substitute when named capture locked",
    ],
    "audio_lag": [
        "Named capture: jiggle only (no force-stop / no FOX retune)",
        "Filler only: heartbeat-fix with Alabama failover",
    ],
    "picture_bad": [
        "Named capture: jiggle → nav reopen intended",
        "Filler: recover Streamers + picture + home local",
    ],
    "guide_stuck": [
        "If locked player: leave it (no Back). Else heartbeat-fix to picture",
    ],
    "streamers_down": [
        "streamers_alive + recover",
        "heartbeat-fix fix",
        "salvation login if credentials screen",
    ],
    "guide_open_failed": [
        "windows layout --mode fill --focus <instance> if dump/aim fails off-screen",
        "nav/open search with fresh dump",
        "reject MAX SPORTS when goal is national linear",
        "retry once; escalate if still failing",
    ],
    "crosstalk": [
        "process-loopback probe per HD-Player PID",
        "windows layout --mode split|grid so each player is visible",
        "do not record until isolation ok",
    ],
    "disk_pressure": [
        "stop new records",
        "package/upload or prune work temps",
    ],
    "upload_failed": [
        "retry GCS upload for session",
        "check credentials / quota",
    ],
    "shadow_stalled": [
        "check sports_daemon single instance",
        "restart live engine if shadow.jsonl stalled",
    ],
    "label_backlog_critical": [
        "overnight farm label tick",
        "human /farm only if trust gate requires",
    ],
}

# Root causes that become open-model todos (desk/heartbeat feed these).
POLICY_EVENTS = frozenset(
    {
        "duplicate_stream",
        "wrong_channel",
        "pluto_or_pack_epg",
        "audio_lag",
        "picture_bad",
        "guide_stuck",
        "streamers_down",
        "open_failed",
    }
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def store_path(root: Path | None = None) -> Path:
    return ensure_data_layout(root) / "indexes" / TODO_JSON


def board_path(root: Path | None = None) -> Path:
    return ensure_data_layout(root) / "indexes" / TODO_BOARD


def log_path(root: Path | None = None) -> Path:
    return ensure_data_layout(root) / "indexes" / TODO_LOG


def _append_log(row: dict[str, Any], root: Path | None = None) -> None:
    path = log_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, default=str) + "\n")


def load(root: Path | None = None) -> dict[str, Any]:
    path = store_path(root)
    if not path.is_file():
        return {"updated_utc": _now(), "items": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        data = {"items": []}
    data.setdefault("items", [])
    return data


def save(data: dict[str, Any], root: Path | None = None) -> Path:
    path = store_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = dict(data)
    data["updated_utc"] = _now()
    # Always keep sorted by priority desc, then newest bump
    items = list(data.get("items") or [])
    items.sort(
        key=lambda x: (
            -int(x.get("priority") or 0),
            -float(x.get("bumped_unix") or 0),
        )
    )
    data["items"] = items
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    write_board(data, root)
    return path


def _score(event: str, *, age_boost: float = 0.0) -> int:
    base = int(PRIORITY.get(event, 60))
    return min(100, base + int(age_boost))


def _todo_instance_id(todo: dict[str, Any]) -> str:
    meta = todo.get("meta") or {}
    iid = str(meta.get("instance_id") or "")
    if iid:
        return iid
    key = str(todo.get("key") or "")
    # Instance-keyed policy todos use engine id or player label as key.
    if key.startswith("Nougat") or key.startswith("Tiramisu") or key.startswith("player"):
        return key
    return ""


def _instance_enabled(instance_id: str, root: Path | None = None) -> bool:
    if not instance_id:
        return True
    try:
        from .instances import get_instance

        return bool(get_instance(instance_id, root).get("enabled", True))
    except Exception:
        return True


def _instance_guide_ui(instance_id: str, root: Path | None = None) -> str | None:
    """Return heartbeat ui_kind when it is guide/search; else None."""
    if not instance_id:
        return None
    try:
        from .heartbeat_fix import GUIDE_KINDS, _load_state

        row = ((_load_state(root).get("instances") or {}).get(instance_id) or {})
        kind = str(row.get("ui_kind") or "")
        if kind in GUIDE_KINDS:
            return kind
    except Exception:
        return None
    return None


def resolve_disabled_instance_todos(root: Path | None = None) -> dict[str, Any]:
    """Auto-resolve open todos aimed at parked (enabled=false) clones."""
    root = ensure_data_layout(root)
    data = load(root)
    resolved: list[str] = []
    for item in data.get("items") or []:
        if item.get("status") not in {"open", "claimed", "blocked"}:
            continue
        iid = _todo_instance_id(item)
        if iid and not _instance_enabled(iid, root):
            item["status"] = "resolved"
            item["resolved_utc"] = _now()
            item["resolve_note"] = "auto:instance_disabled"
            resolved.append(str(item.get("todo_key") or item.get("id")))
    if resolved:
        save(data, root)
        _append_log(
            {"kind": "resolved_disabled", "released": resolved, "utc": _now()},
            root,
        )
    return {"ok": True, "resolved": resolved, "count": len(resolved)}


def ingest_hush(
    event: str,
    *,
    key: str,
    detail: str = "",
    source: str = "notify",
    meta: dict[str, Any] | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Upsert a todo from a HUSH ERROR. Safe to call on every alert (incl. cooldown)."""
    root = ensure_data_layout(root)
    data = load(root)
    items: list[dict[str, Any]] = list(data.get("items") or [])
    todo_key = f"{event}:{key}"
    now_u = time.time()
    existing = next((x for x in items if x.get("todo_key") == todo_key), None)
    actions = list(ACTIONS.get(event) or ["inspect logs", "schedule audit", "desk preflight"])

    if existing and existing.get("status") in {"open", "claimed", "blocked"}:
        existing["detail"] = detail or existing.get("detail")
        existing["bumped_utc"] = _now()
        existing["bumped_unix"] = now_u
        existing["bump_count"] = int(existing.get("bump_count") or 1) + 1
        # Escalate priority slightly each bump (cap 100)
        existing["priority"] = _score(event, age_boost=min(15, existing["bump_count"]))
        existing["meta"] = {**(existing.get("meta") or {}), **(meta or {})}
        existing["actions"] = actions
        row = existing
        action = "bumped"
    elif existing and existing.get("status") == "resolved":
        # Re-open if the same failure returns
        existing.update(
            {
                "status": "open",
                "detail": detail,
                "bumped_utc": _now(),
                "bumped_unix": now_u,
                "bump_count": int(existing.get("bump_count") or 0) + 1,
                "priority": _score(event, age_boost=5),
                "resolved_utc": None,
                "claim": None,
                "meta": {**(existing.get("meta") or {}), **(meta or {})},
                "actions": actions,
                "reopened_utc": _now(),
            }
        )
        row = existing
        action = "reopened"
    else:
        row = {
            "id": uuid.uuid4().hex[:12],
            "todo_key": todo_key,
            "event": event,
            "key": key,
            "title": f"HUSH {event}: {key}",
            "detail": detail,
            "priority": _score(event),
            "status": "open",
            "source": source,
            "actions": actions,
            "created_utc": _now(),
            "bumped_utc": _now(),
            "bumped_unix": now_u,
            "bump_count": 1,
            "meta": meta or {},
        }
        items.append(row)
        action = "created"

    data["items"] = items
    save(data, root)
    _append_log({"kind": action, "todo": row, "utc": _now()}, root)
    return {"ok": True, "action": action, "todo": row}


def ingest_policy(
    event: str,
    *,
    instance_id: str,
    detail: str = "",
    meta: dict[str, Any] | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Upsert a channel-policy todo (duplicate / wrong affiliate / lag / Pluto)."""
    ev = str(event or "wrong_channel")
    if ev == "open_failed":
        ev = "wrong_channel"
    if ev not in PRIORITY:
        ev = "wrong_channel"
    return ingest_hush(
        ev,
        key=instance_id,
        detail=detail or ev,
        source="stream_policy",
        meta={"instance_id": instance_id, **(meta or {})},
        root=root,
    )


def ingest_from_fleet(root: Path | None = None) -> list[dict[str, Any]]:
    """Walk STREAM_STATUS fleet rows → open todos for bad root_causes."""
    root = ensure_data_layout(root)
    out: list[dict[str, Any]] = []
    try:
        from .stream_status import fleet_rows
    except Exception:
        return out
    for row in fleet_rows(root):
        rc = str(row.get("root_cause") or "")
        if rc not in POLICY_EVENTS and rc != "open_failed":
            continue
        if row.get("ok") is True and rc == "ok":
            continue
        iid = str(row.get("instance_id") or "")
        if not iid:
            continue
        # Parked clones must not refill the queue or steal desk claims.
        if not _instance_enabled(iid, root):
            continue
        detail = (
            f"{iid} rc={rc} title={row.get('selected_title') or '—'} "
            f"prog={row.get('program_key') or '—'} calls={row.get('calls') or '—'}"
        )
        out.append(
            ingest_policy(
                rc,
                instance_id=iid,
                detail=detail,
                meta={
                    "program_key": row.get("program_key"),
                    "calls": row.get("calls"),
                    "network": row.get("network"),
                    "selected_title": row.get("selected_title"),
                    "root_cause": rc,
                },
                root=root,
            )
        )
    return out


def ingest_from_audit(report: dict[str, Any], root: Path | None = None) -> list[dict[str, Any]]:
    """Mirror notify_from_audit into the todo queue (even when notify is on cooldown)."""
    from .notify import _stale_page_after

    out: list[dict[str, Any]] = []
    for job in report.get("jobs") or []:
        verdict = str(job.get("verdict") or "")
        jid = str(job.get("job_id") or "")
        label = str(job.get("label") or job.get("channel_id") or jid)
        issues = "; ".join(job.get("issues") or []) or verdict
        tape = job.get("tape") or {}
        detail = (
            f"{label} job={jid} verdict={verdict} "
            f"stills={tape.get('still_count')} audio_s={tape.get('audio_seconds')} {issues}"
        )
        # Match notify policy: only queue after remediation / recover attempt.
        recover = job.get("recover") or {}
        recover_done = bool(recover.get("attempted")) or bool(recover.get("skipped"))
        streak = int(job.get("verdict_streak") or 0)
        event = None
        ladder_exhausted = bool(recover.get("ladder_exhausted"))
        ladder_continue = bool(recover.get("ladder_continue"))
        if verdict == "overdue":
            event = "audit_overdue"
        elif (
            verdict == "picture_dead_live"
            and job.get("pid_alive") is True
            and ladder_exhausted
            and streak >= _stale_page_after()
        ):
            event = "capture_picture_dead"
        elif (
            verdict == "stale_live"
            and job.get("pid_alive") is True
            and recover_done
            and not ladder_continue
            and streak >= _stale_page_after()
        ):
            event = "capture_stale"
        elif (
            verdict in ("broken_live", "started_no_session")
            and job.get("pid_alive") is True
            and recover_done
            and streak >= 2
        ):
            event = "audit_broken_live"
        if event:
            out.append(
                ingest_hush(
                    event,
                    key=jid,
                    detail=detail,
                    source="schedule_audit",
                    meta={
                        "label": label,
                        "verdict": verdict,
                        "shortcut_id": job.get("shortcut_id"),
                        "issues": job.get("issues"),
                    },
                    root=root,
                )
            )
    return out


def ingest_ui_dump_health(
    summary: dict[str, Any] | None = None,
    root: Path | None = None,
) -> list[dict[str, Any]]:
    """Open todos for instances with dump circuit open or soft_empty storms."""
    from .ui_dump import dump_health_summary

    root = ensure_data_layout(root)
    summary = summary or dump_health_summary(root)
    out: list[dict[str, Any]] = []
    sick = list(summary.get("sick_instances") or [])
    circuits = summary.get("circuits") or {}
    by_inst = summary.get("by_instance") or {}
    for iid in sick:
        circ = circuits.get(iid) or {}
        bucket = by_inst.get(iid) or {}
        detail = (
            f"uiautomator sick on {iid}: soft_empty={bucket.get('soft_empty', 0)} "
            f"fail={bucket.get('fail', 0)} circuit={circ.get('circuit') or '—'} "
            f"streak={circ.get('streak') or 0} last={circ.get('last_reason') or bucket.get('last_reason')}"
        )
        out.append(
            ingest_hush(
                "ui_dump_sick",
                key=iid,
                detail=detail,
                source="ui_dump",
                meta={
                    "instance_id": iid,
                    "circuit": circ.get("circuit"),
                    "streak": circ.get("streak"),
                    "soft_empty": bucket.get("soft_empty"),
                    "fail": bucket.get("fail"),
                    "last_reason": circ.get("last_reason") or bucket.get("last_reason"),
                },
                root=root,
            )
        )
    return out


def reprioritize(root: Path | None = None) -> dict[str, Any]:
    """Refresh priorities from open items + latest audit; write board."""
    root = ensure_data_layout(root)
    stale = reclaim_stale_claims(root)
    disabled = resolve_disabled_instance_todos(root)
    data = load(root)
    now_u = time.time()
    for item in data.get("items") or []:
        if item.get("status") not in {"open", "claimed", "blocked"}:
            continue
        age_h = max(0.0, (now_u - float(item.get("bumped_unix") or now_u)) / 3600.0)
        event = str(item.get("event") or "")
        item["priority"] = _score(event, age_boost=min(20, int(age_h * 2)))
        # Already on guide/search: finish-open beats another wrong_channel section crawl.
        iid = _todo_instance_id(item)
        if iid and _instance_guide_ui(iid, root):
            if event in {"guide_stuck", "picture_bad"}:
                item["priority"] = max(int(item["priority"]), 110)
            elif event in {"wrong_channel", "pluto_or_pack_epg", "duplicate_stream"}:
                item["priority"] = min(int(item["priority"]), 82)
    # Pull fresh audit + fleet policy attention into queue
    audit_n = 0
    fleet_n = 0
    try:
        from .schedule_audit import audit_schedule

        report = audit_schedule(include_finished=True)
        ingested = ingest_from_audit(report, root=root)
        audit_n = len(ingested)
        data = load(root)  # reload after ingest
    except Exception as exc:  # noqa: BLE001
        data.setdefault("last_reprioritize_error", str(exc))
    try:
        fleet_ingested = ingest_from_fleet(root)
        fleet_n = len(fleet_ingested)
        data = load(root)
    except Exception as exc:  # noqa: BLE001
        data.setdefault("last_fleet_ingest_error", str(exc))

    # Re-apply guide boost after ingest (new bumps may have reset priority).
    for item in data.get("items") or []:
        if item.get("status") not in {"open", "claimed", "blocked"}:
            continue
        event = str(item.get("event") or "")
        iid = _todo_instance_id(item)
        if iid and _instance_guide_ui(iid, root):
            if event in {"guide_stuck", "picture_bad"}:
                item["priority"] = max(int(item.get("priority") or 0), 110)
            elif event in {"wrong_channel", "pluto_or_pack_epg", "duplicate_stream"}:
                item["priority"] = min(int(item.get("priority") or 100), 82)

    save(data, root)
    open_n = sum(1 for x in data.get("items") or [] if x.get("status") == "open")
    return {
        "ok": True,
        "open": open_n,
        "audit_ingested": audit_n,
        "fleet_ingested": fleet_n,
        "disabled_resolved": disabled.get("count"),
        "stale_claims_released": stale.get("count"),
        "board": str(board_path(root)),
        "store": str(store_path(root)),
        "top": next_open(root),
    }


CLAIM_STALE_SEC = float(__import__("os").environ.get("OHUSH_TODO_CLAIM_STALE_SEC") or 600)


def release_claim(
    todo_id: str,
    *,
    note: str = "",
    root: Path | None = None,
) -> dict[str, Any]:
    """Return a claimed todo to open so the next tick can retry (no deadlock)."""
    data = load(root)
    for item in data.get("items") or []:
        if item.get("id") == todo_id or item.get("todo_key") == todo_id:
            if item.get("status") != "claimed":
                return {"ok": True, "todo": item, "skipped": True}
            item["status"] = "open"
            item["claim"] = None
            item["last_release_utc"] = _now()
            item["last_release_note"] = note
            item["bumped_utc"] = _now()
            item["bumped_unix"] = time.time()
            save(data, root)
            _append_log(
                {"kind": "released", "todo_id": item["id"], "note": note, "utc": _now()},
                root,
            )
            return {"ok": True, "todo": item}
    return {"ok": False, "error": "not_found"}


def reclaim_stale_claims(
    root: Path | None = None,
    *,
    stale_sec: float | None = None,
) -> dict[str, Any]:
    """Unstick claims older than stale_sec (desk crash / failed fix without release)."""
    root = ensure_data_layout(root)
    stale_sec = float(stale_sec if stale_sec is not None else CLAIM_STALE_SEC)
    data = load(root)
    now = time.time()
    released: list[str] = []
    for item in data.get("items") or []:
        if item.get("status") != "claimed":
            continue
        claim_meta = item.get("claim") or {}
        claimed_at = float(claim_meta.get("unix") or item.get("bumped_unix") or 0)
        age = now - claimed_at if claimed_at else stale_sec + 1
        if age >= stale_sec:
            item["status"] = "open"
            item["claim"] = None
            item["last_release_note"] = f"stale_claim>{stale_sec}s"
            item["last_release_utc"] = _now()
            released.append(str(item.get("todo_key") or item.get("id")))
    if released:
        save(data, root)
        _append_log({"kind": "reclaim_stale", "released": released, "utc": _now()}, root)
    return {"ok": True, "released": released, "count": len(released)}


def next_open(root: Path | None = None) -> dict[str, Any] | None:
    reclaim_stale_claims(root)
    resolve_disabled_instance_todos(root)
    data = load(root)
    open_items = [x for x in (data.get("items") or []) if x.get("status") == "open"]

    def _rank(item: dict[str, Any]) -> tuple[int, float]:
        event = str(item.get("event") or "")
        pri = int(item.get("priority") or 0)
        iid = _todo_instance_id(item)
        if iid and _instance_guide_ui(iid, root):
            if event in {"guide_stuck", "picture_bad"}:
                pri = max(pri, 110)
            elif event in {"wrong_channel", "pluto_or_pack_epg", "duplicate_stream"}:
                pri = min(pri, 82)
        return (-pri, -float(item.get("bumped_unix") or 0))

    open_items.sort(key=_rank)
    for item in open_items:
        iid = _todo_instance_id(item)
        if iid and not _instance_enabled(iid, root):
            continue
        return item
    return None


def claim(todo_id: str, *, owner: str = "desk", root: Path | None = None) -> dict[str, Any]:
    data = load(root)
    for item in data.get("items") or []:
        if item.get("id") == todo_id or item.get("todo_key") == todo_id:
            if item.get("status") not in {"open", "claimed"}:
                return {"ok": False, "error": f"status={item.get('status')}"}
            item["status"] = "claimed"
            item["claim"] = {"owner": owner, "utc": _now(), "unix": time.time()}
            item["bumped_unix"] = time.time()
            item["bumped_utc"] = _now()
            save(data, root)
            _append_log({"kind": "claimed", "todo_id": item["id"], "owner": owner, "utc": _now()}, root)
            return {"ok": True, "todo": item}
    return {"ok": False, "error": "not_found"}


def resolve(
    todo_id: str,
    *,
    note: str = "",
    root: Path | None = None,
) -> dict[str, Any]:
    data = load(root)
    for item in data.get("items") or []:
        if item.get("id") == todo_id or item.get("todo_key") == todo_id:
            item["status"] = "resolved"
            item["resolved_utc"] = _now()
            item["resolve_note"] = note
            save(data, root)
            _append_log({"kind": "resolved", "todo_id": item["id"], "note": note, "utc": _now()}, root)
            return {"ok": True, "todo": item}
    return {"ok": False, "error": "not_found"}


def block(todo_id: str, *, reason: str, root: Path | None = None) -> dict[str, Any]:
    data = load(root)
    for item in data.get("items") or []:
        if item.get("id") == todo_id or item.get("todo_key") == todo_id:
            item["status"] = "blocked"
            item["block_reason"] = reason
            item["bumped_utc"] = _now()
            save(data, root)
            return {"ok": True, "todo": item}
    return {"ok": False, "error": "not_found"}


def write_board(data: dict[str, Any] | None = None, root: Path | None = None) -> Path:
    root = ensure_data_layout(root)
    data = data or load(root)
    items = list(data.get("items") or [])
    open_items = [x for x in items if x.get("status") in {"open", "claimed", "blocked"}]
    lines = [
        "# Open-model TODO (HUSH + stream policy)",
        "",
        f"Updated `{data.get('updated_utc') or _now()}`",
        "",
        "HUSH ERRORS **and** fleet policy failures (`duplicate_stream`, `wrong_channel`, "
        "`audio_lag`, Pluto…) land here. Desk claims the top item and runs **wired** "
        "scripts only (heartbeat-fix / enforce-unique) — no free-form channel picks.",
        "",
        f"Open/claimed/blocked: **{len(open_items)}**",
        "",
        "| P | Status | Event | Key | Detail | Next actions |",
        "|--:|---|---|---|---|---|",
    ]
    for x in open_items[:40]:
        acts = "; ".join((x.get("actions") or [])[:2])
        detail = (x.get("detail") or "").replace("|", "/")[:80]
        lines.append(
            f"| {x.get('priority')} | {x.get('status')} | `{x.get('event')}` | "
            f"`{x.get('key')}` | {detail} | {acts} |"
        )
    if not open_items:
        lines.append("| — | — | — | — | queue clear | — |")
    lines.extend(
        [
            "",
            "## Commands",
            "",
            "```powershell",
            "python -m tools.windows_lab todos reprioritize",
            "python -m tools.windows_lab todos next",
            "python -m tools.windows_lab todos claim --id <id>",
            "python -m tools.windows_lab todos resolve --id <id> --note \"…\"",
            "```",
            "",
        ]
    )
    path = board_path(root)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def attempt_fix(todo: dict[str, Any], *, root: Path | None = None) -> dict[str, Any]:
    """Best-effort auto fix for a claimed hush todo (desk calls this)."""
    root = ensure_data_layout(root)
    event = str(todo.get("event") or "")
    steps: list[dict[str, Any]] = []

    if event == "audit_overdue":
        # Try schedule run-due — free instance may pick it up
        from .desk_orchestrator import _run_module

        due = _run_module(["schedule", "run-due"], timeout=180.0)
        steps.append({"step": "schedule_run_due", "ok": due.get("ok"), "tail": (due.get("stdout_tail") or "")[-400:]})
        audit = _run_module(["schedule", "audit"], timeout=120.0)
        steps.append({"step": "schedule_audit", "ok": audit.get("ok")})
        # If job no longer overdue, resolve
        parsed = audit.get("parsed") or {}
        jid = str(todo.get("key") or "")
        still_overdue = False
        for job in parsed.get("jobs") or []:
            if str(job.get("job_id")) == jid and job.get("verdict") == "overdue":
                still_overdue = True
                # Prefer blocking with busy reason for model
                issues = job.get("issues") or []
                if any("busy" in str(i).lower() for i in issues):
                    block(todo["id"], reason="; ".join(map(str, issues)), root=root)
                    return {
                        "ok": False,
                        "blocked": True,
                        "reason": issues,
                        "steps": steps,
                        "lesson": "Overdue because instance busy — need a free player or wait for lock.",
                    }
        if not still_overdue:
            resolve(todo["id"], note="no longer overdue after run-due/audit", root=root)
            return {"ok": True, "resolved": True, "steps": steps}
        return {"ok": False, "steps": steps, "lesson": "Still overdue after run-due — check guide open / instance."}

    if event == "duplicate_stream":
        from .stream_status import enforce_unique_programs

        iid = str((todo.get("meta") or {}).get("instance_id") or todo.get("key") or "")
        if iid and not _instance_enabled(iid, root):
            resolve(todo["id"], note="auto:instance_disabled", root=root)
            return {
                "ok": True,
                "resolved": True,
                "steps": [{"step": "skip_disabled", "ok": True, "instance_id": iid}],
            }
        uniq = enforce_unique_programs(root=root, execute=True)
        steps.append(
            {
                "step": "enforce_unique_programs",
                "ok": bool(uniq.get("ok")),
                "duplicates_found": uniq.get("duplicates_found"),
                "actions": uniq.get("actions"),
            }
        )
        still = int(uniq.get("duplicates_found") or 0) > 0
        if not still:
            resolve(todo["id"], note="fleet programs unique after enforce", root=root)
            return {"ok": True, "resolved": True, "steps": steps}
        # Secondary pass: heartbeat fix on the conflicted instance
        if iid:
            from .heartbeat_fix import GUIDE_KINDS, fix_instance_if_failing, probe_heartbeat

            fixed = fix_instance_if_failing(iid, root=root, force=True)
            steps.append({"step": "heartbeat_fix", "ok": bool(fixed.get("ok")), "result": fixed})
            probe = probe_heartbeat(iid, root=root, save_shot=False)
            ui_kind = str(probe.get("ui_kind") or "")
            steps.append(
                {
                    "step": "heartbeat_probe_after",
                    "ok": bool(probe.get("ok")),
                    "ui_kind": ui_kind,
                    "reason": probe.get("reason"),
                }
            )
            if ui_kind in GUIDE_KINDS:
                return {
                    "ok": False,
                    "steps": steps,
                    "lesson": f"still_on_guide_after_fix:{ui_kind}",
                }
            uniq2 = enforce_unique_programs(root=root, execute=False)
            if int(uniq2.get("duplicates_found") or 0) == 0 and probe.get("ok"):
                resolve(todo["id"], note="unique after heartbeat retune", root=root)
                return {"ok": True, "resolved": True, "steps": steps}
        return {
            "ok": False,
            "steps": steps,
            "lesson": "Still duplicate after enforce-unique — check locks/named jobs.",
        }

    if event in {
        "capture_stale",
        "capture_picture_dead",
        "streamers_down",
        "audit_broken_live",
        "wrong_channel",
        "pluto_or_pack_epg",
        "audio_lag",
        "picture_bad",
        "guide_stuck",
    }:
        iid = str(
            (todo.get("meta") or {}).get("instance_id")
            or todo.get("key")
            or "player 0"
        )
        from .heartbeat_fix import fix_instance_if_failing, probe_heartbeat

        # Clear sticky guide_stuck clocks so a successful fix can pass health.
        try:
            from .heartbeat_fix import _load_state as _hb_load
            from .heartbeat_fix import _save_state as _hb_save

            hb = _hb_load(root)
            row = dict((hb.get("instances") or {}).get(iid) or {})
            row["post_fix_reset"] = _now()
            row.pop("stuck_reason", None)
            hb.setdefault("instances", {})[iid] = row
            _hb_save(hb, root)
        except Exception:
            pass
        if not _instance_enabled(iid, root):
            resolve(todo["id"], note="auto:instance_disabled", root=root)
            return {
                "ok": True,
                "resolved": True,
                "steps": [{"step": "skip_disabled", "ok": True, "instance_id": iid}],
            }
        fixed = fix_instance_if_failing(iid, root=root, force=True)
        steps.append(
            {
                "step": "heartbeat_fix",
                "ok": bool(fixed.get("ok")),
                "reason": fixed.get("reason"),
                "instance_id": iid,
            }
        )
        probe = probe_heartbeat(iid, root=root, save_shot=False)
        ui_kind = str(probe.get("ui_kind") or "")
        steps.append(
            {
                "step": "heartbeat_probe_after",
                "ok": bool(probe.get("ok")),
                "reason": probe.get("reason"),
                "ui_kind": ui_kind,
                "identity": probe.get("identity"),
            }
        )
        try:
            from .heartbeat_fix import GUIDE_KINDS
        except Exception:
            GUIDE_KINDS = frozenset({"guide", "search_ui", "search_hub"})
        # Finish-open contract: guide/search is never a resolved healthy fix.
        if ui_kind in GUIDE_KINDS:
            return {
                "ok": False,
                "steps": steps,
                "lesson": f"still_on_guide_after_fix:{ui_kind}",
            }
        if probe.get("ok"):
            resolve(
                todo["id"],
                note=f"heartbeat ok after fix: {probe.get('reason')}",
                root=root,
            )
            return {"ok": True, "resolved": True, "steps": steps}
        return {
            "ok": False,
            "steps": steps,
            "lesson": f"Still failing after heartbeat_fix: {probe.get('reason')}",
        }

    return {
        "ok": False,
        "steps": steps,
        "lesson": f"No auto-fix wired for {event}; follow actions list.",
    }


def desk_work_once(root: Path | None = None, *, owner: str = "desk") -> dict[str, Any]:
    """Claim top open hush todo and attempt fix — for desk tick.

    Always releases the claim on failure so the queue cannot deadlock.
    """
    root = ensure_data_layout(root)
    reclaim_stale_claims(root)
    top = next_open(root)
    if not top:
        return {"ok": True, "skipped": True, "reason": "queue_empty"}
    claimed = claim(top["id"], owner=owner, root=root)
    if not claimed.get("ok"):
        return claimed
    todo = claimed["todo"]
    try:
        result = attempt_fix(todo, root=root)
    except Exception as exc:  # noqa: BLE001
        release_claim(todo["id"], note=f"attempt_exception:{exc}", root=root)
        return {"ok": False, "todo": todo, "fix": {"ok": False, "error": str(exc)}}
    # Reload — attempt_fix may have resolved/blocked.
    data = load(root)
    cur = next((x for x in (data.get("items") or []) if x.get("id") == todo["id"]), todo)
    if cur.get("status") == "claimed" and not result.get("resolved"):
        if result.get("blocked"):
            pass  # block() already set status
        else:
            release_claim(
                todo["id"],
                note=str(result.get("lesson") or "fix_failed_retry"),
                root=root,
            )
    return {"ok": bool(result.get("ok")), "todo": cur, "fix": result}


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="Open-model TODO queue (HUSH-driven)")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("board", help="Rewrite OPEN_MODEL_TODO.md")
    sub.add_parser("list", help="List open items")
    sub.add_parser("next", help="Show highest-priority open todo")
    sub.add_parser("reprioritize", help="Rescore + ingest latest audit attention")
    c = sub.add_parser("claim", help="Claim a todo")
    c.add_argument("--id", required=True)
    c.add_argument("--owner", default="human")
    r = sub.add_parser("resolve", help="Mark resolved")
    r.add_argument("--id", required=True)
    r.add_argument("--note", default="")
    b = sub.add_parser("block", help="Mark blocked")
    b.add_argument("--id", required=True)
    b.add_argument("--reason", required=True)
    w = sub.add_parser("work", help="Claim top + attempt auto-fix")
    w.add_argument("--owner", default="desk")
    i = sub.add_parser("ingest", help="Manual ingest")
    i.add_argument("--event", required=True)
    i.add_argument("--key", required=True)
    i.add_argument("--detail", default="")

    args = p.parse_args(argv)
    if args.cmd == "board":
        path = write_board()
        print(json.dumps({"ok": True, "board": str(path)}, indent=2))
        return 0
    if args.cmd == "list":
        data = load()
        open_items = [x for x in data.get("items") or [] if x.get("status") != "resolved"]
        print(json.dumps({"ok": True, "items": open_items}, indent=2))
        return 0
    if args.cmd == "next":
        print(json.dumps({"ok": True, "todo": next_open()}, indent=2))
        return 0
    if args.cmd == "reprioritize":
        print(json.dumps(reprioritize(), indent=2, default=str))
        return 0
    if args.cmd == "claim":
        print(json.dumps(claim(args.id, owner=args.owner), indent=2))
        return 0
    if args.cmd == "resolve":
        print(json.dumps(resolve(args.id, note=args.note), indent=2))
        return 0
    if args.cmd == "block":
        print(json.dumps(block(args.id, reason=args.reason), indent=2))
        return 0
    if args.cmd == "work":
        print(json.dumps(desk_work_once(owner=args.owner), indent=2, default=str))
        return 0
    if args.cmd == "ingest":
        print(json.dumps(ingest_hush(args.event, key=args.key, detail=args.detail), indent=2))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
