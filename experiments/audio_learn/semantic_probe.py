"""Causal speech-meaning probe. The local 3B model sees a transcript and nothing else.

Audio for a decision at time t is exactly [t - horizon, t]. Whisper never receives
samples after t. The language-model call is timed separately. Prime rows are a
regression read. The prompt is fixed; it is not edited from those rows.

    C:\\Python313\\python.exe -m experiments.audio_learn.semantic_probe
"""

from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path

import numpy as np

from experiments.measurement.metrics import target_commercials
from experiments.nfl75.inventory import active_intervals
from tools.gpu_lab.audio_load import load_coverage

DATA = Path(r"C:\OHushData\gpu_lab\audio_learn\semantic_probe")
MODEL = "qwen2.5:3b"
URL = "http://127.0.0.1:11434/api/generate"
PROMPT = """The transcript is the only audio a television has heard in the last few seconds of a live NFL broadcast. It ends now. Nothing after it has been heard.

What is on the air at the end of the transcript?

Reply with one JSON object and no other text:
{"label":"program"|"sponsorship"|"ad"|"unsure"}

program = the game, the booth, a studio, halftime, highlights, or an interview. A host may name a sponsor and still be the show.
sponsorship = the show is on, and the words are mainly naming a sponsor ("brought to you by", "presented by") before the show continues.
ad = a standalone commercial pitching a product, store, movie, app, or a different program. Mentioning football does not turn a pitch into the show.
unsure = these words do not say which.

Transcript:
<<TEXT>>
"""

# role is the product target. kind is the reporting bucket.
# split "dev" is training broadcasts. split "prime" is the regression read.
CASES = [
    ("dev_pregame", "dev", "program", "studio", "hush_20260909_213047", 940.0, 8.0),
    ("dev_halftime", "dev", "program", "studio", "hush_20260913_210542", 3360.0, 8.0),
    ("dev_halftime_20", "dev", "program", "studio", "hush_20260913_210542", 3360.0, 20.0),
    ("dev_postgame", "dev", "program", "studio", "hush_20260913_210542", 9000.0, 8.0),
    ("dev_redzone", "dev", "program", "studio", "hush_20260913_150934", 6365.0, 8.0),
    ("dev_live_kick", "dev", "program", "live", "hush_20260909_213047", 2255.0, 8.0),
    ("dev_live_booth", "dev", "program", "live", "hush_20260913_210542", 8485.0, 8.0),
    ("dev_highlights", "dev", "program", "highlights", "hush_20261012_204200", 3510.0, 8.0),
    ("dev_toyota_open", "dev", "sponsorship", "sponsorship", "hush_20260909_213047", 818.0, 8.0),
    ("dev_highlights_by", "dev", "sponsorship", "sponsorship", "hush_20261011_135700", 2650.0, 8.0),
    ("dev_sunday_ticket", "dev", "ad", "football_ad", "hush_20260909_213047", 1262.0, 8.0),
    ("dev_platinum", "dev", "ad", "football_ad", "hush_20260913_210542", 1018.0, 8.0),
    ("dev_progressive", "dev", "ad", "ad", "hush_20260913_210542", 3765.0, 8.0),
    ("dev_traitors", "dev", "ad", "ad", "hush_20260913_210542", 8415.0, 8.0),
    ("dev_right_back", "dev", "program", "transition", "hush_20260913_150934", 6328.0, 8.0),
    ("dev_netflix_promo", "dev", "show_promo", "show_promo", "hush_20260909_213047", 7872.0, 8.0),
    ("dev_local_news", "dev", "other", "other", "hush_20260909_213047", 8635.0, 8.0),
    ("prime_odell_on_8", "prime", "program", "studio", "hush_20260924_220624", 7035.0, 8.0),
    ("prime_odell_on_20", "prime", "program", "studio", "hush_20260924_220624", 7035.0, 20.0),
    ("prime_odell_mid_8", "prime", "program", "studio", "hush_20260924_220624", 7065.0, 8.0),
    ("prime_odell_mid_20", "prime", "program", "studio", "hush_20260924_220624", 7065.0, 20.0),
    ("prime_whit_on_8", "prime", "program", "studio", "hush_20260924_220624", 7407.0, 8.0),
    ("prime_whit_on_20", "prime", "program", "studio", "hush_20260924_220624", 7407.0, 20.0),
    ("prime_whit_mid_8", "prime", "program", "studio", "hush_20260924_220624", 7422.0, 8.0),
    ("prime_palmer_on_8", "prime", "program", "studio", "hush_20260924_220624", 6181.0, 8.0),
    ("prime_palmer_on_20", "prime", "program", "studio", "hush_20260924_220624", 6181.0, 20.0),
    ("prime_palmer_mid_8", "prime", "program", "studio", "hush_20260924_220624", 6194.0, 8.0),
    ("prime_highlights", "prime", "program", "highlights", "hush_20260924_220624", 5040.0, 8.0),
    ("prime_injury", "prime", "program", "studio", "hush_20260924_220624", 6280.0, 8.0),
    ("prime_live_08", "prime", "program", "live", "hush_20261008_205100", 2508.0, 8.0),
    ("prime_live_24", "prime", "program", "live", "hush_20260924_220624", 1208.0, 8.0),
    ("prime_amex_8", "prime", "ad", "football_ad", "hush_20261008_205100", 3405.0, 8.0),
    ("prime_amex_20", "prime", "ad", "football_ad", "hush_20261008_205100", 3405.0, 20.0),
    ("prime_chilis", "prime", "ad", "ad", "hush_20260924_220624", 2990.0, 8.0),
    ("prime_carrie", "prime", "ad", "ad", "hush_20261008_205100", 4986.0, 8.0),
    ("prime_draftkings", "prime", "ad", "football_ad", "hush_20261008_205100", 168.0, 8.0),
    ("prime_nfl_plus", "prime", "ad", "football_ad", "hush_20261008_205100", 4976.0, 8.0),
    ("prime_state_farm", "prime", "sponsorship", "sponsorship", "hush_20261008_205100", 3472.0, 8.0),
    ("prime_chatgpt", "prime", "sponsorship", "sponsorship", "hush_20260924_220624", 1618.0, 8.0),
    ("prime_iphone", "prime", "sponsorship", "sponsorship", "hush_20261008_205100", 3706.0, 8.0),
    ("prime_welcome_back", "prime", "program", "transition", "hush_20261008_205100", 3442.0, 8.0),
    ("prime_quick_break", "prime", "program", "transition", "hush_20261008_205100", 3374.0, 8.0),
    ("prime_next_week", "prime", "show_promo", "show_promo", "hush_20260924_220624", 4485.0, 8.0),
]


