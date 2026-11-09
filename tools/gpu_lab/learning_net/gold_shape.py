"""Record how much of each broadcast the gold marks as commercial.

Fully annotated coverage that is not a mute-target commercial is program.
This probe only counts those spans. It does not edit the gold or choose a cutoff.
"""

from __future__ import annotations

from pathlib import Path

from experiments.ledger import sha256_text
from tools.gpu_lab.ladder import pairs
from tools.gpu_lab.learning_net.data import BRIDGE, bridge_masks
from tools.gpu_lab.learning_net.game_sounds import _role
from tools.gpu_lab.learning_net.log import finish_probe, open_probe
from tools.gpu_lab.prepare import DATA_ROOT

MODULE = Path(__file__)
PROBE_ID = "gold_shape"
QUESTION = "How much of each broadcast does the gold mark as commercial, and when does the last marked break end?"
PLACE_FOLDER = "20261023T044159Z_remainder_place"
PLACE_SHA256 = "51cd0a1d05274ff90c8461aa329db3250ba82269d563e6b53c8cc961277cd7f6"


def _cited(root: Path) -> None:
    path = root / "learning_net" / "probes" / PLACE_FOLDER / "result.json"
    digest = sha256_text(path.read_text(encoding="utf-8"))
    if digest != PLACE_SHA256:
        raise RuntimeError(f"{PLACE_FOLDER} hash {digest} does not match {PLACE_SHA256}")


def run(root: Path = DATA_ROOT) -> dict:
    parameters = {
        "program_definition": "fully annotated coverage minus mute-target commercials and unsure spans",
        "october_may_choose_cutoff": False,
        "gold_edited": False,
        "compared_with": {"probe_id": "remainder_place", "folder": PLACE_FOLDER, "result_sha256": PLACE_SHA256},
    }
    folder = open_probe(PROBE_ID, QUESTION, parameters, MODULE)
    _cited(root)
    rows = []
    for session in BRIDGE:
        mask = bridge_masks()[session]
        coverage = pairs(mask, "coverage")
        commercials = pairs(mask, "verified_commercial")
        programs = pairs(mask, "verified_program")
        coverage_s = round(sum(end - start for start, end in coverage), 3)
        commercial_s = round(sum(end - start for start, end in commercials), 3)
        longest = max(programs, key=lambda span: span[1] - span[0]) if programs else None
        rows.append(
            {
                "session": session,
                "role": _role(session),
                "coverage_s": coverage_s,
                "commercial_n": len(commercials),
                "commercial_s": commercial_s,
                "program_s": mask["program_s"],
                "commercial_seconds_per_hour": None if coverage_s <= 0 else round(commercial_s / (coverage_s / 3600.0), 3),
                "last_commercial_end_s": None if not commercials else round(max(end for _start, end in commercials), 3),
                "longest_program_span": None
                if longest is None
                else {
                    "start_seconds": round(longest[0], 3),
                    "end_seconds": round(longest[1], 3),
                    "duration_s": round(longest[1] - longest[0], 3),
                },
            }
        )
        print(
            f"  {session} breaks {len(commercials)} ad_s {commercial_s} last {rows[-1]['last_commercial_end_s']}",
            flush=True,
        )
    result = {
        "probe_id": PROBE_ID,
        "rows": rows,
        "gold_edited": False,
        "october_may_choose_cutoff": False,
        "remainder_place_result_sha256": PLACE_SHA256,
    }
    finish_probe(folder, PROBE_ID, QUESTION, parameters, result, MODULE)
    return result
