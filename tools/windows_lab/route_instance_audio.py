"""Route each HD-Player window to its registered loopback device via SoundVolumeView.

Windows per-app defaults key off the exe path, so two HD-Player.exe instances must be
routed carefully:

1. Clear sticky exe-level defaults (DefaultRenderDevice) — they force every new
   HD-Player onto one device.
2. Launch primary with system default MZ-631M; launch clone with default MG248
   (existing sessions do not follow SetDefault — restart to rebind).
3. Prefer PID SetAppDefault only after that cold bind; never sticky-set HD-Player.exe.

Requires: C:\\OHushData\\tools\\SoundVolumeView\\SoundVolumeView.exe
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import time
from pathlib import Path
from typing import Any

from .config import farm_dir
from .instances import list_instances

SVV = Path(r"C:\OHushData\tools\SoundVolumeView\SoundVolumeView.exe")

# Command-Line Friendly IDs from SoundVolumeView on this PC
DEVICE_FRIENDLY = {
    "MZ-631M": r"MZ-631M  USB Speaker Bar\Device\Speakers\Render",
    "MG248": r"AMD High Definition Audio Device\Device\1 - MG248\Render",
}


def _svv(*args: str) -> None:
    if not SVV.is_file():
        raise FileNotFoundError(f"SoundVolumeView missing: {SVV}")
    subprocess.run([str(SVV), *args], check=False)


def _hd_players() -> list[dict[str, Any]]:
    ps = (
        "Get-Process HD-Player -ErrorAction SilentlyContinue | "
        "Select-Object Id, MainWindowTitle | ConvertTo-Json"
    )
    raw = subprocess.check_output(
        ["powershell", "-NoProfile", "-Command", ps],
        text=True,
        errors="ignore",
    ).strip()
    if not raw:
        return []
    data = json.loads(raw)
    if isinstance(data, dict):
        data = [data]
    return [{"pid": int(r["Id"]), "title": str(r.get("MainWindowTitle") or "")} for r in data]


def _match_device_key(loopback: str) -> str | None:
    for key in DEVICE_FRIENDLY:
        if key.lower() in loopback.lower():
            return key
    return None


def route_registered(*, settle_sec: float = 1.0) -> dict[str, Any]:
    players = _hd_players()
    rows = list_instances()
    applied = []
    errors = []
    for inst in rows:
        if not inst.get("enabled", True):
            continue
        title = str(inst.get("window_title") or "")
        loop = str(inst.get("loopback_device") or "")
        key = _match_device_key(loop)
        if not key:
            errors.append({"id": inst["id"], "error": f"no device map for loopback={loop!r}"})
            continue
        # Exact title only — "BlueStacks App Player" must not match "... Player 1".
        hit = next((p for p in players if title and p["title"] == title), None)
        if hit is None:
            errors.append({"id": inst["id"], "error": f"no HD-Player for title={title!r}", "players": players})
            continue
        friendly = DEVICE_FRIENDLY[key]
        _svv("/SetAppDefault", friendly, "all", str(hit["pid"]))
        applied.append(
            {
                "id": inst["id"],
                "pid": hit["pid"],
                "title": hit["title"],
                "loopback": loop,
                "device_key": key,
                "friendly": friendly,
            }
        )
    if settle_sec:
        time.sleep(settle_sec)
    return {
        "ok": bool(applied) and not errors,
        "svv": str(SVV),
        "applied": applied,
        "errors": errors,
        "players": players,
    }


def verify_routes() -> dict[str, Any]:
    if not SVV.is_file():
        raise FileNotFoundError(str(SVV))
    out = farm_dir() / "soundvolumeview_snapshot.csv"
    _svv("/scomma", str(out))
    time.sleep(0.8)
    rows = []
    with out.open(encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            if r.get("Name") == "BlueStacks" and r.get("Direction") == "Render":
                rows.append(
                    {
                        "pid": r.get("Process ID"),
                        "device": r.get("Device Name"),
                        "title": r.get("Window Title"),
                    }
                )
    return {"ok": True, "bluestacks_render": rows, "csv": str(out)}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("cmd", choices=["route", "verify", "route-verify"])
    args = p.parse_args(argv)
    if args.cmd in ("route", "route-verify"):
        print(json.dumps(route_registered(), indent=2))
    if args.cmd in ("verify", "route-verify"):
        print(json.dumps(verify_routes(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
