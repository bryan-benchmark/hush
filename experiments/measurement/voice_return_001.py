"""Return lag if a voice over 0.10 waits for the song to drop.

The voice floor and the music lines are already published. Nothing here is
refit. This does not mute, and it does not decide the cut into a commercial.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from experiments.measurement.voice_enroll_split_001 import build_checks  # noqa: E402
from hush.break_trace import MUSIC_LOW  # noqa: E402
from hush.voice_floor import FLOOR  # noqa: E402

OUT = REPO / "docs/ohush/research/VOICE_RETURN_001"
HORIZON_S = 180.0
LONG_S = 60.0


def main() -> None:
    checks, pods = build_checks()
    networks = {}
    for line in (REPO / "docs/ohush/research/START_END_001/receipts.jsonl").read_text().splitlines():
        if line.strip():
            row = json.loads(line)
            networks[row["session"]] = row["network"]
    by_session: dict[str, list[dict]] = defaultdict(list)
    for row in checks:
        if row.get("now") is not None:
            by_session[row["session"]].append(row)
    for rows in by_session.values():
        rows.sort(key=lambda row: row["t"])

    receipts = []
    for session, edges in pods.items():
        rows = by_session.get(session, [])
        for start, end in edges:
            after = [row for row in rows if row["t"] > end]
            game = []
            stopped = "horizon"
            for row in after:
                if row["t"] > end + HORIZON_S:
                    break
                if row["region"] == "ad":
                    stopped = "next_commercial"
                    break
                if row["region"] == "not_game":
                    stopped = "not_the_game"
                    break
                game.append(row)
            first = game[0] if game else None
            voice = next((row for row in game if row["now"] >= FLOOR), None)
            quiet = next(
                (
                    row
                    for row in game
                    if row["now"] >= FLOOR and row.get("music") is not None and row["music"] < MUSIC_LOW
                ),
                None,
            )
            voice_lag = None if first is None or voice is None else round(voice["t"] - first["t"], 1)
            quiet_lag = None if first is None or quiet is None else round(quiet["t"] - first["t"], 1)
            song_wait = None
            if voice_lag is not None and quiet_lag is not None:
                song_wait = round(quiet_lag - voice_lag, 1)
            elif voice is not None:
                song_wait = None
            receipts.append(
                {
                    "session": session,
                    "network": networks.get(session),
                    "commercial_start": start,
                    "commercial_end": end,
                    "first_game_t": None if first is None else first["t"],
                    "gap_from_end_s": None if first is None else round(first["t"] - end, 1),
                    "stopped": None if first else stopped,
                    "voice_lag_s": voice_lag,
                    "quiet_lag_s": quiet_lag,
                    "song_wait_s": song_wait,
                    "voice_who": None if voice is None else voice.get("who"),
                    "voice_now": None if voice is None else round(voice["now"], 3),
                    "voice_music": None if voice is None or voice.get("music") is None else round(voice["music"], 3),
                    "voice_words": None if voice is None else voice.get("words"),
                    "quiet_words": None if quiet is None else quiet.get("words"),
                    "long": bool(voice is not None and (song_wait is None or song_wait >= LONG_S)),
                }
            )

    def median(values: list[float]) -> float | None:
        if not values:
            return None
        ordered = sorted(values)
        return ordered[len(ordered) // 2]

    heard = [row for row in receipts if row["voice_lag_s"] is not None]
    settled = [row for row in receipts if row["quiet_lag_s"] is not None]
    long_rows = [row for row in receipts if row["long"]]
    no_game = [row for row in receipts if row["first_game_t"] is None]
    voice_only = [row["voice_lag_s"] for row in heard]
    quiet_only = [row["quiet_lag_s"] for row in settled]
    waits = [row["song_wait_s"] for row in heard if row["song_wait_s"] is not None]

    def within(values: list[float], limit: float) -> int:
        return sum(1 for value in values if value <= limit)

    summary = {
        "system": "voice_return_001",
        "mute_policy": False,
        "floor": FLOOR,
        "quiet_music": MUSIC_LOW,
        "commercials": len(receipts),
        "no_game_after": len(no_game),
        "voice_back": len(heard),
        "quiet_back": len(settled),
        "song_still_at_60s": len(long_rows),
        "voice_lag_median_s": median(voice_only),
        "quiet_lag_median_s": median(quiet_only),
        "song_wait_median_s": median(waits),
        "quiet_within_s": {
            "0": within(quiet_only, 0),
            "4": within(quiet_only, 4),
            "12": within(quiet_only, 12),
            "30": within(quiet_only, 30),
            "60": within(quiet_only, 60),
        },
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(summary, indent=2) + "\n")
    (OUT / "receipts.jsonl").write_text("".join(json.dumps(row) + "\n" for row in receipts))
    print(json.dumps(summary, indent=2))
    print("LONG")
    for row in long_rows:
        print(
            f"  {row['network']:12} {row['session'][-6:]} end {row['commercial_end']:.0f} "
            f"voice {row['voice_lag_s']} quiet {row['quiet_lag_s']} {row['voice_who']} "
            f"music {row['voice_music']} | {(row['voice_words'] or '')[:120]}"
        )


if __name__ == "__main__":
    main()
