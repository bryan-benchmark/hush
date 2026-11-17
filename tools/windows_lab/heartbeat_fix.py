"""Heartbeat fix route — any stream with a failing picture/audio heartbeat.

Route (locked, one instance at a time):
  probe → recover Streamers → ensure picture → re-open channel/shortcut → verify

Audit calls this on ``stale_live`` / ``broken_live`` / picture_bad so a blue
spinner or cloud-network card cannot sit forever while stills keep landing.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import ensure_data_layout
from .locks import get_lock
from .scheduler import load_jobs

STATE_NAME = "heartbeat_fix_state.json"
DEFAULT_COOLDOWN_S = 180.0
# Tunable: how long guide / frozen frames may sit before heartbeat fails.
DEFAULT_GUIDE_STUCK_S = 90.0
DEFAULT_SEARCH_STUCK_S = 60.0
# Same-frame trip: 1 minute of unchanged pixels fails heartbeat (menu or player).
DEFAULT_FRAME_FREEZE_S = 60.0
# After N intended_channel_hold failures, stop thrashing reopen/jiggle for M seconds.
# Session keeps capturing (hold tape) — see root_cause intended_hold_keep_tape.
DEFAULT_HOLD_FAIL_CAP = 3
DEFAULT_HOLD_QUIET_S = 600.0

GUIDE_KINDS = frozenset(
    {"guide", "guide_like", "empty_event_guide", "search_ui", "search_hub"}
)
PLAYING_KINDS = frozenset({"player_chrome", "player_fullscreen"})
# Instant fail — not a Streamers picture (BlueStacks store / power sheet).
HARD_FAIL_KINDS = frozenset({"bluestacks_home", "power_dialog", "player_hard_error"})


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _state_path(root: Path | None = None) -> Path:
    return ensure_data_layout(root) / "indexes" / STATE_NAME


def _load_state(root: Path | None = None) -> dict[str, Any]:
    path = _state_path(root)
    if not path.is_file():
        return {"instances": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"instances": {}}
    data.setdefault("instances", {})
    return data


def _save_state(state: dict[str, Any], root: Path | None = None) -> None:
    path = _state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    state = dict(state)
    state["updated_utc"] = _now_iso()
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _env_float(name: str, default: float, *, minimum: float = 5.0) -> float:
    try:
        return max(minimum, float(os.environ.get(name) or default))
    except ValueError:
        return default


def _cooldown_s() -> float:
    return _env_float("HUSH_HEARTBEAT_FIX_COOLDOWN_S", DEFAULT_COOLDOWN_S, minimum=30.0)


def _hold_fail_cap() -> int:
    try:
        return max(1, int(os.environ.get("HUSH_INTENDED_HOLD_FAIL_CAP") or DEFAULT_HOLD_FAIL_CAP))
    except ValueError:
        return DEFAULT_HOLD_FAIL_CAP


def _hold_quiet_s() -> float:
    return _env_float("HUSH_INTENDED_HOLD_QUIET_S", DEFAULT_HOLD_QUIET_S, minimum=60.0)


def _clear_intended_hold(inst_state: dict[str, Any]) -> None:
    inst_state.pop("intended_hold_fails", None)
    inst_state.pop("intended_hold_quiet_until", None)
    inst_state.pop("intended_hold_last_root_cause", None)
    inst_state.pop("intended_hold_channel_id", None)


def _arm_intended_hold(
    inst_state: dict[str, Any],
    *,
    root_cause: str,
    channel_id: str | None = None,
) -> dict[str, Any]:
    """Count hold failures; after cap, quiet the desk tick loop."""
    fails = int(inst_state.get("intended_hold_fails") or 0) + 1
    inst_state["intended_hold_fails"] = fails
    inst_state["intended_hold_last_root_cause"] = root_cause
    inst_state["intended_hold_channel_id"] = channel_id
    quiet: dict[str, Any] = {"fails": fails, "cap": _hold_fail_cap(), "quiet_armed": False}
    if fails >= _hold_fail_cap():
        until = _now().timestamp() + _hold_quiet_s()
        inst_state["intended_hold_quiet_until"] = until
        quiet["quiet_armed"] = True
        quiet["quiet_s"] = _hold_quiet_s()
        quiet["quiet_until_unix"] = until
    return quiet


def guide_stuck_s() -> float:
    """Seconds on channel guide / search hub before heartbeat fails (fine-tune via env)."""
    return _env_float("HUSH_GUIDE_STUCK_S", DEFAULT_GUIDE_STUCK_S)


def search_stuck_s() -> float:
    return _env_float("HUSH_SEARCH_STUCK_S", DEFAULT_SEARCH_STUCK_S)


def frame_freeze_s() -> float:
    """Seconds of unchanged frames before heartbeat fails (fine-tune via env)."""
    return _env_float("HUSH_FRAME_FREEZE_S", DEFAULT_FRAME_FREEZE_S)


def _auto_enabled() -> bool:
    return os.environ.get("HUSH_HEARTBEAT_AUTO_FIX", "1").strip().lower() not in (
        "0",
        "false",
        "no",
    )


def _classify_ui(picture: dict[str, Any]) -> str:
    """UI kind from alive-probe texts / activity (guide vs player)."""
    from .streamers_recover import classify

    texts = list(picture.get("texts") or [])
    activity = str(picture.get("activity") or "")
    kind = classify(texts, activity=activity)
    # Accessibility empty + frozen dark-ish slate often still a dead player.
    if kind in {"unknown", "player_or_blank"} and (picture.get("frame_score") or {}).get("freeze", {}).get(
        "frozen"
    ):
        return "player_or_blank"
    return kind


def _bootstrap_stuck_since(
    instance_id: str,
    *,
    root: Path | None = None,
    frame_path: str | None = None,
) -> float | None:
    """Backdate stuck clock from a recent streak of recover snaps for this instance.

    Guide clocks tick, so we do not require pixel-identical frames — a dense
    streak of snaps (no long gap) means the booth has been dumping this
    instance continuously, usually while stuck.
    """
    root = ensure_data_layout(root)
    probe = root / "work" / "streamers_recover"
    if not probe.is_dir():
        return None
    snaps = sorted(probe.glob(f"{instance_id}_*.png"), key=lambda p: p.stat().st_mtime)
    if frame_path and Path(frame_path).is_file():
        snaps.append(Path(frame_path))
        snaps = sorted(set(snaps), key=lambda p: p.stat().st_mtime)
    if len(snaps) < 2:
        return None
    newest = snaps[-1]
    # Gap > 3 minutes breaks the streak (someone left and came back).
    oldest = newest
    for prev in reversed(snaps[:-1]):
        if newest.stat().st_mtime - prev.stat().st_mtime > 1800:
            break
        if oldest.stat().st_mtime - prev.stat().st_mtime > 180:
            break
        oldest = prev
    if oldest is newest:
        return None
    return float(oldest.stat().st_mtime)


def _frame_fingerprint(path: Path | None) -> str | None:
    if not path or not Path(path).is_file():
        return None
    try:
        from PIL import Image, ImageStat

        im = Image.open(path).convert("RGB")
        im.thumbnail((64, 36))
        stat = ImageStat.Stat(im)
        # Coarse signature — enough to tell freeze vs cut.
        means = ",".join(f"{m:.1f}" for m in stat.mean)
        return f"{im.size[0]}x{im.size[1]}:{means}:{Path(path).stat().st_size}"
    except Exception:  # noqa: BLE001
        try:
            return f"size:{Path(path).stat().st_size}"
        except OSError:
            return None


def update_liveness_timers(
    instance_id: str,
    *,
    ui_kind: str,
    frame_path: str | None = None,
    frozen_now: bool | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Track how long this instance has been on guide / frozen. Tunable thresholds.

    Env:
      HUSH_GUIDE_STUCK_S   (default 90) — channel guide too long
      HUSH_SEARCH_STUCK_S  (default 60) — search hub too long
      HUSH_FRAME_FREEZE_S  (default 60) — frames unchanged too long (menu or player)
    """
    root = ensure_data_layout(root)
    now_ts = _now().timestamp()
    state = _load_state(root)
    row = dict((state.get("instances") or {}).get(instance_id) or {})

    prev_kind = str(row.get("ui_kind") or "")
    kind_changed = ui_kind != prev_kind
    # Explicit post-fix reset clears sticky guide clocks so open-model can restart.
    if row.get("post_fix_reset"):
        row["ui_kind"] = ui_kind
        row["ui_kind_since"] = now_ts
        row.pop("stuck_reason", None)
        row.pop("ui_kind_since_bootstrapped", None)
        row.pop("post_fix_reset", None)
        kind_changed = True
    elif kind_changed:
        row["ui_kind"] = ui_kind
        row["ui_kind_since"] = now_ts
        # Bootstrap only when entering a guide/search kind from a playing kind —
        # never re-backdate while already stuck (that permanently blocks restart).
        if prev_kind and prev_kind not in GUIDE_KINDS and ui_kind in GUIDE_KINDS:
            boot = _bootstrap_stuck_since(instance_id, root=root, frame_path=frame_path)
            if boot:
                row["ui_kind_since"] = min(float(row["ui_kind_since"]), boot)
                row["ui_kind_since_bootstrapped"] = True
    else:
        row.setdefault("ui_kind", ui_kind)
        row.setdefault("ui_kind_since", now_ts)

    # Freeze: prefer explicit flag from double-snap; else fingerprint vs last frame.
    fp = _frame_fingerprint(Path(frame_path)) if frame_path else None
    if frozen_now is None and fp and row.get("last_frame_fp"):
        frozen_now = fp == row.get("last_frame_fp")
    if frozen_now:
        if not row.get("freeze_since"):
            boot = _bootstrap_stuck_since(instance_id, root=root, frame_path=frame_path)
            row["freeze_since"] = boot or now_ts
    else:
        row.pop("freeze_since", None)
    if fp:
        row["last_frame_fp"] = fp
    if frame_path:
        row["last_frame"] = str(frame_path)

    # Guide clocks tick — that alone does not clear a true pixel freeze. Same
    # frames for FRAME_FREEZE_S on search/menu still fail (owner: 1 min static).
    kind_age = now_ts - float(row.get("ui_kind_since") or now_ts)
    freeze_age = (now_ts - float(row["freeze_since"])) if row.get("freeze_since") else 0.0

    guide_limit = search_stuck_s() if ui_kind in {"search_ui", "search_hub"} else guide_stuck_s()
    guide_stuck = ui_kind in GUIDE_KINDS and kind_age >= guide_limit
    freeze_limit = frame_freeze_s()
    freeze_stuck = freeze_age >= freeze_limit
    # Blank / unknown / decode error with long freeze is also stuck.
    blank_stuck = ui_kind in {"player_or_blank", "unknown", "player_decode_error"} and freeze_stuck
    hard_fail = ui_kind in HARD_FAIL_KINDS

    stuck_reason = None
    if hard_fail:
        stuck_reason = f"hard_fail:{ui_kind}"
    elif guide_stuck:
        stuck_reason = f"guide_stuck:{ui_kind}:{int(kind_age)}s>={int(guide_limit)}s"
    elif blank_stuck:
        stuck_reason = f"blank_frozen:{ui_kind}:{int(freeze_age)}s"
    elif freeze_stuck and ui_kind in PLAYING_KINDS:
        # Playing chrome but pixels frozen (slate / hung decode) — still a fail.
        stuck_reason = f"picture_frozen:{int(freeze_age)}s>={int(freeze_limit)}s"
    elif freeze_stuck and ui_kind in GUIDE_KINDS:
        stuck_reason = f"menu_frozen:{ui_kind}:{int(freeze_age)}s>={int(freeze_limit)}s"
    elif freeze_stuck:
        stuck_reason = f"frames_frozen:{int(freeze_age)}s>={int(freeze_limit)}s"

    row["kind_age_s"] = round(kind_age, 1)
    row["freeze_age_s"] = round(freeze_age, 1)
    row["stuck_reason"] = stuck_reason
    row["last_probe_utc"] = _now_iso()
    # Keep prior fix bookkeeping keys.
    state.setdefault("instances", {})[instance_id] = row
    _save_state(state, root)

    return {
        "ui_kind": ui_kind,
        "kind_age_s": round(kind_age, 1),
        "freeze_age_s": round(freeze_age, 1),
        "guide_stuck_s": guide_limit,
        "frame_freeze_s": frame_freeze_s(),
        "stuck": bool(stuck_reason),
        "stuck_reason": stuck_reason,
    }


