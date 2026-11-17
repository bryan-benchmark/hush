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

# Live pictures/min: rolling wall window (not cumulative — survives resume/warmup).
RATE_WINDOW_S = 60.0
RATE_KEEP_S = 120.0
RATE_MIN_SPAN_S = 15.0


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def timing_jsonl(root: Path | None = None) -> Path:
    return farm_label_dir(root) / "audit" / "LABEL_TIMING.jsonl"


def timing_snapshot(root: Path | None = None) -> Path:
    return farm_label_dir(root) / "audit" / "LABEL_TIMING.json"


def rate_ring_path(root: Path | None = None) -> Path:
    return farm_label_dir(root) / "audit" / "VISION_RATE_RING.json"


def record_vision_rate_sample(
    *,
    hop_i: int | float | None,
    session: str | None = None,
    root: Path | None = None,
    kind: str = "pictures",
) -> None:
    """Append a hop progress sample for a rolling /min gauge (pictures or sound)."""
    record_label_rate_sample(hop_i=hop_i, session=session, root=root, kind=kind)


def record_label_rate_sample(
    *,
    hop_i: int | float | None,
    session: str | None = None,
    root: Path | None = None,
    kind: str = "pictures",
) -> None:
    """Append a hop progress sample for the rolling stills/min (or sound hops/min) gauge."""
    if hop_i is None:
        return
    try:
        hi = int(hop_i)
    except (TypeError, ValueError):
        return
    kind = str(kind or "pictures")
    path = rate_ring_path(root)
    now = time.monotonic()
    with _LOCK:
        samples: list[dict[str, Any]] = []
        if path.is_file():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                samples = list(raw.get("samples") or [])
            except json.JSONDecodeError:
                samples = []
        same = [s for s in samples if str(s.get("kind") or "pictures") == kind]
        other = [s for s in samples if str(s.get("kind") or "pictures") != kind]
        # Session change or hop rewind (new tape / restart) → fresh ring for this kind.
        if same:
            last = same[-1]
            if session and last.get("session") and str(last.get("session")) != str(session):
                same = []
            elif int(last.get("hop_i") or 0) > hi + 2:
                same = []
        same.append({"t": now, "hop_i": hi, "session": session, "kind": kind})
        same = [s for s in same if now - float(s.get("t") or 0) <= RATE_KEEP_S]
        if len(same) > 240:
            same = same[-240:]
        other = [s for s in other if now - float(s.get("t") or 0) <= RATE_KEEP_S]
        samples = other + same
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"updated_utc": _now(), "samples": samples}, indent=2) + "\n",
            encoding="utf-8",
        )


def rolling_vision_rate(
    *,
    window_s: float = RATE_WINDOW_S,
    root: Path | None = None,
    kind: str = "pictures",
) -> dict[str, Any] | None:
    """hops/min from hop_i deltas over the last ``window_s`` of wall clock."""
    return rolling_label_rate(window_s=window_s, root=root, kind=kind)


def _rate_samples(root: Path | None = None, *, kind: str = "pictures") -> list[dict[str, Any]]:
    path = rate_ring_path(root)
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return [
            s
            for s in list(raw.get("samples") or [])
            if str(s.get("kind") or "pictures") == str(kind or "pictures")
        ]
    except json.JSONDecodeError:
        return []


def rolling_label_rate(
    *,
    window_s: float = RATE_WINDOW_S,
    root: Path | None = None,
    kind: str = "pictures",
) -> dict[str, Any] | None:
    """hops/min from hop_i deltas over the last ``window_s`` of wall clock."""
    samples = _rate_samples(root, kind=kind)
    if len(samples) < 2:
        return None
    now = time.monotonic()
    window_s = max(float(window_s), RATE_MIN_SPAN_S)
    # Prefer oldest sample still inside the window; else the oldest kept sample.
    in_win = [s for s in samples if now - float(s.get("t") or 0) <= window_s]
    if len(in_win) < 2:
        in_win = samples[-min(len(samples), 30) :]
    a, b = in_win[0], in_win[-1]
    dt = float(b.get("t") or 0) - float(a.get("t") or 0)
    dh = int(b.get("hop_i") or 0) - int(a.get("hop_i") or 0)
    if dt < RATE_MIN_SPAN_S or dh < 0:
        return None
    sec_per_hop = dt / max(dh, 1)
    if not (0.05 <= sec_per_hop <= 120.0):
        return None
    return {
        "source": "rolling_window",
        "kind": kind,
        "window_s": round(window_s, 1),
        "span_s": round(dt, 2),
        "hops": dh,
        "sec_per_hop": round(sec_per_hop, 3),
        "hops_per_min": round(60.0 / sec_per_hop, 2),
        "session": b.get("session"),
    }


