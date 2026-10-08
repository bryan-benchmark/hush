"""OHUSH_LIVE_V0 capture, decision log, and local control server.

The optical input is the sensor. A Chrome extension is the actuator.
This process does not write into experiments/.
"""

from __future__ import annotations

import argparse
import json
import queue
import signal
import subprocess
import sys
import threading
import time
import wave
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
from ohush_live.policy import PRODUCT  # noqa: E402
from ohush_live.state import Machine  # noqa: E402

RATE = 48000
CHANNELS = 2
HOST = "127.0.0.1"
PORT = 8770


class Hub:
    def __init__(self, session: Path) -> None:
        self.session = session
        self.machine = Machine()
        self.families: dict[str, dict | None] = {"speaker": None, "audio": None, "semantic": None}
        self.started = time.monotonic()
        self.samples = 0
        self.lock = threading.Lock()
        self.log_path = session / "events.jsonl"
        self._speaker_hold_until = 0.0
        session.mkdir(parents=True, exist_ok=True)
        (session / "README.txt").write_text(
            "OHUSH_LIVE_V0 recording. Not an experiment. Do not use it to change Exp001–005.\n",
            encoding="utf-8",
        )

    def clock(self) -> float:
        with self.lock:
            return self.samples / RATE

    def note_samples(self, frames: int) -> None:
        with self.lock:
            self.samples += frames

    def apply_score(self, message: dict) -> None:
        family = message.get("family")
        if family not in self.families or message.get("available") is False:
            if family in self.families and message.get("available") is False:
                with self.lock:
                    self.families[family] = None
            return
        reading = {
            "departure": message.get("departure"),
            "strong_departure": bool(message.get("strong_departure")),
            "return": message.get("return"),
            "strong_return": bool(message.get("strong_return")),
        }
        now = float(message.get("t") or self.clock())
        with self.lock:
            if family == "speaker" and message.get("speech") is False:
                if reading["strong_departure"] or now <= self._speaker_hold_until:
                    if now <= self._speaker_hold_until:
                        held = dict(self.families["speaker"] or reading)
                        held["strong_return"] = False
                        held["return"] = 0.0
                        self.families["speaker"] = held
                    else:
                        self.families["speaker"] = None
                else:
                    self.families["speaker"] = None
                return
            if family == "speaker" and reading["strong_departure"]:
                self._speaker_hold_until = now + 10.0
            self.families[family] = reading

    def tick(self) -> None:
        with self.lock:
            families = dict(self.families)
            timestamp = self.samples / RATE
        event = self.machine.step(timestamp, 1.0, families)
        if event:
            self._write(event)

    def override(self, action: str) -> dict:
        with self.lock:
            families = dict(self.families)
            timestamp = self.samples / RATE
        event = self.machine.manual(timestamp, action, families)
        self._write(event)
        return event

    def snapshot(self) -> dict:
        with self.lock:
            return {
                "product": PRODUCT,
                "state": self.machine.state,
                "timestamp": round(self.samples / RATE, 3),
                "families": self.families,
                "semantic": "unavailable tonight; speaker and audio are the two live votes",
            }

    def _write(self, event: dict) -> None:
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event) + "\n")
        print(
            f"{event['timestamp']:8.1f}  {event['state_before']} -> {event['state_after']}  {event['reason']}",
            flush=True,
        )


