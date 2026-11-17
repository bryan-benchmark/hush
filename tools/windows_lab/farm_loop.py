"""Autonomous farm loop: multichannel/verdict → human gate → plan → on-air record.

Designed for Task Scheduler every ~15 minutes.

Rules:
- If a capture lock is held: do not label (GPU/lag) and do not start another take
  (unless capture_pause is on — then label/verdict backfill may run).
- Overnight 02:00–06:00 ET: vision+ASR+acoustic consensus auto-locks; disagrees → /verdict.
- If Streamers shows home + loopback is live + BlueStacks window exists: record
  what is already on air (--no-channel-apply). Never retune from this loop.
- Human gate prefers /verdict; legacy /farm pile drains via consensus.
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
from .coverage_farm import farm_label_dir, indexes_dir
from .farm_orchestrate import op1_record, op2_label, op3_human
from .farm_resources import memory_snapshot
from .instances import find_window_title, get_instance, list_instances
from .locks import get_lock, reclaim_dead_locks, release
from .streamers_lag import CLEAN_CONCURRENT, scan_recent_lag

ET = ZoneInfo("America/New_York")
REVIEW_URL = "http://127.0.0.1:3010/farm"
DEFAULT_INSTANCE = "player 0"  # BlueStacks engine Nougat32
DEFAULT_MINUTES = 20
SHORT_MINUTES = 10
PROBE_SECONDS = 2.0
LIVE_PEAK = 0.02
# Daytime: label every other idle loop so Ollama and capture do not stack.
LABEL_EVERY_N_IDLE = 2
# Measured ~7s/clip (Whisper window negligible; qwen dominates). Overnight burns backlog.
SEC_PER_CLIP_EST = 7.0
OVERNIGHT_LABEL_START_HOUR = 2  # 02:00 ET inclusive — multichannel + verdict
OVERNIGHT_LABEL_END_HOUR = 6  # 06:00 ET exclusive
OVERNIGHT_DRAFT_LIMIT = 80  # legacy Ollama; overnight prefers verdict path
DAY_DRAFT_LIMIT = 20
# Sessions processed per overnight / pause-day multichannel tick.
OVERNIGHT_VERDICT_SESSION_LIMIT = 2
VERDICT_URL = "http://127.0.0.1:3020/"
# Match locks.py mid-chunk grace: audio heartbeat quiet this long ⇒ not capturing.
AUDIO_HEARTBEAT_STALE_S = 1200.0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def schedule_window(now: datetime | None = None) -> dict[str, Any]:
    """Day = capture-first; overnight = label-first (no new record).

    Label cost (measured on this box): ~7 s/clip with qwen2.5:14b after Whisper.
    A 20‑minute take @ 60 s clips ≈ 20 clips ≈ 2.3 minutes to draft.
    Overnight 02:00–06:00 ET clears backlogs via multichannel while Streamers sleeps.
    """
    local = (now or datetime.now(ET)).astimezone(ET)
    hour = local.hour
    overnight = OVERNIGHT_LABEL_START_HOUR <= hour < OVERNIGHT_LABEL_END_HOUR
    if overnight:
        return {
            "mode": "overnight_verdict",
            "local_et": local.isoformat(),
            "do_record": False,
            "do_label": True,
            "label_path": "verdict",
            "label_every_n": 1,
            "draft_limit": OVERNIGHT_DRAFT_LIMIT,
            "verdict_session_limit": OVERNIGHT_VERDICT_SESSION_LIMIT,
            "sec_per_clip_est": SEC_PER_CLIP_EST,
            "auto_paid_ad": False,
            "why": (
                "02:00–06:00 ET — multichannel (vision+ASR+acoustic) consensus auto-locks; "
                "disagreements → /verdict; no new TV record"
            ),
        }
    return {
        "mode": "day_capture",
        "local_et": local.isoformat(),
        "do_record": True,
        # Daytime: capture-first. When capture_pause is on, loop still runs verdict backfill.
        "do_label": False,
        "label_path": "verdict",
        "label_every_n": LABEL_EVERY_N_IDLE,
        "draft_limit": DAY_DRAFT_LIMIT,
        "verdict_session_limit": OVERNIGHT_VERDICT_SESSION_LIMIT,
        "sec_per_clip_est": SEC_PER_CLIP_EST,
        "auto_paid_ad": False,
        "why": (
            "Daytime — capture unless capture_pause; owner clears /verdict disagrees; "
            "multichannel overnight 02:00–06:00 ET"
        ),
    }


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _python() -> Path:
    venv = _repo_root() / ".venv" / "Scripts" / "python.exe"
    return venv if venv.is_file() else Path(sys.executable)


def capture_busy(instance_id: str = DEFAULT_INSTANCE, root: Path | None = None) -> dict[str, Any] | None:
    return get_lock("streamers", instance_id, root=root)


def lock_audio_still_capturing(lock: dict[str, Any] | None, root: Path | None = None) -> dict[str, Any]:
    """True only when the locked session still looks like a live audio take.

    Picture heartbeat alone does not count — frame_watch can refresh while WAV
    writing is long dead (Bug 6 / MNF overnight).
    """
    import time

    if not lock:
        return {"capturing": False, "why": "no_lock"}
    sid = str(lock.get("session_id") or "")
    if not sid or sid.startswith("starting_"):
        return {"capturing": False, "why": "starting_or_empty"}
    session_dir = ensure_data_layout(root) / "authorized_sources" / sid
    if not session_dir.is_dir():
        return {"capturing": False, "why": "missing_session_dir"}
    hb = session_dir / "_audio_heartbeat.json"
    if not hb.is_file():
        return {"capturing": False, "why": "no_audio_heartbeat"}
    try:
        data = json.loads(hb.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"capturing": False, "why": "bad_audio_heartbeat"}
    state = str(data.get("state") or "")
    if state in {"done", "stopped", "error"}:
        return {"capturing": False, "why": f"audio_state:{state}"}
    age = time.time() - hb.stat().st_mtime
    if age >= AUDIO_HEARTBEAT_STALE_S:
        return {"capturing": False, "why": f"audio_heartbeat_stale:{int(age)}s"}
    return {"capturing": True, "why": f"audio_live:{state or 'ok'}", "age_s": round(age, 1)}


def prepare_label_gate(
    instance_id: str,
    root: Path | None = None,
    *,
    overnight: bool = False,
    pause_active: bool = False,
) -> dict[str, Any]:
    """Reclaim dead/stale capture locks so overnight/pause labeling is not starved.

    Policy:
    - Always drop locks whose holder PID is dead (reclaim_dead_locks).
    - Overnight or capture_pause: if lock remains but audio is not capturing,
      release it and allow label (Bug 6 — MNF lock outlived the WAV).
    - Overnight with live audio still writing: keep skip (protect Streamers).
    """
    root = ensure_data_layout(root)
    dropped = reclaim_dead_locks(root)
    busy = capture_busy(instance_id, root)
    out: dict[str, Any] = {
        "busy": busy,
        "reclaimed_dead": dropped,
        "released_stale": None,
        "allow_label": busy is None or pause_active or overnight,
        "skip_for_live_capture": False,
    }
    if busy is None:
        out["allow_label"] = True
        return out
    audio = lock_audio_still_capturing(busy, root)
    out["audio"] = audio
    if pause_active:
        # Owner pause: label even if WAV still somehow writing; record stays off.
        out["allow_label"] = True
        out["skip_for_live_capture"] = False
        return out
    if overnight and not audio.get("capturing"):
        try:
            release("streamers", instance_id, root=root)
            out["released_stale"] = {"lock": busy, "why": audio.get("why")}
            out["busy"] = None
            out["allow_label"] = True
        except Exception as exc:  # noqa: BLE001
            out["released_stale"] = {"error": str(exc), "lock": busy}
            out["allow_label"] = False
        return out
    if overnight and audio.get("capturing"):
        out["allow_label"] = False
        out["skip_for_live_capture"] = True
        return out
    # Daytime + live lock: protect capture (historic skip_while_capturing).
    out["allow_label"] = False
    out["skip_for_live_capture"] = True
    return out


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
    from .streamers_alive import probe_streamers_down

    root = ensure_data_layout(root)
    inst = get_instance(instance_id, root)
    window_pat = str(inst.get("window_title") or "BlueStacks")
    title = find_window_title(window_pat)
    try:
        sal = salvation_status(instance_id, root=root)
    except Exception as exc:  # noqa: BLE001
        sal = {"ok": False, "error": str(exc), "screen": "unknown"}
    try:
        alive = probe_streamers_down(instance_id, root=root, save_shot=False)
    except Exception as exc:  # noqa: BLE001
        alive = {"ok": False, "down": True, "error": str(exc), "reason": f"alive_probe_failed:{exc}"}
    # Process-PID loopback is the farm default — do not require a VB-Cable device peak.
    audio_mode = str(inst.get("audio_capture") or "process").lower()
    if audio_mode in ("process", "process_loopback", "pid", "auto"):
        try:
            from .process_loopback import resolve_hd_player_pid

            hit = resolve_hd_player_pid(window_title=window_pat, instance_id=instance_id)
            audio = {
                "ok": True,
                "mode": "process",
                "pid": int(hit["pid"]),
                "title": hit.get("title") or hit.get("matched_title"),
            }
        except Exception as exc:  # noqa: BLE001
            audio = {"ok": False, "mode": "process", "error": str(exc)}
    else:
        audio = probe_loopback_peak(str(inst.get("loopback_device") or "MZ-631M"))
    if alive.get("down"):
        healthy = False
        reason = f"streamers down — {alive.get('reason') or 'error screen'}"
    else:
        healthy = bool(title) and bool(sal.get("ok")) and bool(audio.get("ok"))
        reason = (
            "on-air healthy — record without retune"
            if healthy
            else "not healthy for on-air record (need home + live loopback + visible window)"
        )
    return {
        "ok": healthy,
        "instance_id": instance_id,
        "window_title": title,
        "salvation": sal,
        "audio": audio,
        "streamers_alive": alive,
        "reason": reason,
    }


def identity_on_air_health(
    instance_id: str = DEFAULT_INSTANCE,
    *,
    root: Path | None = None,
    session_id: str | None = None,
    save_shot: bool = False,
) -> dict[str, Any]:
    """Atomic health gate: window/audio **and** heartbeat identity (no dup / lag / wrong).

    Desk must not start ``ON_AIR_CONTINUE`` on a fullscreen player that is the
    same game as another stream or a Pluto/pack filler.
    """
    root = ensure_data_layout(root)
    base = on_air_health(instance_id, root)
    try:
        from .heartbeat_fix import probe_heartbeat

        probe = probe_heartbeat(
            instance_id,
            session_id=session_id,
            root=root,
            save_shot=save_shot,
        )
    except Exception as exc:  # noqa: BLE001
        probe = {"ok": False, "failing": True, "reason": f"probe_error:{exc}", "identity": {}}

    probe_ok = bool(probe.get("ok"))
    base_ok = bool(base.get("ok"))
    ok = base_ok and probe_ok
    if not probe_ok:
        reason = str(probe.get("reason") or "identity_fail")
    elif not base_ok:
        reason = str(base.get("reason") or "not_healthy")
    else:
        reason = "identity_on_air_healthy"

    # Stamp STREAM_STATUS + farm_run receipt every gate check.
    try:
        from .stream_status import classify_root_cause, record

        ident = probe.get("identity") or {}
        record(
            instance_id,
            event="identity_on_air_health",
            ok=ok,
            detail=reason,
            session_id=session_id,
            selected_title=ident.get("selected_title"),
            network=ident.get("network"),
            calls=ident.get("calls"),
            market=ident.get("market") or ident.get("city"),
            channel_number=ident.get("channel_number"),
            program_key=ident.get("program_key"),
            program_title=ident.get("program_title"),
            root_cause=classify_root_cause(ok=ok, reason=reason),
            extra={
                "base_ok": base_ok,
                "probe_ok": probe_ok,
                "duplicate": (probe.get("duplicate") or {}).get("duplicate"),
            },
            root=root,
        )
    except Exception:
        pass

    return {
        "ok": ok,
        "instance_id": instance_id,
        "reason": reason,
        "base": base,
        "probe": probe,
        "identity": probe.get("identity") or {},
        "duplicate": probe.get("duplicate"),
        "receipt": {
            "checked_utc": _now(),
            "base_ok": base_ok,
            "probe_ok": probe_ok,
            "reason": reason,
        },
    }


def write_human_flag(human: dict[str, Any], root: Path | None = None) -> dict[str, Any]:
    root = ensure_data_layout(root)
    idx = indexes_dir(root)
    digest: dict[str, Any] | None = None
    try:
        from .farm_draft import promote_help_queue
        from .farm_label_audit import write_daily_digest

        promote_help_queue(root)
        digest = write_daily_digest(root)
    except Exception as exc:  # noqa: BLE001
        digest = {"ok": False, "error": str(exc)}
    verdict_pending = None
    try:
        triage_path = farm_label_dir(root) / "audit" / "EPISODE_TRIAGE.json"
        if triage_path.is_file():
            blob = json.loads(triage_path.read_text(encoding="utf-8"))
            verdict_pending = sum(len(s.get("episodes") or []) for s in (blob.get("sessions") or []))
    except Exception:
        verdict_pending = None
    flag = idx / "farm_human_needed.flag"
    required = bool(human.get("required")) or bool(verdict_pending and verdict_pending > 0)
    gate = {
        "updated_utc": _now(),
        "required": required,
        "reason": human.get("reason"),
        "review_url": VERDICT_URL,
        "farm_url": REVIEW_URL,
        "help_asks": human.get("help_asks"),
        "verdict_pending": verdict_pending,
        "backlog_level": human.get("backlog_level"),
        "morning_batch": (digest or {}).get("morning_batch") if isinstance(digest, dict) else None,
        "daily_path": str(idx / "farm_labels" / "DAILY_LABEL.md"),
    }
    (idx / "farm_human_gate.json").write_text(json.dumps(gate, indent=2), encoding="utf-8")
    if gate["required"]:
        flag.write_text(
            f"HUMAN NEEDED\n{gate['updated_utc']}\n{VERDICT_URL}\n"
            f"Clear /verdict disagreements (pending≈{verdict_pending}). "
            f"Legacy farm pile={gate.get('help_asks')} — overnight consensus drains it.\n"
            f"{gate.get('reason')}\n",
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

    # Owner pause + overnight stale-lock reclaim (Bug 6).
    pause_active = False
    try:
        from .capture_pause import is_paused

        pause_active = bool(is_paused(root).get("active"))
    except Exception:
        pause_active = False
    overnight = str(sched.get("mode") or "").startswith("overnight")
    gate = prepare_label_gate(
        instance_id,
        root,
        overnight=overnight,
        pause_active=pause_active,
    )
    out["capture_pause"] = {"active": pause_active}
    out["label_gate"] = {
        "reclaimed_dead": len(gate.get("reclaimed_dead") or []),
        "released_stale": gate.get("released_stale"),
        "audio": gate.get("audio"),
        "allow_label": gate.get("allow_label"),
    }
    if gate.get("reclaimed_dead"):
        out["steps"].append(
            {
                "step": "reclaimed_dead_locks",
                "n": len(gate["reclaimed_dead"]),
                "keys": [r.get("key") for r in gate["reclaimed_dead"][:5]],
            }
        )
    if gate.get("released_stale"):
        out["steps"].append(
            {
                "step": "overnight_released_stale_lock",
                "detail": "Audio capture idle — released lock so multichannel/verdict can run",
                "released": gate["released_stale"],
            }
        )
    busy = gate.get("busy")
    out["busy"] = busy

    if busy and gate.get("skip_for_live_capture") and not pause_active:
        out["steps"].append(
            {
                "step": "skip_while_capturing",
                "detail": (
                    "Capture lock held with live audio — no label tick, no new record "
                    "(protect Streamers from lag)."
                ),
                "lock": busy,
                "audio": gate.get("audio"),
            }
        )
        out["human"] = write_human_flag(op3_human(root), root)
        out["plan"] = {
            "daypart": (op1_record(root).get("hierarchy") or {}).get("daypart"),
            "skipped_full_plan": True,
        }
        if overnight:
            try:
                from .farm_verdict_audit import append_verdict_tick

                append_verdict_tick(
                    {
                        "mode": sched.get("mode"),
                        "ok": True,
                        "trigger": "overnight",
                        "skip_reason": "live_audio_lock",
                        "label_gate": out.get("label_gate"),
                        "memory_avail_gb": mem.get("avail_gb"),
                        "why": "lock held with live audio heartbeat",
                    },
                    root=root,
                )
            except Exception:
                pass
        _write_loop_state(out, root)
        return out
    if busy and pause_active:
        out["steps"].append(
            {
                "step": "stale_lock_ignored",
                "detail": "capture_pause active — labeling despite capture lock; record stays off",
                "lock": busy,
            }
        )

    # During capture pause, force verdict backfill even in daytime.
    label_path = str(sched.get("label_path") or "verdict")
    if pause_active and not do_label:
        do_label = True
        label_path = "verdict"
        out["steps"].append(
            {
                "step": "label_forced_by_pause",
                "detail": "TV paused — run multichannel consensus / verdict backlog",
            }
        )

    pass_state = _idle_pass_state(root)
    idle_pass = int(pass_state.get("idle_pass") or 0) + 1
    pass_state["idle_pass"] = idle_pass
    _save_idle_pass_state(root, pass_state)
    label_due = (idle_pass % max(1, label_every_n)) == 0

    # 1) Label pass — verdict/multichannel (preferred) or legacy Ollama draft
    if do_label and label_due and mem.get("allow_label", True):
        if label_path == "verdict":
            try:
                from .farm_label_lock import status as label_lock_status
                from .farm_verdict_audit import append_verdict_tick

                lock_st = label_lock_status(root)
                # Overnight: one detached worker runs until 06:00 ET (continuous drain).
                # Pause-day / loop: same worker with --require-pause, or skip if busy.
                if lock_st.get("held") and lock_st.get("alive") and not lock_st.get("stale"):
                    out["label"] = {
                        "path": "verdict",
                        "ok": True,
                        "skipped": True,
                        "reason": "label_pass_busy",
                        "lock": lock_st,
                    }
                    out["steps"].append({"step": "verdict_pass_busy", "lock": lock_st})
                    append_verdict_tick(
                        {
                            "mode": sched.get("mode"),
                            "ok": True,
                            "trigger": "overnight" if overnight else ("capture_pause" if pause_active else "loop"),
                            "skip_reason": "label_pass_busy",
                            "label_gate": out.get("label_gate"),
                            "memory_avail_gb": mem.get("avail_gb"),
                            "why": "single-flight multichannel already running",
                        },
                        root=root,
                    )
                else:
                    worker = _spawn_verdict_worker(
                        root,
                        overnight=overnight,
                        pause_active=pause_active,
                    )
                    out["label"] = {"path": "verdict", "spawned": worker}
                    out["steps"].append({"step": "verdict_worker_spawn", **worker})
                    append_verdict_tick(
                        {
                            "mode": sched.get("mode"),
                            "ok": bool(worker.get("ok")),
                            "trigger": "overnight" if overnight else ("capture_pause" if pause_active else "loop"),
                            "skip_reason": None if worker.get("ok") else "spawn_failed",
                            "error": worker.get("error"),
                            "label_gate": out.get("label_gate"),
                            "memory_avail_gb": mem.get("avail_gb"),
                            "why": worker.get("detail") or "spawned continuous verdict backfill",
                        },
                        root=root,
                    )
            except Exception as exc:  # noqa: BLE001
                out["label"] = {"path": "verdict", "ok": False, "error": str(exc)}
                out["steps"].append({"step": "verdict_multichannel_failed", "error": str(exc)})
                try:
                    from .farm_verdict_audit import append_verdict_tick

                    append_verdict_tick(
                        {
                            "mode": sched.get("mode"),
                            "ok": False,
                            "trigger": "capture_pause" if pause_active else ("overnight" if overnight else "loop"),
                            "error": str(exc),
                            "label_gate": out.get("label_gate"),
                            "memory_avail_gb": mem.get("avail_gb"),
                            "skip_reason": "error",
                        },
                        root=root,
                    )
                except Exception:
                    pass
        else:
            label = op2_label(root, run_tick=True, model=model, draft_limit=draft_limit)
            try:
                from .export_farm_acoustic_gold import export as export_farm_gold

                out["acoustic_gold_export"] = export_farm_gold(rebuild=True, clean_only=True)
            except Exception as exc:  # noqa: BLE001
                out["acoustic_gold_export"] = {"ok": False, "error": str(exc)}
            out["label"] = {
                "path": "ollama_draft",
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
        if label_path == "verdict" and (overnight or pause_active):
            try:
                from .farm_verdict_audit import append_verdict_tick

                append_verdict_tick(
                    {
                        "mode": sched.get("mode"),
                        "ok": True,
                        "trigger": "capture_pause" if pause_active else "overnight",
                        "skip_reason": reason,
                        "label_gate": out.get("label_gate"),
                        "memory_avail_gb": mem.get("avail_gb"),
                        "why": sched.get("why"),
                    },
                    root=root,
                )
            except Exception:
                pass

    # 2) Human gate
    human = op3_human(root)
    out["human"] = write_human_flag(human, root)
    out["steps"].append({"step": "human_gate", "required": human.get("required")})

    # 2b) Streamers down + stuck-state recover (522, empty guide, decode error…)
    try:
        from .streamers_alive import ensure_streamers_alive
        from .streamers_recover import ensure_ready_for_open

        alive = ensure_streamers_alive(instance_id, root=root, recover=True)
        stuck = ensure_ready_for_open(instance_id, root=root)
        try:
            from .frame_watch import watch_and_recover

            frames = watch_and_recover(instance_id, root=root)
            out["frame_watch"] = {
                "latest_verdict": (frames.get("watch") or {}).get("latest_verdict"),
                "needs_recover": (frames.get("watch") or {}).get("needs_recover"),
                "recovered": bool(frames.get("recovery")),
            }
            out["steps"].append(
                {
                    "step": "frame_watch",
                    "verdict": out["frame_watch"]["latest_verdict"],
                    "needs_recover": out["frame_watch"]["needs_recover"],
                }
            )
        except Exception as fw_exc:  # noqa: BLE001
            out["frame_watch"] = {"ok": False, "error": str(fw_exc)}
        out["streamers_alive"] = {
            "ok": alive.get("ok"),
            "recovered": alive.get("recovered"),
            "reason": ((alive.get("probe") or {}).get("reason") or (alive.get("recovery") or {}).get("after") or {}).get(
                "reason"
            )
            if isinstance(alive.get("probe"), dict)
            else None,
            "probe": alive.get("probe"),
            "recovery": alive.get("recovery") if alive.get("recovered") else None,
        }
        out["streamers_recover"] = {
            "ok": stuck.get("ok"),
            "final_kind": stuck.get("final_kind"),
            "steps": stuck.get("steps"),
        }
        out["steps"].append(
            {
                "step": "streamers_alive",
                "ok": bool(alive.get("ok")),
                "recovered": bool(alive.get("recovered")),
                "down_reason": (alive.get("probe") or {}).get("reason"),
            }
        )
        out["steps"].append(
            {
                "step": "streamers_recover",
                "ok": bool(stuck.get("ok")),
                "final_kind": stuck.get("final_kind"),
            }
        )
    except Exception as exc:  # noqa: BLE001
        out["streamers_alive"] = {"ok": False, "error": str(exc)}
        out["steps"].append({"step": "streamers_alive_failed", "error": str(exc)})

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
    # TNF Thursday hold: leave the instance free for schedule run-due / TNF_PRIME.
    try:
        from .tnf_thursday import tnf_hold_active

        hold = tnf_hold_active()
        out["tnf_hold"] = hold
        if hold.get("active") and do_record:
            do_record = False
            out["steps"].append(
                {
                    "step": "tnf_hold",
                    "skipped_record": True,
                    "why": hold.get("why"),
                }
            )
    except Exception as exc:  # noqa: BLE001
        out["tnf_hold"] = {"active": False, "error": str(exc)}

    try:
        from .capture_pause import is_paused

        pause = is_paused(root)
        out["capture_pause"] = pause
        if pause.get("active") and do_record:
            do_record = False
            out["steps"].append(
                {
                    "step": "capture_pause",
                    "why": pause.get("why"),
                    "detail": "TV record paused by owner flag",
                }
            )
    except Exception as exc:  # noqa: BLE001
        out["capture_pause"] = {"active": False, "error": str(exc)}

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


def _spawn_verdict_worker(
    root: Path,
    *,
    overnight: bool,
    pause_active: bool,
) -> dict[str, Any]:
    """Detach continuous multichannel backfill so the 15m farm loop stays short."""
    root = ensure_data_layout(root)
    log_dir = root / "work" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_log = log_dir / f"verdict_worker_{stamp}.log"
    err_log = log_dir / f"verdict_worker_{stamp}.err"
    cmd = [
        str(_python()),
        "-m",
        "tools.windows_lab.farm_verdict_backfill",
        "--batch",
        "1",
        "--hop-s",
        "5",
        "--sleep-s",
        "3",
        "--trigger",
        "overnight" if overnight else ("capture_pause" if pause_active else "loop"),
    ]
    if overnight:
        cmd.extend(["--until-hour-et", str(OVERNIGHT_LABEL_END_HOUR)])
    if pause_active and not overnight:
        cmd.append("--require-pause")
    try:
        # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP on Windows
        creationflags = 0x00000008 | 0x00000200 if os.name == "nt" else 0
        with out_log.open("w", encoding="utf-8") as out_fh, err_log.open("w", encoding="utf-8") as err_fh:
            proc = subprocess.Popen(
                cmd,
                cwd=str(_repo_root()),
                env={**os.environ, "OHUSH_DATA_ROOT": str(root)},
                stdout=out_fh,
                stderr=err_fh,
                creationflags=creationflags,
            )
        return {
            "ok": True,
            "pid": proc.pid,
            "log": str(out_log),
            "err": str(err_log),
            "cmd": cmd,
            "detail": (
                f"detached verdict worker pid={proc.pid} "
                f"({'until '+str(OVERNIGHT_LABEL_END_HOUR)+' ET' if overnight else 'pause/loop'})"
            ),
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc), "cmd": cmd}


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
    hidden = farm / "run_farm_hidden.vbs"
    hidden.write_text(
        "\r\n".join(
            [
                "' Hidden launcher — no console flash",
                'Set sh = CreateObject("WScript.Shell")',
                f'sh.Run "cmd /c ""{wrapper}""", 0, True',
                "",
            ]
        ),
        encoding="ascii",
        newline="\r\n",
    )
    ps1 = farm / "register_farm_loop.ps1"
    script = f"""# Register OHush farm autonomy loop (every {minutes} minutes)
$ErrorActionPreference = "Stop"
$taskName = "OHushFarmLoop"
$hidden = {json.dumps(str(hidden))}
$action = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "//B //Nologo `"$hidden`""
# Finite repetition duration — MaxValue is rejected by Task Scheduler on this host.
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes {minutes}) -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 2) -Hidden
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Write-Output "Registered $taskName (hidden via $hidden; every {minutes} min)"
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
    alive_p = sub.add_parser("streamers-alive", help="Probe Streamers error screens (522); optional recover")
    alive_p.add_argument("--recover", action="store_true", help="Force-stop + relaunch if down")
    alive_p.add_argument("--instance", default=DEFAULT_INSTANCE)
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
    if args.cmd == "streamers-alive":
        from .streamers_alive import ensure_streamers_alive, probe_streamers_down

        iid = args.instance or ready_instance_id(root) or DEFAULT_INSTANCE
        if args.recover:
            out = ensure_streamers_alive(iid, root=root, recover=True)
        else:
            probe = probe_streamers_down(iid, root=root)
            out = {"ok": bool(probe.get("ok")), "probe": probe, "recovered": False}
        print(json.dumps(out, indent=2))
        return 0 if out.get("ok") else 1
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
