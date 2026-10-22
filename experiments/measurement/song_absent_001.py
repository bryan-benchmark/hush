"""A song only while the show is under the return floor.

Music at or above 0.70 and the 0.10 voice floor are already published.
The floor is the return. This asks what those two lines do together.
It does not start a commercial, and it does not mute.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from experiments.measurement.voice_enroll_split_001 import build_checks  # noqa: E402
from hush.break_trace import MUSIC_HIGH  # noqa: E402
from hush.voice_floor import FLOOR  # noqa: E402

OUT = REPO / "docs/ohush/research/SONG_ABSENT_001"
COMMERCIAL_S = 17648.4
STEP = 4.0


def covered(row: dict, use_now: bool) -> bool:
    music = row.get("music")
    voice = row.get("now") if use_now else row.get("score")
    if music is None or voice is None:
        return False
    return music >= MUSIC_HIGH and voice < FLOOR


def tally(checks: list[dict], use_now: bool) -> dict:
    ad = game = 0.0
    pods = set()
    cuts = []
    for row in checks:
        if not covered(row, use_now):
            continue
        if row["region"] == "ad":
            ad += STEP
            pods.add((row["session"], round(row["t"], 1)))
        elif row["region"] == "game":
            game += STEP
            cuts.append(
                {
                    "session": row["session"],
                    "t": row["t"],
                    "voice": round(row.get("now") if use_now else row["score"], 3),
                    "music": round(row["music"], 3),
                    "words": row.get("words") or "",
                }
            )
    broken = game > 0
    return {
        "voice": "current window" if use_now else "30 second max",
        "commercial_s": ad,
        "game_s": game,
        "ad_steps": int(ad / STEP),
        "broken": broken,
        "percentage": None if broken else round(100.0 * ad / COMMERCIAL_S, 3),
        "game_cuts": cuts[:12],
    }


def main() -> None:
    checks, _pods = build_checks()
    song_ad = STEP * sum(
        1 for row in checks if row["region"] == "ad" and row.get("music") is not None and row["music"] >= MUSIC_HIGH
    )
    payload = {
        "system": "song_absent_001",
        "mute_policy": False,
        "installed": False,
        "music_high": MUSIC_HIGH,
        "floor": FLOOR,
        "song_during_ads_s": song_ad,
        "lines": [tally(checks, False), tally(checks, True)],
        "note": "The floor does not start a commercial. These counts are what the two published lines do when both are required.",
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
