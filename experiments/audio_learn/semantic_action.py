"""Volume action on the saved causal transcripts.

The transcripts, windows, and clocks are the rows already written by
semantic_probe.py. This file does not transcribe again and does not change
the acoustic champion. The task wording below is frozen. It is not edited
after a model's answers are read.

    C:\\Python313\\python.exe -m experiments.audio_learn.semantic_action qwen2.5:14b
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

DATA = Path(r"C:\OHushData\gpu_lab\audio_learn\semantic_probe")
URL = "http://127.0.0.1:11434/api/generate"
PROMPT = """The transcript is the only audio a television has heard in the last few seconds of a live NFL broadcast. It ends now. Nothing after it has been heard.

Choose the first-version volume action for the end of the transcript.

Reply with one JSON object and no other text:
{"action":"play"|"mute"|"unknown"}

play = legitimate programming. The game, play-by-play, a studio or desk discussion, halftime, a postgame show, highlights, an interview, or a host who keeps talking after naming a sponsor. "Presented by" and "brought to you by" are play when the show is what is being presented.
mute = a standalone commercial or a standalone promo. A pitch for a product, store, card, restaurant, movie, app, or a different show. Mentioning football, players, or games does not make a pitch into the show.
unknown = the words are not enough. A fragment, a name, or an unfinished sentence stays unknown. Unknown does not mean the audio is safe to mute, and it does not mean the audio is the show.

Transcript:
<<TEXT>>
"""


def _ask(model: str, text: str) -> tuple[str, float, float]:
    shown = text.strip() or "(no speech)"
    body = json.dumps(
        {
            "model": model,
            "prompt": PROMPT.replace("<<TEXT>>", shown[:1200]),
            "stream": False,
            "format": "json",
            "keep_alive": "30m",
            "options": {"temperature": 0, "num_predict": 60},
        }
    ).encode()
    request = urllib.request.Request(URL, data=body, headers={"Content-Type": "application/json"})
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=180) as response:
        raw = json.loads(response.read().decode())
    wall = time.perf_counter() - started
    try:
        payload = json.loads(raw.get("response") or "{}")
        action = str(payload.get("action") or "").strip().lower()
    except json.JSONDecodeError:
        action = "parse_error"
    if action not in {"play", "mute", "unknown"}:
        action = "parse_error"
    reported = float(raw.get("total_duration") or 0) / 1e9
    return action, round(reported or wall, 3), round(wall, 3)


def main() -> None:
    model = sys.argv[1]
    slug = model.replace(":", "_").replace("/", "_")
    rows = [
        json.loads(line)
        for line in (DATA / "rows.jsonl").read_text(encoding="utf-8").splitlines()
        if line
    ]
    out = []
    for row in rows:
        action, infer_s, wall_s = _ask(model, row["text"])
        saved = {
            "id": row["id"],
            "split": row["split"],
            "role": row["role"],
            "kind": row["kind"],
            "horizon_s": row["horizon_s"],
            "frozen_p": row.get("frozen_p"),
            "old_label": row["label"],
            "action": action,
            "infer_s": infer_s,
            "wall_s": wall_s,
            "whisper_s": row["whisper_s"],
            "text": row["text"],
            "model": model,
        }
        out.append(saved)
        print(
            f"{row['id']:22} {action:8} {infer_s:6.2f}s  {row['text'][:100]}",
            flush=True,
        )
    path = DATA / f"action_{slug}.jsonl"
    path.write_text("".join(json.dumps(item) + "\n" for item in out), encoding="utf-8")
    print("wrote", len(out), path, flush=True)


if __name__ == "__main__":
    main()
