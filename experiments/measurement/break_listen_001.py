"""Clips centered on each logged football break, for the break logger.

Eighteen seconds on either side of the logged start, then the same around
the logged end. The green line in the logger is that logged edge.
Holdouts are not included. Gold is not edited.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.gpu_lab.ladder import pairs  # noqa: E402
from tools.gpu_lab.learning_net.data import bridge_masks  # noqa: E402
from tools.gpu_lab.splits import CALIBRATE, DEVELOP, HOLDOUTS, TRAIN  # noqa: E402

OUT = REPO / "docs" / "ohush" / "research" / "BREAK_LISTEN_001" / "queue.jsonl"
PAD = 18.0
NAMES = {
    "hush_20260909_213047": "Sept 9 NBC",
    "hush_20260913_210542": "Sept 13 NBC",
    "hush_20260914_212529": "Sept 14 ESPN",
    "hush_20260924_220624": "Sept 24 Prime",
    "hush_20261008_205100": "Oct 8 Prime",
    "hush_20261010_222400": "Oct 10",
    "hush_20261011_135700": "Oct 11 afternoon",
    "hush_20261011_204300": "Oct 11 night",
    "hush_20261012_204200": "Oct 12",
}


def main() -> None:
    masks = bridge_masks()
    rows = []
    for session in list(TRAIN) + list(CALIBRATE) + list(DEVELOP):
        if session in HOLDOUTS:
            raise SystemExit(f"refusing sealed holdout {session}")
        name = NAMES.get(session, session)
        for start, end in pairs(masks[session], "verified_commercial"):
            for kind, edge in (("start", float(start)), ("end", float(end))):
                play = max(0.0, edge - PAD)
                stop = edge + PAD
                rows.append(
                    {
                        "id": f"{session}:{kind}:{edge:.3f}",
                        "session": session,
                        "play_start": round(play, 3),
                        "duration": round(stop - play, 3),
                        "mark_s": round(edge - play, 3),
                        "caption": f"{name}. Logged break {kind} is the green line, at {edge - play:.1f}s in this clip.",
                    }
                )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    print(json.dumps({"clips": len(rows), "path": str(OUT)}), flush=True)


if __name__ == "__main__":
    main()
