"""Cite the five Wave 0 receipts and name the Wave 1 row they open.

This probe reads those result files. It does not embed audio, fit a cutoff,
score October again, or rewrite NEED.json.
"""

from __future__ import annotations

import json
from pathlib import Path

from experiments.ledger import sha256_file, sha256_text

from tools.gpu_lab.learning_net.log import LEDGER_PATH, finish_probe, open_probe
from tools.gpu_lab.prepare import DATA_ROOT

MODULE = Path(__file__)
PROBE_ID = "wave0_close"
QUESTION = "Which single Wave 1 row do the five Wave 0 receipts open?"

# Ledger hashes are the LF text of result.json. Windows wrote those files
# with CRLF, so a byte hash of the same file does not equal the ledger hash.
CITATIONS = (
    {
        "probe_id": "ranking",
        "folder": "20261023T004935Z_ranking",
        "result_sha256": "477406f08d314fb0d9e26cda97ba48b58997a4a27323b5ffdca82336560c6153",
        "used_for_reading": True,
    },
    {
        "probe_id": "repeat_map",
        "folder": "20261023T004946Z_repeat_map",
        "result_sha256": "ed22e9c72048acb369d0d61be64d78977d54d8c7105c35a96bfaaf5197c300c1",
        "used_for_reading": True,
    },
    {
        "probe_id": "failure_tags",
        "folder": "20261023T005012Z_failure_tags",
        "result_sha256": "a5ed48602b23def10c87b963964df03cd8d43a10752fd083b7e7ab81c7aca5fd",
        "used_for_reading": False,
        "unused_reason": "top1 counts under-counted repeated class winners; mean probabilities in that file stay valid",
    },
    {
        "probe_id": "failure_tags",
        "folder": "20261023T005224Z_failure_tags",
        "result_sha256": "84b7ebb6eb7b3f4fa06b29b93d7555164fbca11ce77b15adca60f81c9dc6e071",
        "used_for_reading": True,
    },
    {
        "probe_id": "boundaries",
        "folder": "20261023T005133Z_boundaries",
        "result_sha256": "0d56ee6a2c1703ac540ade822f693fb41dbc82ec7cb91f1cc61eed44fb93bc46",
        "used_for_reading": True,
    },
    {
        "probe_id": "joint_rule",
        "folder": "20261023T005214Z_joint_rule",
        "result_sha256": "cc5dba92c8977562fdd7895cacfefaff0b7c6470c255ea477ee23e42bde265ec",
        "used_for_reading": True,
    },
)

PLAN_ROWS = {
    "stay_on_these_vectors": "Stay on these vectors. A rule must keep every pre-October game at 0 program seconds, then survive October once.",
    "dasheng_base_ranking": "One frozen general-audio encoder, Dasheng-base first. Repeat the ranking probe on its vectors. Do not fine-tune it on three games.",
    "copy_matcher": "A copy-matcher whose coverage number is commercial seconds matched, with playback whenever there is no copy.",
    "one_named_sound": "A probe aimed at that sound, still locked on the pre-October games.",
    "boundary_cue": "A boundary cue as a separate measurement, not a mute policy, until it has its own false-accept count on program and on the zero-ad control.",
}


def verify_citations(root: Path, citations: tuple[dict, ...] = CITATIONS) -> list[dict]:
    checked = []
    for item in citations:
        path = root / "probes" / item["folder"] / "result.json"
        text = path.read_text(encoding="utf-8")
        content_sha256 = sha256_text(text)
        if content_sha256 != item["result_sha256"]:
            raise RuntimeError(f"{item['folder']} content hash {content_sha256} does not match the ledger hash {item['result_sha256']}")
        checked.append(
            {
                **item,
                "result_path": str(path),
                "content_sha256": content_sha256,
                "file_sha256": sha256_file(path),
            }
        )
    return checked


