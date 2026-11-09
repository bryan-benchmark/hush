"""Does the sound change across an eye dip, on the September 13 game only.

The dip list is the one already counted. The scores are the two-NBC head.
A break would be a different score on the two sides. A dip in the show
would be the same kind of sound on both sides. Nothing here mutes.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from experiments.measurement.supervised_heldout_001 import FIT, _fit, _scores  # noqa: E402

EYE = REPO / "docs" / "ohush" / "research" / "DROP_SHAPE_001" / "eye.json"
SESSION = "hush_20260913_210542"


def _at(times, scores, moment):
    index = int(np.argmin(np.abs(times - moment)))
    if abs(float(times[index]) - moment) > 1.0:
        return None
    return float(scores[index])


def _median(values):
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return round(ordered[mid], 3)
    return round(0.5 * (ordered[mid - 1] + ordered[mid]), 3)


def main() -> None:
    eye = json.loads(EYE.read_text(encoding="utf-8"))
    _head, _receipt = _fit(FIT)
    times, scores, _labels = _scores(_head, SESSION)
    groups = {"start": [], "end": [], "show": []}
    for row in eye["rows"]:
        before = _at(times, scores, row["t"])
        after = _at(times, scores, row["t"] + 5.0)
        if before is None or after is None:
            continue
        if row["kind"] == "start" and row["distance_s"] <= 8:
            groups["start"].append(after - before)
        elif row["kind"] == "end" and row["distance_s"] <= 8:
            groups["end"].append(after - before)
        elif row["distance_s"] > 20 and not row["inside_or_beside_break"]:
            groups["show"].append(after - before)
    summary = {
        role: {
            "n": len(values),
            "median_after_minus_before": _median(values),
            "after_higher": sum(value > 2 for value in values),
            "after_lower": sum(value < -2 for value in values),
        }
        for role, values in groups.items()
    }
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
