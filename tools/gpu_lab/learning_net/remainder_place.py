"""Place the leftover game seconds against the gold commercial boundaries.

The seconds come from the joint_remainder receipt. This probe does not
rescore them and does not move the cutoff.
"""

from __future__ import annotations

import json
from pathlib import Path

from experiments.ledger import sha256_text
from tools.gpu_lab.decisions import HOP_S
from tools.gpu_lab.ladder import pairs
from tools.gpu_lab.learning_net.data import bridge_masks
from tools.gpu_lab.learning_net.log import finish_probe, open_probe
from tools.gpu_lab.prepare import DATA_ROOT

MODULE = Path(__file__)
PROBE_ID = "remainder_place"
QUESTION = "Do the game seconds the frozen cutoff still hides sit against a commercial, or inside the game?"
REMAINDER_FOLDER = "20261023T044042Z_joint_remainder"
REMAINDER_SHA256 = "0bb80d61abcdecea4905a35a84956b72f9520981209b9d31ba1ab70f771a5fa7"
GAP_EDGES_S = (0.0, 2.0, 10.0, 30.0)


def nearest_commercial(moment: float, commercials: list[tuple[float, float]], hop_s: float = HOP_S) -> dict:
    start = moment
    end = moment + hop_s
    best: tuple[float, str] | None = None
    for begin, stop in commercials:
        if min(end, stop) - max(start, begin) > 1e-9:
            return {"gap_s": 0.0, "side": "overlaps_commercial"}
        if stop <= start + 1e-9:
            gap = start - stop
            side = "after_commercial"
        elif begin >= end - 1e-9:
            gap = begin - end
            side = "before_commercial"
        else:
            continue
        if best is None or gap < best[0]:
            best = (gap, side)
    if best is None:
        return {"gap_s": None, "side": None}
    return {"gap_s": round(best[0], 3), "side": best[1]}


def program_span(moment: float, programs: list[tuple[float, float]], hop_s: float = HOP_S) -> dict | None:
    end = moment + hop_s
    for begin, stop in programs:
        if min(end, stop) - max(moment, begin) <= 1e-9:
            continue
        return {
            "start_seconds": round(begin, 3),
            "end_seconds": round(stop, 3),
            "into_span_s": round(moment - begin, 3),
            "until_span_end_s": round(stop - end, 3),
        }
    return None


def gap_bin(gap_s: float | None, edges: tuple[float, ...] = GAP_EDGES_S) -> str | None:
    if gap_s is None:
        return None
    if gap_s <= edges[0]:
        return "overlaps"
    if gap_s <= edges[1]:
        return "within_2s"
    if gap_s <= edges[2]:
        return "within_10s"
    if gap_s <= edges[3]:
        return "within_30s"
    return "beyond_30s"


def _cited(root: Path) -> dict:
    path = root / "learning_net" / "probes" / REMAINDER_FOLDER / "result.json"
    text = path.read_text(encoding="utf-8")
    digest = sha256_text(text)
    if digest != REMAINDER_SHA256:
        raise RuntimeError(f"{REMAINDER_FOLDER} hash {digest} does not match {REMAINDER_SHA256}")
    return json.loads(text)


def run(root: Path = DATA_ROOT) -> dict:
    parameters = {
        "hop_s": HOP_S,
        "gap_edges_s": list(GAP_EDGES_S),
        "october_may_choose_cutoff": False,
        "compared_with": {"probe_id": "joint_remainder", "folder": REMAINDER_FOLDER, "result_sha256": REMAINDER_SHA256},
    }
    folder = open_probe(PROBE_ID, QUESTION, parameters, MODULE)
    cited = _cited(root)
    masks = bridge_masks()
    rows = []
    for source in cited["rows"]:
        session = source["session"]
        commercials = pairs(masks[session], "verified_commercial")
        programs = pairs(masks[session], "verified_program")
        placed = []
        for second in source["decision_seconds"]:
            place = nearest_commercial(second["t"], commercials)
            span = program_span(second["t"], programs)
            placed.append(
                {
                    "t": second["t"],
                    "class": second["class"],
                    "score": second["score"],
                    "commercial": place,
                    "gap_bin": gap_bin(place["gap_s"]),
                    "program_span": span,
                }
            )
        counts: dict[str, int] = {}
        for item in placed:
            counts[item["gap_bin"]] = counts.get(item["gap_bin"], 0) + 1
        rows.append(
            {
                "session": session,
                "program_cut_s": source["program_cut_s"],
                "n": len(placed),
                "gap_bins": counts,
                "seconds": placed,
            }
        )
        print(f"  {session} {counts}", flush=True)
    result = {
        "probe_id": PROBE_ID,
        "rows": rows,
        "october_may_choose_cutoff": False,
        "joint_remainder_result_sha256": REMAINDER_SHA256,
        "threshold": cited["threshold"],
    }
    finish_probe(folder, PROBE_ID, QUESTION, parameters, result, MODULE)
    return result
