"""Hash unlabeled outputs after each session's four runs exit.

Waits on experiments/replication/logs/queue.log. Does not open the commercial
ledger, does not read score values, and does not label.
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SPANS = REPO / "experiments" / "replication" / "spans.json"
QUEUE = REPO / "experiments" / "replication" / "logs" / "queue.log"
FREEZE = REPO / "experiments" / "replication" / "freeze"
HOLDOUTS = ("hush_20260917_205513", "hush_20260920_200635")
EXPS = ("exp002", "exp003", "exp003b", "exp005")
POLL_S = 30


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _ended(session: str) -> bool:
    if not QUEUE.is_file():
        return False
    text = QUEUE.read_text(encoding="utf-8")
    return all(f"END {session}_{exp} exit=0 " in text for exp in EXPS)


def _files(session: str) -> list[Path]:
    found = []
    for exp in EXPS:
        root = REPO / "experiments" / exp / session
        if not root.is_dir():
            raise SystemExit(f"missing {root}")
        found.extend(path for path in root.rglob("*") if path.is_file())
    return sorted(found)


def _freeze(session: str) -> None:
    if session in HOLDOUTS:
        raise SystemExit(f"refusing sealed holdout {session}")
    files = _files(session)
    rows = [
        {"path": str(path.relative_to(REPO)), "sha256": _sha256(path), "bytes": path.stat().st_size}
        for path in files
    ]
    payload = {
        "session_id": session,
        "frozen_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "truth_ledger_read": False,
        "commercial_ledger_opened": False,
        "n_files": len(rows),
        "files": rows,
    }
    FREEZE.mkdir(parents=True, exist_ok=True)
    dest = FREEZE / f"{session}.json"
    dest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"FROZE {session} files={len(rows)}", flush=True)


def main() -> None:
    sessions = [row["session_id"] for row in json.loads(SPANS.read_text(encoding="utf-8"))]
    pending = [session for session in sessions if not (FREEZE / f"{session}.json").is_file()]
    while pending:
        still = []
        for session in pending:
            if _ended(session):
                _freeze(session)
            else:
                still.append(session)
        pending = still
        if pending:
            time.sleep(POLL_S)


if __name__ == "__main__":
    main()
