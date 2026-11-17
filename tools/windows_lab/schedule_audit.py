"""Audit scheduled guide captures: did they start, and is the tape healthy?

Building block: every guide-backed job should be checkable in one command.
Writes JSON + a short markdown board under indexes/.
"""

from __future__ import annotations

import json
import os
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import ensure_data_layout
from .locks import get_lock
from .scheduler import _parse_when, load_jobs, save_jobs

ET_HINT = "America/New_York"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def audit_path(root: Path | None = None) -> Path:
    return ensure_data_layout(root) / "indexes" / "schedule_audit.json"


def audit_board_path(root: Path | None = None) -> Path:
    return ensure_data_layout(root) / "indexes" / "SCHEDULE_AUDIT.md"


def _session_dir(root: Path, session_id: str) -> Path:
    return ensure_data_layout(root) / "authorized_sources" / session_id


def _find_session_for_job(job: dict[str, Any], root: Path) -> str | None:
    """Best-effort link: job.session_id, lock, or newest matching channel dir."""
    if job.get("session_id"):
        return str(job["session_id"])
    kind = str(job.get("source_kind") or "streamers")
    resource = str(job.get("instance_id") or job.get("tuner_id") or "")
    lock = get_lock(kind, resource, root=root) if resource else None
    if lock and job.get("status") in ("started", "running"):
        sid = lock.get("session_id")
        if sid and str(job.get("channel_id") or "") in str(sid):
            return str(sid)
        if sid and job.get("started_utc"):
            return str(sid)

    channel = str(job.get("channel_id") or "")
    base = ensure_data_layout(root) / "authorized_sources"
    if not base.is_dir() or not channel:
        return None
    started = None
    if job.get("started_utc"):
        try:
            started = _parse_when(str(job["started_utc"]))
        except ValueError:
            started = None
    candidates: list[tuple[float, str]] = []
    for d in base.iterdir():
        if not d.is_dir():
            continue
        name = d.name
        if channel not in name:
            continue
        mtime = d.stat().st_mtime
        if started is not None:
            # Prefer sessions created near start (±2h).
            delta = abs(mtime - started.timestamp())
            if delta > 7200:
                continue
            candidates.append((delta, name))
        else:
            candidates.append((-mtime, name))
    if not candidates:
        return None
    candidates.sort()
    return candidates[0][1]


def _wav_seconds(path: Path) -> float | None:
    try:
        with wave.open(str(path), "rb") as wf:
            frames = wf.getnframes()
            rate = wf.getframerate() or 1
            return frames / float(rate)
    except Exception:  # noqa: BLE001
        return None


