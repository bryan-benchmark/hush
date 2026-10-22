"""Voice over a song in the minute before a labeled football break.

The AudioSet speech and music heads are the ones already in the project.
They are not refit. Lines were taken from the Prime sign-off at 234 seconds,
which had already been listened to: music at least 0.70 and speech at least
0.50, on a 4-second window. This run applies those lines. It does not search
a new cutoff. Holdouts stay closed. Nothing here mutes.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import torch
from scipy.signal import resample_poly

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from experiments.broadcast_intelligence.batch1 import commercials, coverage, load_catalog, read_span  # noqa: E402
from hush.audio import find_session  # noqa: E402

OUT = REPO / "docs/ohush/research/VOICE_OVER_SONG_001"
CHECKPOINT = REPO / "experiments/exp003/models/Cnn14_mAP=0.431.pth"
REDZONE = "hush_20260913_150934"
HORIZONS = (60, 30, 20, 10, 5, 3, 2, 1)
WINDOW = 4.0
MUSIC_LINE = 0.70
SPEECH_LINE = 0.50
SPEECH, MUSIC, CROWD, BED = 0, 137, 69, 267


def sports_breaks():
    catalog = load_catalog()
    chosen = []
    for row in commercials(coverage()):
        cat = catalog.get(row["session"], {})
        if cat.get("content_type") != "sports":
            continue
        if row["session"] == REDZONE:
            continue
        chosen.append(row)
    return chosen


def pods_by_session(rows):
    pods = {}
    for row in rows:
        pods.setdefault(row["session"], []).append((float(row["start_seconds"]), float(row["end_seconds"])))
    return pods


class Tagger:
    def __init__(self):
        torch.backends.nnpack.set_flags(False)
        torch.set_num_threads(4)
        from panns_inference import AudioTagging

        self.model = AudioTagging(checkpoint_path=str(CHECKPOINT), device="cpu")
        self.cache = {}

    def _mono(self, session, t0, t1):
        if session not in self.cache:
            folder = find_session(REPO / "recordings", session)
            self.cache[session] = (folder, json.loads((folder / "session.json").read_text()))
        folder, meta = self.cache[session]
        audio = read_span(folder, meta, t0, t1).mean(axis=1).astype(np.float32)
        y = resample_poly(audio, 2, 3).astype(np.float32)
        need = 320000
        if len(y) < need:
            y = np.pad(y, (0, need - len(y)))
        return y[:need]

    def score(self, session, t0, t1):
        y = self._mono(session, t0, t1)
        clipwise, _ = self.model.inference(y[None, :])
        p = np.asarray(clipwise)[0]
        speech, music, crowd, bed = (float(p[i]) for i in (SPEECH, MUSIC, CROWD, BED))
        return {
            "speech": round(speech, 4),
            "music": round(music, 4),
            "crowd": round(crowd, 4),
            "background_music": round(bed, 4),
            "voice_over_song": bool(speech >= SPEECH_LINE and music >= MUSIC_LINE),
        }


def program_probes(pods, limit=180):
    probes = []
    for sid, intervals in pods.items():
        spans = [s for s in coverage() if s["session"] == sid and s.get("fully_annotated")]
        for span in spans:
            t = float(span["from_seconds"]) + 30
            stop = float(span["to_seconds"]) - 5
            while t < stop and len(probes) < limit:
                if any(a - 30 <= t <= b + 30 for a, b in intervals):
                    t += 120
                    continue
                probes.append((sid, t))
                t += 120
    return probes


def redzone_probes(limit=40):
    probes = []
    spans = [s for s in coverage() if s["session"] == REDZONE and s.get("fully_annotated")]
    for span in spans:
        t = float(span["from_seconds"]) + 30
        stop = float(span["to_seconds"]) - 5
        while t < stop and len(probes) < limit:
            probes.append((REDZONE, t))
            t += 150
    return probes


def main():
    rows = sports_breaks()
    pods = pods_by_session(rows)
    tagger = Tagger()
    break_rows = []
    failed = 0
    for row in rows:
        t = float(row["start_seconds"])
        horizons = {}
        ok = True
        for h in HORIZONS:
            t1 = t - h
            t0 = t1 - WINDOW
            if t0 < 0.2:
                ok = False
                break
            try:
                horizons[str(h)] = tagger.score(row["session"], t0, t1)
            except Exception as exc:
                horizons[str(h)] = {"error": str(exc)}
                ok = False
        after = None
        try:
            after = tagger.score(row["session"], t + 0.5, t + 0.5 + WINDOW)
        except Exception as exc:
            after = {"error": str(exc)}
            ok = False
        if not ok and any("error" in v for v in list(horizons.values()) + [after or {}]):
            failed += 1
        break_rows.append({
            "session": row["session"],
            "t": round(t, 3),
            "horizons": horizons,
            "after": after,
        })
        if len(break_rows) % 20 == 0:
            print(f"breaks {len(break_rows)}", flush=True)

    def probe_rows(pairs, label):
        out = []
        for sid, t in pairs:
            try:
                scored = tagger.score(sid, t - WINDOW, t)
            except Exception as exc:
                scored = {"error": str(exc)}
            out.append({"session": sid, "t": round(t, 3), **scored} if "error" not in scored else {"session": sid, "t": round(t, 3), "error": scored["error"]})
        print(label, len(out), flush=True)
        return out

    play = probe_rows(program_probes(pods), "play")
    zone = probe_rows(redzone_probes(), "redzone")
    payload = {
        "lines": {"music": MUSIC_LINE, "speech": SPEECH_LINE, "window_s": WINDOW, "horizons_before_s": list(HORIZONS)},
        "source": "AudioSet CNN14 clipwise head, checkpoint Cnn14_mAP=0.431.pth, not refit",
        "breaks": break_rows,
        "ordinary_play": play,
        "redzone": zone,
        "failed_breaks": failed,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(payload), encoding="utf-8")
    print("wrote", OUT / "results.json", "breaks", len(break_rows), "failed", failed)


if __name__ == "__main__":
    main()
