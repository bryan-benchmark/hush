"""ECAPA-BACKFILL-001. The existing speaker pipeline, then the frozen voice guard.

Five October recordings had no speaker embeddings. This derives the same
16 kHz mono stream Exp001 used, runs speechbrain/spkrec-ecapa-voxceleb at the
published cosine of 0.25, and does not read commercial labels into that pass.
The voice-guard replay is separate and comes after the parquets exist.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from hush.audio import (  # noqa: E402
    analysis_pieces,
    find_session,
    load_session,
    read_stereo,
    resample_concat,
    write_mono_wav,
)

RECORDINGS = REPO / "recordings"
PYTHON = REPO / ".venv/bin/python"
SR = 16000
HOLDOUTS = ("hush_20260917_205513", "hush_20260920_200635")
# Published fully-annotated spans. The embedding pass does not open the ledger.
SPANS = (
    ("hush_20261011_135700", 0.0, 4896.768),
    ("hush_20261010_222400", 0.0, 6064.768),
    ("hush_20261008_205100", 0.0, 10440.364),
    ("hush_20261012_204200", 0.0, 13111.808),
    ("hush_20261011_204300", 0.0, 14405.376),
)


def derive(session: str, t0: float, t1: float) -> Path:
    if session in HOLDOUTS:
        raise SystemExit(f"refusing sealed holdout {session}")
    folder = find_session(RECORDINGS, session)
    meta = load_session(folder)
    pieces = analysis_pieces(folder, meta, t0, t1)
    parts = [read_stereo(piece).mean(axis=1) for piece in pieces]
    mono = np.asarray(resample_concat(parts, up=1, down=3), dtype=np.float32)
    expected = int(round((t1 - t0) * SR))
    if abs(len(mono) - expected) > 1:
        raise SystemExit(f"{session} resampled length {len(mono)} != {expected}")
    mono = mono[:expected]
    path = REPO / "experiments/exp002/derived" / f"{session}_{t0:.0f}_{t1:.3f}_16k_mono.wav"
    write_mono_wav(path, mono, SR)
    print(f"wrote {path} frames {expected}", flush=True)
    return path


def already_done(session: str) -> bool:
    folder = REPO / "experiments/exp002" / session
    return (folder / "speaker_segments.parquet").exists() and (folder / "metadata.json").exists()


def embed(session: str, t0: float, t1: float, wav: Path) -> None:
    output = REPO / "experiments/exp002" / session
    command = [
        str(PYTHON),
        str(REPO / "src/hush/experiment002.py"),
        "--session",
        session,
        "--t0",
        str(t0),
        "--t1",
        str(t1),
        "--wav",
        str(wav),
        "--output",
        str(output),
        "--device",
        "cpu",
        "--batch-size",
        "32",
    ]
    print(" ".join(command), flush=True)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO / "src")
    subprocess.run(command, cwd=REPO, check=True, env=env)
    meta = json.loads((output / "metadata.json").read_text(encoding="utf-8"))
    if meta["session_id"] != session or meta["embedding_model"]["id"] != "speechbrain/spkrec-ecapa-voxceleb":
        raise SystemExit(f"unexpected speaker metadata for {session}")
    if meta["embedding_model"]["fine_tuned"] or meta["truth_ledger_read"] or abs(meta["analysis_end_seconds"] - t1) > 1e-6:
        raise SystemExit(f"speaker pass did not stay on the frozen pipeline: {session}")
    if int(meta["source_audio"]["sample_rate"]) != SR:
        raise SystemExit(f"unexpected sample rate for {session}")


def main() -> None:
    for session, t0, t1 in SPANS:
        if already_done(session):
            print(f"skip {session}", flush=True)
            continue
        wav = derive(session, t0, t1)
        embed(session, t0, t1, wav)
    missing = [session for session, _t0, _t1 in SPANS if not already_done(session)]
    if missing:
        raise SystemExit(f"speaker pass incomplete: {missing}")
    print("five speaker passes present", flush=True)


if __name__ == "__main__":
    main()
