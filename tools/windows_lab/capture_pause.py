"""Owner pause for TV capture — farm_loop + desk honor this flag.

Pause:  python -m tools.windows_lab.capture_pause on --why "granularity probe"
Resume: python -m tools.windows_lab.capture_pause off
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import ensure_data_layout
from .coverage_farm import indexes_dir

FLAG_NAME = "capture_pause.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def flag_path(root: Path | None = None) -> Path:
    return indexes_dir(ensure_data_layout(root)) / FLAG_NAME


def is_paused(root: Path | None = None) -> dict[str, Any]:
    path = flag_path(root)
    if not path.is_file():
        return {"active": False, "path": str(path)}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"active": False, "path": str(path), "error": "bad_json"}
    return {
        "active": bool(data.get("active")),
        "why": data.get("why"),
        "set_utc": data.get("set_utc"),
        "path": str(path),
        **{k: v for k, v in data.items() if k not in {"active", "why", "set_utc"}},
    }


def set_paused(active: bool, *, why: str = "", root: Path | None = None) -> dict[str, Any]:
    root = ensure_data_layout(root)
    path = flag_path(root)
    if not active:
        if path.is_file():
            path.unlink()
        return {"active": False, "cleared_utc": _now(), "path": str(path)}
    payload = {
        "active": True,
        "why": why or "owner pause — no TV record until capture_pause off",
        "set_utc": _now(),
        "resume": "python -m tools.windows_lab.capture_pause off",
        "then": "re-enable Nougat32 + Nougat32_1 and launch when ready for 2-stream capture",
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="Pause / resume TV capture for farm+desk")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    on = sub.add_parser("on", help="Pause all new TV recording")
    on.add_argument("--why", default="granularity / label compute focus")
    on.add_argument("--stop-instances", action="store_true", help="Disable+stop running BlueStacks")
    sub.add_parser("off", help="Clear pause flag (does not auto-launch BlueStacks)")
    args = p.parse_args(argv)
    if args.cmd == "status":
        print(json.dumps(is_paused(), indent=2))
        return 0
    if args.cmd == "on":
        out = set_paused(True, why=args.why)
        if args.stop_instances:
            from .instances import list_running_engines, stop_bluestacks, upsert_instance

            stopped = []
            for eng in list_running_engines():
                upsert_instance(eng, {"enabled": False})
                stopped.append(stop_bluestacks(eng, hard=True))
            out["stopped"] = stopped
        print(json.dumps(out, indent=2, default=str))
        return 0
    if args.cmd == "off":
        print(json.dumps(set_paused(False), indent=2))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