def _emit(**kwargs: Any) -> None:
    try:
        from .farm_ops import emit

        emit(**kwargs)
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# Spinner / picture-dead ladder (Bug 4)
# Wait/buffer → jiggle → reopen → hard recover → exhausted hold.
# One stage per call so desk/audit ticks escalate without thrashing.
# Every stage emits farm_run event ``spinner_ladder`` for forensics.
# ---------------------------------------------------------------------------

SPINNER_PIC_STATES = frozenset(
    {
        "blue_spinner",
        "buffering",
        "cloud_network_error",
        "black_down",
        "flat_dark",
        "likely_black_or_buffer",
        "error_overlay",
    }
)

SPINNER_LADDER_STAGES: tuple[str, ...] = (
    "wait_buffer",
    "jiggle",
    "channel_hop",  # ch+ then ch- back (ESPN + locals)
    "wait_after_hop",
    "reopen_intended",
    "wait_after_reopen",
    "alternate_local",  # locals only — skipped/logged for ESPN/named linear
    "reopen_or_hard_recover",
    "jiggle_final",
    "exhausted",
)


def spinner_wait_s() -> float:
    return _env_float("HUSH_SPINNER_WAIT_S", 20.0, minimum=5.0)


def spinner_stage_cooldown_s() -> float:
    """Min seconds between ladder stages across desk/audit ticks."""
    return _env_float("HUSH_SPINNER_STAGE_COOLDOWN_S", 35.0, minimum=10.0)


def spinner_exhausted_cooldown_s() -> float:
    """After ladder exhausts, hold before re-entering (keep tape, stop spam)."""
    return _env_float("HUSH_SPINNER_EXHAUSTED_COOLDOWN_S", 300.0, minimum=60.0)


def _is_spinner_fail(reason: str, probe: dict[str, Any] | None = None) -> bool:
    """True when picture is spinner/buffer/cloud — not a frozen-stills stale take."""
    blob = f"{reason or ''}".lower()
    if any(
        k in blob
        for k in (
            "blue_spinner",
            "picture_blue_spinner",
            "session_picture:blue_spinner",
            "buffering",
            "cloud_network",
            "black_down",
            "picture_dead",
        )
    ):
        return True
    probe = probe or {}
    for key in ("session_picture", "picture"):
        node = probe.get(key) or {}
        state = str(node.get("state") or node.get("picture_verdict") or "")
        if state in SPINNER_PIC_STATES:
            return True
        score = node.get("frame_score") or {}
        if str(score.get("verdict") or "") in SPINNER_PIC_STATES:
            return True
    pic = probe.get("picture") or {}
    if str(pic.get("picture_verdict") or "") in SPINNER_PIC_STATES:
        return True
    score = pic.get("frame_score") or {}
    if str(score.get("verdict") or "") in SPINNER_PIC_STATES:
        return True
    return False


def _spinner_cleared(probe: dict[str, Any]) -> bool:
    """Success = heartbeat ok and no spinner/buffer state left."""
    if not probe or probe.get("failing") or not probe.get("ok"):
        return False
    if _is_spinner_fail(str(probe.get("reason") or ""), probe):
        return False
    return True


def _spinner_ladder_key(instance_id: str, job: dict[str, Any]) -> str:
    jid = str(job.get("job_id") or "").strip()
    if jid:
        return f"job:{jid}"
    return f"inst:{instance_id}"


def _job_is_named_linear(
    job: dict[str, Any],
    channel_id: str | None,
    shortcut_id: str | None,
) -> bool:
    """ESPN / MNF / nav linear — may hop channels, must NEVER swap to a local."""
    if job.get("nav_route") or str(job.get("open_via") or "").lower() == "nav":
        return True
    blob = " ".join(
        str(x or "")
        for x in (channel_id, shortcut_id, job.get("label"), job.get("channel_id"), job.get("shortcut_id"))
    ).upper()
    tokens = (
        "ESPN",
        "MNF_",
        "TNF_",
        "NFL_",
        "NBA_",
        "NHL_",
        "CFB_",
        "MANNINGCAST",
        "SPORTSCENTER",
    )
    if any(t in blob for t in tokens):
        return True
    try:
        from .streamers_open import LINEAR_NAV_BY_SHORTCUT

        sid = str(shortcut_id or channel_id or "").upper()
        if sid in LINEAR_NAV_BY_SHORTCUT:
            return True
    except Exception:
        pass
    return False


def _job_is_local_capture(
    job: dict[str, Any],
    channel_id: str | None,
    shortcut_id: str | None,
    *,
    root: Path | None = None,
) -> bool:
    """True when alternate-local swap is allowed (not ESPN/named linear)."""
    if _job_is_named_linear(job, channel_id, shortcut_id):
        return False
    sid = str(shortcut_id or channel_id or job.get("shortcut_id") or job.get("channel_id") or "")
    if not sid:
        return False
    try:
        from .streamers_open import get_shortcut

        row = get_shortcut(sid, root=root)
        if str(row.get("kind") or "").lower() == "local":
            return True
    except Exception:
        pass
    u = sid.upper()
    if u.endswith("_LOCAL") or u.endswith("_NY") or u.endswith("_ATL") or u.endswith("_LA"):
        return True
    if any(u.startswith(p) for p in ("ABC_", "CBS_", "NBC_", "FOX_")):
        return True
    try:
        from .us_locals import network_from_channel_id

        return bool(network_from_channel_id(u))
    except Exception:
        return False


def _load_spinner_ladder(root: Path | None, key: str) -> dict[str, Any]:
    state = _load_state(root)
    ladders = state.setdefault("spinner_ladders", {})
    row = ladders.get(key) or {}
    return dict(row) if isinstance(row, dict) else {}


def _save_spinner_ladder(root: Path | None, key: str, row: dict[str, Any] | None) -> None:
    state = _load_state(root)
    ladders = state.setdefault("spinner_ladders", {})
    if row is None:
        ladders.pop(key, None)
    else:
        ladders[key] = row
    state["spinner_ladders"] = ladders
    _save_state(state, root)


def _clear_spinner_ladder(root: Path | None, key: str, *, why: str) -> None:
    prior = _load_spinner_ladder(root, key)
    if prior:
        _emit(
            event="spinner_ladder",
            detail="cleared",
            ok=True,
            extra={"key": key, "why": why, "prior_stage": prior.get("stage")},
            root=root,
        )
    _save_spinner_ladder(root, key, None)


def _emit_spinner_step(
    *,
    root: Path | None,
    instance_id: str,
    job: dict[str, Any],
    session_id: str | None,
    stage: str,
    stage_i: int,
    ok: bool | None,
    detail: str,
    extra: dict[str, Any] | None = None,
) -> None:
    payload = {
        "stage": stage,
        "stage_i": stage_i,
        "stages": list(SPINNER_LADDER_STAGES),
        "key": _spinner_ladder_key(instance_id, job),
        **(extra or {}),
    }
    _emit(
        event="spinner_ladder",
        detail=detail or stage,
        instance_id=instance_id,
        session_id=session_id,
        job_id=str(job.get("job_id") or "") or None,
        ok=ok,
        extra=payload,
        root=root,
    )