def _serve(hub: Hub) -> None:
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, payload: dict) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self) -> None:  # noqa: N802
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.end_headers()

        def do_GET(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path == "/state":
                self._send(200, hub.snapshot())
                return
            if path == "/":
                state = hub.snapshot()["state"]
                page = f"""<!doctype html>
<meta charset="utf-8">
<title>{PRODUCT}</title>
<style>
  body {{ margin: 0; background: #160a20; color: #f4eef8; font-family: Georgia, serif; }}
  main {{ max-width: 640px; margin: 0 auto; padding: 32px 20px 64px; }}
  .brand-logo {{ height: 56px; width: auto; display: block; }}
  p {{ font-family: ui-monospace, monospace; color: #c4b4d4; }}
</style>
<body><main>
{_brand_logo()}
<p>{PRODUCT}</p>
<p>State: {state}</p>
<p>Chrome extension mutes the Prime tab. ⌘⇧M mute, ⌘⇧P play. Space on the Prime page plays while muted.</p>
</main></body>""".encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(page)))
                self.end_headers()
                self.wfile.write(page)
                return
            self._send(404, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            if urlparse(self.path).path != "/override":
                self._send(404, {"error": "not found"})
                return
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
            action = body.get("action")
            if action not in ("mute", "play"):
                self._send(400, {"error": "action must be mute or play"})
                return
            self._send(200, hub.override(action))

        def log_message(self, fmt: str, *args) -> None:
            return

    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


def _pump(proc: subprocess.Popen, hub: Hub) -> None:
    assert proc.stdout is not None
    for line in proc.stdout:
        text = line.decode("utf-8", errors="replace").strip()
        if not text:
            continue
        try:
            message = json.loads(text)
        except json.JSONDecodeError:
            print(text, flush=True)
            continue
        if message.get("available") is False:
            print(f"{message.get('family')} unavailable: {message.get('error')}", flush=True)
        hub.apply_score(message)


def _spawn(python: Path, script: str) -> subprocess.Popen:
    return subprocess.Popen(
        [str(python), str(REPO / "ohush_live" / script)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


def _write_pcm(proc: subprocess.Popen | None, samples: np.ndarray) -> None:
    if proc is None or proc.stdin is None or proc.poll() is not None:
        return
    try:
        proc.stdin.write(np.asarray(samples, dtype=np.float32).tobytes())
        proc.stdin.flush()
    except BrokenPipeError:
        return


def _mono(block: np.ndarray) -> np.ndarray:
    audio = np.asarray(block, dtype=np.float32)
    if audio.ndim == 2:
        audio = audio.mean(axis=1)
    return audio / 32768.0 if audio.dtype.kind == "i" else audio


def main() -> None:
    parser = argparse.ArgumentParser(description="OHUSH_LIVE_V0")
    parser.add_argument("--input-device", default="USB")
    parser.add_argument("--session", default="")
    args = parser.parse_args()
    stamp = datetime.now().strftime("%Y-%m-%d-tnf")
    session = Path(args.session) if args.session else REPO / "ohush_live" / "sessions" / stamp
    hub = Hub(session)
    devices = query_audio_devices()
    try:
        device = resolve_live_device(args.input_device, "input", devices)
    except LiveControlError:
        matches = [
            row
            for row in devices
            if row["max_input_channels"] > 0 and args.input_device.lower() in row["name"].lower()
        ]
        if len(matches) != 1:
            names = [row["name"] for row in devices if row["max_input_channels"] > 0]
            raise SystemExit("Input device must match one capture input. Available: " + ", ".join(names))
        device = matches[0]
    audio_py = REPO / "experiments" / "exp003" / ".venv" / "bin" / "python"
    speaker_py = REPO / "experiments" / "exp002" / ".venv" / "bin" / "python"
    audio_proc = _spawn(audio_py, "audio_worker.py") if audio_py.is_file() else None
    speaker_proc = _spawn(speaker_py, "speaker_worker.py") if speaker_py.is_file() else None
    if audio_proc:
        threading.Thread(target=_pump, args=(audio_proc, hub), daemon=True).start()
    else:
        print("audio worker missing; that vote stays unavailable", flush=True)
    if speaker_proc:
        threading.Thread(target=_pump, args=(speaker_proc, hub), daemon=True).start()
    else:
        print("speaker worker missing; that vote stays unavailable", flush=True)
    threading.Thread(target=_serve, args=(hub,), daemon=True).start()
    wav_path = session / "capture.wav"
    wav = wave.open(str(wav_path), "wb")
    wav.setnchannels(CHANNELS)
    wav.setsampwidth(2)
    wav.setframerate(RATE)
    audio_q: queue.Queue[np.ndarray] = queue.Queue(maxsize=32)

    def on_audio(indata, frames, _time_info, status) -> None:
        if status:
            print(status, flush=True)
        try:
            audio_q.put_nowait(np.asarray(indata).copy())
        except queue.Full:
            print("capture queue full", flush=True)

    print(f"{PRODUCT}  device={device['name']}  http://{HOST}:{PORT}/", flush=True)
    print(f"log {hub.log_path}", flush=True)
    print("Load the Chrome extension in ohush_live/extension before kickoff.", flush=True)
    next_tick = time.monotonic() + 1.0

    def _stop(_signum, _frame) -> None:
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, _stop)
    try:
        with sd.InputStream(
            device=device["index"],
            channels=CHANNELS,
            samplerate=RATE,
            dtype="int16",
            callback=on_audio,
            blocksize=RATE,
        ):
            while True:
                try:
                    block = audio_q.get(timeout=0.5)
                except queue.Empty:
                    block = None
                if block is not None:
                    pcm = np.asarray(block, dtype=np.int16)
                    wav.writeframes(pcm.tobytes())
                    wav._file.flush()
                    hub.note_samples(len(pcm))
                    mono = pcm.astype(np.float32).mean(axis=1) / 32768.0
                    _write_pcm(audio_proc, resample_poly(mono, 2, 3).astype(np.float32))
                    _write_pcm(speaker_proc, resample_poly(mono, 1, 3).astype(np.float32))
                now = time.monotonic()
                if now >= next_tick:
                    hub.tick()
                    next_tick += 1.0
    except KeyboardInterrupt:
        print("stopping", flush=True)
    finally:
        wav.close()
        for proc in (audio_proc, speaker_proc):
            if proc is not None and proc.stdin is not None:
                proc.stdin.close()


if __name__ == "__main__":
    main()
