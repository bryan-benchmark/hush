"""Read finished transcript chunks on stdin. Write the ledger on stdout.

This process does not open the speakers and does not record. A crash here
leaves the television alone. Feed it the same chunk records the replay uses.

    python -m ohush_live.football_shadow
"""

from __future__ import annotations

import json
import sys

from ohush_live.football_brain import FootballEngine


def main() -> None:
    engine = FootballEngine()
    for line in sys.stdin:
        if not line.strip():
            continue
        chunk = json.loads(line)
        events, state = engine.observe(chunk)
        for event in events:
            sys.stdout.write(json.dumps({"record": "event", **event}) + "\n")
        if events:
            sys.stdout.write(json.dumps({"record": "state", "audio_t": chunk["t0"], **state}) + "\n")
    sys.stdout.write(json.dumps({"record": "done", "duplicates": engine.duplicates, "applied": False}) + "\n")


if __name__ == "__main__":
    main()
