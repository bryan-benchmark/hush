"""Write the Bridge 0 eligibility mask and the causal-window ceilings.

This step does not train. It refuses to run when a sealed holdout is present,
and it reports that embeddings are blocked until the recordings are restored.
"""

from __future__ import annotations

import json
from pathlib import Path

from experiments.ledger import RECORDINGS, sha256_file

from tools.gpu_lab.eligibility import build_masks
from tools.gpu_lab.ladder import delay_ceiling, pairs
from tools.gpu_lab.splits import (
    CALIBRATE,
    CONTROL,
    DEVELOP,
    OUT_OF_SCOPE,
    TNF,
    TRAIN,
    WINDOW_S,
)

DATA_ROOT = Path(r"C:\OHushData\gpu_lab")


def _role(session: str) -> str:
    if session in TRAIN:
        return "train"
    if session in CALIBRATE:
        return "calibrate"
    if session in DEVELOP:
        return "develop"
    if session in CONTROL:
        return "control"
    if session in OUT_OF_SCOPE:
        return "out_of_scope"
    raise RuntimeError(f"{session} is not in the Bridge 0 split")


def recording_status(sessions: list[str]) -> list[dict]:
    rows = []
    for session in sessions:
        matches = sorted(RECORDINGS.glob(f"*/{session}")) if RECORDINGS.exists() else []
        session_json = matches[0] / "session.json" if len(matches) == 1 else None
        rows.append(
            {
                "session": session,
                "present": session_json is not None and session_json.is_file(),
                "session_json_sha256": sha256_file(session_json) if session_json and session_json.is_file() else None,
            }
        )
    return rows


def build_report() -> dict:
    sessions = list(TRAIN + CALIBRATE + DEVELOP + CONTROL + OUT_OF_SCOPE)
    masks = build_masks(sessions)
    for mask in masks:
        mask["role"] = _role(mask["session"])
    tnf = next(mask for mask in masks if mask["session"] == TNF)
    commercials = pairs(tnf, "verified_commercial")
    recordings = recording_status(sessions)
    return {
        "id": "BRIDGE0_ELIGIBILITY",
        "sessions": masks,
        "tnf_delay_ceiling": [delay_ceiling(commercials, window) for window in WINDOW_S],
        "recordings": recordings,
        "recordings_ready": all(row["present"] for row in recordings if row["session"] in TRAIN + CALIBRATE + DEVELOP),
        "next": "restore recordings with scripts/restore_from_gcs.py, then cache past-only AST windows",
    }


def write_report(report: dict, root: Path = DATA_ROOT) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / "eligibility.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return path
