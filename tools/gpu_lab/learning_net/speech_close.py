"""Cite the speech-rank receipt. Do not start a speech-to-text model.

The word classifier opens only when speech-named seconds are the ones that
fail to rank. This probe checks that comparison and stops there.
"""

from __future__ import annotations

import json
from pathlib import Path

from experiments.ledger import sha256_file

from tools.gpu_lab.learning_net.close import verify_citations
from tools.gpu_lab.learning_net.log import finish_probe, open_probe
from tools.gpu_lab.prepare import DATA_ROOT

MODULE = Path(__file__)
PROBE_ID = "speech_rank_close"
QUESTION = "Are speech-named seconds the ones a later game fails to rank?"

CITATIONS = (
    {
        "probe_id": "speech_rank",
        "folder": "20261023T043553Z_speech_rank",
        "result_sha256": "543acadd66206d4e2ab838e69ca4fcc337009048789af28837196f696a818466",
        "used_for_reading": True,
    },
)


def speech_reading(rows: list[dict]) -> dict:
    later = [row for row in rows if row["role"] == "develop"]
    speech_ranks_worse = []
    for row in later:
        speech = row["auc_by_group"]["Speech"]
        music = row["auc_by_group"]["Music"]
        if speech is None or music is None:
            continue
        if speech < music:
            speech_ranks_worse.append({"session": row["session"], "speech_auc": speech, "music_auc": music})
    return {
        "later_games_where_speech_ranks_worse_than_music": speech_ranks_worse,
        "speech_to_text_opened": bool(speech_ranks_worse),
        "speech_to_text_started": False,
        "october_may_choose_cutoff": False,
        "need_json_rewritten": False,
    }


def run(root: Path = DATA_ROOT) -> dict:
    need_path = root / "NEED.json"
    parameters = {
        "citations": [dict(item) for item in CITATIONS],
        "speech_to_text_started": False,
        "need_json_rewritten": False,
        "need_json_sha256": sha256_file(need_path) if need_path.is_file() else None,
        "october_may_choose_cutoff": False,
    }
    folder = open_probe(PROBE_ID, QUESTION, parameters, MODULE)
    checked = verify_citations(root / "learning_net", CITATIONS)
    used = next(item for item in checked if item["used_for_reading"])
    ranked = json.loads(Path(used["result_path"]).read_text(encoding="utf-8"))
    reading = speech_reading(ranked["rows"])
    result = {
        "probe_id": PROBE_ID,
        "citations": checked,
        "reading": reading,
        "floors": ranked["floors"],
        "need_json_rewritten": False,
        "need_json_sha256": parameters["need_json_sha256"],
        "speech_to_text_started": False,
    }
    print(f"  speech_to_text_opened {reading['speech_to_text_opened']}", flush=True)
    finish_probe(folder, PROBE_ID, QUESTION, parameters, result, MODULE)
    return result
