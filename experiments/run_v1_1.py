#!/usr/bin/env python3
"""Run discontinuity_v1_1 from a legacy run's frozen traces."""

from __future__ import annotations

import argparse
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

import discontinuity_v1_1 as v11
import ledger


def _jsonable(obj):
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, np.bool_):
        return bool(obj)
    return obj


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(_jsonable(row), ensure_ascii=False) + "\n")


def session_bounds(session: str) -> tuple[float, float]:
    for day in ledger.RECORDINGS.iterdir() if ledger.RECORDINGS.exists() else []:
        meta = day / session / "session.json"
        if meta.exists():
            data = json.loads(meta.read_text(encoding="utf-8"))
            end = float(data.get("audio_seconds") or 0.0)
            # Prefer last chunk end_elapsed if present (holes preserve clock)
            chunks = data.get("chunks") or []
            if chunks:
                end = max(float(c.get("end_elapsed_seconds") or 0.0) for c in chunks)
            return 0.0, end
    return 0.0, 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--legacy-run", required=True)
    ap.add_argument("--session", action="append", default=[])
    ap.add_argument("--gold-session", default="hush_20260914_212529")
    args = ap.parse_args()

    legacy = ledger.RUNS / args.legacy_run
    if not legacy.is_dir():
        raise SystemExit(f"no legacy run: {args.legacy_run}")
    sessions = args.session or [args.gold_session]

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_id = f"{stamp}_{v11.DETECTOR_ID}"
    out = ledger.RUNS / run_id
    tmp = ledger.RUNS / f".tmp_{run_id}"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)

    all_keeps: list[dict] = []
    n_events = 0
    n_anchors = 0

    for session in sessions:
        trace_dir = legacy / "traces" / session
        if not trace_dir.is_dir():
            raise SystemExit(f"missing traces: {trace_dir}")
        start, end = session_bounds(session)
        # Load peaks then attach intensity with real bounds
        peak_params = {
            "shoulder_s": v11.PARAMS["shoulder_s"],
            "min_peak_score": v11.PARAMS["min_peak_score"],
            "strong_peak_score": v11.PARAMS["strong_peak_score"],
        }
        import discontinuity_v1 as v0

        raw = []
        for npz in sorted(trace_dir.glob("audio_*.npz")):
            z = np.load(npz, allow_pickle=True)
            trace = {k: z[k] for k in z.files}
            for ev in v0.transition_events_from_trace(trace, {**v0.PARAMS, **peak_params}):
                ev["file"] = npz.name.replace(".npz", ".wav")
                raw.append(ev)
        raw.sort(key=lambda e: float(e["elapsed_seconds"]))
        if end <= 0 and raw:
            end = float(raw[-1]["elapsed_seconds"]) + 1.0
        events = v11.attach_rolling_intensity(raw, start, end, v11.PARAMS)
        keeps, anchors, other = v11.propose_break_ins(events, v11.PARAMS)
        n_events += len(events)
        n_anchors += len(anchors)

        tdir = tmp / "transitions" / session
        tdir.mkdir(parents=True)
        write_jsonl(tdir / "transitions.jsonl", [{"session": session, **e} for e in events])
        write_jsonl(tdir / "episode_anchors.jsonl", [{"session": session, **a} for a in anchors])

        for i, row in enumerate(keeps):
            pid = f"in:{session}:{row['file']}:{row['frame_index']}"
            all_keeps.append(
                {
                    "proposal_id": pid,
                    "run_id": run_id,
                    "session": session,
                    "file": row["file"],
                    "stage": "in",
                    "detector_id": v11.DETECTOR_ID,
                    "elapsed_seconds": round(float(row["elapsed_seconds"]), 3),
                    "score": round(float(row["episode_score"]), 3),
                    "boundary_score": round(float(row["boundary_score"]), 3),
                    "frame_index": row["frame_index"],
                    "session_sample_index": row["session_sample_index"],
                    "near_silence": row["near_silence"],
                    "evidence": {
                        "episode_score": row["episode_score"],
                        "episode_components": row.get("episode_components"),
                        "episode_flags": row.get("episode_flags"),
                        "localization": row.get("localization"),
                        "anchor_elapsed_seconds": row.get("anchor_elapsed_seconds"),
                        "context": row.get("context"),
                        "boundary_score": row["boundary_score"],
                        "flux_z": row["flux_z"],
                        "jump_z": row["jump_z"],
                        "rms_db": row["rms_db"],
                    },
                    "selection": {
                        "action": "keep",
                        "reason": "localized_break_onset",
                        "selection_rank": i,
                    },
                }
            )

    write_jsonl(tmp / "candidates.jsonl", all_keeps)
    write_jsonl(tmp / "proposals.jsonl", all_keeps)
    manifest = {
        "run_id": run_id,
        "detector_id": v11.DETECTOR_ID,
        "feature_schema": v11.FEATURE_SCHEMA,
        "params": {k: (list(v) if isinstance(v, tuple) else v) for k, v in v11.PARAMS.items()},
        "legacy_feature_run": args.legacy_run,
        "sessions": sessions,
        "keep_count": len(all_keeps),
        "transition_event_count": n_events,
        "episode_anchor_count": n_anchors,
        "hypothesis": (
            "Detection and localization are separate: rolling transition intensity "
            "identifies break-like episodes; onset is the preceding regime-change boundary."
        ),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    (tmp / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, out)
    print(json.dumps({"run_id": run_id, "keeps": len(all_keeps), "transitions": n_events, "anchors": n_anchors}, indent=2))


if __name__ == "__main__":
    main()
