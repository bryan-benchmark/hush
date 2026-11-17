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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _paths(root: Path | None = None) -> tuple[Path, Path]:
    label = farm_label_dir(root)
    audit = label / "audit"
    audit.mkdir(parents=True, exist_ok=True)
    return audit / LOCK_NAME, audit / META_NAME


def _pid_alive(pid: int) -> bool:
    try:
        if os.name == "nt":
            import ctypes

            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)
                return True
            return False
        os.kill(int(pid), 0)
        return True
    except OSError:
        return False
    except Exception:
        return False


def status(root: Path | None = None) -> dict[str, Any]:
    lock_path, meta_path = _paths(root)
    if not lock_path.is_file():
        return {"held": False}
    meta: dict[str, Any] = {}
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            meta = {}
    pid = int(meta.get("pid") or 0)
    age = time.time() - lock_path.stat().st_mtime
    alive = _pid_alive(pid) if pid else None
    stale = age >= STALE_SEC or alive is False
    return {
        "held": True,
        "pid": pid or None,
        "alive": alive,
        "age_s": round(age, 1),
        "stale": stale,
        "meta": meta,
        "path": str(lock_path),
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
    meta = {
        "pid": os.getpid(),
        "utc": _now(),
        "reason": reason or "verdict_label",
    }
    try:
        os.write(fd, str(os.getpid()).encode("ascii"))
        meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    finally:
        os.close(fd)
    return {"ok": True, "held": True, **meta, "path": str(lock_path)}


def release(root: Path | None = None) -> dict[str, Any]:
    lock_path, meta_path = _paths(root)
    meta: dict[str, Any] = {}
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            meta = {}
    pid = int(meta.get("pid") or 0)
    if pid and pid != os.getpid() and _pid_alive(pid):
        return {"ok": False, "error": "not_holder", "pid": pid}
    try:
        lock_path.unlink(missing_ok=True)
        meta_path.unlink(missing_ok=True)
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "released_utc": _now()}
