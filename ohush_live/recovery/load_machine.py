"""Load a Machine implementation from an isolated code root without touching Exp*.

Clears ``ohush_live*`` modules and prefers ``code_root`` on ``sys.path``.
Call once per process, or use a subprocess per snapshot for paired runs.
"""

from __future__ import annotations

import sys
from pathlib import Path


def _purge_ohush_live() -> None:
    for key in list(sys.modules):
        if key == "ohush_live" or key.startswith("ohush_live."):
            del sys.modules[key]


def load_machine(code_root: Path, *, alias: str = "snapshot"):
    """Import Machine from ``{code_root}/ohush_live/state.py``."""
    del alias  # reserved for logging / future package aliasing
    code_root = Path(code_root).resolve()
    state_path = code_root / "ohush_live" / "state.py"
    if not state_path.is_file():
        raise FileNotFoundError(state_path)
    _purge_ohush_live()
    inserted = str(code_root)
    sys.path.insert(0, inserted)
    try:
        from ohush_live.state import Machine  # type: ignore

        return Machine
    finally:
        if sys.path and sys.path[0] == inserted:
            sys.path.pop(0)
