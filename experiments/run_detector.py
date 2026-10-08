#!/usr/bin/env python3
"""Write an immutable discontinuity_legacy_v0 run.

The run reproduces the current selector. It does not add a local-max filter
or a score floor. Truth lives outside the run directory.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
from pathlib import Path

import numpy as np

import legacy_detector as det
import ledger


def discover_sessions(root: Path) -> list[dict]:
    found = []
    if not root.exists():
        return found
    for day in sorted(p for p in root.iterdir() if p.is_dir()):
        for sess in sorted(p for p in day.iterdir() if p.is_dir()):
            meta_path = sess / "session.json"
            wavs = det.iter_session_wavs(sess)
            if not meta_path.exists():
                found.append(
                    {
                        "session": sess.name,
                        "path": str(sess.relative_to(ledger.ROOT)),
                        "disposition": "excluded",
                        "reason": "missing_session_json",
                        "wavs": [],
                    }
                )
                continue
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                found.append(
                    {
                        "session": sess.name,
                        "path": str(sess.relative_to(ledger.ROOT)),
                        "disposition": "excluded",
                        "reason": "malformed_session_json",
                        "wavs": [],
                    }
                )
                continue
            if not wavs:
                found.append(
                    {
                        "session": sess.name,
                        "path": str(sess.relative_to(ledger.ROOT)),
                        "disposition": "excluded",
                        "reason": "no_audio",
                        "wavs": [],
                        "audio_seconds": meta.get("audio_seconds"),
                        "status": meta.get("status"),
                    }
                )
                continue
            found.append(
                {
                    "session": sess.name,
                    "path": str(sess.relative_to(ledger.ROOT)),
                    "abs_path": sess,
                    "disposition": "included",
                    "reason": None,
                    "meta": meta,
                    "wavs": wavs,
                    "audio_seconds": meta.get("audio_seconds"),
                    "status": meta.get("status"),
                }
            )
    return found


def chunk_timeline(meta: dict, wavs: list[Path]) -> dict[str, dict]:
    chunks = list(meta.get("chunks") or [])
    by_file = {c["file"]: c for c in chunks if "file" in c}
    running = 0.0
    timeline = {}
    for wav in wavs:
        header = det.wav_header(wav)
        c = by_file.get(wav.name, {})
        if "start_elapsed_seconds" in c:
            start = float(c["start_elapsed_seconds"])
        else:
            start = running
        declared = float(c["seconds"]) if "seconds" in c else header["duration_seconds"]
        timeline[wav.name] = {
            "start_seconds": start,
            "declared_seconds": declared,
            "header": header,
        }
        running = start + declared
    return timeline


def build_inputs(sessions: list[dict], only: set[str] | None) -> dict:
    out_sessions = []
    for sess in sessions:
        if only and sess["session"] not in only and sess["disposition"] == "included":
            out_sessions.append(
                {
                    "session": sess["session"],
                    "path": sess["path"],
                    "disposition": "excluded",
                    "reason": "not_selected",
                    "audio_seconds": sess.get("audio_seconds"),
                    "status": sess.get("status"),
                    "wavs": [],
                }
            )
            continue
        if sess["disposition"] != "included":
            out_sessions.append({k: v for k, v in sess.items() if k not in ("abs_path", "meta", "wavs")} | {"wavs": []})
            continue
        timeline = chunk_timeline(sess["meta"], sess["wavs"])
        wav_rows = []
        for wav in sess["wavs"]:
            info = timeline[wav.name]
            header = info["header"]
            rel = str(wav.relative_to(ledger.ROOT))
            wav_rows.append(
                {
                    "path": rel,
                    "file": wav.name,
                    "sha256": ledger.sha256_file(wav),
                    "size": wav.stat().st_size,
                    "sample_rate": header["sample_rate"],
                    "channels": header["channels"],
                    "duration_seconds": header["duration_seconds"],
                    "n_frames": header["n_frames"],
                    "start_seconds": info["start_seconds"],
                    "start_sample": int(round(info["start_seconds"] * header["sample_rate"])),
                    "declared_seconds": info["declared_seconds"],
                }
            )
        out_sessions.append(
            {
                "session": sess["session"],
                "path": sess["path"],
                "disposition": "included",
                "reason": None,
                "audio_seconds": sess.get("audio_seconds"),
                "status": sess.get("status"),
                "sample_rate_hz": sess["meta"].get("sample_rate_hz"),
                "wavs": wav_rows,
            }
        )
    return {"sessions": out_sessions}


def fingerprint(params: dict, input_manifest_sha: str) -> str:
    payload = {
        "detector_code_sha256": ledger.detector_code_sha256(),
        "feature_schema": det.FEATURE_SCHEMA,
        "params": params,
        "break_params": det.BREAK_PARAMS,
        "input_manifest_sha256": input_manifest_sha,
    }
    return ledger.sha256_text(ledger.canon(payload))


def save_trace(path: Path, scored: dict, rate: int, start_sample: int):
    n = len(scored["score"])
    hop = det.hop_samples(rate)
    frame_index = np.arange(n, dtype=np.int32)
    sample_index = frame_index.astype(np.int64) * hop
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        path,
        frame_index=frame_index,
        sample_index=sample_index,
        session_sample_index=sample_index + np.int64(start_sample),
        rms_db=scored["rms_db"].astype(np.float32),
        jump_db=scored["jump_db"].astype(np.float32),
        flux_raw=np.asarray(scored["flux_raw"], dtype=np.float64).astype(np.float32),
        jump_z=scored["jump_z"].astype(np.float32),
        flux_z=scored["flux_z"].astype(np.float32),
        silence_bonus=scored["silence_bonus"].astype(np.float32),
        composite_score=scored["score"].astype(np.float32),
        near_silence=scored["near_silence"].astype(np.uint8),
        jump_mean=np.float64(scored["norm"]["jump_mean"]),
        jump_std=np.float64(scored["norm"]["jump_std"]),
        flux_mean=np.float64(scored["norm"]["flux_mean"]),
        flux_std=np.float64(scored["norm"]["flux_std"]),
    )


def evidence_at(scored: dict, idx: int) -> dict:
    i = int(idx)
    return {
        "composite_score_exact": float(scored["score"][i]),
        "jump_z": float(scored["jump_z"][i]),
        "flux_z_exact": float(scored["flux_z"][i]),
        "flux_raw": float(scored["flux_raw"][i]),
        "jump_db_exact": float(scored["jump_db"][i]),
        "rms_db_exact": float(scored["rms_db"][i]),
        "silence_bonus": float(scored["silence_bonus"][i]),
        "norm": scored["norm"],
    }


def proposal_shell(run_id, run_fp, params_hash, session, file, stage, frame_index, rate, start_sample, start_seconds, chunk_seconds_exact):
    hop = det.hop_samples(rate)
    sample_index = int(frame_index) * hop
    session_sample = int(start_sample) + sample_index
    session_seconds = float(start_seconds) + float(chunk_seconds_exact)
    return {
        "proposal_id": f"{stage}:{session}:{file}:{int(frame_index)}",
        "run_id": run_id,
        "run_fingerprint": run_fp,
        "params_hash": params_hash,
        "detector_id": det.DETECTOR_ID if stage == "in" else det.BREAK_DETECTOR_ID,
        "session": session,
        "file": file,
        "stage": stage,
        "frame_index": int(frame_index),
        "sample_index": sample_index,
        "session_sample_index": session_sample,
        "chunk_seconds": float(chunk_seconds_exact),
        "session_seconds": session_seconds,
    }


def write_histogram(scores: list[float]) -> dict:
    if not scores:
        return {"bins": [], "counts": []}
    arr = np.asarray(scores, dtype=np.float64)
    counts, edges = np.histogram(arr, bins=10)
    return {
        "min": float(arr.min()),
        "max": float(arr.max()),
        "mean": float(arr.mean()),
        "edges": [float(x) for x in edges],
        "counts": [int(c) for c in counts],
    }


def process(only: set[str] | None, top_k: int, with_breaks: bool) -> Path:
    params = dict(det.PARAMS)
    params["top_k"] = int(top_k)
    params_hash = ledger.sha256_text(ledger.canon(params))[:12]
    discovered = discover_sessions(ledger.RECORDINGS)
    print(f"hashing inputs ({len(discovered)} sessions discovered)")
    inputs = build_inputs(discovered, only)
    input_sha = ledger.sha256_text(ledger.canon(inputs))
    run_fp = fingerprint(params, input_sha)
    run_id = f"{ledger.run_id_stamp()}_{det.DETECTOR_ID}_{params_hash[:8]}"
    final = ledger.RUNS / run_id
    if final.exists():
        raise SystemExit(f"run already exists: {final}")
    tmp = ledger.RUNS / f".partial-{run_id}"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    (tmp / "inputs.json").write_text(json.dumps(inputs, indent=2), encoding="utf-8")

    proposals_path = tmp / "proposals.jsonl"
    selections_path = tmp / "selections.jsonl"
    candidates_path = tmp / "candidates.jsonl"
    chunk_log_path = tmp / "chunk_log.jsonl"

    keep_scores: list[float] = []
    n_keep = 0
    n_suppress = 0
    n_cutoff = 0
    per_session: dict[str, dict] = {}

    included = [s for s in inputs["sessions"] if s["disposition"] == "included"]
    by_name = {s["session"]: s for s in discovered}

    for sess in included:
        name = sess["session"]
        session_dir = by_name[name]["abs_path"]
        per_session[name] = {"keeps": 0, "suppressions": 0, "audio_seconds": sess.get("audio_seconds")}
        accumulated = 0.0
        print(f"{name}: {len(sess['wavs'])} chunks")
        for wav_row in sess["wavs"]:
            wav = ledger.ROOT / wav_row["path"]
            rate, _ch, _n, x = det.load_pcm16(wav)
            dur = len(x) / rate
            start_seconds = float(wav_row["start_seconds"])
            start_sample = int(wav_row["start_sample"])
            silent = bool(np.max(np.abs(x)) < float(params["silent_chunk_max_abs"]))
            times, rms, flux = det.frame_features(x, rate)
            scored = det.score_frames(rms, flux, params)
            trace_path = tmp / "traces" / name / f"{wav.stem}.npz"
            save_trace(trace_path, scored, rate, start_sample)
            disposition = "skipped_silent" if silent else "scored"
            chunk_rec = {
                "session": name,
                "file": wav.name,
                "disposition": disposition,
                "reason": "max_abs_below_1e-4" if silent else None,
                "n_frames": int(len(times)),
                "duration_seconds": dur,
                "accumulated_seconds": accumulated,
                "start_seconds": start_seconds,
                "normalization": scored["norm"],
            }
            if silent:
                # Legacy find_candidates did not select inside a silent chunk.
                ledger.append_jsonl(chunk_log_path, chunk_rec)
                accumulated += dur
                continue
            picked, suppressed, cutoff = det.select_legacy(times, scored, params)
            chunk_rec["keeps"] = len(picked)
            chunk_rec["suppressions"] = len(suppressed)
            ledger.append_jsonl(chunk_log_path, chunk_rec)
            rank_by_frame = {int(r["_frame_index"]): i for i, r in enumerate(sorted(picked, key=lambda d: d["score_rank"]))}
            for row in picked:
                frame = int(row["_frame_index"])
                shell = proposal_shell(
                    run_id, run_fp, params_hash, name, wav.name, "in", frame, rate, start_sample, start_seconds, row["_t_exact"]
                )
                public = det.legacy_public_row(row, name, wav.name, accumulated)
                prop = {
                    **shell,
                    "elapsed_seconds": public["elapsed_seconds"],
                    "chunk_elapsed_seconds": public["chunk_elapsed_seconds"],
                    "score": public["score"],
                    "rms_dbfs": public["rms_dbfs"],
                    "loudness_jump_db": public["loudness_jump_db"],
                    "flux_z": public["flux_z"],
                    "near_silence": public["near_silence"],
                    "evidence": evidence_at(scored, frame),
                }
                sel = {
                    "proposal_id": prop["proposal_id"],
                    "run_id": run_id,
                    "session": name,
                    "file": wav.name,
                    "stage": "in",
                    "action": "keep",
                    "reason": "ranked_nonsuppressed",
                    "selection_rank": rank_by_frame[frame],
                    "score_rank": row["score_rank"],
                    "frame_index": frame,
                    "sample_index": prop["sample_index"],
                    "session_sample_index": prop["session_sample_index"],
                }
                breaks = None
                if with_breaks:
                    try:
                        breaks = det.break_at_session_in(session_dir, public["elapsed_seconds"])
                    except RuntimeError as exc:
                        breaks = {"error": str(exc)}
                if breaks and "published" in breaks:
                    prop["fades"] = breaks["published"]["fades"]
                    prop["suggested_out"] = breaks["published"]["suggested_out"]
                    prop["break_duration_if_suggested"] = breaks["published"]["break_duration_if_suggested"]
                    _write_break_receipts(
                        proposals_path, selections_path, run_id, run_fp, params_hash, name, prop["proposal_id"], breaks
                    )
                else:
                    prop["fades"] = []
                    prop["suggested_out"] = None
                    prop["break_error"] = None if not breaks else breaks.get("error")
                ledger.append_jsonl(proposals_path, prop)
                ledger.append_jsonl(selections_path, sel)
                ledger.append_jsonl(candidates_path, {**prop, "selection": sel})
                keep_scores.append(prop["score"])
                n_keep += 1
                per_session[name]["keeps"] += 1
            for row in suppressed:
                frame = int(row["_frame_index"])
                winner = row["winning_frame_index"]
                shell = proposal_shell(
                    run_id, run_fp, params_hash, name, wav.name, "in", frame, rate, start_sample, start_seconds, row["_t_exact"]
                )
                public = det.legacy_public_row(row, name, wav.name, accumulated)
                prop = {
                    **shell,
                    "elapsed_seconds": public["elapsed_seconds"],
                    "chunk_elapsed_seconds": public["chunk_elapsed_seconds"],
                    "score": public["score"],
                    "rms_dbfs": public["rms_dbfs"],
                    "loudness_jump_db": public["loudness_jump_db"],
                    "flux_z": public["flux_z"],
                    "near_silence": public["near_silence"],
                    "evidence": evidence_at(scored, frame),
                }
                sel = {
                    "proposal_id": prop["proposal_id"],
                    "run_id": run_id,
                    "session": name,
                    "file": wav.name,
                    "stage": "in",
                    "action": "suppress",
                    "reason": "min_gap",
                    "winning_proposal_id": f"in:{name}:{wav.name}:{winner}",
                    "gap_seconds": row["gap_seconds"],
                    "score_rank": row["score_rank"],
                    "frame_index": frame,
                    "sample_index": prop["sample_index"],
                    "session_sample_index": prop["session_sample_index"],
                }
                ledger.append_jsonl(proposals_path, prop)
                ledger.append_jsonl(selections_path, sel)
                n_suppress += 1
                per_session[name]["suppressions"] += 1
            if cutoff:
                cutoff_row = {
                    "run_id": run_id,
                    "session": name,
                    "file": wav.name,
                    "stage": "in",
                    **cutoff,
                }
                if cutoff.get("winning_frame_index") is not None:
                    cutoff_row["winning_proposal_id"] = f"in:{name}:{wav.name}:{cutoff['winning_frame_index']}"
                ledger.append_jsonl(selections_path, cutoff_row)
                n_cutoff += 1
            accumulated += dur
            print(f"  {wav.name}: {len(picked)} keeps, {len(suppressed)} min-gap suppressions")

    summary = {
        "note": "Run summary frozen at detection time. Precision and recall are computed by audit.py against coverage, outside this directory.",
        "detector_id": det.DETECTOR_ID,
        "keeps": n_keep,
        "min_gap_suppressions": n_suppress,
        "top_k_cutoffs": n_cutoff,
        "score_histogram": write_histogram(keep_scores),
        "per_session": per_session,
        "suppression_reasons": {"min_gap": n_suppress, "top_k_cutoff_records": n_cutoff},
    }
    (tmp / "audit.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    manifest = {
        "schema_version": 1,
        "run_id": run_id,
        "run_fingerprint": run_fp,
        "detector_id": det.DETECTOR_ID,
        "break_detector_id": det.BREAK_DETECTOR_ID,
        "feature_schema": det.FEATURE_SCHEMA,
        "params": params,
        "params_hash": params_hash,
        "break_params": det.BREAK_PARAMS,
        "input_manifest_sha256": input_sha,
        "detector_code_sha256": ledger.detector_code_sha256(),
        **ledger.git_state(),
        "python": platform.python_version(),
        "numpy": np.__version__,
        "scipy": __import__("scipy").__version__,
        "window_s": params["win_s"],
        "hop_s": params["hop_s"],
        "normalization": {"scope": "chunk"},
        "with_breaks": with_breaks,
        "started_at": None,
        "completed_at": ledger.utc_now(),
    }
    # started_at is the run_id stamp; completed_at is now.
    manifest["started_at"] = datetime_from_run_id(run_id)
    (tmp / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    os.replace(tmp, final)
    print(f"wrote {final}")
    return final


def datetime_from_run_id(run_id: str) -> str:
    stamp = run_id.split("_", 1)[0]
    # YYYYMMDDTHHMMSSZ
    return f"{stamp[0:4]}-{stamp[4:6]}-{stamp[6:8]}T{stamp[9:11]}:{stamp[11:13]}:{stamp[13:15]}Z"


def _write_break_receipts(proposals_path, selections_path, run_id, run_fp, params_hash, session, parent_id, breaks):
    for fade in breaks["fades"]:
        pid = f"fade:{parent_id}:{fade['frame_index']}"
        prop = {
            "proposal_id": pid,
            "run_id": run_id,
            "run_fingerprint": run_fp,
            "params_hash": params_hash,
            "detector_id": det.BREAK_DETECTOR_ID,
            "session": session,
            "stage": "fade",
            "parent_proposal_id": parent_id,
            "frame_index": fade["frame_index"],
            "sample_index": fade["sample_index"],
            "session_sample_index": fade["session_sample_index"],
            "session_seconds": fade["elapsed_seconds"],
            "elapsed_seconds": fade["elapsed_seconds"],
            "rms_dbfs": fade["rms_dbfs"],
        }
        ledger.append_jsonl(proposals_path, prop)
        ledger.append_jsonl(
            selections_path,
            {
                "proposal_id": pid,
                "run_id": run_id,
                "session": session,
                "stage": "fade",
                "action": "keep",
                "reason": "fade_rule",
                "parent_proposal_id": parent_id,
            },
        )
    for fade in breaks["fade_suppressed"]:
        pid = f"fade:{parent_id}:{fade['frame_index']}"
        ledger.append_jsonl(
            selections_path,
            {
                "proposal_id": pid,
                "run_id": run_id,
                "session": session,
                "stage": "fade",
                "action": "suppress",
                "reason": "min_gap",
                "parent_proposal_id": parent_id,
                "gap_seconds": fade["gap_seconds"],
                "winning_elapsed_seconds": fade["winning_elapsed_seconds"],
                "frame_index": fade["frame_index"],
                "session_sample_index": fade["session_sample_index"],
            },
        )
    outs = breaks["outs"]
    if not outs:
        ledger.append_jsonl(
            selections_path,
            {
                "run_id": run_id,
                "session": session,
                "stage": "out",
                "action": "exclude",
                "reason": "no_out_in_window",
                "parent_proposal_id": parent_id,
                "evaluated": 0,
            },
        )
        return
    best = outs[0]
    pid = f"out:{parent_id}:{best['frame_index']}"
    prop = {
        "proposal_id": pid,
        "run_id": run_id,
        "run_fingerprint": run_fp,
        "params_hash": params_hash,
        "detector_id": det.BREAK_DETECTOR_ID,
        "session": session,
        "stage": "out",
        "parent_proposal_id": parent_id,
        "frame_index": best["frame_index"],
        "sample_index": best["sample_index"],
        "session_sample_index": best["session_sample_index"],
        "session_seconds": best["elapsed_seconds"],
        "elapsed_seconds": best["elapsed_seconds"],
        "score": best["score"],
        "rms_dbfs": best["rms_dbfs"],
        "recovery_db": best["recovery_db"],
        "evidence": {
            "flux_z": best["flux_z"],
            "recovery_db_exact": best["recovery_db_exact"],
            "score_exact": best["score_exact"],
            "norm": breaks["window_norm"],
        },
    }
    ledger.append_jsonl(proposals_path, prop)
    ledger.append_jsonl(
        selections_path,
        {
            "proposal_id": pid,
            "run_id": run_id,
            "session": session,
            "stage": "out",
            "action": "keep",
            "reason": "max_score",
            "parent_proposal_id": parent_id,
            "evaluated": len(outs),
        },
    )
    if len(outs) > 1:
        runner = outs[1]
        ledger.append_jsonl(
            selections_path,
            {
                "proposal_id": f"out:{parent_id}:{runner['frame_index']}",
                "run_id": run_id,
                "session": session,
                "stage": "out",
                "action": "suppress",
                "reason": "lower_score",
                "parent_proposal_id": parent_id,
                "winning_proposal_id": pid,
                "evaluated": len(outs),
                "frame_index": runner["frame_index"],
                "session_sample_index": runner["session_sample_index"],
                "elapsed_seconds": runner["elapsed_seconds"],
                "score": runner["score"],
            },
        )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", action="append", default=[], help="session name; repeatable. default: every discovered session")
    ap.add_argument("--top-k", type=int, default=det.DEFAULT_TOP_K)
    ap.add_argument("--no-breaks", action="store_true", help="skip OUT/fade receipts")
    args = ap.parse_args()
    only = set(args.session) if args.session else None
    process(only, args.top_k, with_breaks=not args.no_breaks)


if __name__ == "__main__":
    main()
