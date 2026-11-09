"""Node health: disk free, backlog, last receipt."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from . import NODE_ID, __version__
from .config import ensure_data_layout


def health() -> dict:
    root = ensure_data_layout()
    usage = shutil.disk_usage(root.anchor or "C:\\")
    receipts = sorted((root / "receipts").glob("*.json"), key=lambda p: p.stat().st_mtime)
    inbox = list((root / "inbox").glob("*"))
    quarantine = list((root / "quarantine").glob("*"))
    authorized = list((root / "authorized_sources").rglob("*.wav")) + list(
        (root / "authorized_sources").rglob("*.flac")
    )

    last = None
    if receipts:
        try:
            last = json.loads(receipts[-1].read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            last = {"path": str(receipts[-1]), "error": "invalid json"}

    return {
        "node_id": NODE_ID,
        "health_version": __version__,
        "checked_utc": datetime.now(timezone.utc).isoformat(),
        "data_root": str(root),
        "disk": {
            "free_gb": round(usage.free / (1024**3), 2),
            "total_gb": round(usage.total / (1024**3), 2),
            "used_gb": round(usage.used / (1024**3), 2),
        },
        "counts": {
            "receipts": len(receipts),
            "inbox_items": len(inbox),
            "quarantine_items": len(quarantine),
            "authorized_audio_files": len(authorized),
        },
        "last_receipt": last,
        "status": "ok" if usage.free > 5 * (1024**3) else "low_disk",
    }


def main(argv: list[str] | None = None) -> int:
    print(json.dumps(health(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
