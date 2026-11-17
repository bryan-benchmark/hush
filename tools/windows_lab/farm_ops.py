"""Farm ops: unified run log, status board, game-day preflight, ON_AIR preempt.

Goal: one auditable event stream + one board + one preflight command so the
capture loop can be trusted and tightened quickly.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import ensure_data_layout
from .locks import get_lock, release
from .scheduler import _parse_when, load_jobs

RUN_LOG_NAME = "farm_run.jsonl"
BOARD_NAME = "FARM_OPS.md"
BOARD_JSON_NAME = "farm_ops.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_log_path(root: Path | None = None) -> Path:
    return ensure_data_layout(root) / "work" / "logs" / RUN_LOG_NAME


def board_path(root: Path | None = None) -> Path:
    return ensure_data_layout(root) / "indexes" / BOARD_NAME


def board_json_path(root: Path | None = None) -> Path:
    return ensure_data_layout(root) / "indexes" / BOARD_JSON_NAME


def emit(
    event: str,
    *,
    detail: str = "",
    job_id: str | None = None,
    session_id: str | None = None,
    instance_id: str | None = None,
    stills: int | None = None,
    audio_s: float | None = None,
    still_age: float | None = None,
    hb_age: float | None = None,
    pid: int | None = None,
    ok: bool | None = None,
    extra: dict[str, Any] | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Append one JSON event to farm_run.jsonl (never raises to callers)."""
    row: dict[str, Any] = {
        "utc": _now_iso(),
        "event": event,
        "detail": detail,
        "job_id": job_id,
        "session_id": session_id,
        "instance_id": instance_id,
        "stills": stills,
        "audio_s": audio_s,
        "still_age": still_age,
        "hb_age": hb_age,
        "pid": pid,
        "ok": ok,
    }
    if extra:
        row["extra"] = extra
    # Drop nulls for readability
    row = {k: v for k, v in row.items() if v is not None}
    try:
        path = run_log_path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception as exc:  # noqa: BLE001
        row["log_error"] = str(exc)
    return row


def _lock_map(root: Path | None = None) -> dict[str, dict[str, Any]]:
    from .instances import list_instances

    out: dict[str, dict[str, Any]] = {}
    for row in list_instances(root):
        iid = str(row.get("id") or "")
        if not iid:
            continue
        lock = get_lock("streamers", iid, root=root)
        if lock:
            out[iid] = lock
    return out


def _live_session_snapshot(session_id: str, root: Path | None = None) -> dict[str, Any]:
    from .schedule_audit import inspect_session

    try:
        return inspect_session(session_id, root=root)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc), "session_id": session_id}


def build_ops_snapshot(root: Path | None = None) -> dict[str, Any]:
    """Single board payload: jobs + locks + live tape health."""
    root = ensure_data_layout(root)
    data = load_jobs(root)
    locks = _lock_map(root)
    now = datetime.now(timezone.utc)
    rows: list[dict[str, Any]] = []
    for job in data.get("jobs") or []:
        status = str(job.get("status") or "")
        if status in ("cancelled",):
            continue
        start = None
        try:
            start = _parse_when(str(job.get("start_utc")))
        except Exception:  # noqa: BLE001
            pass
        due = bool(start and start <= now)
        # Skip far-future waiting noise on the ops board (keep next 36h + live/failed recent)
        if status == "scheduled" and start and (start - now).total_seconds() > 36 * 3600:
            continue
        iid = str(job.get("instance_id") or "")
        sid = job.get("session_id")
        tape = _live_session_snapshot(str(sid), root=root) if sid else None
        lock = locks.get(iid)
        rows.append(
            {
                "job_id": job.get("job_id"),
                "label": job.get("label") or job.get("channel_id"),
                "channel_id": job.get("channel_id"),
                "status": status,
                "start_utc": job.get("start_utc"),
                "due": due,
                "instance_id": iid,
                "session_id": sid,
                "pid": job.get("pid"),
                "minutes": job.get("minutes"),
                "last_error": job.get("last_error") or job.get("closed_reason"),
                "lock_session": (lock or {}).get("session_id"),
                "stills": (tape or {}).get("still_count"),
                "audio_s": (tape or {}).get("audio_seconds"),
                "still_age": (tape or {}).get("newest_still_age_s"),
                "hb_age": (tape or {}).get("audio_heartbeat_age_s"),
                "live_ok": (tape or {}).get("live_ok"),
                "has_chunks": bool((tape or {}).get("wav_count")),
            }
        )
    return {
        "checked_utc": _now_iso(),
        "locks": locks,
        "jobs": rows,
        "run_log": str(run_log_path(root)),
    }


