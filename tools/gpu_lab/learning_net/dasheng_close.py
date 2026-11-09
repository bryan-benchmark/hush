"""Cite the AST, Dasheng-base, and Dasheng-1.2B ranking receipts.

This probe does not embed audio, fit a cutoff, or start another encoder.
"""

from __future__ import annotations

import json
from pathlib import Path

from experiments.ledger import sha256_file

from tools.gpu_lab.learning_net.close import verify_citations
from tools.gpu_lab.learning_net.log import finish_probe, open_probe
from tools.gpu_lab.prepare import DATA_ROOT

MODULE = Path(__file__)
PROBE_ID = "dasheng_scale_close"
QUESTION = "Did frozen Dasheng-1.2B lift every later game to the pre-October ranking floor?"

CITATIONS = (
    {
        "probe_id": "ranking",
        "folder": "20261023T004935Z_ranking",
        "result_sha256": "477406f08d314fb0d9e26cda97ba48b58997a4a27323b5ffdca82336560c6153",
        "used_for_reading": False,
    },
    {
        "probe_id": "dasheng_ranking",
        "folder": "20261023T011903Z_dasheng_ranking",
        "result_sha256": "128ac85b53cb4618215ed17dbd61fe9df57754c0d341329cd7c0a13bc157d18f",
        "used_for_reading": False,
    },
    {
        "probe_id": "dasheng_12b_ranking",
        "folder": "20261023T013456Z_dasheng_12b_ranking",
        "result_sha256": "d27022091b3dedef9cc52636828dfe755acea740d7696f6e2ae6e387ef172df0",
        "used_for_reading": True,
    },
)


def scale_reading(large: dict) -> dict:
    """A later game stays weak when its AUC is below every pre-October game.

    The 1.2B receipt already applied that comparison. Lifting every later game
    would leave the stay-on-these-vectors row. Anything still below the floor
    leaves no named encoder past Dasheng-1.2B.
    """
    weak = list(large["later_games_below_pre_october_floor"])
    windows = []
    for block in large["ranking_against_pre_october_floor"]:
        below = list(block["october_below_pre_october_floor"])
        worst = min(below, key=lambda row: row["auc"]) if below else None
        windows.append(
            {
                "window_s": block["window_s"],
                "pre_october_floor_auc": block["pre_october_floor_auc"],
                "october_below_pre_october_floor": below,
                "lowest_october": worst,
            }
        )
    lifted = not weak
    return {
        "later_games_below_pre_october_floor": weak,
        "larger_encoder_lifted_every_later_game": lifted,
        "windows": windows,
        "one_next_build": "stay_on_these_vectors" if lifted else None,
        "larger_model_started": False,
        "finetuned": False,
        "october_may_choose_cutoff": False,
        "need_json_rewritten": False,
    }


def run(root: Path = DATA_ROOT) -> dict:
    need_path = root / "NEED.json"
    parameters = {
        "citations": [dict(item) for item in CITATIONS],
        "need_json_rewritten": False,
        "need_json_sha256": sha256_file(need_path) if need_path.is_file() else None,
        "larger_model_started": False,
        "october_may_choose_cutoff": False,
    }
    folder = open_probe(PROBE_ID, QUESTION, parameters, MODULE)
    checked = verify_citations(root / "learning_net", CITATIONS)
    used = next(item for item in checked if item["used_for_reading"])
    large = json.loads(Path(used["result_path"]).read_text(encoding="utf-8"))
    reading = scale_reading(large)
    result = {
        "probe_id": PROBE_ID,
        "citations": checked,
        "reading": reading,
        "need_json_rewritten": False,
        "need_json_sha256": parameters["need_json_sha256"],
        "larger_model_started": False,
    }
    print(f"  lifted {reading['larger_encoder_lifted_every_later_game']} next {reading['one_next_build']}", flush=True)
    finish_probe(folder, PROBE_ID, QUESTION, parameters, result, MODULE)
    return result
