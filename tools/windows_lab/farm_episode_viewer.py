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
  .btn-done {
    border: 1px solid #0f766e; background: #0f766e; color: #fff;
    border-radius: 6px; padding: 6px 12px; cursor: pointer;
    font: inherit; font-weight: 700; font-size: 12px; white-space: nowrap;
  }
  .btn-done:hover { background: #0d9488; border-color: #0d9488; }
  .btn-done:disabled { opacity: 0.45; cursor: default; }
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
  .layout { display: grid; grid-template-columns: 260px 1fr; min-height: calc(100vh - 52px); }
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
    grid-template-columns: 200px 220px 112px;
    gap: 0;
    align-items: stretch;
    width: max-content;
    max-width: 100%;
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
    display: flex; align-items: stretch; justify-content: stretch;
    padding: 8px;
    border-left: 1px solid var(--line);
    background: #eef3f6;
  }
  .signals {
    display: grid;
    grid-template-columns: 52px 1fr;
    gap: 5px 8px;
    align-items: center;
  }
  .sig-lab {
    font-size: 11px; font-weight: 700; color: var(--muted);
    text-transform: uppercase; letter-spacing: .04em;
  }
  .mark {
    display: inline-block; font-weight: 700; font-size: 13px;
    padding: 3px 8px; border-radius: 5px; line-height: 1.2;
  }
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
  .youbtn {
    cursor: pointer;
    width: 100%;
    height: 100%;
    min-height: 96px;
    border: 2px solid #8aa0b0;
    border-radius: 8px;
    font: inherit;
    font-weight: 800;
    font-size: 18px;
    letter-spacing: 0.02em;
    text-transform: uppercase;
    display: flex; flex-direction: column; align-items: center; justify-content: center;
  }
  .youbtn.ad { background: #ffedd5; color: var(--ad); border-color: #c2410c; }
  .youbtn.show { background: #ccfbf1; color: var(--show); border-color: #0f766e; }
  .youbtn.unk { background: #e5e7eb; color: #4b5563; }
  .youbtn.prefill { border-style: dashed; }
  .youbtn:hover { filter: brightness(0.97); border-style: solid; }
  .youbtn .sub {
    display: block; font-size: 11px; font-weight: 700; letter-spacing: 0.04em;
    text-transform: uppercase; opacity: 0.7; margin-top: 4px;
  }
  .card.cut-start { outline: 2px solid #1d4ed8; }
  .nav-verdict {
    margin-top: 6px; font-size: 11px; font-weight: 700; color: #0f766e;
  }
  .nav-verdict.pending { color: #9a3412; }
  .empty { color: var(--muted); padding: 40px; }
  @media (max-width: 960px) {
    header { flex-direction: column; gap: 6px; }
    header .right { width: 100%; justify-content: space-between; }
    .legend { max-width: 100%; justify-content: flex-start; }
    .layout { grid-template-columns: 1fr; }
    nav { display: flex; gap: 8px; overflow-x: auto; }
    nav button { min-width: 200px; }
    .card { grid-template-columns: 160px 1fr 96px; width: 100%; }
    .card img, .card .nostill { width: 160px; height: 96px; }
  }
</style>
<link rel="preconnect" href="https://fonts.googleapis.com"/>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;600;700&display=swap" rel="stylesheet"/>
</head>
<body>
<header>
  <div class="titles">
    <h1>Episode triage</h1>
    <p class="sub" id="hdr">Loading…</p>
  </div>
  <div class="right">
    <div class="legend">
      <span><span class="swatch" style="background:#ffedd5"></span><b>Ad</b></span>
      <span><span class="swatch" style="background:#ccfbf1"></span><b>Show</b></span>
      <span><span class="swatch" style="background:#fee2e2"></span><b>Muted</b></span>
      <span><span class="swatch" style="background:#dbeafe"></span><b>Playing</b></span>
      <span><span class="swatch" style="background:#fef08a"></span><b>Disagree</b></span>
    </div>
    <button type="button" class="btn-done" id="btnDone" title="Confirm You labels and remove this stretch from the queue">Done</button>
  </div>
</header>
<div class="layout">
  <nav id="nav"></nav>
  <main id="main"><div class="empty">Pick a stretch on the left</div></main>
</div>
<script>
/** When served under ohush.co/verdict (or any /verdict mount), prefix API paths. */
const BASE = (location.pathname === '/verdict' || location.pathname.startsWith('/verdict/'))
  ? '/verdict' : '';
function apiUrl(path) {
  if (!path) return BASE || '/';
  return BASE + (path.startsWith('/') ? path : '/' + path);
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
  if (v === 'mute') return {cls:'ad', text:'mute', prefill: !!prefill};
  if (v === 'keep') return {cls:'show', text:'keep', prefill: !!prefill};
  return {cls:'unk', text:'—', prefill: false};
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
  updateDoneButton();
}

function updateDoneButton() {
  const btn = document.getElementById('btnDone');
  if (!btn) return;
  const cur = currentEp();
  btn.disabled = !cur || isDone(cur.s.session, cur.e.t0, cur.e.t1, cur.e);
  btn.textContent = btn.disabled ? 'Done' : 'Done';
}

function renderMain() {
  const main = document.getElementById('main');
  if (!selected) { main.innerHTML = '<div class="empty">Pick a stretch on the left</div>'; return; }
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
    const H = humanLook(hd.value, {prefill: hd.prefill});
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
          <div class="sig-lab">Picture</div><div><span class="mark ${V.cls}">${V.text}</span></div>
          <div class="sig-lab">Words</div><div><span class="mark ${A.cls}">${A.text}</span></div>
          <div class="sig-lab">Muter</div><div><span class="mark ${M.cls}">${M.text}</span></div>
          <div class="sig-lab">Gold</div><div><span class="mark ${G.cls}">${G.text.replace('Gold: ','')}</span></div>
        </div>
        <div>
          <div class="pbar" title="Muter ad confidence ${pct}%"><span style="width:${pct}%"></span></div>
          <div class="pbar-lab">Muter ad score ${pct}%</div>
        </div>
      </div>
      <div class="you-col">
        <button type="button" class="youbtn ${H.cls} ${H.prefill?'prefill':''}" data-you="${i}" title="Click: flip keep ↔ mute. Double-click: ad starts here.">
          ${H.text || '—'}<span class="sub">You</span>
        </button>
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
    <p class="hero-do"><b>Suggested:</b> ${doText}. ${e.action?.detail || ''}</p>
    <div class="listen">
      <audio id="epAudio" controls preload="auto" src="${audioUrl}"></audio>
      <div class="now" id="audioNow">Take clock: ${Number(e.t0).toFixed(1)}s</div>
    </div>
    <div class="strip-wrap">
      <div class="strip-head">
        <p class="strip-label">${cutT != null ? 'Your cut @ ' + cutT + 's' : 'Click You to flip · double-click You = ad starts here'}</p>
        <button type="button" class="strip-clear" id="btnClearHuman" title="Clear your marks on this stretch">Clear</button>
      </div>
      <div class="strip" id="strip">${cards}</div>
    </div>
  `;
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
      if (ev.target && ev.target.closest && ev.target.closest('[data-you]')) return;
      selectFrame(Number(card.dataset.i), {seek: true, autoplay: false, scroll: false});
    };
  });
  let youClickTimer = null;
  main.querySelectorAll('[data-you]').forEach(btn => {
    btn.onclick = (ev) => {
      ev.stopPropagation();
      const i = Number(btn.dataset.you);
      // No seek on You flip — avoids scroll jump from audio seeked sync
      selectFrame(i, {seek: false, autoplay: false, scroll: false});
      if (youClickTimer) clearTimeout(youClickTimer);
      youClickTimer = setTimeout(() => { youClickTimer = null; cycleHuman(i); }, 220);
    };
    btn.ondblclick = (ev) => {
      ev.stopPropagation();
      ev.preventDefault();
      if (youClickTimer) { clearTimeout(youClickTimer); youClickTimer = null; }
      const i = Number(btn.dataset.you);
      selectFrame(i, {seek: false, autoplay: false, scroll: false});
      saveCutFromSelected();
    };
  });
  selectFrame(selectedFrame || 0, {seek: false, scroll: false});
}

function paintYouChips(session, frames) {
  frames.forEach((f, i) => {
    const btn = document.querySelector(`[data-you="${i}"]`);
    if (!btn) return;
    const hd = humanDisplay(session, f);
    const H = humanLook(hd.value, {prefill: hd.prefill});
    btn.className = `youbtn ${H.cls} ${H.prefill ? 'prefill' : ''}`;
    btn.innerHTML = `${H.text || '—'}<span class="sub">You</span>`;
  });
}

async function cycleHuman(i) {
  const cur = currentEp();
  if (!cur) return;
  const f = cur.e.frames[i];
  if (!f) return;
  const hd = humanDisplay(cur.s.session, f);
  // One click: flip keep ↔ mute (prefill or saved)
  const next = hd.value === 'mute' ? 'keep' : 'mute';
  setHumanLocal(cur.s.session, f.t, next);
  f.human = next;
  paintYouChips(cur.s.session, cur.e.frames);
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
    paintYouChips(cur.s.session, cur.e.frames);
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
    paintYouChips(cur.s.session, cur.e.frames);
    document.querySelectorAll('.card').forEach(c => c.classList.remove('cut-start'));
    stripStatus('You = gold (dashed) · click flip · double-click = ad starts here');
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
    `${nLeft} in this chunk · ${pending} left overall · ${nDone}/${total} done · You autosaves`;
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
  const btn = document.getElementById('btnDone');
  if (btn) { btn.disabled = true; btn.textContent = 'Saving…'; }
  // Materialize You (incl. gold prefill) so You is the saved source of truth
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
    if (!res.ok || !body.ok) throw new Error(body.error || 'done failed');
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
    if (btn) { btn.disabled = false; btn.textContent = 'Done'; }
    alert('Done failed: ' + err.message);
  }
}

async function boot() {
  document.getElementById('btnDone').onclick = () => markStretchDone();
  await loadChunk();
}
boot();
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