def write_ops_board(root: Path | None = None) -> dict[str, Any]:
    snap = build_ops_snapshot(root)
    lines = [
        "# Farm ops",
        "",
        f"Checked `{snap['checked_utc']}`",
        "",
        f"Run log: `{snap['run_log']}`",
        "",
        "## Locks",
        "",
    ]
    locks = snap.get("locks") or {}
    if not locks:
        lines.append("_none_")
    else:
        for iid, lock in locks.items():
            lines.append(
                f"- `{iid}` → `{lock.get('session_id')}` "
                f"(job={lock.get('job_id') or '—'} since {str(lock.get('acquired_utc') or '')[:19]})"
            )
    lines.extend(
        [
            "",
            "## Jobs (live / due / recent)",
            "",
            "| When | Label | Status | Inst | Stills | Audio s | Still age | HB age | Live | Note |",
            "|---|---|---|---|---:|---:|---:|---:|---|---|",
        ]
    )
    for j in snap.get("jobs") or []:
        note = j.get("last_error") or j.get("lock_session") or "—"
        if isinstance(note, str) and len(note) > 40:
            note = note[:40] + "…"
        lines.append(
            f"| {str(j.get('start_utc') or '')[:16]} | {j.get('label')} | {j.get('status')} | "
            f"{j.get('instance_id') or '—'} | {j.get('stills') if j.get('stills') is not None else '—'} | "
            f"{j.get('audio_s') if j.get('audio_s') is not None else '—'} | "
            f"{j.get('still_age') if j.get('still_age') is not None else '—'} | "
            f"{j.get('hb_age') if j.get('hb_age') is not None else '—'} | "
            f"{j.get('live_ok')} | {note} |"
        )
    lines.extend(
        [
            "",
            "## Commands",
            "",
            "```powershell",
            "python -m tools.windows_lab ops board",
            "python -m tools.windows_lab ops preflight",
            "python -m tools.windows_lab ops preempt-on-air --instance Nougat32",
            "```",
            "",
        ]
    )
    path = board_path(root)
    path.write_text("\n".join(lines), encoding="utf-8")
    board_json_path(root).write_text(json.dumps(snap, indent=2), encoding="utf-8")
    snap["board"] = str(path)
    snap["board_json"] = str(board_json_path(root))
    try:
        from .stream_status import refresh_from_live

        snap["stream_status"] = refresh_from_live(probe=False, root=root)
    except Exception as exc:  # noqa: BLE001
        snap["stream_status_error"] = str(exc)
    return snap


def _is_on_air_lock(lock: dict[str, Any] | None) -> bool:
    if not lock:
        return False
    sid = str(lock.get("session_id") or "")
    return "ON_AIR_CONTINUE" in sid


def _pids_matching(substr: str) -> list[int]:
    """Windows: PIDs whose command line contains substr."""
    if os.name != "nt":
        return []
    ps = (
        "Get-CimInstance Win32_Process | "
        "Where-Object { $_.CommandLine -and $_.CommandLine -like '*" + substr.replace("'", "") + "*' } | "
        "Select-Object -ExpandProperty ProcessId"
    )
    try:
        raw = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command", ps],
            text=True,
            errors="ignore",
            timeout=20,
        )
    except Exception:  # noqa: BLE001
        return []
    pids: list[int] = []
    for line in raw.splitlines():
        line = line.strip()
        if line.isdigit():
            pids.append(int(line))
    return pids


