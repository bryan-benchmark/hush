"""Pull the private audio corpus onto this machine.

Git has the code and the labels. The recordings are not in git. This copies
them from the private bucket, plus the three enrolled-show voice prototypes.
It does not delete local files, and it does not overwrite the git checkout
with the cloud copy of the code.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PROJECT = "hushdev"
BUCKET = "hushdev-748439071367-research"
ENROLL = ("enroll_snf.npy", "enroll_mnf.npy", "enroll_tnf.npy")


def _run(args: list[str]) -> None:
    print("+", " ".join(args), flush=True)
    subprocess.run(args, check=True)


def main() -> None:
    project = subprocess.run(
        ["gcloud", "config", "get-value", "project"],
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()
    if project != PROJECT:
        raise SystemExit(f"gcloud project is {project}, expected {PROJECT}")
    recordings = REPO / "recordings"
    recordings.mkdir(parents=True, exist_ok=True)
    cache = REPO / "ohush_live" / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    _run(["gcloud", "storage", "rsync", f"gs://{BUCKET}/raw", str(recordings), "--recursive"])
    for name in ENROLL:
        _run(["gcloud", "storage", "cp", f"gs://{BUCKET}/enroll/{name}", str(cache / name)])
    print(f"recordings are in {recordings}", flush=True)
    print("speaker model downloads on the first live launch", flush=True)


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        sys.exit(exc.returncode)
