"""Append-only receipts for the learning net.

A finished probe is a new directory plus one ledger line. Older directories
are not edited. The ledger line stores the hash of the result file.
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import traceback
from pathlib import Path

from experiments.ledger import sha256_file, sha256_text, utc_now

from tools.gpu_lab.prepare import DATA_ROOT

NET_ROOT = DATA_ROOT / "learning_net"
LEDGER_PATH = NET_ROOT / "LEDGER.jsonl"
PLAN_PATH = Path(__file__).resolve().parents[3] / "docs" / "ohush" / "research" / "LEARNING_NET_001" / "PLAN.md"


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def _append_line(path: Path, line: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    blob = json.dumps(line, sort_keys=True, ensure_ascii=False) + "\n"
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(blob)
        handle.flush()
        os.fsync(handle.fileno())


def _git(args: list[str]) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=Path(__file__).resolve().parents[3], text=True, stderr=subprocess.DEVNULL).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


def code_identity(module_path: Path) -> dict:
    porcelain = _git(["status", "--porcelain", "--", "tools/gpu_lab", "src/hush/audio.py", "docs/ohush/research/LEARNING_NET_001/PLAN.md"])
    return {
        "git_head": _git(["rev-parse", "HEAD"]),
        "worktree_porcelain_sha256": sha256_text(porcelain),
        "worktree_dirty": bool(porcelain),
        "module_sha256": sha256_file(module_path) if module_path.is_file() else None,
        "plan_sha256": sha256_file(PLAN_PATH) if PLAN_PATH.is_file() else None,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
    }


def open_probe(probe_id: str, question: str, parameters: dict, module_path: Path) -> Path:
    NET_ROOT.mkdir(parents=True, exist_ok=True)
    stamp = utc_now().replace("-", "").replace(":", "")
    folder = NET_ROOT / "probes" / f"{stamp}_{probe_id}"
    folder.mkdir(parents=True)
    started = {
        "probe_id": probe_id,
        "question": question,
        "status": "started",
        "started_at": utc_now(),
        "parameters": parameters,
        "code": code_identity(module_path),
    }
    _atomic_write(folder / "started.json", json.dumps(started, indent=2, sort_keys=True))
    print(f"opened {folder}", flush=True)
    return folder


def finish_probe(folder: Path, probe_id: str, question: str, parameters: dict, result: dict, module_path: Path) -> dict:
    result_text = json.dumps(result, indent=2, sort_keys=True)
    _atomic_write(folder / "result.json", result_text)
    finished_at = utc_now()
    receipt = {
        "probe_id": probe_id,
        "question": question,
        "status": "ok",
        "started_at": json.loads((folder / "started.json").read_text(encoding="utf-8"))["started_at"],
        "finished_at": finished_at,
        "parameters": parameters,
        "result_sha256": sha256_text(result_text),
        "result_path": str(folder / "result.json"),
        "code": code_identity(module_path),
    }
    _atomic_write(folder / "receipt.json", json.dumps(receipt, indent=2, sort_keys=True))
    _append_line(LEDGER_PATH, receipt)
    print(f"logged {probe_id} {receipt['result_sha256'][:12]}", flush=True)
    return receipt


def fail_probe(folder: Path, probe_id: str, question: str, parameters: dict, exc: BaseException) -> None:
    error = {"probe_id": probe_id, "status": "error", "finished_at": utc_now(), "error": f"{type(exc).__name__}: {exc}", "trace": traceback.format_exc()}
    _atomic_write(folder / "error.json", json.dumps(error, indent=2, sort_keys=True))
    _append_line(
        LEDGER_PATH,
        {
            "probe_id": probe_id,
            "question": question,
            "status": "error",
            "finished_at": error["finished_at"],
            "parameters": parameters,
            "error": error["error"],
            "result_sha256": sha256_file(folder / "error.json"),
        },
    )