def _kill_pids(pids: list[int]) -> list[int]:
    killed: list[int] = []
    for pid in pids:
        try:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            killed.append(pid)
        except Exception:  # noqa: BLE001
            continue
    return killed


def stop_job_capture(
    job: dict[str, Any],
    *,
    root: Path | None = None,
    reason: str = "stop",
) -> dict[str, Any]:
    """Kill capture PIDs for a job and release its instance lock (idempotent)."""
    root = ensure_data_layout(root)
    sid = str(job.get("session_id") or "")
    iid = str(job.get("instance_id") or "")
    targets: set[int] = set()
    if job.get("pid"):
        try:
            targets.add(int(job["pid"]))
        except (TypeError, ValueError):
            pass
    if sid:
        targets |= set(_pids_matching(sid))
        targets |= set(_pids_matching(f"--job-id {job.get('job_id')}"))
    if job.get("job_id"):
        targets |= set(_pids_matching(f"--job-id {job['job_id']}"))
    killed = _kill_pids(sorted(targets))
    lock_after = None
    if iid:
        release("streamers", iid, root=root)
        lock_after = get_lock("streamers", iid, root=root)
    out = {
        "ok": lock_after is None or not iid,
        "job_id": job.get("job_id"),
        "session_id": sid or None,
        "instance_id": iid or None,
        "killed_pids": killed,
        "reason": reason,
        "lock_after": lock_after,
    }
    emit(
        "stop_capture",
        detail=reason,
        job_id=str(job.get("job_id") or "") or None,
        session_id=sid or None,
        instance_id=iid or None,
        ok=bool(out["ok"]),
        extra={"killed_pids": killed},
        root=root,
    )
    return out


def restart_job(
    job_id: str,
    *,
    root: Path | None = None,
    reason: str = "manual_restart",
    execute: bool = True,
) -> dict[str, Any]:
    """Idempotent restart: kill orphans for job_id, release lock, relaunch same job.

    Does not change channel/minutes/instance — only resets capture bookkeeping
    and starts a fresh detached session under the same job_id.
    """
    from .scheduler import _open_guide_before_record, _start_session_detached, save_jobs

    root = ensure_data_layout(root)
    data = load_jobs(root)
    job = next((j for j in (data.get("jobs") or []) if str(j.get("job_id")) == str(job_id)), None)
    if not job:
        out = {"ok": False, "error": "job_not_found", "job_id": job_id}
        emit("restart", detail="job_not_found", job_id=job_id, ok=False, root=root)
        return out

    old_sid = job.get("session_id")
    old_pid = job.get("pid")
    stopped = stop_job_capture(job, root=root, reason=reason)
    # Brief settle so acquire succeeds.
    time.sleep(0.5)

    job["status"] = "scheduled" if not execute else "running"
    job["last_error"] = None
    job["closed_reason"] = None
    job["close_note"] = None
    job["restarted_utc"] = _now_iso()
    job["restart_reason"] = reason
    job["prior_session_id"] = old_sid
    job["prior_pid"] = old_pid
    job["session_id"] = None
    job["pid"] = None
    job["log"] = None
    save_jobs(data, root)

    if not execute:
        emit(
            "restart",
            detail="dry_preview",
            job_id=str(job_id),
            instance_id=str(job.get("instance_id") or "") or None,
            session_id=str(old_sid) if old_sid else None,
            ok=True,
            extra={"stopped": stopped},
            root=root,
        )
        return {"ok": True, "dry_preview": True, "job": job, "stopped": stopped}

    guide = _open_guide_before_record(job, root=root)
    job["guide_open"] = {
        "ok": guide.get("ok"),
        "selected_title": guide.get("selected_title"),
        "error": guide.get("error"),
        "skipped": guide.get("skipped"),
    }
    if guide.get("ok") is False and not guide.get("skipped"):
        job["status"] = "failed"
        job["last_error"] = guide.get("error") or "guide open failed"
        job["failed_utc"] = _now_iso()
        save_jobs(data, root)
        emit(
            "restart",
            detail="guide_open_failed",
            job_id=str(job_id),
            instance_id=str(job.get("instance_id") or "") or None,
            ok=False,
            extra={"guide": guide, "stopped": stopped},
            root=root,
        )
        return {"ok": False, "error": job["last_error"], "guide": guide, "stopped": stopped}

    result = _start_session_detached(job, root=root)
    if result.get("ok"):
        job["status"] = "started"
        job["session_id"] = result.get("session_id")
        job["pid"] = result.get("pid")
        job["log"] = result.get("log")
        job["started_utc"] = _now_iso()
        save_jobs(data, root)
        emit(
            "restart",
            detail=reason,
            job_id=str(job_id),
            session_id=str(job.get("session_id") or "") or None,
            instance_id=str(job.get("instance_id") or "") or None,
            pid=job.get("pid"),
            ok=True,
            extra={
                "prior_session_id": old_sid,
                "prior_pid": old_pid,
                "killed_pids": stopped.get("killed_pids"),
            },
            root=root,
        )
        write_ops_board(root)
        return {"ok": True, "job": job, "started": result, "stopped": stopped}

    job["status"] = "failed"
    job["last_error"] = result.get("error") or "restart detach failed"
    job["failed_utc"] = _now_iso()
    save_jobs(data, root)
    emit(
        "restart",
        detail=str(job["last_error"]),
        job_id=str(job_id),
        instance_id=str(job.get("instance_id") or "") or None,
        ok=False,
        extra={"stopped": stopped, "result": result},
        root=root,
    )
    return {"ok": False, "error": job["last_error"], "stopped": stopped, "result": result}


