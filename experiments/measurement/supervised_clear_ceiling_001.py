"""Cutoff from show seconds whose lookback is clear of commercials.

The head is the two-NBC logistic from SUPERVISED_HELDOUT_001. The ceiling is
the highest score whose covered second is entirely program and whose
five-second lookback contains no labeled commercial. Both NBC fit games set
that number. Held-out broadcasts do not move it. If they lose show audio,
that is the result.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from experiments.measurement.supervised_ceiling_001 import _names, _nearest_break  # noqa: E402
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
from tools.gpu_lab.learning_net.data import bridge_masks, load_cache  # noqa: E402
from tools.gpu_lab.splits import DEVELOP  # noqa: E402

OUT = REPO / "docs" / "ohush" / "research" / "SUPERVISED_CLEAR_CEILING_001"
PUBLISHED_MIXED_CUTOFF = 12.155325889587404
PUBLISHED_PROGRAM_CUTOFF = 9.892548561096193


def _lookback_commercial(moment: float, commercials: list[tuple[float, float]]) -> float:
    start = moment - WINDOW_S
    return sum(max(0.0, min(moment, stop) - max(start, begin)) for begin, stop in commercials)


def main() -> None:
    if set(DEVELOP) != {sid for sid, _name in OCTOBER}:
        raise SystemExit("October list drifted from the published development split")
    masks = bridge_masks()
    head, receipt = _fit(FIT)
    ceiling = None
    setter = None
    clear_n = 0
    contaminated_n = 0
    contaminated_max = None
    for session in FIT:
        cache = load_cache(session, WINDOW_S)
        times, scores, labels = _scores(head, session)
        commercials = pairs(masks[session], "verified_commercial")
        for index, (moment, score, label) in enumerate(zip(times, scores, labels)):
            if int(label) != 0:
                continue
            ad = _lookback_commercial(float(moment), commercials)
            if ad > 1e-9:
                contaminated_n += 1
                if contaminated_max is None or float(score) > contaminated_max:
                    contaminated_max = float(score)
                continue
            clear_n += 1
            if ceiling is None or float(score) > ceiling:
                ceiling = float(score)
                setter = {
                    "session": session,
                    "t": round(float(moment), 3),
                    "score": float(score),
                    "window_commercial_s": 0.0,
                    "nearest_break": _nearest_break(float(moment), commercials),
                    "emb": cache["emb"][index],
                }
    if ceiling is None or setter is None:
        raise SystemExit("no clear program second on the fit games")
    threshold = math.nextafter(ceiling, math.inf)
    if not (threshold < PUBLISHED_PROGRAM_CUTOFF < PUBLISHED_MIXED_CUTOFF):
        raise SystemExit(f"clear ceiling {threshold} is not below the two published lines")
    named = _names(setter["emb"][None, :])[0]
    setter_out = {key: value for key, value in setter.items() if key != "emb"}
    setter_out["score"] = round(setter_out["score"], 6)
    setter_out["audioset_top3"] = named
    print(
        f"fit {receipt} clear cutoff {threshold} setter {setter_out['session']} {setter_out['t']} "
        f"clear {clear_n} contaminated lookbacks {contaminated_n}",
        flush=True,
    )

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
        "ESPN, held out, clear-lookback NBC cutoff. Shaded spans are labeled commercials.",
        *series["hush_20260914_212529"],
        threshold,
    )
    _plot(
        OUT / "redzone_timeline.png",
        "RedZone, held out, clear-lookback NBC cutoff. This tape has no labeled commercials.",
        *series["hush_20260913_150934"],
        threshold,
    )
    payload = {
        "id": "SUPERVISED_CLEAR_CEILING_001",
        "follows": "SUPERVISED_PROGRAM_CEILING_001",
        "published_mixed_cutoff_unchanged": PUBLISHED_MIXED_CUTOFF,
        "published_program_cutoff_unchanged": PUBLISHED_PROGRAM_CUTOFF,
        "window_s": WINDOW_S,
        "fit": receipt,
        "threshold": threshold,
        "threshold_rule": (
            "one step above the highest score whose covered second is entirely program "
            "and whose five-second lookback contains no labeled commercial, on the two NBC fit games"
        ),
        "setter": setter_out,
        "clear_program_seconds": clear_n,
        "program_seconds_with_commercial_in_lookback": contaminated_n,
        "max_score_among_contaminated_lookbacks": None if contaminated_max is None else round(contaminated_max, 3),
        "october_may_choose_cutoff": False,
        "live_mute_changed": False,
        "sessions": rows,
    }
    (OUT / "results.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT / 'results.json'}", flush=True)


if __name__ == "__main__":
    main()
