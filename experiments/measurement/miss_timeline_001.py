"""A four-second trace through every missed football start.

Each step is one window already scored for speech and music. The step
records who from that show's booth is in it, how loud and how high the
voice is, and the words when a transcript exists. A change is just the
step where that pattern moves. No new line. No mute.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy.signal import resample_poly

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from experiments.broadcast_intelligence.batch1 import read_span  # noqa: E402
from experiments.measurement.atomic_miss_001 import pitch, spectrum  # noqa: E402
from experiments.measurement.show_roster_001 import SESSION_SHOW  # noqa: E402
from experiments.measurement.verified_speaker_001 import (  # noqa: E402
    assign,
    latest_names,
    load_windows,
    prototype,
    spans_from,
)
from experiments.universal_v4.speaker_enrollment import person_name  # noqa: E402
from hush.audio import find_session  # noqa: E402
from hush.show_roster import SHOWS  # noqa: E402
from hush.speaker_memory import MATCH_COSINE  # noqa: E402

OUT = REPO / "docs/ohush/research/START_END_001"
SCORES = REPO / "docs/ohush/research/SONG_TRANSITION_001/scores.jsonl"
SR = 48000
BEFORE = 60.0
AFTER = 20.0
MUSIC_LOW = 0.30
MUSIC_HIGH = 0.70


def prototypes():
    spans = []
    for row in latest_names():
        spans.extend(spans_from(row))
    by_session = defaultdict(list)
    for span in spans:
        by_session[span["session"]].append(span)
    owned = []
    for session, group in by_session.items():
        path = REPO / "experiments/exp002" / session / "speaker_segments.parquet"
        if not path.exists():
            continue
        windows = load_windows(session)
        for row in assign(windows, group):
            name = person_name(row)
            if name:
                owned.append({**row, "person": name})
    built = {}
    for show, names in SHOWS.items():
        for name in names:
            group = [row for row in owned if row["person"] == name]
            proto = prototype(group)
            if proto is not None:
                built.setdefault(show, {})[name] = proto
    return built


def booth_at(windows, bank, t0, t1):
    if windows is None or not bank:
        return {"name": None, "cosine": None, "present": False}
    names = list(bank)
    matrix = np.vstack([bank[name] for name in names])
    best_name, best_score, seen = None, -1.0, False
    for index, (start, end) in enumerate(zip(windows["start"], windows["end"])):
        mid = (float(start) + float(end)) / 2
        if mid < t0 or mid >= t1:
            continue
        seen = True
        scores = windows["vector"][index] @ matrix.T
        winner = int(np.argmax(scores))
        if float(scores[winner]) > best_score:
            best_score = float(scores[winner])
            best_name = names[winner]
    if not seen:
        return {"name": None, "cosine": None, "present": False, "speech_window": False}
    return {
        "name": best_name,
        "cosine": round(best_score, 3),
        "present": best_score >= MATCH_COSINE,
        "speech_window": True,
    }


def words_at(table, t0, t1):
    if table is None:
        return None
    chosen = [
        row.text.strip()
        for row in table.itertuples(index=False)
        if row.start < t1 and row.end > t0 and str(row.text).strip()
    ]
    return " ".join(chosen)[:180]


def pattern(step):
    music = step["music"]
    booth = step["booth"]["present"]
    if booth and music >= MUSIC_HIGH:
        return "booth_over_song"
    if booth and music < MUSIC_LOW:
        return "booth_over_quiet"
    if booth:
        return "booth"
    if music >= MUSIC_HIGH:
        return "song_without_booth"
    if music < MUSIC_LOW:
        return "quiet_without_booth"
    return "in_between"


def cadence(y):
    hop = int(SR * 0.02)
    env = np.array([np.sqrt(np.mean(y[i:i + hop] ** 2)) for i in range(0, max(len(y) - hop, 0), hop)])
    if len(env) < 10:
        return None, None
    env = env - env.mean()
    if float(env.std()) < 1e-8:
        return None, None
    corr = np.correlate(env, env, mode="full")
    corr = corr[len(corr) // 2:]
    lo, hi = int(0.3 / 0.02), min(int(1.5 / 0.02), len(corr) - 1)
    if hi <= lo:
        return None, None
    lag = lo + int(np.argmax(corr[lo:hi]))
    return round(lag * 0.02, 3), round(float(corr[lag] / corr[0]), 3)


def main():
    import pandas as pd

    scores = defaultdict(list)
    for line in SCORES.read_text().splitlines():
        if not line:
            continue
        row = json.loads(line)
        if row.get("kind"):
            continue
        scores[row["session"]].append((row["t"], row["speech"], row["music"]))
    banks = prototypes()
    misses = []
    for line in (OUT / "receipts.jsonl").read_text().splitlines():
        row = json.loads(line)
        if not row["start_caught"]:
            misses.append(row)
    cache, words, speakers = {}, {}, {}
    written = []
    for nth, row in enumerate(misses, start=1):
        sid = row["session"]
        if sid not in cache:
            folder = find_session(REPO / "recordings", sid)
            cache[sid] = (folder, json.loads((folder / "session.json").read_text()))
            word_path = REPO / "experiments/exp005" / sid / "words.parquet"
            words[sid] = pd.read_parquet(word_path) if word_path.exists() else None
            speakers[sid] = load_windows(sid) if (REPO / "experiments/exp002" / sid / "speaker_segments.parquet").exists() else None
        start = float(row["start"])
        window_scores = [item for item in scores[sid] if start - BEFORE < item[0] <= start + AFTER]
        folder, meta = cache[sid]
        origin = max(0.0, start - BEFORE)
        try:
            audio = read_span(folder, meta, origin, start + AFTER).mean(axis=1).astype(np.float32)
        except Exception as exc:
            written.append({**row, "timeline_error": str(exc)})
            continue
        show = SESSION_SHOW.get(sid)
        bank = banks.get(show, {})
        steps = []
        for t, speech, music in window_scores:
            a = int(round((t - 4 - origin) * SR))
            b = int(round((t - origin) * SR))
            if a < 0 or b > len(audio):
                piece = None
            else:
                piece = audio[a:b]
            tone = {}
            if piece is not None and len(piece) > SR:
                rms = float(np.sqrt(np.mean(piece * piece) + 1e-12))
                tone = spectrum(piece)
                gap, strength = cadence(piece)
                tone.update({
                    "rms_db": round(20 * np.log10(rms), 2),
                    "pitch_hz": pitch(piece),
                    "cadence_s": gap,
                    "cadence_strength": strength,
                })
            who = booth_at(speakers[sid], bank, t - 4, t)
            step = {
                "t": t,
                "rel_s": round(t - start, 3),
                "speech": speech,
                "music": music,
                "booth": who,
                "words": words_at(words[sid], t - 4, t),
                **tone,
            }
            step["pattern"] = pattern(step)
            if steps:
                prev = steps[-1]
                changes = []
                if prev["music"] < MUSIC_LOW and music >= MUSIC_HIGH:
                    changes.append("music_rose")
                if prev["music"] >= MUSIC_HIGH and music < MUSIC_LOW:
                    changes.append("music_fell")
                if prev["booth"]["present"] and not who["present"]:
                    changes.append("booth_left")
                if who["present"] and not prev["booth"]["present"]:
                    changes.append("booth_returned")
                if speech - prev["speech"] >= 0.30:
                    changes.append("speech_rose")
                if prev["speech"] - speech >= 0.30:
                    changes.append("speech_fell")
                if prev["pattern"] != step["pattern"]:
                    changes.append(f"pattern:{prev['pattern']}->{step['pattern']}")
                step["changes"] = changes
            else:
                step["changes"] = []
            steps.append(step)
        first = {}
        for kind in ("music_rose", "music_fell", "booth_left", "booth_returned", "speech_rose", "speech_fell"):
            hit = next((step["rel_s"] for step in steps if kind in step["changes"]), None)
            first[kind] = hit
        pattern_change = next((step["rel_s"] for step in steps if any(item.startswith("pattern:") for item in step["changes"])), None)
        written.append({
            "session": sid,
            "network": row["network"],
            "start": row["start"],
            "end": row["end"],
            "show": show,
            "word_source": "full_transcript" if words[sid] is not None else "no_timeline_transcript",
            "steps": steps,
            "first_change_rel_s": first,
            "first_pattern_change_rel_s": pattern_change,
        })
        if nth % 20 == 0:
            print(f"trace {nth}/{len(misses)}", flush=True)
    path = OUT / "timeline_receipts.jsonl"
    with path.open("w", encoding="utf-8") as handle:
        for row in written:
            handle.write(json.dumps(row) + "\n")
    print("wrote", len(written), flush=True)


if __name__ == "__main__":
    main()
