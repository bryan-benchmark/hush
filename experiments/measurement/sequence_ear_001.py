"""The broadcast sequence the ear uses, scored without a new cutoff.

Lines were published before this run and are not searched:

- Music under 0.30 at 30 seconds before a start, then music at least 0.70
  and speech at least 0.50 at 5 seconds. Those are the voice-over-song lines.
- A 12 dB gap inside the 2 seconds centered on the boundary. That is the
  boundaries probe. The decision is stamped one second after the boundary,
  so the window has already been heard.

A start candidate is both. A return candidate is the same 12 dB gap at the
labeled end. A two-minute timer is not a return. October does not move a
line. Nothing here mutes.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.gpu_lab.audio_load import load_coverage  # noqa: E402
from tools.gpu_lab.ladder import pairs  # noqa: E402
from tools.gpu_lab.learning_net.data import bridge_masks  # noqa: E402

SONG = REPO / "docs/ohush/research/VOICE_OVER_SONG_001/results.json"
OUT = REPO / "docs/ohush/research/SEQUENCE_EAR_001"
SR = 16000
MUSIC_LOW = 0.30
MUSIC_HIGH = 0.70
SPEECH_LINE = 0.50
GAP_DB = 12.0
REDZONE = "hush_20260913_150934"
SEPTEMBER = (
    "hush_20260909_213047",
    "hush_20260913_210542",
    "hush_20260914_212529",
    "hush_20260924_220624",
)


def dip(audio: np.ndarray, origin: float, center: float) -> float | None:
    a = int(round((center - 1.0 - origin) * SR))
    b = int(round((center + 1.0 - origin) * SR))
    if a < 0 or b > len(audio) or b - a < SR:
        return None
    window = audio[a:b]
    hop = int(0.1 * SR)
    frames = window[: len(window) - (len(window) % hop)].reshape(-1, hop)
    rms = np.sqrt(np.mean(frames * frames, axis=1) + 1e-12)
    db = 20.0 * np.log10(rms)
    return float(np.median(db) - np.min(db))


def song_arrived(row: dict) -> bool | None:
    horizons = row.get("horizons") or {}
    early = horizons.get("30")
    late = horizons.get("5")
    if not early or not late:
        return None
    return bool(
        early["music"] < MUSIC_LOW
        and late["music"] >= MUSIC_HIGH
        and late["speech"] >= SPEECH_LINE
    )


def near_pod(moment: float, pods: list[tuple[float, float]], pad: float = 30.0) -> bool:
    return any(start - pad <= moment <= end + pad for start, end in pods)


def main() -> None:
    song = json.loads(SONG.read_text(encoding="utf-8"))
    masks = bridge_masks()
    by_session: dict[str, list[dict]] = {}
    for row in song["breaks"]:
        by_session.setdefault(row["session"], []).append(row)

    sessions = []
    for session, rows in sorted(by_session.items()):
        mask = masks[session]
        coverage = pairs(mask, "coverage")[0]
        pods = pairs(mask, "verified_commercial")
        print(f"load {session}", flush=True)
        audio = load_coverage(session, coverage[0], coverage[1])
        starts = []
        ends = []
        for row in rows:
            mark = float(row["t"])
            arrived = song_arrived(row)
            gap = dip(audio, coverage[0], mark)
            cut = bool(gap is not None and gap >= GAP_DB)
            starts.append({
                "t": round(mark, 3),
                "song_arrived": arrived,
                "cut_db": None if gap is None else round(gap, 3),
                "cut": cut,
                "sequence": bool(arrived and cut),
            })
            end = next((stop for start, stop in pods if abs(start - mark) < 0.05), None)
            if end is None:
                continue
            end_gap = dip(audio, coverage[0], end)
            ends.append({
                "t": round(end, 3),
                "cut_db": None if end_gap is None else round(end_gap, 3),
                "cut": bool(end_gap is not None and end_gap >= GAP_DB),
                "length_s": round(end - mark, 3),
            })
        program_gaps = []
        cursor = coverage[0] + 60.0
        while cursor + 1.0 < coverage[1]:
            if not near_pod(cursor, pods):
                gap = dip(audio, coverage[0], cursor)
                if gap is not None:
                    program_gaps.append(gap)
            cursor += 60.0
        known = [row for row in starts if row["song_arrived"] is not None]
        sessions.append({
            "session": session,
            "breaks": len(starts),
            "song_arrived": sum(row["song_arrived"] is True for row in known),
            "song_known": len(known),
            "cut_at_start": sum(row["cut"] for row in starts),
            "sequence": sum(row["sequence"] for row in starts),
            "cut_at_end": sum(row["cut"] for row in ends),
            "ends": len(ends),
            "near_30s": sum(abs(row["length_s"] - 30) <= 7.5 for row in ends),
            "near_120s": sum(abs(row["length_s"] - 120) <= 7.5 for row in ends),
            "near_135s": sum(abs(row["length_s"] - 135) <= 7.5 for row in ends),
            "program_samples": len(program_gaps),
            "program_cuts": sum(gap >= GAP_DB for gap in program_gaps),
        })
        print(
            f"  sequence {sessions[-1]['sequence']}/{sessions[-1]['breaks']} "
            f"end-cut {sessions[-1]['cut_at_end']}/{sessions[-1]['ends']} "
            f"program-cut {sessions[-1]['program_cuts']}/{sessions[-1]['program_samples']}",
            flush=True,
        )
        del audio

    def total(key: str, chosen: list[dict]) -> int:
        return sum(row[key] for row in chosen)

    september = [row for row in sessions if row["session"] in SEPTEMBER]
    later = [row for row in sessions if row["session"] not in SEPTEMBER]
    payload = {
        "id": "SEQUENCE_EAR_001",
        "lines": {
            "music_low_at_30s": MUSIC_LOW,
            "music_high_at_5s": MUSIC_HIGH,
            "speech_at_5s": SPEECH_LINE,
            "gap_db": GAP_DB,
            "gap_window": "2 seconds centered on the boundary, available 1 second later",
            "timer": "not a return",
        },
        "october_may_choose_cutoff": False,
        "live_mute_changed": False,
        "sessions": sessions,
        "september": {
            "sequence": total("sequence", september),
            "breaks": total("breaks", september),
            "program_cuts": total("program_cuts", september),
            "program_samples": total("program_samples", september),
        },
        "later_games_same_lines": {
            "sequence": total("sequence", later),
            "breaks": total("breaks", later),
            "program_cuts": total("program_cuts", later),
            "program_samples": total("program_samples", later),
        },
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"september": payload["september"], "later": payload["later_games_same_lines"]}, indent=2))


if __name__ == "__main__":
    main()
