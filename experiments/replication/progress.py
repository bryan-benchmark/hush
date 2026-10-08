"""Live progress page for the unlabeled replication queue.

Reads queue.log and the per-run logs. Does not open score files or the ledger.
Serves http://127.0.0.1:8765/ and rewrites the page every few seconds.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
QUEUE = ROOT / "logs" / "queue.log"
FREEZE = ROOT / "freeze"
SPANS = ROOT / "spans.json"
PORT = 8765


def _brand_logo() -> str:
    svg = (REPO / "brand" / "OHush_Vector_Brand_Kit" / "OHush_Horizontal_white.svg").read_text(encoding="utf-8")
    svg = svg.split("?>", 1)[-1].strip()
    return svg.replace("<svg ", '<svg class="brand-logo" ', 1)

# Minutes each step took on the Prime span, per hour of audio. Exp003b is a
# bookkeeping pass. Language is most of the time.
STEP_MIN_PER_HOUR = {
    "exp002": 4 * 60 / 7600 * 3600 / 60,  # ~1.9 min per audio hour
    "exp003": 23 * 60 / 7600 * 3600 / 60,
    "exp003b": 0.05,
    "exp005": 61 * 60 / 7600 * 3600 / 60,
}
STEPS = (
    ("exp002", "Speakers"),
    ("exp003", "Audio world"),
    ("exp003b", "Frozen cloud"),
    ("exp005", "Language"),
)
NAMES = {
    "hush_20260924_220624": ("Prime", "Falcons at Packers"),
    "hush_20260827_135935": ("Hulu", "Gilmore Girls (Aug)"),
    "hush_20261007_220650": ("Hulu", "Gilmore Girls"),
    "hush_20260909_213047": ("NBC", "opener"),
    "hush_20260913_150934": ("FOX", "afternoon"),
    "hush_20260913_210542": ("NBC", "Sunday night"),
}
EMBEDDED = re.compile(r"embedded (\d+)/(\d+)")
ASR = re.compile(r"last_end=([0-9.]+)")
WORDS = re.compile(r"^words=\d+", re.M)
START = re.compile(r"^START (\S+) (\S+)$", re.M)
END = re.compile(r"^END (\S+) exit=(\d+) (\S+)$", re.M)


def _spans() -> list[dict]:
    rows = []
    for row in json.loads(SPANS.read_text(encoding="utf-8")):
        title, detail = NAMES.get(row["session_id"], (row["session_id"], ""))
        rows.append(
            {
                "id": row["session_id"],
                "title": title,
                "detail": detail,
                "seconds": float(row["t1"]) - float(row["t0"]),
            }
        )
    return rows


def _queue() -> dict[str, dict]:
    text = QUEUE.read_text(encoding="utf-8") if QUEUE.is_file() else ""
    state: dict[str, dict] = {}
    for match in START.finditer(text):
        state[match.group(1)] = {"started": match.group(2), "exit": None, "ended": None}
    for match in END.finditer(text):
        slot = state.setdefault(match.group(1), {"started": None, "exit": None, "ended": None})
        slot["exit"] = int(match.group(2))
        slot["ended"] = match.group(3)
    return state


def _log_fraction(session: str, step: str, seconds: float) -> float | None:
    path = ROOT / "logs" / f"{session}_{step}.log"
    if not path.is_file():
        return 0.02
    text = path.read_text(encoding="utf-8", errors="replace")
    if step in ("exp002", "exp003"):
        found = EMBEDDED.findall(text)
        if found:
            done, total = int(found[-1][0]), int(found[-1][1])
            frac = done / total if total else 0.0
            if "writing artifacts" in text or text.strip().endswith(f"{total}/{total}"):
                return min(0.99, max(frac, 0.99))
            return min(0.98, frac)
        if "speech segmentation" in text or "resampling" in text:
            return 0.08
        return 0.03
    if step == "exp003b":
        return 0.5
    if WORDS.search(text):
        return 0.97
    ends = ASR.findall(text)
    if ends and seconds > 0:
        return min(0.96, float(ends[-1]) / seconds)
    return 0.02


def _fmt_min(minutes: float) -> str:
    minutes = max(0.0, minutes)
    if minutes < 1:
        return "under a minute"
    rounded = int(round(minutes))
    if rounded < 60:
        return f"about {rounded} min"
    hours, mins = divmod(rounded, 60)
    return f"about {hours} h {mins} min"


def _build() -> str:
    spans = _spans()
    queue = _queue()
    now = datetime.now(timezone.utc)
    sessions = []
    total_weight = 0.0
    done_weight = 0.0
    active_name = None
    eta_min = 0.0
    failed = None

    for span in spans:
        hours = span["seconds"] / 3600
        steps = []
        session_weight = 0.0
        session_done = 0.0
        current = "Waiting"
        for step, label in STEPS:
            weight = STEP_MIN_PER_HOUR[step] * hours
            key = f"{span['id']}_{step}"
            slot = queue.get(key)
            if slot and slot["exit"] == 0:
                frac = 1.0
                status = "done"
            elif slot and slot["exit"] not in (None, 0):
                frac = 1.0
                status = "failed"
                failed = f"{span['title']} {label} exited {slot['exit']}"
            elif slot and slot["started"]:
                frac = _log_fraction(span["id"], step, span["seconds"]) or 0.0
                status = "running"
                current = label
                active_name = f"{span['title']} · {label}"
            else:
                frac = 0.0
                status = "waiting"
            steps.append({"label": label, "weight": weight, "frac": frac, "status": status})
            session_weight += weight
            session_done += weight * frac
            eta_min += weight * (1 - frac)
        hashed = (FREEZE / f"{span['id']}.json").is_file()
        if hashed:
            current = "Hashed"
        elif all(step["status"] == "done" for step in steps):
            current = "Hashing"
        frac = session_done / session_weight if session_weight else 0.0
        total_weight += session_weight
        done_weight += session_done
        sessions.append({**span, "steps": steps, "frac": frac, "current": current, "hashed": hashed})

    overall = done_weight / total_weight if total_weight else 0.0
    stamp = now.astimezone().strftime("%-I:%M:%S %p")
    rows = []
    for session in sessions:
        bits = []
        for step in session["steps"]:
            width = 100 * step["weight"] / sum(item["weight"] for item in session["steps"])
            fill = 100 * step["frac"]
            bits.append(
                f'<div class="seg" style="width:{width:.2f}%" title="{step["label"]}">'
                f'<div class="fill {step["status"]}" style="width:{fill:.1f}%"></div></div>'
            )
        rows.append(
            "<section>"
            f'<div class="row"><strong>{session["title"]}</strong>'
            f'<span class="detail">{session["detail"]}</span>'
            f'<span class="pct">{session["frac"] * 100:.0f}%</span></div>'
            f'<div class="track">{"".join(bits)}</div>'
            f'<div class="sub">{session["current"]}</div>'
            "</section>"
        )
    headline = failed or active_name or "Finished"
    eta = "Queue stopped." if failed else ("Nothing left in the queue." if overall >= 0.999 else f"{_fmt_min(eta_min)} left in the queue.")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta http-equiv="refresh" content="8">
<title>OHush replication progress</title>
<style>
  body {{ margin: 0; font: 15px/1.4 -apple-system, BlinkMacSystemFont, sans-serif; background: #160a20; color: #f4eef8; }}
  main {{ max-width: 680px; margin: 0 auto; padding: 36px 20px 64px; }}
  .brand-logo {{ height: 52px; width: auto; display: block; margin: 0 0 22px; }}
  h1 {{ font-size: 22px; font-weight: 600; margin: 0 0 4px; }}
  .muted {{ color: #c4b4d4; font-size: 13px; }}
  .overall {{ margin: 28px 0 8px; }}
  .track {{ display: flex; gap: 3px; height: 16px; }}
  .seg {{ background: #2a1244; height: 100%; }}
  .fill {{ height: 100%; background: #844cce; }}
  .fill.done {{ background: #2f8f62; }}
  .fill.failed {{ background: #b42318; }}
  .fill.waiting {{ width: 0; }}
  section {{ margin-top: 22px; }}
  .row {{ display: flex; align-items: baseline; gap: 8px; margin-bottom: 6px; }}
  .detail {{ color: #c4b4d4; flex: 1; }}
  .pct {{ font-variant-numeric: tabular-nums; }}
  .sub {{ color: #e4d8f2; font-size: 13px; margin-top: 6px; }}
  .legend {{ display: flex; gap: 16px; margin-top: 28px; color: #c4b4d4; font-size: 12px; }}
  .swatch {{ display: inline-block; width: 10px; height: 10px; margin-right: 6px; vertical-align: -1px; background: #844cce; }}
  .swatch.done {{ background: #2f8f62; }}
</style>
</head>
<body>
<main>
  {_brand_logo()}
  <h1>{headline}</h1>
  <div class="muted">Updated {stamp} · refreshes every 8 seconds · {eta}</div>
  <div class="overall muted">Whole queue · {overall * 100:.0f}%</div>
  <div class="track"><div class="seg" style="width:100%"><div class="fill {"failed" if failed else "running"}" style="width:{overall * 100:.1f}%"></div></div></div>
  {"".join(rows)}
  <div class="legend"><span><i class="swatch"></i>Running</span><span><i class="swatch done"></i>Finished</span><span>Each bar is speakers, audio world, frozen cloud, then language.</span></div>
</main>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        body = _build().encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args) -> None:
        return


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"progress http://127.0.0.1:{PORT}/", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