def preempt_on_air(
    instance_id: str,
    *,
    root: Path | None = None,
    reason: str = "scheduled_job_needs_instance",
    force: bool = False,
) -> dict[str, Any]:
    """Stop ON_AIR_CONTINUE on an instance and release its lock.

    Only touches locks whose session_id contains ON_AIR_CONTINUE unless force=True.
    """
    root = ensure_data_layout(root)
    lock = get_lock("streamers", instance_id, root=root)
    if not lock:
        out = {
            "ok": True,
            "skipped": True,
            "reason": "no_lock",
            "instance_id": instance_id,
        }
        emit("preempt_on_air", detail="no_lock", instance_id=instance_id, ok=True, root=root)
        return out
    if not force and not _is_on_air_lock(lock):
        out = {
            "ok": False,
            "error": "lock_not_on_air_continue",
            "instance_id": instance_id,
            "lock": lock,
        }
        emit(
            "preempt_on_air",
            detail="refused_non_on_air_lock",
            instance_id=instance_id,
            session_id=str(lock.get("session_id") or ""),
            ok=False,
            extra={"lock": lock},
            root=root,
        )
        return out

    sid = str(lock.get("session_id") or "")
    # Kill session / helper processes tied to this session or ON_AIR on this instance.
    targets = set(_pids_matching(sid)) if sid else set()
    targets |= set(_pids_matching(f"ON_AIR_CONTINUE --instance {instance_id}"))
    targets |= set(_pids_matching(f"--channel ON_AIR_CONTINUE"))
    # Narrow: only kill if command also mentions instance or session
    narrowed: list[int] = []
    for pid in sorted(targets):
        try:
            raw = subprocess.check_output(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    f"(Get-CimInstance Win32_Process -Filter \"ProcessId={pid}\").CommandLine",
                ],
                text=True,
                timeout=8,
                errors="ignore",
            )
        except Exception:  # noqa: BLE001
            continue
        low = (raw or "").lower()
        if "on_air_continue" in low or (sid and sid.lower() in low):
            if instance_id.lower() in low or (sid and sid.lower() in low) or "processloopback" in low:
                narrowed.append(pid)
    # Also kill ProcessLoopbackNative writing into this session dir
    if sid:
        narrowed.extend(_pids_matching(sid.replace("\\", "\\\\")))
    narrowed = sorted(set(narrowed))
    killed = _kill_pids(narrowed)
    release("streamers", instance_id, root=root)
    # Brief settle so next acquire succeeds
    time.sleep(0.5)
    still = get_lock("streamers", instance_id, root=root)
    out = {
        "ok": still is None,
        "instance_id": instance_id,
        "reason": reason,
        "session_id": sid,
        "killed_pids": killed,
        "lock_after": still,
    }
    emit(
        "preempt_on_air",
        detail=reason,
        instance_id=instance_id,
        session_id=sid,
        ok=out["ok"],
        extra={"killed_pids": killed},
        root=root,
    )
    return out


