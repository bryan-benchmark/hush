"""Windows lab paths and environment.

Large datasets stay outside Git. Override with OHUSH_DATA_ROOT.
"""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_DATA_ROOT = Path(r"C:\OHushData")
FALLBACK_DATA_ROOT = Path.home() / "OHushData"

SUBDIRS = (
    "inbox",
    "authorized_sources",
    "receipts",
    "indexes",
    "work",
    "quarantine",
    "channel_recipes",
    "schedules",
    "farm",
    "work/capture",
    "work/sessions",
    "work/logs",
)

ALLOWED_RIGHTS = frozenset({"authorized", "test_public"})
BLOCKED_RIGHTS = frozenset({"unknown", "unauthorized", "pending"})

SOURCE_KINDS = frozenset({"streamers", "ota_antenna"})
MEDIA_MODES = frozenset({"av", "audio"})

DEFAULT_STREAMERS_PACKAGE = "ar.tvplayer.tv"
DEFAULT_BLUESTACKS_PLAYER = Path(r"C:\Program Files\BlueStacks_nxt\HD-Player.exe")
DEFAULT_BLUESTACKS_ADB = Path(r"C:\Program Files\BlueStacks_nxt\HD-Adb.exe")
DEFAULT_BLUESTACKS_CONF = Path(r"C:\ProgramData\BlueStacks_nxt\bluestacks.conf")

CAPTURE_SESSIONS_INDEX = "capture_sessions.jsonl"
INSTANCE_REGISTRY_NAME = "instances.json"
SCHEDULE_NAME = "jobs.json"
OTA_CONFIG_NAME = "ota.json"
ACTIVE_LOCKS_NAME = "active_locks.json"


def data_root() -> Path:
    env = os.environ.get("OHUSH_DATA_ROOT")
    if env:
        return Path(env)
    if DEFAULT_DATA_ROOT.is_dir():
        return DEFAULT_DATA_ROOT
    return FALLBACK_DATA_ROOT


def ensure_data_layout(root: Path | None = None) -> Path:
    root = root or data_root()
    root.mkdir(parents=True, exist_ok=True)
    for name in SUBDIRS:
        (root / name).mkdir(parents=True, exist_ok=True)
    return root


def farm_dir(root: Path | None = None) -> Path:
    root = ensure_data_layout(root)
    return root / "farm"


def instance_registry_path(root: Path | None = None) -> Path:
    return farm_dir(root) / INSTANCE_REGISTRY_NAME


def schedule_path(root: Path | None = None) -> Path:
    return ensure_data_layout(root) / "schedules" / SCHEDULE_NAME


def channel_recipes_dir(root: Path | None = None) -> Path:
    return ensure_data_layout(root) / "channel_recipes"


def capture_sessions_index_path(root: Path | None = None) -> Path:
    return ensure_data_layout(root) / "indexes" / CAPTURE_SESSIONS_INDEX


def ota_config_path(root: Path | None = None) -> Path:
    return farm_dir(root) / OTA_CONFIG_NAME


def active_locks_path(root: Path | None = None) -> Path:
    return farm_dir(root) / ACTIVE_LOCKS_NAME
