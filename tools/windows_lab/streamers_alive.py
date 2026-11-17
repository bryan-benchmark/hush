"""Detect Streamers down screens (e.g. Cloudflare 522) and recover.

Runs on each farm loop pass so a black error page does not sit idle for hours.
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import DEFAULT_STREAMERS_PACKAGE, ensure_data_layout
from .coverage_farm import indexes_dir
from .instances import adb, adb_bytes, connect_adb, get_instance, launch_bluestacks

PACKAGE = DEFAULT_STREAMERS_PACKAGE
MAIN = "ar.tvplayer.tv/.ui.MainActivity"

# UI / chrome text that means the player is dead (not a normal channel).
DOWN_PATTERNS = [
    re.compile(r"\berror\s+occurred\b", re.I),
    re.compile(r"\bcode\s*522\b", re.I),
    re.compile(r"\b522\b"),
    re.compile(r"\bconnection\s+timed?\s*out\b", re.I),
    re.compile(r"\btimed?\s*out\b", re.I),
    re.compile(r"\bcloudflare\b", re.I),
    re.compile(r"\bunable\s+to\s+connect\b", re.I),
    re.compile(r"\bno\s+internet\b", re.I),
    re.compile(r"\bnetwork\s+error\b", re.I),
    re.compile(r"\bsomething\s+went\s+wrong\b", re.I),
    re.compile(r"\bgo\s+to\s+cloud\b", re.I),
    re.compile(r"\bcheck\s+your\s+(network|connection|internet)\b", re.I),
    re.compile(r"\bno\s+connection\b", re.I),
    re.compile(r"\boffline\b", re.I),
    re.compile(r"\bretry\b", re.I),
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_texts(xml: str) -> list[str]:
    return re.findall(r'text="([^"]{1,160})"', xml or "")


def _activity(instance: dict[str, Any]) -> str:
    code, out = adb(instance, ["shell", "dumpsys", "window"], timeout=20)
    if code != 0:
        return ""
    for line in out.splitlines():
        if "mCurrentFocus=" in line:
            return line.strip()
    return ""


def _dump_xml(instance: dict[str, Any]) -> str:
    rc, out = adb(
        instance, ["shell", "uiautomator", "dump", "/sdcard/ohush_alive.xml"], timeout=20
    )
    # Match ui_dump contract: rc=0 with null-root is still a failed dump.
    if rc != 0 or "null root" in (out or "").lower() or "error" in (out or "").lower():
        return ""
    code, xml = adb(instance, ["shell", "cat", "/sdcard/ohush_alive.xml"], timeout=20)
    adb(instance, ["shell", "rm", "/sdcard/ohush_alive.xml"], timeout=10)
    return xml if code == 0 else ""


def _dark_frame_ratio(png: bytes) -> float | None:
    """Fraction of near-black pixels — 522 screens are a big dark panel."""
    try:
        from io import BytesIO

        from PIL import Image
    except ImportError:
        return None
    try:
        sig = png.find(b"\x89PNG")
        if sig > 0:
            png = png[sig:]
        im = Image.open(BytesIO(png)).convert("L")
        im.thumbnail((320, 180))
        pix = list(im.getdata())
        if not pix:
            return None
        dark = sum(1 for p in pix if p < 28)
        return round(dark / len(pix), 3)
    except Exception:  # noqa: BLE001
        return None


def probe_streamers_down(
    instance_id: str = "player 0",
    *,
    root: Path | None = None,
    save_shot: bool = True,
) -> dict[str, Any]:
    """Return down=True when Streamers shows a hard error screen."""
    root = ensure_data_layout(root)
    instance = get_instance(instance_id, root)
    connect_adb(instance)

    activity = _activity(instance)
    xml = _dump_xml(instance)
    texts = _parse_texts(xml)
    blob = "\n".join(texts)
    hits = [p.pattern for p in DOWN_PATTERNS if p.search(blob)]

    shot_path = None
    dark_ratio = None
    frame_score: dict[str, Any] | None = None
    if save_shot:
        code_b, png, _err = adb_bytes(instance, ["exec-out", "screencap", "-p"], timeout=20)
        if code_b == 0 and png and len(png) > 200:
            dark_ratio = _dark_frame_ratio(png)
            shot_dir = root / "work" / "streamers_alive"
            shot_dir.mkdir(parents=True, exist_ok=True)
            shot_path = shot_dir / f"alive_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.png"
            sig = png.find(b"\x89PNG")
            shot_path.write_bytes(png[sig:] if sig > 0 else png)
            try:
                from .frame_watch import freeze_score, heuristic_score

                frame_score = heuristic_score(shot_path)
                # Second snap ~1.2s later: frozen slate + any center blue = stuck spinner.
                time.sleep(1.2)
                code_b2, png2, _err2 = adb_bytes(
                    instance, ["exec-out", "screencap", "-p"], timeout=20
                )
                if code_b2 == 0 and png2 and len(png2) > 200:
                    shot2 = shot_dir / (
                        f"alive_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_b.png"
                    )
                    sig2 = png2.find(b"\x89PNG")
                    shot2.write_bytes(png2[sig2:] if sig2 > 0 else png2)
                    score2 = heuristic_score(shot2)
                    fr = freeze_score(shot_path, shot2)
                    frame_score["freeze"] = fr
                    frame_score["score_b"] = {
                        "verdict": score2.get("verdict"),
                        "spinner": score2.get("spinner"),
                    }
                    soft_blue = int((frame_score.get("spinner") or {}).get("blue_count") or 0) >= 10
                    soft_blue2 = int((score2.get("spinner") or {}).get("blue_count") or 0) >= 10
                    if (
                        fr.get("frozen")
                        and (soft_blue or soft_blue2)
                        and frame_score.get("verdict") == "likely_playing"
                    ):
                        frame_score["verdict"] = "blue_spinner"
                        frame_score["picture_ok"] = False
                        frame_score["reasons"] = list(frame_score.get("reasons") or []) + [
                            "frozen_slate_with_center_blue"
                        ]
                    elif score2.get("verdict") in {
                        "blue_spinner",
                        "cloud_network_error",
                        "black_down",
                    }:
                        frame_score = score2
                        frame_score["freeze"] = fr
            except Exception as exc:  # noqa: BLE001
                frame_score = {"ok": False, "error": str(exc)}

    # Accessibility sometimes empty on WebView errors — dark panel + error-ish chrome.
    # Pure black with no text is often a splash/load frame after relaunch — soft signal only.
    chrome_hints = any(
        t for t in texts if re.search(r"\b(FHD|TV guide|History|Clear|Stereo)\b", t, re.I)
    )
    picture_verdict = str((frame_score or {}).get("verdict") or "")
    picture_down = picture_verdict in {
        "blue_spinner",
        "cloud_network_error",
        "black_down",
        "error_overlay",
        "buffering",
    }
    hard_down = bool(hits) or picture_down
    soft_dark = (
        bool(dark_ratio is not None and dark_ratio >= 0.85)
        and not chrome_hints
        and not texts
        and ("MainActivity" in activity or "tvplayer" in activity.lower())
    )
    down = hard_down
    reason = None
    if hits:
        reason = f"error_ui:{','.join(hits[:3])}"
    elif picture_down:
        reason = f"picture_{picture_verdict}"
    elif soft_dark:
        # Not counted as down by itself — caller may wait and re-probe.
        reason = f"soft_dark_loading:dark_ratio={dark_ratio}"

    out = {
        "ok": not down,
        "down": down,
        "soft_dark": soft_dark,
        "checked_utc": _now(),
        "instance_id": instance_id,
        "activity": activity,
        "hits": hits,
        "texts": texts[:30],
        "dark_ratio": dark_ratio,
        "screenshot": str(shot_path) if shot_path else None,
        "frame_score": frame_score,
        "picture_verdict": picture_verdict or None,
        "reason": reason or ("streamers playing / home" if not down else "unknown_down"),
    }
    _write_state(out, root)
    return out


def recover_streamers(
    instance_id: str = "player 0",
    *,
    root: Path | None = None,
    wait_s: float = 18.0,
) -> dict[str, Any]:
    """Force-stop Streamers and relaunch — clears stuck 522 / WebView errors."""
    root = ensure_data_layout(root)
    instance = get_instance(instance_id, root)
    connect_adb(instance)
    steps: list[dict[str, Any]] = []

    code, out = adb(instance, ["shell", "am", "force-stop", PACKAGE], timeout=20)
    steps.append({"op": "force-stop", "code": code, "out": (out or "")[:120]})
    time.sleep(1.2)

    # Prefer explicit activity; fall back to BlueStacks launchApp.
    code2, out2 = adb(
        instance,
        ["shell", "am", "start", "-n", MAIN],
        timeout=20,
    )
    steps.append({"op": "am_start", "code": code2, "out": (out2 or "")[:160]})
    if code2 != 0:
        launched = launch_bluestacks(instance, launch_app=True)
        steps.append({"op": "launch_bluestacks", "pid": launched.get("pid")})

    time.sleep(max(8.0, wait_s))
    after = probe_streamers_down(instance_id, root=root, save_shot=True)
    # Splash is often pure black with no accessibility text — wait once more.
    if after.get("soft_dark") and not after.get("down"):
        time.sleep(8.0)
        after = probe_streamers_down(instance_id, root=root, save_shot=True)
        steps.append({"op": "reprobe_after_splash", "soft_dark": after.get("soft_dark"), "down": after.get("down")})
    # Still hard-down → try one BACK + center tap to dismiss overlays, then probe.
    if after.get("down"):
        adb(instance, ["shell", "input", "keyevent", "4"], timeout=10)
        time.sleep(0.8)
        adb(instance, ["shell", "input", "tap", "800", "450"], timeout=10)
        time.sleep(2.0)
        after = probe_streamers_down(instance_id, root=root, save_shot=True)
        steps.append({"op": "back_and_tap", "down": after.get("down"), "reason": after.get("reason")})

    # Keep HD-Players tiled so recover does not leave windows stacked.
    try:
        from .window_layout import layout_windows

        lay = layout_windows(mode="auto", relaunch_stuck=False)
        steps.append(
            {
                "op": "windows_layout",
                "ok": bool(lay.get("ok")),
                "effective_mode": lay.get("effective_mode"),
            }
        )
    except Exception as exc:  # noqa: BLE001
        steps.append({"op": "windows_layout", "ok": False, "error": str(exc)})

    return {
        "ok": bool(after.get("ok")),
        "recovered": bool(after.get("ok")),
        "checked_utc": _now(),
        "steps": steps,
        "after": after,
    }


def ensure_streamers_alive(
    instance_id: str = "player 0",
    *,
    root: Path | None = None,
    recover: bool = True,
) -> dict[str, Any]:
    """Probe; if hard-down and recover=True, force relaunch once and re-probe."""
    probe = probe_streamers_down(instance_id, root=root)
    if probe.get("ok") or not recover:
        return {"ok": bool(probe.get("ok")), "probe": probe, "recovered": False}
    if not probe.get("down"):
        # soft_dark alone — not a recover trigger
        return {"ok": True, "probe": probe, "recovered": False, "note": "soft_dark_ignored"}
    recovery = recover_streamers(instance_id, root=root)
    return {
        "ok": bool(recovery.get("ok")),
        "probe": probe,
        "recovered": True,
        "recovery": recovery,
    }


def _write_state(row: dict[str, Any], root: Path | None) -> None:
    path = indexes_dir(root) / "farm_streamers_alive.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(row, indent=2) + "\n", encoding="utf-8")
    flag = indexes_dir(root) / "farm_streamers_down.flag"
    if row.get("down"):
        flag.write_text(
            f"STREAMERS DOWN\n{row.get('checked_utc')}\n{row.get('reason')}\n",
            encoding="utf-8",
        )
    elif flag.is_file():
        flag.unlink(missing_ok=True)

def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="Probe / recover Streamers down screens")
    p.add_argument("--instance", default="player 0")
    p.add_argument("--recover", action="store_true", help="Force-stop + relaunch if down")
    p.add_argument("--probe-only", action="store_true")
    args = p.parse_args(argv)
    if args.recover and not args.probe_only:
        out = ensure_streamers_alive(args.instance, recover=True)
    else:
        out = {"ok": True, "probe": probe_streamers_down(args.instance), "recovered": False}
        out["ok"] = bool(out["probe"].get("ok"))
    print(json.dumps(out, indent=2))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