def _run_spinner_ladder(
    instance_id: str,
    *,
    root: Path,
    job: dict[str, Any],
    session_id: str | None,
    channel_id: str | None,
    shortcut_id: str | None,
    before: dict[str, Any],
    force: bool,
) -> dict[str, Any]:
    """Escalate spinner recovery one stage per invocation; log every step."""
    key = _spinner_ladder_key(instance_id, job)
    ladder = _load_spinner_ladder(root, key)
    now_ts = _now().timestamp()
    steps: list[dict[str, Any]] = []

    # Resolve intended once (named MNF/ESPN must not fall to Atlanta).
    if not job.get("job_id"):
        try:
            from .recovery_target import _job_for_lock

            locked_job = _job_for_lock(instance_id, root)
            if locked_job:
                job = dict(locked_job)
                session_id = session_id or job.get("session_id")
                channel_id = channel_id or job.get("channel_id")
                shortcut_id = shortcut_id or job.get("shortcut_id")
                key = _spinner_ladder_key(instance_id, job)
                ladder = _load_spinner_ladder(root, key)
        except Exception:
            pass

    has_intended = bool(
        (channel_id or shortcut_id or job.get("nav_route"))
        and str(channel_id or shortcut_id or "").upper()
        not in {"", "ON_AIR_CONTINUE", "ON_AIR"}
    )
    is_named_linear = _job_is_named_linear(job, channel_id, shortcut_id)
    is_local = _job_is_local_capture(job, channel_id, shortcut_id, root=root)

    if ladder.get("exhausted") and not force:
        age = now_ts - float(ladder.get("exhausted_ts") or ladder.get("ts") or 0)
        if age < spinner_exhausted_cooldown_s():
            _emit_spinner_step(
                root=root,
                instance_id=instance_id,
                job=job,
                session_id=session_id,
                stage="exhausted",
                stage_i=len(SPINNER_LADDER_STAGES) - 1,
                ok=False,
                detail="exhausted_cooldown",
                extra={
                    "age_s": round(age, 1),
                    "cooldown_s": spinner_exhausted_cooldown_s(),
                    "history": ladder.get("history") or [],
                },
            )
            return {
                "ok": False,
                "skipped": True,
                "reason": "spinner_ladder_exhausted",
                "ladder_continue": False,
                "ladder_exhausted": True,
                "instance_id": instance_id,
                "before": before,
                "steps": list(ladder.get("history") or []),
                "lesson": "Spinner ladder exhausted; keeping capture; refused local filler.",
            }

    # Stage cooldown (skip wait if force).
    last_ts = float(ladder.get("ts") or 0)
    if (
        not force
        and last_ts
        and ladder.get("stage")
        and not ladder.get("exhausted")
        and (now_ts - last_ts) < spinner_stage_cooldown_s()
    ):
        _emit_spinner_step(
            root=root,
            instance_id=instance_id,
            job=job,
            session_id=session_id,
            stage=str(ladder.get("stage")),
            stage_i=int(ladder.get("stage_i") or 0),
            ok=False,
            detail="stage_cooldown",
            extra={"age_s": round(now_ts - last_ts, 1)},
        )
        return {
            "ok": False,
            "skipped": True,
            "reason": "spinner_ladder_cooldown",
            "ladder_continue": True,
            "ladder_exhausted": False,
            "instance_id": instance_id,
            "before": before,
            "steps": list(ladder.get("history") or []),
            "stage": ladder.get("stage"),
        }

    stage_i = int(ladder.get("next_stage_i") or 0)
    if stage_i >= len(SPINNER_LADDER_STAGES):
        stage_i = len(SPINNER_LADDER_STAGES) - 1
    stage = SPINNER_LADDER_STAGES[stage_i]
    history = list(ladder.get("history") or [])

    _emit_spinner_step(
        root=root,
        instance_id=instance_id,
        job=job,
        session_id=session_id,
        stage=stage,
        stage_i=stage_i,
        ok=None,
        detail="enter",
        extra={
            "has_intended": has_intended,
            "is_named_linear": is_named_linear,
            "is_local": is_local,
            "fail_reason": before.get("reason"),
            "channel_id": channel_id,
            "shortcut_id": shortcut_id,
            "nav_route": job.get("nav_route"),
        },
    )

    after = before
    stage_ok = False
    stage_detail = stage
    stage_extra: dict[str, Any] = {}

    try:
        if stage == "wait_buffer":
            wait_s = spinner_wait_s()
            time.sleep(wait_s)
            after = probe_heartbeat(instance_id, session_id=session_id, root=root)
            stage_ok = _spinner_cleared(after)
            stage_detail = f"waited_{wait_s:.0f}s"
            stage_extra = {"wait_s": wait_s, "after_reason": after.get("reason")}

        elif stage == "jiggle":
            from .instances import get_instance
            from .streamers_recover import jiggle_stuck_player, jiggle_ok_for_intended

            jig = jiggle_stuck_player(get_instance(instance_id, root))
            time.sleep(2.0)
            after = probe_heartbeat(instance_id, session_id=session_id, root=root)
            stage_ok = _spinner_cleared(after)
            stage_detail = "jiggle_up_down"
            stage_extra = {"keys": jig.get("keys"), "after_reason": after.get("reason")}
            # Named linear: picture clear is not enough — must match intended.
            if stage_ok and is_named_linear:
                ident = jiggle_ok_for_intended(
                    instance_id,
                    intended={
                        "nav_route": job.get("nav_route"),
                        "open_via": job.get("open_via"),
                        "shortcut_id": shortcut_id,
                        "channel_id": channel_id,
                        "label": job.get("label"),
                    },
                    root=root,
                )
                stage_extra["identity"] = {
                    k: ident.get(k)
                    for k in (
                        "ok",
                        "root_cause",
                        "intended_ok",
                        "matched_label",
                        "wrong_pack",
                    )
                }
                if not ident.get("ok"):
                    stage_ok = False
                    stage_detail = "jiggle_refused_no_identity"
                    stage_extra["root_cause"] = ident.get("root_cause")
                    _emit(
                        event="heartbeat_decision",
                        detail="jiggle_refused_no_identity",
                        instance_id=instance_id,
                        session_id=session_id,
                        job_id=str(job.get("job_id") or "") or None,
                        ok=False,
                        extra={
                            "root_cause": ident.get("root_cause"),
                            "wrong_pack": ident.get("wrong_pack"),
                            "channel_id": channel_id,
                            "route": "spinner_ladder",
                        },
                        root=root,
                    )

        elif stage == "channel_hop":
            from .instances import get_instance
            from .streamers_recover import channel_hop_and_back

            hop = channel_hop_and_back(
                get_instance(instance_id, root),
                dwell_s=max(3.0, spinner_wait_s() * 0.35),
            )
            after = probe_heartbeat(instance_id, session_id=session_id, root=root)
            stage_ok = _spinner_cleared(after)
            stage_detail = "channel_up_down_back"
            stage_extra = {
                "keys": hop.get("keys"),
                "dwell_s": hop.get("dwell_s"),
                "after_reason": after.get("reason"),
                "is_named_linear": is_named_linear,
            }

        elif stage == "wait_after_hop":
            wait_s = max(8.0, spinner_wait_s() * 0.5)
            time.sleep(wait_s)
            after = probe_heartbeat(instance_id, session_id=session_id, root=root)
            stage_ok = _spinner_cleared(after)
            stage_detail = f"waited_{wait_s:.0f}s_after_hop"
            stage_extra = {"wait_s": wait_s, "after_reason": after.get("reason")}

        elif stage == "reopen_intended":
            if has_intended:
                reopen = _reopen_channel(
                    instance_id,
                    job=job,
                    channel_id=channel_id,
                    shortcut_id=shortcut_id,
                    root=root,
                )
                stage_extra = {
                    "via": reopen.get("via"),
                    "nav_route": reopen.get("nav_route"),
                    "error": reopen.get("error"),
                    "reopen_ok": bool(reopen.get("ok")),
                }
                time.sleep(3.0)
                after = probe_heartbeat(instance_id, session_id=session_id, root=root)
                stage_ok = _spinner_cleared(after)
                stage_detail = "reopen_intended"
            else:
                from .streamers_recover import recover_loop

                picture = recover_loop(instance_id, goal="picture", max_steps=6, root=root)
                stage_extra = {
                    "filler": True,
                    "recover_ok": picture.get("ok"),
                    "final_kind": picture.get("final_kind"),
                }
                after = probe_heartbeat(instance_id, session_id=session_id, root=root)
                stage_ok = _spinner_cleared(after)
                stage_detail = "recover_picture_filler"

        elif stage == "wait_after_reopen":
            wait_s = spinner_wait_s()
            time.sleep(wait_s)
            after = probe_heartbeat(instance_id, session_id=session_id, root=root)
            stage_ok = _spinner_cleared(after)
            stage_detail = f"waited_{wait_s:.0f}s_after_reopen"
            stage_extra = {"wait_s": wait_s, "after_reason": after.get("reason")}

        elif stage == "alternate_local":
            # ESPN / MNF / named linear: never swap to FOX/NBC — log skip and advance.
            if is_named_linear or not is_local:
                after = before
                stage_ok = False
                stage_detail = "skipped_not_local"
                stage_extra = {
                    "skipped": True,
                    "is_named_linear": is_named_linear,
                    "is_local": is_local,
                    "lesson": (
                        "Named linear (ESPN/MNF/…) — alternate local refused."
                        if is_named_linear
                        else "Job is not a local capture — alternate local skipped."
                    ),
                }
            else:
                net = _fix_network(job, instance_id=instance_id, root=root)
                used_failover = bool(ladder.get("local_failover"))
                failover = not used_failover
                local_out = open_booth_local(
                    instance_id,
                    network=net,
                    failover=failover,
                    root=root,
                )
                time.sleep(3.0)
                after = probe_heartbeat(instance_id, session_id=session_id, root=root)
                # Same net still spinning → try a different Atlanta network once.
                if not _spinner_cleared(after):
                    alt_nets = [n for n in ("FOX", "CBS", "NBC", "ABC") if n != net]
                    for alt in alt_nets[:2]:
                        local_out = open_booth_local(
                            instance_id,
                            network=alt,
                            failover=False,
                            root=root,
                        )
                        time.sleep(2.5)
                        after = probe_heartbeat(
                            instance_id, session_id=session_id, root=root
                        )
                        if local_out.get("ok") and _spinner_cleared(after):
                            net = alt
                            failover = False
                            break
                stage_ok = _spinner_cleared(after)
                stage_detail = "opened_alternate_local"
                stage_extra = {
                    "network": net,
                    "failover": failover,
                    "title": local_out.get("channel_title")
                    or local_out.get("selected_title")
                    or local_out.get("title"),
                    "open_ok": bool(local_out.get("ok")),
                    "error": local_out.get("error"),
                    "via": local_out.get("via"),
                }
                ladder["local_failover"] = bool(failover)

        elif stage == "reopen_or_hard_recover":
            if has_intended and is_named_linear:
                reopen = _reopen_channel(
                    instance_id,
                    job=job,
                    channel_id=channel_id,
                    shortcut_id=shortcut_id,
                    root=root,
                )
                stage_extra = {
                    "via": reopen.get("via"),
                    "error": reopen.get("error"),
                    "reopen_ok": bool(reopen.get("ok")),
                    "attempt": 2,
                }
                time.sleep(3.0)
                after = probe_heartbeat(instance_id, session_id=session_id, root=root)
                stage_ok = _spinner_cleared(after)
                stage_detail = "reopen_intended_retry"
            elif is_local:
                # Second local try: force failover market if not yet used.
                net = _fix_network(job, instance_id=instance_id, root=root)
                local_out = open_booth_local(
                    instance_id,
                    network=net,
                    failover=True,
                    root=root,
                )
                time.sleep(3.0)
                after = probe_heartbeat(instance_id, session_id=session_id, root=root)
                stage_ok = _spinner_cleared(after)
                stage_detail = "local_failover_retry"
                stage_extra = {
                    "network": net,
                    "failover": True,
                    "open_ok": bool(local_out.get("ok")),
                    "error": local_out.get("error"),
                }
            elif has_intended:
                reopen = _reopen_channel(
                    instance_id,
                    job=job,
                    channel_id=channel_id,
                    shortcut_id=shortcut_id,
                    root=root,
                )
                stage_extra = {
                    "via": reopen.get("via"),
                    "error": reopen.get("error"),
                    "reopen_ok": bool(reopen.get("ok")),
                    "attempt": 2,
                }
                time.sleep(3.0)
                after = probe_heartbeat(instance_id, session_id=session_id, root=root)
                stage_ok = _spinner_cleared(after)
                stage_detail = "reopen_intended_retry"
            else:
                from .streamers_alive import recover_streamers

                hard = recover_streamers(instance_id, root=root, wait_s=12.0)
                stage_extra = {"recover_streamers_ok": hard.get("ok"), "filler": True}
                after = probe_heartbeat(instance_id, session_id=session_id, root=root)
                stage_ok = _spinner_cleared(after)
                stage_detail = "recover_streamers_filler"

        elif stage == "jiggle_final":
            from .instances import get_instance
            from .streamers_recover import jiggle_stuck_player

            jiggle_stuck_player(get_instance(instance_id, root))
            time.sleep(2.5)
            after = probe_heartbeat(instance_id, session_id=session_id, root=root)
            stage_ok = _spinner_cleared(after)
            stage_detail = "jiggle_final"
            stage_extra = {"after_reason": after.get("reason")}

        else:  # exhausted
            after = probe_heartbeat(instance_id, session_id=session_id, root=root)
            stage_ok = _spinner_cleared(after)
            stage_detail = "exhausted"
            stage_extra = {
                "has_intended": has_intended,
                "is_named_linear": is_named_linear,
                "is_local": is_local,
                "lesson": (
                    "Will not substitute Atlanta FOX/NBC for locked ESPN/MNF capture."
                    if is_named_linear
                    else (
                        "Local spinner ladder exhausted after alternate station tries."
                        if is_local
                        else "Spinner ladder exhausted on filler box."
                    )
                ),
            }
    except Exception as exc:  # noqa: BLE001
        stage_ok = False
        stage_detail = f"{stage}_exception"
        stage_extra = {"error": str(exc)}
        try:
            after = probe_heartbeat(instance_id, session_id=session_id, root=root)
        except Exception:
            after = before

    step_row = {
        "step": stage,
        "stage_i": stage_i,
        "ok": bool(stage_ok),
        "detail": stage_detail,
        **stage_extra,
    }
    steps.append(step_row)
    history.append({**step_row, "utc": _now_iso()})

    _emit_spinner_step(
        root=root,
        instance_id=instance_id,
        job=job,
        session_id=session_id,
        stage=stage,
        stage_i=stage_i,
        ok=bool(stage_ok),
        detail=stage_detail,
        extra=stage_extra,
    )

    if stage_ok:
        _clear_spinner_ladder(root, key, why=f"cleared_at_{stage}")
        # Also clear generic instance cooldown stamp so healthy path is clean.
        state = _load_state(root)
        inst = dict((state.get("instances") or {}).get(instance_id) or {})
        inst.update({"ts": now_ts, "utc": _now_iso(), "spinner_cleared_stage": stage})
        state.setdefault("instances", {})[instance_id] = inst
        _save_state(state, root)
        _emit(
            event="heartbeat_fix",
            detail=f"spinner_cleared:{stage}",
            instance_id=instance_id,
            session_id=session_id,
            job_id=str(job.get("job_id") or "") or None,
            ok=True,
            extra={"steps": [s.get("step") for s in history], "stage": stage},
            root=root,
        )
        return {
            "ok": True,
            "instance_id": instance_id,
            "reason": f"spinner_cleared:{stage}",
            "before": before,
            "after": after,
            "steps": history,
            "ladder_continue": False,
            "ladder_exhausted": False,
            "force": force,
        }

    # Advance or mark exhausted.
    if stage == "exhausted" or stage_i >= len(SPINNER_LADDER_STAGES) - 1:
        ladder_out = {
            "stage": "exhausted",
            "stage_i": len(SPINNER_LADDER_STAGES) - 1,
            "next_stage_i": len(SPINNER_LADDER_STAGES) - 1,
            "exhausted": True,
            "exhausted_ts": now_ts,
            "ts": now_ts,
            "utc": _now_iso(),
            "history": history[-24:],
            "has_intended": has_intended,
            "is_named_linear": is_named_linear,
            "is_local": is_local,
            "local_failover": bool(ladder.get("local_failover")),
            "channel_id": channel_id,
            "shortcut_id": shortcut_id,
        }
        _save_spinner_ladder(root, key, ladder_out)
        reason = (
            "spinner_ladder_exhausted_hold"
            if has_intended
            else "spinner_ladder_exhausted"
        )
        quiet_meta: dict[str, Any] | None = None
        if is_named_linear or has_intended:
            # Count toward quiet hold so desk stops re-entering the ladder every tick.
            state_ex = _load_state(root)
            inst_ex = dict((state_ex.get("instances") or {}).get(instance_id) or {})
            quiet_meta = _arm_intended_hold(
                inst_ex,
                root_cause=reason,
                channel_id=str(channel_id or shortcut_id or ""),
            )
            state_ex.setdefault("instances", {})[instance_id] = {
                **inst_ex,
                "ts": now_ts,
                "utc": _now_iso(),
                "last_reason": reason,
            }
            _save_state(state_ex, root)
        _emit(
            event="heartbeat_fix_failed",
            detail=reason,
            instance_id=instance_id,
            session_id=session_id,
            job_id=str(job.get("job_id") or "") or None,
            ok=False,
            extra={
                "steps": [s.get("step") for s in history],
                "history": history[-12:],
                "lesson": stage_extra.get("lesson"),
                "channel_id": channel_id,
                "nav_route": job.get("nav_route"),
                "hold": quiet_meta,
                "keep_tape": True,
                "root_cause": reason,
            },
            root=root,
        )
        out_ex: dict[str, Any] = {
            "ok": False,
            "instance_id": instance_id,
            "reason": reason,
            "before": before,
            "after": after,
            "steps": history,
            "ladder_continue": False,
            "ladder_exhausted": True,
            "force": force,
            "root_cause": reason,
            "lesson": stage_extra.get("lesson")
            or "Spinner ladder exhausted; capture kept; no local filler.",
        }
        if quiet_meta is not None:
            out_ex["hold"] = quiet_meta
        return out_ex

    next_i = stage_i + 1
    ladder_out = {
        "stage": stage,
        "stage_i": stage_i,
        "next_stage_i": next_i,
        "exhausted": False,
        "ts": now_ts,
        "utc": _now_iso(),
        "history": history[-24:],
        "has_intended": has_intended,
        "is_named_linear": is_named_linear,
        "is_local": is_local,
        "local_failover": bool(ladder.get("local_failover")),
        "channel_id": channel_id,
        "shortcut_id": shortcut_id,
    }
    _save_spinner_ladder(root, key, ladder_out)
    return {
        "ok": False,
        "instance_id": instance_id,
        "reason": f"spinner_ladder:{stage}",
        "before": before,
        "after": after,
        "steps": history,
        "ladder_continue": True,
        "ladder_exhausted": False,
        "stage": stage,
        "next_stage": SPINNER_LADDER_STAGES[next_i],
        "force": force,
    }