def inspect_session(session_id: str, root: Path | None = None, *, expected_minutes: float | None = None) -> dict[str, Any]:
    root = ensure_data_layout(root)
    out_dir = _session_dir(root, session_id)
    stills_dir = out_dir / "stills"
    wavs = sorted(out_dir.glob("audio_*.wav"))
    # Legacy / in-flight process-loopback may only leave a single full WAV.
    legacy_wavs = sorted(out_dir.glob("_process_loopback_full.wav"))
    audio_files = list(wavs) + [p for p in legacy_wavs if p not in wavs]
    stills = sorted(stills_dir.glob("*.jpg")) + sorted(stills_dir.glob("*.jpeg")) + sorted(stills_dir.glob("*.png"))
    meta_path = out_dir / "meta.json"
    meta = None
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            meta = {"error": "invalid meta.json"}

    audio_bytes = sum(p.stat().st_size for p in audio_files)
    audio_sec = 0.0
    for w in audio_files:
        sec = _wav_seconds(w)
        if sec:
            audio_sec += sec

    newest_still = max((p.stat().st_mtime for p in stills), default=0.0)
    newest_wav = max((p.stat().st_mtime for p in audio_files), default=0.0)
    age_still = (_now().timestamp() - newest_still) if newest_still else None
    age_wav = (_now().timestamp() - newest_wav) if newest_wav else None

    # Live process-loopback heartbeat (written each chunk start/finish).
    from .process_loopback import HEARTBEAT_NAME

    hb_path = out_dir / HEARTBEAT_NAME
    heartbeat: dict[str, Any] | None = None
    age_hb: float | None = None
    if hb_path.is_file():
        try:
            heartbeat = json.loads(hb_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            heartbeat = {"error": "invalid_heartbeat"}
        age_hb = _now().timestamp() - hb_path.stat().st_mtime

    # Picture heartbeat: score newest still for blue spinner / cloud-network error.
    picture: dict[str, Any] | None = None
    age_pic: float | None = None
    if stills:
        try:
            from .frame_watch import heuristic_score, write_picture_heartbeat

            newest_still_path = max(stills, key=lambda p: p.stat().st_mtime)
            score = heuristic_score(newest_still_path)
            picture = write_picture_heartbeat(
                out_dir, still_path=newest_still_path, score=score
            )
            age_pic = 0.0
        except Exception as exc:  # noqa: BLE001
            picture = {"ok": False, "error": str(exc), "picture_ok": None}
    else:
        pic_path = out_dir / "_picture_heartbeat.json"
        if pic_path.is_file():
            try:
                picture = json.loads(pic_path.read_text(encoding="utf-8"))
                age_pic = _now().timestamp() - pic_path.stat().st_mtime
            except json.JSONDecodeError:
                picture = {"error": "invalid_picture_heartbeat", "picture_ok": None}

    expected_stills = None
    if expected_minutes:
        # av = ~1 fps; allow warm-up / screenrecord segment lag.
        expected_stills = max(0, int(expected_minutes * 60 * 0.7))

    # ADB stills come from ~170s screenrecord segments, then extract — allow 4 min gap.
    STILL_FRESH_S = 240.0
    # WAV lands each 15-min chunk; age can approach ~900s while the next chunk records.
    WAV_FRESH_S = 960.0
    # Heartbeat updates at chunk start; allow one full chunk + grace.
    HB_FRESH_S = 1080.0
    PIC_FRESH_S = 240.0

    hb_fresh = age_hb is not None and age_hb < HB_FRESH_S
    wav_fresh = age_wav is not None and age_wav < WAV_FRESH_S
    pic_fresh = age_pic is not None and age_pic < PIC_FRESH_S
    picture_ok = bool(picture and picture.get("picture_ok") is True)
    picture_bad = bool(
        picture
        and picture.get("picture_ok") is False
        and str(picture.get("state") or "")
        in {
            "blue_spinner",
            "cloud_network_error",
            "black_down",
            "error_overlay",
            "buffering",
            "flat_dark",
            "likely_black_or_buffer",
        }
    )
    # Legacy in-flight takes (pre chunked loopback) have no heartbeat and no mid-session WAVs.
    legacy_audio_ok = (
        heartbeat is None
        and not audio_files
        and age_still is not None
        and age_still < STILL_FRESH_S
    )

    checks: dict[str, Any] = {
        "session_dir_exists": out_dir.is_dir(),
        "has_audio": bool(audio_files) or audio_bytes > 0 or hb_fresh,
        "has_stills": len(stills) > 0,
        "stills_fresh": age_still is not None and age_still < STILL_FRESH_S,
        "stills_fresh_120s": age_still is not None and age_still < STILL_FRESH_S,  # alias for older callers
        "audio_progressing": bool(wav_fresh or hb_fresh or legacy_audio_ok),
        "audio_heartbeat_fresh": hb_fresh,
        "audio_wav_fresh": wav_fresh,
        "has_legacy_loopback": bool(legacy_wavs),
        "picture_heartbeat_fresh": pic_fresh,
        "picture_ok": picture_ok,
        "picture_bad": picture_bad,
    }
    if expected_stills is not None and len(stills) > 30:
        # Only enforce density after we clearly started.
        elapsed_guess = max(len(stills), int(audio_sec))
        checks["stills_density_ok"] = len(stills) >= min(expected_stills, int(elapsed_guess * 0.5))

    ok = checks["session_dir_exists"] and (checks["has_stills"] or checks["has_audio"])
    # Live take: recent stills + audio progressing + picture not a known dead overlay.
    # Stills advancing alone is not enough (blue spinner / cloud error freeze the slate).
    live_ok = bool(
        ok
        and checks.get("stills_fresh")
        and checks.get("audio_progressing")
        and not picture_bad
    )

    return {
        "session_id": session_id,
        "session_dir": str(out_dir),
        "exists": out_dir.is_dir(),
        "wav_count": len(wavs),
        "legacy_wav_count": len(legacy_wavs),
        "wav_bytes": audio_bytes,
        "audio_seconds": round(audio_sec, 1),
        "still_count": len(stills),
        "newest_still_age_s": round(age_still, 1) if age_still is not None else None,
        "newest_wav_age_s": round(age_wav, 1) if age_wav is not None else None,
        "audio_heartbeat_age_s": round(age_hb, 1) if age_hb is not None else None,
        "audio_heartbeat": heartbeat,
        "picture_heartbeat_age_s": round(age_pic, 1) if age_pic is not None else None,
        "picture_heartbeat": picture,
        "meta_channel_id": (meta or {}).get("channel_id") if isinstance(meta, dict) else None,
        "meta_job_id": (meta or {}).get("job_id") if isinstance(meta, dict) else None,
        "checks": checks,
        "ok": ok,
        "live_ok": live_ok,
    }


def _pid_alive(pid: int | None) -> bool | None:
    if not pid:
        return None
    try:
        if os.name == "nt":
            import ctypes

            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)
                return True
            return False
        os.kill(int(pid), 0)
        return True
    except OSError:
        return False
    except Exception:  # noqa: BLE001
        return None


