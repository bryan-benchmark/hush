"""Point the existing overlays at the two primary gold spans.

Does not change a threshold, window, collar, phrase list, matcher, freeze rule,
or scoring formula. The only adjustments are the session, the analysis end, and
the August clock shift already declared in the gold note: experiment time is
session time minus 300 s.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from hush import overlay002, overlay003, overlay003b, overlay005  # noqa: E402

HOLDOUTS = ("hush_20260917_205513", "hush_20260920_200635")
JOBS = (
    {
        "session": "hush_20260924_220624",
        "t0": 0.0,
        "analysis_end": 7600.0,
        "wav": REPO / "experiments/replication/derived/hush_20260924_220624_0_7600_16k_mono.wav",
    },
    {
        "session": "hush_20260827_135935",
        "t0": 300.0,
        "analysis_end": 6900.0,
        "wav": REPO / "experiments/replication/derived/hush_20260827_135935_300_7200_16k_mono.wav",
    },
)

_ORIGINAL_BREAKS = {
    overlay002: overlay002.commercial_breaks,
    overlay003: overlay003.commercial_breaks,
    overlay003b: overlay003b.commercial_breaks,
    overlay005: overlay005.commercial_breaks,
}
_ORIGINAL_MASK = overlay003._mask_seconds
_ORIGINAL_WRITE_002 = overlay002._write_csv


def _write_csv_union(path: Path, rows: list[dict]) -> None:
    """The frozen writer takes columns from the first row. Empty clusters omit later columns."""
    if not rows:
        return
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    filled = [{key: row.get(key) for key in fieldnames} for row in rows]
    _ORIGINAL_WRITE_002(path, filled)


overlay002._write_csv = _write_csv_union


def _prepare(module, session: str, t0: float, analysis_end: float) -> None:
    if session in HOLDOUTS:
        raise SystemExit(f"refusing sealed holdout {session}")
    module.SESSION = session
    module.ANALYSIS_END = analysis_end
    original = _ORIGINAL_BREAKS[module]

    def breaks(name: str):
        rows = original(name)
        if t0 == 0:
            return rows
        shifted = []
        for row in rows:
            item = dict(row)
            item["start_seconds"] = float(row["start_seconds"]) - t0
            item["end_seconds"] = float(row["end_seconds"]) - t0
            shifted.append(item)
        return shifted

    module.commercial_breaks = breaks


def _bind_mask() -> None:
    def mask(breaks, end=None):
        return _ORIGINAL_MASK(breaks, overlay003.ANALYSIS_END if end is None else end)

    overlay003._mask_seconds = mask


def _link_exp005_inputs(source: Path, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    for name in ("cues.json", "vocabulary_hits.json", "semantic.parquet", "semantic_embeddings.npy"):
        dest = output / name
        if dest.exists():
            continue
        dest.symlink_to(source / name)


def run_job(job: dict) -> None:
    session = job["session"]
    t0 = job["t0"]
    end = job["analysis_end"]
    root = REPO / "experiments" / "replication" / "overlays" / session
    print(f"START {session} t0={t0} analysis_end={end}", flush=True)

    for module in (overlay002, overlay003, overlay003b, overlay005):
        _prepare(module, session, t0, end)
    _bind_mask()

    out002 = root / "exp002"
    overlay002.run(
        REPO / "experiments/exp002" / session / "speaker_timeline.parquet",
        REPO / "experiments/exp002" / session / "speaker_segments.parquet",
        out002,
        session,
        job["wav"],
    )
    print(f"END {session} exp002", flush=True)

    out003 = root / "exp003"
    overlay003.run(
        REPO / "experiments/exp003" / session / "program_cloud.parquet",
        out003,
    )
    print(f"END {session} exp003", flush=True)

    out003b = root / "exp003b"
    overlay003b.run(
        REPO / "experiments/exp003b" / session / "frozen_timeline.parquet",
        REPO / "experiments/exp003b" / session / "freezes.json",
        out003b,
    )
    print(f"END {session} exp003b", flush=True)

    out005 = root / "exp005"
    _link_exp005_inputs(REPO / "experiments/exp005" / session, out005)
    overlay005.run(out005)
    print(f"END {session} exp005", flush=True)


def main() -> None:
    gold = json.loads((REPO / "experiments/replication/freeze/gold_ledgers.json").read_text())
    if gold.get("overlays_opened") is not False:
        raise SystemExit("gold hash record is missing overlays_opened false")
    for job in JOBS:
        run_job(job)


if __name__ == "__main__":
    main()
