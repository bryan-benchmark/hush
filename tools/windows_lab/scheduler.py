"""Schedule capture jobs and run due ones (source-aware)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import MEDIA_MODES, SOURCE_KINDS, ensure_data_layout, schedule_path
from .locks import get_lock
from .session_capture import start_session


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


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
    root: Path | None = None,
) -> dict[str, Any]:
    if source_kind not in SOURCE_KINDS:
        raise ValueError(f"source_kind must be one of {sorted(SOURCE_KINDS)}")
    if media not in MEDIA_MODES:
        raise ValueError(f"media must be one of {sorted(MEDIA_MODES)}")
    if source_kind == "streamers" and not instance_id:
        raise ValueError("instance_id required for streamers jobs")
    start_utc = _parse_when(start_at)
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


def _resource_for(job: dict[str, Any]) -> tuple[str, str]:
    kind = str(job["source_kind"])
    if kind == "streamers":
        return kind, str(job["instance_id"])
    return kind, str(job.get("tuner_id") or "default")


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

    for job in data.get("jobs") or []:
        if job.get("status") != "scheduled":
            continue
        start = _parse_when(str(job["start_utc"]))
        if start > now:
            continue
        kind, resource_id = _resource_for(job)
        lock = get_lock(kind, resource_id, root=root)
        if lock:
            skipped.append({"job_id": job["job_id"], "reason": "resource_busy", "lock": lock})
            continue
        if not execute:
            skipped.append({"job_id": job["job_id"], "reason": "dry_preview"})
            continue

        job["status"] = "running"
        job["started_utc"] = _now_iso()
        save_jobs(data, root)
        try:
            result = start_session(
                source_kind=kind,
                channel_id=str(job["channel_id"]),
                minutes=float(job["minutes"]),
                media=str(job.get("media") or "av"),
                instance_id=job.get("instance_id"),
                tuner_id=job.get("tuner_id"),
                rights_status=str(job.get("rights_status") or "authorized"),
                apply_channel=True,
                root=root,
                job_id=str(job["job_id"]),
            )
            if result.get("ok"):
                job["status"] = "completed"
                job["session_id"] = result.get("session_id")
                job["completed_utc"] = _now_iso()
                job["last_error"] = None
                started.append({"job_id": job["job_id"], "session_id": job["session_id"]})
            else:
                job["status"] = "failed"
                job["last_error"] = result.get("error") or "session failed"
                job["failed_utc"] = _now_iso()
                failed.append({"job_id": job["job_id"], "error": job["last_error"]})
        except Exception as e:  # noqa: BLE001
            job["status"] = "failed"
            job["last_error"] = str(e)
            job["failed_utc"] = _now_iso()
            failed.append({"job_id": job["job_id"], "error": str(e)})
        save_jobs(data, root)

    return {
        "checked_utc": _now_iso(),
        "started": started,
        "skipped": skipped,
        "failed": failed,
    }


def install_task_scheduler_script(repo: Path, root: Path | None = None) -> Path:
    """Write a PowerShell helper that registers a 1-minute Task Scheduler job."""
    ensure_data_layout(root)
    out = ensure_data_layout(root) / "farm" / "register_capture_scheduler.ps1"
    py = repo / ".venv" / "Scripts" / "python.exe"
    if not py.is_file():
        py = Path("python")
    data_root = ensure_data_layout(root)
    script = f"""# Register OHush capture farm run-due (every 1 minute)
$ErrorActionPreference = "Stop"
$taskName = "OHushCaptureFarmRunDue"
$repo = {json.dumps(str(repo))}
$python = {json.dumps(str(py))}
$dataRoot = {json.dumps(str(data_root))}
$arg = "-m tools.windows_lab schedule run-due"
$action = New-ScheduledTaskAction -Execute $python -Argument $arg -WorkingDirectory $repo
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 1) -RepetitionDuration ([TimeSpan]::MaxValue)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
$envDef = [System.Collections.Generic.Dictionary[string,string]]::new()
# Task inherits user env; set OHUSH_DATA_ROOT in the action wrapper:
$wrapper = Join-Path $dataRoot "farm\\run_due_wrapper.cmd"
@"
@echo off
set OHUSH_DATA_ROOT=$dataRoot
cd /d $repo
$python -m tools.windows_lab schedule run-due >> "$dataRoot\\work\\logs\\schedule_run_due.log" 2>&1
"@ | Set-Content -Path $wrapper -Encoding ASCII
$action = New-ScheduledTaskAction -Execute $wrapper
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Write-Output "Registered $taskName"
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

    l = sub.add_parser("list")
    l.add_argument("--status")

    c = sub.add_parser("cancel")
    c.add_argument("--job-id", required=True)

    r = sub.add_parser("run-due")
    r.add_argument("--dry-run", action="store_true")

    i = sub.add_parser("install-task")
    i.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])

    args = p.parse_args(argv)
    if args.cmd == "add":
        source = {
            "ota": "ota_antenna",
            "antenna": "ota_antenna",
            "ota_antenna": "ota_antenna",
            "streamers": "streamers",
        }.get(args.source, args.source)
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
    if args.cmd == "install-task":
        path = install_task_scheduler_script(args.repo)
        print(json.dumps({"ok": True, "script": str(path)}, indent=2))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
