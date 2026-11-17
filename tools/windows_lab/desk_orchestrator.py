"""Desk cron — open-model + subroutines orchestrate the Streamers farm.

Runs on Task Scheduler (no Cursor). Each tick:

1. Acquire **single-flight desk lock** (never stack ticks / crash the box)
2. Preflight resource gates (RAM / disk / HD-Player count / CPU)
3. ``windows layout --mode auto`` — tile HD-Players so they never overlap
4. ``schedule run-due`` / light guide-refresh cadence
5. ``enforce_unique_programs`` — retune any stream sharing a game (any affiliate)
6. ``heartbeat-fix scan`` — identity / lag / picture truth + receipts
7. HUSH/policy todos → open-model ``attempt_fix`` (wired scripts only)
8. Per enabled instance: identity-on-air health → ``ON_AIR_CONTINUE`` if unique+healthy
9. Write ``DESK.md`` board + ``desk_orchestrator.jsonl``

Safety rails (checks & balances):
- One desk tick at a time (PID lock + heartbeat; stale lock reclaim)
- Task Scheduler ``MultipleInstances IgnoreNew``
- Cap streams / recoveries / vision calls per tick
- Skip record/recover under RAM or disk pressure
- Never start a new take while instance capture lock held
- Refuse start if another desk python is already running (lock holder: warn only)

Env:
  OHUSH_VISION=1 — moondream when frames uncertain
  OHUSH_DESK_MAX_STREAMS — fallback only if farm/desk_limits.json missing (capacity probe writes JSON)
  OHUSH_DESK_LOCK_STALE_SEC=900 — reclaim lock if prior tick died
  OHUSH_DESK_MIN_RAM_GB=6 — skip heavy work below this free RAM
  OHUSH_DESK_MIN_DISK_GB=20 — skip new records below this free disk
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import ensure_data_layout, farm_dir
from .farm_loop import (
    DEFAULT_MINUTES,
    identity_on_air_health,
    schedule_window,
    start_on_air_record,
)
from .farm_resources import memory_snapshot
from .instances import list_instances
from .locks import get_lock
from .streamers_lag import CLEAN_CONCURRENT


def _desk_max_streams() -> int:
    """``farm/desk_limits.json`` (progressive capacity) is authoritative.

    Env ``OHUSH_DESK_MAX_STREAMS`` is only a fallback when the JSON file is
    missing — a stale setx must not block raising the desk after a clean probe.
    """
    try:
        path = farm_dir() / "desk_limits.json"
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            return int(data.get("OHUSH_DESK_MAX_STREAMS") or CLEAN_CONCURRENT)
    except Exception:  # noqa: BLE001
        pass
    env = os.environ.get("OHUSH_DESK_MAX_STREAMS")
    if env:
        try:
            return int(env)
        except ValueError:
            pass
    return int(CLEAN_CONCURRENT)


# Do not freeze DESK_MAX at import — re-read farm/desk_limits.json every tick.
LOCK_STALE_SEC = float(os.environ.get("OHUSH_DESK_LOCK_STALE_SEC") or 900)
# Hung ticks often keep the PID alive while heartbeat freezes mid-fix.
# Reclaim much sooner on stale heartbeat so the farm is not locked for 15m.
HB_STALE_SEC = float(os.environ.get("OHUSH_DESK_HB_STALE_SEC") or 180)
MIN_RAM_GB = float(os.environ.get("OHUSH_DESK_MIN_RAM_GB") or 6.0)
MIN_DISK_GB = float(os.environ.get("OHUSH_DESK_MIN_DISK_GB") or 20.0)
MAX_RECOVERIES_PER_TICK = int(os.environ.get("OHUSH_DESK_MAX_RECOVERIES") or 2)
MAX_VISION_PER_TICK = int(os.environ.get("OHUSH_DESK_MAX_VISION") or 2)
MAX_HD_PLAYERS = int(os.environ.get("OHUSH_DESK_MAX_HD_PLAYERS") or 8)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _python() -> Path:
    venv = _repo_root() / ".venv" / "Scripts" / "python.exe"
    return venv if venv.is_file() else Path(sys.executable)


def log_path(root: Path | None = None) -> Path:
    return ensure_data_layout(root) / "indexes" / "desk_orchestrator.jsonl"


def board_path(root: Path | None = None) -> Path:
    return ensure_data_layout(root) / "indexes" / "DESK.md"


def _append(row: dict[str, Any], root: Path | None = None) -> None:
    path = log_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, default=str) + "\n")


def desk_lock_path(root: Path | None = None) -> Path:
    return ensure_data_layout(root) / "farm" / "desk_tick.lock"


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        import ctypes

        SYNCHRONIZE = 0x00100000
        handle = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, 0, int(pid))
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        # OpenProcess failed — could be access denied (still alive) or gone.
        err = ctypes.windll.kernel32.GetLastError()
        return err == 5  # ACCESS_DENIED ⇒ process exists
    except Exception:
        return False


def _cmdline_is_desk_tick(cmdline: list[str] | str | None) -> bool:
    """True for a heavy desk tick only (``desk tick`` / orchestrator main).

    Light commands (``desk preflight`` / ``board`` / ``install-task``) do not count —
    shell double-spawns must not block each other on diagnostics.
    """
    if not cmdline:
        return False
    parts = [str(x) for x in cmdline] if isinstance(cmdline, (list, tuple)) else str(cmdline).split()
    low_parts = [p.lower() for p in parts]
    if "-c" in low_parts:
        return False
    for i, p in enumerate(low_parts):
        if p in {"tools.windows_lab.desk_orchestrator", "desk_orchestrator"} or p.endswith(
            "desk_orchestrator.py"
        ):
            # Module entry defaults to argparse; treat as tick unless a light subcommand
            light = {"preflight", "board", "install-task"}
            return not any(x in light for x in low_parts[i + 1 :])
        if p == "tools.windows_lab" and i + 1 < len(low_parts) and low_parts[i + 1] == "desk":
            sub = low_parts[i + 2] if i + 2 < len(low_parts) else "tick"
            return sub == "tick"
    return False


def _other_desk_pythons() -> tuple[int, list[int]]:
    """Other python PIDs that look like a desk tick (excludes this process)."""
    me = os.getpid()
    pids: list[int] = []
    try:
        import psutil

        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                info = proc.info
                pid = int(info.get("pid") or 0)
                if pid in {0, me}:
                    continue
                name = (info.get("name") or "").lower()
                if name not in {"python.exe", "pythonw.exe", "python", "pythonw"}:
                    continue
                if _cmdline_is_desk_tick(info.get("cmdline")):
                    pids.append(pid)
            except (psutil.Error, TypeError, ValueError):
                continue
    except Exception:
        return 0, []
    return len(pids), pids


def _hd_player_count() -> int:
    try:
        raw = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "(Get-Process HD-Player -ErrorAction SilentlyContinue | Measure-Object).Count",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return int((raw.stdout or "0").strip() or 0)
    except Exception:
        return 0


def acquire_desk_lock(root: Path | None = None) -> tuple[bool, dict[str, Any]]:
    """Single-flight: only one desk tick may run. Reclaim stale/dead locks.

    Uses O_CREAT|O_EXCL so two ticks cannot both invent a lock file.
    """
    path = desk_lock_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    now = time.time()
    row = {
        "pid": os.getpid(),
        "started_unix": now,
        "started_utc": _now(),
        "heartbeat_unix": now,
        "hostname": os.environ.get("COMPUTERNAME"),
    }

    def _try_create() -> bool:
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            try:
                os.write(fd, json.dumps(row, indent=2).encode("utf-8"))
            finally:
                os.close(fd)
            return True
        except FileExistsError:
            return False

    if _try_create():
        return True, row

    try:
        cur = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        cur = {}
    pid = int(cur.get("pid") or 0)
    started = float(cur.get("started_unix") or 0)
    hb = float(cur.get("heartbeat_unix") or started or 0)
    age = now - started if started else 99999
    hb_age = now - hb if hb else 99999
    if pid == os.getpid():
        return True, cur
    # Alive holder with fresh heartbeat → yield. Frozen heartbeat → reclaim
    # (stuck adb/fix was blocking all open-model work for the full LOCK_STALE).
    if _pid_alive(pid) and age < LOCK_STALE_SEC and hb_age < HB_STALE_SEC:
        return False, {
            "error": "desk_tick_already_running",
            "holder": cur,
            "age_sec": round(age, 1),
            "heartbeat_age_sec": round(hb_age, 1),
        }
    # Stale or dead — reclaim once
    try:
        path.unlink(missing_ok=True)
    except Exception:
        return False, {"error": "desk_lock_reclaim_failed", "holder": cur}
    row["reclaimed_utc"] = _now()
    row["reclaimed_from_pid"] = pid
    if _try_create():
        return True, row
    return False, {
        "error": "desk_tick_race_lost",
        "holder_hint": cur,
    }


def heartbeat_desk_lock(root: Path | None = None) -> None:
    path = desk_lock_path(root)
    if not path.is_file():
        return
    try:
        cur = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return
    if int(cur.get("pid") or 0) != os.getpid():
        return
    cur["heartbeat_unix"] = time.time()
    cur["heartbeat_utc"] = _now()
    path.write_text(json.dumps(cur, indent=2), encoding="utf-8")


def release_desk_lock(root: Path | None = None) -> None:
    path = desk_lock_path(root)
    if not path.is_file():
        return
    try:
        cur = json.loads(path.read_text(encoding="utf-8"))
        if int(cur.get("pid") or 0) not in {0, os.getpid()}:
            return  # someone else owns it
    except Exception:
        pass
    path.unlink(missing_ok=True)


def preflight(
    root: Path | None = None,
    *,
    hold_lock: bool = False,
) -> dict[str, Any]:
    """Resource + overlap gates before any heavy subroutine.

    When ``hold_lock`` is True we already won single-flight; other desk PIDs are
    a warning (racer exiting), not a hard block — the lock file is authoritative.
    """
    mem = memory_snapshot()
    hd = _hd_player_count()
    other_n, other_pids = _other_desk_pythons()
    blockers: list[str] = []
    warnings: list[str] = []

    avail = float(mem.get("avail_gb") or 0)
    disk = float(mem.get("disk_free_gb") or 0)
    if avail and avail < MIN_RAM_GB:
        blockers.append(f"ram_free_gb={avail}<{MIN_RAM_GB}")
    if disk and disk < MIN_DISK_GB:
        blockers.append(f"disk_free_gb={disk}<{MIN_DISK_GB}")
    if hd > MAX_HD_PLAYERS:
        blockers.append(f"hd_players={hd}>{MAX_HD_PLAYERS}")
    if other_n > 0:
        msg = f"other_desk_pythons={other_n}:{other_pids}"
        if hold_lock:
            warnings.append(msg)
        else:
            blockers.append(msg)
    if mem.get("load_pct") is not None and int(mem["load_pct"]) >= 92:
        warnings.append(f"memory_load_pct={mem['load_pct']}")
    if avail and avail < MIN_RAM_GB + 2:
        warnings.append("ram_near_floor")

    allow_record = not blockers and bool(mem.get("allow_record", True))
    # Stuck menus must still be fixed under RAM pressure — parking a clone and
    # BACK-out recover free memory; skipping them leaves search_ui forever.
    ram_only = bool(blockers) and all(str(b).startswith("ram_free_gb=") for b in blockers)
    allow_recover = (not blockers) or ram_only
    # Full-fleet vision when healthy; named locks always get moondream even under
    # dual-capture RAM pressure — otherwise desk flies blind on MNF/ESPN nights.
    # Floor default 0: a locked take must not go heuristic-only because free RAM
    # dipped under an arbitrary GB gate (0.24 free used to keep vision off).
    min_vision_gb = float(os.environ.get("OHUSH_DESK_MIN_RAM_VISION_GB") or 0.0)
    allow_vision = (not blockers) and avail >= MIN_RAM_GB
    named_lock = False
    try:
        from .locks import get_lock
        from .instances import list_instances

        for row in list_instances(root) or []:
            iid = str((row or {}).get("id") or "")
            if not iid:
                continue
            lk = get_lock("streamers", iid, root=root)
            if not lk:
                continue
            sid = str(lk.get("session_id") or "")
            if lk.get("job_id") and "ON_AIR" not in sid.upper():
                named_lock = True
                break
    except Exception:
        named_lock = False
    if not allow_vision and named_lock and avail >= min_vision_gb:
        allow_vision = True
        warnings.append(
            f"vision_for_named_lock_ram={avail:.2f}>={min_vision_gb}"
        )
    # Survival: heartbeat / park excess even when record is blocked by RAM.
    allow_survival = allow_recover

    return {
        "ok": not blockers,
        "blockers": blockers,
        "warnings": warnings,
        "memory": mem,
        "hd_players": hd,
        "other_desk_pythons": other_n,
        "other_desk_pids": other_pids,
        "allow_record": allow_record,
        "allow_recover": allow_recover,
        "allow_vision": allow_vision,
        "named_capture_lock": named_lock,
        "allow_survival": allow_survival,
        "limits": {
            "max_streams": _desk_max_streams(),
            # Display floor; tick() raises recover_budget above this for fleet size.
            "max_recoveries": MAX_RECOVERIES_PER_TICK,
            "max_vision": MAX_VISION_PER_TICK,
            "max_hd_players": MAX_HD_PLAYERS,
            "min_ram_gb": MIN_RAM_GB,
            "min_disk_gb": MIN_DISK_GB,
            "lock_stale_sec": LOCK_STALE_SEC,
        },
    }


def _run_module(args: list[str], *, timeout: float = 600.0) -> dict[str, Any]:
    py = str(_python())
    repo = str(_repo_root())
    try:
        proc = subprocess.run(
            [py, "-m", "tools.windows_lab", *args],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "OHUSH_DATA_ROOT": str(ensure_data_layout())},
        )
        out = (proc.stdout or "").strip()
        err = (proc.stderr or "").strip()
        parsed = None
        if out.startswith("{") or out.startswith("["):
            try:
                parsed = json.loads(out)
            except json.JSONDecodeError:
                # last JSON object in output
                idx = out.rfind("\n{")
                if idx >= 0:
                    try:
                        parsed = json.loads(out[idx + 1 :])
                    except json.JSONDecodeError:
                        parsed = None
        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "parsed": parsed,
            "stdout_tail": out[-1500:],
            "stderr_tail": err[-800:],
        }
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


def enabled_streamers(root: Path | None = None) -> list[dict[str, Any]]:
    rows = []
    for r in list_instances(root):
        if not r.get("enabled", True):
            continue
        if str(r.get("source_kind") or "streamers") != "streamers":
            continue
        rows.append(r)
    # Prefer player fleet (BlueStacks Nougat engines). Tiramisu last — login/ADB flaky.
    def _rank(row: dict[str, Any]) -> tuple[int, int, str]:
        iid = str(row.get("id") or "")
        if row.get("player") is not None:
            return (0, int(row["player"]), iid)
        if iid == "Tiramisu64":
            return (90, 0, iid)
        return (50, 0, iid)

    rows.sort(key=_rank)
    return rows


def decisions_path(root: Path | None = None) -> Path:
    return ensure_data_layout(root) / "indexes" / "desk_decisions.jsonl"


def log_decision(
    decision: str,
    *,
    instance_id: str | None = None,
    ok: bool | None = None,
    detail: str = "",
    extra: dict[str, Any] | None = None,
    root: Path | None = None,
) -> None:
    """Append a human-grepable desk decision (why ESPN stayed / why FOX opened)."""
    root = ensure_data_layout(root)
    row = {
        "utc": datetime.now(timezone.utc).isoformat(),
        "decision": decision,
        "instance_id": instance_id,
        "ok": ok,
        "detail": detail,
        **(extra or {}),
    }
    # Stamp lock/job intent so postmortems show "had MNF_ESPN but opened WAGA".
    if instance_id and "lock" not in row:
        try:
            from .locks import get_lock
            from .recovery_target import resolve_recovery_target

            lock = get_lock("streamers", instance_id, root=root)
            tgt = resolve_recovery_target(instance_id, root=root)
            row["lock_session"] = (lock or {}).get("session_id")
            row["lock_job_id"] = (lock or {}).get("job_id")
            row["intended"] = {
                k: tgt.get(k)
                for k in ("kind", "channel_id", "shortcut_id", "nav_route", "label", "why")
            }
        except Exception as exc:  # noqa: BLE001
            row["intent_error"] = str(exc)
    path = decisions_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, default=str) + "\n")
    _emit_desk_receipt(
        decision,
        instance_id=instance_id,
        ok=ok,
        detail=detail,
        extra=extra,
        root=root,
    )


def _emit_desk_receipt(
    step: str,
    *,
    instance_id: str | None = None,
    ok: bool | None = None,
    detail: str = "",
    extra: dict[str, Any] | None = None,
    root: Path | None = None,
) -> None:
    """Atomic farm_run receipt for every desk control decision."""
    try:
        from .farm_ops import emit

        emit(
            f"desk_{step}",
            detail=detail or step,
            instance_id=instance_id,
            ok=ok,
            extra={"desk_step": step, **(extra or {})},
            root=root,
        )
    except Exception:
        pass


def instance_tick(
    instance_id: str,
    *,
    root: Path | None = None,
    minutes: float = DEFAULT_MINUTES,
    want_record: bool = True,
    allow_recover: bool = True,
    allow_vision: bool = True,
    recover_budget: list[int] | None = None,
) -> dict[str, Any]:
    """One instance: identity health → fix → record only if unique+healthy."""
    root = ensure_data_layout(root)
    steps: list[dict[str, Any]] = []
    recover_budget = recover_budget if recover_budget is not None else [MAX_RECOVERIES_PER_TICK]

    def _can_recover() -> bool:
        return bool(allow_recover and recover_budget[0] > 0)

    def _spend_recover() -> None:
        recover_budget[0] = max(0, recover_budget[0] - 1)

    lock = get_lock("streamers", instance_id, root)
    if lock:
        # Locked streams must NOT fly blind — watch (vision when allowed) then identity.
        sid = str(lock.get("session_id") or "")
        named_job = bool(lock.get("job_id")) and "ON_AIR" not in sid.upper()
        if allow_vision:
            watch = _run_module(
                ["frame-watch", "watch", "--instance", instance_id],
                timeout=180.0,
            )
        else:
            watch = _run_module(["open", "snap", "--instance", instance_id], timeout=90.0)
        steps.append(
            {
                "step": "busy_frame_watch",
                "ok": watch.get("ok"),
                "vision": allow_vision,
                "parsed_verdict": ((watch.get("parsed") or {}).get("watch") or {}).get(
                    "verdict"
                )
                or (watch.get("parsed") or {}).get("kind"),
            }
        )
        log_decision(
            "busy_frame_watch",
            instance_id=instance_id,
            ok=bool(watch.get("ok")),
            detail="vision" if allow_vision else "heuristic_snap",
            extra={"named_job": named_job, "session_id": sid},
            root=root,
        )
        health = identity_on_air_health(
            instance_id, root=root, session_id=sid or None, save_shot=False
        )
        steps.append(
            {
                "step": "busy_identity_probe",
                "ok": health.get("ok"),
                "reason": health.get("reason"),
                "identity": health.get("identity"),
            }
        )
        _emit_desk_receipt(
            "busy_identity",
            instance_id=instance_id,
            ok=bool(health.get("ok")),
            detail=str(health.get("reason") or ""),
            extra={"session_id": sid, "identity": health.get("identity")},
            root=root,
        )
        # Fix unhealthy locked takes too (jiggle / reopen intended) — not only ON_AIR.
        if not health.get("ok") and _can_recover():
            _spend_recover()
            try:
                from .heartbeat_fix import fix_instance_if_failing

                fixed = fix_instance_if_failing(instance_id, root=root, force=True)
                steps.append(
                    {
                        "step": "busy_heartbeat_fix",
                        "ok": bool(fixed.get("ok")),
                        "reason": fixed.get("reason"),
                        "named_job": named_job,
                    }
                )
                log_decision(
                    "busy_heartbeat_fix",
                    instance_id=instance_id,
                    ok=bool(fixed.get("ok")),
                    detail=str(fixed.get("reason") or ""),
                    extra={"named_job": named_job, "steps": [s.get("step") for s in (fixed.get("steps") or []) if isinstance(s, dict)][:10]},
                    root=root,
                )
                _emit_desk_receipt(
                    "busy_heartbeat_fix",
                    instance_id=instance_id,
                    ok=bool(fixed.get("ok")),
                    detail=str(fixed.get("reason") or ""),
                    root=root,
                )
            except Exception as exc:  # noqa: BLE001
                steps.append({"step": "busy_heartbeat_fix", "ok": False, "error": str(exc)})
        return {
            "instance_id": instance_id,
            "ok": True,
            "busy": True,
            "lock": lock,
            "health": health,
            "steps": steps,
            "action": "skip_busy",
            "recover_budget_left": recover_budget[0],
        }

    # 1) Frame watch — vision gated; may recover only if budget remains
    if allow_vision:
        watch = _run_module(
            ["frame-watch", "watch", "--instance", instance_id],
            timeout=180.0,
        )
    else:
        watch = _run_module(["open", "snap", "--instance", instance_id], timeout=90.0)
    steps.append({"step": "frame_watch", **{k: watch.get(k) for k in ("ok", "returncode")}})
    watch_parsed = watch.get("parsed") or {}
    heartbeat_desk_lock(root)

    # 2) Snapshot / classify
    snap = _run_module(["open", "snap", "--instance", instance_id], timeout=90.0)
    snap_p = snap.get("parsed") or {}
    kind = snap_p.get("kind") or "unknown"
    steps.append({"step": "snap", "kind": kind, "ok": snap.get("ok")})

    # 3) Login / recover as needed (budgeted)
    if kind.endswith("_login") or kind in {"welcome_login", "credentials_login", "service_list_login"}:
        if _can_recover():
            _spend_recover()
            login = _run_module(
                ["salvation", "login", "--instance", instance_id],
                timeout=180.0,
            )
            steps.append({"step": "salvation_login", "ok": login.get("ok")})
            snap = _run_module(["open", "snap", "--instance", instance_id], timeout=90.0)
            snap_p = snap.get("parsed") or {}
            kind = snap_p.get("kind") or kind
        else:
            steps.append({"step": "salvation_login_skipped", "reason": "recover_budget_exhausted"})

    needs_recover = kind in {
        "empty_event_guide",
        "player_decode_error",
        "player_hard_error",
        "bluestacks_home",
        "overlay_permission",
        "search_hub",
    } or (watch_parsed.get("watch") or {}).get("needs_recover")

    if needs_recover:
        if _can_recover():
            _spend_recover()
            # Prefer full heartbeat fix (picture + home local) over picture-only.
            try:
                from .heartbeat_fix import fix_instance_if_failing

                rec = fix_instance_if_failing(instance_id, root=root, force=True)
                steps.append(
                    {
                        "step": "heartbeat_fix",
                        "ok": bool(rec.get("ok")),
                        "reason": rec.get("reason"),
                    }
                )
                _emit_desk_receipt(
                    "heartbeat_fix",
                    instance_id=instance_id,
                    ok=bool(rec.get("ok")),
                    detail=str(rec.get("reason") or ""),
                    root=root,
                )
            except Exception as exc:  # noqa: BLE001
                steps.append({"step": "heartbeat_fix", "ok": False, "error": str(exc)})
            snap = _run_module(["open", "snap", "--instance", instance_id], timeout=90.0)
            snap_p = snap.get("parsed") or {}
            kind = snap_p.get("kind") or kind
        else:
            steps.append({"step": "recover_skipped", "reason": "recover_budget_or_gate"})

    if kind in {"guide", "guide_like", "empty_event_guide"} and _can_recover():
        _spend_recover()
        try:
            from .heartbeat_fix import fix_instance_if_failing

            pic = fix_instance_if_failing(instance_id, root=root, force=True)
            steps.append({"step": "ensure_picture_via_heartbeat", "ok": bool(pic.get("ok"))})
        except Exception as exc:  # noqa: BLE001
            steps.append({"step": "ensure_picture_via_heartbeat", "ok": False, "error": str(exc)})

    heartbeat_desk_lock(root)
    # Identity gate — picture alone is not enough to start a take.
    health = identity_on_air_health(instance_id, root=root, save_shot=False)
    steps.append(
        {
            "step": "identity_on_air_health",
            "ok": health.get("ok"),
            "reason": health.get("reason"),
            "identity": health.get("identity"),
            "receipt": health.get("receipt"),
        }
    )
    _emit_desk_receipt(
        "identity_health",
        instance_id=instance_id,
        ok=bool(health.get("ok")),
        detail=str(health.get("reason") or ""),
        extra={"identity": health.get("identity"), "receipt": health.get("receipt")},
        root=root,
    )

    if want_record and not health.get("ok") and _can_recover():
        _spend_recover()
        try:
            from .heartbeat_fix import fix_instance_if_failing

            fixed = fix_instance_if_failing(instance_id, root=root, force=True)
            steps.append(
                {
                    "step": "identity_heartbeat_fix",
                    "ok": bool(fixed.get("ok")),
                    "reason": fixed.get("reason"),
                }
            )
            health = identity_on_air_health(instance_id, root=root, save_shot=False)
            steps.append(
                {
                    "step": "identity_on_air_health_after_fix",
                    "ok": health.get("ok"),
                    "reason": health.get("reason"),
                    "identity": health.get("identity"),
                }
            )
            _emit_desk_receipt(
                "identity_health_after_fix",
                instance_id=instance_id,
                ok=bool(health.get("ok")),
                detail=str(health.get("reason") or ""),
                extra={"identity": health.get("identity")},
                root=root,
            )
        except Exception as exc:  # noqa: BLE001
            steps.append({"step": "identity_heartbeat_fix", "ok": False, "error": str(exc)})

    started = None
    if want_record and health.get("ok"):
        started = start_on_air_record(
            instance_id=instance_id,
            minutes=minutes,
            channel_id="ON_AIR_CONTINUE",
            detach=True,
            root=root,
        )
        steps.append(
            {
                "step": "start_record",
                "ok": bool(started.get("ok")),
                "detached": started.get("detached"),
                "pid": started.get("pid"),
            }
        )
        _emit_desk_receipt(
            "start_record",
            instance_id=instance_id,
            ok=bool(started.get("ok")),
            detail=str((started or {}).get("session_id") or ""),
            extra={"identity": health.get("identity")},
            root=root,
        )
        action = "recording_started" if started.get("ok") else "record_failed"
    elif want_record and not health.get("ok"):
        action = "not_healthy"
        _emit_desk_receipt(
            "not_healthy",
            instance_id=instance_id,
            ok=False,
            detail=str(health.get("reason") or ""),
            extra={"identity": health.get("identity")},
            root=root,
        )
    else:
        action = "watch_only"

    return {
        "instance_id": instance_id,
        "ok": True,
        "busy": False,
        "kind": kind,
        "health": health,
        "watch": watch_parsed,
        "started": started,
        "action": action,
        "steps": steps,
        "recover_budget_left": recover_budget[0],
    }


def tick(
    *,
    root: Path | None = None,
    max_streams: int | None = None,
    minutes: float = DEFAULT_MINUTES,
    run_schedule: bool = True,
) -> dict[str, Any]:
    """Full desk cron pass — single-flight + preflight gates."""
    root = ensure_data_layout(root)
    max_streams = int(max_streams if max_streams is not None else _desk_max_streams())
    # Scale recover/vision with enabled fleet — not just DESK_MAX.
    # heartbeat_scan + hush_todo_work each burn a slot; instance_tick needs its own
    # or _1/_3 sit broken while the board only "bumps" the same todo forever.
    enabled_n = len(enabled_streamers(root))
    recover_budget_n = max(
        MAX_RECOVERIES_PER_TICK,
        max_streams,
        enabled_n + 2,  # +2 for scan + todo without starving per-instance fixes
    )
    vision_budget_n = max(MAX_VISION_PER_TICK, max_streams, enabled_n)
    sched = schedule_window()
    want_record = bool(sched.get("do_record"))
    try:
        from .capture_pause import is_paused

        pause = is_paused(root)
        if pause.get("active"):
            want_record = False
    except Exception:
        pause = {"active": False}

    out: dict[str, Any] = {
        "ok": True,
        "checked_utc": _now(),
        "schedule": sched,
        "max_streams": max_streams,
        "want_record": want_record,
        "capture_pause": pause,
        "steps": [],
        "instances": [],
        "guard": {},
    }

    # Free clones stuck behind dead capture PIDs before scheduling / recording.
    try:
        from .locks import reclaim_dead_locks

        dropped = reclaim_dead_locks(root)
        if dropped:
            out["steps"].append({"step": "reclaim_dead_locks", "dropped": len(dropped)})
    except Exception as exc:  # noqa: BLE001
        out["steps"].append({"step": "reclaim_dead_locks", "ok": False, "error": str(exc)})

    got, lock_info = acquire_desk_lock(root)
    out["guard"]["lock"] = lock_info
    if not got:
        out["ok"] = True  # not a crash — intentional skip
        out["skipped"] = True
        out["reason"] = "single_flight_busy"
        out["steps"].append({"step": "skip_overlap", "holder": lock_info})
        _append(out, root)
        # Refresh board lightly
        board_path(root).write_text(
            "\n".join(
                [
                    "# Desk orchestrator",
                    "",
                    f"Skipped `{_now()}` — another tick holds the lock.",
                    "",
                    f"```json\n{json.dumps(lock_info, indent=2)}\n```",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        return out

    try:
        gates = preflight(root, hold_lock=True)
        out["guard"]["preflight"] = gates
        out["steps"].append(
            {
                "step": "preflight",
                "ok": gates.get("ok"),
                "blockers": gates.get("blockers"),
                "warnings": gates.get("warnings"),
            }
        )
        survival_only = False
        if not gates.get("ok"):
            # RAM floor used to abort the whole tick — then search menus sat for
            # hours with nobody calling heartbeat_fix. Survival still runs.
            if gates.get("allow_survival"):
                survival_only = True
                out["steps"].append(
                    {
                        "step": "preflight_survival",
                        "ok": True,
                        "blockers": gates.get("blockers"),
                        "note": "record blocked; vision kept for named locks; heartbeat + park still run",
                    }
                )
            else:
                out["ok"] = True
                out["skipped"] = True
                out["reason"] = "preflight_blocked"
                out["board"] = str(
                    _write_board(out, sched, max_streams, want_record, note="PREFLIGHT BLOCKED")
                )
                _append(out, root)
                return out

        # Parked clones BlueStacks relaunches must not sit black outside heartbeat.
        try:
            from .instances import stop_disabled_instances

            stopped = stop_disabled_instances(root, hard=True)
            if stopped.get("stopped"):
                out["steps"].append(
                    {
                        "step": "stop_disabled",
                        "ok": bool(stopped.get("ok")),
                        "stopped": [
                            s.get("instance_id") or s.get("engine")
                            for s in (stopped.get("stopped") or [])
                        ],
                    }
                )
        except Exception as exc:  # noqa: BLE001
            out["steps"].append({"step": "stop_disabled", "ok": False, "error": str(exc)})

        # Always tile HD-Players so windows never stack / steal clicks from each other.
        # Qt sometimes ignores live MoveWindow — conf is patched every tick; relaunch
        # stuck/overlapping windows at most once per 30 minutes.
        try:
            from .window_layout import layout_windows

            lay = layout_windows(mode="auto", relaunch_stuck=False)
            need_relaunch = bool(lay.get("overlapping") or lay.get("stuck"))
            relaunched_now = False
            if need_relaunch:
                marker = root / "indexes" / "windows_layout_relaunch.json"
                last_u = 0.0
                try:
                    last_u = float(
                        json.loads(marker.read_text(encoding="utf-8")).get("unix") or 0
                    )
                except Exception:
                    last_u = 0.0
                if time.time() - last_u >= 1800:
                    lay = layout_windows(mode="auto", relaunch_stuck=True)
                    relaunched_now = True
                    marker.write_text(
                        json.dumps({"unix": time.time(), "utc": _now()}, indent=2),
                        encoding="utf-8",
                    )
            out["steps"].append(
                {
                    "step": "windows_layout",
                    "ok": bool(lay.get("ok")),
                    "effective_mode": lay.get("effective_mode"),
                    "overlapping": lay.get("overlapping"),
                    "relaunched": relaunched_now,
                    "placed": [
                        {
                            "instance_id": p.get("instance_id"),
                            "moved": p.get("moved"),
                            "w": p.get("w"),
                            "h": p.get("h"),
                        }
                        for p in (lay.get("placed") or [])
                    ],
                }
            )
            _emit_desk_receipt(
                "windows_layout",
                ok=bool(lay.get("ok")),
                detail=str(lay.get("effective_mode") or "auto"),
                extra={
                    "placed": out["steps"][-1].get("placed"),
                    "overlapping": lay.get("overlapping"),
                    "relaunched": [
                        r.get("instance_id") for r in (lay.get("relaunched") or [])
                    ],
                },
                root=root,
            )
        except Exception as exc:  # noqa: BLE001
            out["steps"].append({"step": "windows_layout", "ok": False, "error": str(exc)})

        want_record = want_record and bool(gates.get("allow_record")) and not survival_only
        allow_recover = bool(gates.get("allow_recover"))
        # Keep vision in survival mode when a named capture is locked — that is
        # when flying blind hurts most (MNF on FOX because desk never looked).
        allow_vision_gate = bool(gates.get("allow_vision"))
        recover_budget = [recover_budget_n]
        vision_budget = [vision_budget_n if allow_vision_gate else 0]
        if survival_only:
            out["survival_only"] = True
            out["steps"].append(
                {
                    "step": "survival_vision_policy",
                    "allow_vision": allow_vision_gate,
                    "named_capture_lock": gates.get("named_capture_lock"),
                    "note": "record blocked; vision still on for locked named jobs",
                }
            )

        if run_schedule:
            due = _run_module(["schedule", "run-due"], timeout=120.0)
            out["steps"].append({"step": "schedule_run_due", "ok": due.get("ok")})
            minute = datetime.now().minute
            # Guide refresh is heavy (UI); only on :00/:30 and when recover budget left
            if minute in {0, 30} and allow_recover and recover_budget[0] > 0:
                recover_budget[0] -= 1
                gr = _run_module(
                    ["schedule", "guide-refresh", "--horizon-hours", "96"],
                    timeout=480.0,
                )
                out["steps"].append({"step": "guide_refresh", "ok": gr.get("ok")})
            # Once a day off-peak: deep guide catalog (channel numbers for schedule).
            hour = datetime.now().hour
            if (
                hour in {5, 6}
                and minute == 5
                and allow_recover
                and recover_budget[0] > 0
            ):
                try:
                    from .guide_catalog import needs_daily_scan

                    if needs_daily_scan(root):
                        recover_budget[0] -= 1
                        gc = _run_module(
                            [
                                "guide-catalog",
                                "daily",
                                "--instance",
                                "Nougat32_1",
                            ],
                            timeout=3600.0,
                        )
                        out["steps"].append(
                            {"step": "guide_catalog_daily", "ok": gc.get("ok"), "detail": gc}
                        )
                except Exception as exc:  # noqa: BLE001
                    out["steps"].append(
                        {"step": "guide_catalog_daily", "ok": False, "error": str(exc)}
                    )

        # Next highest after schedule: never two streams on the same game
        # (different affiliates still waste a player — retune secondary to next net).
        if allow_recover and recover_budget[0] > 0:
            try:
                from .stream_status import enforce_unique_programs

                uniq = enforce_unique_programs(root=root, execute=True)
                retunes = [
                    a
                    for a in (uniq.get("actions") or [])
                    if a.get("action") == "retune"
                ]
                if retunes:
                    recover_budget[0] = max(0, recover_budget[0] - 1)
                out["steps"].append(
                    {
                        "step": "enforce_unique_programs",
                        "ok": bool(uniq.get("ok")),
                        "duplicates_found": uniq.get("duplicates_found"),
                        "actions": uniq.get("actions"),
                    }
                )
                _emit_desk_receipt(
                    "enforce_unique",
                    ok=bool(uniq.get("ok")),
                    detail=f"dups={uniq.get('duplicates_found')}",
                    extra={"actions": uniq.get("actions")},
                    root=root,
                )
            except Exception as exc:  # noqa: BLE001
                out["steps"].append(
                    {"step": "enforce_unique_programs", "ok": False, "error": str(exc)}
                )

        # Channel truth: heartbeat scan first (fleet-wide). Cap by enabled count,
        # not DESK_MAX — otherwise a dual cap starves the third clone forever.
        if allow_recover and recover_budget[0] > 1:
            try:
                from .heartbeat_fix import scan_and_fix

                reserve = max(1, enabled_n)  # keep slots for per-instance ticks
                max_fixes = max(1, min(recover_budget[0] - reserve, enabled_n))
                hb = scan_and_fix(root=root, max_fixes=max_fixes)
                fixed_n = int(hb.get("fixed") or 0)
                if fixed_n:
                    recover_budget[0] = max(reserve, recover_budget[0] - fixed_n)
                hb_results = [
                    {
                        "instance_id": r.get("instance_id"),
                        "ok": r.get("ok"),
                        "skipped": r.get("skipped"),
                        "reason": r.get("reason")
                        or (r.get("probe") or {}).get("reason"),
                        "steps": [
                            s.get("step")
                            for s in (r.get("steps") or [])
                            if isinstance(s, dict)
                        ][:12],
                    }
                    for r in (hb.get("results") or [])
                ]
                out["steps"].append(
                    {
                        "step": "heartbeat_scan",
                        "ok": bool(hb.get("ok")),
                        "fixed": fixed_n,
                        "results": hb_results,
                    }
                )
                for r in hb_results:
                    log_decision(
                        "heartbeat_scan_result",
                        instance_id=str(r.get("instance_id") or "") or None,
                        ok=bool(r.get("ok")),
                        detail=str(r.get("reason") or ""),
                        extra={"skipped": r.get("skipped"), "fix_steps": r.get("steps")},
                        root=root,
                    )
                _emit_desk_receipt(
                    "heartbeat_scan",
                    ok=bool(hb.get("ok")),
                    detail=f"fixed={fixed_n}",
                    extra={"results": hb_results},
                    root=root,
                )
            except Exception as exc:  # noqa: BLE001
                out["steps"].append(
                    {"step": "heartbeat_scan", "ok": False, "error": str(exc)}
                )

        # Per-instance fix/record BEFORE open-model todo work so a stuck todo
        # cannot burn the last recover slot while _1/_3 sit on error screens.
        recording = 0
        for row in enabled_streamers(root):
            heartbeat_desk_lock(root)
            # Re-check RAM mid-tick — soft abort, keep what we started
            mid = memory_snapshot()
            if float(mid.get("avail_gb") or 0) < MIN_RAM_GB:
                out["steps"].append({"step": "abort_ram_pressure", "memory": mid})
                break
            if _hd_player_count() > MAX_HD_PLAYERS:
                out["steps"].append({"step": "abort_hd_player_cap"})
                break
            iid = str(row["id"])
            do_rec = want_record and recording < max_streams
            use_vision = allow_vision_gate and vision_budget[0] > 0
            inst_out = instance_tick(
                iid,
                root=root,
                minutes=minutes,
                want_record=do_rec,
                allow_recover=allow_recover,
                allow_vision=use_vision,
                recover_budget=recover_budget,
            )
            if use_vision:
                vision_budget[0] = max(0, vision_budget[0] - 1)
            out["instances"].append(inst_out)
            # Only healthy recordings fill capacity — busy+unhealthy must not
            # block restarting the free clone (that was the lost-stream bug).
            health_ok = bool((inst_out.get("health") or {}).get("ok"))
            if inst_out.get("action") == "recording_started":
                recording += 1
            elif inst_out.get("busy") and health_ok:
                recording += 1
            # Hard cap: never open more stream slots than max_streams
            if recording >= max_streams and not want_record:
                break
            time.sleep(1.0)

        # Open-model todo AFTER per-instance fixes (same recover pool; don't starve clones).
        try:
            from .open_model_todos import desk_work_once, next_open, reprioritize

            repo = reprioritize(root)
            out["steps"].append(
                {
                    "step": "hush_todos_reprioritize",
                    "ok": repo.get("ok"),
                    "open": repo.get("open"),
                    "fleet_ingested": repo.get("fleet_ingested"),
                    "top": (repo.get("top") or {}).get("todo_key")
                    if isinstance(repo.get("top"), dict)
                    else None,
                }
            )
            if allow_recover and recover_budget[0] > 0 and repo.get("open"):
                worked = desk_work_once(root, owner="desk")
                todo_key = str((worked.get("todo") or {}).get("todo_key") or "")
                todo_iid = None
                try:
                    from .open_model_todos import _todo_instance_id

                    todo_iid = _todo_instance_id(worked.get("todo") or {})
                except Exception:
                    todo_iid = None
                out["steps"].append(
                    {
                        "step": "hush_todo_work",
                        "ok": worked.get("ok"),
                        "todo_key": todo_key,
                        "fix": {
                            k: (worked.get("fix") or {}).get(k)
                            for k in ("resolved", "blocked", "lesson", "ok")
                        },
                    }
                )
                log_decision(
                    "hush_todo_work",
                    instance_id=todo_iid,
                    ok=bool(worked.get("ok")),
                    detail=todo_key,
                    extra={
                        "fix": out["steps"][-1].get("fix"),
                        "fix_steps": [
                            s.get("step")
                            for s in ((worked.get("fix") or {}).get("steps") or [])
                            if isinstance(s, dict)
                        ][:12],
                    },
                    root=root,
                )
                _emit_desk_receipt(
                    "todo_work",
                    ok=bool(worked.get("ok")),
                    detail=todo_key,
                    extra={"fix": out["steps"][-1].get("fix")},
                    root=root,
                )
                if not worked.get("skipped"):
                    recover_budget[0] = max(0, recover_budget[0] - 1)
            out["hush_todo_top"] = next_open(root)
        except Exception as exc:  # noqa: BLE001
            out["steps"].append({"step": "hush_todos", "ok": False, "error": str(exc)})

        out["guard"]["budgets_left"] = {
            "recover": recover_budget[0],
            "vision": vision_budget[0],
            "recording_slots_used": recording,
        }

        out["board"] = str(_write_board(out, sched, max_streams, want_record))
        _append(out, root)
        return out
    finally:
        release_desk_lock(root)


def _write_board(
    out: dict[str, Any],
    sched: dict[str, Any],
    max_streams: int,
    want_record: bool,
    *,
    note: str = "",
) -> Path:
    root = ensure_data_layout()
    gates = (out.get("guard") or {}).get("preflight") or {}
    lines = [
        "# Desk orchestrator",
        "",
        f"Checked `{out.get('checked_utc')}` · mode **{sched.get('mode')}** · "
        f"max_streams **{max_streams}** · want_record **{want_record}**",
        "",
    ]
    if note:
        lines.append(f"**{note}**")
        lines.append("")
    if out.get("skipped"):
        lines.append(f"Skipped: `{out.get('reason')}`")
        lines.append("")
    lines.extend(
        [
            "## Guards",
            f"- Preflight ok: **{gates.get('ok')}** blockers={gates.get('blockers') or []}",
            f"- HD-Players: {gates.get('hd_players')} · other desk pythons: "
            f"{gates.get('other_desk_pythons')} {gates.get('other_desk_pids') or []}",
            f"- Limits: `{json.dumps(gates.get('limits') or {})}`",
            "",
            "| Instance | Action | Kind | Identity health | Reason | Busy |",
            "|---|---|---|---|---|---|",
        ]
    )
    for inst in out.get("instances") or []:
        h = inst.get("health") or {}
        reason = str(h.get("reason") or "—").replace("|", "/")[:48]
        lines.append(
            f"| {inst.get('instance_id')} | {inst.get('action')} | {inst.get('kind')} | "
            f"{h.get('ok')} | {reason} | {inst.get('busy')} |"
        )
    # Show tick control steps (unique / heartbeat / todos) for receipts.
    control = [
        s
        for s in (out.get("steps") or [])
        if s.get("step")
        in {
            "enforce_unique_programs",
            "heartbeat_scan",
            "hush_todos_reprioritize",
            "hush_todo_work",
        }
    ]
    if control:
        lines.extend(["", "## Control steps", ""])
        for s in control:
            lines.append(f"- `{s.get('step')}` ok={s.get('ok')} {json.dumps({k: v for k, v in s.items() if k not in {'step', 'ok', 'actions', 'results', 'fix'} or k == 'fixed'}, default=str)[:180]}")
    lines.extend(
        [
            "",
            "Safety: single-flight lock · Task Scheduler IgnoreNew · RAM/disk/HD caps · "
            "recover/vision budgets · identity gate before ON_AIR · no new take while named lock held.",
            "",
            "Policy todos: `C:\\OHushData\\indexes\\OPEN_MODEL_TODO.md` "
            "(duplicate/wrong/lag + HUSH; desk works wired fixes).",
            "",
            "Receipts: `farm_run` events `desk_*` + `STREAM_STATUS.md` root_cause.",
            "Decisions: `indexes/desk_decisions.jsonl` (intended channel vs what recover opened).",
            "",
            "Cron: `python -m tools.windows_lab desk install-task --register --minutes 10`",
            "",
        ]
    )
    top = out.get("hush_todo_top")
    if top:
        lines.insert(
            3,
            f"HUSH top todo: `{top.get('todo_key')}` p={top.get('priority')} — "
            f"{(top.get('detail') or '')[:100]}",
        )
        lines.insert(4, "")
    path = board_path(root)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def install_task(
    *,
    minutes: int = 10,
    register: bool = False,
    repo: Path | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    repo = repo or _repo_root()
    root = ensure_data_layout(root)
    farm = root / "farm"
    farm.mkdir(parents=True, exist_ok=True)
    (root / "work" / "logs").mkdir(parents=True, exist_ok=True)
    py = _python()
    wrapper = farm / "run_desk_orchestrator.cmd"
    wrapper.write_text(
        "\r\n".join(
            [
                "@echo off",
                f"set OHUSH_DATA_ROOT={root}",
                f"set OHUSH_VISION=1",
                f"cd /d {repo}",
                f'"{py}" -m tools.windows_lab desk tick >> "{root}\\work\\logs\\desk_orchestrator.log" 2>&1',
                "",
            ]
        ),
        encoding="ascii",
        newline="\r\n",
    )
    hidden = farm / "run_desk_hidden.vbs"
    hidden.write_text(
        "\r\n".join(
            [
                "' Hidden launcher — no console flash",
                'Set sh = CreateObject("WScript.Shell")',
                f'sh.Run "cmd /c ""{wrapper}""", 0, True',
                "",
            ]
        ),
        encoding="ascii",
        newline="\r\n",
    )
    ps1 = farm / "register_desk_orchestrator.ps1"
    ps1.write_text(
        f"""# OHush desk orchestrator (frame-watch + recover + record)
$ErrorActionPreference = "Stop"
$taskName = "OHushDeskOrchestrator"
$hidden = {json.dumps(str(hidden))}
$action = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "//B //Nologo `"$hidden`""
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes {int(minutes)}) -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 2) -MultipleInstances IgnoreNew -Hidden
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Write-Output "Registered $taskName every {int(minutes)} min (hidden via $hidden)"
""",
        encoding="utf-8",
    )
    registered = None
    if register:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps1)],
            capture_output=True,
            text=True,
            timeout=60,
        )
        registered = {
            "returncode": completed.returncode,
            "stdout": (completed.stdout or "").strip(),
            "stderr": (completed.stderr or "").strip(),
        }
    return {
        "ok": True,
        "wrapper": str(wrapper),
        "script": str(ps1),
        "minutes": minutes,
        "registered": registered,
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="Desk orchestrator cron")
    sub = p.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("tick", help="One full desk pass (single-flight)")
    t.add_argument("--max-streams", type=int, default=None)
    t.add_argument("--minutes", type=float, default=DEFAULT_MINUTES)
    t.add_argument("--no-schedule", action="store_true")
    i = sub.add_parser("install-task", help="Register Task Scheduler job")
    i.add_argument("--minutes", type=int, default=10)
    i.add_argument("--register", action="store_true")
    sub.add_parser("board", help="Print DESK.md path / last state hint")
    sub.add_parser("preflight", help="Show resource/overlap gates only")

    args = p.parse_args(argv)
    if args.cmd == "tick":
        report = tick(
            max_streams=args.max_streams,
            minutes=args.minutes,
            run_schedule=not args.no_schedule,
        )
        print(json.dumps(report, indent=2, default=str))
        return 0 if report.get("ok") else 2
    if args.cmd == "install-task":
        report = install_task(minutes=args.minutes, register=args.register)
        print(json.dumps(report, indent=2))
        return 0 if report.get("ok") and (
            not report.get("registered") or report["registered"].get("returncode", 0) == 0
        ) else 2
    if args.cmd == "board":
        path = board_path()
        print(json.dumps({"board": str(path), "exists": path.is_file()}, indent=2))
        return 0
    if args.cmd == "preflight":
        gates = preflight()
        print(json.dumps(gates, indent=2))
        return 0 if gates.get("ok") else 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
