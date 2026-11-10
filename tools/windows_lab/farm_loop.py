"""Autonomous farm loop: label → human gate → plan → on-air record.

Designed for Task Scheduler every ~15 minutes.

Rules:
- If a capture lock is held: do not label (GPU/lag) and do not start another take.
- If Streamers shows home + loopback is live + BlueStacks window exists: record
  what is already on air (--no-channel-apply). Never retune from this loop.
- Human gate writes a flag file; owner opens /farm only then.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .config import ensure_data_layout
from .coverage_farm import indexes_dir
from .farm_orchestrate import op1_record, op2_label, op3_human
from .farm_resources import memory_snapshot
from .instances import find_window_title, get_instance, list_instances
from .locks import get_lock
from .streamers_lag import CLEAN_CONCURRENT, scan_recent_lag

ET = ZoneInfo("America/New_York")
REVIEW_URL = "http://127.0.0.1:3010/farm"
DEFAULT_INSTANCE = "Nougat32"
DEFAULT_MINUTES = 20
SHORT_MINUTES = 10
PROBE_SECONDS = 2.0
LIVE_PEAK = 0.02
# Daytime: label every other idle loop so Ollama and capture do not stack.
LABEL_EVERY_N_IDLE = 2
# Measured ~7s/clip (Whisper window negligible; qwen dominates). Overnight burns backlog.
SEC_PER_CLIP_EST = 7.0
OVERNIGHT_LABEL_START_HOUR = 0  # 00:00 ET inclusive
OVERNIGHT_LABEL_END_HOUR = 6  # 06:00 ET exclusive
OVERNIGHT_DRAFT_LIMIT = 80
DAY_DRAFT_LIMIT = 20


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def schedule_window(now: datetime | None = None) -> dict[str, Any]:
    """Day = capture-first; overnight = label-first (no new record).

    Label cost (measured on this box): ~7 s/clip with qwen2.5:14b after Whisper.
    A 20‑minute take @ 60 s clips ≈ 20 clips ≈ 2.3 minutes to draft.
    Overnight 00:00–06:00 ET can clear large backlogs while Streamers sleeps.
    """
    local = (now or datetime.now(ET)).astimezone(ET)
    hour = local.hour
    overnight = OVERNIGHT_LABEL_START_HOUR <= hour < OVERNIGHT_LABEL_END_HOUR
    if overnight:
        return {
            "mode": "overnight_label",
            "local_et": local.isoformat(),
            "do_record": False,
            # Draft for review only — auto paid_ad gated by farm_labels/trust_gate.json.
            "do_label": True,
            "label_every_n": 1,
            "draft_limit": OVERNIGHT_DRAFT_LIMIT,
            "sec_per_clip_est": SEC_PER_CLIP_EST,
            "auto_paid_ad": False,
            "why": "00:00–06:00 ET — draft backlog for review; auto-accept off until gold trust gate",
        }
    return {
        "mode": "day_capture",
        "local_et": local.isoformat(),
        "do_record": True,
        # Labeling stays overnight until the draft process is trusted.
        "do_label": False,
        "label_every_n": LABEL_EVERY_N_IDLE,
        "draft_limit": DAY_DRAFT_LIMIT,
        "sec_per_clip_est": SEC_PER_CLIP_EST,
        "auto_paid_ad": False,
        "why": "Daytime — capture only; labeling deferred to 00:00–06:00 ET overnight window",
    }


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _python() -> Path:
    venv = _repo_root() / ".venv" / "Scripts" / "python.exe"
    return venv if venv.is_file() else Path(sys.executable)


def capture_busy(instance_id: str = DEFAULT_INSTANCE, root: Path | None = None) -> dict[str, Any] | None:
    return get_lock("streamers", instance_id, root=root)


def ready_instance_id(root: Path | None = None) -> str | None:
    for row in list_instances(root):
        if not row.get("enabled", True):
            continue
        if row.get("source_kind", "streamers") not in (None, "streamers"):
            continue
        if str(row.get("loopback_device") or "").strip():
            return str(row["id"])
    return None


def probe_loopback_peak(device_substr: str, *, seconds: float = PROBE_SECONDS) -> dict[str, Any]:
    """Short loopback listen — Streamers must already be playing through this device."""
    try:
        import numpy as np
        import soundcard as sc
    except ImportError as exc:  # pragma: no cover
        return {"ok": False, "error": f"audio libs missing: {exc}"}

    mics = [
        m
        for m in sc.all_microphones(include_loopback=True)
        if getattr(m, "isloopback", False)
        and device_substr.lower() in (m.name or "").lower()
        and not (m.name or "").startswith("Microphone")
    ]
    if not mics:
        return {"ok": False, "error": f"no loopback matching {device_substr!r}", "peak": 0.0, "level": "silent"}
    mic = mics[0]
    frames = max(1, int(48000 * seconds))
    data = mic.record(samplerate=48000, numframes=frames, channels=2)
    peak = float(np.max(np.abs(data))) if data is not None and len(data) else 0.0
    if peak <= 1e-5:
        level = "silent"
    elif peak < LIVE_PEAK:
        level = "quiet"
    elif peak >= 0.98:
        level = "clipping"
    else:
        level = "live"
    return {
        "ok": level == "live",
        "device": mic.name,
        "peak": round(peak, 5),
        "level": level,
        "seconds": seconds,
    }


def on_air_health(instance_id: str = DEFAULT_INSTANCE, root: Path | None = None) -> dict[str, Any]:
    """Picture/audio healthy enough to record without retuning."""
    from .salvation import status as salvation_status

    root = ensure_data_layout(root)
    inst = get_instance(instance_id, root)
    window_pat = str(inst.get("window_title") or "BlueStacks")
    title = find_window_title(window_pat)
    try:
        sal = salvation_status(instance_id, root=root)
    except Exception as exc:  # noqa: BLE001
        sal = {"ok": False, "error": str(exc), "screen": "unknown"}
    audio = probe_loopback_peak(str(inst.get("loopback_device") or "MZ-631M"))
    healthy = bool(title) and bool(sal.get("ok")) and bool(audio.get("ok"))
    return {
        "ok": healthy,
        "instance_id": instance_id,
        "window_title": title,
        "salvation": sal,
        "audio": audio,
        "reason": (
            "on-air healthy — record without retune"
            if healthy
            else "not healthy for on-air record (need home + live loopback + visible window)"
        ),
    }


def write_human_flag(human: dict[str, Any], root: Path | None = None) -> dict[str, Any]:
    root = ensure_data_layout(root)
    idx = indexes_dir(root)
    flag = idx / "farm_human_needed.flag"
    gate = {
        "updated_utc": _now(),
        "required": bool(human.get("required")),
        "reason": human.get("reason"),
        "review_url": REVIEW_URL,
        "help_asks": human.get("help_asks"),
        "backlog_level": human.get("backlog_level"),
    }
    (idx / "farm_human_gate.json").write_text(json.dumps(gate, indent=2), encoding="utf-8")
    if gate["required"]:
        flag.write_text(
            f"HUMAN NEEDED\n{gate['updated_utc']}\n{REVIEW_URL}\n{gate.get('reason')}\n",
            encoding="utf-8",
        )
    elif flag.is_file():
        flag.unlink()
    return gate


def start_on_air_record(
    *,
    instance_id: str,
    channel_id: str,
    minutes: float,
    root: Path | None = None,
    detach: bool = True,
) -> dict[str, Any]:
    """Record whatever Streamers is already showing. Never applies a channel recipe."""
    root = ensure_data_layout(root)
    if capture_busy(instance_id, root):
        return {"ok": False, "error": "resource busy", "lock": capture_busy(instance_id, root)}

    env = os.environ.copy()
    env["OHUSH_DATA_ROOT"] = str(root)
    cmd = [
        str(_python()),
        "-m",
        "tools.windows_lab",
        "session",
        "start",
        "--source",
        "streamers",
        "--instance",
        instance_id,
        "--channel",
        channel_id,
        "--minutes",
        str(minutes),
        "--media",
        "av",
        "--still-interval",
        "1",
        "--no-channel-apply",
        "--rights-status",
        "authorized",
    ]
    log_dir = root / "work" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "farm_on_air_record.log"
    if detach:
        with log_path.open("a", encoding="utf-8") as log:
            log.write(f"\n--- {_now()} start {channel_id} {minutes}m ---\n")
            log.flush()
            proc = subprocess.Popen(
                cmd,
                cwd=str(_repo_root()),
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            )
        return {
            "ok": True,
            "detached": True,
            "pid": proc.pid,
            "channel_id": channel_id,
            "minutes": minutes,
            "log": str(log_path),
            "cmd": cmd,
        }

    from .session_capture import start_session

    result = start_session(
        source_kind="streamers",
        channel_id=channel_id,
        minutes=minutes,
        media="av",
        instance_id=instance_id,
        rights_status="authorized",
        apply_channel=False,
        still_interval_sec=1.0,
        root=root,
    )
    return {"ok": bool(result.get("ok")), "detached": False, "result": result}


def ensure_on_air_recipe(root: Path | None = None) -> Path:
    """Bake the verified on-air continue recipe (no retune steps — safe to document)."""
    from .channel import save_recipe

    recipe = {
        "channel_id": "ON_AIR_CONTINUE",
        "source_kind": "streamers",
        "label": "Whatever is already playing",
        "verified": True,
        "verified_mode": "no_channel_apply",
        "do_not_apply_example_recipe": True,
        "apply_allowed": False,
        "launch": {"package": "ar.tvplayer.tv"},
        "steps": [
            {
                "action": "note",
                "text": (
                    "Do not apply this recipe. Confirm Streamers MainActivity + live loopback, "
                    "then: session start --no-channel-apply --channel ON_AIR_CONTINUE (or the "
                    "real channel_id once known from chrome)."
                ),
            }
        ],
        "open_hint": "Player already up. Farm loop records without guide taps.",
    }
    return save_recipe("ON_AIR_CONTINUE", recipe, root)


def ensure_local_recipe_stubs(root: Path | None = None) -> list[str]:
    """Document local open paths; apply_allowed=false until a real dump-proven recipe exists."""
    from .channel import recipe_path, save_recipe

    stubs = [
        (
            "CBS_LOCAL_FLAGSHIP",
            "US CBS SECTION — any US DMA. Search CBS hits locals; prefer big-DMA with picture. "
            "D-pad center (keyevent 23) after row selected. Never apply EXAMPLE.",
        ),
        (
            "ABC_LOCAL_FLAGSHIP",
            "US ABC SECTION group (search ABC hits movies). Fresh dump before every tap.",
        ),
        (
            "NBC_LOCAL_FLAGSHIP",
            "US NBC SECTION — any US market. Fresh dump; keyevent 23 to open.",
        ),
        (
            "FOX_LOCAL_FLAGSHIP",
            "US FOX SECTION group (search FOX hits movies). Fresh dump; keyevent 23 to open.",
        ),
    ]
    written: list[str] = []
    for channel_id, hint in stubs:
        path = recipe_path(channel_id, root)
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("verified") and data.get("apply_allowed"):
                continue
        save_recipe(
            channel_id,
            {
                "channel_id": channel_id,
                "source_kind": "streamers",
                "label": channel_id,
                "verified": False,
                "apply_allowed": False,
                "do_not_apply_example_recipe": True,
                "open_hint": hint,
                "steps": [
                    {
                        "action": "note",
                        "text": (
                            f"UNVERIFIED. {hint} Replace these notes with dump-proven "
                            "tap labels + keyevent 23, then set verified=true and apply_allowed=true."
                        ),
                    }
                ],
            },
            root,
        )
        written.append(channel_id)
    return written


def _idle_pass_state(root: Path) -> dict[str, Any]:
    path = indexes_dir(root) / "farm_loop_pass.json"
    if path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"idle_pass": 0}


def _save_idle_pass_state(root: Path, state: dict[str, Any]) -> None:
    indexes_dir(root).joinpath("farm_loop_pass.json").write_text(
        json.dumps(state, indent=2), encoding="utf-8"
    )


def run_loop(
    root: Path | None = None,
    *,
    instance_id: str | None = None,
    do_label: bool | None = None,
    do_record: bool | None = None,
    draft_limit: int | None = None,
    model: str = "qwen2.5:14b",
    minutes: float | None = None,
    detach_record: bool = True,
) -> dict[str, Any]:
    root = ensure_data_layout(root)
    ensure_on_air_recipe(root)
    stubs = ensure_local_recipe_stubs(root)
    instance_id = instance_id or ready_instance_id(root) or DEFAULT_INSTANCE
    lag = scan_recent_lag(root)
    busy = capture_busy(instance_id, root)
    mem = memory_snapshot()
    sched = schedule_window()
    # CLI overrides win; otherwise follow day/night window.
    if do_label is None:
        do_label = bool(sched["do_label"])
    if do_record is None:
        do_record = bool(sched["do_record"])
    if draft_limit is None:
        draft_limit = int(sched["draft_limit"])
    label_every_n = int(sched["label_every_n"])

    out: dict[str, Any] = {
        "ok": True,
        "loop_utc": _now(),
        "instance_id": instance_id,
        "busy": busy,
        "streamers_lag": lag.get("overall"),
        "memory": mem,
        "schedule": sched,
        "recipe_stubs": stubs,
        "second_instance": {
            "allowed": bool(mem.get("allow_second_instance")),
            "hold": "Need ≥8 GB free RAM + distinct VB-Cable before enabling clone",
        },
        "steps": [],
    }

    if busy:
        out["steps"].append(
            {
                "step": "skip_while_capturing",
                "detail": "Capture lock held — no label tick, no new record (protect Streamers from lag).",
                "lock": busy,
            }
        )
        out["human"] = write_human_flag(op3_human(root), root)
        out["plan"] = {
            "daypart": (op1_record(root).get("hierarchy") or {}).get("daypart"),
            "skipped_full_plan": True,
        }
        _write_loop_state(out, root)
        return out

    pass_state = _idle_pass_state(root)
    idle_pass = int(pass_state.get("idle_pass") or 0) + 1
    pass_state["idle_pass"] = idle_pass
    _save_idle_pass_state(root, pass_state)
    label_due = (idle_pass % max(1, label_every_n)) == 0

    # 1) Label pass (offset + RAM gate)
    if do_label and label_due and mem.get("allow_label", True):
        label = op2_label(root, run_tick=True, model=model, draft_limit=draft_limit)
        out["label"] = {
            "behind": label.get("behind"),
            "tick_ok": (label.get("tick") or {}).get("ok"),
            "imported": (label.get("tick") or {}).get("imported"),
            "drafted": ((label.get("tick") or {}).get("draft") or {}).get("drafted"),
            "ollama_unloaded": ((label.get("tick") or {}).get("draft") or {}).get("ollama_unloaded"),
        }
        out["steps"].append({"step": "label_tick", "behind": label.get("behind"), "idle_pass": idle_pass})
    else:
        reason = (
            "odd_idle_pass"
            if do_label and not label_due
            else ("ram_pressure" if do_label and not mem.get("allow_label") else "disabled")
        )
        out["steps"].append({"step": "label_skipped", "reason": reason, "idle_pass": idle_pass})

    # 2) Human gate
    human = op3_human(root)
    out["human"] = write_human_flag(human, root)
    out["steps"].append({"step": "human_gate", "required": human.get("required")})

    # 3) Record plan refresh
    plan = op1_record(root)
    top = None
    if plan.get("assignments"):
        top = (plan["assignments"][0] or {}).get("channel_id")
    out["plan"] = {
        "daypart": (plan.get("hierarchy") or {}).get("daypart"),
        "top": top,
        "assignments": len(plan.get("assignments") or []),
        "streamers_lag": (plan.get("streamers_lag") or {}).get("overall"),
    }
    out["steps"].append({"step": "record_plan", "top": top})

    # 3b) Package retain set (B2 dry-run path stays manual until rclone remote exists)
    try:
        from .farm_archive import upload_b2, write_package_index

        pkg = write_package_index(root)
        b2 = upload_b2(execute=False, root=root)
        out["package"] = {"objects": pkg.get("objects"), "gb_total": pkg.get("gb_total")}
        out["b2"] = {"dry_run": True, "dest": b2.get("dest"), "ok": b2.get("ok"), "hint": b2.get("hint")}
        out["steps"].append({"step": "package_index", "objects": pkg.get("objects")})
    except Exception as exc:  # noqa: BLE001
        out["steps"].append({"step": "package_index_failed", "error": str(exc)})

    # 4) On-air record (no retune) — RAM + lag kill-switch
    if do_record:
        if not mem.get("allow_record", True):
            out["record"] = {"ok": False, "skipped": True, "reason": "ram_pressure", "memory": mem}
            out["steps"].append(
                {
                    "step": "on_air_record_skipped",
                    "reason": f"free RAM {mem.get('avail_gb')} GB < {mem.get('thresholds_gb', {}).get('record')} GB",
                }
            )
        elif lag.get("overall") == "critical" and minutes is None:
            # Still allow short takes; kill long ones under lag heat.
            health = on_air_health(instance_id, root)
            out["on_air_health"] = health
            chunk = SHORT_MINUTES
            out["steps"].append({"step": "lag_kill_switch", "chunk_minutes": chunk})
            if health.get("ok"):
                channel = _resolve_on_air_channel(instance_id, root, plan_top=top, out=out)
                rec = start_on_air_record(
                    instance_id=instance_id,
                    channel_id=channel,
                    minutes=float(chunk),
                    root=root,
                    detach=detach_record,
                )
                out["record"] = rec
                out["steps"].append(
                    {
                        "step": "on_air_record",
                        "started": bool(rec.get("ok")),
                        "channel_id": channel,
                        "plan_target": top,
                        "minutes": chunk,
                        "detached": rec.get("detached"),
                    }
                )
            else:
                out["record"] = {"ok": False, "skipped": True, "health": health}
                out["steps"].append({"step": "on_air_record_skipped", "reason": health.get("reason")})
        else:
            health = on_air_health(instance_id, root)
            out["on_air_health"] = health
            chunk = minutes
            if chunk is None:
                chunk = SHORT_MINUTES if lag.get("overall") == "critical" else DEFAULT_MINUTES
            if health.get("ok"):
                channel = _resolve_on_air_channel(instance_id, root, plan_top=top, out=out)
                rec = start_on_air_record(
                    instance_id=instance_id,
                    channel_id=channel,
                    minutes=float(chunk),
                    root=root,
                    detach=detach_record,
                )
                out["record"] = rec
                out["steps"].append(
                    {
                        "step": "on_air_record",
                        "started": bool(rec.get("ok")),
                        "channel_id": channel,
                        "plan_target": top,
                        "minutes": chunk,
                        "detached": rec.get("detached"),
                    }
                )
            else:
                out["record"] = {"ok": False, "skipped": True, "health": health}
                out["steps"].append({"step": "on_air_record_skipped", "reason": health.get("reason")})
    else:
        out["steps"].append({"step": "record_disabled"})

    out["max_concurrent"] = CLEAN_CONCURRENT
    _write_loop_state(out, root)
    return out


def _resolve_on_air_channel(
    instance_id: str,
    root: Path,
    *,
    plan_top: str | None,
    out: dict[str, Any],
) -> str:
    """Prefer chrome channel guess; else ON_AIR_CONTINUE."""
    try:
        from .streamers_chrome import read_playing_channel

        chrome = read_playing_channel(instance_id, root=root, tap_for_chrome=True)
        out["chrome"] = {
            "channel_guess": chrome.get("channel_guess"),
            "program_guess": chrome.get("program_guess"),
            "screenshot": chrome.get("screenshot"),
        }
        out["steps"].append(
            {
                "step": "chrome_peek",
                "channel_guess": chrome.get("channel_guess"),
                "screenshot": chrome.get("screenshot"),
            }
        )
        guess = chrome.get("channel_guess")
        # Reject weak guesses like "NV" from ticker fragments.
        if guess and len(str(guess).strip()) >= 4:
            safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in str(guess))[:48]
            if len(safe) >= 4:
                return safe
    except Exception as exc:  # noqa: BLE001
        out["steps"].append({"step": "chrome_peek_failed", "error": str(exc)})
    return "ON_AIR_CONTINUE"


def _write_loop_state(out: dict[str, Any], root: Path) -> None:
    path = indexes_dir(root) / "farm_loop.json"
    path.write_text(json.dumps(out, indent=2), encoding="utf-8")


def install_loop_task(repo: Path | None = None, root: Path | None = None, *, minutes: int = 15) -> Path:
    """Write PowerShell that registers the farm loop in Task Scheduler."""
    repo = repo or _repo_root()
    root = ensure_data_layout(root)
    farm = root / "farm"
    farm.mkdir(parents=True, exist_ok=True)
    py = _python()
    wrapper = farm / "run_farm_loop.cmd"
    wrapper.write_text(
        "\r\n".join(
            [
                "@echo off",
                f"set OHUSH_DATA_ROOT={root}",
                f"cd /d {repo}",
                f'"{py}" -m tools.windows_lab farm loop >> "{root}\\work\\logs\\farm_loop.log" 2>&1',
                "",
            ]
        ),
        encoding="ascii",
        newline="\r\n",
    )
    (root / "work" / "logs").mkdir(parents=True, exist_ok=True)
    ps1 = farm / "register_farm_loop.ps1"
    script = f"""# Register OHush farm autonomy loop (every {minutes} minutes)