def wave0_reading(ranking: dict, repeat: dict, tags: dict, boundaries: dict, joint: dict) -> dict:
    """Map receipt fields onto the plan table.

    A later game is weak when its AUC sits below every pre-October game at
    that same window. The copy row opens when October commercial seconds meet
    the training copy bar and October program seconds do not. The sound row
    opens when a person has filled every listening note and the class head
    names one class on the hidden seconds. The boundary row opens when the
    predeclared gap is present at edges and absent on interior program seconds.
    """
    by_window = []
    weak_sessions: list[str] = []
    for window in (2.0, 5.0, 10.0):
        rows = [row for row in ranking["rows"] if row["window_s"] == window and row["auc"] is not None]
        floor = min(row["auc"] for row in rows if row["role"] in ("train", "calibrate"))
        below = [
            {"session": row["session"], "auc": row["auc"]}
            for row in rows
            if row["role"] == "develop" and row["auc"] < floor
        ]
        above = [
            {"session": row["session"], "auc": row["auc"]}
            for row in rows
            if row["role"] == "develop" and row["auc"] >= floor
        ]
        weak_sessions.extend(row["session"] for row in below)
        by_window.append(
            {
                "window_s": window,
                "pre_october_floor_auc": floor,
                "october_below_pre_october_floor": below,
                "october_at_or_above_pre_october_floor": above,
            }
        )
    commercial = repeat["october_commercial_copy_fraction"]["copy_fraction"]
    program_copy = repeat["october_program_false_copy_fraction"]["copy_fraction"]
    notes = [row.get("note") for row in tags.get("listen", [])]
    notes_filled = bool(notes) and all(note for note in notes)
    top1 = list(tags.get("hidden_program_top1") or [])
    program_gap = boundaries["program_interior"]["gap_fraction"]
    edge_gap = boundaries["edges"]["gap_fraction"]
    opened = {
        "stay_on_these_vectors": not weak_sessions,
        "dasheng_base_ranking": bool(weak_sessions),
        "copy_matcher": commercial is not None and program_copy == 0 and commercial > 0,
        "one_named_sound": notes_filled and len(top1) == 1,
        "boundary_cue": edge_gap > 0 and program_gap == 0,
    }
    names = [name for name, flag in opened.items() if flag]
    return {
        "ranking_against_pre_october_floor": by_window,
        "later_games_below_pre_october_floor": sorted(set(weak_sessions)),
        "copy_bar_cosine": repeat["copy_bar_cosine"],
        "october_commercial_copy_fraction": commercial,
        "october_program_false_copy_fraction": program_copy,
        "listen_notes_filled": notes_filled,
        "listen_clip_count": len(notes),
        "hidden_program_top1": top1[:2],
        "boundary_gap_fraction": {
            "edges": edge_gap,
            "program_interior": program_gap,
            "commercial_interior": boundaries["commercial_interior"]["gap_fraction"],
        },
        "boundary_median_dip_db": {
            "edges": boundaries["edges"]["median_dip_db"],
            "program_interior": boundaries["program_interior"]["median_dip_db"],
            "commercial_interior": boundaries["commercial_interior"]["median_dip_db"],
        },
        "joint_threshold": joint["threshold"],
        "joint_october_program_cut_s": joint["october_program_cut_s"],
        "joint_october_commercial_held_s": joint["october_commercial_held_s"],
        "joint_october_broken": joint["october_broken"],
        "joint_control_program_cut_s": joint["control"]["program_cut_s"],
        "rows_opened": opened,
        "opened": names,
        "one_next_build": names[0] if len(names) == 1 else None,
        "one_next_build_text": PLAN_ROWS[names[0]] if len(names) == 1 else None,
        "wave1_started": False,
        "need_json_rewritten": False,
    }


def _load_used(root: Path, checked: list[dict]) -> dict[str, dict]:
    loaded = {}
    for item in checked:
        if not item["used_for_reading"]:
            continue
        loaded[item["probe_id"]] = json.loads(Path(item["result_path"]).read_text(encoding="utf-8"))
    missing = {"ranking", "repeat_map", "failure_tags", "boundaries", "joint_rule"} - set(loaded)
    if missing:
        raise RuntimeError(f"wave0 close is missing receipts: {sorted(missing)}")
    return loaded


def run(root: Path = DATA_ROOT) -> dict:
    need_path = root / "NEED.json"
    parameters = {
        "citations": [dict(item) for item in CITATIONS],
        "need_json_rewritten": False,
        "need_json_sha256": sha256_file(need_path) if need_path.is_file() else None,
        "wave1_started": False,
        "october_may_choose_cutoff": False,
    }
    folder = open_probe(PROBE_ID, QUESTION, parameters, MODULE)
    checked = verify_citations(root / "learning_net")
    loaded = _load_used(root / "learning_net", checked)
    reading = wave0_reading(loaded["ranking"], loaded["repeat_map"], loaded["failure_tags"], loaded["boundaries"], loaded["joint_rule"])
    result = {
        "probe_id": PROBE_ID,
        "ledger_path": str(LEDGER_PATH),
        "citations": checked,
        "reading": reading,
        "need_json_rewritten": False,
        "need_json_sha256": parameters["need_json_sha256"],
        "wave1_started": False,
    }
    print(f"  opened rows {reading['opened']}", flush=True)
    finish_probe(folder, PROBE_ID, QUESTION, parameters, result, MODULE)
    return result
