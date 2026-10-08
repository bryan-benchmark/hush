"""Local live status server for the OHush research monitor (SSE + control API)."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable
from urllib.parse import urlparse


def empty_snapshot() -> dict[str, Any]:
    return {
        "recording": False,
        "pipeline": None,
        "standby": False,
        "elapsed_seconds": 0.0,
        "dbfs": -100.0,
        "input_dbfs": -100.0,
        "output_dbfs": -100.0,
        "device_index": None,
        "device_name": None,
        "sample_rate_hz": None,
        "channels": None,
        "chunk": 0,
        "folder": None,
        "session": None,
        "markers": [],
        "warnings_count": 0,
        "monitor_url": None,
        "mode": None,
        "gate": "play",
        "gate_reason": None,
        "transport": "stopped",
        "prime_ms": 40,
        "buffer_ms": 0.0,
        "buffer_frames": 0,
        "buffer_target_ms": 40,
        "buffer_min_ms": None,
        "buffer_max_ms": None,
        "input_device_name": None,
        "output_device_name": None,
        "input_device_index": None,
        "output_device_index": None,
        "input_channels": None,
        "output_channels": None,
        "input_rate_hz": None,
        "output_rate_hz": None,
        "input_default_rate_hz": None,
        "output_default_rate_hz": None,
        "requested_rate_hz": 48000,
        "sample_rate_mismatch": False,
        "host_resampling": False,
        "input_portaudio_flags": 0,
        "output_portaudio_flags": 0,
        "ring_overruns": 0,
        "ring_underruns": 0,
        "record_queue_drops": 0,
        "reprime_count": 0,
        "xruns": 0,
        "recording_integrity": "ok",
        "input_silent": False,
        "input_disconnected": False,
        "output_disconnected": False,
        "engine_stalled": False,
        "estimated_transport_latency_ms": None,
        "input_stream_latency_ms": None,
        "output_stream_latency_ms": None,
        "near_zero_fraction": 0.0,
        "error": None,
        "session_samples": 0,
    }


class LiveState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.snapshot: dict[str, Any] = empty_snapshot()
        self._version = 0
        self._cond = threading.Condition(self._lock)

    def update(self, **kwargs: Any) -> None:
        with self._cond:
            self.snapshot.update(kwargs)
            self._version += 1
            self._cond.notify_all()

    def append_marker(self, marker: dict[str, Any]) -> None:
        with self._cond:
            markers = list(self.snapshot.get("markers") or [])
            markers.append(marker)
            self.snapshot["markers"] = markers[-50:]
            self._version += 1
            self._cond.notify_all()

    def get(self) -> dict[str, Any]:
        with self._lock:
            return dict(self.snapshot)

    def wait_for_change(self, version: int, timeout: float) -> tuple[int, dict[str, Any]]:
        with self._cond:
            if self._version == version:
                self._cond.wait(timeout=timeout)
            return self._version, dict(self.snapshot)


def make_handler(
    state: LiveState,
    on_mark: Callable[[str, str | None], dict[str, Any] | None],
    on_command: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None,
    devices_provider: Callable[[], dict[str, Any]] | None = None,
):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return

        def _cors(self) -> None:
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")

        def _json(self, code: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _read_json(self) -> dict[str, Any] | None:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                body = json.loads(raw.decode("utf-8") or "{}")
            except json.JSONDecodeError:
                return None
            if not isinstance(body, dict):
                return None
            return body

        def do_OPTIONS(self) -> None:
            self.send_response(204)
            self._cors()
            self.end_headers()

        def do_GET(self) -> None:
            path = urlparse(self.path).path

            if path in ("/", "/health"):
                self._json(200, {"ok": True, "service": "hush-live"})
                return

            if path == "/status":
                self._json(200, state.get())
                return

            if path == "/devices":
                if devices_provider is None:
                    self._json(200, {"ok": True, "inputs": [], "outputs": []})
                    return
                try:
                    listed = devices_provider()
                except Exception as exc:
                    self._json(500, {"ok": False, "error": str(exc)})
                    return
                self._json(200, {"ok": True, **listed})
                return

            if path == "/events":
                self.send_response(200)
                self._cors()
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self.end_headers()

                version = -1
                try:
                    while True:
                        version, snap = state.wait_for_change(version, timeout=1.0)
                        line = f"data: {json.dumps(snap)}\n\n".encode("utf-8")
                        self.wfile.write(line)
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    return

            self.send_response(404)
            self._cors()
            self.end_headers()

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            body = self._read_json()
            if body is None:
                self._json(400, {"ok": False, "error": "Expected a JSON object."})
                return

            if path == "/mark":
                self._mark(body)
                return

            if path in ("/session/start", "/session/stop", "/mode", "/gate"):
                if on_command is None:
                    self._json(404, {"ok": False, "error": "Live controls are not available."})
                    return
                name = {
                    "/session/start": "start",
                    "/session/stop": "stop",
                    "/mode": "mode",
                    "/gate": "gate",
                }[path]
                try:
                    result = on_command(name, body)
                except Exception as exc:
                    self._json(500, {"ok": False, "error": str(exc)})
                    return
                code = 200 if result.get("ok") else 400
                self._json(code, result)
                return

            self.send_response(404)
            self._cors()
            self.end_headers()

        def _mark(self, body: dict[str, Any]) -> None:
            kind = str(body.get("type") or "").strip()
            note = body.get("note")
            note_s = str(note).strip() if note is not None else None
            marker = on_mark(kind, note_s)
            if marker is None:
                self._json(
                    400,
                    {
                        "ok": False,
                        "error": 'Use type "ad_start", "content_start", or "note".',
                    },
                )
                return
            self._json(200, {"ok": True, "marker": marker})

    return Handler


def start_live_server(
    state: LiveState,
    on_mark: Callable[[str, str | None], dict[str, Any] | None],
    host: str = "127.0.0.1",
    port: int = 8787,
    on_command: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None,
    devices_provider: Callable[[], dict[str, Any]] | None = None,
) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(
        (host, port),
        make_handler(state, on_mark, on_command, devices_provider),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server
