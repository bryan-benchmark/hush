"""HUSH ERROR alerts via SendGrid email + Twilio SMS.

Secrets live outside git: C:\\OHushData\\farm\\notify.env (or process env).
Never commit API keys. Rotate any key that was pasted into chat.
"""

from __future__ import annotations

import json
import os
import ssl
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import ensure_data_layout, farm_dir


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:  # noqa: BLE001
        return ssl.create_default_context()

# Debounce file so the 1-minute audit tick does not spam.
STATE_NAME = "notify_state.json"
ENV_NAME = "notify.env"

# Events that page a human (stuck / data at risk).
ALERT_EVENTS = {
    "capture_stale": "Stills/audio stopped advancing while session should be live",
    "capture_picture_dead": "Picture spinner/dead while capture still writing — ladder exhausted",
    "capture_dead": "Capture process/lock died mid-take",
    "audit_broken_live": "Audit verdict broken_live / started_no_session",
    "audit_overdue": "Scheduled job past start but never started",
    "guide_open_failed": "Guide search-open failed before record",
    "streamers_down": "Streamers not MainActivity / slate recovery failed",
    "crosstalk": "Multi-instance audio isolation failed",
    "disk_pressure": "Disk free below safe threshold for capture",
    "upload_failed": "GCS Standard upload of audited session failed",
    "shadow_stalled": "Shadow scorer not writing decisions for active tape",
    "label_backlog_critical": "Draft/human backlog critical (optional)",
}

