"""Local visual browser for episode triage (stills + ASR + acoustic + gold).

  python -m tools.windows_lab.farm_episode_viewer
  open http://127.0.0.1:3020/

Also reachable at https://ohush.co/verdict when the monitor proxies here
(OHUSH_VERDICT_ORIGIN + scripts/verdict.ps1 tunnel). The page detects /verdict
and prefixes API/still/audio paths.

Serves EPISODE_TRIAGE + per-second hops with still images from farm captures.
"""

from __future__ import annotations

import argparse
import io
import json
import mimetypes
import threading
import wave
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from .coverage_farm import farm_label_dir, streamers_capture_root

HOST = "127.0.0.1"
PORT = 3020
_VERDICT_LOCK = threading.Lock()

ALLOWED_VERDICTS = {
    "label_wrong",
    "muter_wrong",
    "looks_right",
    "unsure",
}
ALLOWED_HUMAN = {"keep", "mute"}


def _triage_path() -> Path:
    return farm_label_dir() / "audit" / "EPISODE_TRIAGE.json"


def _verdicts_path() -> Path:
    return farm_label_dir() / "audit" / "EPISODE_REVIEW_VERDICTS.json"


def _capture_by_player(pause: dict[str, Any] | None = None) -> dict[str, Any]:
    """Capture on/off per Streamers player (BlueStacks instance)."""
    pause = dict(pause or {})
    owner_off = bool(pause.get("active"))
    players: list[dict[str, Any]] = []
    try:
        from .desk_orchestrator import enabled_streamers
        from .instances import list_running_engines
        from .locks import get_lock

        running = set(list_running_engines() or [])
        for row in enabled_streamers():
            iid = str(row.get("id") or row.get("engine") or "")
            if not iid:
                continue
            lock = get_lock("streamers", iid) or {}
            recording = bool(lock) and not str(lock.get("session_id") or "").startswith("starting_")
            engine_up = iid in running or str(row.get("engine") or "") in running
            if owner_off:
                state = "off"
                why = "owner capture off"
            elif recording:
                state = "on"
                why = str(lock.get("session_id") or "recording")
            else:
                state = "off"
                why = "idle" if engine_up else "engine stopped"
            players.append(
                {
                    "id": iid,
                    "engine": row.get("engine") or iid,
                    "enabled": bool(row.get("enabled", True)),
                    "capture": state,
                    "recording": recording,
                    "engine_up": engine_up,
                    "why": why,
                    "session_id": lock.get("session_id"),
                    "job_id": lock.get("job_id"),
                }
            )
    except Exception as exc:  # noqa: BLE001
        return {
            "owner_capture": "off" if owner_off else "on",
            "owner_off": owner_off,
            "why": pause.get("why"),
            "players": [],
            "on_n": 0,
            "off_n": 0,
            "error": str(exc),
        }
    on_n = sum(1 for p in players if p.get("capture") == "on")
    off_n = sum(1 for p in players if p.get("capture") != "on")
    return {
        "owner_capture": "off" if owner_off else "on",
        "owner_off": owner_off,
        "why": pause.get("why"),
        "set_utc": pause.get("set_utc"),
        "players": players,
        "on_n": on_n,
        "off_n": off_n,
    }


def _overnight_dashboard() -> dict[str, Any]:
    """Compact ops board for /dashboard (overnight verdict + backlog)."""
    label = farm_label_dir()
    board_path = label / "overnight_verdict.json"
    board: dict[str, Any] = {}
    if board_path.is_file():
        try:
            board = json.loads(board_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            board = {"error": "bad overnight_verdict.json"}
    try:
        from .farm_verdict_audit import write_overnight_board

        board = write_overnight_board()
    except Exception as exc:  # noqa: BLE001
        board = {**board, "refresh_error": str(exc)}
    pause: dict[str, Any] = {}
    try:
        from .capture_pause import is_paused

        pause = is_paused()
    except Exception as exc:  # noqa: BLE001
        pause = {"active": False, "error": str(exc)}
    capture = _capture_by_player(pause)
    lock: dict[str, Any] = {}
    try:
        from .farm_label_lock import status as label_lock_status

        lock = label_lock_status()
    except Exception as exc:  # noqa: BLE001
        lock = {"held": False, "error": str(exc)}
    triage = _load_triage()
    pending = 0
    done = 0
    for s in triage.get("sessions") or []:
        for e in s.get("episodes") or []:
            # done tracked in human frames; approximate from triage fields if present
            pending += 1
    try:
        human = _load_human_frames()
        done = len(human.get("done") or {})
        pending = max(0, pending - done)
    except Exception:
        pass
    sched: dict[str, Any] = {}
    try:
        from .farm_loop import schedule_window

        sched = schedule_window()
    except Exception as exc:  # noqa: BLE001
        sched = {"error": str(exc)}
    job: dict[str, Any] = {}
    lab_path = label / "audit" / "LAB_STATUS.json"
    if lab_path.is_file():
        try:
            lab = json.loads(lab_path.read_text(encoding="utf-8"))
            job = dict(lab.get("job") or {})
        except json.JSONDecodeError:
            job = {}
    hop_i = job.get("hop_i")
    hop_of = job.get("hop_of")
    pct = None
    try:
        if hop_i is not None and hop_of:
            pct = round(100.0 * float(hop_i) / float(hop_of), 1)
    except (TypeError, ValueError, ZeroDivisionError):
        pct = None
    live = {
        "phase": job.get("phase"),
        "session": job.get("session"),
        "session_i": job.get("session_i"),
        "session_of": job.get("session_of"),
        "hop_i": hop_i,
        "hop_of": hop_of,
        "pct": pct,
        "t": job.get("t"),
        "model": job.get("model"),
        "note": job.get("note"),
        "updated_utc": job.get("updated_utc"),
        "active": bool(job.get("phase") and str(job.get("phase")) not in {"idle", ""}),
    }
    hierarchy: dict[str, Any] = {}
    try:
        from .farm_verdict_audit import backlog_hierarchy

        hierarchy = backlog_hierarchy(live_job=live, queue_limit=48)
    except Exception as exc:  # noqa: BLE001
        hierarchy = {"error": str(exc)}
    label_timing: dict[str, Any] = {}
    try:
        from .farm_label_timing import load_summary

        label_timing = load_summary()
        # Approximate live elapsed from label-lock age when worker predates timing.
        if live.get("active") and lock.get("held") and lock.get("age_s") is not None:
            running = dict(label_timing.get("running") or {})
            key = f"{live.get('session')}|{live.get('phase')}"
            if key not in running and live.get("session") and live.get("phase"):
                running[key] = {
                    "session": live.get("session"),
                    "step": live.get("phase"),
                    "elapsed_s": round(float(lock.get("age_s") or 0), 1),
                    "started_utc": None,
                    "approx": True,
                    "note": "from label_lock.age_s (timing begin missed mid-flight)",
                }
                label_timing["running"] = running
        # Attach live elapsed onto live_job for the progress card.
        for _k, rv in dict(label_timing.get("running") or {}).items():
            if rv.get("session") == live.get("session") and rv.get("step") == live.get("phase"):
                live["step_elapsed_s"] = rv.get("elapsed_s")
                live["step_started_utc"] = rv.get("started_utc")
                if rv.get("approx"):
                    live["step_elapsed_approx"] = True
                break
        if live.get("step_elapsed_s") is None and live.get("active"):
            try:
                live["step_elapsed_s"] = round(float(lock.get("age_s") or 0), 1)
                live["step_elapsed_approx"] = True
            except (TypeError, ValueError):
                pass
        # Mirror live elapsed onto hierarchy queue row.
        if live.get("active") and live.get("step_elapsed_s") is not None:
            for row in hierarchy.get("queue") or []:
                if row.get("session") == live.get("session"):
                    tm = dict(row.get("timing") or {})
                    tm["live"] = {
                        "step": live.get("phase"),
                        "elapsed_s": live.get("step_elapsed_s"),
                        "started_utc": live.get("step_started_utc"),
                        "approx": bool(live.get("step_elapsed_approx")),
                    }
                    row["timing"] = tm
                    break
    except Exception as exc:  # noqa: BLE001
        label_timing = {"error": str(exc)}
    etas: dict[str, Any] = {}
    try:
        from .farm_label_timing import estimate_label_etas

        etas = estimate_label_etas(
            live_job=live,
            hierarchy=hierarchy,
            timing=label_timing,
            queue_annotate_limit=48,
        )
        # Surface key ETA on live_job for the top card.
        cur = etas.get("current_session") or {}
        if cur.get("remaining_s") is not None:
            live["eta_remaining_s"] = cur.get("remaining_s")
            live["eta_finish_et"] = cur.get("finish_et")
            live["sec_per_hop"] = etas.get("sec_per_hop")
            live["hops_per_min"] = etas.get("hops_per_min")
    except Exception as exc:  # noqa: BLE001
        etas = {"error": str(exc)}
    return {
        "ok": True,
        "updated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "overnight": board,
        "capture_pause": pause,
        "capture": capture,
        "label_lock": lock,
        "live_job": live,
        "hierarchy": hierarchy,
        "etas": etas,
        "label_timing": {
            "totals": label_timing.get("totals"),
            "by_step": label_timing.get("by_step"),
            "running": label_timing.get("running"),
            "ledger": str(label / "audit" / "LABEL_TIMING.jsonl"),
            "error": label_timing.get("error"),
        },
        "schedule": {
            "mode": sched.get("mode"),
            "why": sched.get("why"),
            "do_label": sched.get("do_label"),
            "do_record": sched.get("do_record"),
        },
        "verdict_queue": {
            "pending_approx": pending,
            "done": done,
            "episodes": sum(len(s.get("episodes") or []) for s in (triage.get("sessions") or [])),
        },
        "links": {
            "triage": "/",
            "dashboard": "/dashboard",
            "board_md": str(label / "OVERNIGHT_VERDICT.md"),
            "tick_log": str(label / "audit" / "verdict_ticks.jsonl"),
        },
    }


def _human_frames_path() -> Path:
    return farm_label_dir() / "audit" / "EPISODE_HUMAN_FRAMES.json"


def _verdict_key(session: str, t0: float, t1: float) -> str:
    return f"{session}|{float(t0):.3f}|{float(t1):.3f}"


def _load_verdicts() -> dict:
    path = _verdicts_path()
    if not path.is_file():
        return {"verdicts": {}, "updated_utc": None}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"verdicts": {}, "updated_utc": None}


def _save_verdict(session: str, t0: float, t1: float, verdict: str, note: str = "") -> dict:
    if verdict not in ALLOWED_VERDICTS:
        raise ValueError(f"bad verdict {verdict}")
    key = _verdict_key(session, t0, t1)
    with _VERDICT_LOCK:
        blob = _load_verdicts()
        verdicts = dict(blob.get("verdicts") or {})
        verdicts[key] = {
            "session": session,
            "t0": float(t0),
            "t1": float(t1),
            "verdict": verdict,
            "note": (note or "")[:500],
            "utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        out = {
            "updated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "verdicts": verdicts,
        }
        path = _verdicts_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
        return verdicts[key]


def _load_triage() -> dict:
    path = _triage_path()
    if not path.is_file():
        return {"sessions": [], "error": f"missing {path} — run farm_episode_triage first"}
    return json.loads(path.read_text(encoding="utf-8"))


