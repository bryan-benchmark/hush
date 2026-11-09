"""Write the oracle false-mute audio for listening. Does not change gold.

    python -m experiments.nfl75.protect_clips
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from experiments.ledger import RECORDINGS  # noqa: E402
from experiments.nfl75.diagnose import perfect_endings  # noqa: E402
from experiments.nfl75.inventory import active_intervals, coverage_by_session, excluded_ranges, wall_gaps  # noqa: E402
from experiments.nfl75.mean import PRIME_SESSIONS  # noqa: E402
from experiments.nfl75.persist import _logits, nbc_lines  # noqa: E402
from experiments.nfl75.protect import unprotected_covers  # noqa: E402
from experiments.nfl75.score import _with_exclusions, playback_from_covers, score_product  # noqa: E402
from experiments.measurement.metrics import target_commercials  # noqa: E402
from hush.audio import RAW_SR, analysis_pieces, find_session, load_session, read_stereo, resample_concat, write_mono_wav  # noqa: E402
from hush.speaker_memory import SR  # noqa: E402

MEAN = REPO / "docs" / "ohush" / "research" / "NFL75_MEAN_001" / "results.json"
OUT = REPO / "docs" / "ohush" / "research" / "NFL75_PROTECT_001" / "clips"

# A long interruption is sampled at the start, where the mute opened.
CLIP_S = 20.0


def _clip(session: str, start: float, end: float) -> np.ndarray:
    folder = find_session(RECORDINGS, session)
    meta = load_session(folder)
    pieces = analysis_pieces(folder, meta, start, end)
    mono = [read_stereo(piece).mean(axis=1) for piece in pieces]
    return np.asarray(resample_concat(mono, up=1, down=RAW_SR // SR), dtype=np.float32)


def main() -> None:
    frozen = json.loads(MEAN.read_text(encoding="utf-8"))["frozen"]
    window = int(frozen["window_s"])
    line = float(frozen["start_line"])
    head = nbc_lines()["head"]
    manifest = []
    for session in PRIME_SESSIONS:
        times, scores, _ignored = _logits(head, session)
        clock = [float(moment) for moment in times]
        values = [float(score) for score in scores]
        coverage = coverage_by_session()[session]
        intervals = active_intervals(session)
        commercials = target_commercials(intervals)
        covers = unprotected_covers(clock, values, window=window, start_line=line)
        oracle = perfect_endings(playback_from_covers(coverage, covers), commercials)
        scored = score_product(
            coverage,
            intervals,
            playback_from_covers(coverage, oracle),
            session=session,
            oracle=True,
            audio_present=True,
            wall_gap_s=wall_gaps().get(session, 0.0),
            excluded_ranges=excluded_ranges(session, intervals),
        )
        folder = OUT / session
        folder.mkdir(parents=True, exist_ok=True)
        for index, episode in enumerate(scored["episodes"], start=1):
            start = float(episode["start_s"])
            end = min(float(episode["end_s"]), start + CLIP_S)
            audio = _clip(session, start, end)
            path = folder / f"{index:03d}.wav"
            write_mono_wav(path, audio, SR)
            manifest.append(
                {
                    "session": session,
                    "episode": index,
                    "start_s": round(start, 3),
                    "end_s": round(float(episode["end_s"]), 3),
                    "duration_s": round(float(episode["duration_s"]), 3),
                    "clip_s": round(end - start, 3),
                    "wav": str(path.relative_to(REPO)),
                }
            )
        print(session, len(scored["episodes"]), "episodes", flush=True)
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("clips", len(manifest), flush=True)


if __name__ == "__main__":
    main()
