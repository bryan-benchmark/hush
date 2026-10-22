"""Hold a published count-200 cover until the song drops.

The two covers and the quiet line are already published. This does not
search for a new cover, and it does not mute on its own.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from hush.break_trace import MUSIC_LOW  # noqa: E402

OUT = REPO / "docs/ohush/research/V1_HOLD_001"
COMMERCIAL_S = 17648.4

# From docs/ohush/research/UNIVERSAL_V1/REPORT.md. Not searched again.
COVERS = (
    {
        "network": "Prime Video",
        "session": "hush_20261008_205100",
        "pod_start": 139.874,
        "pod_end": 376.900,
        "cover_start": 150.0,
        "cover_end": 170.0,
    },
    {
        "network": "Cable",
        "session": "hush_20261012_204200",
        "pod_start": 5080.063,
        "pod_end": 5216.609,
        "cover_start": 5090.0,
        "cover_end": 5095.0,
    },
)


def hold_until_quiet(steps: list[dict], cover_start: float, pod_end: float) -> dict:
    """Stay covered from cover_start until music falls under the published quiet line."""
    drop = next(
        (
            row
            for row in steps
            if row["t"] >= cover_start and row.get("music") is not None and row["music"] < MUSIC_LOW
        ),
        None,
    )
    if drop is None:
        return {"unmute_t": None, "broken": True, "commercial_s": 0.0, "program_s": None}
    unmute = float(drop["t"])
    if unmute > pod_end:
        return {
            "unmute_t": unmute,
            "music": drop["music"],
            "broken": True,
            "commercial_s": round(pod_end - cover_start, 3),
            "program_s": round(unmute - pod_end, 3),
        }
    return {
        "unmute_t": unmute,
        "music": drop["music"],
        "broken": False,
        "commercial_s": round(unmute - cover_start, 3),
        "program_s": 0.0,
        "ad_still_heard_s": round(pod_end - unmute, 3),
    }


def main() -> None:
    by_session: dict[str, list[dict]] = {row["session"]: [] for row in COVERS}
    for line in (REPO / "docs/ohush/research/BREAK_TRACE_001/decisions.jsonl").read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row["session"] in by_session:
            by_session[row["session"]].append(row)
    for rows in by_session.values():
        rows.sort(key=lambda row: row["t"])

    receipts = []
    for cover in COVERS:
        result = hold_until_quiet(by_session[cover["session"]], cover["cover_start"], cover["pod_end"])
        published = cover["cover_end"] - cover["cover_start"]
        receipts.append({**cover, "published_s": published, **result})

    commercial = round(sum(row["commercial_s"] for row in receipts if not row["broken"]), 3)
    program = round(sum(row["program_s"] or 0.0 for row in receipts), 3)
    broken = any(row["broken"] for row in receipts)
    summary = {
        "system": "v1_hold_001",
        "mute_policy": False,
        "installed": False,
        "quiet_music": MUSIC_LOW,
        "broken": broken,
        "published_commercial_s": 25.0,
        "commercial_s": commercial,
        "program_s": program,
        "percentage": None if broken or program > 0 else round(100.0 * commercial / COMMERCIAL_S, 3),
        "covers": receipts,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(summary, indent=2) + "\n")
    (OUT / "receipts.jsonl").write_text("".join(json.dumps(row) + "\n" for row in receipts))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
