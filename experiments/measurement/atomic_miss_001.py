"""Atomic before/after receipt for every missed football start.

The four seconds before the labeled cut are the game. The four seconds
after it are the commercial. Pitch, rhythm, loudness, the show's own booth,
and the words are written on the failure. No new threshold. No mute.
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

from experiments.broadcast_intelligence.batch1 import coverage, read_span  # noqa: E402
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
RECEIPTS = OUT / "receipts.jsonl"
SR = 48000
BEFORE = 4.0
AFTER = 4.0


def spectrum(y):
    n = 2048
    hop = 1024
    window = np.hanning(n)
    cents, flats, flux = [], [], []
    prev = None
    for i in range(0, len(y) - n, hop):
        spec = np.abs(np.fft.rfft(y[i:i + n] * window))
        freqs = np.fft.rfftfreq(n, 1 / SR)
        power = spec ** 2 + 1e-12
        cents.append(float(np.sum(freqs * power) / np.sum(power)))
        flats.append(float(np.exp(np.mean(np.log(power))) / np.mean(power)))
        if prev is not None:
            flux.append(float(np.mean(np.maximum(0, spec - prev))))
        prev = spec
    return {
        "centroid_hz": None if not cents else round(float(np.median(cents)), 1),
        "flatness": None if not flats else round(float(np.median(flats)), 4),
        "flux": None if not flux else round(float(np.mean(flux)), 5),
    }


def pitch(y):
    y8 = resample_poly(y, 1, 6).astype(np.float64)
    sr = 8000
    frame, hop = 320, 160
    found = []
    minlag, maxlag = int(sr / 400), int(sr / 70)
    for i in range(0, len(y8) - frame, hop):
        seg = y8[i:i + frame]
        if np.sqrt(np.mean(seg * seg)) < 0.01:
            continue
        seg = seg - seg.mean()
        corr = np.correlate(seg, seg, mode="full")[frame - 1:]
        if corr[0] <= 0:
            continue
        lag = minlag + int(np.argmax(corr[minlag:maxlag]))
        peak = corr[lag] / corr[0]
        if peak > 0.3:
            found.append(sr / lag)
    return None if not found else round(float(np.median(found)), 1)


def rhythm(y):
    hop = int(SR * 0.01)
    env = np.array([
        np.sqrt(np.mean(y[i:i + hop] ** 2))
        for i in range(0, len(y) - hop, hop)
    ])
    if len(env) < 5:
        return None
    line = float(np.median(env) + np.std(env))
    peaks = [
        i for i in range(1, len(env) - 1)
        if env[i] >= line and env[i] >= env[i - 1] and env[i] > env[i + 1]
    ]
    if len(peaks) < 2:
        return None
    gaps = np.diff(peaks) * 0.01
    return round(float(np.median(gaps)), 3)


def side(y):
    rms = float(np.sqrt(np.mean(y * y) + 1e-12))
    body = spectrum(y)
    body.update({
        "rms_db": round(20 * np.log10(rms), 2),
        "pitch_hz": pitch(y),
        "beat_gap_s": rhythm(y),
    })
    return body


def words_between(table, t0, t1):
    if table is None:
        return None
    chosen = [row.text.strip() for row in table.itertuples(index=False) if row.start < t1 and row.end > t0 and row.text.strip()]
    text = " ".join(chosen)
    return text[:400]


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


def booth(windows, show, prototypes_for_show, t0, t1):
    if windows is None or not prototypes_for_show:
        return None
    names = list(prototypes_for_show)
    matrix = np.vstack([prototypes_for_show[name] for name in names])
    best_name, best_score = None, -1.0
    for index, (start, end) in enumerate(zip(windows["start"], windows["end"])):
        mid = (float(start) + float(end)) / 2
        if mid < t0 or mid >= t1:
            continue
        scores = windows["vector"][index] @ matrix.T
        winner = int(np.argmax(scores))
        if float(scores[winner]) > best_score:
            best_score = float(scores[winner])
            best_name = names[winner]
    if best_name is None:
        return {"name": None, "cosine": None, "booth_present": False, "reason": "no_speech_window"}
    return {
        "name": best_name,
        "cosine": round(best_score, 3),
        "booth_present": best_score >= MATCH_COSINE,
    }


def main():
    import pandas as pd
    from faster_whisper import WhisperModel

    misses = []
    for line in RECEIPTS.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if not row["start_caught"]:
            misses.append(row)
    spans = {row["session"]: (float(row["from_seconds"]), float(row["to_seconds"])) for row in coverage()}
    banks = prototypes()
    cache = {}
    words = {}
    speakers = {}
    model = None
    out_rows = []
    for index, row in enumerate(misses, start=1):
        sid = row["session"]
        if sid not in cache:
            folder = find_session(REPO / "recordings", sid)
            cache[sid] = (folder, json.loads((folder / "session.json").read_text()))
            word_path = REPO / "experiments/exp005" / sid / "words.parquet"
            words[sid] = pd.read_parquet(word_path) if word_path.exists() else None
            spk = REPO / "experiments/exp002" / sid / "speaker_segments.parquet"
            speakers[sid] = load_windows(sid) if spk.exists() else None
        folder, meta = cache[sid]
        start = row["start"]
        try:
            audio = read_span(folder, meta, start - BEFORE, start + AFTER).mean(axis=1).astype(np.float32)
        except Exception as exc:
            row["atomic"] = {"error": str(exc)}
            out_rows.append(row)
            continue
        cut = int(BEFORE * SR)
        if len(audio) < cut + int(AFTER * SR * 0.5):
            row["atomic"] = {"error": "short_read", "samples": int(len(audio))}
            out_rows.append(row)
            continue
        before = side(audio[:cut])
        after = side(audio[cut:cut + int(AFTER * SR)])
        show = SESSION_SHOW.get(sid)
        booth_bank = banks.get(show, {})
        before_words = words_between(words[sid], start - BEFORE, start)
        after_words = words_between(words[sid], start, start + AFTER)
        word_source = "existing" if words[sid] is not None else None
        if word_source is None:
            if model is None:
                model = WhisperModel(
                    "medium.en",
                    device="cpu",
                    compute_type="int8",
                    cpu_threads=8,
                    download_root=str(REPO / "experiments/exp005/models"),
                )
            clip = resample_poly(audio[:cut + int(AFTER * SR)], 1, 3).astype(np.float32)
            segments, _info = model.transcribe(
                clip, language="en", word_timestamps=True, vad_filter=False,
                beam_size=5, temperature=0.0, condition_on_previous_text=False,
            )
            before_bits, after_bits = [], []
            for segment in segments:
                for word in segment.words or []:
                    token = word.word.strip()
                    if not token:
                        continue
                    if word.end <= BEFORE:
                        before_bits.append(token)
                    elif word.start >= BEFORE:
                        after_bits.append(token)
            before_words = " ".join(before_bits)[:400]
            after_words = " ".join(after_bits)[:400]
            word_source = "whisper_medium_en_on_the_8s_clip"
        cov0, cov1 = spans[sid]
        row["atomic"] = {
            "window_s": [ -BEFORE, AFTER ],
            "show": show,
            "broadcast_fraction": round((start - cov0) / max(cov1 - cov0, 1), 3),
            "game_clock": "not_in_the_audio_ledger",
            "before": before,
            "after": after,
            "booth_before": booth(speakers[sid], show, booth_bank, start - BEFORE, start),
            "booth_after": booth(speakers[sid], show, booth_bank, start, start + AFTER),
            "words_before": before_words,
            "words_after": after_words,
            "word_source": word_source,
        }
        out_rows.append(row)
        if index % 10 == 0:
            print(f"atom {index}/{len(misses)}", flush=True)
    path = OUT / "atomic_receipts.jsonl"
    with path.open("w", encoding="utf-8") as handle:
        for row in out_rows:
            handle.write(json.dumps(row) + "\n")
    print("wrote", path, "rows", len(out_rows), flush=True)


if __name__ == "__main__":
    main()