def _gold_ads() -> list[tuple]:
    rows = []
    sessions = (
        "hush_20260909_213047",
        "hush_20260913_210542",
        "hush_20261011_135700",
        "hush_20261012_204200",
    )
    for session in sessions:
        breaks = [pair for pair in target_commercials(active_intervals(session)) if pair[1] - pair[0] >= 30]
        if not breaks:
            continue
        start, end = breaks[min(1, len(breaks) - 1)]
        moment = round((start + end) / 2, 1)
        rows.append((f"dev_break_{session[-6:]}", "dev", "ad", "ad", session, moment, 8.0))
    return rows


def _ask(text: str) -> tuple[str, float]:
    shown = text.strip() or "(no speech)"
    body = json.dumps(
        {
            "model": MODEL,
            "prompt": PROMPT.replace("<<TEXT>>", shown[:1200]),
            "stream": False,
            "format": "json",
            "keep_alive": "30m",
            "options": {"temperature": 0, "num_predict": 40},
        }
    ).encode()
    request = urllib.request.Request(URL, data=body, headers={"Content-Type": "application/json"})
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=90) as response:
        raw = json.loads(response.read().decode())
    wall = time.perf_counter() - started
    try:
        payload = json.loads(raw.get("response") or "{}")
        label = str(payload.get("label") or "").strip().lower()
    except json.JSONDecodeError:
        label = "parse_error"
    if label not in {"program", "sponsorship", "ad", "unsure"}:
        label = "parse_error"
    reported = float(raw.get("total_duration") or 0) / 1e9
    return label, round(reported or wall, 3)


def _frozen_p(session: str, moment: float) -> float | None:
    path = Path(r"C:\OHushData\gpu_lab\audio_learn\predictions\frozen") / f"{session}.npz"
    if not path.is_file():
        return None
    data = np.load(path)
    index = int(np.argmin(np.abs(data["t"] - moment)))
    if abs(float(data["t"][index]) - moment) > 2:
        return None
    return round(float(data["p"][index]), 3)


def main() -> None:
    from faster_whisper import WhisperModel

    DATA.mkdir(parents=True, exist_ok=True)
    cases = list(CASES) + _gold_ads()
    model = WhisperModel("base.en", device="cpu", compute_type="int8", cpu_threads=4)
    rows = []
    for case_id, split, role, kind, session, moment, horizon in cases:
        audio = load_coverage(session, moment - horizon, moment)
        started = time.perf_counter()
        segments, _info = model.transcribe(audio, vad_filter=True, beam_size=1)
        whisper_s = round(time.perf_counter() - started, 3)
        text = " ".join(segment.text.strip() for segment in segments if segment.text.strip())
        label, infer_s = _ask(text)
        row = {
            "id": case_id,
            "split": split,
            "role": role,
            "kind": kind,
            "session": session,
            "t": moment,
            "horizon_s": horizon,
            "text": text,
            "label": label,
            "whisper_s": whisper_s,
            "infer_s": infer_s,
            "available_after_s": round(whisper_s + infer_s, 3),
            "frozen_p": _frozen_p(session, moment),
        }
        rows.append(row)
        print(f"{case_id:22} {label:12} {whisper_s:5.2f}s+{infer_s:5.2f}s  {text[:110]}", flush=True)
    (DATA / "rows.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    print("wrote", len(rows), flush=True)


if __name__ == "__main__":
    main()
