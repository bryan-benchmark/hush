#!/usr/bin/env python3
"""Run discontinuity_v1 against an existing legacy run's traces (frozen features)."""

from __future__ import annotations

import argparse
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

import discontinuity_v1 as v1
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--legacy-run", required=True, help="Run id that already has traces/")
    ap.add_argument("--session", action="append", default=[], help="Limit to session(s)")
    ap.add_argument("--gold-session", default="hush_20260914_212529")
    args = ap.parse_args()

    legacy = ledger.RUNS / args.legacy_run
    if not legacy.is_dir():
        raise SystemExit(f"no legacy run: {args.legacy_run}")
    sessions = args.session or [args.gold_session]

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_id = f"{stamp}_{v1.DETECTOR_ID}"
    out = ledger.RUNS / run_id
    tmp = ledger.RUNS / f".tmp_{run_id}"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)

    all_keeps: list[dict] = []
    all_events = 0
    all_suppress: list[dict] = []

    for session in sessions:
        trace_dir = legacy / "traces" / session
        if not trace_dir.is_dir():
            raise SystemExit(f"missing traces: {trace_dir}")
        events = v1.load_session_events_from_traces(trace_dir, v1.PARAMS)
        keeps, suppressed = v1.propose_break_starts(events, v1.PARAMS)
        all_events += len(events)

        for i, row in enumerate(keeps):
            pid = f"in:{session}:{row['file']}:{row['frame_index']}"
            all_keeps.append(
                {
                    "proposal_id": pid,
                    "run_id": run_id,
                    "session": session,
                    "file": row["file"],
                    "stage": "in",
                    "detector_id": v1.DETECTOR_ID,
                    "elapsed_seconds": round(float(row["elapsed_seconds"]), 3),
                    "score": round(float(row["break_start_score"]), 3),
                    "boundary_score": round(float(row["boundary_score"]), 3),
                    "frame_index": row["frame_index"],
                    "session_sample_index": row["session_sample_index"],
                    "near_silence": row["near_silence"],
                    "evidence": {
                        "break_start_score": row["break_start_score"],
                        "components": row["components"],
                        "flags": row["flags"],
                        "context": row["context"],
                        "boundary_score": row["boundary_score"],
                        "flux_z": row["flux_z"],
                        "jump_z": row["jump_z"],
                        "rms_db": row["rms_db"],
                    },
                    "selection": {
                        "action": "keep",
                        "reason": "break_start",
                        "selection_rank": i,
                    },
                }
            )

        tpath = tmp / "transitions" / session
        tpath.mkdir(parents=True)
        write_jsonl(tpath / "transitions.jsonl", [{"session": session, **row} for row in events])

        for row in suppressed:
            all_suppress.append(
                {
                    "session": session,
                    "file": row.get("file"),
                    "elapsed_seconds": row.get("elapsed_seconds"),
                    "boundary_score": row.get("boundary_score"),
                    "break_start_score": row.get("break_start_score"),
                    "action": row.get("action"),
                    "reason": row.get("reason"),
                    "frame_index": row.get("frame_index"),
                    "components": row.get("components"),
                    "flags": row.get("flags"),
                }
            )

    write_jsonl(tmp / "candidates.jsonl", all_keeps)
    write_jsonl(tmp / "proposals.jsonl", all_keeps)
    write_jsonl(tmp / "suppressions.jsonl", all_suppress)

    manifest = {
        "run_id": run_id,
        "detector_id": v1.DETECTOR_ID,
        "feature_schema": v1.FEATURE_SCHEMA,
        "params": {k: (list(v) if isinstance(v, tuple) else v) for k, v in v1.PARAMS.items()},
        "legacy_feature_run": args.legacy_run,
        "sessions": sessions,
        "keep_count": len(all_keeps),
        "transition_event_count": all_events,
        "suppression_count": len(all_suppress),
        "hypothesis": (
            "Break onset is the start of a temporal cluster of acoustic transitions; "
            "isolated program edits lack post-transition structure."
        ),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    (tmp / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, out)
    print(json.dumps({"run_id": run_id, "keeps": len(all_keeps), "transitions": all_events, "path": str(out)}, indent=2))


if __name__ == "__main__":
    main()
