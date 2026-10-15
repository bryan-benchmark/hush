"""Verified program-speaker enrollment. Not a mute.

A verified row is one a person wrote, naming a speaker and a program-audio
interval. Cluster ids, booth_present, and .booth.json are not enrollments.
This script does not open those files and does not invent a speaker.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "docs/ohush/research/UNIVERSAL_V4_SPEAKER_ENROLLMENT_001"
LEDGER = OUT / "verified.jsonl"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    if LEDGER.exists():
        for line in LEDGER.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    payload = {
        "system": "universal_v4_speaker_enrollment",
        "verdict": "NOT_MEASURED" if not rows else "EVIDENCE_ONLY",
        "mute_policy": False,
        "verified_enrollments": len(rows),
        "refused_as_enrollment": [".booth.json", "cluster ids", "booth_present"],
        "booth_files_read": False,
    }
    (OUT / "results.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
