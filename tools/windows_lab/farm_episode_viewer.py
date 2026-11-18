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
# keep/mute = muter gold. drop = exclude from train (guide chrome, black, junk).
ALLOWED_HUMAN = {"keep", "mute", "drop"}


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
                    "player": row.get("player"),
                    "player_label": row.get("player_label")
                    or (f"player {row['player']}" if row.get("player") is not None else iid),
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
    human = _load_human_frames()
    waiting = _verdict_waiting_stats(triage=triage, human=human)
    pending = int(waiting.get("pending") or 0)
    done = int(waiting.get("cleared") or 0)
    pending_seconds = int(waiting.get("seconds") or 0)
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
    hop_s = job.get("hop_s")
    try:
        hop_s_f = float(hop_s) if hop_s is not None else 5.0
    except (TypeError, ValueError):
        hop_s_f = 5.0
    # Plain words for the desk (internal keys stay session/hop).
    tape_name = str(job.get("session") or "")
    still_i = hop_i
    still_of = hop_of
    live = {
        "phase": job.get("phase"),
        "session": job.get("session"),
        "tape": tape_name,  # plain: one recorded capture folder
        "session_i": job.get("session_i"),
        "session_of": job.get("session_of"),
        "hop_i": hop_i,
        "hop_of": hop_of,
        "hop_s": hop_s_f,
        "still_i": still_i,  # plain: which still we're on
        "still_of": still_of,
        "still_every_s": hop_s_f,  # usually 5s of tape per still
        "pct": pct,
        "t": job.get("t"),
        "model": job.get("model"),
        "note": job.get("note"),
        "updated_utc": job.get("updated_utc"),
        "active": bool(job.get("phase") and str(job.get("phase")) not in {"idle", ""}),
        # Heartbeat writes step_elapsed onto the job — prefer that over lock mtime
        # (lock age_s is refreshed every still, so it is useless for rate).
        "step_elapsed_s": job.get("step_elapsed_s"),
        "resumed_hops": job.get("resumed_hops"),
        "workers": job.get("workers"),
        "lock_age_s": (lock.get("meta") or {}).get("step_elapsed_s")
        if isinstance(lock, dict)
        else None,
    }
    # Heartbeat age — desk shows STALLED when the worker stops writing.
    try:
        upd = str(job.get("updated_utc") or "")
        if upd:
            job_age = (
                datetime.now(timezone.utc)
                - datetime.strptime(upd, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            ).total_seconds()
            live["job_age_s"] = round(job_age, 1)
            live["stalled"] = bool(live.get("active") and job_age >= 90.0)
    except ValueError:
        pass
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
        # Heartbeat job.step_elapsed_s wins; ledger / lock meta are fallbacks.
        job_elapsed = live.get("step_elapsed_s")
        for _k, rv in dict(label_timing.get("running") or {}).items():
            if rv.get("session") == live.get("session") and rv.get("step") == live.get("phase"):
                live["step_started_utc"] = rv.get("started_utc")
                if job_elapsed is None:
                    live["step_elapsed_s"] = rv.get("elapsed_s")
                    if rv.get("approx"):
                        live["step_elapsed_approx"] = True
                break
        if live.get("step_elapsed_s") is None and live.get("active"):
            meta_elapsed = (lock.get("meta") or {}).get("step_elapsed_s") if isinstance(lock, dict) else None
            try:
                if meta_elapsed is not None:
                    live["step_elapsed_s"] = round(float(meta_elapsed), 1)
                else:
                    # Last resort only — lock mtime is heartbeat-fresh, not span.
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
            live["stills_per_min"] = etas.get("hops_per_min")
        if live.get("hop_s") is None:
            live["hop_s"] = (etas.get("pace") or {}).get("hop_s") or 5.0
            live["still_every_s"] = live["hop_s"]
        for k in ("content_pos_s", "content_total_s", "progress_plain", "audio_s"):
            if cur.get(k) is not None:
                live[k] = cur.get(k)
    except Exception as exc:  # noqa: BLE001
        etas = {"error": str(exc)}
    # Desk-facing progress: "~37.5 min through a ~2h recording" (never hop counts).
    if not live.get("progress_plain") and live.get("active"):
        try:
            from .farm_label_timing import tape_through_plain, audit_plain_name

            every = float(live.get("still_every_s") or live.get("hop_s") or 5.0)
            pos = None
            total = None
            if still_i is not None:
                pos = float(still_i) * every
            if still_of:
                total = float(still_of) * every
            if live.get("t") is not None and pos is None:
                pos = float(live["t"])
            live["content_pos_s"] = pos
            live["content_total_s"] = total
            live["progress_plain"] = tape_through_plain(
                pos_s=pos,
                total_s=total,
                audit=audit_plain_name(str(live.get("phase") or "")),
                waiting=bool(live.get("stalled")),
            )
        except Exception:
            pass
    host_util: dict[str, Any] = {}
    try:
        from .farm_resources import host_util_snapshot

        host_util = host_util_snapshot()
    except Exception as exc:  # noqa: BLE001
        host_util = {"ok": False, "error": str(exc), "plain": "util —"}
    channel_agree: dict[str, Any] = {}
    try:
        from .farm_consensus import channel_agreement_stats

        channel_agree = channel_agreement_stats()
    except Exception as exc:  # noqa: BLE001
        channel_agree = {"ok": False, "error": str(exc)}
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
        "host_util": host_util,
        "channel_agreement": channel_agree,
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
            "pending_approx": pending,  # human_review + pic/txt/snd done + not cleared
            "pending_seconds": pending_seconds,  # merged tape estimate (not raw len_s=1 sum)
            "stretches": int(waiting.get("stretches") or 0),
            "done": done,
            "episodes": sum(len(s.get("episodes") or []) for s in (triage.get("sessions") or [])),
            "plain": waiting.get("plain"),
            "filter": "finished_pic_txt_snd_disagree_human_review",
            "skipped": waiting.get("skipped"),
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


def _episode_beat_times(episode: dict[str, Any], *, hop_s: float = 5.0) -> list[float]:
    """Hop times that make up this triage card.

    Prefer the inclusive hop grid [t0, t1] (story is often subsampled for
    display — clearing only those beats would skip unlabeled hops).
    """
    try:
        hop = max(1.0, float(hop_s or episode.get("hop_s") or 5.0))
    except (TypeError, ValueError):
        hop = 5.0
    try:
        t0 = float(episode["t0"])
        t1 = float(episode["t1"])
    except (KeyError, TypeError, ValueError):
        t0 = t1 = None
    times: list[float] = []
    if t0 is not None and t1 is not None:
        t = t0
        # Cap iterations so a corrupt span cannot hang the desk.
        for _ in range(4000):
            if t > t1 + 1e-6:
                break
            times.append(round(t, 3))
            t += hop
        if times and times[-1] < t1 - 1e-6:
            times.append(round(t1, 3))
    if times:
        return sorted(set(times))
    for b in episode.get("story") or []:
        try:
            times.append(float(b["t"]))
        except (KeyError, TypeError, ValueError):
            continue
    return sorted(set(times))


def _episode_already_cleared(
    session: str,
    episode: dict[str, Any],
    *,
    done: dict[str, Any],
    marks: dict[str, Any] | None,
    hop_s: float = 5.0,
) -> bool:
    """True when this card should leave the You-queue.

    Exact done-key match is not enough: triage used to emit 1s cards on a 5s
    spine, then merge them. Old point Done keys and per-still You marks must
    still clear the new stretch (and vice versa).
    """
    try:
        t0 = float(episode["t0"])
        t1 = float(episode["t1"])
    except (KeyError, TypeError, ValueError):
        return False
    if _verdict_key(session, t0, t1) in done:
        return True

    try:
        hop = max(1.0, float(hop_s))
    except (TypeError, ValueError):
        hop = 5.0

    done_ranges: list[tuple[float, float]] = []
    for rec in (done or {}).values():
        if not isinstance(rec, dict):
            continue
        if str(rec.get("session") or "") != session:
            continue
        try:
            a = float(rec["t0"])
            b = float(rec["t1"])
        except (KeyError, TypeError, ValueError):
            continue
        # Point Done at hop T covers that still; range Done covers [a, b+hop].
        if abs(b - a) < 0.05:
            done_ranges.append((a, a + hop))
        else:
            done_ranges.append((a, b + hop))

    def _beat_cleared(t: float) -> bool:
        if marks and _human_mark_at(marks, t) in ALLOWED_HUMAN:
            return True
        for a, b in done_ranges:
            if a - 1e-6 <= t <= b + 1e-6:
                return True
        return False

    beats = _episode_beat_times(episode, hop_s=hop) or [t0]
    return bool(beats) and all(_beat_cleared(t) for t in beats)


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
    empty = {"sessions": {}, "cuts": {}, "done": {}, "updated_utc": None}
    if not path.is_file():
        return dict(empty)
    raw = path.read_text(encoding="utf-8")
    try:
        blob = json.loads(raw)
    except json.JSONDecodeError:
        # Prefer .bak over returning empty (empty + save was wiping the desk).
        bak = path.with_suffix(".json.bak")
        if bak.is_file():
            try:
                blob = json.loads(bak.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return dict(empty)
        else:
            return dict(empty)
    if not isinstance(blob, dict):
        return dict(empty)
    blob.setdefault("sessions", {})
    blob.setdefault("cuts", {})
    blob.setdefault("done", {})
    return blob


def _session_multichannel_done(session: str) -> bool:
    """True when pictures + sound audits exist (transcript rides with pictures)."""
    d = farm_label_dir() / "audit" / str(session)
    return (d / "hops_vision.jsonl").is_file() and (d / "hops_acoustic.jsonl").is_file()


def _episode_has_pic_txt_snd(episode: dict[str, Any]) -> bool:
    """Story beats must carry vision, transcript (asr), and sound (acoustic)."""
    story = list(episode.get("story") or [])
    if not story:
        return False
    for beat in story:
        has_pic = beat.get("vision") is not None or bool(beat.get("visual"))
        has_txt = "asr" in beat  # lexicon may be empty/other
        has_snd = beat.get("acoustic") is not None or beat.get("p") is not None
        if not (has_pic and has_txt and has_snd):
            return False
    return True


def _verdict_waiting_stats(
    triage: dict[str, Any] | None = None,
    human: dict[str, Any] | None = None,
    *,
    hop_s: float = 5.0,
) -> dict[str, Any]:
    """Episodes that finished pic+txt+snd, still disagree, and need a human verdict.

    Excludes: not-yet-labeled tapes, auto suggestions that aren't human_review,
    and clips already cleared in triage.

    ``seconds`` is estimated *tape* time, not raw ``len_s`` sums. Many farm
    disagree rows are 1-frame point samples every hop_s (t0==t1, len_s=1); summing
    those as 1s each understates the tape you still have to walk. We merge nearby
    pending hops into stretches and credit ``(t1-t0)+hop_s`` per stretch.
    """
    triage = triage if triage is not None else _load_triage()
    human = human if human is not None else _load_human_frames()
    done = dict(human.get("done") or {})
    marks_by = dict(human.get("sessions") or {})
    pending = 0
    skipped = {"not_done_pipeline": 0, "not_human_review": 0, "cleared": 0, "incomplete_channels": 0}
    by_session: dict[str, list[tuple[float, float]]] = {}
    try:
        hop = max(1.0, float(hop_s))
    except (TypeError, ValueError):
        hop = 5.0
    gap = hop + 0.51  # merge stills that sit on adjacent hops
    for s in triage.get("sessions") or []:
        session = str(s.get("session") or "")
        if not session:
            continue
        ready = _session_multichannel_done(session)
        marks = marks_by.get(session) or {}
        for e in s.get("episodes") or []:
            try:
                t0 = float(e["t0"])
                t1 = float(e["t1"])
            except (KeyError, TypeError, ValueError):
                continue
            if _episode_already_cleared(session, e, done=done, marks=marks, hop_s=hop):
                skipped["cleared"] += 1
                continue
            if not ready:
                skipped["not_done_pipeline"] += 1
                continue
            if (e.get("action") or {}).get("do") != "human_review":
                skipped["not_human_review"] += 1
                continue
            if not _episode_has_pic_txt_snd(e):
                skipped["incomplete_channels"] += 1
                continue
            story = list(e.get("story") or [])
            if story and all(_vision_text_is_guide(b.get("visual")) for b in story):
                skipped.setdefault("guide_chrome", 0)
                skipped["guide_chrome"] += 1
                continue
            pending += 1
            by_session.setdefault(session, []).append((t0, t1))
    seconds = 0.0
    stretches = 0
    for rows in by_session.values():
        rows = sorted(rows)
        a, b = rows[0]
        for t0, t1 in rows[1:]:
            if t0 <= b + gap:
                if t1 > b:
                    b = t1
                continue
            seconds += (b - a) + hop
            stretches += 1
            a, b = t0, t1
        seconds += (b - a) + hop
        stretches += 1
    sec_i = int(round(seconds))
    return {
        "pending": pending,
        "seconds": sec_i,
        "stretches": stretches,
        "cleared": len(done),
        "skipped": skipped,
        "hop_s": hop,
        "plain": (
            f"{pending} disagree clips · ~{sec_i}s tape ({stretches} stretches)"
            if pending
            else "Verdict clear"
        ),
    }


def _human_frames_weight(blob: dict[str, Any] | None) -> int:
    if not isinstance(blob, dict):
        return 0
    n = len(blob.get("done") or {})
    for marks in (blob.get("sessions") or {}).values():
        if isinstance(marks, dict):
            n += len(marks)
    return n


def _write_human_frames(blob: dict) -> dict:
    """Atomic write. Refuse to clobber a fat label file with a near-empty one.

    Concurrent desk/viewer/triage used to read a half-written JSON (decode →
    empty), then save — wiping thousands of You marks. Keep a ``.bak`` and
    require an explicit shrink override to replace a large file with a tiny one.
    """
    path = _human_frames_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    blob = dict(blob)
    blob["updated_utc"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    new_n = _human_frames_weight(blob)
    if path.is_file():
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            old = None
        old_n = _human_frames_weight(old)
        # Guard: never replace ≥50 labels with <20% of prior mass unless forced.
        if old_n >= 50 and new_n < max(10, int(old_n * 0.2)) and not blob.pop("_force_shrink", False):
            bak = path.with_suffix(".json.refuse_shrink")
            bak.write_text(json.dumps(blob, indent=2) + "\n", encoding="utf-8")
            raise RuntimeError(
                f"refusing to shrink EPISODE_HUMAN_FRAMES ({old_n} → {new_n}); "
                f"wrote candidate to {bak.name}"
            )
        if old_n > 0:
            path.with_suffix(".json.bak").write_text(
                json.dumps(old, indent=2) + "\n", encoding="utf-8"
            )
    text = json.dumps(blob, indent=2) + "\n"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)
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
    """Update per-second human marks for a session.

    - marks: { "27": "mute"|"keep"|"drop", ... } merge
    - clear_times: undo marks at those seconds (not the same as drop)
    - cut_t + stretch_times: keep before cut_t, mute from cut_t onward
    - done: mark stretch confirmed / remove from queue (requires t0,t1)

    ``drop`` = junk / guide chrome — exclude from muter train (not Show, not Ad).
    ``clear`` only removes your mark so the frame is unmarked again.
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
                "vision_guide": _vision_text_is_guide(v.get("visual") or ""),
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


def _vision_text_is_guide(text: str | None) -> bool:
    """Guide chrome or emulator promo (BlueStacks Prime) — drop, not train."""
    try:
        from .farm_draft import vision_caption_is_drop_junk

        return bool(vision_caption_is_drop_junk(text))
    except Exception:  # noqa: BLE001
        try:
            from .farm_draft import vision_caption_is_guide

            return bool(vision_caption_is_guide(text))
        except Exception:  # noqa: BLE001
            return False


def _vision_visual_by_t(session: str) -> dict[float, str]:
    """Map hop time → vision caption for a session (from hops_vision or hops)."""
    out: dict[float, str] = {}
    audit = farm_label_dir() / "audit" / str(session)
    for name in ("hops_vision.jsonl", "hops.jsonl"):
        path = audit / name
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            try:
                t = round(float(row.get("t") or 0.0), 1)
            except (TypeError, ValueError):
                continue
            vis = ((row.get("channels") or {}).get("vision") or {}).get("visual")
            if not vis:
                vis = row.get("visual")
            if vis and t not in out:
                out[t] = str(vis)
        if out:
            break
    return out


def auto_drop_guides_from_vision(*, dry_run: bool = False) -> dict[str, Any]:
    """Drop + clear finished disagree clips that are guide chrome or emulator junk.

    Uses existing VL captions (image data) — no re-infer. Marks matching stills
    as human ``drop`` and marks the episode Done so it leaves the queue.
    Emulator junk = BlueStacks Prime upsell overlays (not TV ads).
    """
    triage = _load_triage()
    human = _load_human_frames()
    done = dict(human.get("done") or {})
    sessions_marks = dict(human.get("sessions") or {})
    vis_cache: dict[str, dict[float, str]] = {}
    dropped_frames = 0
    cleared_eps = 0
    skipped_saved = 0
    considered = 0
    for s in triage.get("sessions") or []:
        session = str(s.get("session") or "")
        if not session:
            continue
        if not _session_multichannel_done(session):
            continue
        if session not in vis_cache:
            vis_cache[session] = _vision_visual_by_t(session)
        vis_map = vis_cache[session]
        marks = dict(sessions_marks.get(session) or {})
        dirty = False
        for e in s.get("episodes") or []:
            try:
                t0 = float(e["t0"])
                t1 = float(e["t1"])
            except (KeyError, TypeError, ValueError):
                continue
            dk = _verdict_key(session, t0, t1)
            if dk in done:
                continue
            action = str((e.get("action") or {}).get("do") or "")
            tag = str(e.get("tag") or "")
            triage_says_guide = action == "drop_guide" or tag == "streamers_guide"
            if action not in {"human_review", "drop_guide"} and not triage_says_guide:
                continue
            if not _episode_has_pic_txt_snd(e):
                continue
            considered += 1
            story = list(e.get("story") or [])
            times = sorted(
                {
                    round(float(b["t"]), 1)
                    for b in story
                    if b.get("t") is not None
                }
                or {round(t0, 1)}
            )
            guide_times: list[float] = []
            for t in times:
                text = vis_map.get(t) or ""
                if not text:
                    for b in story:
                        try:
                            if abs(float(b.get("t") or -1) - t) < 0.15:
                                text = str(b.get("visual") or "")
                                break
                        except (TypeError, ValueError):
                            continue
                if _vision_text_is_guide(text):
                    guide_times.append(t)
            # Triage already tagged guide, or ≥80% of story beats are junk chrome.
            if not triage_says_guide:
                if not guide_times or len(guide_times) < max(1, int(0.8 * len(times) + 0.999)):
                    continue
            # Drop every hop in the episode span whose caption matches (not only story subsample).
            span_hits = [
                float(t)
                for t, text in vis_map.items()
                if t0 - 1e-6 <= float(t) <= t1 + 1e-6 and _vision_text_is_guide(text)
            ]
            targets = sorted(set(guide_times) | set(span_hits)) or list(times)
            if any(_human_mark_at(marks, t) in {"keep", "mute"} for t in targets):
                skipped_saved += 1
                continue
            for t in targets:
                key = f"{float(t):g}"
                if _human_mark_at(marks, t) != "drop":
                    marks[key] = "drop"
                    dropped_frames += 1
            done[dk] = {
                "session": session,
                "t0": t0,
                "t1": t1,
                "utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "source": "auto_drop_guide_or_emulator_junk",
            }
            cleared_eps += 1
            dirty = True
        if dirty:
            sessions_marks[session] = marks
    blob = {
        **human,
        "sessions": sessions_marks,
        "done": done,
        "updated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if not dry_run and (dropped_frames or cleared_eps):
        _write_human_frames(blob)
    return {
        "ok": True,
        "dry_run": dry_run,
        "considered_episodes": considered,
        "dropped_frames": dropped_frames,
        "cleared_episodes": cleared_eps,
        "skipped_human_keep_mute": skipped_saved,
        "waiting_after": _verdict_waiting_stats(triage=triage, human=blob),
    }


def _still_md5(session: str, still_name: str) -> str | None:
    if not still_name:
        return None
    path = _session_dir(session) / "stills" / still_name
    if not path.is_file():
        return None
    try:
        import hashlib

        return hashlib.md5(path.read_bytes()).hexdigest()
    except OSError:
        return None


def auto_drop_frozen_stills(*, dry_run: bool = False, min_repeat: int = 3) -> dict[str, Any]:
    """Drop lag-frozen runs: the same still bytes repeated across a disagree stretch.

    Capture lag leaves one Pants-on-Fire (etc.) frame copied for many seconds.
    Dropping one second left the rest in queue — clear the whole freeze run and
    mark the episode Done so it cannot train.
    """
    triage = _load_triage()
    human = _load_human_frames()
    done = dict(human.get("done") or {})
    sessions_marks = dict(human.get("sessions") or {})
    denied_path = farm_label_dir() / "audit" / "DENIED_STILL_MD5.json"
    denied: set[str] = set()
    if denied_path.is_file():
        try:
            denied = {str(x) for x in (json.loads(denied_path.read_text(encoding="utf-8")).get("md5") or [])}
        except json.JSONDecodeError:
            denied = set()
    dropped_frames = 0
    cleared_eps = 0
    frozen_md5s: set[str] = set()
    considered = 0
    for s in triage.get("sessions") or []:
        session = str(s.get("session") or "")
        if not session or not _session_multichannel_done(session):
            continue
        marks = dict(sessions_marks.get(session) or {})
        dirty = False
        for e in s.get("episodes") or []:
            try:
                t0 = float(e["t0"])
                t1 = float(e["t1"])
            except (KeyError, TypeError, ValueError):
                continue
            dk = _verdict_key(session, t0, t1)
            if dk in done:
                continue
            if str((e.get("action") or {}).get("do") or "") not in {"human_review", "drop_guide"}:
                continue
            if not _episode_has_pic_txt_snd(e):
                continue
            considered += 1
            frames = _episode_frames(session, t0, t1)
            if len(frames) < max(2, int(min_repeat)):
                # Still check lag caption on sparse cards.
                vis_hits = [
                    float(f["t"])
                    for f in frames
                    if _vision_text_is_guide(str(f.get("visual") or ""))
                ]
                if not vis_hits:
                    continue
                targets = vis_hits
            else:
                by_md5: dict[str, list[float]] = {}
                for f in frames:
                    dig = _still_md5(session, str(f.get("still_name") or ""))
                    if not dig:
                        continue
                    by_md5.setdefault(dig, []).append(float(f["t"]))
                targets = []
                for dig, ts in by_md5.items():
                    if dig in denied or len(ts) >= int(min_repeat) or len(ts) >= max(3, int(0.5 * len(frames))):
                        targets.extend(ts)
                        frozen_md5s.add(dig)
                        denied.add(dig)
                # Caption lag-stuck (Pants on Fire) even if md5 varies slightly.
                for f in frames:
                    if _vision_text_is_guide(str(f.get("visual") or "")):
                        targets.append(float(f["t"]))
                targets = sorted(set(targets))
                if not targets:
                    continue
                # Require the freeze to dominate the stretch before auto-clearing.
                if len(targets) < max(int(min_repeat), int(0.5 * len(frames) + 0.999)):
                    continue
            if any(_human_mark_at(marks, t) in {"keep", "mute"} for t in targets):
                continue
            for t in targets:
                key = f"{float(t):g}"
                if _human_mark_at(marks, t) != "drop":
                    marks[key] = "drop"
                    dropped_frames += 1
            # If most of the stretch is freeze/junk, Done the whole card.
            cover = len(targets) / max(1, len(frames) if frames else len(targets))
            if cover >= 0.8 or not frames:
                done[dk] = {
                    "session": session,
                    "t0": t0,
                    "t1": t1,
                    "utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "source": "auto_drop_frozen_still",
                }
                cleared_eps += 1
            dirty = True
        if dirty:
            sessions_marks[session] = marks
    blob = {
        **human,
        "sessions": sessions_marks,
        "done": done,
        "updated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if not dry_run and (dropped_frames or cleared_eps):
        _write_human_frames(blob)
        denied_path.write_text(
            json.dumps(
                {
                    "md5": sorted(denied),
                    "updated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "note": "Lag-frozen still bytes — never train / always Drop in Verdict",
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    return {
        "ok": True,
        "dry_run": dry_run,
        "considered_episodes": considered,
        "dropped_frames": dropped_frames,
        "cleared_episodes": cleared_eps,
        "frozen_md5_n": len(frozen_md5s),
        "denied_md5_n": len(denied),
        "waiting_after": _verdict_waiting_stats(triage=triage, human=blob),
    }


# Most disagree rows are 1-frame (~1s) hops — load a bigger queue than the old 4.
DEFAULT_CHUNK_SIZE = 16
MAX_CHUNK_SIZE = 32


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
    chunk_size = max(1, min(int(chunk_size), MAX_CHUNK_SIZE))

    flat = _flat_episodes(triage)
    pending_keys: list[str] = []
    cleared_n = 0
    for session, e in flat:
        dk = _verdict_key(session, float(e["t0"]), float(e["t1"]))
        marks = human_sessions.get(session) or {}
        if _episode_already_cleared(session, e, done=human_done, marks=marks):
            cleared_n += 1
            continue
        if (e.get("action") or {}).get("do") != "human_review":
            continue
        if not _session_multichannel_done(session):
            continue
        if not _episode_has_pic_txt_snd(e):
            continue
        # Guide chrome never belongs in the You-queue (even before Drop is written).
        story = list(e.get("story") or [])
        if story and all(_vision_text_is_guide(b.get("visual")) for b in story):
            continue
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
            cleared = _episode_already_cleared(session, e, done=human_done, marks=marks)
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
                    "human_done": human_done.get(dk) or (True if cleared else None),
                    "already_cleared": cleared,
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
            "cleared_total": cleared_n,
            "episode_total": len(flat),
        },
    }


HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover"/>
<meta name="apple-mobile-web-app-capable" content="yes"/>
<meta name="mobile-web-app-capable" content="yes"/>
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
  .btn-nav, .btn-next, .btn-done {
    border: 1px solid var(--line); background: #fff; color: var(--ink);
    border-radius: 8px; padding: 8px 14px; cursor: pointer;
    font: inherit; font-weight: 700; font-size: 13px; white-space: nowrap;
    display: inline-flex; align-items: center; gap: 4px;
  }
  .btn-nav:hover { border-color: var(--ink); }
  .btn-done, .btn-next {
    border-color: #0f766e; background: #0f766e; color: #fff;
  }
  .btn-done:hover, .btn-next:hover { background: #0d9488; border-color: #0d9488; }
  .btn-nav:disabled, .btn-done:disabled, .btn-next:disabled { opacity: 0.45; cursor: default; }
  .frame-nav { display: inline-flex; align-items: center; gap: 6px; }
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
  .pill.drop { background: #f3e8ff; color: #6b21a8; }
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
    grid-template-columns: 200px minmax(180px, 1fr) 188px;
    gap: 0;
    align-items: stretch;
    width: 100%;
    max-width: 740px;
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
  .card img {
    display: block; width: 200px; height: 112px; object-fit: cover; background: #111;
    cursor: zoom-in;
  }
  .card .nostill {
    width: 200px; height: 112px; display: flex; align-items: center; justify-content: center;
    color: #888; background: #1a1a1a; font-size: 12px;
  }
  .lightbox {
    position: fixed; inset: 0; z-index: 40;
    display: none; align-items: center; justify-content: center;
    background: rgba(10, 16, 22, .92); padding: 24px;
  }
  .lightbox.open { display: flex; }
  .lightbox img {
    max-width: min(96vw, 1600px);
    max-height: 92vh;
    width: auto; height: auto;
    object-fit: contain;
    border-radius: 4px;
    box-shadow: 0 0 0 1px rgba(255,255,255,.12);
  }
  .lightbox .lb-close {
    position: absolute; top: 14px; right: 14px; z-index: 2;
    width: 44px; height: 44px; border-radius: 8px;
    border: 1px solid rgba(255,255,255,.35); background: rgba(18,32,43,.9);
    color: #fff; cursor: pointer; font: inherit; font-size: 22px; font-weight: 700;
    line-height: 1; display: flex; align-items: center; justify-content: center;
  }
  .lightbox .lb-close:hover { background: #fff; color: #14212b; }
  .lightbox .lb-meta {
    position: absolute; left: 16px; bottom: 14px;
    color: rgba(255,255,255,.75); font-size: 12px; font-weight: 600;
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
    touch-action: manipulation; -webkit-tap-highlight-color: transparent;
    user-select: none;
  }
  .pick.drop {
    grid-column: 1 / -1;
    flex-direction: row; gap: 6px; min-height: 34px; padding: 6px 8px;
    font-size: 12px;
  }
  .pick.drop .ico { width: 14px; height: 14px; margin-bottom: 0; }
  .pick .sub {
    display: block; font-size: 10px; font-weight: 700; letter-spacing: .04em;
    text-transform: uppercase; opacity: .7; margin-top: 1px;
  }
  .pick.drop .sub { margin-top: 0; }
  .pick .ico { width: 18px; height: 18px; margin-bottom: 2px; }
  .pick.show.on {
    background: #ccfbf1; color: var(--show); border-color: #0f766e;
  }
  .pick.ad.on {
    background: #ffedd5; color: var(--ad); border-color: #c2410c;
  }
  .pick.drop.on {
    background: #e5e7eb; color: #374151; border-color: #4b5563;
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
  .action-bar .hint { margin: 0; font-size: 12px; color: var(--muted); line-height: 1.3; max-width: 40vw; }
  .action-bar .frame-nav .btn-nav { min-width: 96px; padding: 12px 14px; font-size: 14px; }
  .action-bar .btn-done { min-width: 120px; padding: 12px 18px; font-size: 15px; }
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
    header { flex-direction: column; gap: 6px; padding: 10px 12px; }
    header .right { width: 100%; justify-content: space-between; }
    .legend { max-width: none; display: none; }
    .hdr-next { display: none; }
    .layout { grid-template-columns: 1fr; padding-bottom: calc(88px + env(safe-area-inset-bottom, 0px)); }
    nav {
      display: flex; gap: 8px; overflow-x: auto; border-right: 0;
      border-bottom: 1px solid var(--line); padding-bottom: 8px;
      -webkit-overflow-scrolling: touch;
    }
    nav button { min-width: 160px; flex: 0 0 auto; padding: 10px; }
    main { padding: 8px 10px 20px; }
    .hero-title { font-size: 16px; }
    .hero-do { display: none; }
    .audit-key { display: none; }
    .meta-bar { font-size: 10px; }
    .listen { margin-bottom: 8px; }
    .strip-wrap { max-height: none; border: 0; background: transparent; padding: 0; }
    .strip-head { margin-bottom: 8px; }
    .card {
      grid-template-columns: 1fr;
      max-width: none;
    }
    /* Label first on phone — thumb reach without scrolling past audits */
    .card .you-col {
      order: 1; border-left: 0; border-bottom: 1px solid var(--line);
      min-height: 0; padding: 12px;
      position: sticky; top: 52px; z-index: 3;
      background: #eef3f6;
    }
    .card .thumb { order: 2; }
    .card img, .card .nostill { width: 100%; height: min(42vw, 220px); }
    .card .body { order: 3; border-left: 0; border-top: 1px solid var(--line); padding: 8px 10px; }
    .card:not(.selected) .you-col { position: static; }
    .card:not(.selected) .pick { min-height: 48px; font-size: 14px; }
    .choice {
      grid-template-columns: 1fr 1fr 1fr;
      gap: 8px; min-height: 72px;
    }
    .pick {
      font-size: 16px; min-height: 64px; padding: 10px 4px;
      border-radius: 12px;
    }
    .pick.drop {
      grid-column: auto; flex-direction: column; min-height: 64px; gap: 2px;
    }
    .pick .sub { font-size: 10px; }
    .pick.drop .sub { margin-top: 1px; }
    .choice-hint { margin-top: 4px; }
    .action-bar {
      padding: 10px 12px calc(10px + env(safe-area-inset-bottom, 0px));
      gap: 8px;
    }
    .action-bar .hint { max-width: 36vw; font-size: 11px; line-height: 1.25; }
    .action-bar .frame-nav { gap: 8px; flex: 1; justify-content: flex-end; }
    .action-bar .frame-nav .btn-nav {
      min-width: 0; flex: 1; max-width: 120px;
      padding: 14px 12px; font-size: 15px; min-height: 48px;
      touch-action: manipulation;
    }
    .action-bar .btn-done { display: none; }
    .lightbox { padding: 12px; padding-top: 56px; }
    .lightbox .lb-close {
      top: calc(10px + env(safe-area-inset-top, 0px));
      right: 10px; width: 48px; height: 48px; font-size: 26px;
    }
    .lightbox img { max-height: 85vh; }
  }
  @media (max-width: 420px) {
    .action-bar .hint { display: none; }
    .signals .sig .lab { display: none; }
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
      <span><span class="swatch" style="background:#e5e7eb"></span><b>Drop</b></span>
      <span><span class="swatch" style="background:#fee2e2"></span><b>Muted</b></span>
      <span><span class="swatch" style="background:#dbeafe"></span><b>Playing</b></span>
    </div>
    <a class="nav-link" id="linkDash" href="/dashboard">Desk</a>
    <a class="nav-link" id="linkSched" href="/schedule">Schedule</a>
    <button type="button" class="btn-done hdr-next" id="btnDoneHdr" title="Finish this stretch and load the next one">Done</button>
  </div>
</header>
<div class="layout">
  <nav id="nav"></nav>
  <main id="main"><div class="empty">Pick a stretch</div></main>
</div>
<div class="action-bar">
  <p class="hint" id="actionHint">Show / Ad / Drop = one click · last frame auto-advances stretch</p>
  <div class="frame-nav">
    <button type="button" class="btn-nav" id="btnPrevFrame" title="Previous frame · on first frame, reopen last Done stretch">← Prev</button>
    <button type="button" class="btn-nav" id="btnNextFrame" title="Next frame (no label)">Next →</button>
    <button type="button" class="btn-done" id="btnDone" title="Skip leftovers using suggestions · usually not needed — labeling the last frame finishes the stretch">Done</button>
  </div>
</div>
<div class="lightbox" id="lightbox" role="dialog" aria-modal="true" aria-label="Still fullscreen" hidden>
  <button type="button" class="lb-close" id="lbClose" title="Close" aria-label="Close">×</button>
  <img id="lbImg" alt=""/>
  <div class="lb-meta" id="lbMeta"></div>
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
    drop: '<path d="M4 7h12M8 7V5h4v2M6 7l1 9h6l1-9"/>',
    next: '<path d="M5 10h9M10 6l4 4-4 4"/>',
    prev: '<path d="M15 10H6M10 6l-4 4 4 4"/>',
    clock: '<circle cx="10" cy="10" r="7"/><path d="M10 6v4.5L13 12"/>',
  };
  const p = paths[name] || paths.pic;
  return `<svg class="${c}" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${p}</svg>`;
}
let DATA = null;
let selected = null;
let selectedFrame = 0;
let HUMAN = {}; // session -> { tKey: keep|mute|drop }
let HUMAN_CUTS = {}; // epKey -> { cut_t }
let HUMAN_DONE = {}; // epKey -> { utc }
/** Last Done stretches so ← Prev / Back can reopen and fix. */
const RECENT_STRETCHES = [];
const MAX_RECENT_STRETCHES = 16;

const TAG = {
  streamers_guide: { pill: 'drop', title: 'Guide chrome', short: 'Auto-drop · not train' },
  boundary_late: { pill: 'fix', title: 'Label cut is late', short: 'Fix the gold cut' },
  soft_gold_or_vision_ad: { pill: 'fix', title: 'Label may be soft', short: 'Check if this is really show' },
  true_acoustic_fp: { pill: 'muter', title: 'Live muter false mute', short: 'Model muted real show' },
  hangover: { pill: 'hang', title: 'Slow unmute', short: 'Stuck muted after ad' },
  mixed_review: { pill: 'review', title: 'Needs a look', short: 'Mixed signals' },
};
const DO = {
  drop_guide: 'Auto-drop guide chrome (not train)',
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
  if (v === 'drop') return {cls:'drop', text:'Drop', value:'drop', prefill: !!prefill};
  return {cls:'unk', text:'—', value:null, prefill: false};
}
function choiceHtml(i, hd) {
  const H = humanLook(hd.value, {prefill: hd.prefill});
  const keepOn = H.value === 'keep' ? 'on' : '';
  const muteOn = H.value === 'mute' ? 'on' : '';
  const dropOn = H.value === 'drop' ? 'on' : '';
  const pref = H.prefill ? 'prefill' : '';
  const hint = H.value
    ? (H.prefill ? 'suggested' : (H.value === 'drop' ? 'dropped · not train' : 'yours'))
    : 'pick one';
  const hintCls = (!H.prefill && H.value) ? 'yours' : '';
  return `<div class="choice" data-choice-i="${i}">
    <button type="button" class="pick show ${keepOn} ${keepOn?pref:''}" data-pick="keep" data-i="${i}" title="Show · one click (last frame finishes stretch)">
      ${ico('show')}<span>Show</span><span class="sub">keep</span>
    </button>
    <button type="button" class="pick ad ${muteOn} ${muteOn?pref:''}" data-pick="mute" data-i="${i}" title="Ad · one click · double-click = cut starts here">
      ${ico('ad')}<span>Ad</span><span class="sub">mute</span>
    </button>
    <button type="button" class="pick drop ${dropOn}" data-pick="drop" data-i="${i}" title="Drop junk/guide · one click">
      ${ico('drop')}<span>Drop</span><span class="sub">junk</span>
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
/** Saved You mark, else vision-guide drop, else gold prefill. */
function humanDisplay(session, f) {
  const saved = humanAt(session, f.t) || f.human || null;
  if (saved) return { value: saved, prefill: false };
  if (f.vision_guide) return { value: 'drop', prefill: true };
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
  updateNavButtons();
}

function updateNavButtons() {
  const cur = currentEp();
  const frames = cur ? (cur.e.frames || []) : [];
  const n = frames.length;
  const done = !cur || isDone(cur.s.session, cur.e.t0, cur.e.t1, cur.e);
  const canStretchBack = RECENT_STRETCHES.length > 0;
  const onFirst = !cur || n < 1 || selectedFrame <= 0;
  const prev = document.getElementById('btnPrevFrame');
  const next = document.getElementById('btnNextFrame');
  if (prev) {
    if (!onFirst) {
      prev.disabled = false;
      prev.innerHTML = `${ico('prev')} Prev`;
      prev.title = 'Previous frame';
    } else if (canStretchBack) {
      prev.disabled = false;
      prev.innerHTML = `${ico('prev')} Back`;
      prev.title = `Reopen last Done stretch (${RECENT_STRETCHES.length} saved)`;
    } else {
      prev.disabled = true;
      prev.innerHTML = `${ico('prev')} Prev`;
      prev.title = 'Previous frame';
    }
  }
  if (next) {
    next.disabled = !cur || n < 2 || selectedFrame >= n - 1;
    next.innerHTML = `Next ${ico('next')}`;
  }
  ['btnDone', 'btnDoneHdr'].forEach(id => {
    const btn = document.getElementById(id);
    if (!btn) return;
    btn.disabled = done;
    btn.innerHTML = `${ico('next')} Done`;
  });
  const hint = document.getElementById('actionHint');
  if (hint) {
    const backNote = canStretchBack ? ` · Back×${RECENT_STRETCHES.length}` : '';
    if (!cur) hint.textContent = canStretchBack ? `Queue empty · ← Back reopens last Done` : 'Queue empty';
    else if (!n) hint.textContent = 'No frames in this stretch';
    else if (n === 1) hint.innerHTML = `One frame · Show / Ad / Drop finishes + next stretch${backNote}`;
    else hint.innerHTML = `Frame <b>${selectedFrame + 1}/${n}</b> · last pick auto-finishes stretch${backNote}`;
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
    updateNavButtons();
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
      ? `<img class="still-zoom" src="${apiUrl(f.still_url)}" alt="${f.t}s" loading="lazy" data-full="${apiUrl(f.still_url)}" data-t="${f.t}" title="Click to enlarge"/>`
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
        <p class="strip-label">${cutT != null ? (ico('ad') + ' Your cut @ ' + cutT + 's') : (ico('show') + ' / ' + ico('ad') + ' / Drop · dashed = suggested · double-tap Ad = cut')}</p>
        <button type="button" class="strip-clear" id="btnClearHuman" title="Undo marks on this stretch (not Drop — Drop excludes junk from train)">Undo</button>
      </div>
      <div class="strip" id="strip">${cards}</div>
    </div>
  `;
  updateNavButtons();
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
    updateNavButtons();
  }
  // Expose for bottom Prev/Next and 1-click label advance
  window.__epSelectFrame = selectFrame;
  window.__epFrameCount = frames.length;

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
      if (ev.target && ev.target.closest && ev.target.closest('[data-pick], .still-zoom')) return;
      selectFrame(Number(card.dataset.i), {seek: true, autoplay: false, scroll: false});
    };
  });
  main.querySelectorAll('img.still-zoom').forEach(img => {
    img.onclick = (ev) => {
      ev.stopPropagation();
      const i = Number(img.closest('.card')?.dataset?.i);
      if (Number.isFinite(i)) selectFrame(i, {seek: true, autoplay: false, scroll: false});
      openLightbox(img.dataset.full || img.src, img.dataset.t);
    };
  });
  bindPickButtons(main, selectFrame);
  selectFrame(selectedFrame || 0, {seek: false, scroll: false});
}

function openLightbox(src, t) {
  const lb = document.getElementById('lightbox');
  const im = document.getElementById('lbImg');
  const meta = document.getElementById('lbMeta');
  if (!lb || !im || !src) return;
  im.src = src;
  im.alt = (t != null ? (t + 's') : 'still');
  if (meta) meta.textContent = t != null ? ('Take clock ' + Number(t).toFixed(1) + 's · Esc or × to close') : 'Esc or × to close';
  lb.hidden = false;
  lb.classList.add('open');
}

function closeLightbox() {
  const lb = document.getElementById('lightbox');
  const im = document.getElementById('lbImg');
  if (!lb) return;
  lb.classList.remove('open');
  lb.hidden = true;
  if (im) im.removeAttribute('src');
}

function bindPickButtons(root, selectFrameFn) {
  let pickClickTimer = null;
  (root || document).querySelectorAll('[data-pick]').forEach(btn => {
    btn.onclick = (ev) => {
      ev.stopPropagation();
      const i = Number(btn.dataset.i);
      const val = btn.dataset.pick;
      if (selectFrameFn) selectFrameFn(i, {seek: false, autoplay: false, scroll: false});
      if (pickClickTimer) clearTimeout(pickClickTimer);
      // Short delay so double-click Ad can set cut without racing a +next advance
      pickClickTimer = setTimeout(() => {
        pickClickTimer = null;
        setHumanChoice(i, val, {advance: true});
      }, 180);
    };
    btn.ondblclick = (ev) => {
      ev.stopPropagation();
      ev.preventDefault();
      if (pickClickTimer) { clearTimeout(pickClickTimer); pickClickTimer = null; }
      const i = Number(btn.dataset.i);
      const val = btn.dataset.pick;
      if (selectFrameFn) selectFrameFn(i, {seek: false, autoplay: false, scroll: false});
      // Ad double-click = cut starts here; stay on frame so you can see the cut
      setHumanChoice(i, val, {advance: false}).then(() => {
        if (val === 'mute') saveCutFromSelected();
      });
    };
  });
}

function paintChoices(session, frames) {
  frames.forEach((f, i) => {
    const col = document.querySelector(`.card[data-i="${i}"] .you-col`);
    if (!col) return;
    col.innerHTML = choiceHtml(i, humanDisplay(session, f));
    bindPickButtons(col, (idx, opts) => {
      if (window.__epSelectFrame) window.__epSelectFrame(idx, opts || {});
    });
  });
}

function focusFrame(i, opts) {
  if (typeof window.__epSelectFrame === 'function') {
    window.__epSelectFrame(i, Object.assign({seek: true, scroll: true}, opts || {}));
    return;
  }
  selectedFrame = i;
  updateNavButtons();
}

function stepFrame(delta) {
  const cur = currentEp();
  if (delta < 0 && (!cur || selectedFrame <= 0)) {
    if (RECENT_STRETCHES.length) reopenLastStretch();
    return;
  }
  if (!cur) return;
  const n = (cur.e.frames || []).length;
  if (!n) return;
  focusFrame(Math.max(0, Math.min(n - 1, selectedFrame + delta)));
}

function pushRecentStretch(cur, id) {
  if (!cur) return;
  const frames = (cur.e.frames || []).map(f => Object.assign({}, f));
  RECENT_STRETCHES.push({
    session: cur.s.session,
    t0: cur.e.t0,
    t1: cur.e.t1,
    key: cur.key,
    tag: cur.e.tag,
    action: cur.e.action,
    len_s: cur.e.len_s,
    frames,
  });
  while (RECENT_STRETCHES.length > MAX_RECENT_STRETCHES) RECENT_STRETCHES.shift();
}

function ensureRecentInData(item) {
  if (!DATA.sessions) DATA.sessions = [];
  let si = DATA.sessions.findIndex(s => s.session === item.session);
  if (si < 0) {
    DATA.sessions.push({ session: item.session, episodes: [] });
    si = DATA.sessions.length - 1;
  }
  const s = DATA.sessions[si];
  if (!s.episodes) s.episodes = [];
  let ei = s.episodes.findIndex(e =>
    Math.abs(Number(e.t0) - Number(item.t0)) < 1e-6 &&
    Math.abs(Number(e.t1) - Number(item.t1)) < 1e-6
  );
  const patch = {
    t0: item.t0,
    t1: item.t1,
    len_s: item.len_s != null ? item.len_s : (Number(item.t1) - Number(item.t0)),
    tag: item.tag || 'mixed_review',
    action: item.action || { do: 'human_review' },
    frames: item.frames || [],
    n_frames: (item.frames || []).length,
    in_chunk: true,
    human_done: null,
  };
  if (ei < 0) {
    s.episodes.push(patch);
    ei = s.episodes.length - 1;
  } else {
    Object.assign(s.episodes[ei], patch);
  }
  return `${si}:${ei}`;
}

async function reopenLastStretch() {
  const item = RECENT_STRETCHES.pop();
  if (!item) return;
  const prevBtn = document.getElementById('btnPrevFrame');
  if (prevBtn) { prevBtn.disabled = true; prevBtn.textContent = 'Opening…'; }
  try {
    const res = await fetch(apiUrl('/api/human_frames'), {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        session: item.session,
        t0: item.t0,
        t1: item.t1,
        done: false,
      }),
    });
    const body = await res.json();
    if (!res.ok || !body.ok) throw new Error(body.error || 'reopen failed');
    if (body.done_map) HUMAN_DONE = body.done_map;
    else delete HUMAN_DONE[item.key];
    if (body.marks) HUMAN[item.session] = body.marks;
    selected = ensureRecentInData(item);
    selectedFrame = 0;
    if (DATA.chunk) {
      DATA.chunk.pending_total = (DATA.chunk.pending_total || 0) + 1;
      DATA.chunk.done_total = Math.max(0, (DATA.chunk.done_total || 1) - 1);
    }
    updateHdr();
    renderNav();
    renderMain();
  } catch (err) {
    RECENT_STRETCHES.push(item);
    updateNavButtons();
    alert('Back failed: ' + err.message);
  }
}

async function setHumanChoice(i, next, {advance} = {}) {
  const cur = currentEp();
  if (!cur) return;
  const f = cur.e.frames[i];
  if (!f || (next !== 'keep' && next !== 'mute' && next !== 'drop')) return;
  const doAdvance = advance !== false;
  // Lag freeze: one Drop on a stuck still should Drop every identical frame in the stretch.
  const marks = {};
  const targets = [i];
  if (next === 'drop' && f.still_url) {
    (cur.e.frames || []).forEach((fr, idx) => {
      if (fr && fr.still_url && fr.still_url === f.still_url) targets.push(idx);
    });
  }
  [...new Set(targets)].forEach((idx) => {
    const fr = cur.e.frames[idx];
    if (!fr) return;
    setHumanLocal(cur.s.session, fr.t, next);
    fr.human = next;
    marks[String(fr.t)] = next;
  });
  paintChoices(cur.s.session, cur.e.frames);
  try {
    await fetch(apiUrl('/api/human_frames'), {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        session: cur.s.session,
        marks,
        t0: cur.e.t0,
        t1: cur.e.t1,
      }),
    });
  } catch (_) {}
  if (doAdvance) {
    const n = (cur.e.frames || []).length;
    const allDropped = next === 'drop' && (cur.e.frames || []).every(fr => humanAt(cur.s.session, fr.t) === 'drop');
    if (allDropped) {
      await markStretchDone();
    } else if (i + 1 < n) {
      focusFrame(i + 1, {seek: true, scroll: true, autoplay: false});
    } else {
      // Last frame labeled → finish stretch and load next (no Done click).
      await markStretchDone();
    }
  } else {
    updateNavButtons();
  }
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
    stripStatus('Choose Show / Ad / Drop · dashed = suggested · double-tap Ad = cut');
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

const CHUNK_SIZE = 16;

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

let _stretchSaving = false;
async function markStretchDone() {
  const cur = currentEp();
  if (!cur || isDone(cur.s.session, cur.e.t0, cur.e.t1, cur.e) || _stretchSaving) return;
  _stretchSaving = true;
  const doneId = selected;
  ['btnDone', 'btnDoneHdr'].forEach(id => {
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
    pushRecentStretch(cur, doneId);
    if (DATA.chunk) {
      DATA.chunk.pending_total = Math.max(0, (DATA.chunk.pending_total || 1) - 1);
      DATA.chunk.done_total = (DATA.chunk.done_total || 0) + 1;
    }
    if (!queueItems().length) {
      await loadChunk();
      updateNavButtons();
      return;
    }
    selectNextInQueue();
    updateHdr();
    renderNav();
    renderMain();
  } catch (err) {
    updateNavButtons();
    alert('Done failed: ' + err.message);
  } finally {
    _stretchSaving = false;
  }
}

async function boot() {
  const goDone = () => markStretchDone();
  const d1 = document.getElementById('btnDone');
  const d2 = document.getElementById('btnDoneHdr');
  if (d1) d1.onclick = goDone;
  if (d2) d2.onclick = goDone;
  const prev = document.getElementById('btnPrevFrame');
  const next = document.getElementById('btnNextFrame');
  if (prev) prev.onclick = () => stepFrame(-1);
  if (next) next.onclick = () => stepFrame(1);
  const dash = document.getElementById('linkDash');
  if (dash) dash.href = apiUrl('/dashboard');
  const sched = document.getElementById('linkSched');
  if (sched) sched.href = apiUrl('/schedule');
  const lb = document.getElementById('lightbox');
  const lbClose = document.getElementById('lbClose');
  if (lbClose) lbClose.onclick = (ev) => { ev.stopPropagation(); closeLightbox(); };
  if (lb) {
    lb.onclick = (ev) => {
      if (ev.target === lb) closeLightbox();
    };
  }
  document.addEventListener('keydown', (ev) => {
    if (ev.key === 'Escape') closeLightbox();
  });
  await loadChunk();
}
boot();
</script>
</body>
</html>
"""


DASHBOARD_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover"/>
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
  .header-right { display: flex; align-items: center; gap: 10px; flex: 0 0 auto; flex-wrap: wrap; justify-content: flex-end; }
  .host-util {
    display: flex; align-items: stretch; gap: 6px; flex-wrap: wrap;
    font-variant-numeric: tabular-nums;
  }
  .host-util .hu {
    border: 1px solid var(--line); background: #fff; border-radius: 8px;
    padding: 5px 8px; min-width: 3.6rem; text-align: right;
  }
  .host-util .hu .k {
    margin: 0; color: var(--muted); font-size: 9px; font-weight: 700;
    text-transform: uppercase; letter-spacing: .04em;
  }
  .host-util .hu .v {
    margin: 0; font-size: 13px; font-weight: 700; line-height: 1.2; color: var(--ink);
  }
  .host-util .hu.hot { border-color: #fdba74; background: #fff7ed; }
  .host-util .hu.hot .v { color: var(--warn); }
  .verdict-wait {
    text-align: right; text-decoration: none; color: inherit;
    border: 1px solid var(--line); background: #fff; border-radius: 8px;
    padding: 6px 10px; min-width: 7.5rem;
  }
  .verdict-wait .k {
    margin: 0; color: var(--muted); font-size: 10px; font-weight: 700;
    text-transform: uppercase; letter-spacing: .04em;
  }
  .verdict-wait .v {
    margin: 0; font-size: 20px; font-weight: 700; font-variant-numeric: tabular-nums;
    color: var(--warn); line-height: 1.15;
  }
  .verdict-wait .h { margin: 0; color: var(--muted); font-size: 11px; }
  .verdict-wait.ok .v { color: var(--ok); }
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
  .ico {
    width: 14px; height: 14px; flex: 0 0 auto; display: inline-block; vertical-align: -2px;
  }
  .ico.lg { width: 18px; height: 18px; }
  .ico.sm { width: 9px; height: 9px; vertical-align: -1px; }
  .speed {
    display: grid; grid-template-columns: repeat(3, minmax(0,1fr)); gap: 8px;
  }
  .speed .sc {
    background: var(--card); border: 1px solid var(--line); border-radius: 10px; padding: 10px 12px;
  }
  .speed .sc.pic {
    grid-column: 1 / 3;
    grid-row: span 2;
    display: grid;
    grid-template-columns: auto minmax(0, 1fr);
    grid-template-rows: auto auto;
    gap: 6px 18px;
    align-items: end;
  }
  .speed .sc.pic > .k { grid-column: 1 / -1; }
  .speed .sc.pic > .v {
    grid-column: 1; align-self: end; margin-top: 0; padding-bottom: 10px;
    font-size: 26px;
  }
  .speed .sc.pic > .speed-chart {
    grid-column: 2;
    grid-row: 2;
    align-self: end;
    min-width: 0;
  }
  .speed .sc.bad { border-color: #fda4af; background: #fff1f2; }
  .speed .sc.warn { border-color: #fdba74; background: #fff7ed; }
  .speed .sc .k {
    color: var(--muted); font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: .04em;
    display: inline-flex; align-items: center; gap: 5px;
  }
  .speed .sc .v { margin-top: 4px; font-size: 22px; font-weight: 700; font-variant-numeric: tabular-nums; line-height: 1.1; }
  .speed-chart {
    background: transparent; border: 0; border-radius: 0; padding: 0;
    min-width: 0;
  }
  .speed-chart > svg { display: block; width: 100%; height: 52px; }
  .speed-chart .axis {
    display: flex; justify-content: space-between; margin-top: 1px;
    color: var(--muted); font-size: 9px; font-variant-numeric: tabular-nums;
  }
  .speed-chart.idle { opacity: .72; }
  @media (max-width: 560px) {
    .speed { grid-template-columns: 1fr 1fr; }
    .speed .sc.pic {
      grid-column: 1 / -1;
      grid-row: auto;
      grid-template-columns: auto minmax(0, 1fr);
    }
  }
  .hero-phase {
    display: inline-flex; align-items: center; gap: 8px;
  }
  .hero-phase .ico { width: 22px; height: 22px; color: var(--run); }
  .panel {
    background: var(--card); border: 1px solid var(--line); border-radius: 12px; padding: 12px 14px;
  }
  .panel h3 { margin: 0 0 8px; font-size: 13px; }
  .back-stats {
    display: grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap: 6px 14px;
    margin: 0 0 10px; font-size: 12px; line-height: 1.35;
  }
  .back-stats b { font-variant-numeric: tabular-nums; }
  .back-stats .muted { color: var(--muted); font-weight: 600; }
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
  .foot { margin: 6px 0 0; font-size: 11px; color: var(--muted); }
  .agree-lede {
    margin: 0 0 10px; font-size: 14px; line-height: 1.45; color: var(--ink); font-weight: 600;
  }
  .agree-lede span { font-weight: 400; color: var(--muted); }
  .agree-grid {
    display: grid; grid-template-columns: repeat(3, minmax(0,1fr)); gap: 8px;
    margin: 0 0 12px;
  }
  .agree-stat {
    border: 1px solid var(--line); border-radius: 8px; padding: 8px 10px; background: #f8fafc;
  }
  .agree-stat .k {
    margin: 0; font-size: 10px; font-weight: 700; text-transform: uppercase;
    letter-spacing: .04em; color: var(--muted);
  }
  .agree-stat .role {
    margin: 2px 0 6px; font-size: 11px; line-height: 1.3; color: var(--ink);
  }
  .agree-stat .meter {
    height: 8px; border-radius: 999px; background: #e8eef2; overflow: hidden;
  }
  .agree-stat .meter > i {
    display: block; height: 100%; border-radius: 999px; background: #64748b;
  }
  .agree-stat .meter.hot > i { background: #b45309; }
  .agree-stat .meter.cool > i { background: #0f766e; }
  .agree-stat .meter.dim > i { background: #94a3b8; }
  .agree-stat .v {
    margin: 6px 0 0; font-size: 18px; font-weight: 700; font-variant-numeric: tabular-nums;
  }
  .agree-stat .s { margin: 2px 0 0; font-size: 11px; color: var(--muted); line-height: 1.35; }
  .agree-block { margin: 0 0 12px; }
  .agree-block h4 {
    margin: 0 0 6px; font-size: 11px; font-weight: 700; text-transform: uppercase;
    letter-spacing: .04em; color: var(--muted);
  }
  .agree-rows { display: grid; gap: 6px; margin: 0; font-size: 12px; }
  .agree-rows .row {
    display: grid; grid-template-columns: 7.5rem 1fr auto; gap: 8px; align-items: center;
  }
  .agree-rows .bar {
    height: 8px; border-radius: 999px; background: #e8eef2; overflow: hidden; margin: 0;
  }
  .agree-rows .bar > i {
    display: block; height: 100%; border-radius: 999px; background: #334155;
  }
  .agree-rows .bar.good > i { background: #0f766e; }
  .agree-rows .bar.warn > i { background: #b45309; }
  .agree-rows .n {
    font-variant-numeric: tabular-nums; font-weight: 700; min-width: 3.2rem; text-align: right;
  }
  .agree-fight {
    display: grid; grid-template-columns: 1fr auto 1fr; gap: 8px; align-items: stretch;
    margin: 0 0 10px;
  }
  .agree-fight .side {
    border: 1px solid var(--line); border-radius: 8px; padding: 8px 10px; background: #fff;
  }
  .agree-fight .side.hot { background: #fff7ed; border-color: #fdba74; }
  .agree-fight .side.cool { background: #f0fdfa; border-color: #99f6e4; }
  .agree-fight .side .k { margin: 0; font-size: 10px; font-weight: 700; text-transform: uppercase; color: var(--muted); }
  .agree-fight .side .v { margin: 2px 0 0; font-size: 16px; font-weight: 700; }
  .agree-fight .side .s { margin: 2px 0 0; font-size: 11px; color: var(--muted); line-height: 1.35; }
  .agree-fight .mid {
    display: flex; flex-direction: column; align-items: center; justify-content: center;
    min-width: 4.5rem; text-align: center; font-size: 11px; color: var(--muted); font-weight: 600;
  }
  .agree-fight .mid b {
    display: block; font-size: 18px; color: var(--ink); font-variant-numeric: tabular-nums;
  }
  .agree-ask {
    margin: 0; padding: 8px 10px; border-radius: 8px; background: #f1f5f9;
    font-size: 12px; line-height: 1.45; color: var(--ink);
  }
  .agree-ask b { font-weight: 700; }
  .agree-ask ul { margin: 4px 0 0; padding-left: 1.1rem; }
  .agree-ask li { margin: 2px 0; }
  @media (max-width: 560px) {
    .agree-grid { grid-template-columns: 1fr; }
    .agree-fight { grid-template-columns: 1fr; }
    .agree-fight .mid { flex-direction: row; gap: 6px; min-width: 0; }
    .agree-rows .row { grid-template-columns: 1fr auto; }
    .agree-rows .bar { grid-column: 1 / -1; }
  }
  @media (min-width: 720px) {
    .back-stats { grid-template-columns: repeat(4, minmax(0,1fr)); }
    .hero { grid-template-columns: 1.4fr .8fr; align-items: center; }
    .hero-main { grid-column: 1; }
    .hero-eta { grid-column: 2; text-align: right; }
    .bar { grid-column: 1 / -1; }
    .meta { grid-column: 1 / -1; }
  }
  @media (max-width: 419px) {
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
  <div class="header-right">
    <div class="host-util" id="hostUtil" title="Live host utilization" aria-label="Host utilization">
      <div class="hu" id="huCpu"><p class="k">CPU</p><p class="v">—</p></div>
      <div class="hu" id="huRam"><p class="k">RAM</p><p class="v">—</p></div>
      <div class="hu" id="huGpu"><p class="k">GPU</p><p class="v">—</p></div>
      <div class="hu" id="huVram"><p class="k">VRAM</p><p class="v">—</p></div>
    </div>
    <a class="verdict-wait" id="verdictWait" href="/" title="Finished pic+txt+snd disagrees that need you">
      <p class="k">Verdict waiting</p>
      <p class="v" id="verdictWaitN">—</p>
      <p class="h" id="verdictWaitH">disagree · need you</p>
    </a>
    <a class="nav" id="linkTriage" href="/">Triage</a>
    <a class="nav" id="linkSchedDash" href="/schedule">Schedule</a>
  </div>
</header>
<main>
  <section class="hero idle" id="hero">
    <div class="hero-main">
      <p class="kicker" id="liveKicker">Now</p>
      <h2 id="liveBig">Checking…</h2>
    </div>
    <div class="hero-eta">
      <p class="kicker" id="liveEtaLabel">Left on this one</p>
      <div class="eta-big" id="liveEta">—</div>
      <p class="meta" id="liveEtaSub"></p>
    </div>
    <div class="bar"><i id="liveBar"></i></div>
    <p class="meta" id="liveMeta"></p>
  </section>

  <section class="speed" id="speedBoard" aria-label="Live speed">
    <div class="sc pic"><div class="k">Pictures</div><div class="v">—<span style="font-size:12px;color:var(--muted);font-weight:600"> /min</span></div></div>
    <div class="sc"><div class="k">Transcript</div><div class="v">—</div></div>
    <div class="sc"><div class="k">Sound</div><div class="v">—</div></div>
  </section>

  <section class="panel" id="agreePanel" aria-label="Three sensors compared">
    <h3>Do the three sensors agree?</h3>
    <p class="foot" id="agreeSub" style="margin-top:-4px;margin-bottom:8px">Scanning hops…</p>
    <p class="agree-lede" id="agreeLede" hidden></p>
    <div class="agree-grid" id="agreeCov"></div>
    <div class="agree-block">
      <h4>Where they fight</h4>
      <div class="agree-fight" id="agreeFight"></div>
    </div>
    <div class="agree-block">
      <h4>How often pairs match</h4>
      <div class="agree-rows" id="agreePairs"></div>
    </div>
    <div class="agree-ask" id="agreeAsk" hidden></div>
    <p class="foot" id="agreeFoot"></p>
  </section>

  <section class="panel">
    <h3>Backlog</h3>
    <div class="back-stats" id="backStats"></div>
    <div class="bar"><i id="funnelBar"></i></div>
    <div class="queue" id="queue" style="margin-top:10px"></div>
  </section>
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
function picRateChartHtml(hist, opt) {
  const o = opt || {};
  const active = !!o.active;
  const baseline = (o.baseline != null && Number.isFinite(Number(o.baseline))) ? Number(o.baseline) : 8.5;
  const keepS = Math.max(30, Number(o.keepS) || 120);
  const pts = (Array.isArray(hist) ? hist : [])
    .map(p => ({ age: Number(p.age_s), y: Number(p.per_min) }))
    .filter(p => Number.isFinite(p.age) && Number.isFinite(p.y) && p.y >= 0)
    .sort((a, b) => b.age - a.age); // oldest → newest for drawing left→right
  const live = (o.live != null && Number.isFinite(Number(o.live))) ? Number(o.live) : null;
  const W = 640, H = 52, L = 22, R = 4, T = 4, B = 4;
  const plotW = W - L - R, plotH = H - T - B;
  let svgInner = '';
  if (pts.length >= 2 && active) {
    const ys = pts.map(p => p.y).concat([baseline, live != null ? live : baseline]);
    let yMax = Math.max(20, ...ys) * 1.12;
    yMax = Math.ceil(yMax / 10) * 10;
    const xOf = (age) => L + plotW * (1 - Math.min(1, Math.max(0, age / keepS)));
    const yOf = (v) => T + plotH * (1 - Math.min(1, Math.max(0, v / yMax)));
    const baseY = yOf(baseline);
    const line = pts.map((p, i) => `${i ? 'L' : 'M'}${xOf(p.age).toFixed(1)},${yOf(p.y).toFixed(1)}`).join(' ');
    const area = `${line} L${xOf(pts[pts.length - 1].age).toFixed(1)},${(T + plotH).toFixed(1)} L${xOf(pts[0].age).toFixed(1)},${(T + plotH).toFixed(1)} Z`;
    svgInner = `
      <line x1="${L}" y1="${baseY.toFixed(1)}" x2="${W - R}" y2="${baseY.toFixed(1)}" stroke="#fdba74" stroke-width="1" stroke-dasharray="4 3"/>
      <text x="${L - 3}" y="${(baseY + 3).toFixed(1)}" text-anchor="end" fill="#b45309" font-size="8">${Math.round(baseline)}</text>
      <text x="${L - 3}" y="${(T + 7).toFixed(1)}" text-anchor="end" fill="#5a6b78" font-size="8">${Math.round(yMax)}</text>
      <path d="${area}" fill="rgba(3,105,161,.10)"/>
      <path d="${line}" fill="none" stroke="#0369a1" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>
      <circle cx="${xOf(pts[pts.length - 1].age).toFixed(1)}" cy="${yOf(pts[pts.length - 1].y).toFixed(1)}" r="2.4" fill="#0369a1"/>
    `;
  } else {
    svgInner = `
      <text x="${W / 2}" y="${H / 2 + 3}" text-anchor="middle" fill="#5a6b78" font-size="10">${
        active ? 'Collecting…' : '—'
      }</text>
    `;
  }
  const spanMin = Math.round(keepS / 60);
  return `<div class="speed-chart${active ? '' : ' idle'}" aria-label="Pictures per minute over time">
    <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img">${svgInner}</svg>
    <div class="axis"><span>−${spanMin}m</span><span>now</span></div>
  </div>`;
}
async function refresh() {
  const res = await fetch(apiUrl('/api/overnight'), { cache: 'no-store' });
  if (!res.ok) throw new Error('status ' + res.status);
  const d = await res.json();
  const o = d.overnight || {};
  const lock = d.label_lock || {};
  const live = d.live_job || {};
  const h = d.hierarchy || {};
  const funnel = h.funnel || {};
  const etas = d.etas || {};
  const cur = etas.current_session || {};
  const totEta = etas.total || {};
  const pri = etas.priority || {};
  const vq = d.verdict_queue || {};
  const verdictSec = (vq.pending_seconds != null) ? Number(vq.pending_seconds) : null;
  const verdictN = (vq.pending_approx != null) ? Number(vq.pending_approx) : null;

  document.getElementById('sub').textContent =
    `${d.updated_utc || '—'} · ${o.day_et || ''} ET`;
  const hu = d.host_util || {};
  const gpu = hu.gpu || {};
  function setHu(id, text, hot) {
    const el = document.getElementById(id);
    if (!el) return;
    const v = el.querySelector('.v');
    if (v) v.textContent = text;
    el.className = 'hu' + (hot ? ' hot' : '');
  }
  setHu('huCpu',
    (hu.cpu_pct != null && Number.isFinite(Number(hu.cpu_pct))) ? (Math.round(Number(hu.cpu_pct)) + '%') : '—',
    Number(hu.cpu_pct) >= 85);
  setHu('huRam',
    (hu.ram_used_gb != null && hu.ram_total_gb != null)
      ? (Number(hu.ram_used_gb).toFixed(1) + '/' + Number(hu.ram_total_gb).toFixed(0) + 'G')
      : ((hu.ram_pct != null) ? (Math.round(Number(hu.ram_pct)) + '%') : '—'),
    Number(hu.ram_pct) >= 90);
  setHu('huGpu',
    (gpu.ok && gpu.util_pct != null) ? (Math.round(Number(gpu.util_pct)) + '%') : '—',
    Number(gpu.util_pct) >= 95 || Number(gpu.temp_c) >= 85);
  setHu('huVram',
    (gpu.ok && gpu.vram_used_gb != null && gpu.vram_total_gb != null)
      ? (Number(gpu.vram_used_gb).toFixed(1) + '/' + Number(gpu.vram_total_gb).toFixed(1) + 'G')
      : '—',
    Number(gpu.vram_pct) >= 92);
  const huRoot = document.getElementById('hostUtil');
  if (huRoot) huRoot.title = hu.plain || 'Live host utilization';
  const vw = document.getElementById('verdictWait');
  const vn = document.getElementById('verdictWaitN');
  const vh = document.getElementById('verdictWaitH');
  // Primary: seconds of finished pic+txt+snd disagree that still need you.
  if (vn) {
    vn.textContent = (verdictSec != null && Number.isFinite(verdictSec))
      ? (Math.round(verdictSec) + 's')
      : '—';
  }
  if (vh) {
    const bits = [];
    if (verdictN != null && Number.isFinite(verdictN)) bits.push(Math.round(verdictN) + ' clips');
    const st = (vq.stretches != null) ? Number(vq.stretches) : null;
    if (st != null && Number.isFinite(st)) bits.push(Math.round(st) + ' stretches');
    bits.push('tape · need you');
    vh.textContent = bits.join(' · ');
  }
  if (vw) vw.className = 'verdict-wait' + ((verdictN === 0 || verdictSec === 0) ? ' ok' : '');

  const active = !!live.active;
  const hero = document.getElementById('hero');
  hero.className = active ? 'hero live' : 'hero';
  const phase = phaseName(live.phase);
  const livePhase = String(live.phase || '');
  const stalled = !!(live.stalled || (etas.pace || {}).stalled);
  const speed = etas.speed || {};
  const picSp = speed.pictures || {};
  const sndSp = speed.sound || {};
  if (active) {
    const throughRaw = live.progress_plain || (cur.progress_plain) || phase;
    const through = String(throughRaw).replace(/^(pictures|transcript|sound|merge|auto-lock)\s*·\s*/i, '');
    document.getElementById('liveKicker').textContent = stalled
      ? ('Stuck · ' + phase)
      : ('Working · ' + phase);
    document.getElementById('liveEtaLabel').textContent = 'Left';
    document.getElementById('liveBig').innerHTML =
      `<span class="hero-phase">${ico(phaseIco(live.phase), 'lg')}<span>${stalled ? 'STUCK · ' : ''}${shortSess(live.tape || live.session)} · ${through}</span></span>`;
    document.getElementById('liveBar').style.width = Math.max(0, Math.min(100, Number(live.pct) || 0)) + '%';
    document.getElementById('liveEta').textContent = stalled ? '—' : fmtDur(live.eta_remaining_s ?? cur.remaining_s);
    document.getElementById('liveEtaSub').textContent = stalled
      ? ('no heartbeat ' + fmtDur(live.job_age_s || (etas.pace || {}).job_age_s))
      : (live.eta_finish_et || cur.finish_et ? ('~' + (live.eta_finish_et || cur.finish_et)) : '');
    const picturing = livePhase === 'vision';
    const rate = (!picturing || picSp.stalled || stalled)
      ? null
      : (picSp.live_per_min != null
          ? picSp.live_per_min
          : ((etas.pace || {}).hops_per_min != null ? (etas.pace || {}).hops_per_min : null));
    const workersNHero = live.workers != null
      ? live.workers
      : ((lock.meta || {}).workers != null ? (lock.meta || {}).workers : null);
    const bits = picturing ? [
      (stalled || picSp.stalled) ? '0/min' : (rate != null ? (Math.round(Number(rate)) + '/min') : null),
      (workersNHero != null) ? (Number(workersNHero) + ' workers') : null,
      live.pct != null ? (fmt(live.pct) + '%') : null,
    ].filter(Boolean) : [
      phase === 'sound' || livePhase === 'acoustic' ? 'sound' : phase,
    ].filter(Boolean);
    document.getElementById('liveMeta').textContent = bits.join(' · ');
    if (stalled) hero.className = 'hero';
  } else {
    document.getElementById('liveKicker').textContent = 'Idle';
    document.getElementById('liveEtaLabel').textContent = 'Review';
    document.getElementById('liveBig').innerHTML =
      `<span class="hero-phase">${ico('wait', 'lg')}<span>${live.note || 'Waiting'}</span></span>`;
    document.getElementById('liveBar').style.width = '0%';
    document.getElementById('liveEta').textContent = fmtDur(pri.remaining_s);
    document.getElementById('liveEtaSub').textContent = '';
    document.getElementById('liveMeta').textContent = '';
  }

  const picturingNow = active && livePhase === 'vision';
  const soundingNow = active && livePhase === 'acoustic';
  const picVs = picSp.vs_baseline;
  const picCls = picturingNow
    ? ((picSp.stalled || stalled) ? 'bad' : (picVs != null && picVs < 0.7 ? 'warn' : ''))
    : '';
  const rateShown = !picturingNow
    ? null
    : ((picSp.stalled || stalled)
      ? 0
      : (picSp.live_per_min != null
          ? picSp.live_per_min
          : ((etas.pace || {}).hops_per_min != null ? (etas.pace || {}).hops_per_min : null)));
  const soundRate = soundingNow
    ? ((sndSp.stalled || stalled) ? 0 : sndSp.live_per_min)
    : null;
  const workersN = picturingNow
    ? (live.workers != null
        ? live.workers
        : ((lock.meta || {}).workers != null ? (lock.meta || {}).workers : null))
    : null;
  const workersPlain = workersN != null
    ? (Number(workersN) + ' worker' + (Number(workersN) === 1 ? '' : 's'))
    : null;
  const soundPct = soundingNow && (sndSp.pct != null || live.pct != null)
    ? (sndSp.pct != null ? sndSp.pct : live.pct)
    : null;
  const hist = Array.isArray(picSp.history) ? picSp.history : [];
  if (picturingNow && rateShown != null && Number.isFinite(Number(rateShown))) {
    const last = hist.length ? hist[hist.length - 1] : null;
    if (!last || Math.abs(Number(last.per_min) - Number(rateShown)) > 0.5) {
      hist.push({ age_s: 0, per_min: Number(rateShown) });
    } else {
      last.age_s = 0;
      last.per_min = Number(rateShown);
    }
  }
  document.getElementById('speedBoard').innerHTML = `
    <div class="sc pic ${picCls}"><div class="k">${ico('pic', 'sm')} Pictures${
      workersPlain ? (' · ' + workersPlain) : ''
    }</div><div class="v">${
      rateShown != null ? Math.round(Number(rateShown)) : '—'
    }<span style="font-size:13px;color:var(--muted);font-weight:600"> /min</span></div>${
      picRateChartHtml(hist, {
        live: rateShown,
        baseline: picSp.baseline_per_min,
        active: picturingNow,
        keepS: picSp.history_keep_s || 120,
        stalled: !!(picSp.stalled || stalled),
      })
    }</div>
    <div class="sc"><div class="k">${ico('txt', 'sm')} Transcript</div><div class="v">${
      picturingNow ? 'on' : '—'
    }</div></div>
    <div class="sc"><div class="k">${ico('snd', 'sm')} Sound</div><div class="v">${
      soundRate != null
        ? (Math.round(Number(soundRate)) + '<span style="font-size:13px;color:var(--muted);font-weight:600"> /min</span>')
        : '—'
    }</div></div>
  `;

  const ag = d.channel_agreement || {};
  const cov = ag.coverage || {};
  const pw = ag.pairwise || {};
  const trio = ag.trio || {};
  const odd = (trio.odd_one_out || {});
  const vs = ag.vision_vs_sound || {};
  const locks = ag.auto_lock || {};
  const coals = locks.coalitions || {};
  const sndPicCoal = coals['acoustic+vision'] || {};
  const all3Coal = coals['acoustic+asr+vision'] || {};
  function pctNum(x) {
    const n = Number(x);
    return Number.isFinite(n) ? n : null;
  }
  function pctTxt(x) {
    const n = pctNum(x);
    return n != null ? (n + '%') : '—';
  }
  function barWidth(x) {
    const n = pctNum(x);
    return n == null ? 0 : Math.max(0, Math.min(100, n));
  }
  const sndMute = pctNum((cov.acoustic || {}).mute_pct);
  const picMute = pctNum((cov.vision || {}).mute_pct);
  const clashN = Number(vs.pic_mute_snd_play || 0);
  const agreeSub = document.getElementById('agreeSub');
  if (agreeSub) {
    agreeSub.textContent = ag.ok
      ? (`${fmt(ag.sessions)} tapes · ${fmt(ag.hops_total)} moments · only counting clear mute/play votes`)
      : (ag.error || 'Agreement unavailable');
  }
  const agreeLede = document.getElementById('agreeLede');
  if (agreeLede) {
    if (ag.ok) {
      agreeLede.hidden = false;
      agreeLede.innerHTML =
        `Pictures call “ad/mute” far more often than sound ` +
        `(${pctTxt(picMute)} vs ${pctTxt(sndMute)}). ` +
        `<span>Main fight: picture says ad while sound says keep playing ` +
        `(${fmt(clashN)} moments).</span>`;
    } else {
      agreeLede.hidden = true;
      agreeLede.textContent = '';
    }
  }
  const agreeCov = document.getElementById('agreeCov');
  if (agreeCov && ag.ok) {
    const snd = cov.acoustic || {};
    const pic = cov.vision || {};
    const txt = cov.asr || {};
    agreeCov.innerHTML = `
      <div class="agree-stat">
        <p class="k">${ico('snd', 'sm')} Sound</p>
        <p class="role">Heard mute vs play</p>
        <div class="meter cool" title="How often sound votes mute"><i style="width:${barWidth(snd.mute_pct)}%"></i></div>
        <p class="v">${pctTxt(snd.mute_pct)} mute</p>
        <p class="s">Votes on ${pctTxt(snd.pct)} of moments · usually keeps the game on</p>
      </div>
      <div class="agree-stat">
        <p class="k">${ico('pic', 'sm')} Pictures</p>
        <p class="role">Looks like ad vs show</p>
        <div class="meter hot" title="How often pictures vote mute"><i style="width:${barWidth(pic.mute_pct)}%"></i></div>
        <p class="v">${pctTxt(pic.mute_pct)} mute</p>
        <p class="s">Votes on ${pctTxt(pic.pct)} of moments · over-calls ads</p>
      </div>
      <div class="agree-stat">
        <p class="k">${ico('txt', 'sm')} Transcript</p>
        <p class="role">Words when available</p>
        <div class="meter dim" title="How often transcript votes at all"><i style="width:${barWidth(txt.pct)}%"></i></div>
        <p class="v">${pctTxt(txt.pct)} voting</p>
        <p class="s">Mostly empty/uncertain · weak third vote</p>
      </div>
    `;
  }
  const agreeFight = document.getElementById('agreeFight');
  if (agreeFight && ag.ok) {
    const bothPlay = Number(vs.pic_play_snd_play || 0);
    const bothMute = Number(vs.pic_mute_snd_mute || 0);
    const sndMutePicPlay = Number(vs.pic_play_snd_mute || 0);
    agreeFight.innerHTML = `
      <div class="side hot">
        <p class="k">${ico('pic', 'sm')} Pictures</p>
        <p class="v">“Ad — mute”</p>
        <p class="s">Mute vote ${pctTxt(picMute)}</p>
      </div>
      <div class="mid">vs<br/><b>${fmt(clashN)}</b>clashes</div>
      <div class="side cool">
        <p class="k">${ico('snd', 'sm')} Sound</p>
        <p class="v">“Play on”</p>
        <p class="s">Mute vote only ${pctTxt(sndMute)}</p>
      </div>
      <p class="foot" style="grid-column:1/-1;margin:0">
        Also: both play ${fmt(bothPlay)} · both mute ${fmt(bothMute)} · sound mutes while picture plays ${fmt(sndMutePicPlay)}.
        When two of three disagree, pictures are usually the odd one out (${pctTxt((odd.vision||{}).pct)}).
        Auto-locks mostly come from sound+pictures together (${pctTxt(sndPicCoal.pct)}), not all three (${pctTxt(all3Coal.pct)}).
      </p>
    `;
  }
  const agreePairs = document.getElementById('agreePairs');
  if (agreePairs && ag.ok) {
    const rows = [
      ['Sound + words', pw.sound_transcript, 'good'],
      ['Pictures + words', pw.pictures_transcript, 'warn'],
      ['Sound + pictures', pw.sound_pictures, 'warn'],
    ];
    agreePairs.innerHTML = rows.map(([lab, cell, kind]) => {
      const c = cell || {};
      return `<div class="row"><span>${lab}</span>
        <div class="bar ${kind}"><i style="width:${barWidth(c.agree_pct)}%"></i></div>
        <span class="n">${pctTxt(c.agree_pct)}</span></div>`;
    }).join('');
  }
  const agreeAsk = document.getElementById('agreeAsk');
  if (agreeAsk) {
    if (ag.ok) {
      agreeAsk.hidden = false;
      agreeAsk.innerHTML =
        `<b>Better questions for the team</b>
         <ul>
           <li>When pictures say ad and sound says play, who is right on the tape?</li>
           <li>Should auto-mute trust sound more when vision is ad-happy?</li>
           <li>Is transcript useful yet, or still too often blank to cast a vote?</li>
         </ul>`;
    } else {
      agreeAsk.hidden = true;
      agreeAsk.textContent = '';
    }
  }
  const agreeFoot = document.getElementById('agreeFoot');
  if (agreeFoot) {
    agreeFoot.textContent = ag.ok
      ? (`Sample: ${fmt(ag.sessions)} tapes / ${fmt(ag.hops_total)} moments · ` +
         `sound votes ${pctTxt((cov.acoustic||{}).pct)} · pictures ${pctTxt((cov.vision||{}).pct)} · ` +
         `words ${pctTxt((cov.asr||{}).pct)}`)
      : '';
  }

  const wallPer = (totEta.wall_per_content != null)
    ? totEta.wall_per_content
    : ((etas.pace || {}).wall_per_content);
  const contentLeft = totEta.content_left_h != null ? totEta.content_left_h : totEta.audio_left_h;
  document.getElementById('backStats').innerHTML = `
    <div><span class="muted">Done</span><br><b>${fmt(funnel.finished)}/${fmt(funnel.prepared)}</b> · ${fmt(funnel.pct_finished)}%</div>
    <div><span class="muted">In line</span><br><b>${fmt(funnel.waiting_for_pictures)}</b> need pictures</div>
    <div><span class="muted">Needs review</span><br><b>${fmtDur(pri.remaining_s)}</b>${pri.finish_et ? (' · ~' + pri.finish_et) : ''}</div>
    <div><span class="muted">All left</span><br><b>${fmtDur(totEta.remaining_s)}</b>${
      contentLeft != null
        ? (' · ' + fmt(contentLeft) + 'h show' + (wallPer != null ? (' · ~' + Number(wallPer).toFixed(1) + '×') : ''))
        : ''
    }</div>
  `;
  document.getElementById('funnelBar').style.width = Math.max(0, Math.min(100, Number(funnel.pct_finished)||0)) + '%';

  const queueRows = (h.queue || [])
    .filter(r => r.status !== 'done')
    .slice(0, 12);
  document.getElementById('queue').innerHTML = queueRows.map(row => {
    const ch = row.channels || {};
    const running = row.status === 'running';
    const nextKind = ({vision:'pic', asr:'txt', acoustic:'snd', combine:'stack', consensus:'lock'})[row.next] || 'run';
    const throughRaw = row.progress_plain
      || (running ? (live.progress_plain || '') : '');
    const through = String(throughRaw).replace(/^(pictures|transcript|sound|merge|auto-lock)\s*·\s*/i, '');
    return `<div class="qrow ${running ? 'run' : ''}">
      <div>
        <div class="name">${shortSess(row.session)}</div>
        <div class="marks">
          ${mark('pic', !!ch.vision, running && livePhase==='vision')}
          ${mark('txt', !!ch.asr, running && livePhase==='vision')}
          ${mark('snd', !!ch.acoustic, running && livePhase==='acoustic')}
          ${mark('lock', !!ch.gold, running && (livePhase==='consensus'||livePhase==='combine'))}
        </div>
        <div class="foot">${through || 'waiting'}</div>
      </div>
      <div class="right">
        ${pill(running ? 'now' : 'queued', running ? 'run' : 'warn')}
        <div class="foot">${row.eta_s != null ? fmtDur(row.eta_s) : ''}</div>
      </div>
    </div>`;
  }).join('') || '<p class="meta">Queue clear</p>';
}
document.getElementById('linkTriage').href = apiUrl('/');
const linkSchedDash = document.getElementById('linkSchedDash');
if (linkSchedDash) linkSchedDash.href = apiUrl('/schedule');
const vwLink = document.getElementById('verdictWait');
if (vwLink) vwLink.href = apiUrl('/');
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
        if not getattr(self, "_head", False):
            self.wfile.write(body)

    def do_HEAD(self) -> None:  # noqa: N802
        self._head = True
        try:
            self.do_GET()
        finally:
            self._head = False

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        if path in {"/", "/index.html"}:
            self._send(200, HTML.encode("utf-8"), "text/html; charset=utf-8")
            return
        if path in {"/dashboard", "/dashboard.html", "/overnight"}:
            self._send(200, DASHBOARD_HTML.encode("utf-8"), "text/html; charset=utf-8")
            return
        if path in {"/schedule", "/schedule.html", "/recording-schedule"}:
            try:
                from .recording_schedule import (
                    board_html_path,
                    publish_recording_schedule,
                )

                board = publish_recording_schedule(rebuild_plan=False)
                html_path = board_html_path()
                html = (
                    html_path.read_text(encoding="utf-8")
                    if html_path.is_file()
                    else ""
                )
                if not html:
                    from .recording_schedule import _render_html

                    html = _render_html(board)
            except Exception as exc:  # noqa: BLE001
                html = f"<pre>schedule error: {exc}</pre>"
            self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
            return
        if path == "/api/schedule":
            try:
                from .recording_schedule import publish_recording_schedule

                blob = publish_recording_schedule(rebuild_plan=False)
            except Exception as exc:  # noqa: BLE001
                blob = {"ok": False, "error": str(exc)}
            self._send(200, json.dumps(blob, default=str).encode("utf-8"), "application/json")
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

        if parsed.path == "/api/schedule":
            try:
                from .recording_schedule import apply_schedule_edit

                out = apply_schedule_edit(body if isinstance(body, dict) else {})
                code = 200 if out.get("ok") else 400
                self._send(
                    code,
                    json.dumps(out, default=str).encode("utf-8"),
                    "application/json",
                )
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
    p.add_argument(
        "--auto-drop-guides",
        action="store_true",
        help="One-shot: drop guide/emulator/lag-caption junk clips, then exit",
    )
    p.add_argument(
        "--auto-drop-frozen",
        action="store_true",
        help="One-shot: drop lag-frozen still runs (same image bytes repeated), then exit",
    )
    p.add_argument("--dry-run", action="store_true", help="With auto-drop flags, do not write")
    args = p.parse_args(argv)
    if args.auto_drop_guides:
        print(json.dumps(auto_drop_guides_from_vision(dry_run=bool(args.dry_run)), indent=2), flush=True)
        return 0
    if args.auto_drop_frozen:
        print(json.dumps(auto_drop_frozen_stills(dry_run=bool(args.dry_run)), indent=2), flush=True)
        return 0
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