# Informational — email only by default, or suppressed unless HUSH_NOTIFY_INFO=1.
INFO_EVENTS = {
    "capture_started": "Scheduled capture started",
    "capture_healthy_complete": "Take finished audit-green",
    "upload_ok": "Audited session landed in GCS Standard",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def notify_env_path(root: Path | None = None) -> Path:
    return farm_dir(root) / ENV_NAME


def _parse_env_file(path: Path) -> dict[str, str]:
    loaded: dict[str, str] = {}
    if not path.is_file():
        return loaded
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key:
            loaded[key] = val
    return loaded


def load_notify_env(root: Path | None = None) -> dict[str, str]:
    """Load local env into os.environ (does not override already-set vars).

    Order (later files fill gaps only): repo `.env` → `C:\\OHushData\\farm\\notify.env`.
    """
    repo_env = Path(__file__).resolve().parents[2] / ".env"
    paths = [repo_env, notify_env_path(root)]
    loaded: dict[str, str] = {}
    for path in paths:
        for key, val in _parse_env_file(path).items():
            loaded[key] = val
            if key not in os.environ:
                os.environ[key] = val
    return loaded


def _state_path(root: Path | None = None) -> Path:
    return ensure_data_layout(root) / "indexes" / STATE_NAME


def _load_state(root: Path | None = None) -> dict[str, Any]:
    path = _state_path(root)
    if not path.is_file():
        return {"sent": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"sent": {}}


def _save_state(state: dict[str, Any], root: Path | None = None) -> None:
    path = _state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    state["updated_utc"] = _now_iso()
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _cooldown_s() -> int:
    try:
        return max(60, int(os.environ.get("HUSH_NOTIFY_COOLDOWN_S") or "1800"))
    except ValueError:
        return 1800


def _once_until_clear() -> bool:
    """Default on: one page per open fault; no 30‑min nag while still broken."""
    return os.environ.get("HUSH_NOTIFY_ONCE", "1").strip().lower() not in ("0", "false", "no")


def _state_key(event: str, key: str) -> str:
    return f"{event}:{key}"


def _should_send(event: str, key: str, root: Path | None = None) -> bool:
    state = _load_state(root)
    sent = state.setdefault("sent", {})
    row = sent.get(_state_key(event, key)) or {}
    if _once_until_clear():
        # Stay quiet until audit clears this fault (open → False).
        if row.get("open"):
            return False
        return True
    last = float(row.get("ts") or 0)
    if time.time() - last < _cooldown_s():
        return False
    return True


def _mark_sent(event: str, key: str, root: Path | None = None) -> None:
    state = _load_state(root)
    sent = state.setdefault("sent", {})
    sent[_state_key(event, key)] = {
        "ts": time.time(),
        "utc": _now_iso(),
        "open": True,
    }
    _save_state(state, root)


def clear_alert(event: str, key: str, root: Path | None = None) -> bool:
    """Mark an alert cleared so a future recurrence can page again."""
    state = _load_state(root)
    sent = state.setdefault("sent", {})
    sk = _state_key(event, key)
    row = sent.get(sk)
    if not row:
        return False
    if not row.get("open"):
        return False
    row["open"] = False
    row["cleared_utc"] = _now_iso()
    sent[sk] = row
    _save_state(state, root)
    return True


def clear_alerts_except(
    active: set[tuple[str, str]],
    root: Path | None = None,
) -> list[str]:
    """Clear any open alert not in this audit's active (event, key) set."""
    state = _load_state(root)
    sent = state.setdefault("sent", {})
    cleared: list[str] = []
    for sk, row in list(sent.items()):
        if not isinstance(row, dict) or not row.get("open"):
            continue
        if ":" not in sk:
            continue
        event, _, key = sk.partition(":")
        if (event, key) in active:
            continue
        row["open"] = False
        row["cleared_utc"] = _now_iso()
        sent[sk] = row
        cleared.append(sk)
    if cleared:
        _save_state(state, root)
    return cleared


def _hush_brand_text(text: str) -> str:
    """Strip company branding from alert title/body (From address may still be *@benchmark.care)."""
    import re

    out = text or ""
    # Redact emails on the old domain first so they never appear in copy.
    out = re.sub(r"(?i)\b[\w.+-]+@benchmark\.care\b", "[redacted]", out)
    out = re.sub(r"(?i)\bbenchmark(?:\.care)?\b", "HUSH", out)
    out = re.sub(r"(?i)\s*\(not\s+HUSH\)\s*", " ", out)
    out = re.sub(r"[ \t]{2,}", " ", out)
    return out.strip()


def _send_email(subject: str, body: str) -> dict[str, Any]:
    api_key = os.environ.get("SENDGRID_API_KEY") or ""
    # From may be a verified *@benchmark.care address — that is fine.
    # Never put "Benchmark" in subject, body, or From display name.
    from_email = (
        os.environ.get("SENDGRID_FROM_EMAIL_HUSH")
        or os.environ.get("HUSH_FROM_EMAIL")
        or os.environ.get("SENDGRID_FROM_EMAIL")
        or ""
    ).strip()
    from_name = (os.environ.get("SENDGRID_FROM_NAME") or "HUSH").strip() or "HUSH"
    if "benchmark" in from_name.lower():
        from_name = "HUSH"
    reply_to = (
        os.environ.get("SENDGRID_REPLY_TO")
        or os.environ.get("HUSH_ALERT_EMAIL")
        or from_email
    )
    to_email = os.environ.get("HUSH_ALERT_EMAIL") or ""
    if not api_key or not from_email or not to_email:
        return {"ok": False, "channel": "email", "error": "email not configured"}
    clean_subject = _hush_brand_text(subject)
    clean_body = _hush_brand_text(body)
    payload = {
        "personalizations": [{"to": [{"email": to_email}]}],
        "from": {"email": from_email, "name": from_name},
        "reply_to": {"email": reply_to, "name": "HUSH"},
        "subject": clean_subject,
        "content": [{"type": "text/plain", "value": clean_body}],
        "categories": ["hush-error"],
    }
    req = urllib.request.Request(
        "https://api.sendgrid.com/v3/mail/send",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20, context=_ssl_context()) as resp:
            return {"ok": 200 <= resp.status < 300, "channel": "email", "status": resp.status}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        return {"ok": False, "channel": "email", "error": f"HTTP {exc.code}", "detail": detail}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "channel": "email", "error": str(exc)}


