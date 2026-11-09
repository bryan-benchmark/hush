"""ADB channel recipes for Streamers (TiviMate) and shared recipe IO."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import DEFAULT_STREAMERS_PACKAGE, channel_recipes_dir, ensure_data_layout
from .instances import adb, connect_adb, get_instance, launch_bluestacks, wait_for_adb


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def recipe_path(channel_id: str, root: Path | None = None) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in channel_id.strip())
    return channel_recipes_dir(root) / f"{safe}.json"


def list_recipes(root: Path | None = None) -> list[dict[str, Any]]:
    ensure_data_layout(root)
    rows = []
    for path in sorted(channel_recipes_dir(root).glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {"error": "invalid json"}
        rows.append({"channel_id": path.stem, "path": str(path), **data})
    return rows


def load_recipe(channel_id: str, root: Path | None = None) -> dict[str, Any]:
    path = recipe_path(channel_id, root)
    if not path.is_file():
        raise FileNotFoundError(f"channel recipe missing: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    data["channel_id"] = data.get("channel_id") or channel_id
    data["path"] = str(path)
    return data


def save_recipe(channel_id: str, recipe: dict[str, Any], root: Path | None = None) -> Path:
    ensure_data_layout(root)
    path = recipe_path(channel_id, root)
    body = dict(recipe)
    body["channel_id"] = channel_id
    body["updated_utc"] = _now()
    path.write_text(json.dumps(body, indent=2), encoding="utf-8")
    return path


def example_recipe(channel_id: str = "EXAMPLE") -> dict[str, Any]:
    return {
        "channel_id": channel_id,
        "source_kind": "streamers",
        "label": channel_id,
        "launch": {"package": DEFAULT_STREAMERS_PACKAGE},
        "steps": [
            {"action": "wait", "seconds": 5},
            {"action": "keyevent", "code": 82},
            {"action": "wait", "seconds": 1},
            {
                "action": "note",
                "text": "Replace steps with taps/keyevents that open this favorite in Streamers.",
            },
        ],
        "verify": None,
    }


def ensure_example_recipe(root: Path | None = None) -> Path:
    path = recipe_path("EXAMPLE", root)
    if not path.is_file():
        save_recipe("EXAMPLE", example_recipe("EXAMPLE"), root)
    return path


def _run_step(instance: dict[str, Any], step: dict[str, Any], *, dry_run: bool) -> dict[str, Any]:
    action = str(step.get("action") or "").lower()
    result: dict[str, Any] = {"step": step, "ok": True, "detail": ""}
    if dry_run:
        result["detail"] = "dry_run"
        return result

    if action == "wait":
        time.sleep(float(step.get("seconds") or 1.0))
        result["detail"] = f"slept {step.get('seconds', 1)}"
        return result
    if action == "note":
        result["detail"] = str(step.get("text") or "")
        return result
    if action == "keyevent":
        code = int(step["code"])
        rc, out = adb(instance, ["shell", "input", "keyevent", str(code)])
        result["ok"] = rc == 0
        result["detail"] = out or f"keyevent {code}"
        return result
    if action == "tap":
        x, y = int(step["x"]), int(step["y"])
        rc, out = adb(instance, ["shell", "input", "tap", str(x), str(y)])
        result["ok"] = rc == 0
        result["detail"] = out or f"tap {x},{y}"
        return result
    if action == "swipe":
        args = [str(int(step[k])) for k in ("x1", "y1", "x2", "y2")]
        duration = str(int(step.get("duration_ms") or 300))
        rc, out = adb(instance, ["shell", "input", "swipe", *args, duration])
        result["ok"] = rc == 0
        result["detail"] = out or "swipe"
        return result
    if action == "text":
        text = str(step.get("text") or "").replace(" ", "%s")
        rc, out = adb(instance, ["shell", "input", "text", text])
        result["ok"] = rc == 0
        result["detail"] = out or "text"
        return result
    if action == "shell":
        cmd = list(step.get("args") or [])
        if not cmd:
            result["ok"] = False
            result["detail"] = "shell step missing args"
            return result
        rc, out = adb(instance, ["shell", *cmd], timeout=float(step.get("timeout") or 30))
        result["ok"] = rc == 0
        result["detail"] = out
        return result

    result["ok"] = False
    result["detail"] = f"unknown action {action!r}"
    return result


def apply_recipe(
    *,
    channel_id: str,
    instance_id: str,
    root: Path | None = None,
    dry_run: bool = False,
    launch: bool = True,
    wait_adb_seconds: float = 90.0,
) -> dict[str, Any]:
    recipe = load_recipe(channel_id, root)
    if str(recipe.get("source_kind") or "streamers") not in ("streamers", "shared"):
        raise ValueError(f"recipe {channel_id} is not a streamers recipe")

    instance = get_instance(instance_id, root)
    launch_info = None
    if launch and not dry_run:
        launch_info = launch_bluestacks(instance, launch_app=True)
        connect_adb(instance)
        if not wait_for_adb(instance, seconds=wait_adb_seconds):
            return {
                "ok": False,
                "channel_id": channel_id,
                "instance_id": instance_id,
                "error": "ADB not ready after launch",
                "launch": launch_info,
                "applied_utc": _now(),
            }
        # Bring package to foreground again in case launch raced boot.
        package = str(
            (recipe.get("launch") or {}).get("package")
            or instance.get("package")
            or DEFAULT_STREAMERS_PACKAGE
        )
        adb(
            instance,
            [
                "shell",
                "monkey",
                "-p",
                package,
                "-c",
                "android.intent.category.LAUNCHER",
                "1",
            ],
            timeout=20.0,
        )

    step_results = []
    ok = True
    for step in recipe.get("steps") or []:
        if str(step.get("action") or "").lower() == "note":
            step_results.append(_run_step(instance, step, dry_run=dry_run))
            continue
        row = _run_step(instance, step, dry_run=dry_run)
        step_results.append(row)
        if not row["ok"]:
            ok = False
            break

    return {
        "ok": ok,
        "channel_id": channel_id,
        "instance_id": instance_id,
        "dry_run": dry_run,
        "launch": launch_info,
        "steps": step_results,
        "recipe_path": recipe.get("path"),
        "applied_utc": _now(),
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="Channel recipes")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    e = sub.add_parser("example")
    e.add_argument("--channel-id", default="EXAMPLE")
    a = sub.add_parser("apply")
    a.add_argument("--source", default="streamers", choices=("streamers",))
    a.add_argument("--instance", required=True)
    a.add_argument("--channel", required=True)
    a.add_argument("--dry-run", action="store_true")
    a.add_argument("--no-launch", action="store_true")
    s = sub.add_parser("save-example")
    s.add_argument("--channel-id", default="EXAMPLE")

    args = p.parse_args(argv)
    if args.cmd == "list":
        ensure_example_recipe()
        print(json.dumps({"recipes": list_recipes()}, indent=2))
        return 0
    if args.cmd == "example":
        print(json.dumps(example_recipe(args.channel_id), indent=2))
        return 0
    if args.cmd == "save-example":
        path = save_recipe(args.channel_id, example_recipe(args.channel_id))
        print(json.dumps({"ok": True, "path": str(path)}, indent=2))
        return 0
    if args.cmd == "apply":
        try:
            result = apply_recipe(
                channel_id=args.channel,
                instance_id=args.instance,
                dry_run=args.dry_run,
                launch=not args.no_launch,
            )
        except FileNotFoundError as e:
            print(json.dumps({"ok": False, "error": str(e)}))
            return 1
        print(json.dumps(result, indent=2))
        return 0 if result.get("ok") else 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
