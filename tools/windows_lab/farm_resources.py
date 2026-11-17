"""Host resource pressure for farm loop decisions."""

from __future__ import annotations

import ctypes
import shutil
import subprocess
from typing import Any


# Second BlueStacks wants headroom; label+record on one instance needs less.
MIN_FREE_GB_FOR_RECORD = 4.0
MIN_FREE_GB_FOR_SECOND_INSTANCE = 8.0
MIN_FREE_GB_FOR_LABEL = 3.0


class _MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def memory_snapshot() -> dict[str, Any]:
    stat = _MEMORYSTATUSEX()
    stat.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
        usage = shutil.disk_usage("C:\\")
        return {
            "ok": False,
            "error": "GlobalMemoryStatusEx failed",
            "disk_free_gb": round(usage.free / (1024**3), 2),
        }
    total = stat.ullTotalPhys / (1024**3)
    avail = stat.ullAvailPhys / (1024**3)
    usage = shutil.disk_usage("C:\\")
    return {
        "ok": True,
        "total_gb": round(total, 2),
        "avail_gb": round(avail, 2),
        "load_pct": int(stat.dwMemoryLoad),
        "disk_free_gb": round(usage.free / (1024**3), 2),
        "allow_record": avail >= MIN_FREE_GB_FOR_RECORD,
        "allow_label": avail >= MIN_FREE_GB_FOR_LABEL,
        "allow_second_instance": avail >= MIN_FREE_GB_FOR_SECOND_INSTANCE,
        "thresholds_gb": {
            "record": MIN_FREE_GB_FOR_RECORD,
            "label": MIN_FREE_GB_FOR_LABEL,
            "second_instance": MIN_FREE_GB_FOR_SECOND_INSTANCE,
        },
    }


def _gpu_snapshot() -> dict[str, Any]:
    """Best-effort NVIDIA util + VRAM via nvidia-smi (fast CSV query)."""
    try:
        out = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
            text=True,
            timeout=2.5,
            stderr=subprocess.DEVNULL,
        )
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
        return {"ok": False, "error": str(exc)}
    line = (out or "").strip().splitlines()[0] if (out or "").strip() else ""
    parts = [p.strip() for p in line.split(",")]
    if len(parts) < 3:
        return {"ok": False, "error": f"bad nvidia-smi: {line!r}"}
    try:
        util = float(parts[0])
        used_mib = float(parts[1])
        total_mib = float(parts[2])
        temp_c = float(parts[3]) if len(parts) > 3 and parts[3] != "" else None
    except ValueError:
        return {"ok": False, "error": f"parse nvidia-smi: {line!r}"}
    vram_pct = round(100.0 * used_mib / total_mib, 1) if total_mib > 0 else None
    return {
        "ok": True,
        "util_pct": round(util, 1),
        "vram_used_gb": round(used_mib / 1024.0, 2),
        "vram_total_gb": round(total_mib / 1024.0, 2),
        "vram_pct": vram_pct,
        "temp_c": round(temp_c, 0) if temp_c is not None else None,
    }


_HOST_UTIL_CACHE: dict[str, Any] = {"t": 0.0, "blob": None}
_HOST_UTIL_TTL_S = 2.0


def host_util_snapshot(*, force: bool = False) -> dict[str, Any]:
    """CPU / RAM / GPU utilization for the label desk header (cached ~2s)."""
    import time

    now = time.monotonic()
    cached = _HOST_UTIL_CACHE.get("blob")
    if (
        not force
        and cached is not None
        and (now - float(_HOST_UTIL_CACHE.get("t") or 0.0)) < _HOST_UTIL_TTL_S
    ):
        return cached

    mem = memory_snapshot()
    cpu_pct = None
    try:
        import psutil

        # First sample after process start is always 0 with interval=None — warm once.
        cpu_pct = float(psutil.cpu_percent(interval=None))
        if cpu_pct == 0.0 and not _HOST_UTIL_CACHE.get("cpu_warmed"):
            cpu_pct = float(psutil.cpu_percent(interval=0.05))
            _HOST_UTIL_CACHE["cpu_warmed"] = True
        else:
            _HOST_UTIL_CACHE["cpu_warmed"] = True
    except Exception:  # noqa: BLE001
        cpu_pct = None
    gpu = _gpu_snapshot()
    ram_pct = mem.get("load_pct") if mem.get("ok") else None
    used_gb = None
    if mem.get("ok") and mem.get("total_gb") is not None and mem.get("avail_gb") is not None:
        used_gb = round(float(mem["total_gb"]) - float(mem["avail_gb"]), 2)
    bits = []
    if cpu_pct is not None:
        bits.append(f"CPU {cpu_pct:.0f}%")
    if ram_pct is not None and used_gb is not None and mem.get("total_gb") is not None:
        bits.append(f"RAM {used_gb:g}/{float(mem['total_gb']):g}G")
    elif ram_pct is not None:
        bits.append(f"RAM {int(ram_pct)}%")
    if gpu.get("ok"):
        bits.append(f"GPU {float(gpu['util_pct']):.0f}%")
        if gpu.get("vram_used_gb") is not None and gpu.get("vram_total_gb") is not None:
            bits.append(f"VRAM {gpu['vram_used_gb']:g}/{gpu['vram_total_gb']:g}G")
        if gpu.get("temp_c") is not None:
            bits.append(f"{int(gpu['temp_c'])}°C")
    blob = {
        "ok": True,
        "cpu_pct": round(cpu_pct, 1) if cpu_pct is not None else None,
        "ram_pct": int(ram_pct) if ram_pct is not None else None,
        "ram_used_gb": used_gb,
        "ram_total_gb": mem.get("total_gb") if mem.get("ok") else None,
        "gpu": gpu,
        "plain": " · ".join(bits) if bits else "util —",
    }
    _HOST_UTIL_CACHE["t"] = now
    _HOST_UTIL_CACHE["blob"] = blob
    return blob