def _env_peak_floor() -> float:
    """Below this int16-scale peak, audio is lagged/silent.

    Floor is always in WAV int16 absolute units (0..32767). Default 500 ≈ soft
    silence. Process-loopback helper peaks are float 0..1 and must be scaled
    before compare — see ``_peak_as_i16``.
    """
    return _env_float("HUSH_AUDIO_LAG_PEAK_MIN", 500.0, minimum=1.0)


def _env_lag_streak() -> int:
    try:
        return max(1, int(os.environ.get("HUSH_AUDIO_LAG_STREAK") or "2"))
    except ValueError:
        return 2


def _peak_as_i16(peak: float | None) -> float | None:
    """Normalize helper float peaks (0..1) to int16 absolute scale.

    Measured: loopback ``peak`` ≈ 0.34 while the same WAV maxes ≈ 11235.
    Comparing 0.34 < floor 500 falsely marked live UFC as audio_lag.
    """
    if peak is None:
        return None
    p = float(peak)
    if p < 0:
        return None
    # Normalized float from process_loopback / some heartbeats.
    if p <= 1.5:
        return p * 32767.0
    return p


def _wav_peak(path: Path) -> float | None:
    try:
        import wave

        import numpy as np

        with wave.open(str(path), "rb") as w:
            n = min(w.getnframes(), int(w.getframerate() * 8))
            raw = w.readframes(n)
            if not raw:
                return None
            arr = np.frombuffer(raw, dtype="<i2")
            if arr.size == 0:
                return None
            return float(np.max(np.abs(arr.astype(np.int32))))
    except Exception:  # noqa: BLE001
        return None


def probe_audio_lag(
    instance_id: str,
    *,
    session_id: str | None = None,
    root: Path | None = None,
    sample_s: float = 2.5,
) -> dict[str, Any]:
    """Audio-first lag probe: recent WAV peak or a short process-loopback sample.

    Tunable: HUSH_AUDIO_LAG_PEAK_MIN (default 500, int16 units),
    HUSH_AUDIO_LAG_STREAK (default 2).
    """
    root = ensure_data_layout(root)
    peak: float | None = None
    peak_raw: float | None = None
    source = None
    if session_id:
        sess = root / "authorized_sources" / session_id
        wavs = sorted(sess.glob("audio_*.wav"), key=lambda p: p.stat().st_mtime)
        if wavs:
            peak = _wav_peak(wavs[-1])
            peak_raw = peak
            source = str(wavs[-1])
        hb = sess / "_audio_heartbeat.json"
        if peak is None and hb.is_file():
            try:
                row = json.loads(hb.read_text(encoding="utf-8"))
                if row.get("peak") is not None:
                    peak_raw = float(row["peak"])
                    peak = _peak_as_i16(peak_raw)
                    source = "audio_heartbeat"
                elif row.get("peak_session") is not None:
                    peak_raw = float(row["peak_session"])
                    peak = _peak_as_i16(peak_raw)
                    source = "audio_heartbeat"
            except Exception:  # noqa: BLE001
                pass

    if peak is None and sample_s > 0:
        try:
            from .process_loopback import record_process_loopback, resolve_hd_player_pid

            hit = resolve_hd_player_pid(instance_id=instance_id)
            out = root / "work" / "heartbeat_lag" / f"{instance_id}_lag.wav"
            out.parent.mkdir(parents=True, exist_ok=True)
            info = record_process_loopback(pid=int(hit["pid"]), seconds=float(sample_s), out_path=out)
            peak_raw = float(info.get("peak") or 0.0)
            # Prefer int16 WAV max — matches floor units. Helper peak is float 0..1.
            if out.is_file():
                wp = _wav_peak(out)
                if wp is not None:
                    peak = wp
                else:
                    peak = _peak_as_i16(peak_raw)
            else:
                peak = _peak_as_i16(peak_raw)
            source = "loopback_sample"
        except Exception as exc:  # noqa: BLE001
            return {
                "ok": False,
                "lagging": None,
                "error": str(exc),
                "instance_id": instance_id,
            }

    floor = _env_peak_floor()
    lagging = peak is not None and float(peak) < floor
    return {
        "ok": True,
        "lagging": lagging,
        "peak": peak,
        "peak_raw": peak_raw,
        "peak_floor": floor,
        "peak_scale": "int16",
        "source": source,
        "instance_id": instance_id,
        "session_id": session_id,
        "checked_utc": _now_iso(),
    }


def update_audio_lag_state(
    instance_id: str,
    lag_probe: dict[str, Any],
    *,
    root: Path | None = None,
) -> dict[str, Any]:
    """Streak-track audio lag and decide Atlanta→Alabama failover."""
    root = ensure_data_layout(root)
    state = _load_state(root)
    row = dict((state.get("instances") or {}).get(instance_id) or {})
    lagging = lag_probe.get("lagging")
    streak = int(row.get("audio_lag_streak") or 0)
    if lagging is True:
        streak += 1
    elif lagging is False:
        streak = 0
    row["audio_lag_streak"] = streak
    row["audio_lag_peak"] = lag_probe.get("peak")
    row["audio_lag_checked_utc"] = _now_iso()
    need = _env_lag_streak()
    confirmed = streak >= need
    row["audio_lagging"] = confirmed
    if confirmed and not row.get("audio_lag_since"):
        row["audio_lag_since"] = _now_iso()
    if not confirmed:
        row.pop("audio_lag_since", None)
    state.setdefault("instances", {})[instance_id] = row
    _save_state(state, root)
    return {
        "lagging": confirmed,
        "streak": streak,
        "need_streak": need,
        "peak": lag_probe.get("peak"),
        "peak_floor": lag_probe.get("peak_floor"),
        "market": row.get("local_market"),
        "network": row.get("local_network"),
        "failover": bool(row.get("local_failover")),
    }


def _fix_network(
    job: dict[str, Any] | None,
    *,
    instance_id: str | None = None,
    root: Path | None = None,
) -> str:
    from .us_locals import network_from_channel_id

    job = job or {}
    preferred = None
    for key in ("channel_id", "shortcut_id", "label"):
        net = network_from_channel_id(str(job.get(key) or ""))
        if net:
            preferred = net
            break
    # ON_AIR / unknown filler: rotate Atlanta nets so two players never share WSB.
    # Never bare-default to ABC — that collapsed both clones onto WSB every recover.
    if instance_id:
        try:
            from .stream_status import instance_default_network, pick_filler_network

            return pick_filler_network(instance_id, root=root, preferred=preferred)
        except Exception:
            try:
                from .stream_status import instance_default_network

                return instance_default_network(instance_id)
            except Exception:
                pass
    if preferred:
        return preferred
    return "FOX"


def open_booth_local(
    instance_id: str,
    *,
    network: str,
    failover: bool = False,
    root: Path | None = None,
) -> dict[str, Any]:
    """Open Atlanta (or Alabama failover) US local via grouper, else call-letter search.

    Prefer US * SECTION when the rail is visible. Pack EPGs (Pluto / SN+ / FLSP)
    hide that rail — open_home_local falls back to WSB/WXIA/… search and still
    lands on the Atlanta/Alabama affiliate (never Pluto).
    """
    from .us_locals import open_home_local

    out = open_home_local(
        network,
        failover=failover,
        instance_id=instance_id,
        open_player=True,
        save=True,
        root=root,
    )
    # Guard: never accept Pluto / free-ad titles.
    title = str(
        out.get("channel_title") or out.get("selected_title") or out.get("title") or ""
    ).lower()
    if any(bad in title for bad in ("pluto", "roku", "tubi", "freevee")):
        out = dict(out)
        out["ok"] = False
        out["error"] = f"rejected_bad_source:{title[:80]}"
    return out


