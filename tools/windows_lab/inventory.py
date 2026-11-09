"""Read-only machine inventory for Node 01 (secrets redacted)."""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import NODE_ID, __version__
from .config import data_root


_SECRET_RE = re.compile(
    r"(api[_-]?key|secret|token|password|credential|authorization)=([^\s]+)",
    re.IGNORECASE,
)


def _redact(text: str) -> str:
    return _SECRET_RE.sub(r"\1=<redacted>", text)


def _run(cmd: list[str], timeout: float = 20.0) -> str | None:
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, timeout=timeout, text=True)
        return _redact(out.strip())
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return None


def _ps(script: str) -> str | None:
    return _run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            script,
        ]
    )


def collect() -> dict:
    root = data_root()
    free_gb = None
    total_gb = None
    try:
        usage = shutil.disk_usage(root.anchor if root.anchor else "C:\\")
        free_gb = round(usage.free / (1024**3), 2)
        total_gb = round(usage.total / (1024**3), 2)
    except OSError:
        pass

    nvidia = _run(["nvidia-smi", "--query-gpu=name,driver_version,memory.total", "--format=csv,noheader"])
    virt = _ps(
        "(Get-CimInstance Win32_Processor).VirtualizationFirmwareEnabled; "
        "(Get-CimInstance Win32_ComputerSystem).HypervisorPresent"
    )

    env_keys = sorted(
        k
        for k in os.environ
        if any(s in k.upper() for s in ("OHUSH", "PATH", "PYTHON", "VIRTUAL"))
    )
    env_safe = {k: ("<redacted>" if any(s in k.upper() for s in ("KEY", "SECRET", "TOKEN", "PASSWORD")) else os.environ.get(k, "")) for k in env_keys}
    # Never dump full PATH contents with credentials; truncate
    if "PATH" in env_safe and len(env_safe["PATH"]) > 200:
        env_safe["PATH"] = env_safe["PATH"][:200] + "…"

    return {
        "node_id": NODE_ID,
        "inventory_version": __version__,
        "collected_utc": datetime.now(timezone.utc).isoformat(),
        "hostname": platform.node(),
        "os": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
        },
        "python": {
            "executable": sys.executable,
            "version": sys.version.split()[0],
        },
        "cpu": _ps("(Get-CimInstance Win32_Processor | Select-Object -First 1).Name"),
        "ram_gb": _ps(
            "[math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory/1GB,2)"
        ),
        "gpu": nvidia or _ps("(Get-CimInstance Win32_VideoController).Name -join '; '"),
        "virtualization_notes": virt,
        "disk": {"root": str(root), "free_gb": free_gb, "total_gb": total_gb},
        "tools": {
            "git": _run(["git", "--version"]),
            "node": _run(["node", "--version"]),
            "obs": bool(
                Path(r"C:\Program Files\obs-studio\bin\64bit\obs64.exe").exists()
                or shutil.which("obs64")
            ),
            "bluestacks": bool(
                Path(r"C:\Program Files\BlueStacks_nxt\HD-Player.exe").exists()
                or Path(r"C:\Program Files\BlueStacks\HD-Player.exe").exists()
                or list(Path(r"C:\Program Files").glob("BlueStacks*/**/HD-Player.exe"))
            ),
        },
        "env_safe": env_safe,
    }


def main(argv: list[str] | None = None) -> int:
    report = collect()
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