def label_rate_history(
    *,
    lookback_s: float = 20.0,
    root: Path | None = None,
    kind: str = "pictures",
    max_points: int = 60,
) -> list[dict[str, Any]]:
    """Time series of instantaneous hops/min for a live desk graph.

    Each point is hops/min vs a sample about ``lookback_s`` earlier (not the
    full 60s meter). Ages are seconds before *now* (larger = older).
    """
    samples = _rate_samples(root, kind=kind)
    if len(samples) < 2:
        return []
    now = time.monotonic()
    lookback_s = max(float(lookback_s), RATE_MIN_SPAN_S)
    # Walk chronologically; for each sample find the latest earlier sample
    # at least lookback_s behind.
    points: list[dict[str, Any]] = []
    j = 0
    for i, b in enumerate(samples):
        tb = float(b.get("t") or 0)
        target = tb - lookback_s
        while j < i and float(samples[j].get("t") or 0) < target - 1.0:
            j += 1
        # Prefer the sample closest to ``target`` without going past ``tb``.
        a = None
        best = None
        for k in range(j, i):
            ta = float(samples[k].get("t") or 0)
            if ta > tb:
                break
            gap = abs(ta - target)
            if best is None or gap < best:
                best = gap
                a = samples[k]
        if a is None:
            continue
        dt = tb - float(a.get("t") or 0)
        dh = int(b.get("hop_i") or 0) - int(a.get("hop_i") or 0)
        if dt < RATE_MIN_SPAN_S * 0.75 or dh < 0:
            continue
        sec_per_hop = dt / max(dh, 1)
        if not (0.05 <= sec_per_hop <= 120.0):
            continue
        points.append(
            {
                "age_s": round(now - tb, 1),
                "per_min": round(60.0 / sec_per_hop, 2),
                "hop_i": int(b.get("hop_i") or 0),
            }
        )
    if len(points) <= max_points:
        return points
    # Even downsample; always keep the newest point.
    out: list[dict[str, Any]] = []
    last_i = len(points) - 1
    step = last_i / float(max_points - 1)
    seen: set[int] = set()
    for n in range(max_points):
        idx = int(round(n * step)) if n < max_points - 1 else last_i
        if idx in seen:
            continue
        seen.add(idx)
        out.append(points[idx])
    return out


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

# Healthy solo-box baselines (one label worker, players idle / capture off).
# Measured ~7s/still for qwen2.5vl:7b → ~8.5 stills/min.
BASELINE_STILLS_PER_MIN = 8.5
BASELINE_SEC_PER_STILL = 7.0
BASELINE_WALL_PER_CONTENT = 1.4
# Job heartbeat older than this while "active" ⇒ stalled (0 stills/min).
LIVE_STALL_SEC = 90.0


def _f(x: Any, default: float | None = None) -> float | None:
    try:
        if x is None or x == "":
            return default
        return float(x)
    except (TypeError, ValueError):
        return default


def fmt_content_clock(sec: float | None) -> str:
    """Human tape time: ~37.5 min, ~2h — not hop counts."""
    if sec is None:
        return "—"
    try:
        n = float(sec)
    except (TypeError, ValueError):
        return "—"
    if n < 0:
        n = 0.0
    if n < 60:
        return f"~{int(round(n))}s"
    if n < 3600:
        m = n / 60.0
        # Keep one decimal so "~37.5 min" stays readable (not "~38 min").
        txt = f"{m:.1f}".rstrip("0").rstrip(".")
        return f"~{txt} min"
    h = n / 3600.0
    txt = f"{h:.1f}".rstrip("0").rstrip(".")
    return f"~{txt}h"


def tape_through_plain(
    *,
    pos_s: float | None,
    total_s: float | None,
    audit: str | None = None,
    waiting: bool = False,
) -> str:
    """Common-sense progress for any audit.

    Examples:
      ~37.5 min through a ~2h recording
      pictures · ~37.5 min through a ~2h recording
      sound · waiting on a ~2h recording
    """
    total = fmt_content_clock(total_s) if total_s else "recording"
    if waiting or pos_s is None:
        body = f"waiting on a {total} recording" if total_s else "waiting"
    elif total_s:
        body = f"{fmt_content_clock(pos_s)} through a {total} recording"
    else:
        body = f"{fmt_content_clock(pos_s)} through this recording"
    if audit:
        return f"{audit} · {body}"
    return body