def _pid_command_line(pid: int) -> str | None:
    """Best-effort Windows command line (detects PID reuse)."""
    if os.name != "nt":
        return None
    try:
        import subprocess

        out = subprocess.check_output(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                f"(Get-CimInstance Win32_Process -Filter \"ProcessId={int(pid)}\").CommandLine",
            ],
            text=True,
            timeout=8,
            stderr=subprocess.DEVNULL,
        )
        text = (out or "").strip()
        return text or None
    except Exception:  # noqa: BLE001
        return None


def _pid_is_our_capture(pid: int | None, job: dict[str, Any]) -> bool | None:
    """True only if pid is alive AND still our windows_lab session start."""
    alive = _pid_alive(pid)
    if alive is not True:
        return alive
    assert pid is not None
    cmd = _pid_command_line(int(pid))
    if cmd is None:
        # Could not read cmdline — treat as unknown (do not trust bare OpenProcess).
        return None
    low = cmd.lower()
    if "tools.windows_lab" not in low or "session" not in low:
        return False
    jid = str(job.get("job_id") or "")
    if jid and jid not in cmd:
        return False
    ch = str(job.get("channel_id") or "")
    if ch and ch not in cmd:
        return False
    return True


def audit_job(job: dict[str, Any], root: Path | None = None, *, now: datetime | None = None) -> dict[str, Any]:
    root = ensure_data_layout(root)
    now = now or _now()
    status = str(job.get("status") or "")
    start = _parse_when(str(job["start_utc"]))
    due = start <= now
    guide = job.get("guide") or {}
    shortcut_id = job.get("shortcut_id")
    our_pid = _pid_is_our_capture(job.get("pid"), job)

    row: dict[str, Any] = {
        "job_id": job.get("job_id"),
        "label": job.get("label"),
        "channel_id": job.get("channel_id"),
        "status": status,
        "start_utc": job.get("start_utc"),
        "minutes": job.get("minutes"),
        "due": due,
        "guide": guide,
        "shortcut_id": shortcut_id,
        "apply_channel": job.get("apply_channel"),
        "weekly": job.get("weekly"),
        "pid": job.get("pid"),
        "pid_alive": our_pid,
        "issues": [],
        "verdict": "unknown",
    }

    if status == "cancelled":
        row["verdict"] = "cancelled"
        return row
    if status == "failed":
        row["verdict"] = "failed"
        row["issues"].append(job.get("last_error") or "failed")
        return row
    if status == "scheduled" and not due:
        row["verdict"] = "waiting"
        return row
    if status == "scheduled" and due:
        row["verdict"] = "overdue"
        row["issues"].append("start time passed but status still scheduled (run-due blocked or task down)")
        lock = get_lock(str(job.get("source_kind")), str(job.get("instance_id") or ""), root=root)
        if lock:
            row["issues"].append(f"resource busy: {lock.get('session_id')}")
            row["lock"] = lock
        return row

    # started / running / completed
    session_id = _find_session_for_job(job, root)
    row["session_id"] = session_id
    if not session_id:
        if status in ("started", "running"):
            row["verdict"] = "started_no_session"
            row["issues"].append("no session dir linked yet")
            if row["pid_alive"] is False:
                row["issues"].append("detach pid dead")
                row["verdict"] = "dead"
        elif status == "completed":
            row["verdict"] = "completed_missing_tape"
            row["issues"].append("completed without session_id")
        return row

    elapsed_min = None
    # Prefer restarted_utc so a mid-window session restart can warm up again.
    for key in ("restarted_utc", "started_utc"):
        if not job.get(key):
            continue
        try:
            elapsed_min = (now - _parse_when(str(job[key]))).total_seconds() / 60.0
            break
        except ValueError:
            continue
    expected = elapsed_min if elapsed_min is not None else float(job.get("minutes") or 0)
    # Cap expected stills window to requested minutes.
    expected = min(expected, float(job.get("minutes") or expected or 0))

    tape = inspect_session(session_id, root, expected_minutes=expected)
    row["tape"] = tape

    if status == "completed":
        if tape.get("ok") and tape.get("still_count", 0) > 0 and tape.get("wav_count", 0) > 0:
            row["verdict"] = "healthy_complete"
        else:
            row["verdict"] = "thin_complete"
            row["issues"].append("completed session missing audio or stills")
        return row

    # Live
    hb_fresh = bool((tape.get("checks") or {}).get("audio_heartbeat_fresh"))
    checks = tape.get("checks") or {}
    picture_bad = bool(checks.get("picture_bad"))
    pic = tape.get("picture_heartbeat") or {}
    if tape.get("live_ok"):
        row["verdict"] = "healthy_live"
    elif picture_bad:
        # Stills/audio may still "advance" while Streamers shows spinner / cloud error.
        state = str(pic.get("state") or "picture_dead")
        recording_active = bool(
            our_pid is True
            and (
                checks.get("stills_fresh")
                or checks.get("audio_progressing")
                or checks.get("audio_heartbeat_fresh")
            )
        )
        row["recording_active"] = recording_active
        row["picture_state"] = state
        if recording_active:
            # Capture PID + fresh tape bytes — picture dead, not a dead take.
            row["verdict"] = "picture_dead_live"
            row["issues"].append(f"picture dead while capturing: {state}")
        else:
            row["verdict"] = "stale_live"
            row["issues"].append(f"picture heartbeat bad: {state}")
        for reason in (pic.get("reasons") or [])[:2]:
            row["issues"].append(str(reason))
    elif (elapsed_min or 0) < 4 and int(tape.get("still_count") or 0) == 0:
        # Empty dir / first ADB segment — never page as broken_live during warm-up.
        row["verdict"] = "warming"
        row["issues"].append("waiting for first still segment (~3 min)")
        if hb_fresh:
            row["issues"].append("audio heartbeat already live")
    elif tape.get("ok"):
        row["verdict"] = "stale_live"
        row["issues"].append("session exists but stills/audio not fresh")
    else:
        row["verdict"] = "broken_live"
        row["issues"].append("session dir weak or empty")

    if our_pid is False and status in ("started", "running"):
        row["issues"].append("capture pid dead or reused (not our session process)")
        # Dead process + not writing is not a live take — escalate to dead for remediate.
        if row["verdict"] in ("stale_live", "picture_dead_live", "broken_live", "warming"):
            row["verdict"] = "dead"

    return row


