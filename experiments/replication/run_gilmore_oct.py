#!/usr/bin/env python3
"""Wait for the current unlabeled queue to finish, then run one new session.

Does not reopen the commercial ledger. Same four frozen experiments as
run_unlabeled.py.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SPANS = REPO / "experiments" / "replication" / "spans.json"
QUEUE = REPO / "experiments" / "replication" / "logs" / "queue.log"
LOGS = REPO / "experiments" / "replication" / "logs"
HOLDOUTS = ("hush_20260917_205513", "hush_20260920_200635")
SESSION = "hush_20261007_220650"
WAIT_FOR = "END hush_20260913_210542_exp005 exit=0 "
PY = {
    "exp002": REPO / "experiments" / "exp002" / ".venv" / "bin" / "python",
    "exp003": REPO / "experiments" / "exp003" / ".venv" / "bin" / "python",
    "exp003b": REPO / ".venv" / "bin" / "python",
    "exp005": REPO / "experiments" / "exp005" / ".venv" / "bin" / "python",
}


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _wait() -> None:
    print(f"waiting for {WAIT_FOR!r}", flush=True)
    while True:
        text = QUEUE.read_text(encoding="utf-8") if QUEUE.is_file() else ""
        if WAIT_FOR in text:
            print(f"seen at {_stamp()}", flush=True)
            return
        # if the runner already exited without writing END, stop waiting forever
        time.sleep(30)


def _run(name: str, argv: list[str]) -> None:
    LOGS.mkdir(parents=True, exist_ok=True)
    log_path = LOGS / f"{name}.log"
    line = f"START {name} {_stamp()}\n"
    print(line, end="", flush=True)
    with QUEUE.open("a", encoding="utf-8") as handle:
        handle.write(line)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO / "src")
    env["HF_HUB_OFFLINE"] = "1"
    env.setdefault("HF_HOME", str(Path.home() / ".cache" / "huggingface"))
    with log_path.open("w", encoding="utf-8") as log:
        proc = subprocess.run(argv, cwd=REPO, env=env, stdout=log, stderr=subprocess.STDOUT)
    status = f"END {name} exit={proc.returncode} {_stamp()}\n"
    print(status, end="", flush=True)
    with QUEUE.open("a", encoding="utf-8") as handle:
        handle.write(status)
    if proc.returncode != 0:
        raise SystemExit(f"{name} failed, see {log_path}")


def main() -> None:
    rows = {row["session_id"]: row for row in json.loads(SPANS.read_text(encoding="utf-8"))}
    if SESSION not in rows:
        raise SystemExit(f"{SESSION} missing from spans.json")
    row = rows[SESSION]
    if SESSION in HOLDOUTS:
        raise SystemExit(f"refusing sealed holdout {SESSION}")
    _wait()
    # skip if already fully done
    text = QUEUE.read_text(encoding="utf-8") if QUEUE.is_file() else ""
    if all(f"END {SESSION}_{exp} exit=0 " in text for exp in ("exp002", "exp003", "exp003b", "exp005")):
        print(f"{SESSION} already complete", flush=True)
        return
    t0 = float(row["t0"])
    t1 = float(row["t1"])
    wav = str(REPO / row["derived_16k"])
    if not Path(wav).is_file():
        raise SystemExit(f"missing derived wav {wav}")
    _run(
        f"{SESSION}_exp002",
        [
            str(PY["exp002"]),
            "-m",
            "hush.experiment002",
            "--session",
            SESSION,
            "--t0",
            str(t0),
            "--t1",
            str(t1),
            "--wav",
            wav,
            "--output",
            str(REPO / "experiments" / "exp002" / SESSION),
        ],
    )
    _run(
        f"{SESSION}_exp003",
        [
            str(PY["exp003"]),
            "-m",
            "hush.experiment003",
            "--session",
            SESSION,
            "--t0",
            str(t0),
            "--t1",
            str(t1),
            "--output",
            str(REPO / "experiments" / "exp003" / SESSION),
        ],
    )
    _run(
        f"{SESSION}_exp003b",
        [
            str(PY["exp003b"]),
            "-m",
            "hush.experiment003b",
            "--session",
            SESSION,
            "--scores",
            str(REPO / "experiments" / "exp003" / SESSION / "program_cloud.parquet"),
            "--output",
            str(REPO / "experiments" / "exp003b" / SESSION),
        ],
    )
    _run(
        f"{SESSION}_exp005",
        [
            str(PY["exp005"]),
            "-m",
            "hush.experiment005",
            "--session",
            SESSION,
            "--t0",
            str(t0),
            "--t1",
            str(t1),
            "--wav",
            wav,
            "--output",
            str(REPO / "experiments" / "exp005" / SESSION),
        ],
    )


if __name__ == "__main__":
    main()
