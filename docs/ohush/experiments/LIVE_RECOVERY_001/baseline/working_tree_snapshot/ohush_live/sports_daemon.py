"""Record the original broadcast and gate only the speakers.

Detector work runs off the audio callback. A separate uploader process
receives closed chunks only. Neither is allowed to stop the recording.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import queue
import re
import select
import subprocess
import sys
import termios
import threading
import time
import tty
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import numpy as np
import sounddevice as sd
from scipy.signal import resample_poly

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))


def _brand_logo() -> str:
    svg = (REPO / "brand" / "OHush_Vector_Brand_Kit" / "OHush_Horizontal_white.svg").read_text(encoding="utf-8")
    svg = svg.split("?>", 1)[-1].strip()
    return svg.replace("<svg ", '<svg class="brand-logo" ', 1)

from live_audio import LiveControlError, query_audio_devices, resolve_live_device  # noqa: E402
from ohush_live.chunk_uploader import PROJECT  # noqa: E402
from ohush_live.chunks import ChunkWriter  # noqa: E402
from ohush_live.daemon import _pump, _spawn, _write_pcm  # noqa: E402
from ohush_live.gate import ListenerGate  # noqa: E402
from ohush_live.sounds import make_beds, make_earcon  # noqa: E402
from ohush_live.policy import BOOTH_HOLD_S  # noqa: E402
from ohush_live.sports import (  # noqa: E402
    CHUNK_MINUTES,
    PRODUCT,
    AutoLatch,
    ReturnHint,
    decision_row,
    REPLACEMENTS,
    override_row,
    votes,
)
from ohush_live.state import Machine  # noqa: E402

RATE = 48000
CHANNELS = 2
HOST = "127.0.0.1"
PORT = 8770
ACTIVE_PATH = REPO / "ohush_live" / "sessions" / ".active_desk.json"
BOOTH_PATH = REPO / "ohush_live" / "sessions" / ".booth.json"


def _load_booth_ids() -> list[str]:
    """Announcer crew remembered across restarts (Al, color, etc.)."""
    try:
        raw = json.loads(BOOTH_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(raw, dict):
        return []
    ids = raw.get("ids")
    if isinstance(ids, list) and ids:
        return [str(x) for x in ids][:8]
    protos = raw.get("protos")
    if isinstance(protos, dict) and protos:
        return [str(x) for x in protos.keys()][:8]
    return []


def _read_active() -> dict | None:
    try:
        raw = json.loads(ACTIVE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


def _write_active(payload: dict) -> None:
    ACTIVE_PATH.parent.mkdir(parents=True, exist_ok=True)
    ACTIVE_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _mark_active_stopped(active: dict | None = None) -> None:
    row = dict(active or _read_active() or {})
    if not row:
        return
    row["recording"] = False
    _write_active(row)


def _next_chunk_number(folder: Path) -> int:
    highest = -1
    for path in folder.glob("audio_*.wav"):
        try:
            highest = max(highest, int(path.stem.split("_")[1]))
        except (IndexError, ValueError):
            continue
    return highest + 1


class SportsSession:
    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.machine = Machine()
        self.latch = AutoLatch()
        self.hint = ReturnHint()
        self.families: dict[str, dict | None] = {"speaker": None, "audio": None, "semantic": None}
        self.samples = 0
        self._speaker_hold_until = 0.0
        self._lock = threading.Lock()
        folder.mkdir(parents=True, exist_ok=True)
        self.decisions = (folder / "decisions.jsonl").open("a", encoding="utf-8")
        self.overrides = (folder / "overrides.jsonl").open("a", encoding="utf-8")
        self.ratings = (folder / "ratings.jsonl").open("a", encoding="utf-8")
        self.labels = (folder / "labels.jsonl").open("a", encoding="utf-8")
        # Vote / lag / near-miss trail so ad in-out flapping is diagnosable after the fact.
        self.track = (folder / "track.jsonl").open("a", encoding="utf-8")
        self.events: list[dict] = []
        self.levels: list[dict] = []
        self._last_track_t = -1.0
        self.live = {"recording": False, "input_name": "", "output_name": "", "error": "", "open_chunk": ""}
        self._booth_hold_until = 0.0
        self._booth_ids: list[str] = _load_booth_ids()
        self.meta = {
            "product": PRODUCT,
            "scientific_authority": False,
            "allowed_to_change_exp001_005": False,
            "dataset_role": "live_dev",
            "show": "",
            "service": "",
            "content": "sports",
            "temporal_mode": "live",
            "delivery": "tv-optical",
            "ad_insertion": "unknown",
            "input_path": "tv_optical_pcm",
            "chunk_minutes": CHUNK_MINUTES,
        }
        prior = folder / "session.json"
        if prior.is_file():
            try:
                saved = json.loads(prior.read_text(encoding="utf-8"))
                if isinstance(saved, dict):
                    for key in ("show", "service", "content"):
                        if saved.get(key):
                            self.meta[key] = saved[key]
            except (OSError, json.JSONDecodeError):
                pass
        self._write_meta()

    def _write_meta(self) -> None:
        (self.folder / "session.json").write_text(json.dumps(self.meta, indent=2) + "\n", encoding="utf-8")

    def configure(self, show: str, service: str, content: str) -> None:
        if show.strip():
            self.meta["show"] = show.strip()[:160]
        if service.strip():
            self.meta["service"] = service.strip()[:80]
        if content.strip():
            self.meta["content"] = content.strip()[:40]
        self._write_meta()

    def clock(self) -> float:
        with self._lock:
            return self.samples / RATE

    def add_samples(self, frames: int) -> None:
        with self._lock:
            self.samples += frames

    def apply_score(self, message: dict) -> None:
        family = message.get("family")
        if family not in self.families:
            return
        if message.get("available") is False:
            with self._lock:
                self.families[family] = None
            return
        # Handshake-only {"available": true} must not count as a live vote.
        if "departure" not in message and "return" not in message and "strong_departure" not in message:
            return
        reading = {
            "departure": message.get("departure"),
            "strong_departure": bool(message.get("strong_departure")),
            "return": message.get("return"),
            "strong_return": bool(message.get("strong_return")),
            "speech": bool(message.get("speech")),
            "recurring": bool(message.get("recurring")),
            "booth_present": bool(message.get("booth_present")),
            "continuity": message.get("continuity"),
            "cluster_id": message.get("cluster_id"),
            "similarity_to_booth": message.get("similarity_to_booth"),
        }
        now = float(message.get("t") or self.clock())
        with self._lock:
            if family == "speaker":
                ids = message.get("booth_ids")
                if isinstance(ids, list) and ids:
                    self._booth_ids = [str(x) for x in ids][:4]
                # Identity metadata only — never a mute veto by itself.
                reading["booth_locked"] = bool(self._booth_ids)
                reading["booth_ids"] = list(self._booth_ids)
                # Bounded outro hold starts only on verified booth speech.
                if reading["speech"] and reading["booth_present"]:
                    self._booth_hold_until = max(self._booth_hold_until, now + BOOTH_HOLD_S)
            if family == "speaker" and message.get("speech") is False:
                prior = self.families.get("speaker")
                # Keep a recent broadcaster-return vote through short pauses so
                # cover does not stick between intro sentences.
                if prior and prior.get("strong_return") and now <= self._speaker_hold_until:
                    return
                # Brief outro linger after the last *verified* booth line.
                if now <= self._booth_hold_until and prior and prior.get("booth_present"):
                    self.families["speaker"] = {
                        "departure": None,
                        "strong_departure": False,
                        "return": None,
                        "strong_return": False,
                        "speech": False,
                        "recurring": False,
                        "booth_present": True,
                        "booth_locked": bool(self._booth_ids),
                        "continuity": None,
                        "cluster_id": prior.get("cluster_id"),
                        "similarity_to_booth": prior.get("similarity_to_booth"),
                        "booth_ids": list(self._booth_ids),
                    }
                    return
                if now <= self._speaker_hold_until and prior:
                    held = dict(prior)
                    held["strong_return"] = False
                    held["return"] = 0.0
                    held["booth_present"] = False
                    self.families["speaker"] = held
                else:
                    # No synthetic booth lock when the worker is quiet.
                    self.families["speaker"] = None
                return
            if family == "speaker" and reading["strong_departure"]:
                self._speaker_hold_until = now + 10.0
            if family == "speaker" and reading["strong_return"]:
                self._speaker_hold_until = max(self._speaker_hold_until, now + 8.0)
            self.families[family] = reading

    def tick(self, gate: ListenerGate) -> None:
        with self._lock:
            families = dict(self.families)
            timestamp = self.samples / RATE
            auto = gate.auto
        level = {
            "t": round(timestamp, 1),
            "db": round(gate.input_dbfs(), 1),
            "lag_ms": round(gate.lag_ms(RATE), 1),
        }
        if not self.levels or self.levels[-1]["t"] != level["t"]:
            self.levels.append(level)
            if len(self.levels) > 20000:
                del self.levels[:1000]
        # booth_locked = identities known (metadata). Never invent a speaker
        # reading that vetoes commercial detection when the worker is quiet.
        if self._booth_ids and families.get("speaker"):
            sp = dict(families["speaker"])
            sp["booth_locked"] = True
            sp["booth_ids"] = list(self._booth_ids)
            families["speaker"] = sp
        # Expire outro hold without leaving a zombie speaker family.
        if (
            families.get("speaker")
            and families["speaker"].get("booth_present")
            and not families["speaker"].get("speech")
            and timestamp > self._booth_hold_until
        ):
            families["speaker"] = None
            self.families["speaker"] = None
        departure = votes(families, "strong_departure")
        # Verified booth speech counts as a return vote for hints even when
        # Exp002 return_score is still 0 (needs 30s absence).
        sp_now = families.get("speaker") or {}
        booth_back = bool(sp_now.get("speech") and sp_now.get("booth_present"))
        returning = votes(families, "strong_return") + (1 if booth_back else 0)
        alive = sum(1 for reading in families.values() if reading is not None)
        diag = self.machine.diagnostics()
        # Sample every second while armed, or whenever votes are hot / lag is fat.
        hot = departure > 0 or returning > 0 or level["lag_ms"] > 350 or booth_back
        if timestamp - self._last_track_t >= 1.0 or hot:
            self._last_track_t = timestamp
            self._append(
                self.track,
                {
                    "t": round(timestamp, 3),
                    "event": "track",
                    "hearing": "REPLACEMENT" if gate.mode == "replacement" else "PROGRAM",
                    "machine": diag["state"],
                    "auto": auto,
                    "departure_votes": departure,
                    "return_votes": returning,
                    "families_alive": alive,
                    "mute_streak_s": diag["mute_streak_s"],
                    "play_streak_s": diag["play_streak_s"],
                    "muted_for_s": self.machine.muted_for(timestamp),
                    "lag_ms": level["lag_ms"],
                    "dropped_frames": gate.dropped_frames(),
                    "speaker": families.get("speaker"),
                    "audio": families.get("audio"),
                    "semantic": families.get("semantic"),
                    "product": PRODUCT,
                },
            )
        if not auto:
            return
        if gate.mode == "replacement" and self.hint.update(True, returning, 1.0):
            gate.cue_return()
            self._append(self.decisions, {"t": round(timestamp, 3), "event": "return_hint", "product": PRODUCT})
            print(f"{timestamp:8.1f}  program may be back  press F9", flush=True)
        if self.machine.state == "PLAY" and not self.latch.allow_auto_mute(departure):
            return
        if self.machine.state == "MUTED" and not self.latch.allow_auto_play(returning):
            return
        event = self.machine.step(timestamp, 1.0, families)
        if not event:
            return
        if event["state_after"] == "MUTED":
            gate.play_replacement()
            self._log_decision(timestamp, "PROGRAM_TO_REPLACEMENT", "auto", families, gate.replacement, False, gate=gate)
        elif event["state_after"] == "PLAY":
            gate.play_program()
            self.hint.reset()
            self._log_decision(timestamp, "REPLACEMENT_TO_PROGRAM", "auto", families, gate.replacement, False, gate=gate)

    def human(self, gate: ListenerGate, action: str) -> None:
        timestamp = self.clock()
        prior = "replacement" if gate.mode == "replacement" else "program"
        if action == "mute":
            noop = prior == "replacement"
            self.latch.human_mute(was_program=prior == "program")
            gate.play_replacement()
            if not noop:
                self.machine.manual(timestamp, "mute", self._families())
            self._log_decision(
                timestamp,
                "PROGRAM_TO_REPLACEMENT",
                "human",
                self._families(),
                gate.replacement,
                True,
                noop=noop,
                prior_hearing=prior,
                gate=gate,
            )
        elif action == "play":
            noop = prior == "program"
            # Only hold auto-mute when leaving a covered break — not when already on Show.
            self.latch.human_play(was_replacement=prior == "replacement")
            gate.play_program()
            self.hint.reset()
            if not noop:
                self.machine.manual(timestamp, "play", self._families())
            self._log_decision(
                timestamp,
                "REPLACEMENT_TO_PROGRAM",
                "human",
                self._families(),
                gate.replacement,
                True,
                noop=noop,
                prior_hearing=prior,
                gate=gate,
            )
        elif action == "auto":
            gate.auto = not gate.auto
            action = "auto_on" if gate.auto else "auto_off"
        elif action == "sound":
            name = gate.cycle_replacement()
            self._append(self.decisions, {"t": round(timestamp, 3), "event": "replacement", "replacement": name})
            print(f"{timestamp:8.1f}  replacement {name}", flush=True)
            action = f"sound_{name}"
        elif action.startswith("sound_"):
            name = action[len("sound_") :]
            if name not in REPLACEMENTS:
                return
            gate.set_replacement(name)
            self._append(self.decisions, {"t": round(timestamp, 3), "event": "replacement", "replacement": name})
            print(f"{timestamp:8.1f}  replacement {name}", flush=True)
        elif action.startswith("rate"):
            score = int(action[-1])
            if score < 1 or score > 5:
                return
            row = {
                "t": round(timestamp, 3),
                "event": "sound_rating",
                "kind": "pleasantness",
                "replacement": gate.replacement,
                "score": score,
            }
            self._append(self.ratings, row)
            print(f"{timestamp:8.1f}  {gate.replacement} pleasant {score}    every break? y or n", flush=True)
            return
        elif action in ("want_yes", "want_no"):
            row = {
                "t": round(timestamp, 3),
                "event": "sound_rating",
                "kind": "every_break",
                "replacement": gate.replacement,
                "want": action == "want_yes",
            }
            self._append(self.ratings, row)
            answer = "yes" if action == "want_yes" else "no"
            print(f"{timestamp:8.1f}  {gate.replacement} every break {answer}", flush=True)
            return
        else:
            return
        self._append(self.overrides, override_row(timestamp, action, prior))
        print(f"{timestamp:8.1f}  human {action}", flush=True)

    def label(self, gate: ListenerGate, verdict: str, note: str, about: float | None) -> None:
        if verdict not in ("commercial", "program", "unsure"):
            return
        row = {
            "t": round(self.clock(), 3),
            "event": "label_fix",
            "verdict": verdict,
            "about": None if about is None else round(float(about), 3),
            "note": (note or "")[:240],
            "hearing": "REPLACEMENT" if gate.mode == "replacement" else "PROGRAM",
            "replacement": gate.replacement,
            "scientific_authority": False,
            "dataset_role": "live_dev",
        }
        self._append(self.labels, row)
        print(f"{row['t']:8.1f}  label {verdict}", flush=True)

    def snapshot(self, gate: ListenerGate) -> dict:
        families = self._families()
        open_name = self.live.get("open_chunk") or ""
        chunks = [
            path.name
            for path in sorted(self.folder.glob("audio_*.wav"))
            if path.name != open_name and path.stat().st_size > 44
        ]
        diag = self.machine.diagnostics()
        return {
            "product": PRODUCT,
            "state": "REPLACEMENT" if gate.mode == "replacement" else "PROGRAM",
            "auto": gate.auto,
            "replacement": gate.replacement,
            "sounds": list(REPLACEMENTS),
            "timestamp": round(self.clock(), 3),
            "input_dbfs": round(gate.input_dbfs(), 1),
            "lag_ms": round(gate.lag_ms(RATE), 1),
            "departure_votes": votes(families, "strong_departure"),
            "return_votes": votes(families, "strong_return"),
            "mute_streak_s": diag["mute_streak_s"],
            "play_streak_s": diag["play_streak_s"],
            "recording": bool(self.live["recording"]),
            "input_name": self.live["input_name"],
            "output_name": self.live["output_name"],
            "error": self.live["error"],
            "folder": str(self.folder),
            "families": families,
            "levels": self.levels[-240:],
            "events": self.events[-80:],
            "chunks": chunks,
            "show": self.meta.get("show") or "",
            "service": self.meta.get("service") or "",
            "content": self.meta.get("content") or "sports",
            "booth_ids": list(self._booth_ids),
            "resumable": bool((_read_active() or {}).get("recording")) and not bool(self.live["recording"]),
            "scientific_authority": False,
            "dataset_role": "live_dev",
        }

    def close(self) -> None:
        for handle in (self.decisions, self.overrides, self.ratings, self.labels, self.track):
            handle.close()

    def _families(self) -> dict:
        with self._lock:
            return dict(self.families)

    def _log_decision(
        self,
        timestamp,
        state,
        source,
        families,
        replacement,
        human,
        *,
        noop: bool = False,
        prior_hearing: str | None = None,
        gate: ListenerGate | None = None,
    ) -> None:
        diag = self.machine.diagnostics()
        row = decision_row(
            timestamp,
            state,
            source,
            families,
            replacement,
            human,
            noop=noop,
            prior_hearing=prior_hearing,
            departure_votes=votes(families, "strong_departure"),
            return_votes=votes(families, "strong_return"),
            lag_ms=None if gate is None else gate.lag_ms(RATE),
            mute_streak_s=diag["mute_streak_s"],
            play_streak_s=diag["play_streak_s"],
        )
        self._append(self.decisions, row)
        tag = " noop" if noop else ""
        print(f"{timestamp:8.1f}  {state}  {source}  {replacement}{tag}", flush=True)

    def _append(self, handle, row: dict) -> None:
        handle.write(json.dumps(row) + "\n")
        handle.flush()
        self.events.append(row)
        if len(self.events) > 400:
            del self.events[:100]


def _device(value: str, kind: str) -> dict:
    devices = query_audio_devices()
    try:
        return resolve_live_device(value, kind, devices)
    except LiveControlError:
        matches = [
            row
            for row in devices
            if row["max_input_channels" if kind == "input" else "max_output_channels"] > 0
            and value.lower() in row["name"].lower()
        ]
        if len(matches) != 1:
            key = "max_input_channels" if kind == "input" else "max_output_channels"
            names = [row["name"] for row in devices if row[key] > 0]
            raise LiveControlError(f"{kind} device must match one name. Available: " + ", ".join(names))
        return matches[0]


class Desk:
    """Starts and stops the capture. The HTTP server stays up either way."""

    def __init__(self, folder: Path, upload: bool) -> None:
        self.folder = folder
        self.gate = ListenerGate(make_beds(), make_earcon())
        self.session = SportsSession(folder)
        self._lock = threading.Lock()
        self._stop: threading.Event | None = None
        self._record_q: queue.Queue | None = None
        self._record_thread: threading.Thread | None = None
        self._writer: ChunkWriter | None = None
        self._next_chunk = 0
        self._upload = upload
        self._uploader = None
        # ML workers are heavy (Torch). Spawn only when a session actually starts.
        self._audio_proc = None
        self._speaker_proc = None
        self._workers_started = False
        self._next_chunk = _next_chunk_number(folder)

    def _active_payload(self, *, recording: bool) -> dict:
        return {
            "recording": recording,
            "show": self.session.meta.get("show") or "",
            "service": self.session.meta.get("service") or "",
            "content": self.session.meta.get("content") or "sports",
            "input": self.session.live.get("input_name") or "",
            "output": self.session.live.get("output_name") or "",
            "folder": str(self.folder),
        }

    def _ensure_workers(self) -> None:
        if self._workers_started:
            return
        self._workers_started = True
        if self._upload and self._uploader is None:
            self._uploader = subprocess.Popen(
                [sys.executable, "-m", "ohush_live.chunk_uploader", str(self.folder)],
                cwd=str(REPO),
                stdin=subprocess.PIPE,
            )
        audio_py = REPO / "experiments" / "exp003" / ".venv" / "bin" / "python"
        speaker_py = REPO / "experiments" / "exp002" / ".venv" / "bin" / "python"
        self._audio_proc = _spawn(audio_py, "audio_worker.py") if audio_py.is_file() else None
        self._speaker_proc = _spawn(speaker_py, "speaker_worker.py") if speaker_py.is_file() else None
        if self._audio_proc:
            threading.Thread(target=_pump, args=(self._audio_proc, self.session), daemon=True).start()
        if self._speaker_proc:
            threading.Thread(target=_pump, args=(self._speaker_proc, self.session), daemon=True).start()
        print("detectors warming (audio + speaker)", flush=True)

    def start(self, input_name: str, output_name: str) -> str:
        with self._lock:
            if self.session.live["recording"]:
                return ""
            if self._record_thread is not None and self._record_thread.is_alive():
                self.session.live["error"] = "Still closing the last recording."
                return self.session.live["error"]
            try:
                source = _device(input_name, "input")
                speakers = _device(output_name, "output")
            except LiveControlError as exc:
                self.session.live["error"] = str(exc)
                return str(exc)
            self._ensure_workers()
            stop = threading.Event()
            record_q: queue.Queue = queue.Queue(maxsize=256)
            detect_q: queue.Queue = queue.Queue(maxsize=64)
            writer = ChunkWriter(
                self.folder,
                frames_per_chunk=CHUNK_MINUTES * 60 * RATE,
                start_number=self._next_chunk,
            )
            self._stop = stop
            self._record_q = record_q
            self._writer = writer
            record_thread = threading.Thread(
                target=_record, args=(record_q, writer, self._uploader, stop), daemon=True
            )
            self._record_thread = record_thread
            self.session.live["recording"] = True
            self.session.live["input_name"] = source["name"]
            self.session.live["output_name"] = speakers["name"]
            self.session.live["error"] = ""
            self.session.live["open_chunk"] = writer.path.name if writer.path else ""
            _write_active(self._active_payload(recording=True))

        record_thread.start()
        threading.Thread(
            target=_detect,
            args=(detect_q, self.session, self.gate, self._audio_proc, self._speaker_proc, stop),
            daemon=True,
        ).start()

        def _listen() -> None:
            try:
                _run_streams(self.gate, record_q, detect_q, source["index"], speakers["index"], stop)
            except Exception as exc:
                self.session.live["error"] = str(exc)
                print(exc, flush=True)
            finally:
                if self.session.live["recording"]:
                    # Keep .active_desk.json so refresh / engine restart can jump back in.
                    self.end(clear_active=False)

        threading.Thread(target=_listen, daemon=True).start()
        print(f"{PRODUCT}  in={source['name']}  out={speakers['name']}", flush=True)
        return ""

    def end(self, *, clear_active: bool = False) -> None:
        with self._lock:
            if not self.session.live["recording"]:
                if clear_active:
                    _mark_active_stopped(self._active_payload(recording=False))
                return
            stop = self._stop
            record_q = self._record_q
            record_thread = self._record_thread
            writer = self._writer
            self.session.live["recording"] = False
            self.session.live["open_chunk"] = ""
        if stop is not None:
            stop.set()
        if record_q is not None:
            record_q.put(None)
        if record_thread is not None:
            record_thread.join(timeout=3)
        if writer is not None:
            last = writer.close()
            self._next_chunk = writer.number
            if last is not None:
                _send_upload(self._uploader, last)
        if clear_active:
            _mark_active_stopped(self._active_payload(recording=False))
        print("recording paused", flush=True)

    def shutdown(self) -> None:
        # Do not clear active intent — only an explicit Stop should.
        self.end(clear_active=False)
        for name in (
            "decisions.jsonl",
            "overrides.jsonl",
            "ratings.jsonl",
            "labels.jsonl",
            "track.jsonl",
            "session.json",
        ):
            _send_upload(self._uploader, self.folder / name)
        self.session.close()
        for proc in (self._audio_proc, self._speaker_proc, self._uploader):
            if proc is None:
                continue
            try:
                if proc.stdin is not None:
                    proc.stdin.close()
            except Exception:
                pass
            try:
                proc.terminate()
            except Exception:
                pass
        self._audio_proc = None
        self._speaker_proc = None
        self._uploader = None


def _devices(*, refresh: bool = False) -> dict:
    # PortAudio caches the device list for the process lifetime unless we reinit.
    # Never reinit while a stream is open.
    rows = query_audio_devices(refresh=refresh)
    def slim(row: dict) -> dict:
        return {"index": row["index"], "name": row["name"]}

    return {
        "inputs": [slim(row) for row in rows if row["max_input_channels"] > 0],
        "outputs": [slim(row) for row in rows if row["max_output_channels"] > 0],
    }


def _serve(desk: Desk) -> None:
    session = desk.session
    gate = desk.gate

    class Handler(BaseHTTPRequestHandler):
        def _cors(self) -> None:
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")

        def _send(self, code: int, payload: dict) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self._cors()
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _body(self) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                payload = json.loads(raw or b"{}")
            except json.JSONDecodeError:
                return {}
            return payload if isinstance(payload, dict) else {}

        def do_OPTIONS(self) -> None:  # noqa: N802
            self.send_response(204)
            self._cors()
            self.end_headers()

        def do_GET(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path == "/state":
                self._send(200, session.snapshot(gate))
                return
            if path == "/devices":
                # Rescan USB/Core Audio unless a live stream is open.
                self._send(200, _devices(refresh=not bool(session.live.get("recording"))))
                return
            if path.startswith("/media/"):
                name = Path(path).name
                file = desk.folder / name
                open_name = session.live.get("open_chunk") or ""
                if not re.fullmatch(r"audio_\d{4}\.wav", name) or name == open_name or not file.is_file():
                    self._send(404, {"error": "closed recordings only"})
                    return
                data = file.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "audio/wav")
                self._cors()
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            if path == "/":
                page = """<!doctype html><meta charset=utf-8><title>OHush</title>
