"""Score the sports tapes with the 3-second labels from VOICE_ENROLL_001.

News, commercials, other shows, and skips are not voices. The live mute
is not changed.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from experiments.measurement.show_roster_001 import SESSION_SHOW  # noqa: E402
from experiments.measurement.verified_speaker_001 import load_windows  # noqa: E402
from hush.audio import (  # noqa: E402
    RAW_SR,
    analysis_pieces,
    find_session,
    load_session,
    read_stereo,
    resample_concat,
)
from hush.experiment002 import _embed_windows, _load_encoder  # noqa: E402
from hush.session_catalog import RECORDINGS  # noqa: E402
from hush.speaker_memory import EMBEDDING_MODEL_ID, SR  # noqa: E402

OUT = REPO / "docs/ohush/research/VOICE_ENROLL_001"
KEEP = {"clear", "laugh", "loud", "crowd", "song"}
CAST = {
    "snf": ["Mike Tirico", "Cris Collinsworth", "Maria Taylor", "Mike Tomlin"],
    "mnf": ["Joe Buck", "Troy Aikman"],
    "tnf": [
        "Al Michaels",
        "Kirk Herbstreit",
        "Clarissa Thompson",
        "Ryan Fitzpatrick",
        "Andrew Whitworth",
        "Tony Gonzalez",
    ],
}
LINES = [0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.50]
MODEL = REPO / "experiments/exp002/models/spkrec-ecapa-voxceleb"


def latest_labels() -> list[dict]:
    by_id: dict[str, dict] = {}
    for line in (OUT / "labels.jsonl").read_text().splitlines():
        if line.strip():
            row = json.loads(line)
            by_id[row["id"]] = row
    return list(by_id.values())


def clip_16k(session: str, start: float, duration: float) -> np.ndarray:
    folder = find_session(RECORDINGS, session)
    meta = load_session(folder)
    pieces = analysis_pieces(folder, meta, start, start + duration)
    mono = [read_stereo(piece).mean(axis=1) for piece in pieces]
    audio = resample_concat(mono, up=1, down=RAW_SR // SR)
    return np.asarray(audio, dtype=np.float32)


def prototype(vectors: list[np.ndarray]) -> np.ndarray:
    mean = np.mean(np.stack(vectors), axis=0)
    return mean / np.linalg.norm(mean)


def main() -> None:
    labels = [row for row in latest_labels() if row.get("condition") in KEEP and row.get("who")]
    encoder = _load_encoder(MODEL, "cpu")
    grouped: dict[str, list[np.ndarray]] = defaultdict(list)
    sessions_used: dict[str, set[str]] = defaultdict(set)
    for row in labels:
        audio = clip_16k(row["session"], float(row["play_start"]), float(row["duration"]))
        vector = _embed_windows(audio, [(0.0, len(audio) / SR)], encoder, "cpu", 8)[0]
        grouped[row["who"]].append(vector)
        sessions_used[row["who"]].add(row["session"])
    voices = {name: prototype(vectors) for name, vectors in grouped.items()}

    receipts = [
        json.loads(line)
        for line in (REPO / "docs/ohush/research/START_END_001/receipts.jsonl").read_text().splitlines()
        if line.strip()
    ]
    pods: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for row in receipts:
        if row["network"] in {"NBC", "ESPN", "Prime", "Prime Video"}:
            pods[row["session"]].append((float(row["start"]), float(row["end"])))

    def in_ad(session: str, t: float) -> bool:
        return any(start <= t <= end for start, end in pods[session])

    decisions: dict[str, list[dict]] = defaultdict(list)
    for line in (REPO / "docs/ohush/research/BREAK_TRACE_001/decisions.jsonl").read_text().splitlines():
        if line.strip():
            row = json.loads(line)
            if row["session"] in pods:
                decisions[row["session"]].append(row)
    for session in decisions:
        decisions[session].sort(key=lambda row: row["t"])

    checks = []
    for session, rows in decisions.items():
        show = SESSION_SHOW.get(session)
        names = [name for name in CAST.get(show, []) if name in voices]
        if not names:
            continue
        windows = load_windows(session)
        mids = (windows["start"] + windows["end"]) / 2
        order = np.argsort(mids)
        mids = mids[order]
        matrix = np.vstack([voices[name] for name in names])
        raw = windows["vector"][order] @ matrix.T
        times = [float(row["t"]) for row in rows]
        bins = []
        for row in rows:
            left = int(np.searchsorted(mids, float(row["t"]) - 4, side="left"))
            right = int(np.searchsorted(mids, float(row["t"]), side="left"))
            bins.append(None if right <= left else float(raw[left:right].max()))
        cursor = 0
        for index, row in enumerate(rows):
            while times[cursor] < float(row["t"]) - 30:
                cursor += 1
            if float(row["t"]) - times[cursor] < 26:
                continue
            vals = [bins[slot] for slot in range(cursor, index + 1) if bins[slot] is not None]
            checks.append((in_ad(session, float(row["t"])), None if not vals else max(vals)))

    def matrix_at(line: float) -> dict:
        cells = {"ad_off": 0, "game_off": 0, "ad_on": 0, "game_on": 0, "no_sample_ad": 0, "no_sample_game": 0}
        for ad, score in checks:
            if score is None:
                cells["no_sample_ad" if ad else "no_sample_game"] += 4
                continue
            on = score >= line
            if ad and not on:
                cells["ad_off"] += 4
            elif not ad and not on:
                cells["game_off"] += 4
            elif ad and on:
                cells["ad_on"] += 4
            else:
                cells["game_on"] += 4
        return cells

    payload = {
        "system": "voice_enroll_score_001",
        "model": EMBEDDING_MODEL_ID,
        "mute_policy": False,
        "clips_used": {name: len(vectors) for name, vectors in sorted(grouped.items())},
        "checks": len(checks),
        "rule": "sound off when the best saved voice on that show stays under the line for 30 seconds",
        "lines": {f"{line:.2f}": matrix_at(line) for line in LINES},
    }
    (OUT / "score.json").write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps({"clips_used": payload["clips_used"], "checks": len(checks)}, indent=2))
    print(f"{'line':>6} {'ad off':>8} {'game off':>9} {'ad on':>8} {'game on':>8}")
    for line in LINES:
        cells = payload["lines"][f"{line:.2f}"]
        print(f"{line:6.2f} {cells['ad_off']:8} {cells['game_off']:9} {cells['ad_on']:8} {cells['game_on']:8}")


if __name__ == "__main__":
    main()
