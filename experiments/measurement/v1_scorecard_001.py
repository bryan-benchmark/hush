"""Score the uninstalled song hold the way the accuracy rule requires.

The two covers and the quiet line are already published. This does not
search for a new cover, and it does not mute.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "docs/ohush/research/V1_SCORECARD_001"
COMMERCIAL_S = 17648.4
HOLD = json.loads((REPO / "docs/ohush/research/V1_HOLD_001/results.json").read_text())


def main() -> None:
    pods = []
    for line in (REPO / "docs/ohush/research/START_END_001/receipts.jsonl").read_text().splitlines():
        if line.strip():
            row = json.loads(line)
            pods.append(row)
    by_key = {
        (row["session"], round(row["pod_start"], 3)): row for row in HOLD["covers"]
    }
    rows = []
    for pod in pods:
        length = round(float(pod["end"]) - float(pod["start"]), 3)
        held = by_key.get((pod["session"], round(float(pod["start"]), 3)))
        if held is None:
            rows.append(
                {
                    "session": pod["session"],
                    "network": pod["network"],
                    "length_s": length,
                    "held_s": 0.0,
                    "start_lag_s": length,
                    "tail_heard_s": 0.0,
                    "return_lag_s": 0.0,
                }
            )
            continue
        start_lag = round(held["cover_start"] - held["pod_start"], 3)
        rows.append(
            {
                "session": pod["session"],
                "network": pod["network"],
                "length_s": length,
                "held_s": held["commercial_s"],
                "start_lag_s": start_lag,
                "tail_heard_s": held["ad_still_heard_s"],
                "return_lag_s": 0.0,
            }
        )
    held = round(sum(row["held_s"] for row in rows), 3)
    missed = sum(1 for row in rows if row["held_s"] == 0)
    lags = sorted(row["start_lag_s"] for row in rows)
    mid = lags[len(lags) // 2]
    payload = {
        "system": "v1_scorecard_001",
        "mute_policy": False,
        "installed": False,
        "pods": len(rows),
        "pods_never_muted": missed,
        "commercial_s": COMMERCIAL_S,
        "held_s": held,
        "heard_s": round(COMMERCIAL_S - held, 3),
        "program_s": HOLD["program_s"],
        "broken": HOLD["broken"],
        "percentage": None if HOLD["broken"] else round(100.0 * held / COMMERCIAL_S, 3),
        "return_lag_s": 0.0,
        "median_start_lag_s": mid,
        "note": "Start lag on a commercial that is never muted is its whole length. Return lag is zero because both let-gos are still inside the commercial.",
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