$ErrorActionPreference = "Stop"
$taskName = "OHushFarmLoop"
$wrapper = {json.dumps(str(wrapper))}
$action = New-ScheduledTaskAction -Execute $wrapper
# Finite repetition duration — MaxValue is rejected by Task Scheduler on this host.
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes {minutes}) -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 2)
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Write-Output "Registered $taskName -> $wrapper (every {minutes} min)"
"""
    ps1.write_text(script, encoding="utf-8")
    return ps1


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="Autonomous farm loop")
    sub = p.add_subparsers(dest="cmd")

    # Default: run loop when invoked as `farm loop`
    run_p = sub.add_parser("run", help="Run one loop pass (default)")
    run_p.add_argument("--instance", default=None)
    run_p.add_argument("--no-label", action="store_true")
    run_p.add_argument("--no-record", action="store_true")
    run_p.add_argument("--minutes", type=float, default=None)
    run_p.add_argument("--limit", type=int, default=None, help="Draft clip cap (default from day/night schedule)")
    run_p.add_argument("--model", default="qwen2.5:14b")
    run_p.add_argument("--foreground-record", action="store_true")

    sub.add_parser("health", help="Probe on-air health only")
    sub.add_parser("schedule", help="Show day/night capture vs label window")
    inst = sub.add_parser("install-task", help="Write + optionally register Task Scheduler job")
    inst.add_argument("--minutes", type=int, default=15)
    inst.add_argument("--register", action="store_true", help="Run the PowerShell registrar now")
    inst.add_argument("--repo", type=Path, default=None)

    argv = list(sys.argv[1:] if argv is None else argv)
    # `farm loop` and `farm loop --limit 15` both mean run.
    if not argv or argv[0].startswith("-"):
        argv = ["run", *argv]
    args = p.parse_args(argv)

    root = ensure_data_layout()
    if args.cmd == "health":
        iid = ready_instance_id(root) or DEFAULT_INSTANCE
        print(json.dumps(on_air_health(iid, root), indent=2))
        return 0
    if args.cmd == "schedule":
        sched = schedule_window()
        # Rough backlog ETA from unscored queue rows.
        pending = 0
        key_scored: set[str] = set()
        from .coverage_farm import farm_label_dir

        qpath = farm_label_dir(root) / "queue.jsonl"
        kpath = farm_label_dir(root) / "key.jsonl"
        if kpath.is_file():
            for line in kpath.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                row = json.loads(line)
                if row.get("model"):
                    key_scored.add(row["clip"])
        if qpath.is_file():
            for line in qpath.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                clip = json.loads(line)["clip"]
                if clip not in key_scored:
                    pending += 1
        eta_min = round(pending * SEC_PER_CLIP_EST / 60.0, 1)
        print(
            json.dumps(
                {
                    "schedule": sched,
                    "backlog": {
                        "pending_clips": pending,
                        "sec_per_clip_est": SEC_PER_CLIP_EST,
                        "eta_min": eta_min,
                        "overnight_capacity_clips": int(
                            (OVERNIGHT_LABEL_END_HOUR - OVERNIGHT_LABEL_START_HOUR)
                            * 60
                            * 60
                            / SEC_PER_CLIP_EST
                        ),
                    },
                },
                indent=2,
            )
        )
        return 0
    if args.cmd == "install-task":
        path = install_loop_task(args.repo, root, minutes=args.minutes)
        registered = None
        if args.register:
            try:
                completed = subprocess.run(
                    ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(path)],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                registered = {
                    "returncode": completed.returncode,
                    "stdout": (completed.stdout or "").strip(),
                    "stderr": (completed.stderr or "").strip(),
                }
            except Exception as exc:  # noqa: BLE001
                registered = {"error": str(exc)}
        print(json.dumps({"ok": True, "script": str(path), "registered": registered}, indent=2))
        return 0 if not registered or registered.get("returncode", 0) == 0 else 2
    if args.cmd == "run":
        out = run_loop(
            root,
            instance_id=args.instance,
            do_label=False if args.no_label else None,
            do_record=False if args.no_record else None,
            draft_limit=args.limit,
            model=args.model,
            minutes=args.minutes,
            detach_record=not args.foreground_record,
        )
        print(json.dumps(out, indent=2))
        return 0 if out.get("ok") else 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
