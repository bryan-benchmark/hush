"""Hold the spot-fingerprint covers until the song drops.

The covers are the ones SPOT_FINGERPRINT_001 already started at count 200.
The quiet line is music under 0.30, on the 4-second steps already logged.
No new cover is searched. The count is not moved.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from experiments.measurement.v1_hold_001 import hold_until_quiet  # noqa: E402
from hush.break_trace import MUSIC_LOW  # noqa: E402
from tools.gpu_lab.ladder import pairs  # noqa: E402
from tools.gpu_lab.learning_net.data import bridge_masks  # noqa: E402

OUT = REPO / "docs" / "ohush" / "research" / "SPOT_HOLD_001"
SPOT = REPO / "docs" / "ohush" / "research" / "SPOT_FINGERPRINT_001" / "results.json"
TRACE = REPO / "docs" / "ohush" / "research" / "BREAK_TRACE_001" / "decisions.jsonl"
COMMERCIAL_S = 17648.4


def pod_of(moment: float, commercials: list[tuple[float, float]]) -> tuple[float, float] | None:
    for start, end in commercials:
        if start - 1e-6 <= moment < end:
            return start, end
    return None


def main() -> None:
    spot = json.loads(SPOT.read_text(encoding="utf-8"))
    if spot["count"] != 200:
        raise SystemExit("spot result is not the published count")
    masks = bridge_masks()
    steps: dict[str, list[dict]] = {}
    for line in TRACE.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        steps.setdefault(row["session"], []).append(row)
    for rows in steps.values():
        rows.sort(key=lambda row: row["t"])

    holds = []
    for session_row in spot["sessions"]:
        hits = sorted(session_row["hits"], key=lambda row: row["cover_t0"])
        commercials = pairs(masks[session_row["session"]], "verified_commercial")
        trace = steps.get(session_row["session"], [])
        open_until = None
        open_pod = None
        for hit in hits:
            pod = pod_of(hit["cover_t0"], commercials)
            if pod is None:
                holds.append(
                    {
                        "session": session_row["session"],
                        "name": session_row["name"],
                        "cover_t0": hit["cover_t0"],
                        "broken": True,
                        "because": "cover is outside a labeled commercial",
                    }
                )
                continue
            if open_until is not None and open_pod == pod and hit["cover_t0"] < open_until:
                continue
            result = hold_until_quiet(trace, hit["cover_t0"], pod[1])
            open_until = result.get("unmute_t")
            open_pod = pod
            holds.append(
                {
                    "session": session_row["session"],
                    "name": session_row["name"],
                    "pod_t0": round(pod[0], 3),
                    "pod_t1": round(pod[1], 3),
                    "cover_t0": hit["cover_t0"],
                    "fingerprint_s": 5.0,
                    **result,
                }
            )
            print(
                f"{session_row['name']} from {hit['cover_t0']} "
                f"commercial {result.get('commercial_s')} program {result.get('program_s')}",
                flush=True,
            )

    broken = any(row.get("broken") for row in holds)
    program = round(sum(row.get("program_s") or 0.0 for row in holds), 3)
    commercial = round(sum(row.get("commercial_s") or 0.0 for row in holds if not row.get("broken")), 3)
    payload = {
        "id": "SPOT_HOLD_001",
        "follows": "SPOT_FINGERPRINT_001",
        "quiet_music": MUSIC_LOW,
        "count_unchanged": 200,
        "new_cover_searched": False,
        "installed": False,
        "broken": broken or program > 0,
        "fingerprint_commercial_s": 30.0,
        "commercial_s": None if broken or program > 0 else commercial,
        "program_s": program,
        "percentage": None if broken or program > 0 else round(100.0 * commercial / COMMERCIAL_S, 3),
        "holds": holds,
        "live_mute_changed": False,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: payload[key] for key in ("commercial_s", "program_s", "broken")}, indent=2), flush=True)


if __name__ == "__main__":
    main()
