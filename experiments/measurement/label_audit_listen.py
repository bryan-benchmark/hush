"""Serve the label-audit listen on localhost. Scores stay off the page."""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

import numpy as np
import soundfile as sf

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from hush.audio import analysis_pieces, find_session, load_session, read_stereo  # noqa: E402

OUT = REPO / "docs" / "ohush" / "research" / "LABEL_AUDIT_001"
CLIPS = OUT / "clips"
QUEUE = OUT / "queue.jsonl"
JUDGMENTS = OUT / "judgments.json"
HOST = "127.0.0.1"
PORT = 3020
SR = 48000

PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Hush label listen</title>
  <style>
    body { font-family: Georgia, serif; margin: 2rem auto; max-width: 52rem; line-height: 1.45; color: #1c1915; background: #f6f1e7; }
    h1 { font-size: 1.5rem; font-weight: normal; }
    textarea { width: 100%; min-height: 8rem; font: 1.05rem Georgia, serif; padding: 0.5rem; box-sizing: border-box; }
    button { font-family: Georgia, serif; font-size: 1rem; margin-right: 0.5rem; padding: 0.35rem 0.8rem; }
    .row { display: flex; justify-content: space-between; gap: 1rem; margin-top: 0.6rem; }
    #status { min-height: 1.2rem; }
    .transport { display: flex; background: #1a1024; border-radius: 8px; overflow: hidden; margin: 1rem 0 0.4rem; }
    #play { width: 56px; border: 0; border-right: 1px solid rgba(255,255,255,0.12); background: transparent; color: #7dffb3; font-size: 1.4rem; cursor: pointer; margin: 0; }
    .wave-wrap { position: relative; flex: 1; cursor: crosshair; touch-action: none; }
    #wave { width: 100%; height: 160px; display: block; pointer-events: none; }
    #playhead { position: absolute; top: 0; bottom: 0; left: 0; width: 2px; background: #7dffb3; box-shadow: 0 0 8px #7dffb3; pointer-events: none; }
    #clock { font-variant-numeric: tabular-nums; margin: 0 0 1rem; }
  </style>
</head>
<body>
  <h1>What is happening?</h1>
  <p id="place"></p>
  <p>Click the wave to jump. Drag to move through it. Write what you hear, and say if you would want it left on.</p>
  <div class="transport">
    <button type="button" id="play" aria-label="Play">▶</button>
    <div class="wave-wrap" id="hit">
      <canvas id="wave" width="840" height="160"></canvas>
      <div id="playhead"></div>
    </div>
  </div>
  <p id="clock">0.00 of 0s</p>
  <audio id="player" preload="auto"></audio>
  <form id="form">
    <textarea name="note" placeholder="Announcer still talking about the game, then they throw to a car ad..."></textarea>
    <div class="row">
      <span>
        <button type="button" id="back">Back</button>
        <button type="submit">Save and next</button>
      </span>
      <span id="count"></span>
    </div>
    <p id="status"></p>
  </form>
  <script>
    const form = document.getElementById("form");
    const note = form.elements.note;
    const player = document.getElementById("player");
    const canvas = document.getElementById("wave");
    const hit = document.getElementById("hit");
    const playhead = document.getElementById("playhead");
    const playButton = document.getElementById("play");
    let rows = [];
    let index = 0;
    let drawToken = 0;
    let audioCtx = null;
    let heard = 0;
    let held = null;
    let dragging = false;
    function duration() {
      if (Number.isFinite(player.duration) && player.duration > 0) return player.duration;
      return heard;
    }
    function show(seconds) {
      const span = duration();
      playhead.style.left = span ? Math.min(100, Math.max(0, (seconds / span) * 100)) + "%" : "0%";
      document.getElementById("clock").textContent = seconds.toFixed(2) + " of " + (span ? span.toFixed(0) : "0") + "s";
    }
    function secondsAt(clientX) {
      const rect = hit.getBoundingClientRect();
      const span = duration();
      if (!span || rect.width <= 0) return null;
      const fraction = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width));
      return fraction * span;
    }
    function paint(buffer) {
      const ctx = canvas.getContext("2d");
      const data = buffer.getChannelData(0);
      const width = canvas.width;
      const height = canvas.height;
      ctx.clearRect(0, 0, width, height);
      ctx.fillStyle = "#1a1024";
      ctx.fillRect(0, 0, width, height);
      ctx.strokeStyle = "#d7c6f5";
      ctx.beginPath();
      const step = Math.max(1, Math.floor(data.length / width));
      for (let x = 0; x < width; x += 1) {
        let min = 1;
        let max = -1;
        const start = x * step;
        for (let i = 0; i < step; i += 1) {
          const sample = data[start + i] || 0;
          if (sample < min) min = sample;
          if (sample > max) max = sample;
        }
        ctx.moveTo(x + 0.5, (1 - max) * 0.5 * height);
        ctx.lineTo(x + 0.5, (1 - min) * 0.5 * height);
      }
      ctx.stroke();
    }
    function commit(andPlay) {
      if (held == null) return;
      const target = held;
      const apply = () => {
        const start = () => {
          if (Math.abs((player.currentTime || 0) - target) > 0.3) {
            player.addEventListener("seeked", start, { once: true });
            player.currentTime = target;
            return;
          }
          if (!andPlay) {
            held = null;
            return;
          }
          player.play().then(() => {
            if (Math.abs(player.currentTime - target) > 0.5) player.currentTime = target;
            else held = null;
          }).catch(() => undefined);
        };
        player.pause();
        player.addEventListener("seeked", start, { once: true });
        player.currentTime = target;
        if (!player.seeking && Math.abs((player.currentTime || 0) - target) <= 0.3) {
          player.removeEventListener("seeked", start);
          start();
        }
      };
      if (player.readyState >= 3) apply();
      else player.addEventListener("canplay", apply, { once: true });
    }
    function tick() {
      if (!dragging && held != null && !player.seeking && Math.abs((player.currentTime || 0) - held) < 0.35) held = null;
      show(held != null ? held : (player.currentTime || 0));
      playButton.textContent = player.paused ? "▶" : "❚❚";
      playButton.setAttribute("aria-label", player.paused ? "Play" : "Pause");
      requestAnimationFrame(tick);
    }
    hit.addEventListener("pointerdown", (event) => {
      if (event.button !== 0) return;
      hit.setPointerCapture(event.pointerId);
      dragging = true;
      held = secondsAt(event.clientX);
      if (held != null) show(held);
    });
    hit.addEventListener("pointermove", (event) => {
      if (!dragging || !hit.hasPointerCapture(event.pointerId)) return;
      held = secondsAt(event.clientX);
      if (held != null) show(held);
    });
    function release(event) {
      if (!dragging) return;
      dragging = false;
      if (hit.hasPointerCapture(event.pointerId)) hit.releasePointerCapture(event.pointerId);
      held = secondsAt(event.clientX);
      if (held != null) show(held);
      commit(true);
    }
    hit.addEventListener("pointerup", release);
    hit.addEventListener("pointercancel", release);
    playButton.addEventListener("click", () => {
      if (player.paused) player.play();
      else player.pause();
    });
    window.addEventListener("keydown", (event) => {
      if (event.code !== "Space" || event.target === note) return;
      event.preventDefault();
      if (player.paused) player.play();
      else player.pause();
    });
    function fill() {
      const row = rows[index];
      const token = ++drawToken;
      document.getElementById("place").textContent = "Clip " + (index + 1) + " of " + rows.length;
      document.getElementById("count").textContent = row.clip;
      player.pause();
      held = null;
      heard = 0;
      player.src = "/clips/" + row.clip + ".wav";
      player.load();
      note.value = row.note || "";
      document.getElementById("status").textContent = "";
      fetch(player.src)
        .then((response) => response.arrayBuffer())
        .then((bytes) => {
          if (!audioCtx) audioCtx = new AudioContext();
          return audioCtx.decodeAudioData(bytes.slice(0));
        })
        .then((buffer) => {
          if (token !== drawToken) return;
          heard = buffer.duration;
          paint(buffer);
        })
        .catch(() => undefined);
    }
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const body = { clip: rows[index].clip, note: note.value.trim() };
      if (!body.note) {
        document.getElementById("status").textContent = "Write what you hear, then save.";
        return;
      }
      const response = await fetch("/judgment", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      if (!response.ok) {
        document.getElementById("status").textContent = "Save failed.";
        return;
      }
      rows[index].note = body.note;
      const done = index >= rows.length - 1;
      if (!done) index += 1;
      fill();
      if (done) document.getElementById("status").textContent = "Saved. That was the last clip.";
    });
    document.getElementById("back").addEventListener("click", () => {
      if (index > 0) index -= 1;
      fill();
    });
    requestAnimationFrame(tick);
    fetch("/queue").then((response) => response.json()).then((payload) => {
      rows = payload;
      const firstOpen = rows.findIndex((row) => !row.note);
      index = firstOpen === -1 ? 0 : firstOpen;
      fill();
    });
  </script>
