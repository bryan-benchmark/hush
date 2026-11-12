"""Copy the current lab muter weights into ohush_live paths for Mac realtime.

Windows lab trains/scores under C:\\OHushData\\gpu_lab\\audio_learn.
This script stages the files the live desk reads, refreshes MODEL_MANIFEST
hashes, and prints the Mac pull steps. It does not commit or push.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LAB = Path(r"C:\OHushData\gpu_lab\audio_learn")
CACHE = REPO / "ohush_live" / "cache" / "research_muter"
MODELS = REPO / "ohush_live" / "models"
MANIFEST = REPO / "ohush_live" / "MODEL_MANIFEST.json"

COPIES = (
    (LAB / "weights" / "frame_mn10_strong_1.pt", CACHE / "frame_mn10_strong_1.pt", "frame_mn10"),
    (LAB / "checkpoints" / "frozen_head.pt", MODELS / "frozen_head.pt", "frozen_head"),
)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--head",
        type=Path,
        default=None,
        help="Optional alternate frozen_head.pt (default: lab checkpoints/frozen_head.pt)",
    )
    parser.add_argument(
        "--encoder",
        type=Path,
        default=None,
        help="Optional alternate frame_mn10_strong_1.pt",
    )
    args = parser.parse_args()

    planned = list(COPIES)
    if args.encoder is not None:
        planned[0] = (args.encoder, CACHE / "frame_mn10_strong_1.pt", "frame_mn10")
    if args.head is not None:
        planned[1] = (args.head, MODELS / "frozen_head.pt", "frozen_head")

    hashes: dict[str, str] = {}
    for src, dst, key in planned:
        if not src.is_file():
            raise SystemExit(f"missing lab weight: {src}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        digest = sha256(dst)
        hashes[key] = digest
        print(f"copied {src.name} -> {dst}  sha256={digest}", flush=True)

    if MANIFEST.is_file():
        doc = json.loads(MANIFEST.read_text(encoding="utf-8"))
        for asset in doc.get("assets") or []:
            if asset.get("id") == "frame_mn10" and "frame_mn10" in hashes:
                asset["sha256"] = hashes["frame_mn10"]
            if asset.get("id") == "frozen_head" and "frozen_head" in hashes:
                asset["sha256"] = hashes["frozen_head"]
        doc["updated"] = __import__("datetime").date.today().isoformat()
        MANIFEST.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
        print(f"updated {MANIFEST}", flush=True)

    print(
        "\nNext:\n"
        "  1) Wire any code changes into ohush_live (same effort as the KEEP).\n"
        "  2) git add ohush_live/models/frozen_head.pt ohush_live/MODEL_MANIFEST.json LATEST_MUTER.md\n"
        "     (frame_mn10 stays fetched on Mac from the PretrainedSED GitHub release unless you change the URL)\n"
        "  3) commit + push research/windows-lab-node-01\n"
        "  4) Mac: git pull && follow LATEST_MUTER.md && ./scripts/desk restart-engine\n",
        flush=True,
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
