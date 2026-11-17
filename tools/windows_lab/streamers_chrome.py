"""Read Streamers player chrome for channel identity (no retune)."""

from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import ensure_data_layout
from .instances import adb, adb_bytes, connect_adb, get_instance

# Middle of 1600x900 player — shows chrome without opening menus.
CHROME_TAP = (800, 450)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_dump_texts(xml: str) -> list[str]:
    return re.findall(r'text="([^"]{1,120})"', xml)


def read_playing_channel(
    instance_id: str = "Nougat32",
    *,
    root: Path | None = None,
    tap_for_chrome: bool = True,
) -> dict[str, Any]:
    """Tap to reveal chrome (optional), dump UI + screenshot, extract a channel hint.

    Accessibility text is often empty on the player; we still save a still for OCR later
    and return any texts that mention FHD / channel-like rows.
    """
    root = ensure_data_layout(root)
    instance = get_instance(instance_id, root)
    connect_adb(instance)
    if tap_for_chrome:
        adb(instance, ["shell", "input", "tap", str(CHROME_TAP[0]), str(CHROME_TAP[1])], timeout=10)
        time.sleep(0.8)

    adb(instance, ["shell", "uiautomator", "dump", "/sdcard/ohush_chrome.xml"], timeout=20)
    code, xml_out = adb(instance, ["shell", "cat", "/sdcard/ohush_chrome.xml"], timeout=20)
    xml = xml_out if code == 0 else ""
    texts = _parse_dump_texts(xml)

    shot_dir = root / "work" / "chrome_peek"
    shot_dir.mkdir(parents=True, exist_ok=True)
    shot = shot_dir / f"chrome_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.png"
    code_b, png, err = adb_bytes(instance, ["exec-out", "screencap", "-p"], timeout=20)
    if code_b == 0 and len(png) > 100:
        sig = png.find(b"\x89PNG")
        if sig > 0:
            png = png[sig:]
        shot.write_bytes(png)
    else:
        shot = None

    # Heuristics from chrome texts when present.
    channel_guess = None
    program_guess = None
    for t in texts:
        if re.search(r"\bFHD\b|\bFPS\b|\bSTEREO\b", t, re.I):
            continue
        if "TV guide" in t or t in {"History", "Clear"}:
            continue
        if "|" in t and len(t) > 8:
            program_guess = t
            left = t.split("|", 1)[0].strip()
            if left:
                channel_guess = left
        elif re.match(r"^\d{1,5}$", t.strip()):
            channel_guess = channel_guess or f"CH_{t.strip()}"

    player_chrome = any(
        x in (xml or "") or any(x in t for t in texts) for x in ("FHD", "TV guide", "History")
    ) or bool(shot)

    return {
        "ok": True,
        "instance_id": instance_id,
        "checked_utc": _now(),
        "channel_guess": channel_guess,
        "program_guess": program_guess,
        "texts": texts[:40],
        "player_chrome_hint": player_chrome,
        "screenshot": str(shot) if shot else None,
        "note": (
            "Use channel_guess when non-null; otherwise keep ON_AIR_CONTINUE and "
            "inspect screenshot. Accessibility is often empty on fullscreen player."
        ),
        "screencap_error": err if code_b != 0 else None,
    }