<body style="background:#160a20;color:#f4eef8;font-family:Georgia,serif;padding:48px">
<p>The desk is at <a style="color:#c4b0f5" href="http://127.0.0.1:3010/">http://127.0.0.1:3010/</a></p>
</body>""".encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(page)))
                self.end_headers()
                self.wfile.write(page)
                return
            self._send(404, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            body = self._body()
            if path == "/override":
                session.human(gate, str(body.get("action") or ""))
                self._send(200, session.snapshot(gate))
                return
            if path == "/start":
                session.configure(
                    str(body.get("show") or ""),
                    str(body.get("service") or ""),
                    str(body.get("content") or "sports"),
                )
                err = desk.start(str(body.get("input") or ""), str(body.get("output") or ""))
                code = 400 if err else 200
                self._send(code, {**session.snapshot(gate), "error": err or session.live["error"]})
                return
            if path == "/stop":
                desk.end(clear_active=True)
                self._send(200, session.snapshot(gate))
                return
            if path == "/label":
                about = body.get("about")
                session.label(
                    gate,
                    str(body.get("verdict") or ""),
                    str(body.get("note") or ""),
                    None if about is None else float(about),
                )
                self._send(200, session.snapshot(gate))
                return
            self._send(404, {"error": "not found"})

        def log_message(self, fmt: str, *args) -> None:
            return

    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


def _keys(session: SportsSession, gate: ListenerGate, stop: threading.Event) -> None:
    if not sys.stdin.isatty():
        return
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    tty.setcbreak(fd)
    mapping = {
        "\x1b[19~": "mute",
        "\x1b[20~": "play",
        "\x1b[21~": "auto",
        "m": "mute",
        "p": "play",
        "a": "auto",
        "s": "sound",
        "1": "rate1",
        "2": "rate2",
        "3": "rate3",
        "4": "rate4",
        "5": "rate5",
        "y": "want_yes",
        "n": "want_no",
    }
    try:
        while not stop.is_set():
            ready, _, _ = select.select([sys.stdin], [], [], 0.2)
            if not ready:
                continue
            seq = sys.stdin.read(1)
            if seq == "\x1b":
                while select.select([sys.stdin], [], [], 0.05)[0]:
                    seq += sys.stdin.read(1)
            action = mapping.get(seq)
            if action:
                session.human(gate, action)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _record(record_q: queue.Queue, writer: ChunkWriter, uploader: subprocess.Popen | None, stop: threading.Event) -> None:
    while not (stop.is_set() and record_q.empty()):
        try:
            pcm = record_q.get(timeout=0.2)
        except queue.Empty:
            continue
        if pcm is None:
            break
        for path in writer.write(pcm):
            _send_upload(uploader, path)


def _send_upload(uploader: subprocess.Popen | None, path: Path) -> None:
    if uploader is None or uploader.stdin is None or uploader.poll() is not None:
        print(f"kept local {path.name}", flush=True)
        return
    try:
        uploader.stdin.write((str(path) + "\n").encode("utf-8"))
        uploader.stdin.flush()
    except BrokenPipeError:
        print(f"uploader down, kept local {path.name}", flush=True)


def _detect(detect_q: queue.Queue, session: SportsSession, gate: ListenerGate, audio_proc, speaker_proc, stop: threading.Event) -> None:
    next_tick = RATE
    seen = 0
    while not (stop.is_set() and detect_q.empty()):
        try:
            raw = detect_q.get(timeout=0.2)
        except queue.Empty:
            continue
        if raw is None:
            break
        pcm = np.frombuffer(raw, dtype=np.int16).reshape(-1, CHANNELS)
        session.add_samples(len(pcm))
        seen += len(pcm)
        mono = pcm.astype(np.float32).mean(axis=1) / 32768.0
        _write_pcm(audio_proc, resample_poly(mono, 2, 3).astype(np.float32))
        _write_pcm(speaker_proc, resample_poly(mono, 1, 3).astype(np.float32))
        while seen >= next_tick:
            session.tick(gate)
            next_tick += RATE


def _run_streams(gate: ListenerGate, record_q: queue.Queue, detect_q: queue.Queue, input_index: int, output_index: int, stop: threading.Event) -> None:
    def on_in(indata, _frames, _time_info, status) -> None:
        if status:
            print(status, flush=True)
        pcm = np.ascontiguousarray(indata, dtype=np.int16)
        gate.push(pcm)
        raw = pcm.tobytes()
        try:
            record_q.put_nowait(raw)
        except queue.Full:
            print("record queue full", flush=True)
        try:
            detect_q.put_nowait(raw)
        except queue.Full:
            pass

    def on_out(outdata, _frames, _time_info, status) -> None:
        if status:
            print(status, flush=True)
        gate.render(outdata)

    with sd.InputStream(
        device=input_index, channels=CHANNELS, samplerate=RATE, dtype="int16", callback=on_in, blocksize=2048
    ), sd.OutputStream(
        device=output_index, channels=CHANNELS, samplerate=RATE, dtype="int16", callback=on_out, blocksize=2048
    ):
        while not stop.is_set():
            time.sleep(0.2)


def _preflight(gate: ListenerGate, input_index: int, output_index: int) -> None:
    print("Preflight: you should hear the TV, then silence. The input meter should stay up both times.", flush=True)
    stop = threading.Event()
    record_q: queue.Queue = queue.Queue()
    detect_q: queue.Queue = queue.Queue()

    def watch() -> None:
        gate.play_program()
        time.sleep(4)
        print(f"hearing program   input {gate.input_dbfs():6.1f} dBFS", flush=True)
        gate.play_replacement()
        gate.replacement = "silence"
        time.sleep(4)
        level = gate.input_dbfs()
        print(f"hearing silence   input {level:6.1f} dBFS", flush=True)
        if level < -60:
            print("Capture went quiet while the speakers were silenced. The mute reached the source.", flush=True)
        else:
            print("Capture stayed up while the speakers were silent.", flush=True)
        stop.set()

    threading.Thread(target=watch, daemon=True).start()
    _run_streams(gate, record_q, detect_q, input_index, output_index, stop)


def _acquire_singleton():
    """One engine only. Spawning during make_beds used to pile up Torch workers and jetsam the Mac."""
    folder = REPO / "ohush_live" / "sessions"
    folder.mkdir(parents=True, exist_ok=True)
    lock_path = folder / ".desk.lock"
    pid_path = folder / ".desk.pid"
    handle = open(lock_path, "a+", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        return None
    handle.seek(0)
    handle.truncate()
    handle.write(str(os.getpid()))
    handle.flush()
    pid_path.write_text(str(os.getpid()), encoding="utf-8")
    return handle


def main() -> None:
    parser = argparse.ArgumentParser(description=PRODUCT)
    parser.add_argument("--input-device", default="USB")
    parser.add_argument("--output-device", default="")
    parser.add_argument("--session", default="")
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--no-upload", action="store_true")
    args = parser.parse_args()
    if args.preflight:
        if not args.output_device:
            devices = query_audio_devices()
            names = [row["name"] for row in devices if row["max_output_channels"] > 0]
            raise SystemExit("Pass --output-device for preflight. Outputs: " + ", ".join(names))
        source = _device(args.input_device, "input")
        speakers = _device(args.output_device, "output")
        _preflight(ListenerGate(make_beds(), make_earcon()), source["index"], speakers["index"])
        return
    lock = _acquire_singleton()
    if lock is None:
        print("engine already running — not starting a second copy", flush=True)
        return
    stamp = datetime.now().strftime("%Y-%m-%d-tnf")
    active = _read_active()
    if args.session:
        folder = Path(args.session)
    elif active and active.get("recording") and active.get("folder"):
        folder = Path(str(active["folder"]))
    else:
        folder = REPO / "ohush_live" / "sessions" / stamp
    desk = Desk(folder, upload=not args.no_upload)
    if active and not desk.session.meta.get("show"):
        desk.session.configure(
            str(active.get("show") or ""),
            str(active.get("service") or ""),
            str(active.get("content") or "sports"),
        )
    threading.Thread(target=_serve, args=(desk,), daemon=True).start()
    process_stop = threading.Event()
    threading.Thread(target=_keys, args=(desk.session, desk.gate, process_stop), daemon=True).start()
    if args.output_device:
        err = desk.start(args.input_device, args.output_device)
        if err:
            raise SystemExit(err)
    elif active and active.get("recording") and active.get("input") and active.get("output"):
        desk.session.configure(
            str(active.get("show") or ""),
            str(active.get("service") or ""),
            str(active.get("content") or "sports"),
        )
        err = desk.start(str(active["input"]), str(active["output"]))
        if err:
            print(f"could not resume open session: {err}", flush=True)
        else:
            print("resumed open session (Stop was never clicked)", flush=True)
    print("Turn the TV speakers down. Leave optical audio running. Listen on this Mac.", flush=True)
    print("Dashboard  http://127.0.0.1:3010/", flush=True)
    print(f"Engine     http://{HOST}:{PORT}/   F8 mute  F9 play  F10 auto  S sound  1-5 pleasant  y/n every break", flush=True)
    print(f"project {PROJECT}  logs {folder}", flush=True)
    try:
        while not process_stop.is_set():
            time.sleep(0.4)
    except KeyboardInterrupt:
        process_stop.set()
    finally:
        process_stop.set()
        desk.shutdown()
        print("recording closed", flush=True)
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
            lock.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
