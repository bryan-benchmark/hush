"""Copy the research corpus to a private Cloud Storage bucket.

Does not delete cloud objects. Does not enable Firestore.
Skips virtualenvs, model downloads, and resampled wavs that can be rebuilt.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PROJECT = "hushdev"
BUCKET = "hushdev-748439071367-research"
SKIP_DIR_NAMES = {
    ".venv",
    "node_modules",
    ".next",
    "__pycache__",
    ".cache",
    "models",
    "derived",
    ".mplconfig",
    "cache",
    "sessions",
}
SKIP_SUFFIXES = {".pyc", ".wav"}
KEEP_WAV_ROOTS = {"recordings"}


def _run(args: list[str], check: bool = True) -> subprocess.CompletedProcess:
    print("+", " ".join(args), flush=True)
    return subprocess.run(args, check=check, text=True, capture_output=True)


def _project() -> str:
    result = _run(["gcloud", "config", "get-value", "project"])
    return result.stdout.strip()


def _ensure_bucket() -> None:
    listed = _run(["gcloud", "storage", "buckets", "list", "--project", PROJECT, "--format=value(name)"])
    names = {line.strip() for line in listed.stdout.splitlines() if line.strip()}
    uri = f"gs://{BUCKET}"
    if BUCKET not in names:
        _run(
            [
                "gcloud",
                "storage",
                "buckets",
                "create",
                uri,
                "--project", PROJECT,
                "--location=us-east1",
                "--default-storage-class=STANDARD",
                "--uniform-bucket-level-access",
                "--soft-delete-duration=30d",
            ]
        )
    _run(["gcloud", "storage", "buckets", "update", uri, "--public-access-prevention"])


def _keep(path: Path, root_name: str) -> bool:
    if any(part in SKIP_DIR_NAMES for part in path.parts):
        return False
    if path.suffix in SKIP_SUFFIXES and not (path.suffix == ".wav" and root_name in KEEP_WAV_ROOTS):
        return False
    if path.suffix == ".wav" and root_name not in KEEP_WAV_ROOTS:
        return False
    return path.is_file()


def _files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(path for path in root.rglob("*") if _keep(path, root.name))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _upload(local: Path, remote: str) -> None:
    _run(["gcloud", "storage", "cp", str(local), remote])


def _hash_tree(root: Path, dest: Path) -> int:
    count = 0
    total = 0
    with dest.open("w", encoding="utf-8") as handle:
        for path in _files(root):
            digest = _sha256(path)
            handle.write(f"{digest}  {path.relative_to(REPO).as_posix()}\n")
            count += 1
            total += path.stat().st_size
            if count % 25 == 0:
                print(f"hashed {count} files under {root.name}", flush=True)
    print(f"hashed {count} files, {total} bytes, {dest}", flush=True)
    return count


def _rsync(local: Path, remote: str, excludes: list[str]) -> None:
    command = ["gcloud", "storage", "rsync", str(local), remote, "--recursive"]
    for pattern in excludes:
        command.extend(["--exclude", pattern])
    print("+", " ".join(command), flush=True)
    subprocess.run(command, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Back up OHush research to Cloud Storage")
    parser.add_argument("--gold-only", action="store_true")
    args = parser.parse_args()
    project = _project()
    if project != PROJECT:
        raise SystemExit(f"gcloud project is {project}, expected {PROJECT}")
    _ensure_bucket()
    gold_files = [
        REPO / "experiments/annotations/truth_events.jsonl",
        REPO / "experiments/gold/GOLD_REPLICATION_V1.json",
        REPO / "experiments/replication/freeze/gold_ledgers.json",
        REPO / "experiments/replication/PRIMARY_OVERLAY_COMPARISON.md",
    ]
    manifest = {
        "project": PROJECT,
        "bucket": BUCKET,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "deletes_cloud_files": False,
        "files": [],
    }
    backup_dir = REPO / "experiments" / "backup"
    backup_dir.mkdir(parents=True, exist_ok=True)
    for path in gold_files:
        digest = _sha256(path)
        manifest["files"].append({"path": str(path.relative_to(REPO)), "sha256": digest, "bytes": path.stat().st_size})
        _upload(path, f"gs://{BUCKET}/gold/{path.name}")
    (backup_dir / "GOLD_REPLICATION_V1.sha256").write_text(
        "".join(f"{item['sha256']}  {item['path']}\n" for item in manifest["files"]),
        encoding="utf-8",
    )
    _upload(backup_dir / "GOLD_REPLICATION_V1.sha256", f"gs://{BUCKET}/gold/GOLD_REPLICATION_V1.sha256")
    enroll_cache = REPO / "ohush_live" / "cache"
    for name in ("enroll_snf.npy", "enroll_mnf.npy", "enroll_tnf.npy"):
        path = enroll_cache / name
        if path.is_file():
            _upload(path, f"gs://{BUCKET}/enroll/{name}")
    if args.gold_only:
        (backup_dir / "backup_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        print("gold uploaded", flush=True)
        return

    recordings_hash = backup_dir / "recordings.sha256"
    experiments_hash = backup_dir / "experiments.sha256"
    _hash_tree(REPO / "recordings", recordings_hash)
    _hash_tree(REPO / "experiments", experiments_hash)
    _upload(recordings_hash, f"gs://{BUCKET}/manifests/sha256/recordings.sha256")
    _upload(experiments_hash, f"gs://{BUCKET}/manifests/sha256/experiments.sha256")
    experiment_excludes = [
        r".*(\.venv/|__pycache__/|/models/|/derived/|node_modules/|\.next/|\.cache/|\.pyc$|\.wav$)",
    ]
    _rsync(REPO / "experiments", f"gs://{BUCKET}/experiments", experiment_excludes)
    _rsync(REPO / "recordings", f"gs://{BUCKET}/raw", [])
    _rsync(REPO / "src", f"gs://{BUCKET}/code/src", [r".*/__pycache__/.*", r".*\.pyc$"])
    for name in (
        "truth_events.jsonl",
        "GOLD_REPLICATION_V1.json",
        "gold_ledgers.json",
        "PRIMARY_OVERLAY_COMPARISON.md",
        "GOLD_REPLICATION_V1.sha256",
    ):
        described = _run(["gcloud", "storage", "objects", "describe", f"gs://{BUCKET}/gold/{name}", "--format=value(name)"])
        if not described.stdout.strip():
            raise SystemExit(f"missing after upload: gs://{BUCKET}/gold/{name}")
    manifest["recordings_sha256"] = str(recordings_hash.relative_to(REPO))
    manifest["experiments_sha256"] = str(experiments_hash.relative_to(REPO))
    manifest["rsync_deletes_unmatched"] = False
    out = backup_dir / "backup_manifest.json"
    out.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    _upload(out, f"gs://{BUCKET}/manifests/backup_manifest.json")
    print(f"manifest {out}", flush=True)


if __name__ == "__main__":
    main()
