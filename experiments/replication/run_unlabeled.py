"""Run frozen unlabeled Exp002, Exp003, Exp003b, and Exp005 on locked spans.

Reads experiments/replication/spans.json. Does not open the commercial ledger
or the sealed holdouts. One model at a time.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SPANS = REPO / "experiments" / "replication" / "spans.json"
LOGS = REPO / "experiments" / "replication" / "logs"
HOLDOUTS = ("hush_20260917_205513", "hush_20260920_200635")
PY = {
    "exp002": REPO / "experiments" / "exp002" / ".venv" / "bin" / "python",
    "exp003": REPO / "experiments" / "exp003" / ".venv" / "bin" / "python",
    "exp003b": REPO / ".venv" / "bin" / "python",
    "exp005": REPO / "experiments" / "exp005" / ".venv" / "bin" / "python",
}


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _run(name: str, argv: list[str]) -> None:
    LOGS.mkdir(parents=True, exist_ok=True)
    log_path = LOGS / f"{name}.log"
    queue = LOGS / "queue.log"
    line = f"START {name} {_stamp()}\n"
    print(line, end="", flush=True)
    with queue.open("a", encoding="utf-8") as handle:
        handle.write(line)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO / "src")
    env["HF_HUB_OFFLINE"] = "1"
    env.setdefault("HF_HOME", str(Path.home() / ".cache" / "huggingface"))
    with log_path.open("w", encoding="utf-8") as log:
        proc = subprocess.run(argv, cwd=REPO, env=env, stdout=log, stderr=subprocess.STDOUT)
    status = f"END {name} exit={proc.returncode} {_stamp()}\n"
    print(status, end="", flush=True)
    with queue.open("a", encoding="utf-8") as handle:
        handle.write(status)
    if proc.returncode != 0:
        raise SystemExit(f"{name} failed, see {log_path}")


def main() -> None:
    rows = json.loads(SPANS.read_text(encoding="utf-8"))
    for row in rows:
        session = row["session_id"]
        if session in HOLDOUTS or any(token in row["derived_16k"] for token in HOLDOUTS):
            raise SystemExit(f"refusing sealed holdout {session}")
        t0 = float(row["t0"])
        t1 = float(row["t1"])
        wav = str(REPO / row["derived_16k"])
        tag = session
        _run(
            f"{tag}_exp002",
            [
                str(PY["exp002"]),
                "-m",
                "hush.experiment002",
                "--session",
                session,
                "--t0",
                str(t0),
                "--t1",
                str(t1),
                "--wav",
                wav,
                "--output",
                str(REPO / "experiments" / "exp002" / session),
            ],
        )
        _run(
            f"{tag}_exp003",
            [
                str(PY["exp003"]),
                "-m",
                "hush.experiment003",
                "--session",
                session,
                "--t0",
                str(t0),
                "--t1",
                str(t1),
                "--output",
                str(REPO / "experiments" / "exp003" / session),
            ],
        )
        _run(
            f"{tag}_exp003b",
            [
                str(PY["exp003b"]),
                "-m",
                "hush.experiment003b",
                "--session",
                session,
                "--scores",
                str(REPO / "experiments" / "exp003" / session / "program_cloud.parquet"),
                "--output",
                str(REPO / "experiments" / "exp003b" / session),
            ],
        )
        _run(
            f"{tag}_exp005",
            [
                str(PY["exp005"]),
                "-m",
                "hush.experiment005",
                "--session",
                session,
                "--t0",
                str(t0),
                "--t1",
                str(t1),
                "--wav",
                wav,
                "--output",
                str(REPO / "experiments" / "exp005" / session),
            ],
        )


if __name__ == "__main__":
    main()