def probe_heartbeat(
    instance_id: str,
    *,
    session_id: str | None = None,
    root: Path | None = None,
    save_shot: bool = True,
) -> dict[str, Any]:
    """Picture (and optional session audio) heartbeat probe."""
    root = ensure_data_layout(root)
    from .streamers_alive import probe_streamers_down

    picture = probe_streamers_down(instance_id, root=root, save_shot=save_shot)
    audio: dict[str, Any] | None = None
    session_picture: dict[str, Any] | None = None
    if session_id:
        try:
            from .schedule_audit import inspect_session

            tape = inspect_session(session_id, root=root)
            checks = tape.get("checks") or {}
            audio = {
                "ok": bool(checks.get("audio_progressing")),
                "audio_heartbeat_fresh": checks.get("audio_heartbeat_fresh"),
                "audio_wav_fresh": checks.get("audio_wav_fresh"),
                "audio_seconds": tape.get("audio_seconds"),
                "hb_age": tape.get("audio_heartbeat_age_s"),
            }
            session_picture = tape.get("picture_heartbeat")
        except Exception as exc:  # noqa: BLE001
            audio = {"ok": None, "error": str(exc)}

    picture_down = bool(picture.get("down"))
    session_pic_bad = bool(
        session_picture
        and session_picture.get("picture_ok") is False
        and str(session_picture.get("state") or "")
        in {
            "blue_spinner",
            "cloud_network_error",
            "black_down",
            "error_overlay",
            "buffering",
            "flat_dark",
            "likely_black_or_buffer",
            "stuck_guide",
            "frozen_frames",
        }
    )
    audio_bad = bool(audio and audio.get("ok") is False)

    ui_kind = _classify_ui(picture)
    frame_path = (picture.get("screenshot") or (picture.get("frame_score") or {}).get("path"))
    frozen_now = None
    fr = (picture.get("frame_score") or {}).get("freeze") or {}
    if isinstance(fr, dict) and "frozen" in fr:
        frozen_now = bool(fr.get("frozen"))
    liveness = update_liveness_timers(
        instance_id,
        ui_kind=ui_kind,
        frame_path=str(frame_path) if frame_path else None,
        frozen_now=frozen_now,
        root=root,
    )
    stuck = bool(liveness.get("stuck"))

    # Audio lag (peak) — only sample when picture looks otherwise alive, or session known.
    lag_probe = None
    lag_state = None
    try:
        # Prefer session WAV peak (no extra grab). Live sample only for unlocked fillers.
        sample = 0.0
        if not session_id and not picture_down and not stuck:
            sample = 2.0
        lag_probe = probe_audio_lag(
            instance_id,
            session_id=session_id,
            root=root,
            sample_s=sample,
        )
        lag_state = update_audio_lag_state(instance_id, lag_probe, root=root)
    except Exception as exc:  # noqa: BLE001
        lag_probe = {"ok": False, "error": str(exc)}
        lag_state = {"lagging": False, "error": str(exc)}

    audio_lagging = bool((lag_state or {}).get("lagging"))

    # Fleet identity: are we on the same channel/game as another player?
    identity: dict[str, Any] = {}
    duplicate: dict[str, Any] | None = None
    try:
        from .stream_status import (
            find_duplicate_streams,
            identity_from_texts,
            normalize_program_key,
            record as status_record,
        )

        texts = list(picture.get("texts") or [])
        identity = identity_from_texts(texts)
        # Fullscreen often has empty dump — peek chrome once when locked/session.
        if (session_id or not identity) and not picture_down:
            try:
                from .streamers_chrome import read_playing_channel

                chrome = read_playing_channel(instance_id, root=root, tap_for_chrome=True)
                identity.update(identity_from_texts(list(chrome.get("texts") or [])))
                if chrome.get("program_guess") and not identity.get("program_key"):
                    identity["program_title"] = chrome.get("program_guess")
                    identity["program_key"] = normalize_program_key(str(chrome.get("program_guess")))
                if chrome.get("channel_guess") and str(chrome["channel_guess"]).startswith("CH_"):
                    try:
                        identity["channel_number"] = int(str(chrome["channel_guess"]).split("_", 1)[1])
                    except Exception:
                        pass
            except Exception:
                pass
        if identity:
            status_record(
                instance_id,
                event="identity_probe",
                ok=True,
                detail="chrome/ui identity",
                session_id=session_id,
                selected_title=identity.get("selected_title"),
                network=identity.get("network"),
                calls=identity.get("calls"),
                market=identity.get("market") or identity.get("city"),
                channel_number=identity.get("channel_number"),
                program_key=identity.get("program_key"),
                program_title=identity.get("program_title"),
                ui_kind=ui_kind,
                emit_farm_run=False,
                root=root,
            )
        duplicate = find_duplicate_streams(instance_id, identity, root=root)
    except Exception as exc:  # noqa: BLE001
        duplicate = {"duplicate": False, "error": str(exc)}

    dup = bool((duplicate or {}).get("duplicate"))
    failing = picture_down or session_pic_bad or audio_bad or stuck or audio_lagging or dup
    reason = None
    if picture_down:
        reason = picture.get("reason") or "picture_down"
    elif stuck:
        reason = str(liveness.get("stuck_reason") or "stuck")
    elif dup:
        conflict = ((duplicate or {}).get("conflicts") or [{}])[0]
        reason = f"duplicate_stream:{conflict.get('why')}@{conflict.get('instance_id')}"
    elif audio_lagging:
        reason = (
            f"audio_lag:peak={lag_probe.get('peak') if lag_probe else None}"
            f"<floor={lag_probe.get('peak_floor') if lag_probe else None}"
            f":streak={(lag_state or {}).get('streak')}"
        )
    elif session_pic_bad:
        reason = f"session_picture:{session_picture.get('state')}"
    elif audio_bad:
        reason = "audio_heartbeat_stale"
    else:
        reason = "ok"

    return {
        "ok": not failing,
        "failing": failing,
        "reason": reason,
        "instance_id": instance_id,
        "session_id": session_id,
        "ui_kind": ui_kind,
        "liveness": liveness,
        "audio_lag": lag_state,
        "audio_lag_probe": lag_probe,
        "identity": identity,
        "duplicate": duplicate,
        "picture": picture,
        "session_picture": session_picture,
        "audio": audio,
        "checked_utc": _now_iso(),
        "thresholds": {
            "guide_stuck_s": guide_stuck_s(),
            "search_stuck_s": search_stuck_s(),
            "frame_freeze_s": frame_freeze_s(),
            "audio_lag_peak_min": _env_peak_floor(),
            "audio_lag_streak": _env_lag_streak(),
        },
    }


