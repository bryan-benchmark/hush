"""Upload closed WAV chunks. This process is not allowed to stop the recorder.

It never uploads a path it was not given, and it never deletes cloud objects.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

BUCKET = "hushdev-748439071367-research"
PROJECT = "hushdev"


def cp_command(path: Path, dest: str, digest: str) -> list[str]:
    return [
        "gcloud",
        "storage",
        "cp",
        str(path),
        dest,
        f"--custom-metadata=sha256={digest}",
        f"--project={PROJECT}",
    ]


def object_name(session_name: str, filename: str) -> str:
    return f"gs://{BUCKET}/live/{session_name}/{filename}"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verified(described: dict, digest: str, size: int) -> bool:
    meta = described.get("metadata") or {}
    remote = str(meta.get("sha256") or "")
    remote_size = int(described.get("size") or 0)
    return remote == digest and remote_size == size


def upload_one(path: Path, session_dir: Path) -> dict:
    digest = sha256(path)
    size = path.stat().st_size
    dest = object_name(session_dir.name, path.name)
    subprocess.run(cp_command(path, dest, digest), check=True)
    described = subprocess.run(
        ["gcloud", "storage", "objects", "describe", dest, "--format=json"],
        check=True,
        capture_output=True,
        text=True,
    )
    body = json.loads(described.stdout)
    ok = verified(body, digest, size)
    row = {
        "path": path.name,
        "sha256": digest,
        "bytes": size,
        "object": dest,
        "cloud_verified": ok,
    }
    with (session_dir / "upload_manifest.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row) + "\n")
    print(f"cloud {path.name} verified={ok}", flush=True)
    return row


def main() -> None:
    session_dir = Path(sys.argv[1])
    session_dir.mkdir(parents=True, exist_ok=True)
    for line in sys.stdin:
        name = line.strip()
        if not name:
            continue
        path = Path(name)
        if not path.is_file():
            print(f"skip missing {path}", flush=True)
            continue
        try:
            upload_one(path, session_dir)
        except Exception as exc:
            print(f"upload failed {path.name}: {exc}", flush=True)


if __name__ == "__main__":
    main()