def _tape_worth_keeping(tape: dict[str, Any], *, minutes: float) -> bool:
    stills = int(tape.get("still_count") or 0)
    wavs = int(tape.get("wav_count") or 0) + int(tape.get("legacy_wav_count") or 0)
    audio_s = float(tape.get("audio_seconds") or 0)
    need_s = max(60.0, float(minutes or 0) * 60.0 * 0.5)
    return stills > 0 and wavs > 0 and audio_s >= min(need_s, 120.0)


def remediate_started_jobs(
    data: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Close dead/finished takes in place. Fix first — do not page bookkeeping.

    Returns list of remediation actions taken.
    """
    now = now or _now()
    by_id = {str(r.get("job_id")): r for r in rows if r.get("job_id")}
    actions: list[dict[str, Any]] = []
    for job in data.get("jobs") or []:
        if str(job.get("status") or "") not in ("started", "running"):
            continue
        jid = str(job.get("job_id") or "")
        row = by_id.get(jid) or {}
        verdict = str(row.get("verdict") or "")
        tape = row.get("tape") or {}
        minutes = float(job.get("minutes") or row.get("minutes") or 0)
        try:
            start = _parse_when(str(job.get("start_utc") or row.get("start_utc")))
        except Exception:  # noqa: BLE001
            continue
        window_end = start.timestamp() + minutes * 60.0 + 300.0  # +5 min grace
        window_over = now.timestamp() >= window_end
        pid_ours = row.get("pid_alive")
        stale_age = tape.get("newest_still_age_s")
        not_writing = stale_age is None or float(stale_age) > 180.0
        frozen_hard = stale_age is not None and float(stale_age) > 900.0  # >15 min
        audio_s = float(tape.get("audio_seconds") or 0)
        requested_s = max(0.0, minutes * 60.0)
        audio_done = requested_s > 0 and audio_s >= requested_s * 0.95

        should_close = False
        reason = ""
        if pid_ours is False and not_writing:
            should_close = True
            reason = "capture process gone; stills/audio not advancing"
        elif audio_done and not_writing:
            # Full tape already on disk; leftover started status must not SMS.
            should_close = True
            reason = "requested audio minutes reached; capture no longer advancing"
        elif window_over and not_writing and verdict in (
            "stale_live",
            "picture_dead_live",
            "broken_live",
            "dead",
            "healthy_live",
        ):
            # Window finished and nothing fresh — bookkeeping, not an outage page.
            should_close = True
            reason = "scheduled window ended; capture no longer advancing"
        elif frozen_hard and verdict in ("stale_live", "picture_dead_live", "broken_live", "dead"):
            # Mid-window + pid still ours: let recover_hung_live_jobs try first.
            # Close on the post-recover remediate pass, or when pid is gone / window over.
            recover = row.get("recover") or {}
            recover_done = bool(recover.get("attempted")) or bool(recover.get("skipped")) or bool(
                recover.get("reuse")
            )
            if window_over or audio_done or pid_ours is not True or recover_done:
                should_close = True
                reason = "stills/audio frozen >15 min; closing zombie started job"

        if not should_close:
            continue

        if _tape_worth_keeping(tape, minutes=minutes):
            job["status"] = "completed"
            job["completed_utc"] = _now_iso()
            job["closed_reason"] = "auto_remediate_complete"
            job["close_note"] = reason
            action = "completed"
        else:
            job["status"] = "failed"
            job["failed_utc"] = _now_iso()
            job["closed_reason"] = "auto_remediate_failed"
            job["last_error"] = reason
            action = "failed"

        job["closed_utc"] = _now_iso()
        actions.append(
            {
                "job_id": jid,
                "label": job.get("label"),
                "action": action,
                "reason": reason,
                "verdict_before": verdict,
                "stills": tape.get("still_count"),
                "audio_s": tape.get("audio_seconds"),
                "session_id": job.get("session_id") or row.get("session_id"),
                "instance_id": job.get("instance_id") or row.get("instance_id"),
            }
        )
    return actions


def _remediate_state_path(root: Path | None = None) -> Path:
    return ensure_data_layout(root) / "indexes" / "audit_remediate_state.json"


def _load_remediate_state(root: Path | None = None) -> dict[str, Any]:
    path = _remediate_state_path(root)
    if not path.is_file():
        return {"recover": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"recover": {}}
    data.setdefault("recover", {})
    return data


def _save_remediate_state(state: dict[str, Any], root: Path | None = None) -> None:
    path = _remediate_state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    state = dict(state)
    state["updated_utc"] = _now_iso()
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _auto_recover_enabled() -> bool:
    return os.environ.get("HUSH_AUDIT_AUTO_RECOVER", "1").strip().lower() not in (
        "0",
        "false",
        "no",
    )


def _stamp_recover_flags(rows: list[dict[str, Any]], *, root: Path | None = None) -> None:
    """Attach recover attempt metadata onto audit rows (survives row rebuilds)."""
    state = _load_remediate_state(root)
    tried = state.get("recover") or {}
    for row in rows:
        jid = str(row.get("job_id") or "")
        if not jid:
            continue
        if row.get("recover"):
            continue
        prior = tried.get(jid)
        if prior and prior.get("open"):
            row["recover"] = {
                "attempted": True,
                "ok": prior.get("ok"),
                "utc": prior.get("utc"),
                "reuse": True,
            }
        elif row.get("verdict") in ("stale_live", "picture_dead_live", "broken_live") and row.get(
            "pid_alive"
        ) is True:
            # Hung but not attempted yet (budget deferred or first sighting before recover call).
            row.setdefault("recover", {"attempted": False, "pending": True})


def recover_hung_live_jobs(
    data: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    root: Path | None = None,
    max_per_tick: int = 1,
) -> list[dict[str, Any]]:
    """For live hung / picture-dead takes: run the heartbeat fix route.

    At most ``max_per_tick`` fixes per audit (keeps the 1‑minute scheduler healthy).
    Spinner ladder may continue across ticks until exhausted; other fixes lock once.
    """
    root = ensure_data_layout(root)
    hung_verdicts = ("stale_live", "picture_dead_live", "broken_live")
    if not _auto_recover_enabled():
        for row in rows:
            if row.get("verdict") in hung_verdicts and row.get("pid_alive") is True:
                row["recover"] = {"attempted": False, "skipped": True, "reason": "auto_recover_disabled"}
        return []

    state = _load_remediate_state(root)
    tried = state.setdefault("recover", {})
    by_id = {str(j.get("job_id")): j for j in (data.get("jobs") or []) if j.get("job_id")}

    # Clear recover locks for jobs that are healthy / finished again.
    healthy_clear = {"healthy_live", "warming", "waiting", "healthy_complete", "cancelled"}
    for row in rows:
        jid = str(row.get("job_id") or "")
        if not jid or jid not in tried:
            continue
        status = str((by_id.get(jid) or {}).get("status") or row.get("status") or "")
        if row.get("verdict") in healthy_clear or status in ("completed", "failed", "cancelled"):
            row_state = tried.get(jid) or {}
            if row_state.get("open") or row_state.get("ladder_continue"):
                row_state["open"] = False
                row_state["ladder_continue"] = False
                row_state["cleared_utc"] = _now_iso()
                tried[jid] = row_state

    hung = [
        r
        for r in rows
        if r.get("verdict") in hung_verdicts
        and r.get("pid_alive") is True
        and r.get("job_id")
    ]
    for row in hung:
        jid = str(row["job_id"])
        prior = tried.get(jid) or {}
        if prior.get("open") and not prior.get("ladder_continue"):
            row["recover"] = {
                "attempted": True,
                "ok": prior.get("ok"),
                "utc": prior.get("utc"),
                "reuse": True,
                "route": prior.get("route") or "heartbeat_fix",
                "ladder_exhausted": prior.get("ladder_exhausted"),
            }

    # Block only hard-open locks; spinner ladder_continue stays eligible.
    blocked_ids = {
        jid
        for jid, st in tried.items()
        if isinstance(st, dict) and st.get("open") and not st.get("ladder_continue")
    }
    eligible_rows = [r for r in hung if str(r.get("job_id")) not in blocked_ids]

    from .heartbeat_fix import fix_failing_from_audit_rows

    actions = fix_failing_from_audit_rows(
        data,
        eligible_rows,
        root=root,
        max_per_tick=max_per_tick,
    )
    for action in actions:
        jid = str(action.get("job_id") or "")
        if not jid or action.get("skipped"):
            # Cooldown / deferred still marks attempted for notify streak context.
            if jid and action.get("ladder_continue"):
                tried[jid] = {
                    "open": False,
                    "ladder_continue": True,
                    "ok": False,
                    "ts": _now().timestamp(),
                    "utc": _now_iso(),
                    "instance_id": action.get("instance_id"),
                    "route": "spinner_ladder",
                    "reason": action.get("reason"),
                }
            continue
        ladder_continue = bool(action.get("ladder_continue"))
        ladder_exhausted = bool(action.get("ladder_exhausted"))
        tried[jid] = {
            # Keep open only when done (success or exhausted) — else re-enter ladder.
            "open": bool(action.get("ok")) or ladder_exhausted or not ladder_continue,
            "ladder_continue": ladder_continue and not ladder_exhausted,
            "ladder_exhausted": ladder_exhausted,
            "ok": bool(action.get("ok")),
            "ts": _now().timestamp(),
            "utc": _now_iso(),
            "instance_id": action.get("instance_id"),
            "route": "spinner_ladder" if ladder_continue or ladder_exhausted else "heartbeat_fix",
            "reason": action.get("reason"),
            "stage": action.get("stage"),
        }
        # Stamp row for notify this tick.
        for row in rows:
            if str(row.get("job_id")) == jid:
                row["recover"] = {
                    "attempted": True,
                    "ok": action.get("ok"),
                    "utc": _now_iso(),
                    "route": tried[jid]["route"],
                    "ladder_continue": ladder_continue,
                    "ladder_exhausted": ladder_exhausted,
                    "reason": action.get("reason"),
                    "stage": action.get("stage"),
                }

    state["recover"] = tried
    _save_remediate_state(state, root)
    return actions


def _board_md(report: dict[str, Any], *, root: Path | None = None) -> str:
    lines = [
        "# Schedule audit",
        "",
        f"Checked `{report.get('checked_utc')}`",
        "",
        f"Summary: **{report.get('summary', {}).get('healthy', 0)}** healthy · "
        f"**{report.get('summary', {}).get('attention', 0)}** need attention · "
        f"**{report.get('summary', {}).get('waiting', 0)}** waiting · "
        f"**{report.get('summary', {}).get('failed', 0)}** failed",
        "",
        "| When (UTC) | Label | Status | Verdict | Stills | Audio s | Issues |",
        "|---|---|---|---|---:|---:|---|",
    ]
    for row in report.get("jobs") or []:
        tape = row.get("tape") or {}
        issues = "; ".join(row.get("issues") or []) or "—"
        lines.append(
            f"| {str(row.get('start_utc') or '')[:19]} | {row.get('label') or row.get('channel_id')} | "
            f"{row.get('status')} | {row.get('verdict')} | {tape.get('still_count', '—')} | "
            f"{tape.get('audio_seconds', '—')} | {issues} |"
        )
    lines.append("")
    try:
        from .ui_dump import dump_health_board_md, dump_health_summary

        dump_sum = report.get("dump_health") or dump_health_summary(root)
        lines.append(dump_health_board_md(dump_sum, root=root).rstrip())
        lines.append("")
    except Exception as exc:  # noqa: BLE001
        lines.append(f"## Dump health\n\n_(unavailable: {exc})_\n")
    lines.append("Guide jobs carry `guide.search_query` / `guide.channel_title` / `shortcut_id`.")
    lines.append("Re-run: `python -m tools.windows_lab schedule audit`")
    lines.append("")
    return "\n".join(lines)


def audit_schedule(
    root: Path | None = None,
    *,
    include_finished: bool = True,
    stamp_session_ids: bool = True,
    remediate: bool = True,
    notify: bool = True,
) -> dict[str, Any]:
    root = ensure_data_layout(root)
    data = load_jobs(root)

    def _build_rows(jobs_data: dict[str, Any]) -> list[dict[str, Any]]:
        built: list[dict[str, Any]] = []
        for job in jobs_data.get("jobs") or []:
            status = str(job.get("status") or "")
            if not include_finished and status in ("completed", "cancelled", "failed"):
                continue
            row = audit_job(job, root)
            built.append(row)
            if stamp_session_ids and row.get("session_id") and not job.get("session_id"):
                job["session_id"] = row["session_id"]
        return built

    rows = _build_rows(data)
    remediations: list[dict[str, Any]] = []
    if remediate:
        remediations = remediate_started_jobs(data, rows)
        if remediations:
            save_jobs(data, root)
            rows = _build_rows(data)
        recovers = recover_hung_live_jobs(data, rows, root=root, max_per_tick=1)
        if recovers:
            remediations.extend(recovers)
            # Give stills/audio a moment to advance after Streamers recover.
            import time as _time

            _time.sleep(8.0)
            rows = _build_rows(data)
            # Close again if recover left a dead/finished take.
            more = remediate_started_jobs(data, rows)
            if more:
                remediations.extend(more)
                save_jobs(data, root)
                rows = _build_rows(data)
        # Re-stamp recover flags after any row rebuild (notify needs them).
        _stamp_recover_flags(rows, root=root)
        if remediations or stamp_session_ids:
            save_jobs(data, root)
    elif stamp_session_ids:
        save_jobs(data, root)

    healthy_v = {"healthy_live", "healthy_complete", "waiting", "warming"}
    fail_v = {"failed", "dead", "broken_live", "completed_missing_tape", "overdue"}
    wait_v = {"waiting", "warming"}
    summary = {
        "healthy": sum(1 for r in rows if r.get("verdict") in healthy_v),
        "attention": sum(
            1
            for r in rows
            if r.get("verdict") not in healthy_v | fail_v | wait_v | {"cancelled"}
        ),
        "waiting": sum(1 for r in rows if r.get("verdict") in wait_v),
        "failed": sum(1 for r in rows if r.get("verdict") in fail_v),
        "total": len(rows),
    }
    # One streak bump per job per audit tick (shared by notify + todo ingest).
    try:
        from .notify import _bump_verdict_streak

        for row in rows:
            jid = str(row.get("job_id") or "")
            if not jid:
                continue
            row["verdict_streak"] = _bump_verdict_streak(
                jid, str(row.get("verdict") or ""), root=root
            )
    except Exception:  # noqa: BLE001
        pass

    dump_health: dict[str, Any] = {}
    try:
        from .ui_dump import dump_health_summary

        dump_health = dump_health_summary(root, hours=24.0)
    except Exception as exc:  # noqa: BLE001
        dump_health = {"ok": False, "error": str(exc)}

    report = {
        "checked_utc": _now_iso(),
        "summary": summary,
        "jobs": rows,
        "remediations": remediations,
        "dump_health": dump_health,
        "ok": summary["failed"] == 0
        and summary["attention"] == 0
        and bool(dump_health.get("ok", True)),
    }
    path = audit_path(root)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    board = audit_board_path(root)
    board.write_text(_board_md(report, root=root), encoding="utf-8")
    report["audit_json"] = str(path)
    report["audit_board"] = str(board)
    if notify:
        try:
            from .notify import notify_from_audit

            report["notifications"] = notify_from_audit(report, root=root)
        except Exception as exc:  # noqa: BLE001
            report["notifications"] = [{"ok": False, "error": str(exc)}]
    else:
        report["notifications"] = []
    # Open-model punch list (ingest even if notify cooldown skipped SMS).
    try:
        from .open_model_todos import ingest_from_audit, ingest_ui_dump_health, write_board

        report["open_model_todos"] = ingest_from_audit(report, root=root)
        report["dump_todos"] = ingest_ui_dump_health(dump_health, root=root)
        write_board(root=root)
    except Exception as exc:  # noqa: BLE001
        report["open_model_todos"] = [{"ok": False, "error": str(exc)}]
    # Unified farm ops log + board (best-effort).
    try:
        from .farm_ops import emit, write_ops_board

        for rem in remediations:
            if not isinstance(rem, dict):
                continue
            action = str(rem.get("action") or "remediate")
            # Normalize bookkeeping closes onto the lifecycle contract.
            event = "closed" if action in {"completed", "failed"} else action
            if action in {"recover_picture", "heartbeat_fix"}:
                event = "recover"
            emit(
                event,
                detail=str(rem.get("reason") or action),
                job_id=str(rem.get("job_id") or "") or None,
                session_id=str(rem.get("session_id") or "") or None,
                instance_id=str(rem.get("instance_id") or "") or None,
                stills=rem.get("stills"),
                audio_s=rem.get("audio_s"),
                ok=action != "failed",
                extra={
                    k: rem.get(k)
                    for k in ("verdict_before", "action", "ok")
                    if k in rem
                },
                root=root,
            )
        # Attention-only (healthy_live every minute would flood the run log).
        for row in rows:
            v = str(row.get("verdict") or "")
            if v not in {
                "overdue",
                "stale_live",
                "picture_dead_live",
                "broken_live",
                "dead",
                "started_no_session",
            }:
                continue
            tape = row.get("tape") or {}
            pic = tape.get("picture_heartbeat") or {}
            emit(
                f"audit_{v}",
                detail="; ".join(row.get("issues") or []) or v,
                job_id=str(row.get("job_id") or "") or None,
                session_id=str(row.get("session_id") or "") or None,
                stills=tape.get("still_count"),
                audio_s=tape.get("audio_seconds"),
                still_age=tape.get("newest_still_age_s"),
                hb_age=tape.get("audio_heartbeat_age_s"),
                pid=row.get("pid"),
                ok=False,
                extra={
                    "picture_state": pic.get("state"),
                    "picture_ok": pic.get("picture_ok"),
                }
                if pic
                else None,
                root=root,
            )
        report["ops_board"] = write_ops_board(root).get("board")
    except Exception as exc:  # noqa: BLE001
        report["ops_board_error"] = str(exc)
    return report


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="Audit capture schedule health")
    p.add_argument("--include-finished", action="store_true", default=True)
    p.add_argument("--active-only", action="store_true")
    args = p.parse_args(argv)
    report = audit_schedule(include_finished=not args.active_only)
    print(json.dumps(report, indent=2))
    return 0 if report.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
