"""BlueStacks instance registry, launch helpers, and doctor checks."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import (
    DEFAULT_BLUESTACKS_ADB,
    DEFAULT_BLUESTACKS_CONF,
    DEFAULT_BLUESTACKS_PLAYER,
    DEFAULT_STREAMERS_PACKAGE,
    ensure_data_layout,
    instance_registry_path,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_registry() -> dict[str, Any]:
    """Seed registry for the Node 01 Nougat32 instance."""
    conf = _parse_bluestacks_conf(DEFAULT_BLUESTACKS_CONF)
    adb_port = int(conf.get("bst.instance.Nougat32.adb_port", "5555") or 5555)
    return {
        "updated_utc": _now(),
        "bluestacks_player": str(DEFAULT_BLUESTACKS_PLAYER),
        "bluestacks_adb": str(DEFAULT_BLUESTACKS_ADB),
        "max_concurrent_streamers": 3,
        "instances": {
            "Nougat32": {
                "source_kind": "streamers",
                "engine": "Nougat32",
                "adb_port": adb_port,
                "adb_serial": f"127.0.0.1:{adb_port}",
                "window_title": "BlueStacks App Player",
                "package": DEFAULT_STREAMERS_PACKAGE,
                "loopback_device": "MZ-631M",
                "audio_route_note": (
                    "Match Windows default playback. Node 01 originally used MG248 HDMI; "
                    "this PC currently defaults to MZ-631M USB speakers. "
                    "For parallel instances assign a dedicated VB-Cable per instance."
                ),
                "enabled": True,
            }
        },
    }


def _parse_bluestacks_conf(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        out[key.strip()] = val.strip().strip('"')
    return out


def load_registry(root: Path | None = None) -> dict[str, Any]:
    ensure_data_layout(root)
    path = instance_registry_path(root)
    if not path.is_file():
        reg = default_registry()
        save_registry(reg, root)
        return reg
    return json.loads(path.read_text(encoding="utf-8"))


def save_registry(reg: dict[str, Any], root: Path | None = None) -> Path:
    ensure_data_layout(root)
    path = instance_registry_path(root)
    reg = dict(reg)
    reg["updated_utc"] = _now()
    path.write_text(json.dumps(reg, indent=2), encoding="utf-8")
    return path


def list_instances(root: Path | None = None) -> list[dict[str, Any]]:
    reg = load_registry(root)
    rows = []
    for name, cfg in (reg.get("instances") or {}).items():
        row = {"id": name, **cfg}
        rows.append(row)
    return rows


def get_instance(instance_id: str, root: Path | None = None) -> dict[str, Any]:
    reg = load_registry(root)
    cfg = (reg.get("instances") or {}).get(instance_id)
    if not cfg:
        raise KeyError(f"unknown instance {instance_id!r}; known={list((reg.get('instances') or {}))}")
    return {"id": instance_id, **cfg, "_registry": reg}


def upsert_instance(instance_id: str, patch: dict[str, Any], root: Path | None = None) -> dict[str, Any]:
    reg = load_registry(root)
    instances = dict(reg.get("instances") or {})
    cur = dict(instances.get(instance_id) or {})
    cur.update(patch)
    cur.setdefault("source_kind", "streamers")
    cur.setdefault("package", DEFAULT_STREAMERS_PACKAGE)
    cur.setdefault("enabled", True)
    instances[instance_id] = cur
    reg["instances"] = instances
    save_registry(reg, root)
    return {"id": instance_id, **cur}


def _which_adb(reg: dict[str, Any] | None = None) -> str:
    reg = reg or load_registry()
    cand = Path(str(reg.get("bluestacks_adb") or DEFAULT_BLUESTACKS_ADB))
    if cand.is_file():
        return str(cand)
    found = shutil.which("adb")
    if found:
        return found
    raise FileNotFoundError("ADB not found (HD-Adb.exe or adb on PATH)")


def _run(cmd: list[str], timeout: float = 30.0) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        return int(proc.returncode), out.strip()
    except FileNotFoundError as e:
        return 127, str(e)
    except subprocess.TimeoutExpired:
        return 124, "timeout"


def adb(instance: dict[str, Any], args: list[str], timeout: float = 30.0) -> tuple[int, str]:
    reg = instance.get("_registry") or load_registry()
    adb_bin = _which_adb(reg)
    serial = str(instance.get("adb_serial") or f"127.0.0.1:{instance.get('adb_port', 5555)}")
    return _run([adb_bin, "-s", serial, *args], timeout=timeout)


def connect_adb(instance: dict[str, Any], timeout: float = 20.0) -> tuple[bool, str]:
    reg = instance.get("_registry") or load_registry()
    adb_bin = _which_adb(reg)
    serial = str(instance.get("adb_serial") or f"127.0.0.1:{instance.get('adb_port', 5555)}")
    code, out = _run([adb_bin, "connect", serial], timeout=timeout)
    ok = code == 0 and ("connected" in out.lower() or "already" in out.lower())
    return ok, out


def wait_for_adb(instance: dict[str, Any], seconds: float = 60.0) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        connect_adb(instance)
        code, out = adb(instance, ["shell", "echo", "ohush_ok"], timeout=10.0)
        if code == 0 and "ohush_ok" in out:
            return True
        time.sleep(2.0)
    return False


def launch_bluestacks(instance: dict[str, Any], *, launch_app: bool = True) -> dict[str, Any]:
    reg = instance.get("_registry") or load_registry()
    player = Path(str(reg.get("bluestacks_player") or DEFAULT_BLUESTACKS_PLAYER))
    if not player.is_file():
        raise FileNotFoundError(f"BlueStacks player missing: {player}")
    engine = str(instance.get("engine") or instance["id"])
    cmd = [str(player), "--instance", engine]
    if launch_app:
        package = str(instance.get("package") or DEFAULT_STREAMERS_PACKAGE)
        cmd.extend(["--cmd", "launchApp", "--package", package, "--source", "ohush_windows_lab"])
    proc = subprocess.Popen(cmd, cwd=str(player.parent))
    return {"pid": proc.pid, "cmd": cmd, "started_utc": _now()}


def window_titles() -> list[str]:
    code, out = _run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "Get-Process | Where-Object { $_.MainWindowTitle } | "
            "Select-Object -ExpandProperty MainWindowTitle",
        ],
        timeout=15.0,
    )
    if code != 0:
        return []
    return [line.strip() for line in out.splitlines() if line.strip()]


def find_window_title(pattern: str) -> str | None:
    needle = pattern.lower()
    for title in window_titles():
        if needle in title.lower():
            return title
    return None


def ffmpeg_path() -> str | None:
    return shutil.which("ffmpeg")


def doctor(instance_id: str | None = None, root: Path | None = None) -> dict[str, Any]:
    ensure_data_layout(root)
    reg = load_registry(root)
    targets = [instance_id] if instance_id else list((reg.get("instances") or {}).keys())
    checks: list[dict[str, Any]] = []

    player = Path(str(reg.get("bluestacks_player") or DEFAULT_BLUESTACKS_PLAYER))
    checks.append(
        {
            "name": "bluestacks_player",
            "ok": player.is_file(),
            "detail": str(player),
        }
    )
    try:
        adb_bin = _which_adb(reg)
        checks.append({"name": "adb", "ok": True, "detail": adb_bin})
    except FileNotFoundError as e:
        checks.append({"name": "adb", "ok": False, "detail": str(e)})
        adb_bin = None

    ff = ffmpeg_path()
    checks.append({"name": "ffmpeg", "ok": bool(ff), "detail": ff or "missing"})

    instance_reports = []
    for name in targets:
        try:
            inst = get_instance(name, root)
        except KeyError as e:
            instance_reports.append({"id": name, "ok": False, "error": str(e)})
            continue
        report: dict[str, Any] = {"id": name, "checks": []}
        report["checks"].append(
            {
                "name": "enabled",
                "ok": bool(inst.get("enabled", True)),
                "detail": inst.get("enabled", True),
            }
        )
        ok_conn, conn_out = (False, "adb unavailable")
        if adb_bin:
            ok_conn, conn_out = connect_adb(inst)
        report["checks"].append({"name": "adb_connect", "ok": ok_conn, "detail": conn_out})
        shell_ok = False
        shell_out = ""
        if ok_conn:
            code, shell_out = adb(inst, ["shell", "getprop", "ro.build.version.release"], timeout=10.0)
            shell_ok = code == 0 and bool(shell_out.strip())
        report["checks"].append({"name": "adb_shell", "ok": shell_ok, "detail": shell_out or "n/a"})

        package = str(inst.get("package") or DEFAULT_STREAMERS_PACKAGE)
        pkg_ok = False
        pkg_out = ""
        if shell_ok:
            code, pkg_out = adb(inst, ["shell", "pm", "path", package], timeout=15.0)
            pkg_ok = code == 0 and "package:" in pkg_out
        report["checks"].append(
            {"name": "streamers_package", "ok": pkg_ok, "detail": pkg_out or package}
        )

        title_pat = str(inst.get("window_title") or "BlueStacks")
        found = find_window_title(title_pat)
        report["checks"].append(
            {
                "name": "window_title",
                "ok": found is not None,
                "detail": found or f"no window matching {title_pat!r}",
            }
        )

        loopback = str(inst.get("loopback_device") or "")
        report["checks"].append(
            {
                "name": "loopback_device_configured",
                "ok": bool(loopback),
                "detail": loopback or "set loopback_device in farm/instances.json",
            }
        )
        report["ok"] = all(c["ok"] for c in report["checks"] if c["name"] != "window_title")
        # window may be down until launch; soft-fail only
        instance_reports.append(report)

    overall = all(c["ok"] for c in checks) and all(r.get("ok") for r in instance_reports)
    return {
        "checked_utc": _now(),
        "ok": overall,
        "global_checks": checks,
        "instances": instance_reports,
        "registry_path": str(instance_registry_path(root)),
    }


def crosstalk_check(
    instance_a: str,
    instance_b: str,
    *,
    root: Path | None = None,
) -> dict[str, Any]:
    """Static isolation check: loopback devices must differ for parallel capture."""
    a = get_instance(instance_a, root)
    b = get_instance(instance_b, root)
    da = str(a.get("loopback_device") or "").strip().lower()
    db = str(b.get("loopback_device") or "").strip().lower()
    distinct = bool(da and db and da != db)
    shared_hdmi = "mg248" in da or "mg248" in db or "hdmi" in da or "hdmi" in db
    return {
        "checked_utc": _now(),
        "instance_a": {"id": instance_a, "loopback_device": a.get("loopback_device")},
        "instance_b": {"id": instance_b, "loopback_device": b.get("loopback_device")},
        "distinct_loopbacks": distinct,
        "hdmi_shared_risk": shared_hdmi and not distinct,
        "ok": distinct,
        "guidance": (
            "OK: dedicated loopbacks."
            if distinct
            else "Assign distinct VB-Cable (or VoiceMeeter strip) per instance before parallel jobs."
        ),
    }


def discover_bluestacks_instances() -> list[dict[str, Any]]:
    conf = _parse_bluestacks_conf(DEFAULT_BLUESTACKS_CONF)
    found: dict[str, dict[str, Any]] = {}
    for key, val in conf.items():
        m = re.match(r"bst\.instance\.([^.]+)\.adb_port$", key)
        if m:
            name = m.group(1)
            found.setdefault(name, {"id": name, "engine": name})
            found[name]["adb_port"] = int(val)
            found[name]["adb_serial"] = f"127.0.0.1:{int(val)}"
    return list(found.values())


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="BlueStacks instance registry")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list")
    sub.add_parser("discover")
    d = sub.add_parser("doctor")
    d.add_argument("--instance")
    l = sub.add_parser("launch")
    l.add_argument("--instance", required=True)
    l.add_argument("--no-app", action="store_true")
    u = sub.add_parser("upsert")
    u.add_argument("--instance", required=True)
    u.add_argument("--adb-port", type=int)
    u.add_argument("--loopback-device")
    u.add_argument("--window-title")
    u.add_argument("--package")
    u.add_argument("--enabled", choices=("true", "false"))
    c = sub.add_parser("crosstalk")
    c.add_argument("--a", required=True)
    c.add_argument("--b", required=True)

    args = p.parse_args(argv)
    if args.cmd == "list":
        print(json.dumps({"instances": list_instances()}, indent=2))
        return 0
    if args.cmd == "discover":
        print(json.dumps({"discovered": discover_bluestacks_instances()}, indent=2))
        return 0
    if args.cmd == "doctor":
        report = doctor(args.instance)
        print(json.dumps(report, indent=2))
        return 0 if report.get("ok") else 1
    if args.cmd == "launch":
        inst = get_instance(args.instance)
        info = launch_bluestacks(inst, launch_app=not args.no_app)
        print(json.dumps({"ok": True, "launch": info}, indent=2))
        return 0
    if args.cmd == "upsert":
        patch: dict[str, Any] = {}
        if args.adb_port is not None:
            patch["adb_port"] = args.adb_port
            patch["adb_serial"] = f"127.0.0.1:{args.adb_port}"
        if args.loopback_device:
            patch["loopback_device"] = args.loopback_device
        if args.window_title:
            patch["window_title"] = args.window_title
        if args.package:
            patch["package"] = args.package
        if args.enabled is not None:
            patch["enabled"] = args.enabled == "true"
        row = upsert_instance(args.instance, patch)
        print(json.dumps({"ok": True, "instance": row}, indent=2))
        return 0
    if args.cmd == "crosstalk":
        report = crosstalk_check(args.a, args.b)
        print(json.dumps(report, indent=2))
        return 0 if report.get("ok") else 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