def preflight(
    root: Path | None = None,
    *,
    instances: list[str] | None = None,
    notify_test: bool = False,
    chunk_probe_s: float = 8.0,
) -> dict[str, Any]:
    """Game-day preflight: instances, locks, shortcuts, chunk path, optional notify."""
    root = ensure_data_layout(root)
    from .instances import list_instances
    from .process_loopback import ensure_helper, hd_players, resolve_hd_player_pid

    wanted = instances or ["Nougat32", "Nougat32_1"]
    checks: list[dict[str, Any]] = []
    blockers: list[str] = []
    warnings: list[str] = []

    # 1) Helper binary
    try:
        helper = ensure_helper()
        checks.append({"check": "process_loopback_helper", "ok": True, "path": str(helper)})
    except Exception as exc:  # noqa: BLE001
        blockers.append(f"helper:{exc}")
        checks.append({"check": "process_loopback_helper", "ok": False, "error": str(exc)})

    # 2) HD-Player / instances
    players = hd_players()
    checks.append({"check": "hd_players", "ok": bool(players), "players": players})
    if not players:
        blockers.append("no_hd_player")

    reg = {str(r.get("id")): r for r in list_instances(root)}
    for iid in wanted:
        row = reg.get(iid)
        if not row or not row.get("enabled", True):
            blockers.append(f"instance_missing_or_disabled:{iid}")
            checks.append({"check": f"instance:{iid}", "ok": False})
            continue
        lock = get_lock("streamers", iid, root=root)
        on_air = _is_on_air_lock(lock)
        title = str(row.get("window_title") or "")
        pid_ok = False
        pid_err = None
        try:
            hit = resolve_hd_player_pid(window_title=title or None, instance_id=iid)
            pid_ok = True
            checks.append(
                {
                    "check": f"instance:{iid}",
                    "ok": True,
                    "pid": hit.get("pid"),
                    "title": hit.get("title"),
                    "lock": lock,
                    "on_air_continue": on_air,
                }
            )
        except Exception as exc:  # noqa: BLE001
            pid_err = str(exc)
            warnings.append(f"instance_pid:{iid}:{exc}")
            checks.append(
                {
                    "check": f"instance:{iid}",
                    "ok": False,
                    "error": pid_err,
                    "lock": lock,
                    "on_air_continue": on_air,
                }
            )
        if on_air:
            warnings.append(f"on_air_holds:{iid}")

    # 3) Parent→child local recipes + shortcuts for near-due jobs
    try:
        from .us_locals import ensure_market_local_shortcuts

        seeded = ensure_market_local_shortcuts(root=root)
        checks.append(
            {
                "check": "section_child_locals",
                "ok": True,
                "seeded": len(seeded),
                "ids": [r.get("id") for r in seeded[:16]],
            }
        )
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"section_child_seed:{exc}")
        checks.append({"check": "section_child_locals", "ok": False, "error": str(exc)})

    data = load_jobs(root)
    now = datetime.now(timezone.utc)
    near = []
    for job in data.get("jobs") or []:
        if job.get("status") != "scheduled":
            continue
        try:
            start = _parse_when(str(job["start_utc"]))
        except Exception:  # noqa: BLE001
            continue
        hours = (start - now).total_seconds() / 3600.0
        if -0.1 <= hours <= 36:
            near.append(job)
    missing_sc = []
    from .streamers_open import get_shortcut
    from .us_locals import resolve_local_pick

    for job in near:
        sc = job.get("shortcut_id")
        if not sc:
            continue
        try:
            get_shortcut(str(sc), root)
            continue
        except Exception:  # noqa: BLE001
            pass
        # FOX_NY-style ids resolve via parent section even before a row exists.
        if resolve_local_pick(str(sc), channel_id=str(job.get("channel_id") or ""), root=root):
            continue
        missing_sc.append(str(sc))
    checks.append(
        {
            "check": "near_due_shortcuts",
            "ok": not missing_sc,
            "near_due": len(near),
            "missing": missing_sc,
        }
    )
    if missing_sc:
        blockers.append(f"missing_shortcuts:{missing_sc}")

    # 4) Short chunk probe on primary if free and resolvable
    primary = wanted[0]
    lock = get_lock("streamers", primary, root=root)
    probe: dict[str, Any] = {"skipped": True}
    if not lock and chunk_probe_s > 0:
        try:
            from .process_loopback import record_process_loopback, resolve_hd_player_pid

            hit = resolve_hd_player_pid(instance_id=primary)
            out_dir = ensure_data_layout(root) / "work" / "preflight_probe"
            out_dir.mkdir(parents=True, exist_ok=True)
            wav = out_dir / "preflight_chunk.wav"
            if wav.is_file():
                wav.unlink()
            info = record_process_loopback(
                pid=int(hit["pid"]),
                seconds=float(chunk_probe_s),
                out_path=wav,
            )
            ok = wav.is_file() and wav.stat().st_size > 1024
            probe = {
                "skipped": False,
                "ok": ok,
                "bytes": wav.stat().st_size if wav.is_file() else 0,
                "pid": hit.get("pid"),
                "info": {k: info.get(k) for k in ("peak", "returncode", "seconds")},
            }
            if not ok:
                blockers.append("chunk_probe_failed")
        except Exception as exc:  # noqa: BLE001
            probe = {"skipped": False, "ok": False, "error": str(exc)}
            blockers.append(f"chunk_probe:{exc}")
    elif lock:
        probe = {"skipped": True, "reason": "primary_busy", "lock": lock}
        warnings.append("chunk_probe_skipped_busy")
    checks.append({"check": "chunk_probe", **probe})

    # 5) Optional notify smoke (email+sms)
    notify_row = None
    if notify_test:
        try:
            from .notify import notify

            notify_row = notify(
                "capture_stale",
                detail="preflight notify smoke (safe to ignore)",
                dedupe_key="preflight_smoke",
                force=True,
                channels="auto",
                root=root,
            )
            if not notify_row.get("ok"):
                warnings.append("notify_test_failed")
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"notify_test:{exc}")
            notify_row = {"ok": False, "error": str(exc)}

    ok = not blockers
    report = {
        "ok": ok,
        "checked_utc": _now_iso(),
        "blockers": blockers,
        "warnings": warnings,
        "checks": checks,
        "notify_test": notify_row,
        "near_due_jobs": [
            {
                "job_id": j.get("job_id"),
                "label": j.get("label"),
                "start_utc": j.get("start_utc"),
                "instance_id": j.get("instance_id"),
                "shortcut_id": j.get("shortcut_id"),
            }
            for j in near
        ],
    }
    emit(
        "preflight",
        detail="ok" if ok else f"blocked:{blockers}",
        ok=ok,
        extra={"warnings": warnings, "blockers": blockers},
        root=root,
    )
    board = write_ops_board(root)
    report["board"] = board.get("board")
    path = ensure_data_layout(root) / "indexes" / "FARM_PREFLIGHT.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    report["preflight_json"] = str(path)
    return report


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="Farm ops: log, board, preflight, preempt")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("board", help="Write FARM_OPS.md (+ STREAM_STATUS.md) board")
    st = sub.add_parser("streams", help="Write STREAM_STATUS.md uptime board")
    st.add_argument("--probe", action="store_true")
    st.add_argument("--instances", default="")
    sub.add_parser("log-tail", help="Print last N farm_run events").add_argument(
        "-n", type=int, default=30
    )
    pf = sub.add_parser("preflight", help="Game-day preflight")
    pf.add_argument("--instances", default="Nougat32,Nougat32_1")
    pf.add_argument("--notify-test", action="store_true")
    pf.add_argument("--chunk-probe-s", type=float, default=8.0)
    pf.add_argument("--no-chunk-probe", action="store_true")
    pr = sub.add_parser("preempt-on-air", help="Kill ON_AIR_CONTINUE on an instance")
    pr.add_argument("--instance", required=True)
    pr.add_argument("--force", action="store_true", help="Kill even if lock is not ON_AIR")
    pr.add_argument("--reason", default="manual_preempt")
    rs = sub.add_parser("restart", help="Idempotent kill+relaunch for one job_id")
    rs.add_argument("--job-id", required=True)
    rs.add_argument("--reason", default="manual_restart")
    rs.add_argument("--dry-run", action="store_true")
    hb = sub.add_parser("heartbeat-fix", help="Fix stream(s) when picture/audio heartbeat fails")
    hb.add_argument("--instance")
    hb.add_argument("--scan", action="store_true", help="Probe enabled instances and fix failures")
    hb.add_argument("--only-locked", action="store_true")
    hb.add_argument("--force", action="store_true")
    hb.add_argument("--max-fixes", type=int, default=3)
    ev = sub.add_parser("emit", help="Append a manual farm_run event")
    ev.add_argument("--event", required=True)
    ev.add_argument("--detail", default="")
    ev.add_argument("--job-id")
    ev.add_argument("--instance")
    args = p.parse_args(argv)

    if args.cmd == "board":
        print(json.dumps(write_ops_board(), indent=2))
        return 0
    if args.cmd == "streams":
        from .stream_status import refresh_from_live

        inst = [x.strip() for x in str(args.instances).split(",") if x.strip()] or None
        print(json.dumps(refresh_from_live(instances=inst, probe=bool(args.probe)), indent=2)[:4000])
        return 0
    if args.cmd == "log-tail":
        path = run_log_path()
        if not path.is_file():
            print(json.dumps({"ok": True, "events": []}, indent=2))
            return 0
        lines = path.read_text(encoding="utf-8").splitlines()
        rows = [json.loads(x) for x in lines[-args.n :] if x.strip()]
        print(json.dumps({"ok": True, "events": rows}, indent=2))
        return 0
    if args.cmd == "preflight":
        inst = [x.strip() for x in str(args.instances).split(",") if x.strip()]
        report = preflight(
            instances=inst,
            notify_test=bool(args.notify_test),
            chunk_probe_s=0.0 if args.no_chunk_probe else float(args.chunk_probe_s),
        )
        print(json.dumps(report, indent=2))
        return 0 if report.get("ok") else 2
    if args.cmd == "preempt-on-air":
        out = preempt_on_air(args.instance, reason=args.reason, force=bool(args.force))
        print(json.dumps(out, indent=2))
        return 0 if out.get("ok") or out.get("skipped") else 2
    if args.cmd == "restart":
        out = restart_job(
            args.job_id,
            reason=args.reason,
            execute=not bool(args.dry_run),
        )
        print(json.dumps(out, indent=2))
        return 0 if out.get("ok") else 2
    if args.cmd == "heartbeat-fix":
        from .heartbeat_fix import fix_instance_if_failing, scan_and_fix

        if args.scan or not args.instance:
            out = scan_and_fix(
                instances=[args.instance] if args.instance else None,
                only_locked=bool(args.only_locked),
                force=bool(args.force),
                max_fixes=int(args.max_fixes),
            )
        else:
            out = fix_instance_if_failing(args.instance, force=bool(args.force))
        print(json.dumps(out, indent=2))
        return 0 if out.get("ok") or out.get("skipped") else 2
    if args.cmd == "emit":
        print(
            json.dumps(
                emit(args.event, detail=args.detail, job_id=args.job_id, instance_id=args.instance),
                indent=2,
            )
        )
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