</body>
</html>
"""


def load_queue() -> list[dict]:
    rows = [json.loads(line) for line in QUEUE.read_text(encoding="utf-8").splitlines() if line.strip()]
    saved = json.loads(JUDGMENTS.read_text(encoding="utf-8")) if JUDGMENTS.exists() else {}
    for row in rows:
        prior = saved.get(row["clip"])
        if prior:
            row["note"] = prior.get("note", "")
    return rows


def extract(rows: list[dict]) -> None:
    CLIPS.mkdir(parents=True, exist_ok=True)
    sessions: dict[str, tuple[Path, dict]] = {}
    for row in rows:
        dest = CLIPS / f"{row['clip']}.wav"
        if dest.exists() and dest.stat().st_size > 44:
            continue
        session = row["session"]
        if session not in sessions:
            folder = find_session(REPO / "recordings", session)
            sessions[session] = (folder, load_session(folder))
        folder, meta = sessions[session]
        t0 = max(0.0, float(row["t0"]))
        t1 = float(row["t1"])
        pieces = analysis_pieces(folder, meta, t0, t1)
        audio = np.concatenate([read_stereo(piece) for piece in pieces], axis=0)
        sf.write(str(dest), np.clip(audio, -1.0, 1.0), SR, subtype="PCM_16")
        print(f"wrote {dest.name} {audio.shape[0] / SR:.1f}s", flush=True)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        return

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = unquote(self.path.split("?", 1)[0])
        if path in ("/", "/listen"):
            self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
            return
        if path == "/queue":
            self._send(200, json.dumps(load_queue()).encode("utf-8"), "application/json")
            return
        if path.startswith("/clips/") and path.endswith(".wav"):
            name = Path(path).name
            target = CLIPS / name
            if target.is_file():
                self._send(200, target.read_bytes(), "audio/wav")
                return
        self._send(404, b"missing", "text/plain")

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/judgment":
            self._send(404, b"missing", "text/plain")
            return
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length).decode("utf-8"))
        saved = json.loads(JUDGMENTS.read_text(encoding="utf-8")) if JUDGMENTS.exists() else {}
        saved[body["clip"]] = {"note": str(body.get("note") or "").strip()}
        JUDGMENTS.write_text(json.dumps(saved, indent=2) + "\n", encoding="utf-8")
        self._send(200, b"{\"ok\":true}", "application/json")


def main() -> None:
    rows = load_queue()
    extract(rows)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"http://{HOST}:{PORT}/", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
