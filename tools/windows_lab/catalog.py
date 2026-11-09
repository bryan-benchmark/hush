"""Capture session index (unlabeled queue) under OHUSH_DATA_ROOT/indexes."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import capture_sessions_index_path, ensure_data_layout


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_session(row: dict[str, Any], root: Path | None = None) -> dict[str, Any]:
    ensure_data_layout(root)
    path = capture_sessions_index_path(root)
    body = dict(row)
    body.setdefault("label_status", "unlabeled")
    body.setdefault("indexed_utc", _now())
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(body, ensure_ascii=False) + "\n")
    return body


def list_sessions(
    root: Path | None = None,
    *,
    label_status: str | None = "unlabeled",
    source_kind: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    path = capture_sessions_index_path(root)
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if label_status and row.get("label_status") != label_status:
            continue
        if source_kind and row.get("source_kind") != source_kind:
            continue
        rows.append(row)
    return rows[-limit:]


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="Capture session catalog")
    sub = p.add_subparsers(dest="cmd", required=True)
    l = sub.add_parser("list")
    l.add_argument("--label-status", default="unlabeled")
    l.add_argument("--source-kind")
    l.add_argument("--limit", type=int, default=200)
    l.add_argument("--all", action="store_true")

    args = p.parse_args(argv)
    if args.cmd == "list":
        status = None if args.all else args.label_status
        rows = list_sessions(label_status=status, source_kind=args.source_kind, limit=args.limit)
        print(json.dumps({"count": len(rows), "sessions": rows}, indent=2))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
