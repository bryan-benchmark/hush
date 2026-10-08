"""Dataset roles. Holdout audio may be detected. It must not be shown while tuning."""

from __future__ import annotations

import json

import ledger

DATASETS_PATH = ledger.GOLD / "DATASETS_V1.json"
SEAL = "HOLDOUT_V1"


def load_datasets() -> dict:
    return json.loads(DATASETS_PATH.read_text(encoding="utf-8"))


def role_of(session: str, datasets: dict | None = None) -> str:
    data = datasets or load_datasets()
    row = (data.get("sessions") or {}).get(session) or {}
    return str(row.get("role") or data.get("default_role") or "dev")


def reason_of(session: str, datasets: dict | None = None) -> str | None:
    data = datasets or load_datasets()
    row = (data.get("sessions") or {}).get(session) or {}
    return row.get("reason")


def reviewable(session: str, datasets: dict | None = None) -> bool:
    """Sessions a person may inspect while tuning."""
    return role_of(session, datasets) == "dev"
