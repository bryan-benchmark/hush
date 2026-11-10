"""Host resource pressure for farm loop decisions."""

from __future__ import annotations

import ctypes
import shutil
from dataclasses import dataclass
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