def _reopen_channel(
    instance_id: str,
    *,
    job: dict[str, Any] | None = None,
    channel_id: str | None = None,
    shortcut_id: str | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Put the intended channel back on after recover (not a random ESPN fill)."""
    root = ensure_data_layout(root)
    job = job or {}
    shortcut_id = shortcut_id or job.get("shortcut_id")
    channel_id = channel_id or job.get("channel_id")
    open_via = job.get("open_via")
    nav_route = job.get("nav_route")

    # Linear ESPN* — parent→child nav, never search (ESPNU) or Atlanta NBC filler.
    if nav_route or str(open_via or "") == "nav":
        try:
            from .streamers_open import LINEAR_NAV_BY_SHORTCUT, nav_route_for_shortcut
            from .streamers_nav import run_route

            rid = str(nav_route or "") or None
            if not rid:
                rid = LINEAR_NAV_BY_SHORTCUT.get(str(shortcut_id or channel_id or "").upper())
            if not rid and shortcut_id:
                rid = nav_route_for_shortcut(str(shortcut_id), None)
            if rid:
                out = run_route(
                    rid,
                    instance_id=instance_id,
                    root=root,
                    open_player=True,
                    save_as=str(shortcut_id or channel_id or rid),
                )
                return {
                    "ok": bool(out.get("ok")),
                    "via": "nav",
                    "nav_route": rid,
                    "shortcut_id": shortcut_id,
                    "result": out,
                }
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "via": "nav", "nav_route": nav_route, "error": str(exc)}

    if shortcut_id:
        try:
            from .streamers_open import open_shortcut

            out = open_shortcut(str(shortcut_id), instance_id=instance_id, root=root)
            return {"ok": bool(out.get("ok")), "via": "shortcut", "shortcut_id": shortcut_id, "result": out}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "via": "shortcut", "shortcut_id": shortcut_id, "error": str(exc)}

    if open_via == "search" and (job.get("guide") or {}).get("search_query"):
        try:
            from .streamers_open import search_open

            q = str((job.get("guide") or {}).get("search_query"))
            out = search_open(query=q, instance_id=instance_id, root=root)
            return {"ok": bool(out.get("ok")), "via": "search", "query": q, "result": out}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "via": "search", "error": str(exc)}

    if channel_id:
        try:
            from .channel import apply_recipe

            out = apply_recipe(channel_id=str(channel_id), instance_id=instance_id, root=root, launch=True)
            return {
                "ok": bool(out.get("ok")),
                "via": "channel_recipe",
                "channel_id": channel_id,
                "result": {"ok": out.get("ok"), "steps": len(out.get("steps") or [])},
            }
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "via": "channel_recipe", "channel_id": channel_id, "error": str(exc)}

    return {"ok": True, "via": "none", "skipped": True}


def fix_heartbeat(
    instance_id: str,
    *,
    root: Path | None = None,
    job: dict[str, Any] | None = None,
    session_id: str | None = None,
    channel_id: str | None = None,
    shortcut_id: str | None = None,
    force: bool = False,
    reason: str = "heartbeat_failing",
) -> dict[str, Any]:
    """Full fix route for one instance. Idempotent under cooldown unless force."""
    root = ensure_data_layout(root)
    job = job or {}
    session_id = session_id or job.get("session_id")
    channel_id = channel_id or job.get("channel_id")
    shortcut_id = shortcut_id or job.get("shortcut_id")

    # Resolve intended job early — quiet hold + spinner ladder need it before
    # already_healthy short-circuit (desk thrash was spinner_ladder every tick).
    if not job.get("job_id"):
        try:
            from .recovery_target import _job_for_lock

            locked_job = _job_for_lock(instance_id, root)
            if locked_job:
                job = dict(locked_job)
                session_id = session_id or job.get("session_id")
                channel_id = channel_id or job.get("channel_id")
                shortcut_id = shortcut_id or job.get("shortcut_id")
        except Exception:
            pass

    before = probe_heartbeat(instance_id, session_id=session_id, root=root)
    fail_reason = before.get("reason") or reason
    spinnerish = _is_spinner_fail(fail_reason, before) or str(reason or "") in {
        "picture_dead_live",
        "blue_spinner",
        "picture_blue_spinner",
    }
    early_intended = bool(
        (channel_id or shortcut_id or job.get("nav_route"))
        and str(channel_id or shortcut_id or "").upper()
        not in {"", "ON_AIR_CONTINUE", "ON_AIR"}
    )
    state_early = _load_state(root)
    inst_early = dict((state_early.get("instances") or {}).get(instance_id) or {})
    if force and early_intended:
        _clear_intended_hold(inst_early)
        state_early.setdefault("instances", {})[instance_id] = inst_early
        _save_state(state_early, root)
    quiet_until_early = float(inst_early.get("intended_hold_quiet_until") or 0)
    quiet_armed = bool(
        early_intended
        and not force
        and quiet_until_early
        and _now().timestamp() < quiet_until_early
    )
    if quiet_armed and before.get("ok") and not spinnerish:
        # Truly healthy desk tick (not a spinner thrash route) — clear hold.
        _clear_intended_hold(inst_early)
        state_early.setdefault("instances", {})[instance_id] = inst_early
        _save_state(state_early, root)
        quiet_armed = False
    if quiet_armed:
        left = max(0.0, quiet_until_early - _now().timestamp())
        _emit(
            event="heartbeat_fix_deferred",
            detail="intended_hold_quiet",
            instance_id=instance_id,
            session_id=session_id,
            job_id=str(job.get("job_id") or "") or None,
            ok=False,
            extra={
                "root_cause": "intended_hold_quiet",
                "quiet_left_s": round(left, 1),
                "hold_fails": inst_early.get("intended_hold_fails"),
                "last_root_cause": inst_early.get("intended_hold_last_root_cause"),
                "channel_id": channel_id or inst_early.get("intended_hold_channel_id"),
                "blocked_route": "spinner_ladder" if spinnerish else "fix_heartbeat",
                "fail_reason": fail_reason,
                "lesson": (
                    "Holding quietly — keep capturing bad/spinner tape rather than "
                    "thrashing spinner ladder / nav every desk tick. force=True clears."
                ),
            },
            root=root,
        )
        return {
            "ok": False,
            "skipped": True,
            "reason": "intended_hold_quiet",
            "quiet_left_s": round(left, 1),
            "before": before,
            "instance_id": instance_id,
            "root_cause": "intended_hold_quiet",
            "lesson": "Quiet hold after repeated intended fails; tape kept.",
        }

    if before.get("ok") and not force:
        try:
            _clear_spinner_ladder(
                root, _spinner_ladder_key(instance_id, job), why="already_healthy"
            )
        except Exception:
            pass
        _emit(
            event="heartbeat_ok",
            detail="skip_healthy",
            instance_id=instance_id,
            session_id=session_id,
            job_id=str(job.get("job_id") or "") or None,
            ok=True,
            root=root,
        )
        return {
            "ok": True,
            "skipped": True,
            "reason": "already_healthy",
            "before": before,
            "instance_id": instance_id,
        }

    # Spinner / picture-dead: escalate via logged ladder (own cooldowns).
    if spinnerish:
        _emit(
            event="heartbeat_fail",
            detail=str(fail_reason),
            instance_id=instance_id,
            session_id=session_id,
            job_id=str(job.get("job_id") or "") or None,
            ok=False,
            extra={"route": "spinner_ladder"},
            root=root,
        )
        return _run_spinner_ladder(
            instance_id,
            root=root,
            job=job,
            session_id=session_id,
            channel_id=channel_id,
            shortcut_id=shortcut_id,
            before=before,
            force=force,
        )

    state = _load_state(root)
    inst_state = dict((state.get("instances") or {}).get(instance_id) or {})
    last_ts = float(inst_state.get("ts") or 0)
    if not force and last_ts and (_now().timestamp() - last_ts) < _cooldown_s():
        out = {
            "ok": False,
            "skipped": True,
            "reason": "cooldown",
            "cooldown_s": _cooldown_s(),
            "last_fix_utc": inst_state.get("utc"),
            "before": before,
            "instance_id": instance_id,
        }
        _emit(
            event="heartbeat_fix_deferred",
            detail="cooldown",
            instance_id=instance_id,
            session_id=session_id,
            job_id=str(job.get("job_id") or "") or None,
            ok=False,
            extra={"last_fix_utc": inst_state.get("utc"), "root_cause": "fix_cooldown"},
            root=root,
        )
        return out

    _emit(
        event="heartbeat_fail",
        detail=str(fail_reason),
        instance_id=instance_id,
        session_id=session_id,
        job_id=str(job.get("job_id") or "") or None,
        ok=False,
        root=root,
    )
    try:
        from .stream_status import record as _status_record

        _status_record(
            instance_id,
            event="heartbeat_fail",
            ok=False,
            detail=str(fail_reason),
            job_id=str(job.get("job_id") or "") or None,
            session_id=session_id,
            ui_kind=str(before.get("ui_kind") or ""),
            audio_lagging=bool((before.get("audio_lag") or {}).get("lagging")),
            picture_state=str(
                (((before.get("picture") or {}).get("frame_score") or {}).get("verdict") or "")
            ),
            emit_farm_run=False,
            root=root,
        )
    except Exception:
        pass

    steps: list[dict[str, Any]] = []

    has_intended = bool(
        (channel_id or shortcut_id or job.get("nav_route"))
        and str(channel_id or shortcut_id or "").upper()
        not in {"", "ON_AIR_CONTINUE", "ON_AIR"}
    )

    # force=True clears a quiet hold so an operator can retry immediately.
    if force and has_intended:
        _clear_intended_hold(inst_state)

    # Named-lock quiet hold — stop jiggle/reopen thrash after repeated intended fails.
    quiet_until = float(inst_state.get("intended_hold_quiet_until") or 0)
    if has_intended and not force and quiet_until and _now().timestamp() < quiet_until:
        left = max(0.0, quiet_until - _now().timestamp())
        _emit(
            event="heartbeat_fix_deferred",
            detail="intended_hold_quiet",
            instance_id=instance_id,
            session_id=session_id,
            job_id=str(job.get("job_id") or "") or None,
            ok=False,
            extra={
                "root_cause": "intended_hold_quiet",
                "quiet_left_s": round(left, 1),
                "hold_fails": inst_state.get("intended_hold_fails"),
                "last_root_cause": inst_state.get("intended_hold_last_root_cause"),
                "channel_id": channel_id or inst_state.get("intended_hold_channel_id"),
                "lesson": (
                    "Holding quietly — keep capturing bad/spinner tape rather than "
                    "thrashing nav every desk tick. force=True clears."
                ),
            },
            root=root,
        )
        return {
            "ok": False,
            "skipped": True,
            "reason": "intended_hold_quiet",
            "quiet_left_s": round(left, 1),
            "before": before,
            "instance_id": instance_id,
            "root_cause": "intended_hold_quiet",
            "lesson": "Quiet hold after repeated intended_channel_hold; tape kept.",
        }

    picture_fail = any(
        x in str(fail_reason or "")
        for x in (
            "picture_",
            "black_down",
            "blue_spinner",
            "frames_frozen",
            "bluestacks_home",
            "search_ui",
        )
    )
    ui_kind = str(before.get("ui_kind") or "")
    can_jiggle = picture_fail or ui_kind in {
        "player_decode_error",
        "player_hard_error",
        "player_or_blank",
        "player_chrome",
        "player_fullscreen",
    }
    can_jiggle = can_jiggle and ui_kind not in {
        "bluestacks_home",
        "search_ui",
        "search_hub",
        "welcome_login",
    }

    # 0) Soft unstick — one up/down — before force-stop or NBC retune.
    # Named linear locks require intended identity, not bare likely_playing.
    if can_jiggle:
        try:
            from .streamers_recover import jiggle_stuck_player, jiggle_ok_for_intended, _picture_looks_ok
            from .instances import get_instance

            jig = jiggle_stuck_player(get_instance(instance_id, root))
            intended_tgt = {
                "nav_route": job.get("nav_route"),
                "open_via": job.get("open_via"),
                "shortcut_id": shortcut_id,
                "channel_id": channel_id,
                "label": job.get("label"),
            }
            if has_intended:
                check = jiggle_ok_for_intended(instance_id, intended=intended_tgt, root=root)
            else:
                check = _picture_looks_ok(instance_id, root=root)
            steps.append(
                {
                    "step": "jiggle_up_down",
                    "ok": bool(check.get("ok")),
                    "verdict": check.get("verdict"),
                    "kind": check.get("kind"),
                    "keys": jig.get("keys"),
                    "root_cause": check.get("root_cause"),
                    "intended_ok": check.get("intended_ok"),
                    "wrong_pack": check.get("wrong_pack"),
                    "matched_label": check.get("matched_label"),
                }
            )
            if check.get("ok"):
                after = probe_heartbeat(instance_id, session_id=session_id, root=root)
                _clear_intended_hold(inst_state)
                state.setdefault("instances", {})[instance_id] = {
                    **inst_state,
                    "ts": _now().timestamp(),
                    "utc": _now_iso(),
                    "last_reason": "jiggle_restored",
                }
                _save_state(state, root)
                _emit(
                    event="heartbeat_fix",
                    detail="jiggle_restored",
                    instance_id=instance_id,
                    session_id=session_id,
                    job_id=str(job.get("job_id") or "") or None,
                    ok=True,
                    extra={
                        "steps": [s.get("step") for s in steps],
                        "root_cause": check.get("root_cause") or "jiggle_restored",
                        "intended_ok": check.get("intended_ok"),
                        "matched_label": check.get("matched_label"),
                        "channel_id": channel_id,
                    },
                    root=root,
                )
                return {
                    "ok": True,
                    "instance_id": instance_id,
                    "reason": "jiggle_restored",
                    "before": before,
                    "after": after,
                    "steps": steps,
                    "force": force,
                    "root_cause": check.get("root_cause"),
                }
            if has_intended and check.get("root_cause") in {
                "jiggle_wrong_pack",
                "jiggle_picture_ok_identity_unknown",
            }:
                _emit(
                    event="heartbeat_decision",
                    detail="jiggle_refused_no_identity",
                    instance_id=instance_id,
                    session_id=session_id,
                    job_id=str(job.get("job_id") or "") or None,
                    ok=False,
                    extra={
                        "root_cause": check.get("root_cause"),
                        "wrong_pack": check.get("wrong_pack"),
                        "looked_for": check.get("looked_for"),
                        "lesson": check.get("lesson"),
                        "channel_id": channel_id,
                    },
                    root=root,
                )
        except Exception as exc:  # noqa: BLE001
            steps.append({"step": "jiggle_up_down", "ok": False, "error": str(exc)})

    # 1) Named capture (ESPN/MNF/…) — re-open *before* force-stop. Force-stop
    # was wiping the rail so nav could not find US: ESPN, then filler opened FOX.
    if has_intended:
        reopen_early = _reopen_channel(
            instance_id,
            job=job,
            channel_id=channel_id,
            shortcut_id=shortcut_id,
            root=root,
        )
        steps.append(
            {
                "step": "reopen_intended",
                "ok": bool(reopen_early.get("ok")),
                "via": reopen_early.get("via"),
                "nav_route": reopen_early.get("nav_route"),
                "shortcut_id": reopen_early.get("shortcut_id"),
                "channel_id": channel_id,
                "error": reopen_early.get("error"),
                "before_force_stop": True,
            }
        )
        _emit(
            event="heartbeat_decision",
            detail="reopen_intended_before_force_stop",
            instance_id=instance_id,
            session_id=session_id,
            job_id=str(job.get("job_id") or "") or None,
            ok=bool(reopen_early.get("ok")),
            extra={
                "via": reopen_early.get("via"),
                "nav_route": reopen_early.get("nav_route"),
                "channel_id": channel_id,
                "error": reopen_early.get("error"),
            },
            root=root,
        )
        if reopen_early.get("ok") and not reopen_early.get("skipped"):
            after = probe_heartbeat(instance_id, session_id=session_id, root=root)
            _clear_intended_hold(inst_state)
            state.setdefault("instances", {})[instance_id] = {
                **inst_state,
                "ts": _now().timestamp(),
                "utc": _now_iso(),
                "last_reason": "reopened_intended",
            }
            _save_state(state, root)
            _emit(
                event="heartbeat_fix",
                detail="reopened_intended",
                instance_id=instance_id,
                session_id=session_id,
                job_id=str(job.get("job_id") or "") or None,
                ok=True,
                extra={
                    "steps": [s.get("step") for s in steps],
                    "root_cause": "reopened_intended",
                    "via": reopen_early.get("via"),
                    "nav_route": reopen_early.get("nav_route"),
                    "channel_id": channel_id,
                },
                root=root,
            )
            return {
                "ok": True,
                "instance_id": instance_id,
                "reason": "reopened_intended",
                "before": before,
                "after": after,
                "steps": steps,
                "reopen": reopen_early,
                "force": force,
                "root_cause": "reopened_intended",
            }
        # Intended still failed — jiggle once more (identity-gated), then hold. Do NOT open FOX/NBC.
        try:
            from .streamers_recover import jiggle_stuck_player, jiggle_ok_for_intended
            from .instances import get_instance

            jiggle_stuck_player(get_instance(instance_id, root))
            check2 = jiggle_ok_for_intended(
                instance_id,
                intended={
                    "nav_route": job.get("nav_route"),
                    "open_via": job.get("open_via"),
                    "shortcut_id": shortcut_id,
                    "channel_id": channel_id,
                    "label": job.get("label"),
                },
                root=root,
            )
            steps.append(
                {
                    "step": "jiggle_after_nav_fail",
                    "ok": bool(check2.get("ok")),
                    "verdict": check2.get("verdict"),
                    "root_cause": check2.get("root_cause"),
                    "intended_ok": check2.get("intended_ok"),
                    "wrong_pack": check2.get("wrong_pack"),
                }
            )
            if check2.get("ok"):
                after = probe_heartbeat(instance_id, session_id=session_id, root=root)
                _clear_intended_hold(inst_state)
                state.setdefault("instances", {})[instance_id] = {
                    **inst_state,
                    "ts": _now().timestamp(),
                    "utc": _now_iso(),
                    "last_reason": "jiggle_after_nav_fail",
                }
                _save_state(state, root)
                return {
                    "ok": True,
                    "instance_id": instance_id,
                    "reason": "jiggle_after_nav_fail",
                    "before": before,
                    "after": after,
                    "steps": steps,
                    "force": force,
                    "root_cause": check2.get("root_cause"),
                }
        except Exception as exc:  # noqa: BLE001
            steps.append({"step": "jiggle_after_nav_fail", "ok": False, "error": str(exc)})
        after = probe_heartbeat(instance_id, session_id=session_id, root=root)
        quiet_meta = _arm_intended_hold(
            inst_state,
            root_cause="intended_channel_hold_no_local",
            channel_id=str(channel_id or ""),
        )
        state.setdefault("instances", {})[instance_id] = {
            **inst_state,
            "ts": _now().timestamp(),
            "utc": _now_iso(),
            "last_reason": "intended_channel_hold_no_local",
        }
        _save_state(state, root)
        _emit(
            event="heartbeat_fix_failed",
            detail="intended_channel_hold_no_local",
            instance_id=instance_id,
            session_id=session_id,
            job_id=str(job.get("job_id") or "") or None,
            ok=False,
            extra={
                "steps": [s.get("step") for s in steps],
                "channel_id": channel_id,
                "nav_route": job.get("nav_route"),
                "root_cause": "intended_channel_hold_no_local",
                "hold": quiet_meta,
                "keep_tape": True,
                "lesson": (
                    "Will not substitute Atlanta FOX/NBC for locked MNF/ESPN. "
                    "Keep capturing while held; after "
                    f"{quiet_meta.get('cap')} fails quiet {_hold_quiet_s():.0f}s "
                    "(no desk thrash)."
                ),
            },
            root=root,
        )
        return {
            "ok": False,
            "instance_id": instance_id,
            "reason": "intended_channel_hold_no_local",
            "before": before,
            "after": after,
            "steps": steps,
            "force": force,
            "root_cause": "intended_channel_hold_no_local",
            "hold": quiet_meta,
            "lesson": "Locked intended channel could not be restored; refused local filler; tape kept.",
        }

    # 2) Filler boxes only: hard relaunch + picture recover + US local hierarchy.
    from .streamers_alive import recover_streamers

    hard = recover_streamers(instance_id, root=root, wait_s=12.0)
    steps.append({"step": "recover_streamers", "ok": hard.get("ok"), "after": (hard.get("after") or {}).get("reason")})

    from .streamers_recover import recover_loop

    picture = recover_loop(instance_id, goal="picture", max_steps=8, root=root)
    steps.append(
        {
            "step": "recover_picture",
            "ok": picture.get("ok"),
            "final_kind": picture.get("final_kind"),
            "error": picture.get("error"),
        }
    )

    # 3) Filler / no intended job: US local hierarchy (Atlanta home, AL if audio lag).
    # Never Pluto / ESPN Max / free-ad junk. Rotate net if peer already on ABC/WSB.
    net = _fix_network(job, instance_id=instance_id, root=root)
    prior = dict((_load_state(root).get("instances") or {}).get(instance_id) or {})
    lag_reason = "audio_lag" in str(fail_reason or "")
    dup_reason = "duplicate_stream" in str(fail_reason or "")
    use_failover = bool(lag_reason or prior.get("local_failover") or prior.get("audio_lagging"))
    # First break → Atlanta; confirmed audio lag on Atlanta → Birmingham (AL).
    # Duplicate stream stays in Atlanta but on a different network (NBC/CBS/FOX).
    if lag_reason and not prior.get("local_failover"):
        use_failover = True
    elif not lag_reason:
        use_failover = False
    if dup_reason:
        use_failover = False

    # player_chrome after recover is fine for a locked take — do NOT yank to NBC.
    need_local = (not has_intended) and (
        not picture.get("ok")
        or str(picture.get("final_kind") or "")
        in GUIDE_KINDS
        | {
            "player_decode_error",
            "player_hard_error",
            "player_or_blank",
        }
        or lag_reason
        or use_failover
        or dup_reason
        or picture_fail
    )
    if need_local:
        try:
            from .streamers_recover import ensure_ready_for_open

            ready = ensure_ready_for_open(instance_id, root=root)
            steps.append(
                {
                    "step": "ensure_guide",
                    "ok": bool(ready.get("ok")),
                    "final_kind": ready.get("final_kind"),
                    "error": ready.get("error"),
                }
            )
            if dup_reason:
                # Same game on another affiliate → next unused Atlanta net, verify program differs.
                from .stream_status import retune_to_next_priority

                avoid = set()
                prior_pk = prior.get("program_key")
                if prior_pk:
                    avoid.add(str(prior_pk))
                forced = retune_to_next_priority(
                    instance_id, root=root, avoid_program_keys=avoid
                )
                steps.append(
                    {
                        "step": "force_home_local",
                        "ok": bool(forced.get("ok")),
                        "via": "retune_next_priority",
                        "network": forced.get("network") or net,
                        "market": "Atlanta",
                        "failover": False,
                        "title": forced.get("selected_title"),
                        "program_key": forced.get("program_key"),
                        "error": forced.get("error"),
                        "tried": forced.get("tried"),
                    }
                )
            else:
                # Schedule + coverage hierarchy — not bare Atlanta ABC/WSB.
                from .recovery_target import open_recovery_target

                sched = open_recovery_target(
                    instance_id,
                    job=job,
                    root=root,
                    failover=use_failover,
                )
                steps.extend(list(sched.get("steps") or []))
                forced = {
                    "ok": bool(sched.get("ok")),
                    "via": sched.get("via") or "schedule_hierarchy",
                    "network": sched.get("network") or net,
                    "pick": sched.get("pick") or {},
                    "channel_title": sched.get("channel_title"),
                    "selected_title": sched.get("selected_title"),
                    "title": sched.get("selected_title") or sched.get("channel_title"),
                    "error": sched.get("error"),
                    "program_key": sched.get("program_key"),
                }
                tgt = sched.get("target") or {}
                steps.append(
                    {
                        "step": "force_home_local",
                        "ok": bool(forced.get("ok")),
                        "via": forced.get("via"),
                        "network": forced.get("network"),
                        "market": (forced.get("pick") or {}).get("market")
                        or ("Birmingham" if use_failover else "Atlanta"),
                        "failover": use_failover,
                        "calls": (forced.get("pick") or {}).get("calls"),
                        "title": forced.get("title"),
                        "error": forced.get("error"),
                        "schedule_why": tgt.get("why"),
                        "schedule_kind": tgt.get("kind"),
                        "schedule_label": tgt.get("label"),
                    }
                )
            # Stamp market on instance state for lag failover tracking.
            st = _load_state(root)
            inst_row = dict((st.get("instances") or {}).get(instance_id) or {})
            inst_row["local_network"] = forced.get("network") or net
            inst_row["local_market"] = (forced.get("pick") or {}).get("market") or (
                "Birmingham" if use_failover and not dup_reason else "Atlanta"
            )
            inst_row["local_failover"] = bool(use_failover) and not dup_reason
            inst_row["local_calls"] = (forced.get("pick") or {}).get("calls")
            if forced.get("program_key"):
                inst_row["program_key"] = forced.get("program_key")
            st.setdefault("instances", {})[instance_id] = inst_row
            _save_state(st, root)
            # Locals fail under load — rotate other US broadcast nets only.
            # Never ESPN / ESPN+ / ESPNU / sports packs (no usable commercials).
            if not forced.get("ok"):
                fb = None
                # Prefer unused nets; ABC last so a failed FOX/CBS open does not
                # bounce both clones onto WSB.
                try:
                    from .stream_status import FILLER_NETWORK_ORDER, pick_filler_network

                    first = pick_filler_network(
                        instance_id,
                        root=root,
                        exclude_networks={str(net or "").upper()} - {""},
                    )
                    alt_order = [first] + [
                        n for n in FILLER_NETWORK_ORDER if n != first
                    ]
                except Exception:
                    alt_order = ["FOX", "CBS", "NBC", "ABC"]
                for alt_net in alt_order:
                    if alt_net == str(net or "").upper():
                        continue
                    try:
                        fb = open_booth_local(
                            instance_id,
                            network=alt_net,
                            failover=use_failover,
                            root=root,
                        )
                    except Exception as exc:  # noqa: BLE001
                        fb = {"ok": False, "error": str(exc)}
                    steps.append(
                        {
                            "step": "force_alt_local",
                            "ok": bool(fb.get("ok")),
                            "network": alt_net,
                            "title": fb.get("channel_title")
                            or fb.get("selected_title")
                            or fb.get("title"),
                            "via": fb.get("via"),
                            "error": fb.get("error"),
                        }
                    )
                    if fb.get("ok"):
                        break
        except Exception as exc:  # noqa: BLE001
            steps.append({"step": "force_home_local", "ok": False, "error": str(exc)})

    # 4) If the job already named a real local shortcut/channel, prefer that (still no Pluto/ESPN+).
    reopen = None
    sid = str(shortcut_id or job.get("shortcut_id") or "")
    cid = str(channel_id or job.get("channel_id") or "")
    if sid or cid:
        bad = any(
            x in (sid + cid).lower()
            for x in (
                "pluto",
                "roku",
                "tubi",
                "espn_max",
                "max_sports",
                "espn+",
                "espn_plus",
                "espn plus",
                "espn unlimited",
                "espnu",
            )
        )
        if not bad:
            reopen = _reopen_channel(
                instance_id,
                job=job,
                channel_id=channel_id,
                shortcut_id=shortcut_id,
                root=root,
            )
            steps.append(
                {
                    "step": "reopen_channel",
                    **{k: reopen.get(k) for k in ("ok", "via", "shortcut_id", "channel_id", "error", "skipped")},
                }
            )
        else:
            steps.append(
                {
                    "step": "reopen_channel",
                    "ok": False,
                    "skipped": True,
                    "reason": f"rejected_bad_source:{sid or cid}",
                }
            )

    # Reset stuck timers after a fix attempt so verify is not poisoned by old ages.
    state = _load_state(root)
    inst = dict((state.get("instances") or {}).get(instance_id) or {})
    inst.pop("freeze_since", None)
    inst["ui_kind_since"] = _now().timestamp()
    inst["post_fix_reset"] = _now_iso()
    state.setdefault("instances", {})[instance_id] = inst
    _save_state(state, root)

    # Settle so the next still / screencap is post-fix.
    time.sleep(3.0)
    after = probe_heartbeat(instance_id, session_id=session_id, root=root)
    # Retune paths enter the guide on purpose — finish into player or fail closed.
    tried_picture = any(
        s.get("step")
        in {
            "recover_picture",
            "force_home_local",
            "force_alt_local",
            "force_live_card",
            "force_live_card_fallback",
            "ensure_guide",
            "finish_open_picture",
        }
        for s in steps
    )
    if tried_picture and str(after.get("ui_kind") or "") in GUIDE_KINDS:
        try:
            from .streamers_recover import recover_loop

            rec = recover_loop(instance_id, goal="picture", max_steps=6, root=root)
            steps.append(
                {
                    "step": "finish_open_picture",
                    "ok": bool(rec.get("ok")),
                    "final_kind": rec.get("final_kind"),
                    "error": rec.get("error"),
                }
            )
            time.sleep(2.0)
            after = probe_heartbeat(instance_id, session_id=session_id, root=root)
        except Exception as exc:  # noqa: BLE001
            steps.append(
                {"step": "finish_open_picture", "ok": False, "error": str(exc)}
            )
    # Never report healthy while still on guide/search (even if probe soft-ok).
    if str(after.get("ui_kind") or "") in GUIDE_KINDS:
        after = dict(after)
        after["ok"] = False
        after["failing"] = True
        after["reason"] = f"still_on_guide_after_fix:{after.get('ui_kind')}"
    ok = bool(after.get("ok"))

    state = _load_state(root)
    merged = dict((state.get("instances") or {}).get(instance_id) or {})
    merged.update(
        {
            "ts": _now().timestamp(),
            "utc": _now_iso(),
            "ok": ok,
            "reason": fail_reason,
            "job_id": job.get("job_id"),
            "session_id": session_id,
            # Keep post-verify liveness clocks from the after-probe; drop poison freeze.
            "freeze_since": None if ok else merged.get("freeze_since"),
        }
    )
    if ok:
        merged.pop("freeze_since", None)
        merged["ui_kind_since"] = _now().timestamp()
    state.setdefault("instances", {})[instance_id] = {k: v for k, v in merged.items() if v is not None}
    _save_state(state, root)

    _emit(
        event="heartbeat_fixed" if ok else "heartbeat_fix_failed",
        detail=str(after.get("reason") or fail_reason),
        instance_id=instance_id,
        session_id=session_id,
        job_id=str(job.get("job_id") or "") or None,
        ok=ok,
        extra={"steps": [s.get("step") for s in steps]},
        root=root,
    )
    try:
        from .stream_status import record as _status_record

        home_step = next((s for s in steps if s.get("step") == "force_home_local"), {})
        _status_record(
            instance_id,
            event="heartbeat_fixed" if ok else "heartbeat_fix_failed",
            ok=ok,
            detail=str(after.get("reason") or fail_reason),
            job_id=str(job.get("job_id") or "") or None,
            session_id=session_id,
            selected_title=home_step.get("title"),
            via=home_step.get("via"),
            network=home_step.get("network"),
            market=home_step.get("market"),
            calls=home_step.get("calls"),
            failover=bool(home_step.get("failover")),
            ui_kind=str(after.get("ui_kind") or ""),
            audio_lagging=bool((after.get("audio_lag") or {}).get("lagging")),
            extra={"steps": [s.get("step") for s in steps]},
            emit_farm_run=False,
            root=root,
        )
    except Exception:
        pass

    return {
        "ok": ok,
        "instance_id": instance_id,
        "job_id": job.get("job_id"),
        "session_id": session_id,
        "reason": fail_reason,
        "before": before,
        "after": after,
        "steps": steps,
        "checked_utc": _now_iso(),
    }


def fix_failing_from_audit_rows(
    data: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    root: Path | None = None,
    max_per_tick: int = 1,
) -> list[dict[str, Any]]:
    """Audit hook: fix hung / picture-bad live jobs (budgeted)."""
    root = ensure_data_layout(root)
    if not _auto_enabled():
        return [{"ok": False, "skipped": True, "reason": "HUSH_HEARTBEAT_AUTO_FIX=0"}]

    by_id = {str(j.get("job_id")): j for j in (data.get("jobs") or []) if j.get("job_id")}
    actions: list[dict[str, Any]] = []
    budget = max(0, int(max_per_tick))

    candidates = [
        r
        for r in rows
        if r.get("verdict") in ("stale_live", "picture_dead_live", "broken_live")
        and r.get("pid_alive") is True
        and r.get("job_id")
    ]
    # Prefer picture-dead / spinner first.
    def _prio(row: dict[str, Any]) -> int:
        v = str(row.get("verdict") or "")
        issues = " ".join(row.get("issues") or []).lower()
        if v == "picture_dead_live":
            return 0
        if "picture" in issues or "blue_spinner" in issues or "cloud_network" in issues:
            return 1
        return 2

    candidates.sort(key=_prio)

    for row in candidates:
        if budget <= 0:
            row["recover"] = {"attempted": False, "deferred": True, "reason": "heartbeat_fix_budget"}
            continue
        jid = str(row["job_id"])
        job = dict(by_id.get(jid) or {})
        # Stamp row fields onto job for reopen.
        job.setdefault("instance_id", row.get("instance_id"))
        job.setdefault("session_id", row.get("session_id"))
        job.setdefault("channel_id", row.get("channel_id"))
        job.setdefault("shortcut_id", row.get("shortcut_id"))
        job["job_id"] = jid

        iid = str(job.get("instance_id") or row.get("instance_id") or "Nougat32")
        budget -= 1
        verdict = str(row.get("verdict") or "stale_live")
        result = fix_heartbeat(iid, root=root, job=job, reason=verdict)
        ladder_continue = bool(result.get("ladder_continue"))
        ladder_exhausted = bool(result.get("ladder_exhausted"))
        route = (
            "spinner_ladder"
            if ladder_continue or ladder_exhausted or str(result.get("reason") or "").startswith("spinner_")
            else "heartbeat_fix"
        )
        actions.append(
            {
                "job_id": jid,
                "label": job.get("label") or row.get("label"),
                "action": route,
                "ok": result.get("ok"),
                "skipped": result.get("skipped"),
                "instance_id": iid,
                "session_id": job.get("session_id"),
                "verdict_before": verdict,
                "reason": result.get("reason"),
                "after_reason": (result.get("after") or {}).get("reason"),
                "ladder_continue": ladder_continue,
                "ladder_exhausted": ladder_exhausted,
                "stage": result.get("stage") or result.get("next_stage"),
                "steps": [
                    s.get("step") if isinstance(s, dict) else s
                    for s in (result.get("steps") or [])
                ][-12:],
            }
        )
        row["recover"] = {
            "attempted": not bool(result.get("skipped")) or ladder_continue,
            "ok": result.get("ok"),
            "utc": _now_iso(),
            "instance_id": iid,
            "route": route,
            "skipped": result.get("skipped"),
            "reason": result.get("reason"),
            "ladder_continue": ladder_continue,
            "ladder_exhausted": ladder_exhausted,
            "stage": result.get("stage"),
        }
    return actions


def fix_instance_if_failing(
    instance_id: str,
    *,
    root: Path | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Fix one instance; attach scheduled job context if the lock names one."""
    root = ensure_data_layout(root)
    lock = get_lock("streamers", instance_id, root=root)
    job = None
    session_id = None
    if lock:
        session_id = str(lock.get("session_id") or "") or None
        jid = lock.get("job_id")
        if jid:
            data = load_jobs(root)
            job = next((j for j in (data.get("jobs") or []) if str(j.get("job_id")) == str(jid)), None)
    return fix_heartbeat(
        instance_id,
        root=root,
        job=job,
        session_id=session_id,
        force=force,
        reason="manual_or_scan",
    )


def scan_and_fix(
    *,
    root: Path | None = None,
    instances: list[str] | None = None,
    only_locked: bool = False,
    force: bool = False,
    max_fixes: int = 3,
) -> dict[str, Any]:
    """Probe listed instances (default: enabled registry) and fix failures.

    Also catches **disabled-but-running** clones: stop them (do not open-channel
    fix). Parked engines that BlueStacks relaunches were invisible to heartbeat
    and sat black forever.
    """
    root = ensure_data_layout(root)
    from .instances import list_instances, list_running_engines, stop_bluestacks

    rows = [
        r
        for r in list_instances(root)
        if r.get("source_kind", "streamers") == "streamers"
    ]
    running = set(list_running_engines())
    if instances:
        wanted = list(instances)
        stop_ids: list[str] = []
    else:
        wanted = [str(r.get("id")) for r in rows if r.get("enabled", True)]
        stop_ids = [
            str(r.get("id"))
            for r in rows
            if not r.get("enabled", True) and str(r.get("engine") or r.get("id")) in running
        ]
    results: list[dict[str, Any]] = []
    fixes = 0
    stopped: list[dict[str, Any]] = []
    for iid in stop_ids:
        try:
            # Soft ACPI often leaves parked clones running (and eating RAM).
            # Hard poweroff + kill HD-Player title is required for DESK_MAX.
            st = stop_bluestacks(iid, root=root, hard=True)
            if not st.get("ok"):
                st = stop_bluestacks(iid, root=root, hard=True, wait_sec=60.0)
            stopped.append(st)
            results.append(
                {
                    "instance_id": iid,
                    "ok": bool(st.get("ok")),
                    "skipped": False,
                    "reason": "stopped_disabled_running"
                    if st.get("ok")
                    else "stop_disabled_failed",
                    "action": "stop_disabled",
                    "stop": {
                        k: st.get(k)
                        for k in ("method", "error", "killed_hd_player_pids", "running")
                    },
                }
            )
        except Exception as exc:  # noqa: BLE001
            results.append(
                {
                    "instance_id": iid,
                    "ok": False,
                    "reason": "stop_disabled_failed",
                    "error": str(exc),
                    "action": "stop_disabled",
                }
            )
    for iid in wanted:
        lock = get_lock("streamers", iid, root=root)
        if only_locked and not lock:
            continue
        probe = probe_heartbeat(
            iid,
            session_id=str((lock or {}).get("session_id") or "") or None,
            root=root,
        )
        if probe.get("ok") and not force:
            results.append({"instance_id": iid, "ok": True, "skipped": True, "reason": "healthy", "probe": probe})
            continue
        if fixes >= max_fixes and not force:
            results.append({"instance_id": iid, "ok": False, "skipped": True, "reason": "max_fixes", "probe": probe})
            continue
        fixes += 1
        results.append(fix_instance_if_failing(iid, root=root, force=force))
    return {
        "ok": all(r.get("ok") or r.get("skipped") for r in results),
        "checked_utc": _now_iso(),
        "fixed": fixes,
        "stopped_disabled": stopped,
        "results": results,
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="Fix streams when heartbeat fails")
    sub = p.add_subparsers(dest="cmd", required=True)

    pr = sub.add_parser("probe", help="Probe picture/audio heartbeat")
    pr.add_argument("--instance", default="Nougat32")
    pr.add_argument("--session-id")

    fx = sub.add_parser("fix", help="Run the full heartbeat fix route")
    fx.add_argument("--instance", default="Nougat32")
    fx.add_argument("--job-id")
    fx.add_argument("--session-id")
    fx.add_argument("--channel")
    fx.add_argument("--shortcut")
    fx.add_argument("--force", action="store_true")

    sc = sub.add_parser("scan", help="Probe many instances; fix failures")
    sc.add_argument("--instances", default="", help="Comma list; default=all enabled")
    sc.add_argument("--only-locked", action="store_true")
    sc.add_argument("--force", action="store_true")
    sc.add_argument("--max-fixes", type=int, default=3)

    args = p.parse_args(argv)
    if args.cmd == "probe":
        print(json.dumps(probe_heartbeat(args.instance, session_id=args.session_id), indent=2))
        return 0
    if args.cmd == "fix":
        job = None
        if args.job_id:
            data = load_jobs()
            job = next((j for j in (data.get("jobs") or []) if str(j.get("job_id")) == str(args.job_id)), None)
            if not job:
                print(json.dumps({"ok": False, "error": "job_not_found", "job_id": args.job_id}, indent=2))
                return 2
        out = fix_heartbeat(
            args.instance if not job else str(job.get("instance_id") or args.instance),
            job=job,
            session_id=args.session_id,
            channel_id=args.channel,
            shortcut_id=args.shortcut,
            force=bool(args.force),
        )
        print(json.dumps(out, indent=2))
        return 0 if out.get("ok") or out.get("skipped") else 2
    if args.cmd == "scan":
        inst = [x.strip() for x in str(args.instances).split(",") if x.strip()] or None
        out = scan_and_fix(
            instances=inst,
            only_locked=bool(args.only_locked),
            force=bool(args.force),
            max_fixes=int(args.max_fixes),
        )
        print(json.dumps(out, indent=2))
        return 0 if out.get("ok") else 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
