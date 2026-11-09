"""Multi-instance / VB-Cable isolation helpers for parallel Streamers capture."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import ensure_data_layout, farm_dir
from .instances import crosstalk_check, discover_bluestacks_instances, list_instances, upsert_instance


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def isolation_report(root: Path | None = None) -> dict[str, Any]:
    rows = list_instances(root)
    streamers = [r for r in rows if r.get("source_kind", "streamers") == "streamers" and r.get("enabled", True)]
    pairs = []
    ok = True
    for i, a in enumerate(streamers):
        for b in streamers[i + 1 :]:
            check = crosstalk_check(a["id"], b["id"], root=root)
            pairs.append(check)
            if not check.get("ok"):
                ok = False
    discovered = discover_bluestacks_instances()
    return {
        "checked_utc": _now(),
        "ok": ok if len(streamers) > 1 else True,
        "enabled_streamers": [{"id": r["id"], "loopback_device": r.get("loopback_device")} for r in streamers],
        "pair_checks": pairs,
        "bluestacks_discovered": discovered,
        "guidance": (
            "Install VB-Audio Virtual Cable (one cable per concurrent instance). "
            "In each BlueStacks instance, route audio to that cable. "
            "Register with: python -m tools.windows_lab instances upsert "
            "--instance <EngineName> --adb-port <port> --loopback-device \"CABLE-N Input\". "
            "Clone engines in BlueStacks Multi-Instance Manager, then instances discover."
        ),
    }


def write_setup_checklist(root: Path | None = None) -> Path:
    ensure_data_layout(root)
    path = farm_dir(root) / "MULTI_INSTANCE_SETUP.md"
    report = isolation_report(root)
    body = f"""# Multi-instance Streamers setup

Updated: {report["checked_utc"]}

## Goal

Run 2–3 BlueStacks instances on different channels at once without audio crosstalk.

## Steps

1. Install **VB-Audio Virtual Cable** (or VoiceMeeter) — one virtual cable per concurrent instance.
2. Open **BlueStacks Multi-Instance Manager** and clone `Nougat32` (e.g. `Nougat32_1`, `Nougat32_2`).
3. Boot each instance once; note ADB ports via:

```powershell
python -m tools.windows_lab instances discover
```

4. In each instance, set host/Android audio output to its dedicated cable.
5. Register loopbacks:

```powershell
python -m tools.windows_lab instances upsert --instance Nougat32 --loopback-device "CABLE Input"
python -m tools.windows_lab instances upsert --instance Nougat32_1 --adb-port PORT --loopback-device "CABLE-2 Input" --window-title "BlueStacks"
```

6. Verify isolation:

```powershell
python -m tools.windows_lab instances crosstalk --a Nougat32 --b Nougat32_1
python -m tools.windows_lab multi-instance report
```

7. Schedule overlapping jobs on different `--instance` values.

## Current report snapshot

```json
{json.dumps(report, indent=2)}
```
"""
    path.write_text(body, encoding="utf-8")
    return path


def seed_second_instance_stub(root: Path | None = None) -> dict[str, Any]:
    """If a second BlueStacks engine exists, register it with a placeholder loopback."""
    discovered = discover_bluestacks_instances()
    known = {r["id"] for r in list_instances(root)}
    added = []
    for row in discovered:
        if row["id"] in known:
            continue
        upsert_instance(
            row["id"],
            {
                "engine": row["id"],
                "adb_port": row.get("adb_port"),
                "adb_serial": row.get("adb_serial"),
                "window_title": "BlueStacks App Player",
                "loopback_device": "",  # must be filled before parallel jobs
                "enabled": True,
                "audio_route_note": "Set a dedicated VB-Cable before enabling parallel capture.",
            },
            root=root,
        )
        added.append(row["id"])
    path = write_setup_checklist(root)
    return {"added": added, "checklist": str(path), "discovered": discovered}


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="Multi-instance isolation helpers")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("report")
    sub.add_parser("write-checklist")
    sub.add_parser("sync-discovered")

    args = p.parse_args(argv)
    if args.cmd == "report":
        print(json.dumps(isolation_report(), indent=2))
        return 0
    if args.cmd == "write-checklist":
        path = write_setup_checklist()
        print(json.dumps({"ok": True, "path": str(path)}, indent=2))
        return 0
    if args.cmd == "sync-discovered":
        print(json.dumps(seed_second_instance_stub(), indent=2))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
