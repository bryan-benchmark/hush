"""Per-instance / per-tuner active capture locks."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, TypeVar

from .config import active_locks_path, ensure_data_layout

T = TypeVar("T")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_locks_text(raw: str) -> dict[str, Any]:
    """Parse locks JSON; tolerate a prior concurrent smash (concatenated objects)."""
    raw = (raw or "").strip()
    if not raw:
        return {"locks": {}}
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            data.setdefault("locks", {})
            return data
    except json.JSONDecodeError:
        pass
    # Take the first complete JSON value if the file was double-written.
    dec = json.JSONDecoder()
    data, _idx = dec.raw_decode(raw)
    if not isinstance(data, dict):
        return {"locks": {}}
    data.setdefault("locks", {})
    return data


def _with_file_lock(root: Path | None, fn: Callable[[], T], *, timeout_sec: float = 15.0) -> T:
    """Exclusive lock around load/modify/save so parallel session starts cannot smash JSON."""
    ensure_data_layout(root)
    lock_path = active_locks_path(root).with_name("active_locks.lock")
    deadline = time.time() + timeout_sec
    fd: int | None = None
    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_RDWR)
            break
        except FileExistsError:
            if time.time() >= deadline:
                # Stale lock leftover — steal after timeout
                try:
                    lock_path.unlink(missing_ok=True)  # type: ignore[call-arg]
                except TypeError:
                    if lock_path.is_file():
                        lock_path.unlink()
                if time.time() >= deadline + 2:
                    raise TimeoutError(f"active_locks.lock busy: {lock_path}")
            time.sleep(0.05)
    try:
        os.write(fd, str(os.getpid()).encode("ascii", errors="ignore"))
        return fn()
    finally:
        if fd is not None:
            os.close(fd)
        try:
            lock_path.unlink(missing_ok=True)  # type: ignore[call-arg]
        except TypeError:
            if lock_path.is_file():
                lock_path.unlink()
        except OSError:
            pass


def _load_unlocked(root: Path | None = None) -> dict[str, Any]:
    ensure_data_layout(root)
    path = active_locks_path(root)
    if not path.is_file():
        return {"locks": {}}
    return _parse_locks_text(path.read_text(encoding="utf-8"))


def _save_unlocked(data: dict[str, Any], root: Path | None = None) -> None:
    path = active_locks_path(root)
    tmp = path.with_suffix(".tmp")
    payload = json.dumps(data, indent=2)
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, path)


def _load(root: Path | None = None) -> dict[str, Any]:
    return _with_file_lock(root, lambda: _load_unlocked(root))


def _save(data: dict[str, Any], root: Path | None = None) -> None:
    _with_file_lock(root, lambda: _save_unlocked(data, root))


def normalize_resource_id(source_kind: str, resource_id: str, root: Path | None = None) -> str:
    """Streamers locks key on BlueStacks engine id; accept player 0 / player 1 aliases."""
    rid = str(resource_id or "")
    if str(source_kind) != "streamers":
        return rid
    try:
        from .instances import normalize_instance_id

        return normalize_instance_id(rid, root)
    except Exception:  # noqa: BLE001
        return rid


def resource_key(source_kind: str, resource_id: str, root: Path | None = None) -> str:
    return f"{source_kind}:{normalize_resource_id(source_kind, resource_id, root)}"


def _pid_alive(pid: Any) -> bool | None:
    if not pid:
        return None
    try:
        import psutil

        return bool(psutil.pid_exists(int(pid)))
    except Exception:  # noqa: BLE001
        pass
    try:
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes

            k32 = ctypes.windll.kernel32
            k32.OpenProcess.restype = wintypes.HANDLE
            k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            k32.CloseHandle.argtypes = [wintypes.HANDLE]
            k32.SetLastError(0)
            handle = k32.OpenProcess(0x1000, False, int(pid))
            if handle:
                k32.CloseHandle(handle)
                return True
            return False
        os.kill(int(pid), 0)
        return True
    except OSError:
        return False
    except Exception:  # noqa: BLE001
        return None


def _session_dir_for_lock(row: dict[str, Any], root: Path | None = None) -> Path | None:
    sid = str(row.get("session_id") or "")
    if not sid or sid.startswith("starting_"):
        return None
    base = ensure_data_layout(root) / "authorized_sources" / sid
    return base if base.is_dir() else None


def _lock_holder_dead(row: dict[str, Any] | None, root: Path | None = None) -> bool:
    """True when the capture holder is gone (PID dead, or orphaned legacy lock)."""
    if not row:
        return False
    alive = _pid_alive(row.get("holder_pid"))
    if alive is False:
        return True
    if alive is True:
        return False
    # Legacy locks with no holder_pid: use session heartbeat / age.
    sid = str(row.get("session_id") or "")
    acquired = str(row.get("acquired_utc") or "")
    age_s = None
    if acquired:
        try:
            age_s = (datetime.now(timezone.utc) - datetime.fromisoformat(acquired)).total_seconds()
        except ValueError:
            age_s = None
    if sid.startswith("starting_"):
        # Pre-guide hold with no live PID — drop after 10 minutes.
        return age_s is not None and age_s > 600
    session_dir = _session_dir_for_lock(row, root)
    if session_dir is None:
        return age_s is not None and age_s > 120
    hb = session_dir / "_audio_heartbeat.json"
    if hb.is_file():
        try:
            data = json.loads(hb.read_text(encoding="utf-8"))
            state = str(data.get("state") or "")
            if state in ("done", "stopped", "error"):
                return True
            # Mid-chunk (15m) can leave heartbeat quiet — allow 20m stale.
            if time.time() - hb.stat().st_mtime < 1200:
                return False
        except Exception:  # noqa: BLE001
            pass
        return True
    # No heartbeat yet — give start a short window, then reclaim.
    return age_s is not None and age_s > 180


def get_lock(source_kind: str, resource_id: str, root: Path | None = None) -> dict[str, Any] | None:
    data = _load(root)
    return (data.get("locks") or {}).get(resource_key(source_kind, resource_id, root))


def reclaim_dead_locks(root: Path | None = None) -> list[dict[str, Any]]:
    """Drop capture locks whose holder process died (unblocks clone scale-up)."""

    def _do() -> list[dict[str, Any]]:
        data = _load_unlocked(root)
        locks = dict(data.get("locks") or {})
        dropped: list[dict[str, Any]] = []
        for key, row in list(locks.items()):
            if not isinstance(row, dict):
                continue
            if _lock_holder_dead(row, root):
                dropped.append({"key": key, **row})
                locks.pop(key, None)
        if dropped:
            data["locks"] = locks
            _save_unlocked(data, root)
        return dropped

    return _with_file_lock(root, _do)


def acquire(
    source_kind: str,
    resource_id: str,
    *,
    session_id: str,
    job_id: str | None = None,
    holder_pid: int | None = None,
    root: Path | None = None,
    allow_upgrade_job_id: str | None = None,
) -> tuple[bool, dict[str, Any]]:
    def _do() -> tuple[bool, dict[str, Any]]:
        data = _load_unlocked(root)
        locks = dict(data.get("locks") or {})
        rid = normalize_resource_id(source_kind, resource_id, root)
        key = resource_key(source_kind, rid, root)
        existing = locks.get(key)
        if existing:
            # Dead holder → reclaim and take.
            if _lock_holder_dead(existing, root):
                existing = None
            # Same job upgrading starting_* → real session_id.
            elif (
                allow_upgrade_job_id
                and str(existing.get("job_id") or "") == str(allow_upgrade_job_id)
                and str(existing.get("session_id") or "").startswith("starting_")
            ):
                existing = None
            else:
                return False, existing
        row = {
            "source_kind": source_kind,
            "resource_id": rid,
            "session_id": session_id,
            "job_id": job_id,
            "holder_pid": int(holder_pid) if holder_pid else os.getpid(),
            "acquired_utc": _now(),
        }
        locks[key] = row
        data["locks"] = locks
        _save_unlocked(data, root)
        return True, row

    return _with_file_lock(root, _do)


def release(source_kind: str, resource_id: str, root: Path | None = None) -> None:
    def _do() -> None:
        data = _load_unlocked(root)
        locks = dict(data.get("locks") or {})
        locks.pop(resource_key(source_kind, resource_id, root), None)
        data["locks"] = locks
        _save_unlocked(data, root)

    _with_file_lock(root, _do)