def _load_human_frames() -> dict:
    path = _human_frames_path()
    if not path.is_file():
        return {"sessions": {}, "cuts": {}, "done": {}, "updated_utc": None}
    try:
        blob = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"sessions": {}, "cuts": {}, "done": {}, "updated_utc": None}
    blob.setdefault("sessions", {})
    blob.setdefault("cuts", {})
    blob.setdefault("done", {})
    return blob


def _write_human_frames(blob: dict) -> dict:
    path = _human_frames_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    blob["updated_utc"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    path.write_text(json.dumps(blob, indent=2) + "\n", encoding="utf-8")
    return blob


def _save_human_frames(
    session: str,
    *,
    marks: dict[str, str] | None = None,
    clear_times: list[float] | None = None,
    cut_t: float | None = None,
    stretch_times: list[float] | None = None,
    t0: float | None = None,
    t1: float | None = None,
    done: bool | None = None,
) -> dict:
    """Update per-second human keep/mute marks for a session.

    - marks: { "27": "mute", ... } merge
    - clear_times: drop marks at those seconds
    - cut_t + stretch_times: keep before cut_t, mute from cut_t onward
    - done: mark stretch confirmed / remove from queue (requires t0,t1)
    """
    if not session or ".." in session or "/" in session or "\\" in session:
        raise ValueError("bad session")
    with _VERDICT_LOCK:
        blob = _load_human_frames()
        sessions = dict(blob.get("sessions") or {})
        cuts = dict(blob.get("cuts") or {})
        done_map = dict(blob.get("done") or {})
        cur = dict(sessions.get(session) or {})

        if clear_times is not None:
            for t in clear_times:
                cur.pop(f"{float(t):g}", None)
                cur.pop(str(int(t)) if float(t) == int(t) else f"{float(t):g}", None)
                # also try both int and float keys
                cur.pop(str(int(float(t))), None)

        if marks:
            for k, v in marks.items():
                key = f"{float(k):g}"
                if v in ("", None, "clear", "unset"):
                    cur.pop(key, None)
                    cur.pop(str(int(float(k))), None)
                    continue
                if v not in ALLOWED_HUMAN:
                    raise ValueError(f"bad human mark {v}")
                cur[key] = v

        if cut_t is not None and stretch_times:
            ct = float(cut_t)
            for t in stretch_times:
                tt = float(t)
                key = f"{tt:g}"
                cur[key] = "mute" if tt + 1e-9 >= ct else "keep"
            if t0 is not None and t1 is not None:
                cuts[_verdict_key(session, float(t0), float(t1))] = {
                    "session": session,
                    "t0": float(t0),
                    "t1": float(t1),
                    "cut_t": ct,
                    "utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                }

        ep_done = None
        if done is not None and t0 is not None and t1 is not None:
            dk = _verdict_key(session, float(t0), float(t1))
            if done:
                ep_done = {
                    "session": session,
                    "t0": float(t0),
                    "t1": float(t1),
                    "utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                }
                done_map[dk] = ep_done
            else:
                done_map.pop(dk, None)

        sessions[session] = cur
        out = _write_human_frames({"sessions": sessions, "cuts": cuts, "done": done_map})
        return {
            "session": session,
            "marks": cur,
            "cut": cuts.get(_verdict_key(session, float(t0 or 0), float(t1 or 0))) if t0 is not None else None,
            "done": ep_done if done else None,
            "done_map": done_map,
        }


def _session_dir(session: str) -> Path:
    return streamers_capture_root() / session


def _slice_wav(session: str, t0: float, t1: float, *, pad_s: float = 0.5) -> bytes:
    """Return a small WAV clip for [t0-pad, t1+pad] from session audio.wav."""
    wav_path = _session_dir(session) / "audio.wav"
    if not wav_path.is_file():
        raise FileNotFoundError(f"missing audio.wav for {session}")
    if t1 < t0:
        t0, t1 = t1, t0
    with wave.open(str(wav_path), "rb") as wf:
        rate = wf.getframerate()
        nch = wf.getnchannels()
        sw = wf.getsampwidth()
        nframes = wf.getnframes()
        dur = nframes / float(rate) if rate else 0.0
        start_s = max(0.0, float(t0) - float(pad_s))
        end_s = min(dur, float(t1) + float(pad_s))
        if end_s <= start_s:
            end_s = min(dur, start_s + 1.0)
        start = int(start_s * rate)
        count = max(1, int((end_s - start_s) * rate))
        wf.setpos(min(start, max(0, nframes - 1)))
        frames = wf.readframes(count)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as out:
        out.setnchannels(nch)
        out.setsampwidth(sw)
        out.setframerate(rate)
        out.writeframes(frames)
    return buf.getvalue()


def _hops(session: str) -> list[dict]:
    path = farm_label_dir() / "audit" / session / "hops.jsonl"
    if not path.is_file():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def _still_name_for_t(session: str, t: float, vision: dict | None = None) -> str:
    """Prefer vision receipt name; else capture still_tNNNNN.N.jpg by second."""
    v = vision or {}
    named = v.get("still_name") or (Path(str(v.get("still") or "")).name if v.get("still") else "")
    if named:
        return str(named)
    cand = f"still_t{float(t):07.1f}.jpg"
    if (_session_dir(session) / "stills" / cand).is_file():
        return cand
    return ""


def _episode_frames(session: str, t0: float, t1: float) -> list[dict]:
    """Every 1s hop in [t0,t1] with still URL + channel fields."""
    sd = _session_dir(session)
    out = []
    for h in _hops(session):
        t = float(h.get("t") or 0)
        if t < t0 - 1e-6 or t > t1 + 1e-6:
            continue
        ch = h.get("channels") or {}
        v = ch.get("vision") or {}
        a = ch.get("asr") or {}
        ac = ch.get("acoustic") or {}
        g = ch.get("gold") or {}
        still_name = _still_name_for_t(session, t, v)
        still_path = sd / "stills" / still_name if still_name else None
        out.append(
            {
                "t": t,
                "disagreement": bool(h.get("disagreement")),
                "why": h.get("why"),
                "still_name": still_name,
                "still_url": (
                    f"/still?session={session}&file={still_name}" if still_name and still_path and still_path.is_file() else None
                ),
                "vision_class": v.get("class") or v.get("acoustic_bucket"),
                "vision_bucket": v.get("acoustic_bucket"),
                "visual": v.get("visual") or "",
                "asr_lex": a.get("lexicon") or a.get("acoustic_bucket"),
                "asr_text": a.get("text") or "",
                "p": (ac or {}).get("p"),
                "action": (ac or {}).get("action"),
                "force_play": (ac or {}).get("force_play"),
                "gold": (g or {}).get("bucket"),
                "gold_range": (
                    f"{(g or {}).get('start_s')}–{(g or {}).get('end_s')}" if g else None
                ),
            }
        )
    out.sort(key=lambda r: float(r["t"]))
    return out


def _human_mark_at(marks: dict, t: float) -> str | None:
    if not marks:
        return None
    key = f"{float(t):g}"
    if key in marks:
        return marks[key]
    ikey = str(int(t)) if float(t) == int(t) else None
    if ikey and ikey in marks:
        return marks[ikey]
    return None


DEFAULT_CHUNK_SIZE = 4


def _flat_episodes(triage: dict) -> list[tuple[str, dict]]:
    out: list[tuple[str, dict]] = []
    for s in triage.get("sessions") or []:
        session = s["session"]
        for e in s.get("episodes") or []:
            out.append((session, e))
    return out


def _enrich(triage: dict, *, chunk_size: int = DEFAULT_CHUNK_SIZE) -> dict:
    """Attach frames only for the next undoned chunk (keeps localhost light)."""
    verdicts = (_load_verdicts().get("verdicts") or {})
    human_blob = _load_human_frames()
    human_sessions = human_blob.get("sessions") or {}
    human_cuts = human_blob.get("cuts") or {}
    human_done = human_blob.get("done") or {}
    chunk_size = max(1, min(int(chunk_size), 12))

    flat = _flat_episodes(triage)
    pending_keys: list[str] = []
    for session, e in flat:
        dk = _verdict_key(session, float(e["t0"]), float(e["t1"]))
        if dk not in human_done:
            pending_keys.append(dk)
    chunk_keys = set(pending_keys[:chunk_size])

    sessions = []
    chunk_episode_n = 0
    for s in triage.get("sessions") or []:
        session = s["session"]
        marks = human_sessions.get(session) or {}
        episodes = []
        for e in s.get("episodes") or []:
            t0 = float(e["t0"])
            t1 = float(e["t1"])
            dk = _verdict_key(session, t0, t1)
            in_chunk = dk in chunk_keys
            frames: list[dict] = []
            if in_chunk:
                frames = _episode_frames(session, t0, t1)
                for f in frames:
                    f["human"] = _human_mark_at(marks, float(f["t"]))
                chunk_episode_n += 1
            vrec = verdicts.get(dk)
            episodes.append(
                {
                    **e,
                    "frames": frames,
                    "n_frames": len(frames) if in_chunk else int(round(float(e.get("len_s") or 0))),
                    "review": vrec,
                    "human_cut": human_cuts.get(dk),
                    "human_done": human_done.get(dk),
                    "in_chunk": in_chunk,
                }
            )
        sessions.append({**s, "episodes": episodes, "session_dir": str(_session_dir(session))})
    return {
        **triage,
        "sessions": sessions,
        "verdicts": verdicts,
        "human_frames": human_sessions,
        "human_cuts": human_cuts,
        "human_done": human_done,
        "chunk": {
            "size": chunk_size,
            "in_chunk": chunk_episode_n,
            "pending_total": len(pending_keys),
            "done_total": len(human_done),
            "episode_total": len(flat),
        },
    }


HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Episode triage</title>
<style>
  :root {
    --bg: #e8eef2;
    --ink: #12202b;
    --muted: #5a6b78;
    --panel: #f7fafc;
    --line: #c5d2dc;
    --ad: #c2410c;
    --show: #0f766e;
    --mute: #b91c1c;
    --play: #1d4ed8;
    --hi: #fef08a;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
    background:
      linear-gradient(180deg, #d7e4ec 0%, var(--bg) 220px),
      var(--bg);
    color: var(--ink);
  }
  header {
    position: sticky; top: 0; z-index: 5;
    background: rgba(231,238,242,.94);
    border-bottom: 1px solid var(--line);
    padding: 8px 14px;
    backdrop-filter: blur(8px);
    display: flex; align-items: flex-start; justify-content: space-between; gap: 12px;
  }
  header .titles { min-width: 0; }
  header h1 {
    margin: 0;
    font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
    font-size: 14px;
    font-weight: 700;
    letter-spacing: -0.01em;
  }
  header .sub { margin: 2px 0 0; color: var(--muted); font-size: 11px; }
  header .right {
    display: flex; align-items: flex-start; gap: 10px; flex-shrink: 0;
  }
  .btn-next {
    border: 1px solid #0f766e; background: #0f766e; color: #fff;
    border-radius: 8px; padding: 8px 14px; cursor: pointer;
    font: inherit; font-weight: 700; font-size: 13px; white-space: nowrap;
  }
  .btn-next:hover { background: #0d9488; border-color: #0d9488; }
  .btn-next:disabled { opacity: 0.45; cursor: default; }
  .nav-link {
    border: 1px solid var(--line); background: #fff; color: var(--ink);
    border-radius: 6px; padding: 6px 10px; cursor: pointer;
    font: inherit; font-weight: 700; font-size: 12px; white-space: nowrap;
    text-decoration: none; display: inline-flex; align-items: center;
  }
  .nav-link:hover { border-color: #0f766e; color: #0f766e; }
  .legend {
    display: flex; flex-wrap: wrap; gap: 4px 10px;
    justify-content: flex-end; max-width: 42vw;
    margin: 0; font-size: 10px; color: var(--muted); line-height: 1.3;
  }
  .legend b { color: var(--ink); font-weight: 600; }
  .swatch {
    display: inline-block; width: 8px; height: 8px; border-radius: 2px;
    margin-right: 3px; vertical-align: -1px;
  }
  .layout { display: grid; grid-template-columns: 260px 1fr; min-height: calc(100vh - 52px); padding-bottom: 72px; }
  nav {
    border-right: 1px solid var(--line);
    background: rgba(247,250,252,.85);
    overflow: auto;
    padding: 8px;
  }
  .sess {
    font-size: 10px; text-transform: uppercase; letter-spacing: .06em;
    color: var(--muted); margin: 8px 4px 4px; font-weight: 600;
  }
  nav button {
    display: block; width: 100%; text-align: left; margin: 0 0 6px;
    border: 1px solid var(--line); background: var(--panel); color: var(--ink);
    border-radius: 8px; padding: 7px 9px; cursor: pointer;
  }
  nav button:hover { border-color: #8aa0b0; }
  nav button.active {
    border-color: var(--ink); box-shadow: 0 0 0 1px var(--ink);
  }
  .pill {
    display: inline-block; font-size: 10px; font-weight: 700;
    padding: 2px 6px; border-radius: 4px; margin-bottom: 3px;
  }
  .pill.fix { background: #ffedd5; color: #9a3412; }
  .pill.muter { background: #fee2e2; color: #991b1b; }
  .pill.hang { background: #dbeafe; color: #1e40af; }
  .pill.review { background: #e5e7eb; color: #374151; }
  .nav-title { font-size: 12px; font-weight: 650; line-height: 1.25; }
  .nav-meta { margin-top: 2px; font-size: 11px; color: var(--muted); }
  main { padding: 10px 14px 32px; overflow: auto; }
  .hero-title {
    font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
    font-size: 18px; margin: 0 0 2px; letter-spacing: -0.02em; font-weight: 700;
  }
  .hero-do {
    font-size: 12px; line-height: 1.35; margin: 0 0 8px; max-width: 72ch;
  }
  .meta-bar {
    display: flex; flex-wrap: wrap; gap: 4px 12px;
    margin: 2px 0 6px; font-size: 11px; color: var(--muted);
  }
  .meta-bar b { color: var(--ink); font-weight: 650; }
  .strip-wrap {
    background: var(--panel); border: 1px solid var(--line);
    border-radius: 10px; padding: 8px;
    display: flex; flex-direction: column;
    min-height: 0;
    max-height: calc(100vh - 220px);
  }
  .strip-head {
    display: flex; align-items: center; justify-content: space-between; gap: 8px;
    margin: 0 0 6px; flex-shrink: 0;
  }
  .strip-label {
    font-size: 11px; color: var(--muted); margin: 0; font-weight: 600;
  }
  .strip-clear {
    border: 1px solid var(--line); background: #fff; color: var(--muted);
    border-radius: 6px; padding: 3px 8px; cursor: pointer; font: inherit; font-size: 11px;
  }
  .strip-clear:hover { border-color: var(--ink); color: var(--ink); }
  .strip {
    display: flex; flex-direction: column; gap: 8px;
    overflow-y: auto; overflow-x: hidden; padding: 2px 2px 8px;
    scroll-snap-type: y proximity;
    min-height: 0;
  }
  .card {
    display: grid;
    grid-template-columns: 200px minmax(180px, 1fr) 168px;
    gap: 0;
    align-items: stretch;
    width: 100%;
    max-width: 720px;
    flex: 0 0 auto;
    scroll-snap-align: start;
    border: 1px solid var(--line); border-radius: 10px; overflow: hidden;
    background: #fff; cursor: pointer; position: relative;
  }
  .card:hover { border-color: #8aa0b0; }
  .card.selected { border-color: var(--ink); box-shadow: 0 0 0 1px var(--ink); }
  .card.clash { box-shadow: inset 3px 0 0 #ca8a04; }
  .card .thumb { position: relative; background: #111; }
  .card .time {
    position: absolute; top: 8px; left: 8px; z-index: 1;
    background: rgba(18,32,43,.88); color: #fff;
    font-size: 12px; font-weight: 700; padding: 3px 7px; border-radius: 5px;
  }
  .card .disagree-tag {
    position: absolute; top: 8px; right: 8px; z-index: 1;
    background: #ca8a04; color: #fff;
    font-size: 10px; font-weight: 700; padding: 2px 6px; border-radius: 4px;
  }
  .card img { display: block; width: 200px; height: 112px; object-fit: cover; background: #111; }
  .card .nostill {
    width: 200px; height: 112px; display: flex; align-items: center; justify-content: center;
    color: #888; background: #1a1a1a; font-size: 12px;
  }
  .card .body {
    padding: 10px 12px;
    display: flex; flex-direction: column; justify-content: center; gap: 6px;
    border-left: 1px solid var(--line);
    min-width: 0;
  }
  .card .you-col {
    display: flex; flex-direction: column; align-items: stretch; justify-content: center;
    gap: 6px; padding: 8px;
    border-left: 1px solid var(--line);
    background: #eef3f6;
  }
  .choice {
    display: grid; grid-template-columns: 1fr 1fr; gap: 6px;
    width: 100%; height: 100%; min-height: 88px;
  }
  .pick {
    cursor: pointer; border: 2px solid #8aa0b0; border-radius: 8px;
    background: #fff; color: var(--muted);
    font: inherit; font-weight: 800; font-size: 14px; letter-spacing: .02em;
    text-transform: uppercase; padding: 8px 4px;
    display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 2px;
  }
  .pick .sub {
    display: block; font-size: 10px; font-weight: 700; letter-spacing: .04em;
    text-transform: uppercase; opacity: .7; margin-top: 1px;
  }
  .pick .ico { width: 18px; height: 18px; margin-bottom: 2px; }
  .pick.show.on {
    background: #ccfbf1; color: var(--show); border-color: #0f766e;
  }
  .pick.ad.on {
    background: #ffedd5; color: var(--ad); border-color: #c2410c;
  }
  .pick.prefill { border-style: dashed; }
  .pick.on.prefill { border-style: dashed; }
  .pick:hover { filter: brightness(0.98); }
  .choice-hint {
    font-size: 10px; font-weight: 700; color: var(--muted);
    text-align: center; text-transform: uppercase; letter-spacing: .04em;
  }
  .choice-hint.yours { color: #0f766e; }
  .action-bar {
    position: fixed; left: 0; right: 0; bottom: 0; z-index: 8;
    display: flex; align-items: center; justify-content: space-between; gap: 10px;
    padding: 10px 14px calc(10px + env(safe-area-inset-bottom, 0px));
    background: rgba(255,255,255,.96); border-top: 1px solid var(--line);
    backdrop-filter: blur(10px);
  }
  .action-bar .hint { margin: 0; font-size: 12px; color: var(--muted); line-height: 1.3; max-width: 55vw; }
  .action-bar .btn-next { min-width: 140px; padding: 12px 18px; font-size: 15px; }
  .signals {
    display: flex; flex-wrap: wrap; gap: 5px;
  }
  .sig {
    display: inline-flex; align-items: center; gap: 5px;
    border: 1px solid var(--line); border-radius: 7px;
    padding: 4px 7px; background: #f8fafc; min-width: 0;
  }
  .sig .lab {
    font-size: 10px; font-weight: 700; color: var(--muted);
    text-transform: uppercase; letter-spacing: .03em;
  }
  .ico {
    width: 14px; height: 14px; flex: 0 0 auto;
    display: inline-block; vertical-align: -2px;
  }
  .ico.lg { width: 18px; height: 18px; }
  .mark {
    display: inline-flex; align-items: center; gap: 5px;
    font-weight: 700; font-size: 12px;
    padding: 2px 7px; border-radius: 5px; line-height: 1.2;
  }
  .audit-key {
    display: flex; flex-wrap: wrap; gap: 6px; margin: 0 0 8px;
  }
  .audit-key .ak {
    display: inline-flex; align-items: center; gap: 5px;
    border: 1px solid var(--line); background: #fff; border-radius: 999px;
    padding: 4px 8px; font-size: 11px; font-weight: 700; color: var(--muted);
  }
  .audit-key .ak .hint { font-weight: 600; color: #8aa0b0; }
  .empty-box {
    color: var(--muted); padding: 28px 20px; text-align: center;
    display: grid; gap: 12px; justify-items: center;
  }
  .empty-box .audit-key { justify-content: center; margin: 0; }
  .mark.ad { background: #ffedd5; color: var(--ad); }
  .mark.show { background: #ccfbf1; color: var(--show); }
  .mark.mute { background: #fee2e2; color: var(--mute); }
  .mark.play { background: #dbeafe; color: var(--play); }
  .mark.unk { background: #e5e7eb; color: #4b5563; }
  .pbar {
    height: 5px; background: #e5e7eb; border-radius: 99px; overflow: hidden;
  }
  .pbar > span { display: block; height: 100%; background: var(--ad); }
  .pbar-lab {
    font-size: 10px; color: var(--muted); margin-top: 2px;
  }
  .listen {
    margin: 0 0 10px;
    background: #12202b;
    color: #e8eef2;
    border-radius: 8px;
    padding: 8px 10px;
  }
  .listen audio { width: 100%; height: 32px; margin: 0; }
  .listen .now {
    margin-top: 4px; font-size: 12px; font-weight: 700; color: #fef08a;
    font-variant-numeric: tabular-nums;
  }
  .card.playing {
    border-color: #1d4ed8;
    box-shadow: 0 0 0 2px #1d4ed8;
  }
  .card.cut-start { outline: 2px solid #1d4ed8; }
  .nav-verdict {
    margin-top: 6px; font-size: 11px; font-weight: 700; color: #0f766e;
  }
  .nav-verdict.pending { color: #9a3412; }
  .empty { color: var(--muted); padding: 40px; }
  .hdr-next { display: inline-flex; }
  @media (max-width: 960px) {
    header { flex-direction: column; gap: 6px; }
    header .right { width: 100%; justify-content: space-between; }
    .legend { max-width: none; display: none; }
    .hdr-next { display: none; }
    .layout { grid-template-columns: 1fr; padding-bottom: 84px; }
    nav {
      display: flex; gap: 8px; overflow-x: auto; border-right: 0;
      border-bottom: 1px solid var(--line); padding-bottom: 8px;
    }
    nav button { min-width: 180px; flex: 0 0 auto; }
    main { padding: 10px 10px 24px; }
    .strip-wrap { max-height: none; }
    .card {
      grid-template-columns: 1fr;
      max-width: none;
    }
    .card .thumb { order: 1; }
    .card img, .card .nostill { width: 100%; height: 180px; }
    .card .body { order: 2; border-left: 0; border-top: 1px solid var(--line); }
    .card .you-col {
      order: 3; border-left: 0; border-top: 1px solid var(--line);
      min-height: 0; padding: 10px;
    }
    .choice { min-height: 64px; }
    .pick { font-size: 15px; min-height: 56px; }
    .action-bar .hint { max-width: 42vw; font-size: 11px; }
    .action-bar .btn-next { min-width: 0; flex: 1; }
  }
</style>
<link rel="preconnect" href="https://fonts.googleapis.com"/>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;600;700&display=swap" rel="stylesheet"/>
</head>
<body>
<header>
  <div class="titles">
    <h1>Verdict</h1>
    <p class="sub" id="hdr">Loading…</p>
  </div>
  <div class="right">
    <div class="legend">
      <span><span class="swatch" style="background:#ffedd5"></span><b>Ad</b></span>
      <span><span class="swatch" style="background:#ccfbf1"></span><b>Show</b></span>
      <span><span class="swatch" style="background:#fee2e2"></span><b>Muted</b></span>
      <span><span class="swatch" style="background:#dbeafe"></span><b>Playing</b></span>
    </div>
    <a class="nav-link" id="linkDash" href="/dashboard">Desk</a>
    <button type="button" class="btn-next hdr-next" id="btnNextHdr" title="Save this stretch and go to the next one">Next →</button>
  </div>
</header>
<div class="layout">
  <nav id="nav"></nav>
  <main id="main"><div class="empty">Pick a stretch</div></main>
</div>
<div class="action-bar">
  <p class="hint" id="actionHint">Pick Show or Ad on each frame · Next saves and continues</p>
  <button type="button" class="btn-next" id="btnNext" title="Save this stretch and go to the next one">Next →</button>
</div>
<script>
/** When served under ohush.co/verdict (or any /verdict mount), prefix API paths. */
const BASE = (location.pathname === '/verdict' || location.pathname.startsWith('/verdict/'))
  ? '/verdict' : '';
function apiUrl(path) {
  if (!path) return BASE || '/';
  return BASE + (path.startsWith('/') ? path : '/' + path);
}
/** Tiny inline SVGs — same audit language as /dashboard. */
function ico(name, cls) {
  const c = cls ? ('ico ' + cls) : 'ico';
  const paths = {
    pic: '<rect x="3" y="5" width="14" height="11" rx="2"/><circle cx="12" cy="10.5" r="2.5"/><path d="M7 5l1.5-2h3L13 5"/>',
    txt: '<path d="M4 5h12v9H9l-3 3v-3H4z"/><path d="M7 8h6M7 11h4"/>',
    snd: '<path d="M3 10h2l3-3v10l-3-3H3z"/><path d="M12 8a4 4 0 010 8M14.5 6a7 7 0 010 12"/>',
    lock: '<rect x="5" y="9" width="10" height="8" rx="1.5"/><path d="M8 9V7a2 2 0 014 0v2"/>',
    show: '<circle cx="10" cy="10" r="6"/><path d="M7 10l2 2 4-4"/>',
    ad: '<path d="M5 5l10 10M15 5L5 15"/><rect x="3.5" y="3.5" width="13" height="13" rx="2"/>',
    next: '<path d="M5 10h9M10 6l4 4-4 4"/>',
    clock: '<circle cx="10" cy="10" r="7"/><path d="M10 6v4.5L13 12"/>',
  };
  const p = paths[name] || paths.pic;
  return `<svg class="${c}" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${p}</svg>`;
}
let DATA = null;
let selected = null;
let selectedFrame = 0;
let HUMAN = {}; // session -> { tKey: keep|mute }
let HUMAN_CUTS = {}; // epKey -> { cut_t }
let HUMAN_DONE = {}; // epKey -> { utc }

const TAG = {
  boundary_late: { pill: 'fix', title: 'Label cut is late', short: 'Fix the gold cut' },
  soft_gold_or_vision_ad: { pill: 'fix', title: 'Label may be soft', short: 'Check if this is really show' },
  true_acoustic_fp: { pill: 'muter', title: 'Live muter false mute', short: 'Model muted real show' },
  hangover: { pill: 'hang', title: 'Slow unmute', short: 'Stuck muted after ad' },
  mixed_review: { pill: 'review', title: 'Needs a look', short: 'Mixed signals' },
};
const DO = {
  fix_gold_boundary: 'Fix the human label cut',
  fix_gold_soft_ad: 'Relabel this as an ad',
  keep_as_muter_hard_negative: 'Keep as a muter training miss',
  controller_return_bug: 'Controller return lag (not a new ad)',
  human_review: 'Human review',
};
function epKey(session, t0, t1) {
  return `${session}|${Number(t0).toFixed(3)}|${Number(t1).toFixed(3)}`;
}
function currentEp() {
  if (!selected) return null;
  const [si, ei] = selected.split(':').map(Number);
  const s = DATA.sessions[si];
  const e = s.episodes[ei];
  return { s, e, key: epKey(s.session, e.t0, e.t1) };
}

function shortSession(s) {
  const m = String(s||'').match(/T(\d{4}Z)_(.+)$/);
  if (!m) return s;
  return m[2].replace(/_/g,' ') + ' · ' + m[1];
}
function look(v) {
  const x = String(v||'').toLowerCase();
  if (['ad','non_broadcast','paid_ad','show_promo','mute'].includes(x)) return {cls:'ad', text:'Ad'};
  if (['program','broadcast','play','program_sports','program_studio'].includes(x)) return {cls:'show', text:'Show'};
  if (!x || x === 'other' || x === 'empty' || x === 'mixed' || x === 'uncertain') return {cls:'unk', text:'Unclear'};
  return {cls:'unk', text:x};
}
function act(v) {
  if (v === 'cover') return {cls:'mute', text:'MUTED'};
  if (v === 'play') return {cls:'play', text:'PLAYING'};
  return {cls:'unk', text:'—'};
}
function gold(v) {
  const L = look(v);
  if (L.cls === 'ad') return {cls:'ad', text:'Gold: mute'};
  if (L.cls === 'show') return {cls:'show', text:'Gold: keep'};
  return {cls:'unk', text:'Gold: —'};
}
function humanLook(v, {prefill} = {}) {
  if (v === 'mute') return {cls:'ad', text:'Ad', value:'mute', prefill: !!prefill};
  if (v === 'keep') return {cls:'show', text:'Show', value:'keep', prefill: !!prefill};
  return {cls:'unk', text:'—', value:null, prefill: false};
}
function choiceHtml(i, hd) {
  const H = humanLook(hd.value, {prefill: hd.prefill});
  const keepOn = H.value === 'keep' ? 'on' : '';
  const muteOn = H.value === 'mute' ? 'on' : '';
  const pref = H.prefill ? 'prefill' : '';
  const hint = H.value
    ? (H.prefill ? 'suggested' : 'yours')
    : 'pick one';
  const hintCls = (!H.prefill && H.value) ? 'yours' : '';
  return `<div class="choice" data-choice-i="${i}">
    <button type="button" class="pick show ${keepOn} ${keepOn?pref:''}" data-pick="keep" data-i="${i}" title="Keep / show">
      ${ico('show')}<span>Show</span><span class="sub">keep</span>
    </button>
    <button type="button" class="pick ad ${muteOn} ${muteOn?pref:''}" data-pick="mute" data-i="${i}" title="Ad / mute · double-click = ad starts here">
      ${ico('ad')}<span>Ad</span><span class="sub">mute</span>
    </button>
  </div>
  <div class="choice-hint ${hintCls}">${hint}</div>`;
}
function goldAsHuman(gold) {
  const L = look(gold);
  if (L.cls === 'ad') return 'mute';
  if (L.cls === 'show') return 'keep';
  return null;
}
function humanAt(session, t) {
  const m = HUMAN[session] || {};
  for (const k of Object.keys(m)) {
    if (Math.abs(Number(k) - Number(t)) < 1e-6) return m[k];
  }
  return null;
}
/** Saved You mark, else gold prefill (what you see / flip). */
function humanDisplay(session, f) {
  const saved = humanAt(session, f.t) || f.human || null;
  if (saved) return { value: saved, prefill: false };
  const pre = goldAsHuman(f.gold);
  return { value: pre, prefill: !!pre };
}
function setHumanLocal(session, t, val) {
  if (!HUMAN[session]) HUMAN[session] = {};
  for (const k of Object.keys(HUMAN[session])) {
    if (Math.abs(Number(k) - Number(t)) < 1e-6) delete HUMAN[session][k];
  }
  if (val) HUMAN[session][String(Number(t))] = val;
}

function isDone(session, t0, t1, e) {
  const key = epKey(session, t0, t1);
  return !!(HUMAN_DONE[key] || e?.human_done);
}

function queueItems() {
  // Only the loaded chunk — keeps UI + server light
  const items = [];
  (DATA.sessions || []).forEach((s, si) => {
    (s.episodes || []).forEach((e, ei) => {
      if (e.in_chunk && !isDone(s.session, e.t0, e.t1, e)) {
        items.push({ si, ei, s, e, id: `${si}:${ei}` });
      }
    });
  });
  return items;
}

function renderNav() {
  const nav = document.getElementById('nav');
  const bits = [];
  let lastSess = null;
  const queue = queueItems();
  queue.forEach(({ si, ei, s, e, id }) => {
    if (s.session !== lastSess) {
      bits.push(`<div class="sess">${shortSession(s.session)}</div>`);
      lastSess = s.session;
    }
    const meta = TAG[e.tag] || TAG.mixed_review;
    const active = selected === id ? 'active' : '';
    const vk = epKey(s.session, e.t0, e.t1);
    const cut = HUMAN_CUTS[vk]?.cut_t ?? e.human_cut?.cut_t;
    const vline = cut != null
      ? `<div class="nav-verdict">Cut @ ${cut}s</div>`
      : `<div class="nav-verdict pending">In queue</div>`;
    bits.push(`<button class="${active}" data-id="${id}">
      <div class="pill ${meta.pill}">${meta.title}</div>
      <div class="nav-title">${Math.round(e.t0)}s → ${Math.round(e.t1)}s · ${Math.round(e.len_s)}s long</div>
      <div class="nav-meta">${meta.short} · ${e.n_frames || 0} frames</div>
      ${vline}
    </button>`);
  });
  nav.innerHTML = bits.join('') || '<div class="empty">Queue empty — all stretches done</div>';
  nav.querySelectorAll('button').forEach(btn => {
    btn.onclick = () => { selected = btn.dataset.id; selectedFrame = 0; renderNav(); renderMain(); };
  });
  updateNextButton();
}

function updateNextButton() {
  const cur = currentEp();
  const disabled = !cur || isDone(cur.s.session, cur.e.t0, cur.e.t1, cur.e);
  ['btnNext', 'btnNextHdr'].forEach(id => {
    const btn = document.getElementById(id);
    if (!btn) return;
    btn.disabled = disabled;
    btn.innerHTML = `${ico('next')} Next`;
  });
  const hint = document.getElementById('actionHint');
  if (hint) {
    if (!cur) hint.textContent = 'Queue empty';
    else hint.innerHTML = `${ico('pic')} ${ico('txt')} ${ico('snd')} ${ico('lock')} &nbsp; Show or Ad · dashed = suggested`;
  }
}

function auditKeyHtml() {
  return `<div class="audit-key" aria-label="Audit channels">
    <span class="ak">${ico('pic')} Pictures <span class="hint">vision</span></span>
    <span class="ak">${ico('txt')} Transcript <span class="hint">ASR</span></span>
    <span class="ak">${ico('snd')} Sound <span class="hint">muter</span></span>
    <span class="ak">${ico('lock')} Auto-lock <span class="hint">≥2 agree</span></span>
  </div>`;
}
function sigChip(kind, label, L) {
  return `<div class="sig" title="${label}">
    ${ico(kind)}<span class="lab">${label}</span><span class="mark ${L.cls}">${L.text}</span>
  </div>`;
}
function renderMain() {
  const main = document.getElementById('main');
  if (!selected) {
    main.innerHTML = `<div class="empty-box">
      <div>Nothing in the queue — all stretches finished</div>
      ${auditKeyHtml()}
      <div style="font-size:12px;max-width:42ch;line-height:1.4">When a stretch lands, each frame shows these four audits side by side so you can scan agreement at a glance.</div>
    </div>`;
    updateNextButton();
    return;
  }
  const [si, ei] = selected.split(':').map(Number);
  const s = DATA.sessions[si];
  const e = s.episodes[ei];
  const frames = e.frames || [];
  const meta = TAG[e.tag] || TAG.mixed_review;
  const doText = DO[e.action?.do] || e.action?.do || 'Review';
  const cutT = e.human_cut?.cut_t;
  const cards = frames.map((f, i) => {
    const img = f.still_url
      ? `<img src="${apiUrl(f.still_url)}" alt="${f.t}s" loading="lazy"/>`
      : `<div class="nostill">No still</div>`;
    const V = look(f.vision_class || f.vision_bucket);
    const A = look(f.asr_lex);
    const M = act(f.action);
    const G = gold(f.gold);
    const hd = humanDisplay(s.session, f);
    const pct = Math.max(0, Math.min(100, Math.round(100 * (f.p || 0))));
    const isCut = cutT != null && Math.abs(Number(f.t) - Number(cutT)) < 1e-6;
    return `<div class="card ${f.disagreement ? 'clash' : ''} ${i===selectedFrame?'selected':''} ${isCut?'cut-start':''}" data-i="${i}">
      <div class="thumb">
        <div class="time">${f.t}s</div>
        ${f.disagreement ? '<div class="disagree-tag">disagree</div>' : ''}
        ${img}
      </div>
      <div class="body">
        <div class="signals">
          ${sigChip('pic', 'Pictures', V)}
          ${sigChip('txt', 'Transcript', A)}
          ${sigChip('snd', 'Sound', M)}
          ${sigChip('lock', 'Auto-lock', {cls: G.cls, text: G.text.replace('Gold: ','')})}
        </div>
        <div>
          <div class="pbar" title="Sound / muter ad confidence ${pct}%"><span style="width:${pct}%"></span></div>
          <div class="pbar-lab">${ico('snd')} Sound score ${pct}%</div>
        </div>
      </div>
      <div class="you-col">
        ${choiceHtml(i, hd)}
      </div>
    </div>`;
  }).join('');

  // pad=0 so audio t=0 is exactly episode t0 (frames line up 1:1)
  const pad = 0;
  const audioUrl = apiUrl(`/audio?session=${encodeURIComponent(s.session)}&t0=${e.t0}&t1=${e.t1}&pad=${pad}`);
  main.innerHTML = `
    <div class="pill ${meta.pill}">${meta.title}</div>
    <h2 class="hero-title">${Math.round(e.t0)}s → ${Math.round(e.t1)}s</h2>
    <div class="meta-bar">
      <span>Take <b>${shortSession(s.session)}</b></span>
      <span>Length <b>${Math.round(e.len_s)}s</b></span>
      <span>Frames <b>${frames.length}</b></span>
      <span>Patch <b>${e.action?.patch_id || 'none'}</b></span>
    </div>
    ${auditKeyHtml()}
    <p class="hero-do"><b>Suggested:</b> ${doText}. ${e.action?.detail || ''}</p>
    <div class="listen">
      <audio id="epAudio" controls preload="auto" src="${audioUrl}"></audio>
      <div class="now" id="audioNow">${ico('clock')} Take clock: ${Number(e.t0).toFixed(1)}s</div>
    </div>
    <div class="strip-wrap">
      <div class="strip-head">
        <p class="strip-label">${cutT != null ? (ico('ad') + ' Your cut @ ' + cutT + 's') : (ico('show') + ' / ' + ico('ad') + ' Choose · dashed = suggested · double-tap Ad = cut')}</p>
        <button type="button" class="strip-clear" id="btnClearHuman" title="Clear your marks on this stretch">Clear</button>
      </div>
      <div class="strip" id="strip">${cards}</div>
    </div>
  `;
  updateNextButton();
  const audio = document.getElementById('epAudio');
  const nowEl = document.getElementById('audioNow');
  let syncFromAudio = false;

  function frameIndexForTakeTime(takeT) {
    if (!frames.length) return 0;
    let best = 0;
    let bestDist = Infinity;
    for (let i = 0; i < frames.length; i++) {
      const d = Math.abs(Number(frames[i].t) - takeT);
      if (d < bestDist) { bestDist = d; best = i; }
    }
    return best;
  }

  function selectFrame(i, {seek, autoplay, scroll} = {}) {
    if (!frames.length) return;
    i = Math.max(0, Math.min(frames.length - 1, i));
    selectedFrame = i;
    main.querySelectorAll('.card').forEach(c => {
      const on = Number(c.dataset.i) === selectedFrame;
      c.classList.toggle('selected', on);
      c.classList.toggle('playing', on);
    });
    if (scroll) {
      const el = main.querySelector(`.card[data-i="${selectedFrame}"]`);
      const strip = document.getElementById('strip');
      if (el && strip) {
        const er = el.getBoundingClientRect();
        const sr = strip.getBoundingClientRect();
        if (er.top < sr.top || er.bottom > sr.bottom) {
          el.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
        }
      }
    }
    if (seek && audio && !syncFromAudio) {
      const rel = Math.max(0, Number(frames[i].t) - Number(e.t0) + pad);
      try { audio.currentTime = rel; } catch (_) {}
      if (autoplay) audio.play().catch(() => {});
    }
    if (nowEl && frames[selectedFrame]) {
      const takeT = Number(frames[selectedFrame].t);
      nowEl.textContent = `Take clock: ${takeT.toFixed(1)}s · frame ${selectedFrame + 1}/${frames.length}`;
    }
  }

  function syncFramesFromAudio() {
    if (!audio || !frames.length) return;
    const takeT = Number(e.t0) - pad + audio.currentTime;
    if (nowEl) nowEl.textContent = `Take clock: ${takeT.toFixed(1)}s`;
    const i = frameIndexForTakeTime(takeT);
    if (i === selectedFrame) {
      main.querySelectorAll('.card').forEach(c => {
        const on = Number(c.dataset.i) === selectedFrame;
        c.classList.toggle('selected', on);
        c.classList.toggle('playing', on);
      });
      return;
    }
    // Only auto-scroll while audio is playing — never jump the list on You flips/seeks
    const shouldScroll = !audio.paused;
    syncFromAudio = true;
    selectFrame(i, {seek: false, scroll: shouldScroll});
    syncFromAudio = false;
  }

  if (audio) {
    audio.addEventListener('timeupdate', syncFramesFromAudio);
    audio.addEventListener('seeked', syncFramesFromAudio);
    audio.addEventListener('play', syncFramesFromAudio);
  }
  const clearBtn = document.getElementById('btnClearHuman');
  if (clearBtn) clearBtn.onclick = () => clearHumanStretch();
  main.querySelectorAll('.card').forEach(card => {
    card.onclick = (ev) => {
      if (ev.target && ev.target.closest && ev.target.closest('[data-pick]')) return;
      selectFrame(Number(card.dataset.i), {seek: true, autoplay: false, scroll: false});
    };
  });
  let pickClickTimer = null;
  main.querySelectorAll('[data-pick]').forEach(btn => {
    btn.onclick = (ev) => {
      ev.stopPropagation();
      const i = Number(btn.dataset.i);
      const val = btn.dataset.pick;
      selectFrame(i, {seek: false, autoplay: false, scroll: false});
      if (pickClickTimer) clearTimeout(pickClickTimer);
      pickClickTimer = setTimeout(() => {
        pickClickTimer = null;
        setHumanChoice(i, val);
      }, 180);
    };
    btn.ondblclick = (ev) => {
      ev.stopPropagation();
      ev.preventDefault();
      if (pickClickTimer) { clearTimeout(pickClickTimer); pickClickTimer = null; }
      const i = Number(btn.dataset.i);
      const val = btn.dataset.pick;
      selectFrame(i, {seek: false, autoplay: false, scroll: false});
      // Ad double-click = cut starts here; Show just selects Show
      setHumanChoice(i, val).then(() => {
        if (val === 'mute') saveCutFromSelected();
      });
    };
  });
  selectFrame(selectedFrame || 0, {seek: false, scroll: false});
}

function paintChoices(session, frames) {
  frames.forEach((f, i) => {
    const col = document.querySelector(`.card[data-i="${i}"] .you-col`);
    if (!col) return;
    col.innerHTML = choiceHtml(i, humanDisplay(session, f));
    col.querySelectorAll('[data-pick]').forEach(btn => {
      btn.onclick = (ev) => {
        ev.stopPropagation();
        setHumanChoice(Number(btn.dataset.i), btn.dataset.pick);
      };
      btn.ondblclick = (ev) => {
        ev.stopPropagation();
        ev.preventDefault();
        const i2 = Number(btn.dataset.i);
        const val = btn.dataset.pick;
        setHumanChoice(i2, val).then(() => {
          if (val === 'mute') saveCutFromSelected();
        });
      };
    });
  });
}

async function setHumanChoice(i, next) {
  const cur = currentEp();
  if (!cur) return;
  const f = cur.e.frames[i];
  if (!f || (next !== 'keep' && next !== 'mute')) return;
  setHumanLocal(cur.s.session, f.t, next);
  f.human = next;
  paintChoices(cur.s.session, cur.e.frames);
  try {
    await fetch(apiUrl('/api/human_frames'), {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        session: cur.s.session,
        marks: { [String(f.t)]: next },
      }),
    });
  } catch (_) {}
}

function stripStatus(text) {
  const el = document.querySelector('.strip-label');
  if (el) el.textContent = text;
}

async function saveCutFromSelected() {
  const cur = currentEp();
  if (!cur) return;
  const f = cur.e.frames[selectedFrame];
  if (!f) return;
  stripStatus('Saving cut…');
  const times = cur.e.frames.map(x => x.t);
  try {
    const res = await fetch(apiUrl('/api/human_frames'), {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        session: cur.s.session,
        cut_t: f.t,
        stretch_times: times,
        t0: cur.e.t0,
        t1: cur.e.t1,
      }),
    });
    const body = await res.json();
    if (!res.ok || !body.ok) throw new Error(body.error || 'save failed');
    HUMAN[cur.s.session] = body.marks || {};
    cur.e.frames.forEach(fr => { fr.human = humanAt(cur.s.session, fr.t); });
    cur.e.human_cut = { cut_t: f.t };
    HUMAN_CUTS[cur.key] = { cut_t: f.t };
    paintChoices(cur.s.session, cur.e.frames);
    document.querySelectorAll('.card').forEach(c => {
      const idx = Number(c.dataset.i);
      const fr = cur.e.frames[idx];
      c.classList.toggle('cut-start', fr && Math.abs(Number(fr.t) - Number(f.t)) < 1e-6);
    });
    stripStatus('Your cut @ ' + f.t + 's');
    renderNav();
  } catch (err) {
    stripStatus('Cut save failed: ' + err.message);
  }
}

async function clearHumanStretch() {
  const cur = currentEp();
  if (!cur) return;
  const times = cur.e.frames.map(x => x.t);
  try {
    const res = await fetch(apiUrl('/api/human_frames'), {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        session: cur.s.session,
        clear_times: times,
        clear_cut: true,
        t0: cur.e.t0,
        t1: cur.e.t1,
      }),
    });
    const body = await res.json();
    if (!res.ok || !body.ok) throw new Error(body.error || 'clear failed');
    HUMAN[cur.s.session] = body.marks || {};
    cur.e.frames.forEach(fr => { fr.human = null; });
    cur.e.human_cut = null;
    delete HUMAN_CUTS[cur.key];
    paintChoices(cur.s.session, cur.e.frames);
    document.querySelectorAll('.card').forEach(c => c.classList.remove('cut-start'));
    stripStatus('Choose Show or Ad · dashed = suggested · double-tap Ad = cut starts here');
    renderNav();
  } catch (err) {
    stripStatus('Clear failed: ' + err.message);
  }
}

function selectNextInQueue() {
  const q = queueItems();
  if (!q.length) { selected = null; return; }
  // prefer first item after current, else first
  let idx = q.findIndex(x => x.id === selected);
  if (idx >= 0 && idx + 1 < q.length) selected = q[idx + 1].id;
  else selected = q[0].id;
  selectedFrame = 0;
}

const CHUNK_SIZE = 4;

function updateHdr() {
  const c = DATA.chunk || {};
  const nLeft = queueItems().length;
  const pending = c.pending_total != null ? c.pending_total : nLeft;
  const nDone = c.done_total != null ? c.done_total : Object.keys(HUMAN_DONE).length;
  const total = c.episode_total != null ? c.episode_total : 0;
  document.getElementById('hdr').textContent =
    `${nLeft} here · ${pending} left · ${nDone}/${total} finished · choices autosave`;
}

async function loadChunk() {
  const res = await fetch(apiUrl('/api/triage?chunk_size=' + CHUNK_SIZE));
  DATA = await res.json();
  HUMAN = DATA.human_frames || {};
  HUMAN_CUTS = DATA.human_cuts || {};
  HUMAN_DONE = DATA.human_done || {};
  updateHdr();
  const q = queueItems();
  const boundary = q.find(x => x.e.tag === 'boundary_late');
  selected = (boundary || q[0] || {}).id || null;
  selectedFrame = 0;
  renderNav();
  renderMain();
  return q.length;
}

async function markStretchDone() {
  const cur = currentEp();
  if (!cur || isDone(cur.s.session, cur.e.t0, cur.e.t1, cur.e)) return;
  ['btnNext', 'btnNextHdr'].forEach(id => {
    const btn = document.getElementById(id);
    if (btn) { btn.disabled = true; btn.textContent = 'Saving…'; }
  });
  // Materialize choices (incl. gold prefill) so your pick is the saved truth
  const marks = {};
  (cur.e.frames || []).forEach(f => {
    const hd = humanDisplay(cur.s.session, f);
    if (hd.value) marks[String(f.t)] = hd.value;
  });
  try {
    const res = await fetch(apiUrl('/api/human_frames'), {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        session: cur.s.session,
        t0: cur.e.t0,
        t1: cur.e.t1,
        marks,
        done: true,
      }),
    });
    const body = await res.json();
    if (!res.ok || !body.ok) throw new Error(body.error || 'next failed');
    HUMAN[cur.s.session] = body.marks || HUMAN[cur.s.session] || {};
    if (body.done_map) HUMAN_DONE = body.done_map;
    else HUMAN_DONE[cur.key] = body.done || { utc: new Date().toISOString() };
    cur.e.human_done = HUMAN_DONE[cur.key];
    cur.e.in_chunk = false;
    cur.e.frames.forEach(fr => { fr.human = humanAt(cur.s.session, fr.t); });
    if (!queueItems().length) {
      await loadChunk();
      return;
    }
    selectNextInQueue();
    if (DATA.chunk) {
      DATA.chunk.pending_total = Math.max(0, (DATA.chunk.pending_total || 1) - 1);
      DATA.chunk.done_total = (DATA.chunk.done_total || 0) + 1;
    }
    updateHdr();
    renderNav();
    renderMain();
  } catch (err) {
    updateNextButton();
    alert('Next failed: ' + err.message);
  }
}

async function boot() {
  const goNext = () => markStretchDone();
  const n1 = document.getElementById('btnNext');
  const n2 = document.getElementById('btnNextHdr');
  if (n1) n1.onclick = goNext;
  if (n2) n2.onclick = goNext;
  const dash = document.getElementById('linkDash');
  if (dash) dash.href = apiUrl('/dashboard');
  await loadChunk();
}
boot();
</script>
</body>
</html>
"""


DASHBOARD_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Label desk</title>
<style>
  :root {
    --bg: #e8eef2;
    --ink: #14212b;
    --muted: #5a6b78;
    --line: #c9d5de;
    --ok: #0f766e;
    --warn: #b45309;
    --run: #0369a1;
    --card: #fff;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
    background: var(--bg);
    color: var(--ink);
  }
  header {
    display: flex; justify-content: space-between; align-items: flex-start;
    gap: 12px; padding: 12px 14px; border-bottom: 1px solid var(--line);
    background: rgba(255,255,255,.92); position: sticky; top: 0; z-index: 2;
    backdrop-filter: blur(8px);
  }
  h1 { margin: 0; font-size: 15px; letter-spacing: -.01em; }
  .sub { margin: 3px 0 0; color: var(--muted); font-size: 12px; line-height: 1.35; }
  a.nav {
    flex: 0 0 auto; text-decoration: none; border: 1px solid var(--line); background: #fff;
    color: var(--ink); border-radius: 8px; padding: 8px 10px; font-weight: 700; font-size: 12px;
  }
  main {
    max-width: 920px; margin: 0 auto; padding: 12px 14px 28px;
    display: grid; gap: 10px;
  }
  .hero {
    background: var(--card); border: 1px solid var(--line); border-radius: 12px;
    padding: 14px; display: grid; gap: 10px;
  }
  .hero.live { border-color: #5eead4; box-shadow: 0 0 0 1px rgba(15,118,110,.12); }
  .hero-top { display: flex; justify-content: space-between; gap: 10px; align-items: baseline; flex-wrap: wrap; }
  .kicker { margin: 0; font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: .05em; color: var(--muted); }
  .hero h2 { margin: 0; font-size: clamp(18px, 4.2vw, 24px); line-height: 1.2; font-variant-numeric: tabular-nums; }
  .eta-big { font-size: clamp(22px, 5vw, 28px); font-weight: 700; font-variant-numeric: tabular-nums; color: var(--run); }
  .meta { margin: 0; color: var(--muted); font-size: 12px; line-height: 1.4; }
  .bar { height: 10px; background: #eef3f6; border-radius: 999px; overflow: hidden; }
  .bar > i { display: block; height: 100%; width: 0; background: var(--ok); border-radius: 999px; }
  .glance {
    display: grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap: 8px;
  }
  .stat {
    background: var(--card); border: 1px solid var(--line); border-radius: 10px; padding: 10px 12px;
  }
  .stat .k {
    color: var(--muted); font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: .04em;
    display: inline-flex; align-items: center; gap: 5px;
  }
  .stat .v { margin-top: 2px; font-size: 20px; font-weight: 700; font-variant-numeric: tabular-nums; }
  .stat .h { margin-top: 2px; color: var(--muted); font-size: 12px; }
  .ico {
    width: 14px; height: 14px; flex: 0 0 auto; display: inline-block; vertical-align: -2px;
  }
  .ico.lg { width: 18px; height: 18px; }
  .audit-legend {
    display: flex; flex-wrap: wrap; gap: 6px;
  }
  .audit-legend .ak {
    display: inline-flex; align-items: center; gap: 5px;
    background: var(--card); border: 1px solid var(--line); border-radius: 999px;
    padding: 5px 9px; font-size: 11px; font-weight: 700; color: var(--muted);
  }
  .audit-legend .ak .hint { font-weight: 600; color: #8aa0b0; }
  .audit-legend .ak.on { background: #ccfbf1; color: var(--ok); border-color: #99f6e4; }
  .audit-legend .ak.go { background: #e0f2fe; color: var(--run); border-color: #7dd3fc; }
  .hero-phase {
    display: inline-flex; align-items: center; gap: 8px;
  }
  .hero-phase .ico { width: 22px; height: 22px; color: var(--run); }
  .chips { display: flex; flex-wrap: wrap; gap: 6px; }
  .chip {
    display: inline-flex; align-items: center; gap: 6px;
    background: var(--card); border: 1px solid var(--line); border-radius: 999px;
    padding: 6px 10px; font-size: 12px; font-weight: 600;
  }
  .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--muted); }
  .dot.on { background: var(--ok); }
  .dot.off { background: var(--warn); }
  .dot.run { background: var(--run); }
  .dot.warn { background: var(--warn); }
  .panel {
    background: var(--card); border: 1px solid var(--line); border-radius: 12px; padding: 12px 14px;
  }
  .panel h3 { margin: 0 0 8px; font-size: 13px; }
  .story { margin: 0 0 8px; font-size: 13px; line-height: 1.4; }
  .split {
    display: grid; grid-template-columns: 1fr; gap: 8px;
  }
  .queue { display: grid; gap: 0; }
  .qrow {
    display: grid; grid-template-columns: 1fr auto; gap: 8px 12px;
    padding: 10px 0; border-top: 1px solid #eef3f6; align-items: start;
  }
  .qrow:first-child { border-top: 0; }
  .qrow.run { background: linear-gradient(90deg, #f0f9ff, transparent); margin: 0 -6px; padding-left: 6px; padding-right: 6px; border-radius: 8px; }
  .name { font-weight: 700; font-size: 13px; font-variant-numeric: tabular-nums; }
  .marks { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 4px; }
  .mark {
    font-size: 10px; font-weight: 700; padding: 3px 7px; border-radius: 4px;
    border: 1px solid var(--line); color: var(--muted); background: #fff;
    display: inline-flex; align-items: center; gap: 4px;
  }
  .mark .ico { width: 12px; height: 12px; }
  .mark.on { background: #ccfbf1; color: var(--ok); border-color: #99f6e4; }
  .mark.go { background: #e0f2fe; color: var(--run); border-color: #7dd3fc; }
  .mark.off { background: #fff7ed; color: var(--warn); border-color: #fed7aa; }
  .right { text-align: right; }
  .pill { display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 11px; font-weight: 700; }
  .pill.ok { background: #ccfbf1; color: var(--ok); }
  .pill.warn { background: #ffedd5; color: var(--warn); }
  .pill.run { background: #e0f2fe; color: var(--run); }
  details.more {
    background: var(--card); border: 1px solid var(--line); border-radius: 12px; padding: 10px 14px;
  }
  details.more > summary {
    cursor: pointer; font-weight: 700; font-size: 13px; list-style: none;
  }
  details.more > summary::-webkit-details-marker { display: none; }
  details.more[open] > summary { margin-bottom: 8px; }
  .more-body { display: grid; gap: 10px; color: var(--muted); font-size: 12px; }
  .kv { display: grid; grid-template-columns: 1fr auto; gap: 4px 12px; }
  .kv span:nth-child(odd) { color: var(--muted); }
  .kv span:nth-child(even) { font-weight: 700; color: var(--ink); font-variant-numeric: tabular-nums; text-align: right; }
  pre {
    margin: 0; background: #f7fafc; border: 1px solid var(--line); border-radius: 8px;
    padding: 10px; overflow: auto; font-size: 11px; line-height: 1.35; max-height: 160px;
  }
  .foot { margin: 6px 0 0; font-size: 11px; color: var(--muted); }
  @media (min-width: 720px) {
    .glance { grid-template-columns: repeat(4, minmax(0,1fr)); }
    .split { grid-template-columns: 1.2fr .8fr; }
    .hero { grid-template-columns: 1.4fr .8fr; align-items: center; }
    .hero-main { grid-column: 1; }
    .hero-eta { grid-column: 2; text-align: right; }
    .bar { grid-column: 1 / -1; }
    .meta { grid-column: 1 / -1; }
  }
  @media (max-width: 419px) {
    .stat .v { font-size: 18px; }
    .qrow { grid-template-columns: 1fr; }
    .right { text-align: left; }
  }
</style>
<link rel="preconnect" href="https://fonts.googleapis.com"/>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;600;700&display=swap" rel="stylesheet"/>
</head>
<body>
<header>
  <div>
    <h1>Label desk</h1>
    <p class="sub" id="sub">Loading…</p>
  </div>
  <a class="nav" id="linkTriage" href="/">Triage</a>
</header>
<main>
  <section class="hero idle" id="hero">
    <div class="hero-main">
      <p class="kicker" id="liveKicker">Now</p>
      <h2 id="liveBig">Checking…</h2>
    </div>
    <div class="hero-eta">
      <p class="kicker">This tape left</p>
      <div class="eta-big" id="liveEta">—</div>
      <p class="meta" id="liveEtaSub"></p>
    </div>
    <div class="bar"><i id="liveBar"></i></div>
    <p class="meta" id="liveMeta"></p>
  </section>

  <section class="glance" id="glance"></section>

  <section class="audit-legend" id="auditLegend" aria-label="Audit channels"></section>

  <section class="chips" id="statusChips"></section>

  <section class="panel">
    <h3>Backlog</h3>
    <p class="story" id="funnelPlain">Loading…</p>
    <div class="bar"><i id="funnelBar"></i></div>
    <p class="foot" id="funnelFoot"></p>
  </section>

  <section class="panel">
    <h3>Up next</h3>
    <div class="queue" id="queue"></div>
    <p class="foot" id="queueFoot"></p>
  </section>

  <details class="more">
    <summary>More detail</summary>
    <div class="more-body">
      <div>
        <strong style="color:var(--ink)">ETAs &amp; timing</strong>
        <div class="kv" id="timeKv" style="margin-top:6px"></div>
      </div>
      <div>
        <strong style="color:var(--ink)">If nothing locks overnight</strong>
        <ol style="margin:6px 0 0; padding-left:18px">
          <li><code>live_audio_lock</code> — still writing WAV past 02:00</li>
          <li><code>label_pass_busy</code> — worker already running</li>
          <li><code>ollama_down</code> — start Ollama / qwen2.5vl:7b</li>
          <li><code>ram_pressure</code> — free RAM under label floor</li>
        </ol>
      </div>
      <div>
        <strong style="color:var(--ink)">Last tick</strong>
        <pre id="last" style="margin-top:6px">null</pre>
      </div>
    </div>
  </details>
</main>
<script>
const BASE = (location.pathname === '/verdict/dashboard' || location.pathname.startsWith('/verdict/'))
  ? '/verdict' : '';
function apiUrl(path) {
  return BASE + (path.startsWith('/') ? path : '/' + path);
}
function ico(name, cls) {
  const c = cls ? ('ico ' + cls) : 'ico';
  const paths = {
    pic: '<rect x="3" y="5" width="14" height="11" rx="2"/><circle cx="12" cy="10.5" r="2.5"/><path d="M7 5l1.5-2h3L13 5"/>',
    txt: '<path d="M4 5h12v9H9l-3 3v-3H4z"/><path d="M7 8h6M7 11h4"/>',
    snd: '<path d="M3 10h2l3-3v10l-3-3H3z"/><path d="M12 8a4 4 0 010 8M14.5 6a7 7 0 010 12"/>',
    lock: '<rect x="5" y="9" width="10" height="8" rx="1.5"/><path d="M8 9V7a2 2 0 014 0v2"/>',
    show: '<circle cx="10" cy="10" r="6"/><path d="M7 10l2 2 4-4"/>',
    ad: '<path d="M5 5l10 10M15 5L5 15"/><rect x="3.5" y="3.5" width="13" height="13" rx="2"/>',
    clock: '<circle cx="10" cy="10" r="7"/><path d="M10 6v4.5L13 12"/>',
    wait: '<circle cx="10" cy="10" r="7"/><path d="M7 10h6"/>',
    run: '<path d="M7 5l9 5-9 5z"/>',
    cap: '<circle cx="10" cy="10" r="4"/><circle cx="10" cy="10" r="7"/>',
    stack: '<path d="M4 7h12v9H4z"/><path d="M7 4h12v9"/>',
  };
  const p = paths[name] || paths.pic;
  return `<svg class="${c}" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${p}</svg>`;
}
function pill(text, kind) {
  return `<span class="pill ${kind||'ok'}">${text}</span>`;
}
function fmt(n) {
  if (n == null || n === '') return '—';
  return String(n);
}
function shortSess(s) {
  return String(s || '').replace(/^20\\d{2}/, '');
}
function fmtDur(sec) {
  if (sec == null || sec === '') return '—';
  const n = Number(sec);
  if (!Number.isFinite(n)) return '—';
  if (n < 60) return Math.round(n) + 's';
  if (n < 3600) return (n/60).toFixed(n < 600 ? 1 : 0) + 'm';
  return (n/3600).toFixed(1) + 'h';
}
function phaseName(p) {
  return ({vision:'pictures', asr:'transcript', acoustic:'sound', combine:'merge', consensus:'auto-lock'})[p] || p || 'job';
}
function phaseIco(p) {
  return ({vision:'pic', asr:'txt', acoustic:'snd', combine:'stack', consensus:'lock'})[p] || 'run';
}
function mark(kind, on, go) {
  const cls = go ? 'mark go' : (on ? 'mark on' : 'mark off');
  const label = ({pic:'Pictures', txt:'Transcript', snd:'Sound', lock:'Auto-lock'})[kind] || kind;
  return `<span class="${cls}" title="${label}">${ico(kind)}${label}</span>`;
}
async function refresh() {
  const res = await fetch(apiUrl('/api/overnight'), { cache: 'no-store' });
  if (!res.ok) throw new Error('status ' + res.status);
  const d = await res.json();
  const o = d.overnight || {};
  const pause = d.capture_pause || {};
  const capture = d.capture || {};
  const lock = d.label_lock || {};
  const sched = d.schedule || {};
  const q = d.verdict_queue || {};
  const live = d.live_job || {};
  const h = d.hierarchy || {};
  const funnel = h.funnel || {};
  const etas = d.etas || {};
  const cur = etas.current_session || {};
  const totEta = etas.total || {};
  const pri = etas.priority || {};
  const win = etas.window || {};
  const lt = d.label_timing || {};
  const tot = lt.totals || {};

  document.getElementById('sub').textContent =
    `${d.updated_utc || '—'} · ${o.day_et || ''} ET · refreshes every 5s`;

  const active = !!live.active;
  const hero = document.getElementById('hero');
  hero.className = active ? 'hero live' : 'hero';
  const phase = phaseName(live.phase);
  const livePhase = String(live.phase || '');
  if (active) {
    document.getElementById('liveKicker').textContent = 'Working now';
    document.getElementById('liveBig').innerHTML =
      `<span class="hero-phase">${ico(phaseIco(live.phase), 'lg')}<span>${phase} · ${shortSess(live.session)} · ${fmt(live.hop_i)}/${fmt(live.hop_of)}</span></span>`;
    document.getElementById('liveBar').style.width = Math.max(0, Math.min(100, Number(live.pct) || 0)) + '%';
    document.getElementById('liveEta').textContent = fmtDur(live.eta_remaining_s ?? cur.remaining_s);
    document.getElementById('liveEtaSub').textContent = live.eta_finish_et || cur.finish_et
      ? ('done ~' + (live.eta_finish_et || cur.finish_et))
      : '';
    const bits = [
      live.pct != null ? (fmt(live.pct) + '%') : null,
      live.step_elapsed_s != null ? ('elapsed ' + fmtDur(live.step_elapsed_s) + (live.step_elapsed_approx ? '≈' : '')) : null,
      live.hops_per_min != null ? (fmt(live.hops_per_min) + '/min') : null,
      live.model || null,
    ].filter(Boolean);
    document.getElementById('liveMeta').textContent = bits.join(' · ');
  } else {
    document.getElementById('liveKicker').textContent = 'Idle';
    document.getElementById('liveBig').innerHTML =
      `<span class="hero-phase">${ico('wait', 'lg')}<span>${live.note || 'Waiting for next tape'}</span></span>`;
    document.getElementById('liveBar').style.width = '0%';
    document.getElementById('liveEta').textContent = fmtDur(pri.remaining_s);
    document.getElementById('liveEtaSub').textContent = 'help-pile left';
    document.getElementById('liveMeta').textContent = live.updated_utc || '';
  }

  document.getElementById('glance').innerHTML = `
    <div class="stat"><div class="k">${ico('lock')} Finished</div><div class="v">${fmt(funnel.finished)}<span style="font-size:13px;color:var(--muted);font-weight:600">/${fmt(funnel.prepared)}</span></div><div class="h">${fmt(funnel.pct_finished)}%</div></div>
    <div class="stat"><div class="k">${ico('pic')} Waiting</div><div class="v">${fmt(funnel.waiting_for_pictures)}</div><div class="h">pictures first</div></div>
    <div class="stat"><div class="k">${ico('show')} Help pile</div><div class="v">${fmtDur(pri.remaining_s)}</div><div class="h">${pri.finish_et ? ('~' + pri.finish_et) : (fmt(o.help_asks_now) + ' clips')}</div></div>
    <div class="stat"><div class="k">${ico('clock')} All left</div><div class="v">${fmtDur(totEta.remaining_s)}</div><div class="h">${fmt(win.overnights_needed)} overnights</div></div>
  `;

  const picGo = active && livePhase === 'vision';
  const txtGo = active && livePhase === 'vision';
  const sndGo = active && livePhase === 'acoustic';
  const lockGo = active && (livePhase === 'consensus' || livePhase === 'combine');
  document.getElementById('auditLegend').innerHTML = `
    <span class="ak ${picGo?'go':''}">${ico('pic')} Pictures <span class="hint">vision</span></span>
    <span class="ak ${txtGo?'go':''}">${ico('txt')} Transcript <span class="hint">ASR</span></span>
    <span class="ak ${sndGo?'go':''}">${ico('snd')} Sound <span class="hint">muter</span></span>
    <span class="ak ${lockGo?'go':''}">${ico('lock')} Auto-lock <span class="hint">≥2 agree</span></span>
  `;

  const ownerCap = String(capture.owner_capture || (pause.active ? 'off' : 'on'));
  const chips = [];
  chips.push(`<span class="chip">${ico('cap')}<span class="dot ${ownerCap==='on'?'on':'off'}"></span>Capture ${ownerCap}</span>`);
  (capture.players || []).forEach(p => {
    const on = String(p.capture||'') === 'on';
    chips.push(`<span class="chip">${ico('cap')}<span class="dot ${on?'on':'off'}"></span>${p.id || p.engine} ${on?'on':'off'}</span>`);
  });
  chips.push(`<span class="chip">${ico(lock.held?'run':'wait')}<span class="dot ${lock.held?'run':'off'}"></span>Label ${lock.held?'running':'idle'}</span>`);
  chips.push(`<span class="chip">${ico('clock')}<span class="dot"></span>${sched.mode || 'schedule'}</span>`);
  if (q.pending_approx != null) chips.push(`<span class="chip">${ico('ad')}<span class="dot ${q.pending_approx?'warn':'on'}"></span>Disagree ${fmt(q.pending_approx)}</span>`);
  document.getElementById('statusChips').innerHTML = chips.join('');

  document.getElementById('funnelPlain').innerHTML =
    `${ico('stack')} ${funnel.plain || '—'}`;
  document.getElementById('funnelBar').style.width = Math.max(0, Math.min(100, Number(funnel.pct_finished)||0)) + '%';
  const until16 = win.secs_to_16et != null ? (' · ' + fmtDur(win.secs_to_16et) + ' until 16:00') : '';
  const fit16 = win.priority_before_16et ? ' · help pile fits by 16:00' : ' · help pile misses 16:00';
  document.getElementById('funnelFoot').textContent =
    (Number(funnel.working_now) ? `${fmt(funnel.working_now)} working now` : 'Nothing running')
    + until16 + fit16;

  const queueRows = (h.queue || [])
    .filter(r => r.status !== 'done')
    .slice(0, 12);
  document.getElementById('queue').innerHTML = queueRows.map(row => {
    const ch = row.channels || {};
    const running = row.status === 'running';
    const nextKind = ({vision:'pic', asr:'txt', acoustic:'snd', combine:'stack', consensus:'lock'})[row.next] || 'run';
    const next = ({vision:'pictures', acoustic:'sound', combine:'merge', consensus:'auto-lock'})[row.next] || row.next || '—';
    return `<div class="qrow ${running ? 'run' : ''}">
      <div>
        <div class="name">${shortSess(row.session)}</div>
        <div class="marks">
          ${mark('pic', !!ch.vision, running && livePhase==='vision')}
          ${mark('txt', !!ch.asr, running && livePhase==='vision')}
          ${mark('snd', !!ch.acoustic, running && livePhase==='acoustic')}
          ${mark('lock', !!ch.gold, running && (livePhase==='consensus'||livePhase==='combine'))}
        </div>
        <div class="foot">${row.help ? ('help ' + row.help + ' · ') : ''}${ico(nextKind)} next ${next}</div>
      </div>
      <div class="right">
        ${pill(running ? 'now' : 'queued', running ? 'run' : 'warn')}
        <div class="foot">${row.eta_s != null ? (ico('clock') + ' ' + fmtDur(row.eta_s)) : ''}</div>
      </div>
    </div>`;
  }).join('') || '<p class="meta">Queue clear</p>';
  document.getElementById('queueFoot').textContent =
    `Top ${queueRows.length} waiting/working of ${fmt(h.queue_total)} · finished hidden`;

  const byStep = lt.by_step || {};
  document.getElementById('timeKv').innerHTML = [
    [ico('clock') + ' This tape left', fmtDur(cur.remaining_s)],
    [ico('show') + ' Help pile left', fmtDur(pri.remaining_s)],
    [ico('stack') + ' All prepared left', fmtDur(totEta.remaining_s)],
    [ico('run') + ' Pace', etas.hops_per_min != null ? (fmt(etas.hops_per_min) + '/min') : '—'],
    [ico('clock') + ' Wall timed', fmtDur(tot.label_wall_s)],
    [ico('pic') + ' Pictures mean', fmtDur((byStep.vision||{}).mean_s)],
    [ico('lock') + ' Locked today', fmt(o.consensus_locked_today)],
  ].map(([k,v]) => `<span>${k}</span><span>${v}</span>`).join('');
  document.getElementById('last').textContent = JSON.stringify(o.last_tick || null, null, 2);
}
document.getElementById('linkTriage').href = apiUrl('/');
refresh().catch(err => {
  document.getElementById('sub').textContent = 'Failed: ' + err.message;
});
setInterval(() => { refresh().catch(() => {}); }, 5000);
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:  # quieter
        if args and str(args[0]).startswith("GET /still"):
            return
        super().log_message(fmt, *args)

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        if path in {"/", "/index.html"}:
            self._send(200, HTML.encode("utf-8"), "text/html; charset=utf-8")
            return
        if path in {"/dashboard", "/dashboard.html", "/overnight"}:
            self._send(200, DASHBOARD_HTML.encode("utf-8"), "text/html; charset=utf-8")
            return
        if path == "/api/overnight":
            try:
                blob = _overnight_dashboard()
            except Exception as exc:  # noqa: BLE001
                blob = {"ok": False, "error": str(exc)}
            self._send(200, json.dumps(blob, default=str).encode("utf-8"), "application/json")
            return
        if path == "/api/triage":
            qs = parse_qs(parsed.query)
            try:
                chunk_size = int((qs.get("chunk_size") or [str(DEFAULT_CHUNK_SIZE)])[0])
            except ValueError:
                chunk_size = DEFAULT_CHUNK_SIZE
            blob = _enrich(_load_triage(), chunk_size=chunk_size)
            self._send(200, json.dumps(blob).encode("utf-8"), "application/json")
            return
        if path == "/api/verdicts":
            self._send(200, json.dumps(_load_verdicts()).encode("utf-8"), "application/json")
            return
        if path == "/audio":
            qs = parse_qs(parsed.query)
            session = unquote((qs.get("session") or [""])[0])
            try:
                t0 = float((qs.get("t0") or ["0"])[0])
                t1 = float((qs.get("t1") or ["0"])[0])
                pad = float((qs.get("pad") or ["0.5"])[0])
            except ValueError:
                self._send(400, b"bad times", "text/plain")
                return
            if not session or ".." in session or "/" in session or "\\" in session:
                self._send(400, b"bad session", "text/plain")
                return
            if abs(t1 - t0) > 180:
                self._send(400, b"clip too long", "text/plain")
                return
            try:
                data = _slice_wav(session, t0, t1, pad_s=max(0.0, min(pad, 2.0)))
            except FileNotFoundError:
                self._send(404, b"missing audio", "text/plain")
                return
            except Exception as exc:  # noqa: BLE001
                self._send(500, str(exc).encode("utf-8"), "text/plain")
                return
            self._send(200, data, "audio/wav")
            return
        if path == "/still":
            qs = parse_qs(parsed.query)
            session = unquote((qs.get("session") or [""])[0])
            file = unquote((qs.get("file") or [""])[0])
            if not session or not file or "/" in file or "\\" in file or ".." in file:
                self._send(400, b"bad request", "text/plain")
                return
            root = streamers_capture_root().resolve()
            still = (_session_dir(session) / "stills" / file).resolve()
            if not str(still).startswith(str(root)) or not still.is_file():
                self._send(404, b"missing", "text/plain")
                return
            data = still.read_bytes()
            ctype = mimetypes.guess_type(still.name)[0] or "image/jpeg"
            self._send(200, data, ctype)
            return
        self._send(404, b"not found", "text/plain")

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            self._send(400, json.dumps({"ok": False, "error": str(exc)}).encode("utf-8"), "application/json")
            return

        if parsed.path == "/api/verdict":
            try:
                record = _save_verdict(
                    str(body.get("session") or ""),
                    float(body.get("t0")),
                    float(body.get("t1")),
                    str(body.get("verdict") or ""),
                    str(body.get("note") or ""),
                )
                self._send(200, json.dumps({"ok": True, "record": record}).encode("utf-8"), "application/json")
            except Exception as exc:  # noqa: BLE001
                self._send(
                    400,
                    json.dumps({"ok": False, "error": str(exc)}).encode("utf-8"),
                    "application/json",
                )
            return

        if parsed.path == "/api/human_frames":
            try:
                session = str(body.get("session") or "")
                marks = body.get("marks")
                clear_times = body.get("clear_times")
                cut_t = body.get("cut_t")
                stretch_times = body.get("stretch_times")
                t0 = body.get("t0")
                t1 = body.get("t1")
                if body.get("clear_cut") and t0 is not None and t1 is not None:
                    with _VERDICT_LOCK:
                        blob = _load_human_frames()
                        cuts = dict(blob.get("cuts") or {})
                        cuts.pop(_verdict_key(session, float(t0), float(t1)), None)
                        blob["cuts"] = cuts
                        _write_human_frames(blob)
                done_flag = body.get("done")
                record = _save_human_frames(
                    session,
                    marks={str(k): str(v) for k, v in (marks or {}).items()} if marks else None,
                    clear_times=[float(x) for x in clear_times] if clear_times is not None else None,
                    cut_t=float(cut_t) if cut_t is not None else None,
                    stretch_times=[float(x) for x in stretch_times] if stretch_times else None,
                    t0=float(t0) if t0 is not None else None,
                    t1=float(t1) if t1 is not None else None,
                    done=bool(done_flag) if done_flag is not None else None,
                )
                self._send(200, json.dumps({"ok": True, **record}).encode("utf-8"), "application/json")
            except Exception as exc:  # noqa: BLE001
                self._send(
                    400,
                    json.dumps({"ok": False, "error": str(exc)}).encode("utf-8"),
                    "application/json",
                )
            return

        self._send(404, b"not found", "text/plain")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Local episode triage visual viewer")
    p.add_argument("--port", type=int, default=PORT)
    p.add_argument("--no-open", action="store_true")
    args = p.parse_args(argv)
    port = int(args.port)
    httpd = ThreadingHTTPServer((HOST, port), Handler)
    url = f"http://{HOST}:{port}/"
    print(
        json.dumps(
            {
                "ok": True,
                "url": url,
                "triage": str(_triage_path()),
                "verdicts": str(_verdicts_path()),
                "human_frames": str(_human_frames_path()),
            },
            indent=2,
        ),
        flush=True,
    )
    if not args.no_open:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("stopped", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
