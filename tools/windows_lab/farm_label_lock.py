"""Single-flight lock for multichannel / verdict labeling.

Prevents OHushFarmLoop (15m) + backfill + overnight worker from stacking
qwen/Whisper jobs and starving each other.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import ensure_data_layout
from .coverage_farm import farm_label_dir

LOCK_NAME = "verdict_label_pass.lock"
META_NAME = "verdict_label_pass.json"
STALE_SEC = 6 * 3600  # hard reclaim — a pass should not outlive overnight
# Also reclaim when LAB_STATUS job stops advancing (worker wedged with lock held).
JOB_STALE_SEC = 20 * 60
# Labelers must heartbeat like channel audio/picture hearts.
# VL timeout is 180s; allow one slow still + margin before reclaim.
HEARTBEAT_STALE_SEC = 6 * 60


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _paths(root: Path | None = None) -> tuple[Path, Path]:
    label = farm_label_dir(root)
    audit = label / "audit"
    audit.mkdir(parents=True, exist_ok=True)
    return audit / LOCK_NAME, audit / META_NAME


def _read_meta(meta_path: Path) -> dict[str, Any]:
    if not meta_path.is_file():
        return {}
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _pid_alive(pid: int) -> bool:
    """True only if the process still exists.

    Prefer psutil — raw OpenProcess via ctypes is easy to mis-type on Windows
    and previously returned false positives that wedged the label lock for hours.
    """
    try:
        import psutil

        return bool(psutil.pid_exists(int(pid)))
    except Exception:
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
    except Exception:
        return False


def _beat_age_s(meta: dict[str, Any], *, lock_mtime: float) -> float | None:
    """Seconds since last labeler heartbeat (falls back to lock file mtime)."""
    beat = str(meta.get("beat_utc") or meta.get("utc") or "")
    if beat:
        try:
            # accept both ...Z and iso with offset
            raw = beat.replace("Z", "+00:00") if beat.endswith("Z") and "+" not in beat else beat
            dt = datetime.fromisoformat(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds())
        except ValueError:
            pass
    return max(0.0, time.time() - float(lock_mtime))


def heartbeat(root: Path | None = None, **fields: Any) -> dict[str, Any]:
    """Touch the label-pass heart (same idea as channel _audio_heartbeat.json).

    Call at least once per still / phase step so a wedged worker is reclaimable
    and the desk can show live progress.
    """
    lock_path, meta_path = _paths(root)
    if not lock_path.is_file():
        return {"ok": False, "error": "no_lock"}
    meta = _read_meta(meta_path)
    pid = int(meta.get("pid") or 0)
    if pid and pid != os.getpid() and _pid_alive(pid):
        return {"ok": False, "error": "not_holder", "pid": pid}
    now = _now()
    meta.update({k: v for k, v in fields.items() if v is not None})
    meta["pid"] = os.getpid()
    meta["beat_utc"] = now
    meta["beat_mono"] = round(time.monotonic(), 3)
    try:
        meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
        # Refresh lock mtime so age_s tracks the heart too.
        now_ts = time.time()
        os.utime(lock_path, (now_ts, now_ts))
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "beat_utc": now, "meta": meta}


def status(root: Path | None = None) -> dict[str, Any]:
    lock_path, meta_path = _paths(root)
    if not lock_path.is_file():
        return {"held": False}
    meta = _read_meta(meta_path)
    pid = int(meta.get("pid") or 0)
    mtime = lock_path.stat().st_mtime
    age = time.time() - mtime
    alive = _pid_alive(pid) if pid else None
    beat_age = _beat_age_s(meta, lock_mtime=mtime)
    job_age_s = None
    job_stale = False
    try:
        job_path = farm_label_dir(root) / "audit" / "LAB_STATUS.json"
        if job_path.is_file():
            job = (json.loads(job_path.read_text(encoding="utf-8")).get("job") or {})
            upd = str(job.get("updated_utc") or "")
            if upd:
                job_age_s = round(
                    (
                        datetime.now(timezone.utc)
                        - datetime.strptime(upd, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                    ).total_seconds(),
                    1,
                )
                # Held lock + frozen job blob: only if the lock itself is old too
                # (a fresh reclaim leaves the previous job stamp until the first hop).
                job_stale = (
                    bool(job.get("phase"))
                    and job_age_s is not None
                    and job_age_s >= JOB_STALE_SEC
                    and age >= JOB_STALE_SEC
                )
    except Exception:
        job_age_s = None
    # Heartbeat stale: explicit beat went quiet, OR no beat ever and job is also quiet.
    # Legacy workers (pre-heartbeat) that still write LAB_STATUS stay non-stale.
    heartbeat_stale = False
    if beat_age is not None and beat_age >= HEARTBEAT_STALE_SEC:
        if meta.get("beat_utc"):
            heartbeat_stale = True
        elif job_age_s is None or job_age_s >= HEARTBEAT_STALE_SEC:
            heartbeat_stale = True
    stale = age >= STALE_SEC or alive is False or heartbeat_stale or job_stale
    return {
        "held": True,
        "pid": pid or None,
        "alive": alive,
        "age_s": round(age, 1),
        "beat_age_s": round(beat_age, 1) if beat_age is not None else None,
        "heartbeat_stale": heartbeat_stale,
        "job_age_s": job_age_s,
        "stale": stale,
        "meta": meta,
        "path": str(lock_path),
        "phase": meta.get("phase"),
        "session": meta.get("session"),
        "hop_i": meta.get("hop_i"),
        "hop_of": meta.get("hop_of"),
        "note": meta.get("note"),
    }


def acquire(root: Path | None = None, *, reason: str = "") -> dict[str, Any]:
    """Try to take the label pass lock. Reclaims dead/stale holders."""
    ensure_data_layout(root)
    lock_path, meta_path = _paths(root)
    cur = status(root)
    if cur.get("held") and cur.get("stale"):
        try:
            lock_path.unlink(missing_ok=True)
            meta_path.unlink(missing_ok=True)
        except OSError:
            pass
        cur = status(root)
    if cur.get("held"):
        return {"ok": False, "held": True, **cur}
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_RDWR)
    except FileExistsError:
        return {"ok": False, **status(root)}
    now = _now()
    meta = {
        "pid": os.getpid(),
        "utc": now,
        "beat_utc": now,
        "beat_mono": round(time.monotonic(), 3),
        "reason": reason or "verdict_label",
        "note": "acquired",
    }
    try:
        os.write(fd, str(os.getpid()).encode("ascii"))
        meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    finally:
        os.close(fd)
    return {"ok": True, "held": True, **meta, "path": str(lock_path)}


def release(root: Path | None = None, *, force: bool = False) -> dict[str, Any]:
    lock_path, meta_path = _paths(root)
    meta: dict[str, Any] = {}
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            meta = {}
    pid = int(meta.get("pid") or 0)
    cur = status(root)
    if (not force) and pid and pid != os.getpid() and _pid_alive(pid) and not cur.get("stale"):
        return {"ok": False, "error": "not_holder", "pid": pid}
    try:
        lock_path.unlink(missing_ok=True)
        meta_path.unlink(missing_ok=True)
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "released_utc": _now(), "forced": bool(force or cur.get("stale")), "was": cur}
