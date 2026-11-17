"""Per-session / per-step wall times for farm labeling.

Append-only ledger:
  indexes/farm_labels/audit/LABEL_TIMING.jsonl
Rollup snapshot:
  indexes/farm_labels/audit/LABEL_TIMING.json

Steps: asr | vision | acoustic | combine | consensus
"""

from __future__ import annotations

import json
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .coverage_farm import farm_label_dir

STEPS = ("asr", "vision", "acoustic", "combine", "consensus")
_LOCK = threading.RLock()
# (session, step) -> {t0, started_utc, meta}
_ACTIVE: dict[tuple[str, str], dict[str, Any]] = {}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def timing_jsonl(root: Path | None = None) -> Path:
    return farm_label_dir(root) / "audit" / "LABEL_TIMING.jsonl"


def timing_snapshot(root: Path | None = None) -> Path:
    return farm_label_dir(root) / "audit" / "LABEL_TIMING.json"


def begin_step(session: str, step: str, *, root: Path | None = None, **meta: Any) -> dict[str, Any]:
    """Mark step start (idempotent if already active for same session/step)."""
    key = (str(session), str(step))
    with _LOCK:
        cur = _ACTIVE.get(key)
        if cur:
            cur["meta"] = {**(cur.get("meta") or {}), **meta}
            return {
                "session": session,
                "step": step,
                "started_utc": cur["started_utc"],
                "resumed": True,
            }
        started = _now()
        _ACTIVE[key] = {"t0": time.perf_counter(), "started_utc": started, "meta": dict(meta)}
    # Persist in-progress so a crash mid-step still shows start time.
    _write_in_progress(session, step, started, meta, root=root)
    return {"session": session, "step": step, "started_utc": started, "resumed": False}


