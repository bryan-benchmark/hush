"""Sign Streamers into Salvation on a BlueStacks instance and schedule recordings.

The password stays in the data root, outside git. Channel key sequences are
saved per channel after one confirmed pass; a job without steps only reserves
the instance and the time.
"""

from __future__ import annotations

import json
import re
import time
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import ensure_data_layout, salvation_login_path, salvation_recordings_path
from .instances import adb, connect_adb, get_instance, launch_bluestacks, wait_for_adb

PACKAGE = "ar.tvplayer.tv"
LABELS = {
    "salvation",
    "username",
    "password",
    "next",
    "back",
    "cancel",
    "done",
    "add playlist",
    "playlist name",
    "settings",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_login(root: Path | None = None) -> dict[str, Any]:
    path = salvation_login_path(root)
    if not path.is_file():
        raise FileNotFoundError(
            f"Salvation login file missing: {path}. "
            "Create it with service, username, password, and playlist_name."
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    for key in ("username", "password"):
        if not str(data.get(key) or "").strip():
            raise ValueError(f"salvation login is missing {key}")
    data.setdefault("service", "Salvation")
    data.setdefault("playlist_name", "ohush")
    return data


def public_login(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "service": data.get("service") or "Salvation",
        "username": data.get("username"),
        "password_set": bool(data.get("password")),
        "playlist_name": data.get("playlist_name") or "ohush",
    }


def _bounds_center(bounds: str) -> tuple[int, int]:
    nums = [int(n) for n in re.findall(r"\d+", bounds or "")]
    if len(nums) != 4:
        raise ValueError(f"bad bounds {bounds!r}")
    x1, y1, x2, y2 = nums
    return (x1 + x2) // 2, (y1 + y2) // 2


def parse_dump(xml_text: str) -> dict[str, Any]:
    root = ET.fromstring(xml_text)
    texts: list[str] = []
    clickables: list[dict[str, Any]] = []
    for node in root.iter("node"):
        text = (node.attrib.get("text") or "").strip()
        if text and node.attrib.get("class", "").endswith("TextView"):
            texts.append(text)
        if node.attrib.get("clickable") != "true":
            continue
        kids = [(c.attrib.get("text") or "").strip() for c in node.iter("node")]
        label = next((k for k in kids if k), "")
        clickables.append({"label": label, "bounds": node.attrib.get("bounds") or ""})
    return {"texts": texts, "clickables": clickables, "root": root}


def _password_field_bounds(ui: dict[str, Any]) -> str | None:
    """Tiramisu/Leanback: password value is an empty focusable TextView under the row."""
    root = ui.get("root")
    if root is None:
        return None
    for node in root.iter("node"):
        texts = [(c.attrib.get("text") or "").strip().lower() for c in node.iter("node")]
        if "password" not in texts:
            continue
        # Prefer empty focusable TextView inside the Password row (the actual field).
        for child in node.iter("node"):
            cls = child.attrib.get("class") or ""
            if not cls.endswith("TextView"):
                continue
            if (child.attrib.get("text") or "").strip():
                continue
            if child.attrib.get("focusable") == "true" or child.attrib.get("clickable") == "true":
                return child.attrib.get("bounds") or ""
        if node.attrib.get("clickable") == "true":
            return node.attrib.get("bounds") or ""
    return None


def _include_tv_checked(ui: dict[str, Any]) -> bool | None:
    """Best-effort: row present; checked state often absent from dump — return None if unknown."""
    texts = [t.lower() for t in (ui.get("texts") or [])]
    if "include tv channels" not in texts:
        return None
    return None  # dump has no checkbox state; caller may tap to ensure on


def screen_kind(activity: str, texts: list[str]) -> str:
    low = [t.lower() for t in texts]
    if "add playlist" in low and "username" not in low and "salvation" not in low:
        return "welcome"
    if "playlist name" in low and "done" in low and "username" not in low:
        return "playlist_name"
    if "username" in low and "password" in low and "next" in low:
        return "credentials"
    if "salvation" in low and "cancel" in low and "username" not in low:
        return "service_list"
    if "MainActivity" in activity:
        return "home"
    return "unknown"


def _idx(texts: list[str], label: str) -> int:
    for i, text in enumerate(texts):
        if text.lower() == label:
            return i
    return -1


def credentials_filled(texts: list[str]) -> tuple[bool, bool]:
    """Username shows as adjacent text; password fields usually expose no dots in the dump."""
    user_at = _idx(texts, "username")
    pass_at = _idx(texts, "password")
    user_ok = user_at >= 0 and pass_at > user_at + 1
    # Cannot reliably detect a filled password from accessibility text.
    pass_ok = False
    return user_ok, pass_ok


def playlist_name_filled(texts: list[str]) -> bool:
    name_at = _idx(texts, "playlist name")
    done_at = _idx(texts, "done")
    return name_at >= 0 and done_at > name_at + 1


def plan_step(kind: str, texts: list[str], login: dict[str, Any]) -> dict[str, Any]:
    """One remote action for the current screen. The caller re-reads the UI after it."""
    if kind == "home":
        return {"op": "done"}
    if kind == "welcome":
        return {"op": "tap", "label": "add playlist"}
    if kind == "service_list":
        return {"op": "tap", "label": str(login.get("service") or "Salvation")}
    if kind == "credentials":
        user_ok, _pass_ok = credentials_filled(texts)
        if not user_ok:
            return {"op": "type", "label": "username", "text": str(login["username"])}
        # Password field rarely mirrors glyphs into uiautomator text. Type once,
        # then Next on the following step (tracked by login() via trace).
        typed = bool(login.get("_password_typed"))
        if not typed:
            login["_password_typed"] = True
            return {"op": "type", "label": "password", "text": str(login["password"])}
        return {"op": "tap", "label": "next"}
    if kind == "playlist_name":
        if not playlist_name_filled(texts):
            return {"op": "type", "label": "playlist name", "text": str(login.get("playlist_name") or "ohush")}
        return {"op": "tap", "label": "done"}
    return {"op": "unknown"}


def _dump(instance: dict[str, Any]) -> str:
    # Pull as a file — exec-out + text decode breaks on Android 13 XML (cp1252).
    from .config import ensure_data_layout

    dest = ensure_data_layout() / "work" / "salvation_ui.xml"
    dest.parent.mkdir(parents=True, exist_ok=True)
    code, out = adb(instance, ["shell", "uiautomator", "dump", "/sdcard/ohush_ui.xml"], timeout=20)
    if code != 0:
        raise RuntimeError(f"uiautomator dump failed: {out}")
    code, out = adb(instance, ["pull", "/sdcard/ohush_ui.xml", str(dest)], timeout=20)
    adb(instance, ["shell", "rm", "/sdcard/ohush_ui.xml"], timeout=10)
    if code != 0 or not dest.is_file():
        raise RuntimeError(f"could not pull UI dump: {out}")
    xml = dest.read_text(encoding="utf-8", errors="replace")
    if "<hierarchy" not in xml:
        raise RuntimeError("could not read the UI dump")
    return xml


def _activity(instance: dict[str, Any]) -> str:
    code, out = adb(instance, ["shell", "dumpsys", "window"], timeout=20)
    if code != 0:
        return ""
    for line in out.splitlines():
        if "mCurrentFocus=" in line:
            return line.strip()
    return ""


def _tap_label(instance: dict[str, Any], ui: dict[str, Any], label: str) -> None:
    needle = label.lower()
    match = next((c for c in ui["clickables"] if c["label"].lower() == needle), None)
    if match is None:
        raise LookupError(f"no clickable control labeled {label!r}")
    x, y = _bounds_center(match["bounds"])
    code, out = adb(instance, ["shell", "input", "tap", str(x), str(y)])
    if code != 0:
        raise RuntimeError(out)


def _adb_type(instance: dict[str, Any], text: str) -> None:
    """Type into the focused field (caller clears/focuses first)."""
    # Do not prefix a throwaway "x" — HOME+KEYCODE_DEL never removed it (DEL is
    # backspace/before-cursor) and left garbage like "xCBS" in Streamers search.
    payload = str(text).replace(" ", "%s")
    code, out = adb(instance, ["shell", "input", "text", payload])
    if code != 0:
        raise RuntimeError(out)
    time.sleep(0.2)


def _type_into(instance: dict[str, Any], ui: dict[str, Any], label: str, text: str) -> None:
    needle = label.lower()
    if needle == "password":
        bounds = _password_field_bounds(ui)
        if bounds:
            x, y = _bounds_center(bounds)
            # Aim lower-middle of the row (value line), not the "Password" title.
            code, out = adb(instance, ["shell", "input", "tap", str(x), str(y)])
            if code != 0:
                raise RuntimeError(out)
        else:
            _tap_label(instance, ui, label)
    else:
        _tap_label(instance, ui, label)
    time.sleep(0.8)
    _adb_type(instance, text)
    time.sleep(0.3)
    # Do not press Enter on password — on Tiramisu it can clear focus without enabling Next.
    if needle != "password":
        adb(instance, ["shell", "input", "keyevent", "66"])
        time.sleep(0.6)
    else:
        time.sleep(0.4)


def _launch_app(instance: dict[str, Any]) -> None:
    adb(
        instance,
        ["shell", "monkey", "-p", PACKAGE, "-c", "android.intent.category.LAUNCHER", "1"],
        timeout=20,
    )


def ensure_ready(instance_id: str, root: Path | None = None, *, launch: bool = True) -> dict[str, Any]:
    instance = get_instance(instance_id, root)
    ok, detail = connect_adb(instance)
    if not ok and launch:
        launch_bluestacks(instance, launch_app=False)
        if not wait_for_adb(instance, seconds=90):
            raise RuntimeError(f"BlueStacks {instance_id} did not accept ADB ({detail})")
    elif not ok:
        raise RuntimeError(f"ADB is down for {instance_id}: {detail}")
    return instance


def login(instance_id: str, root: Path | None = None, *, steps: int = 12) -> dict[str, Any]:
    creds = load_login(root)
    instance = ensure_ready(instance_id, root)
    _launch_app(instance)
    time.sleep(2.0)
    trace: list[dict[str, Any]] = []
    kind = "unknown"
    for _ in range(steps):
        activity = _activity(instance)
        ui = parse_dump(_dump(instance))
        kind = screen_kind(activity, ui["texts"])
        action = plan_step(kind, ui["texts"], creds)
        safe = {k: v for k, v in action.items() if k != "text"}
        if action.get("op") == "type":
            safe["text_len"] = len(str(action.get("text") or ""))
        trace.append({"screen": kind, "action": safe})
        if action["op"] == "done":
            return {"ok": True, "instance": instance_id, "screen": kind, "trace": trace, "login": public_login(creds)}
        if action["op"] == "tap":
            _tap_label(instance, ui, str(action["label"]))
            time.sleep(1.5 if action["label"].lower() != "done" else 4.0)
        elif action["op"] == "type":
            _type_into(instance, ui, str(action["label"]), str(action["text"]))
        else:
            break
    return {"ok": kind == "home", "instance": instance_id, "screen": kind, "trace": trace, "login": public_login(creds)}


def status(instance_id: str, root: Path | None = None) -> dict[str, Any]:
    instance = ensure_ready(instance_id, root, launch=False)
    activity = _activity(instance)
    ui = parse_dump(_dump(instance))
    kind = screen_kind(activity, ui["texts"])
    shown = activity.split()[-1].rstrip("}") if activity else ""
    return {"ok": kind == "home", "instance": instance_id, "screen": kind, "activity": shown}


def load_recordings(root: Path | None = None) -> dict[str, Any]:
    ensure_data_layout(root)
    path = salvation_recordings_path(root)
    if not path.is_file():
        data = {"updated_utc": _now(), "jobs": []}
        save_recordings(data, root)
        return data
    return json.loads(path.read_text(encoding="utf-8"))


def save_recordings(data: dict[str, Any], root: Path | None = None) -> Path:
    ensure_data_layout(root)
    path = salvation_recordings_path(root)
    data = dict(data)
    data["updated_utc"] = _now()
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def add_recording(
    *,
    instance_id: str,
    channel: str,
    start_at: str,
    minutes: float,
    root: Path | None = None,
) -> dict[str, Any]:
    job = {
        "job_id": uuid.uuid4().hex[:12],
        "instance_id": instance_id,
        "channel": channel,
        "start_at": start_at,
        "minutes": float(minutes),
        "steps": [],
        "status": "scheduled",
        "created_utc": _now(),
    }
    data = load_recordings(root)
    jobs = list(data.get("jobs") or [])
    jobs.append(job)
    data["jobs"] = jobs
    save_recordings(data, root)
    return job


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="Salvation login on BlueStacks")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("status", "login"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--instance", default="player 0")
    add = sub.add_parser("record-add")
    add.add_argument("--instance", default="player 0")
    add.add_argument("--channel", required=True)
    add.add_argument("--at", required=True, help="ISO time, e.g. 2026-11-16T20:00:00-05:00")
    add.add_argument("--minutes", type=float, required=True)
    sub.add_parser("record-list")
    args = p.parse_args(argv)
    if args.cmd == "status":
        print(json.dumps(status(args.instance), indent=2))
        return 0
    if args.cmd == "login":
        result = login(args.instance)
        print(json.dumps(result, indent=2))
        return 0 if result.get("ok") else 3
    if args.cmd == "record-add":
        job = add_recording(
            instance_id=args.instance,
            channel=args.channel,
            start_at=args.at,
            minutes=args.minutes,
        )
        print(json.dumps({"ok": True, "job": job}, indent=2))
        return 0
    if args.cmd == "record-list":
        print(json.dumps(load_recordings(), indent=2))
        return 0
    return 2
