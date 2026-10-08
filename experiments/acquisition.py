#!/usr/bin/env python3
"""acquisition_v1: decide whether a chunk is TV audio before any ad detector runs.

Does not modify discontinuity_legacy_v0. Writes a report beside the run, not inside it.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

import datasets
import ledger
import legacy_detector as det

DETECTOR_ID = "acquisition_v1"
NEAR_SILENCE_DB = -80.0
TRANSIENT_MAX_DB = -60.0
SHORT_SECONDS = 60.0


def classify_chunk(stats: dict) -> dict:
    """Turn measured stats into eligible_for_detection and a reason.

    Order matters: a silence-plus-transient chunk must not be called mere digital silence.
    """
    duration = float(stats["duration_seconds"])
    near = float(stats["near_silence_fraction"])
    zeros = float(stats["digital_zero_fraction"])
    rms_max = float(stats["rms_max_db"])
    rms_p95 = float(stats["rms_p95_db"])
    clip = float(stats["clipping_fraction"])
    flat = float(stats["longest_flatline_seconds"])
    if stats.get("malformed"):
        return {"eligible_for_detection": False, "reason": "malformed"}
    if duration < SHORT_SECONDS:
        return {"eligible_for_detection": False, "reason": "short_test_capture"}
    if near >= 0.90 and rms_max > TRANSIENT_MAX_DB:
        return {"eligible_for_detection": False, "reason": "mostly_silence_plus_transient"}
    if zeros >= 0.98 or (near >= 0.98 and rms_p95 < -90.0):
        return {"eligible_for_detection": False, "reason": "digital_silence"}
    if clip >= 0.01:
        return {"eligible_for_detection": False, "reason": "clipping"}
    if flat >= 60.0 and near >= 0.5:
        return {"eligible_for_detection": False, "reason": "flatline"}
    return {"eligible_for_detection": True, "reason": "valid_tv_audio"}


def _percentiles(rms_db: np.ndarray) -> dict:
    if rms_db.size == 0:
        return {"rms_p50_db": None, "rms_p95_db": None, "rms_max_db": None, "near_silence_fraction": 1.0}
    return {
        "rms_p50_db": float(np.percentile(rms_db, 50)),
        "rms_p95_db": float(np.percentile(rms_db, 95)),
        "rms_max_db": float(np.max(rms_db)),
        "near_silence_fraction": float(np.mean(rms_db < NEAR_SILENCE_DB)),
    }


def _extend_flat(same: np.ndarray, flat_run: int, flat_max: int) -> tuple[int, int]:
    if same.size == 0:
        return flat_run, flat_max
    if same[0] and flat_run:
        if bool(np.all(same)):
            lead = int(same.size)
        else:
            lead = int(np.argmax(~same))
        flat_run += lead
        flat_max = max(flat_max, flat_run)
        same = same[lead:]
        if same.size == 0:
            return flat_run, flat_max
    flat_run = 0
    padded = np.concatenate([[False], same, [False]])
    changes = np.diff(padded.astype(np.int8))
    starts = np.flatnonzero(changes == 1)
    ends = np.flatnonzero(changes == -1)
    if starts.size:
        lengths = ends - starts
        flat_max = max(flat_max, int(lengths.max()))
        if bool(same[-1]):
            flat_run = int(lengths[-1])
    return flat_run, flat_max


def scan_wav(path: Path) -> dict:
    """Sample-level acquisition stats. Frame RMS comes from the caller when a trace exists."""
    try:
        header = det.wav_header(path)
    except RuntimeError as exc:
        return {
            "malformed": True,
            "error": str(exc),
            "duration_seconds": 0.0,
            "digital_zero_fraction": 1.0,
            "clipping_fraction": 0.0,
            "longest_flatline_seconds": 0.0,
            "channel_mean_square": [],
            "nonzero_sample_fraction": 0.0,
        }
    n = int(header["n_frames"])
    ch = int(header["channels"])
    rate = int(header["sample_rate"])
    if n <= 0 or ch <= 0:
        return {
            "malformed": True,
            "error": "empty",
            "duration_seconds": 0.0,
            "digital_zero_fraction": 1.0,
            "clipping_fraction": 0.0,
            "longest_flatline_seconds": 0.0,
            "channel_mean_square": [],
            "nonzero_sample_fraction": 0.0,
        }
    data = np.memmap(path, dtype="<i2", mode="r", offset=int(header["data_offset"]), shape=(n, ch))
    zeros = 0
    clips = 0
    nonzero = 0
    sumsq = np.zeros(ch, dtype=np.float64)
    flat_run = 0
    flat_max = 0
    prev = None
    block = 48000 * 30
    for start in range(0, n, block):
        chunk = np.asarray(data[start : start + block])
        if len(chunk) == 0:
            continue
        zeros += int(np.count_nonzero(chunk == 0))
        clips += int(np.count_nonzero((chunk >= 32767) | (chunk <= -32768)))
        nonzero += int(np.count_nonzero(chunk))
        sumsq += np.sum(chunk.astype(np.float64) ** 2, axis=0)
        same = np.zeros(len(chunk), dtype=bool)
        if prev is not None:
            same[0] = bool(np.all(chunk[0] == prev))
        if len(chunk) > 1:
            same[1:] = np.all(chunk[1:] == chunk[:-1], axis=1)
        flat_run, flat_max = _extend_flat(same, flat_run, flat_max)
        prev = chunk[-1]
    total = n * ch
    return {
        "malformed": False,
        "duration_seconds": n / float(rate),
        "sample_rate": rate,
        "channels": ch,
        "digital_zero_fraction": zeros / total,
        "nonzero_sample_fraction": nonzero / total,
        "clipping_fraction": clips / total,
        "longest_flatline_seconds": flat_max / float(rate),
        "channel_mean_square": [float(v / n) / (32768.0 ** 2) for v in sumsq],
    }


def frame_rms_from_trace(trace: Path) -> np.ndarray | None:
    if not trace.exists():
        return None
    with np.load(trace) as z:
        return np.asarray(z["rms_db"], dtype=np.float64)


def audit_run(run_id: str) -> Path:
    run = ledger.RUNS / run_id
    if not run.is_dir():
        raise SystemExit(f"no run: {run_id}")
    inputs = json.loads((run / "inputs.json").read_text(encoding="utf-8"))
    roles = datasets.load_datasets()
    chunks = []
    for sess in inputs["sessions"]:
        if sess.get("disposition") != "included":
            continue
        name = sess["session"]
        for wav in sess["wavs"]:
            path = ledger.ROOT / wav["path"]
            print(f"  {name}/{wav['file']}", flush=True)
            measured = scan_wav(path)
            trace = frame_rms_from_trace(run / "traces" / name / f"{Path(wav['file']).stem}.npz")
            if trace is not None:
                measured.update(_percentiles(trace))
            else:
                measured.update({"rms_p50_db": None, "rms_p95_db": None, "rms_max_db": None, "near_silence_fraction": None, "malformed": True})
            verdict = classify_chunk(measured)
            chunks.append({
                "session": name,
                "file": wav["file"],
                "dataset_role": datasets.role_of(name, roles),
                "duration_seconds": measured.get("duration_seconds"),
                "nonzero_sample_fraction": measured.get("nonzero_sample_fraction"),
                "digital_zero_fraction": measured.get("digital_zero_fraction"),
                "rms_p50_db": measured.get("rms_p50_db"),
                "rms_p95_db": measured.get("rms_p95_db"),
                "rms_max_db": measured.get("rms_max_db"),
                "near_silence_fraction": measured.get("near_silence_fraction"),
                "longest_flatline_seconds": measured.get("longest_flatline_seconds"),
                "clipping_fraction": measured.get("clipping_fraction"),
                "channel_mean_square": measured.get("channel_mean_square"),
                **verdict,
            })
    by_reason: dict[str, int] = {}
    by_session: dict[str, dict] = {}
    for row in chunks:
        by_reason[row["reason"]] = by_reason.get(row["reason"], 0) + 1
        bucket = by_session.setdefault(row["session"], {"chunks": 0, "eligible": 0, "reasons": {}})
        bucket["chunks"] += 1
        bucket["eligible"] += int(row["eligible_for_detection"])
        bucket["reasons"][row["reason"]] = bucket["reasons"].get(row["reason"], 0) + 1
    ineligible_seconds = sum(float(r["duration_seconds"] or 0) for r in chunks if not r["eligible_for_detection"])
    report = {
        "detector_id": DETECTOR_ID,
        "run_id": run_id,
        "near_silence_db": NEAR_SILENCE_DB,
        "chunks": len(chunks),
        "eligible_chunks": sum(1 for r in chunks if r["eligible_for_detection"]),
        "ineligible_hours": ineligible_seconds / 3600.0,
        "by_reason": by_reason,
        "by_session": by_session,
        "rows": chunks,
    }
    out = ledger.ROOT / "experiments" / "reports" / f"acquisition_{run_id}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "rows"}, indent=2))
    print(f"wrote {out}")
    return out


def eligible_files(run_id: str) -> set[tuple[str, str]] | None:
    path = ledger.ROOT / "experiments" / "reports" / f"acquisition_{run_id}.json"
    if not path.exists():
        return None
    report = json.loads(path.read_text(encoding="utf-8"))
    return {(r["session"], r["file"]) for r in report["rows"] if r["eligible_for_detection"]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    args = ap.parse_args()
    audit_run(args.run)


if __name__ == "__main__":
    main()
