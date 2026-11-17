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
            "Fleet = Nougat32 clones only (same Android SKU). Clone in Multi-Instance Manager, "
            "then `instances discover`. Audio = process-PID loopback of each HD-Player "
            "(no VB-Cable required). Hot concurrent count is set by progressive-capacity lag, "
            "not by how many clones sit ready."
        ),
    }


def write_setup_checklist(root: Path | None = None) -> Path:
    ensure_data_layout(root)
    path = farm_dir(root) / "MULTI_INSTANCE_SETUP.md"
    report = isolation_report(root)
    body = f"""# Multi-instance Streamers setup

Updated: {report["checked_utc"]}

## Goal

**Ready fleet:** aim for ~**10** **Nougat32** clones (logged in via clone disk; keep extras stopped).
**Hot concurrent:** add one-at-a-time with `progressive-capacity --step N` until lag fails (start desk at 2).

**Tiramisu64 is retired** from capture (`enabled: false`). Do not use it as stream 3 — clone Nougat instead.

## Audio (one rule)

Every take: resolve that instance’s `HD-Player` PID → **process loopback WAV**.
No shared speaker bar. No extra VB-Cable for stream 3+.

```powershell
python -m tools.windows_lab process-loopback probe
```

## Steps

1. In **BlueStacks Multi-Instance Manager**, clone `Nougat32` → `Nougat32_1`, `Nougat32_2`, … (stop source first).
2. Discover + upsert (`audio_capture=process`):

```powershell
python -m tools.windows_lab instances discover
python -m tools.windows_lab instances upsert --instance Nougat32 --audio-capture process
python -m tools.windows_lab instances upsert --instance Nougat32_1 --adb-port 5565 --audio-capture process
```

3. One-time Salvation login on each new clone (`salvation login --instance …`) until home/guide.
4. Measure before raising desk max:

```powershell
python -m tools.windows_lab progressive-capacity --step 2 --minutes 2
python -m tools.windows_lab progressive-capacity --step 3 --minutes 2
```

5. Set `OHUSH_DESK_MAX_STREAMS` to the highest `N_ok` verdict; keep extra clones powered off until needed.
6. Tile windows when operating: `python -m tools.windows_lab windows layout --mode auto`.

## Current report snapshot

```json
{json.dumps(report, indent=2)}
```
"""
    path.write_text(body, encoding="utf-8")
    return path


def default_window_title(instance_id: str) -> str:
    """BlueStacks Multi-Instance titles: primary + 'App Player N' for clones."""
    iid = str(instance_id or "")
    if iid == "Nougat32":
        return "BlueStacks App Player"
    if iid.startswith("Nougat32_"):
        suffix = iid.split("_", 1)[1]
        return f"BlueStacks App Player {suffix}"
    # Other engines: best-effort unique label for PID resolve.
    return f"BlueStacks App Player ({iid})"


def seed_second_instance_stub(root: Path | None = None) -> dict[str, Any]:
    """Register any discovered BlueStacks engines not yet in the farm registry."""
    discovered = discover_bluestacks_instances()
    known = {r["id"] for r in list_instances(root)}
    added = []
    repaired = []
    for row in discovered:
        iid = str(row["id"])
        title = default_window_title(iid)
        patch = {
            "engine": iid,
            "adb_port": row.get("adb_port"),
            "adb_serial": row.get("adb_serial"),
            "window_title": title,
            "audio_capture": "process",
            "loopback_device": "",  # optional fallback; process-PID loopback is primary
            "audio_route_note": (
                "Process-PID loopback (no VB-Cable). window_title must match HD-Player exactly."
            ),
        }
        if iid not in known:
            # Primary on by default; clones stay off until capacity/desk opts them in.
            patch["enabled"] = iid == "Nougat32"
            upsert_instance(iid, patch, root=root)
            added.append(iid)
            continue
        # Repair wrong/shared titles or missing process-loopback (breaks PID audio).
        # Do not flip enabled — desk/capacity own that.
        try:
            from .instances import get_instance

            cur = get_instance(iid, root)
            cur_title = str(cur.get("window_title") or "")
            need = False
            if cur_title != title:
                need = True
            if str(cur.get("audio_capture") or "") not in (
                "process",
                "process_loopback",
                "pid",
                "auto",
            ):
                need = True
            if need:
                upsert_instance(iid, patch, root=root)
                repaired.append(iid)
        except Exception:  # noqa: BLE001
            pass
    path = write_setup_checklist(root)
    return {
        "added": added,
        "repaired": repaired,
        "checklist": str(path),
        "discovered": discovered,
    }


# refresh helper used by agents after fleet changes
def refresh_checklist(root: Path | None = None) -> Path:
    return write_setup_checklist(root)


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="Multi-instance isolation helpers")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("report")
    sub.add_parser("write-checklist")
    sub.add_parser("sync-discovered")
    sub.add_parser("route-audio", help="PID-route HD-Player windows to registered loopbacks (SoundVolumeView)")
    sub.add_parser("verify-audio", help="Snapshot BlueStacks render devices from SoundVolumeView")

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
    if args.cmd == "route-audio":
        from .route_instance_audio import route_registered

        print(json.dumps(route_registered(), indent=2))
        return 0
    if args.cmd == "verify-audio":
        from .route_instance_audio import verify_routes

        print(json.dumps(verify_routes(), indent=2))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