def _send_sms(text: str) -> dict[str, Any]:
    sid = os.environ.get("TWILIO_ACCOUNT_SID") or ""
    token = os.environ.get("TWILIO_AUTH_TOKEN") or ""
    from_phone = os.environ.get("TWILIO_FROM") or os.environ.get("TWILIO_PHONE_NUMBER") or ""
    to_phone = os.environ.get("HUSH_ALERT_SMS") or ""
    if not sid or not token or not from_phone or not to_phone:
        return {"ok": False, "channel": "sms", "error": "sms not configured"}
    # Twilio REST: application/x-www-form-urlencoded
    import base64
    from urllib.parse import urlencode

    body = _hush_brand_text(text)[:1500]
    data = urlencode({"From": from_phone, "To": to_phone, "Body": body}).encode("utf-8")
    auth = base64.b64encode(f"{sid}:{token}".encode("ascii")).decode("ascii")
    req = urllib.request.Request(
        f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
        data=data,
        headers={
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20, context=_ssl_context()) as resp:
            return {"ok": 200 <= resp.status < 300, "channel": "sms", "status": resp.status}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        return {"ok": False, "channel": "sms", "error": f"HTTP {exc.code}", "detail": detail}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "channel": "sms", "error": str(exc)}


def notify(
    event: str,
    *,
    detail: str = "",
    dedupe_key: str | None = None,
    force: bool = False,
    channels: str | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Send HUSH ERROR (or info) notification.

    channels: "email,sms" | "email" | "sms" | "auto"
      auto = email+sms for ALERT_EVENTS, email-only for INFO unless HUSH_NOTIFY_INFO=1
    """
    load_notify_env(root)
    key = dedupe_key or event
    is_alert = event in ALERT_EVENTS
    is_info = event in INFO_EVENTS
    if not is_alert and not is_info:
        # Unknown events treated as alerts so we never swallow a new failure class.
        is_alert = True

    if is_info and os.environ.get("HUSH_NOTIFY_INFO", "0") not in ("1", "true", "yes"):
        return {"ok": True, "skipped": True, "reason": "info_suppressed", "event": event}

    # Always queue alerts for the open-model todo list (even when SMS is on cooldown).
    todo_row = None
    if is_alert:
        try:
            from .open_model_todos import ingest_hush

            todo_row = ingest_hush(
                event,
                key=key,
                detail=detail,
                source="hush_notify",
                root=root,
            )
        except Exception as exc:  # noqa: BLE001
            todo_row = {"ok": False, "error": str(exc)}

    if not force and not _should_send(event, key, root):
        reason = "open_until_clear" if _once_until_clear() else "cooldown"
        try:
            from .farm_ops import emit

            emit(
                "notify_suppressed",
                detail=reason,
                job_id=key if key != event else None,
                ok=True,
                extra={"event": event, "key": key},
                root=root,
            )
        except Exception:  # noqa: BLE001
            pass
        return {
            "ok": True,
            "skipped": True,
            "reason": reason,
            "event": event,
            "key": key,
            "todo": todo_row,
        }

    why = ALERT_EVENTS.get(event) or INFO_EVENTS.get(event) or event
    subject = f"HUSH ERROR: {event}" if is_alert else f"HUSH: {event}"
    clean_detail = _hush_brand_text(detail.strip())
    body = (
        f"{subject}\n\n"
        f"{why}\n\n"
        f"{clean_detail}\n\n"
        f"— HUSH lab alert\n"
        f"utc={_now_iso()}\n"
        f"event={event}\n"
        f"key={key}\n"
    )
    sms_text = (
        f"HUSH ERROR {event}: {clean_detail[:200]}"
        if is_alert
        else f"HUSH {event}: {clean_detail[:200]}"
    )

    ch = (channels or "auto").lower()
    want_email = ch in ("auto", "email", "email,sms", "sms,email", "both")
    want_sms = ch in ("sms", "email,sms", "sms,email", "both") or (ch == "auto" and is_alert)

    results: list[dict[str, Any]] = []
    if want_email:
        results.append(_send_email(subject, body))
    if want_sms:
        results.append(_send_sms(sms_text))

    ok_any = any(r.get("ok") for r in results) if results else False
    if ok_any:
        _mark_sent(event, key, root)

    # Append to local log (no secrets)
    log_dir = ensure_data_layout(root) / "work" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    with (log_dir / "hush_notify.log").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"utc": _now_iso(), "event": event, "key": key, "results": results}) + "\n")

    try:
        from .farm_ops import emit

        emit(
            "notify_sent" if ok_any else "notify_failed",
            detail=event,
            job_id=key if key != event else None,
            ok=ok_any,
            extra={
                "event": event,
                "key": key,
                "channels": [
                    {"channel": r.get("channel") or r.get("via"), "ok": r.get("ok")}
                    for r in results
                    if isinstance(r, dict)
                ],
            },
            root=root,
        )
    except Exception:  # noqa: BLE001
        pass

    return {"ok": ok_any, "event": event, "key": key, "results": results, "todo": todo_row}


def _stale_page_after() -> int:
    """Consecutive stale audits required before SMS (ADB segment gaps are 1–2 ticks)."""
    try:
        return max(1, int(os.environ.get("HUSH_NOTIFY_STALE_STREAK") or "3"))
    except ValueError:
        return 3


def _bump_verdict_streak(jid: str, verdict: str, root: Path | None = None) -> int:
    state = _load_state(root)
    streaks = state.setdefault("streaks", {})
    row = streaks.get(jid) or {}
    if row.get("verdict") == verdict:
        n = int(row.get("n") or 0) + 1
    else:
        n = 1
    streaks[jid] = {"verdict": verdict, "n": n, "utc": _now_iso()}
    _save_state(state, root)
    return n


def _read_verdict_streak(jid: str, verdict: str, root: Path | None = None) -> int:
    state = _load_state(root)
    row = (state.get("streaks") or {}).get(jid) or {}
    if row.get("verdict") != verdict:
        return 0
    return int(row.get("n") or 0)


def notify_from_audit(report: dict[str, Any], root: Path | None = None) -> list[dict[str, Any]]:
    """Page only faults that still need a human after audit remediation.

    Dead/finished takes are auto-closed in ``schedule_audit.remediate_started_jobs``
    and must not SMS. ``stale_live`` pages only when our capture pid is still alive
    (real hung take), not when a recycled Windows PID fooled a bare alive check.
    """
    out: list[dict[str, Any]] = []
    # Keep open alerts for jobs still in attention so a 1-tick healthy flicker
    # cannot clear+repage the same fault.
    protect: set[tuple[str, str]] = set()
    for job in report.get("jobs") or []:
        verdict = str(job.get("verdict") or "")
        jid = str(job.get("job_id") or "")
        label = str(job.get("label") or job.get("channel_id") or jid)
        issues = "; ".join(job.get("issues") or []) or verdict
        tape = job.get("tape") or {}
        detail = (
            f"{label} job={jid} verdict={verdict} "
            f"stills={tape.get('still_count')} audio_s={tape.get('audio_seconds')} {issues}"
        )

        recover = job.get("recover") or {}
        recover_done = bool(recover.get("attempted")) or bool(recover.get("skipped"))
        # Prefer streak stamped by audit_schedule; fall back to state file.
        streak = int(job.get("verdict_streak") or 0)
        if not streak and jid:
            streak = _read_verdict_streak(jid, verdict, root=root)
        event: str | None = None
        ladder_exhausted = bool(recover.get("ladder_exhausted"))
        ladder_continue = bool(recover.get("ladder_continue"))
        if verdict == "overdue":
            # run-due already ran in the same scheduler tick before audit.
            event = "audit_overdue"
        elif (
            verdict == "picture_dead_live"
            and job.get("pid_alive") is True
            and ladder_exhausted
            and streak >= _stale_page_after()
        ):
            # Spinner while capturing — page only after full ladder exhaust.
            event = "capture_picture_dead"
        elif (
            verdict == "stale_live"
            and job.get("pid_alive") is True
            and recover_done
            and not ladder_continue
            and streak >= _stale_page_after()
        ):
            # Hung live take — require consecutive stale ticks (skip ADB segment gaps).
            event = "capture_stale"
        elif (
            verdict in ("broken_live", "started_no_session")
            and job.get("pid_alive") is True
            and recover_done
            and streak >= 2
        ):
            # Second consecutive broken after warm-up window — real attach failure.
            event = "audit_broken_live"
        elif verdict == "healthy_complete":
            out.append(
                notify("capture_healthy_complete", detail=detail, dedupe_key=jid, root=root)
            )
        # picture_dead_live while ladder still climbing: quiet
        # dead / thin_complete / failed / stale with dead pid: no page (remediated or bookkeeping)
        # hung but recover still pending this tick: quiet — next audit pages if still bad
        # warming / single-gap stale: quiet

        if jid and verdict in {
            "overdue",
            "stale_live",
            "picture_dead_live",
            "broken_live",
            "started_no_session",
            "dead",
        }:
            protect.add(("audit_overdue", jid))
            protect.add(("capture_stale", jid))
            protect.add(("capture_picture_dead", jid))
            protect.add(("audit_broken_live", jid))

        if event and jid:
            protect.add((event, jid))
            out.append(notify(event, detail=detail, dedupe_key=jid, root=root))

    cleared = clear_alerts_except(protect, root=root)
    if cleared:
        out.append({"ok": True, "cleared": cleared})
    return out


def write_env_template(root: Path | None = None) -> Path:
    path = notify_env_path(root)
    if path.is_file():
        return path
    path.write_text(
        "\n".join(
            [
                "# HUSH notify — KEEP OUT OF GIT (lives under OHushData)",
                "# From may be a verified *@benchmark.care address; subject/body never say Benchmark.",
                "SENDGRID_API_KEY=",
                "SENDGRID_FROM_EMAIL_HUSH=",
                "SENDGRID_FROM_EMAIL=",
                "SENDGRID_FROM_NAME=HUSH",
                "SENDGRID_REPLY_TO=",
                "HUSH_ALERT_EMAIL=",
                "TWILIO_ACCOUNT_SID=",
                "TWILIO_AUTH_TOKEN=",
                "TWILIO_FROM=",
                "HUSH_ALERT_SMS=",
                "# 1 = page once per open fault (default). 0 = re-page every HUSH_NOTIFY_COOLDOWN_S.",
                "HUSH_NOTIFY_ONCE=1",
                "HUSH_NOTIFY_COOLDOWN_S=1800",
                "HUSH_NOTIFY_INFO=0",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return path


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="HUSH ERROR notify")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("events", help="List alert/info event ids")
    t = sub.add_parser("test", help="Send a test HUSH ERROR")
    t.add_argument("--event", default="capture_stale")
    t.add_argument("--detail", default="manual test from notify CLI")
    t.add_argument("--force", action="store_true")
    t.add_argument("--channels", default="auto")
    sub.add_parser("template", help="Write notify.env template under OHushData/farm")
    args = p.parse_args(argv)
    if args.cmd == "events":
        print(json.dumps({"alert": ALERT_EVENTS, "info": INFO_EVENTS}, indent=2))
        return 0
    if args.cmd == "template":
        path = write_env_template()
        print(json.dumps({"ok": True, "path": str(path)}, indent=2))
        return 0
    if args.cmd == "test":
        load_notify_env()
        print(json.dumps(notify(args.event, detail=args.detail, force=args.force, channels=args.channels), indent=2))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
