"""Shared paths, hashing, and append-only annotation resolution."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECORDINGS = ROOT / "recordings"
RUNS = ROOT / "experiments" / "runs"
ANNOTATIONS = ROOT / "experiments" / "annotations"
GOLD = ROOT / "experiments" / "gold"
TRUTH_PATH = ANNOTATIONS / "truth_events.jsonl"
REVIEWS_PATH = ANNOTATIONS / "candidate_reviews.jsonl"

LEGACY_KEYS = (
    "elapsed_seconds",
    "score",
    "rms_dbfs",
    "loudness_jump_db",
    "flux_z",
    "near_silence",
    "session",
    "file",
    "chunk_elapsed_seconds",
)


def canon(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path, buf: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(buf)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_id_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def append_jsonl(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def resolve_ledger(rows: list[dict], id_key: str) -> list[dict]:
    """Latest row wins. A later row with supersedes drops the named id."""
    superseded = {r["supersedes"] for r in rows if r.get("supersedes")}
    latest: dict[str, dict] = {}
    for row in rows:
        latest[row[id_key]] = row
    return [row for gid, row in latest.items() if gid not in superseded]


def git_state(repo: Path = ROOT) -> dict:
    def run(args: list[str]) -> str:
        return subprocess.check_output(args, cwd=repo, stderr=subprocess.DEVNULL).decode()

    try:
        sha = run(["git", "rev-parse", "HEAD"]).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return {"git_sha": None, "git_dirty": None, "git_diff_hash": None}
    porcelain = run(["git", "status", "--porcelain"])
    dirty = bool(porcelain.strip())
    diff_hash = None
    if dirty:
        diff = subprocess.check_output(["git", "diff", "HEAD"], cwd=repo)
        diff_hash = hashlib.sha256(diff).hexdigest()
    return {"git_sha": sha, "git_dirty": dirty, "git_diff_hash": diff_hash}


def detector_code_sha256() -> str:
    h = hashlib.sha256()
    for name in ("legacy_detector.py",):
        h.update((ROOT / "experiments" / name).read_bytes())
    return h.hexdigest()


def load_gold_manifest(name: str) -> dict:
    path = GOLD / f"{name}.json"
    if not path.exists():
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))