def end_step(
    session: str,
    step: str,
    *,
    ok: bool = True,
    root: Path | None = None,
    **meta: Any,
) -> dict[str, Any]:
    """Close step, append JSONL row, refresh rollup."""
    key = (str(session), str(step))
    with _LOCK:
        cur = _ACTIVE.pop(key, None)
    ended = _now()
    if cur:
        started_utc = str(cur["started_utc"])
        duration_s = round(float(time.perf_counter() - float(cur["t0"])), 3)
        merged = {**(cur.get("meta") or {}), **meta}
    else:
        # No begin in this process — still record a point row if caller passed duration.
        started_utc = str(meta.pop("started_utc", None) or ended)
        duration_s = meta.pop("duration_s", None)
        if duration_s is not None:
            try:
                duration_s = round(float(duration_s), 3)
            except (TypeError, ValueError):
                duration_s = None
        merged = dict(meta)
    row = {
        "utc": ended,
        "session": str(session),
        "step": str(step),
        "ok": bool(ok),
        "started_utc": started_utc,
        "ended_utc": ended,
        "duration_s": duration_s,
        **{k: v for k, v in merged.items() if v is not None},
    }
    path = timing_jsonl(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
            fh.flush()
    snap = rebuild_snapshot(root=root)
    row["snapshot"] = str(timing_snapshot(root))
    row["totals"] = snap.get("totals") or {}
    return row


@contextmanager
def timed_step(
    session: str,
    step: str,
    *,
    root: Path | None = None,
    **meta: Any,
) -> Iterator[dict[str, Any]]:
    """Context manager: begin on enter, end on exit (ok=False on exception)."""
    state: dict[str, Any] = {"ok": True, "meta": dict(meta)}
    begin_step(session, step, root=root, **meta)

    def note(**kw: Any) -> None:
        state["meta"].update(kw)

    state["note"] = note
    try:
        yield state
    except Exception:
        state["ok"] = False
        end_step(session, step, ok=False, root=root, **state["meta"])
        raise
    else:
        end_step(session, step, ok=bool(state.get("ok", True)), root=root, **state["meta"])


def _write_in_progress(
    session: str,
    step: str,
    started_utc: str,
    meta: dict[str, Any],
    *,
    root: Path | None = None,
) -> None:
    path = timing_snapshot(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        blob: dict[str, Any] = {}
        if path.is_file():
            try:
                blob = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                blob = {}
        running = dict(blob.get("running") or {})
        running[f"{session}|{step}"] = {
            "session": session,
            "step": step,
            "started_utc": started_utc,
            "meta": meta,
        }
        blob["running"] = running
        blob["updated_utc"] = _now()
        path.write_text(json.dumps(blob, indent=2, default=str) + "\n", encoding="utf-8")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _stats(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0, "total_s": 0.0, "mean_s": None, "p50_s": None, "max_s": None}
    xs = sorted(values)
    n = len(xs)
    return {
        "n": n,
        "total_s": round(sum(xs), 1),
        "mean_s": round(sum(xs) / n, 1),
        "p50_s": round(xs[n // 2], 1),
        "max_s": round(xs[-1], 1),
    }


def rebuild_snapshot(root: Path | None = None) -> dict[str, Any]:
    """Recompute LABEL_TIMING.json from the JSONL ledger (+ in-memory running)."""
    rows = _read_jsonl(timing_jsonl(root))
    by_step_vals: dict[str, list[float]] = {s: [] for s in STEPS}
    by_session: dict[str, dict[str, Any]] = {}
    # Last successful (or latest) duration per session/step wins for session view.
    for row in rows:
        step = str(row.get("step") or "")
        session = str(row.get("session") or "")
        dur = row.get("duration_s")
        if session and step:
            slot = by_session.setdefault(session, {"steps": {}, "total_s": 0.0, "complete": False})
            slot["steps"][step] = {
                "duration_s": dur,
                "ok": row.get("ok"),
                "started_utc": row.get("started_utc"),
                "ended_utc": row.get("ended_utc"),
            }
        if step in by_step_vals and dur is not None and row.get("ok") is not False:
            try:
                by_step_vals[step].append(float(dur))
            except (TypeError, ValueError):
                pass

    for session, slot in by_session.items():
        steps = slot["steps"]
        total = 0.0
        for st, info in steps.items():
            try:
                if info.get("duration_s") is not None:
                    total += float(info["duration_s"])
            except (TypeError, ValueError):
                pass
        slot["total_s"] = round(total, 1)
        slot["complete"] = all(
            steps.get(s) and steps[s].get("duration_s") is not None
            for s in ("vision", "acoustic", "combine", "consensus")
        )

    by_step = {s: _stats(by_step_vals.get(s) or []) for s in STEPS}
    label_wall = round(sum(float(v["total_s"] or 0) for v in by_step.values()), 1)
    running: dict[str, Any] = {}
    with _LOCK:
        for (session, step), cur in _ACTIVE.items():
            running[f"{session}|{step}"] = {
                "session": session,
                "step": step,
                "started_utc": cur.get("started_utc"),
                "elapsed_s": round(time.perf_counter() - float(cur["t0"]), 1),
                "meta": cur.get("meta") or {},
            }

    # Keep any disk running keys that aren't in this process (other worker).
    path = timing_snapshot(root)
    if path.is_file():
        try:
            prev = json.loads(path.read_text(encoding="utf-8"))
            for k, v in dict(prev.get("running") or {}).items():
                if k not in running:
                    # Drop stale if we have a completed row newer than start.
                    running[k] = v
        except json.JSONDecodeError:
            pass
    # Clear running entries that already completed in JSONL (latest end after start).
    cleaned: dict[str, Any] = {}
    latest_end: dict[tuple[str, str], str] = {}
    for row in rows:
        latest_end[(str(row.get("session")), str(row.get("step")))] = str(row.get("ended_utc") or "")
    active_keys = {f"{a}|{b}" for (a, b) in _ACTIVE}
    for k, v in running.items():
        sess = str(v.get("session") or "")
        step = str(v.get("step") or "")
        ended = latest_end.get((sess, step))
        started = str(v.get("started_utc") or "")
        if ended and started and ended >= started and k not in active_keys:
            continue
        cleaned[k] = v

    # ETA: mean vision seconds × sessions still needing vision (approx).
    vision_mean = (by_step.get("vision") or {}).get("mean_s")
    payload = {
        "updated_utc": _now(),
        "by_step": by_step,
        "by_session": by_session,
        "running": cleaned,
        "totals": {
            "label_wall_s": label_wall,
            "label_wall_h": round(label_wall / 3600.0, 2) if label_wall else 0.0,
            "sessions_timed": len(by_session),
            "sessions_complete": sum(1 for s in by_session.values() if s.get("complete")),
            "rows": len(rows),
            "vision_mean_s": vision_mean,
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    return payload


def load_summary(root: Path | None = None) -> dict[str, Any]:
    """Return rollup; rebuild if missing."""
    path = timing_snapshot(root)
    if path.is_file():
        try:
            blob = json.loads(path.read_text(encoding="utf-8"))
            # Refresh running elapsed from this process.
            with _LOCK:
                for (session, step), cur in _ACTIVE.items():
                    blob.setdefault("running", {})[f"{session}|{step}"] = {
                        "session": session,
                        "step": step,
                        "started_utc": cur.get("started_utc"),
                        "elapsed_s": round(time.perf_counter() - float(cur["t0"]), 1),
                        "meta": cur.get("meta") or {},
                    }
            return blob
        except json.JSONDecodeError:
            pass
    return rebuild_snapshot(root=root)


def active_elapsed(session: str, step: str) -> float | None:
    key = (str(session), str(step))
    with _LOCK:
        cur = _ACTIVE.get(key)
        if not cur:
            return None
        return round(time.perf_counter() - float(cur["t0"]), 1)


# Fallback costs when the ledger is still empty (seconds).
_DEFAULT_SEC_PER_HOP = 4.5
_DEFAULT_ACOUSTIC_BASE_S = 45.0
_DEFAULT_ACOUSTIC_PER_HOP_S = 0.02
_DEFAULT_COMBINE_S = 8.0
_DEFAULT_CONSENSUS_S = 12.0
_DEFAULT_ASR_PER_AUDIO_S = 0.08  # whisper-ish if transcript missing
_WAV_BYTES_PER_S = 32000.0  # 16 kHz mono s16le


def _f(x: Any, default: float | None = None) -> float | None:
    try:
        if x is None or x == "":
            return default
        return float(x)
    except (TypeError, ValueError):
        return default


def _audio_duration_s(session: str, root: Path | None = None) -> float | None:
    try:
        from .coverage_farm import streamers_capture_root

        wav = streamers_capture_root(root) / session / "audio.wav"
        if not wav.is_file():
            return None
        return round(wav.stat().st_size / _WAV_BYTES_PER_S, 1)
    except OSError:
        return None


def _step_mean(by_step: dict[str, Any], step: str, fallback: float) -> float:
    mean = _f((by_step.get(step) or {}).get("mean_s"))
    return float(mean) if mean is not None and mean > 0 else float(fallback)


def _eta_clock(remaining_s: float | None) -> dict[str, Any]:
    if remaining_s is None:
        return {"remaining_s": None, "finish_utc": None, "finish_et": None}
    from zoneinfo import ZoneInfo

    rem = max(0.0, float(remaining_s))
    now = datetime.now(timezone.utc)
    finish = now.timestamp() + rem
    finish_dt = datetime.fromtimestamp(finish, tz=timezone.utc)
    et = finish_dt.astimezone(ZoneInfo("America/New_York"))
    return {
        "remaining_s": round(rem, 1),
        "finish_utc": finish_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "finish_et": et.strftime("%Y-%m-%d %H:%M ET"),
    }


def estimate_label_etas(
    *,
    live_job: dict[str, Any] | None = None,
    hierarchy: dict[str, Any] | None = None,
    timing: dict[str, Any] | None = None,
    root: Path | None = None,
    hop_s: float = 5.0,
    queue_annotate_limit: int = 48,
) -> dict[str, Any]:
    """Projected remaining time for live session + full backlog."""
    live = dict(live_job or {})
    hier = dict(hierarchy or {})
    timing = dict(timing or load_summary(root))
    by_step = dict(timing.get("by_step") or {})
    stages = dict(hier.get("stages") or {})
    queue = list(hier.get("queue") or [])

    hop_i = _f(live.get("hop_i"), 0.0) or 0.0
    hop_of = _f(live.get("hop_of"), 0.0) or 0.0
    elapsed = _f(live.get("step_elapsed_s"), 0.0) or 0.0
    phase = str(live.get("phase") or "")
    hop_s = _f(live.get("hop_s"), hop_s) or hop_s

    sec_per_hop = None
    hops_per_min = None
    if live.get("active") and phase == "vision" and hop_i >= 5 and elapsed > 1:
        sec_per_hop = elapsed / hop_i
        hops_per_min = 60.0 / sec_per_hop if sec_per_hop > 0 else None
    if sec_per_hop is None:
        # Historical: mean vision / typical hops, else default.
        v_mean = _f((by_step.get("vision") or {}).get("mean_s"))
        if v_mean and hop_of >= 10:
            sec_per_hop = v_mean / hop_of
        else:
            sec_per_hop = _DEFAULT_SEC_PER_HOP
    sec_per_hop = max(0.05, float(sec_per_hop))

    acoustic_mean = _step_mean(by_step, "acoustic", _DEFAULT_ACOUSTIC_BASE_S)
    combine_mean = _step_mean(by_step, "combine", _DEFAULT_COMBINE_S)
    consensus_mean = _step_mean(by_step, "consensus", _DEFAULT_CONSENSUS_S)

    def _vision_cost(n_hops: float) -> float:
        return float(n_hops) * sec_per_hop

    def _acoustic_cost(n_hops: float) -> float:
        # Prefer ledger mean; else scale lightly with hops.
        if (by_step.get("acoustic") or {}).get("n"):
            return acoustic_mean
        return _DEFAULT_ACOUSTIC_BASE_S + _DEFAULT_ACOUSTIC_PER_HOP_S * float(n_hops)

    def _tail_cost(n_hops: float) -> float:
        return _acoustic_cost(n_hops) + combine_mean + consensus_mean

    def _full_session_cost(n_hops: float, *, need_asr: bool = False) -> float:
        asr = (_DEFAULT_ASR_PER_AUDIO_S * float(n_hops) * hop_s) if need_asr else 0.0
        return asr + _vision_cost(n_hops) + _tail_cost(n_hops)

    # --- current session ---
    current: dict[str, Any] = {
        "active": bool(live.get("active")),
        "session": live.get("session"),
        "phase": phase or None,
        "elapsed_s": round(elapsed, 1) if elapsed else None,
        "remaining_s": None,
        "projected_total_s": None,
        "pct_done": live.get("pct"),
    }
    if live.get("active") and phase == "vision" and hop_of > 0 and hop_i >= 0:
        left_hops = max(0.0, hop_of - hop_i)
        vision_left = left_hops * sec_per_hop
        # After vision finishes this session still needs acoustic/combine/consensus.
        rem = vision_left + _tail_cost(hop_of)
        projected = elapsed + rem
        current.update(
            {
                "remaining_s": round(rem, 1),
                "vision_remaining_s": round(vision_left, 1),
                "tail_remaining_s": round(_tail_cost(hop_of), 1),
                "projected_total_s": round(projected, 1),
                "left_hops": int(left_hops),
                "sec_per_hop": round(sec_per_hop, 3),
                "hops_per_min": round(hops_per_min, 2) if hops_per_min else round(60.0 / sec_per_hop, 2),
            }
        )
    elif live.get("active") and phase == "acoustic":
        # Unknown progress inside acoustic — use mean remaining fraction from elapsed.
        rem = max(5.0, acoustic_mean - elapsed) if elapsed else acoustic_mean
        rem = rem + combine_mean + consensus_mean
        current.update(
            {
                "remaining_s": round(rem, 1),
                "projected_total_s": round(elapsed + rem, 1),
                "sec_per_hop": round(sec_per_hop, 3),
            }
        )
    elif live.get("active") and phase in {"combine", "consensus"}:
        rem = combine_mean + consensus_mean if phase == "combine" else consensus_mean
        current.update(
            {
                "remaining_s": round(max(1.0, rem), 1),
                "projected_total_s": round(elapsed + max(1.0, rem), 1),
            }
        )

    current_clock = _eta_clock(current.get("remaining_s"))
    current["finish_et"] = current_clock["finish_et"]
    current["finish_utc"] = current_clock["finish_utc"]

    # Cap inferred hop counts: live jobs often cover ~2h even when WAV is longer.
    hop_cap = max(float(hop_of or 0), 1800.0)  # ≥ live hop_of, else 2.5h @ 5s
    if hop_of and hop_of >= 100:
        hop_cap = max(hop_cap, float(hop_of))

    # --- per queued session estimates ---
    per_session: list[dict[str, Any]] = []
    total_remaining = float(current.get("remaining_s") or 0.0)
    priority_remaining = float(current.get("remaining_s") or 0.0)
    audio_left_s = 0.0
    for row in queue[: max(1, int(queue_annotate_limit))]:
        s = str(row.get("session") or "")
        status = str(row.get("status") or "")
        nxt = str(row.get("next") or "")
        help_n = int(row.get("help") or 0)
        audio_s = _audio_duration_s(s, root)
        n_hops = _f(row.get("n_hops"))
        capped = False
        if status == "running" and hop_of:
            n_hops = float(hop_of)
        elif n_hops is None and audio_s:
            raw = max(1.0, audio_s / max(hop_s, 0.5))
            if raw > hop_cap:
                n_hops = hop_cap
                capped = True
            else:
                n_hops = raw
        if n_hops is None:
            n_hops = hop_of if hop_of else 1440.0  # median farm take ~2h
        n_hops = float(n_hops)

        if status == "done" or nxt == "done":
            eta_s = 0.0
            kind = "done"
            add = 0.0
        elif status == "running":
            eta_s = float(current.get("remaining_s") or _full_session_cost(n_hops))
            kind = "running"
            add = 0.0  # already in total_remaining
        elif nxt == "vision":
            eta_s = _full_session_cost(n_hops)
            kind = "full"
            add = eta_s
        elif nxt == "acoustic":
            eta_s = _tail_cost(n_hops)
            kind = "tail"
            add = eta_s
        elif nxt == "combine":
            eta_s = combine_mean + consensus_mean
            kind = "combine+"
            add = eta_s
        elif nxt == "consensus":
            eta_s = consensus_mean
            kind = "consensus"
            add = eta_s
        else:
            eta_s = _full_session_cost(n_hops)
            kind = "full"
            add = eta_s

        if status != "running":
            total_remaining += float(add)
            if help_n > 0:
                priority_remaining += float(add)
            if audio_s and nxt not in {"done", ""} and status != "done":
                # Count capped audio hours (what we assume we label).
                audio_left_s += min(float(audio_s), float(n_hops) * hop_s)

        entry = {
            "session": s,
            "status": status,
            "next": nxt,
            "help": help_n,
            "eta_s": round(float(eta_s), 1),
            "kind": kind,
            "n_hops_est": int(round(n_hops)),
            "audio_s": audio_s,
            "hops_capped": capped,
        }
        per_session.append(entry)
        row["eta_s"] = entry["eta_s"]
        row["eta_kind"] = kind

    need_vision = int(stages.get("need_vision") or 0)
    vision_etas = [p["eta_s"] for p in per_session if p["kind"] == "full" and p["status"] != "running"]
    avg_full = (sum(vision_etas) / len(vision_etas)) if vision_etas else _full_session_cost(min(hop_cap, 1440.0))
    unshown_vision = max(
        0, need_vision - sum(1 for p in per_session if p["next"] == "vision" and p["status"] != "running")
    )
    unshown_extra = unshown_vision * avg_full
    total_remaining += unshown_extra
    # Unshown sessions usually still have help piles further down — count half into priority.
    priority_remaining += 0.5 * unshown_extra

    total_clock = _eta_clock(total_remaining)
    priority_clock = _eta_clock(priority_remaining)
    sessions_left = int(stages.get("left") or 0)
    per_session_avg = round(total_remaining / sessions_left, 1) if sessions_left else None

    sessions_per_hour = None
    if per_session_avg and per_session_avg > 0:
        sessions_per_hour = round(3600.0 / per_session_avg, 2)
    hours_to_clear = round(total_remaining / 3600.0, 2) if total_remaining else 0.0
    priority_h = round(priority_remaining / 3600.0, 2) if priority_remaining else 0.0

    from zoneinfo import ZoneInfo

    now_et = datetime.now(ZoneInfo("America/New_York"))
    pause_end = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
    secs_to_pause_end = max(0.0, (pause_end - now_et).total_seconds())
    clears_before_pause_end = bool(secs_to_pause_end > 0 and total_remaining <= secs_to_pause_end)
    priority_before_pause = bool(secs_to_pause_end > 0 and priority_remaining <= secs_to_pause_end)

    return {
        "sec_per_hop": round(sec_per_hop, 3),
        "hops_per_min": round(60.0 / sec_per_hop, 2),
        "assumptions": {
            "hop_s": hop_s,
            "hop_cap": int(hop_cap),
            "acoustic_mean_s": round(acoustic_mean, 1),
            "combine_mean_s": round(combine_mean, 1),
            "consensus_mean_s": round(consensus_mean, 1),
            "avg_full_session_s": round(avg_full, 1),
            "unshown_vision_sessions": unshown_vision,
            "unshown_extra_s": round(unshown_extra, 1),
            "source": "live_rate"
            if (live.get("active") and phase == "vision" and hop_i >= 5 and elapsed > 1)
            else "defaults_or_ledger",
        },
        "current_session": current,
        "per_session_avg_s": per_session_avg,
        "sessions_left": sessions_left,
        "sessions_per_hour": sessions_per_hour,
        "total": {
            **total_clock,
            "remaining_h": hours_to_clear,
            "audio_left_h": round(audio_left_s / 3600.0, 2) if audio_left_s else None,
            "label_wall_per_audio": (
                round(total_remaining / audio_left_s, 2) if audio_left_s and total_remaining else None
            ),
        },
        "priority": {
            **priority_clock,
            "remaining_h": priority_h,
            "note": "running + help-pile sessions (help>0)",
        },
        "window": {
            "now_et": now_et.strftime("%Y-%m-%d %H:%M ET"),
            "secs_to_16et": round(max(0.0, secs_to_pause_end), 1),
            "hours_to_16et": round(secs_to_pause_end / 3600.0, 2),
            "clears_before_16et": clears_before_pause_end,
            "priority_before_16et": priority_before_pause,
            "overnight_budget_h": 4.0,
            "fits_one_overnight": hours_to_clear <= 4.0,
            "overnights_needed": round(hours_to_clear / 4.0, 1) if hours_to_clear else 0.0,
            "priority_overnights": round(priority_h / 4.0, 1) if priority_h else 0.0,
        },
        "queue_etas": per_session,
    }
