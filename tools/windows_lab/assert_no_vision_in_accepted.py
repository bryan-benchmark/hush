"""Fail if vision_auto rows ever leak into farm_accepted.jsonl."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ACCEPTED = Path(r"C:\OHushData\gpu_lab\audio_learn\broadcast_labels\farm_accepted.jsonl")


def main() -> int:
    if not ACCEPTED.is_file():
        print(json.dumps({"ok": True, "n": 0, "leaks": []}))
        return 0
    leaks = []
    n = 0
    for line in ACCEPTED.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        n += 1
        r = json.loads(line)
        src = str(r.get("source") or "")
        mid = str(r.get("model_id") or "")
        if "vision" in src.lower() or mid.startswith("vision_timeline"):
            leaks.append({"session": r.get("session"), "start_s": r.get("start_s"), "source": src, "model_id": mid})
    ok = not leaks
    print(json.dumps({"ok": ok, "n": n, "leaks": leaks}, indent=2))
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