def audit_plain_name(step: str | None) -> str:
    return {
        "vision": "pictures",
        "asr": "transcript",
        "acoustic": "sound",
        "combine": "merge",
        "consensus": "auto-lock",
        "pictures": "pictures",
        "transcript": "transcript",
        "sound": "sound",
        "auto-lock": "auto-lock",
    }.get(str(step or ""), str(step or "audit"))


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
    # After checkpoint resume, hop_i includes prior work but step_elapsed does not.
    resumed_hops = _f(live.get("resumed_hops"), 0.0) or 0.0
    hops_for_rate = max(0.0, float(hop_i) - float(resumed_hops))
    if hops_for_rate < 5 and hop_i >= 5 and resumed_hops <= 0:
        hops_for_rate = float(hop_i)

    job_age_s = _f(live.get("job_age_s"))
    if job_age_s is None:
        upd = str(live.get("updated_utc") or "")
        if upd:
            try:
                job_age_s = (
                    datetime.now(timezone.utc)
                    - datetime.strptime(upd, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                ).total_seconds()
            except ValueError:
                job_age_s = None
    stalled = bool(live.get("active") and job_age_s is not None and job_age_s >= LIVE_STALL_SEC)

    # Live pictures/min only while phase=vision. Otherwise ETA still needs a
    # sec_per_hop assumption — but do not publish a fake live gauge (e.g. 1200/min
    # after vision ends and hop_i=hop_of lingers on the job blob).
    lock_age_s = _f(live.get("lock_age_s"))
    rate_span_s = None
    rate_source = "defaults_or_ledger"
    vision_live = bool(live.get("active") and phase == "vision" and not stalled)
    rolling = rolling_vision_rate(window_s=RATE_WINDOW_S, root=root) if vision_live else None

    sec_per_hop = None
    hops_per_min = None  # live gauge; stay None when not in vision
    if stalled and phase == "vision":
        hops_per_min = 0.0
        rate_source = "stalled"
        sec_per_hop = BASELINE_SEC_PER_STILL
    elif vision_live and rolling:
        sec_per_hop = float(rolling["sec_per_hop"])
        hops_per_min = float(rolling["hops_per_min"])
        rate_source = "rolling_window"
        rate_span_s = float(rolling.get("span_s") or RATE_WINDOW_S)
    elif vision_live:
        for cand, src in (
            (elapsed, "step_elapsed"),
            (lock_age_s, "lock_age"),
        ):
            if cand is None or hops_for_rate < 5 or cand <= 1:
                continue
            sec = float(cand) / float(hops_for_rate)
            if 0.15 <= sec <= 90.0:
                rate_span_s = float(cand)
                rate_source = src
                sec_per_hop = sec
                hops_per_min = 60.0 / sec if sec > 0 else None
                break
    if sec_per_hop is None:
        # ETA assumption only (not a live stills/min reading).
        v_mean = _f((by_step.get("vision") or {}).get("mean_s"))
        if v_mean and hop_of >= 10:
            sec_per_hop = v_mean / hop_of
        else:
            sec_per_hop = _DEFAULT_SEC_PER_HOP
        if rate_source != "stalled":
            rate_source = "defaults_or_ledger"
    sec_per_hop = max(0.15, float(sec_per_hop))  # never advertise sub-0.15s as live

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

        audit = audit_plain_name(nxt if nxt not in {"done", ""} else phase)
        # Label window length (what this pass scores), not raw WAV if the file is longer.
        label_span_s = float(n_hops) * hop_s
        if audio_s:
            label_span_s = min(float(audio_s), label_span_s)
        if status == "running":
            pos = None
            if phase == "vision" and hop_of > 0:
                pos = hop_i * hop_s
            elif live.get("t") is not None:
                pos = _f(live.get("t"))
            run_total = float(hop_of) * hop_s if hop_of else label_span_s
            if audio_s:
                run_total = min(float(audio_s), run_total)
            progress_plain = tape_through_plain(
                pos_s=pos,
                total_s=run_total,
                audit=audit_plain_name(phase or nxt),
            )
        elif status == "done" or nxt == "done":
            progress_plain = tape_through_plain(
                pos_s=label_span_s,
                total_s=label_span_s,
                audit="done",
            )
        else:
            progress_plain = tape_through_plain(
                pos_s=None,
                total_s=label_span_s,
                audit=audit,
                waiting=True,
            )
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
            "progress_plain": progress_plain,
        }
        per_session.append(entry)
        row["eta_s"] = entry["eta_s"]
        row["eta_kind"] = kind
        row["audio_s"] = audio_s
        row["progress_plain"] = progress_plain

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

    # Extrapolate content hours for tapes not in the annotated queue slice.
    known_audio = [float(p["audio_s"]) for p in per_session if p.get("audio_s")]
    avg_audio_s = (sum(known_audio) / len(known_audio)) if known_audio else (min(hop_cap, 1440.0) * hop_s)
    if unshown_vision > 0:
        audio_left_s += unshown_vision * min(float(avg_audio_s), float(hop_cap) * hop_s)

    # Running tape: content still to label ≈ left hops × hop length.
    if live.get("active") and hop_of > 0:
        left_hops = max(0.0, hop_of - hop_i) if phase == "vision" else 0.0
        cur_audio = _audio_duration_s(str(live.get("session") or ""), root)
        content_left = left_hops * hop_s if phase == "vision" else None
        current["audio_s"] = cur_audio
        current["content_left_s"] = round(content_left, 1) if content_left is not None else None
        # Live pictures pace: wall seconds per second of tape (vision only).
        current["wall_per_content"] = round(sec_per_hop / hop_s, 2) if hop_s > 0 else None
        pos_s = None
        if phase == "vision" and hop_of > 0:
            pos_s = hop_i * hop_s
        elif live.get("t") is not None:
            pos_s = _f(live.get("t"))
        # Prefer the labeled window (hop_of × hop_s), not a longer on-disk WAV.
        total_s = float(hop_of) * hop_s if hop_of else cur_audio
        if cur_audio and total_s:
            total_s = min(float(cur_audio), float(total_s))
        elif cur_audio and not total_s:
            total_s = float(cur_audio)
        current["content_pos_s"] = round(pos_s, 1) if pos_s is not None else None
        current["content_total_s"] = round(total_s, 1) if total_s is not None else None
        current["progress_plain"] = tape_through_plain(
            pos_s=pos_s,
            total_s=total_s,
            audit=audit_plain_name(phase),
            waiting=bool(stalled),
        )
        if content_left:
            audio_left_s += float(content_left)

    sound_roll = (
        rolling_label_rate(window_s=RATE_WINDOW_S, root=root, kind="sound")
        if live.get("active") and phase == "acoustic" and not stalled
        else None
    )
    sound_speed: dict[str, Any] = {
        "live_per_min": (
            round(float(sound_roll["hops_per_min"]), 2)
            if sound_roll
            else (0.0 if stalled and phase == "acoustic" else None)
        ),
        "baseline_per_min": None,
        "unit": "hops/min",
        "active": bool(live.get("active") and phase == "acoustic"),
        "pct": live.get("pct") if phase == "acoustic" else None,
        "hop_i": live.get("hop_i") if phase == "acoustic" else None,
        "hop_of": live.get("hop_of") if phase == "acoustic" else None,
        "plain": (
            f"{float(sound_roll['hops_per_min']):.0f} sound hops/min · last ~1 min"
            if sound_roll
            else (
                "Sound running"
                if live.get("active") and phase == "acoustic"
                else "Idle · after pictures on each recording"
            )
        ),
    }

    total_clock = _eta_clock(total_remaining)
    priority_clock = _eta_clock(priority_remaining)
    tapes_left = int(stages.get("left") or 0)
    # Kept for API compat — tapes vary in length, prefer content rates below.
    per_tape_avg = round(total_remaining / tapes_left, 1) if tapes_left else None
    tapes_per_hour = round(3600.0 / per_tape_avg, 2) if per_tape_avg and per_tape_avg > 0 else None
    hours_to_clear = round(total_remaining / 3600.0, 2) if total_remaining else 0.0
    priority_h = round(priority_remaining / 3600.0, 2) if priority_remaining else 0.0

    wall_per_content = (
        round(total_remaining / audio_left_s, 2) if audio_left_s and total_remaining else None
    )
    # How long 1 minute of tape takes in wall clock.
    wall_s_per_content_min = round(wall_per_content * 60.0, 1) if wall_per_content else None
    content_h_per_wall_h = round(1.0 / wall_per_content, 3) if wall_per_content and wall_per_content > 0 else None
    content_left_h = round(audio_left_s / 3600.0, 2) if audio_left_s else None
    # Live vision-only factor (usually lower than full-pipeline wall_per_content).
    live_wall_per_content = round(sec_per_hop / hop_s, 2) if hop_s > 0 else None

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
            "avg_full_tape_s": round(avg_full, 1),
            "avg_full_session_s": round(avg_full, 1),  # alias
            "avg_tape_audio_s": round(avg_audio_s, 1),
            "unshown_vision_tapes": unshown_vision,
            "unshown_vision_sessions": unshown_vision,  # alias
            "unshown_extra_s": round(unshown_extra, 1),
            "source": rate_source,
            "rate_span_s": round(rate_span_s, 1) if rate_span_s is not None else None,
        },
        "current_session": current,  # current recording (capture folder)
        "current_tape": current,
        "per_session_avg_s": per_tape_avg,  # alias — prefer pace.content
        "per_tape_avg_s": per_tape_avg,
        "sessions_left": tapes_left,
        "tapes_left": tapes_left,
        "sessions_per_hour": tapes_per_hour,
        "tapes_per_hour": tapes_per_hour,
        "pace": {
            "unit": "content",
            "hop_s": hop_s,
            "sec_per_hop": round(sec_per_hop, 3),
            # Live gauge fields — null when not currently labeling pictures.
            "hops_per_min": round(float(hops_per_min), 2) if hops_per_min is not None else None,
            "stills_per_min": round(float(hops_per_min), 2) if hops_per_min is not None else None,
            "eta_sec_per_hop": round(sec_per_hop, 3),
            # Full backlog: clock seconds spent per second of show.
            "wall_per_content": wall_per_content,
            "wall_min_per_content_min": wall_per_content,
            "wall_s_per_content_min": wall_s_per_content_min,
            "content_h_per_wall_h": content_h_per_wall_h,
            "plain": (
                f"Each minute of show needs about {wall_per_content:.1f} min of machine time"
                if wall_per_content
                else None
            ),
            "live_wall_per_content": live_wall_per_content,
            "live_plain": (
                (
                    f"Pictures now: about {float(hops_per_min):.0f}/min"
                    f" · one every {sec_per_hop:.1f}s"
                    f" · each minute of show ≈ {live_wall_per_content:.1f} min of work"
                )
                if hops_per_min is not None
                and live_wall_per_content
                and live.get("active")
                and phase == "vision"
                and not stalled
                else (
                    "Stuck — no heartbeat from the labeler"
                    if stalled and phase == "vision"
                    else None
                )
            ),
            "stalled": stalled,
            "job_age_s": round(job_age_s, 1) if job_age_s is not None else None,
            "glossary": {
                "recording": "One capture folder from a channel (also called a tape).",
                "picture": f"One TV frame the model scores, every {hop_s:g}s of the show.",
                "needs_review": "Clips where the automatics disagreed — you decide.",
            },
        },
        "speed": {
            "pictures": {
                "live_per_min": round(float(hops_per_min), 2) if hops_per_min is not None else None,
                "baseline_per_min": BASELINE_STILLS_PER_MIN,
                "unit": "pictures/min",
                "vs_baseline": (
                    round(float(hops_per_min) / BASELINE_STILLS_PER_MIN, 2)
                    if hops_per_min is not None and BASELINE_STILLS_PER_MIN
                    else None
                ),
                "stalled": stalled,
                "history": (
                    label_rate_history(lookback_s=20.0, root=root, kind="pictures")
                    if vision_live
                    else []
                ),
                "history_keep_s": RATE_KEEP_S,
                "plain": (
                    "Pictures stuck (0/min)"
                    if stalled
                    else (
                        f"{float(hops_per_min):.0f} pictures/min"
                        f" (solo baseline {BASELINE_STILLS_PER_MIN:g}/min)"
                        if hops_per_min is not None
                        else None
                    )
                ),
            },
            "transcript": {
                "live_per_min": None,
                "baseline_per_min": None,
                "unit": "—",
                "active": bool(live.get("active") and phase == "vision"),
                "plain": (
                    "On · rides with pictures"
                    if live.get("active") and phase == "vision"
                    else "Idle · runs with the picture pass"
                ),
            },
            "sound": sound_speed,
            "baseline_note": (
                "Live meters only for the pass that’s running: pictures/min (vision), "
                "sound hops/min (muter). Transcript rides with pictures — no separate /min."
            ),
        },
        "total": {
            **total_clock,
            "remaining_h": hours_to_clear,
            "content_left_h": content_left_h,
            "audio_left_h": content_left_h,  # alias
            "label_wall_per_audio": wall_per_content,
            "wall_per_content": wall_per_content,
        },
        "priority": {
            **priority_clock,
            "remaining_h": priority_h,
            "note": "running + recordings that still need your review",
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
