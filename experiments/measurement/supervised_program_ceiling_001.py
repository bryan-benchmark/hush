"""Score the same NBC head with a ceiling taken from entirely-program seconds.

SUPERVISED_CEILING_001 found that 12.155 is a mixed boundary second whose
lookback is still the ad. This run takes one step above the highest score
whose covered second is entirely program, on the same two NBC games and the
same head. Held-out broadcasts do not move it. If the fit games lose show
audio, that is the result.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from experiments.measurement.supervised_heldout_001 import (  # noqa: E402
    FIT,
    OCTOBER,
    REPORT,
    WINDOW_S,
    _fit,
    _plot,
    _score_session,
    _scores,
)
from tools.gpu_lab.ladder import pairs  # noqa: E402
from tools.gpu_lab.learning_net.data import bridge_masks  # noqa: E402
from tools.gpu_lab.splits import DEVELOP  # noqa: E402

OUT = REPO / "docs" / "ohush" / "research" / "SUPERVISED_PROGRAM_CEILING_001"
PUBLISHED_MIXED_CUTOFF = 12.155325889587404


def main() -> None:
    if set(DEVELOP) != {sid for sid, _name in OCTOBER}:
        raise SystemExit("October list drifted from the published development split")
    masks = bridge_masks()
    head, receipt = _fit(FIT)
    ceiling = None
    setter = None
    for session in FIT:
        times, scores, labels = _scores(head, session)
        for moment, score, label in zip(times, scores, labels):
            if int(label) != 0:
                continue
            if ceiling is None or float(score) > ceiling:
                ceiling = float(score)
                setter = {"session": session, "t": round(float(moment), 3), "score": float(score)}
    if ceiling is None or setter is None:
        raise SystemExit("no entirely-program second on the fit games")
    threshold = math.nextafter(ceiling, math.inf)
    if threshold >= PUBLISHED_MIXED_CUTOFF:
        raise SystemExit("entirely-program ceiling did not sit below the mixed-second line")
    print(f"fit {receipt} entirely-program cutoff {threshold} setter {setter}", flush=True)

    rows = []
    series = {}
    for session in (*FIT, *(sid for sid, _name, _role in REPORT), *(sid for sid, _name in OCTOBER)):
        times, scores, labels = _scores(head, session)
        row = _score_session(masks[session], times, scores, labels, threshold)
        if session in FIT:
            row["role"] = "fit"
        elif session in {sid for sid, _name, _role in REPORT}:
            row["role"] = "held_out"
        else:
            row["role"] = "october_already_inspected"
        rows.append(row)
        if session in ("hush_20260914_212529", "hush_20260913_150934"):
            series[session] = (times, scores, pairs(masks[session], "verified_commercial"))
        print(
            f"{row['name']} recognized {row['commercial_recognized_s']} "
            f"missed {row['commercial_missed_s']} program {row['program_mistaken_s']} "
            f"interruptions {row['program_interruptions']}",
            flush=True,
        )

    OUT.mkdir(parents=True, exist_ok=True)
    _plot(
        OUT / "espn_timeline.png",
        "ESPN, held out, entirely-program NBC cutoff. Shaded spans are labeled commercials.",
        *series["hush_20260914_212529"],
        threshold,
    )
    _plot(
        OUT / "redzone_timeline.png",
        "RedZone, held out, entirely-program NBC cutoff. This tape has no labeled commercials.",
        *series["hush_20260913_150934"],
        threshold,
    )
    payload = {
        "id": "SUPERVISED_PROGRAM_CEILING_001",
        "follows": "SUPERVISED_CEILING_001",
        "published_mixed_cutoff_unchanged": PUBLISHED_MIXED_CUTOFF,
        "window_s": WINDOW_S,
        "fit": receipt,
        "threshold": threshold,
        "threshold_rule": "one step above the highest score whose covered second is entirely program, on the two NBC fit games",
        "setter": setter,
        "october_may_choose_cutoff": False,
        "live_mute_changed": False,
        "sessions": rows,
    }
    (OUT / "results.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT / 'results.json'}", flush=True)


if __name__ == "__main__":
    main()
