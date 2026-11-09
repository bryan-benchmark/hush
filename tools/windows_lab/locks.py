"""Per-instance / per-tuner active capture locks."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import active_locks_path, ensure_data_layout


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load(root: Path | None = None) -> dict[str, Any]:
    ensure_data_layout(root)
    path = active_locks_path(root)
    if not path.is_file():
        return {"locks": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def _save(data: dict[str, Any], root: Path | None = None) -> None:
    path = active_locks_path(root)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def resource_key(source_kind: str, resource_id: str) -> str:
    return f"{source_kind}:{resource_id}"


def get_lock(source_kind: str, resource_id: str, root: Path | None = None) -> dict[str, Any] | None:
    data = _load(root)
    return (data.get("locks") or {}).get(resource_key(source_kind, resource_id))


def acquire(
    source_kind: str,
    resource_id: str,
    *,
    session_id: str,
    job_id: str | None = None,
    root: Path | None = None,
) -> tuple[bool, dict[str, Any]]:
    data = _load(root)
    locks = dict(data.get("locks") or {})
    key = resource_key(source_kind, resource_id)
    existing = locks.get(key)
    if existing:
        return False, existing
    row = {
        "source_kind": source_kind,
        "resource_id": resource_id,
        "session_id": session_id,
        "job_id": job_id,
        "acquired_utc": _now(),
    }
    locks[key] = row
    data["locks"] = locks
    _save(data, root)
    return True, row


def release(source_kind: str, resource_id: str, root: Path | None = None) -> None:
    data = _load(root)
    locks = dict(data.get("locks") or {})
    locks.pop(resource_key(source_kind, resource_id), None)
    data["locks"] = locks
    _save(data, root)
