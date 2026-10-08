#!/usr/bin/env python3
"""Explain one frame: trace, norm, selection, nearby truth, review."""

from __future__ import annotations

import argparse
import json

import numpy as np

import event_match
import ledger


def load_run(run_id: str):
    path = ledger.RUNS / run_id
    if not path.is_dir():
        raise SystemExit(f"no run: {run_id}")
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--proposal")
    ap.add_argument("--session")
    ap.add_argument("--t", type=float, help="session seconds")
    ap.add_argument("--radius", type=int, default=8, help="frames of trace on each side")
    args = ap.parse_args()
    run = load_run(args.run)
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    inputs = json.loads((run / "inputs.json").read_text(encoding="utf-8"))
    proposals = ledger.read_jsonl(run / "proposals.jsonl")
    selections = ledger.read_jsonl(run / "selections.jsonl")
    if args.proposal:
        prop = next((p for p in proposals if p.get("proposal_id") == args.proposal), None)
        if prop is None:
            raise SystemExit(f"no proposal {args.proposal}")
        session = prop["session"]
        t = float(prop.get("session_seconds") or prop.get("elapsed_seconds"))
    else:
        if not args.session or args.t is None:
            raise SystemExit("pass --proposal or --session and --t")
        session = args.session
        t = args.t
        prop = _nearest_proposal(proposals, session, t)
    wav = _wav_for_time(inputs, session, t)
    view = _trace_view(run, session, wav, t, args.radius)
    selection = None
    if prop:
        selection = next((s for s in selections if s.get("proposal_id") == prop.get("proposal_id")), None)
    truth = ledger.resolve_ledger(ledger.read_jsonl(ledger.TRUTH_PATH), "gold_id")
    nearby_truth = [
        g
        for g in truth
        if g.get("session") == session and abs(float(g["start_seconds"]) - t) <= 30
    ]
    reviews = []
    if prop:
        reviews = [
            r
            for r in ledger.resolve_ledger(ledger.read_jsonl(ledger.REVIEWS_PATH), "review_id")
            if r.get("proposal_id") == prop.get("proposal_id")
        ]
    signed = None
    if nearby_truth:
        pairs = event_match.match_one_to_one(
            [float(g["start_seconds"]) for g in nearby_truth],
            [t],
            event_match.DEFAULT_COLLAR_S,
        )
        if pairs:
            signed = pairs[0][2]
    report = {
        "run_id": manifest["run_id"],
        "run_fingerprint": manifest["run_fingerprint"],
        "detector_id": manifest["detector_id"],
        "params_hash": manifest["params_hash"],
        "normalization_scope": manifest["normalization"]["scope"],
        "session": session,
        "time_seconds": t,
        "file": wav["file"] if wav else None,
        "proposal": prop,
        "selection": selection,
        "trace": view,
        "nearby_truth": nearby_truth,
        "signed_error_vs_nearest_matched_truth": signed,
        "reviews": reviews,
    }
    print(json.dumps(report, indent=2))


def _wav_for_time(inputs: dict, session: str, t: float):
    for sess in inputs["sessions"]:
        if sess["session"] != session:
            continue
        for wav in sess["wavs"]:
            start = float(wav["start_seconds"])
            end = start + float(wav["duration_seconds"])
            if start <= t < end or (t == end and wav == sess["wavs"][-1]):
                return wav
    return None


def _nearest_proposal(proposals: list[dict], session: str, t: float):
    best = None
    best_d = 1e18
    for p in proposals:
        if p.get("session") != session or p.get("stage") not in (None, "in"):
            continue
        d = abs(float(p.get("elapsed_seconds", p.get("session_seconds", 0))) - t)
        if d < best_d:
            best, best_d = p, d
    return best


def _trace_view(run, session: str, wav: dict | None, t: float, radius: int):
    if not wav:
        return None
    path = run / "traces" / session / f"{Path_stem(wav['file'])}.npz"
    if not path.exists():
        return {"missing": str(path)}
    z = np.load(path)
    start = float(wav["start_seconds"])
    hop_s = 0.125
    local = t - start
    idx = int(np.argmin(np.abs(np.arange(len(z["frame_index"])) * hop_s - local)))
    lo = max(0, idx - radius)
    hi = min(len(z["frame_index"]), idx + radius + 1)
    frames = []
    for i in range(lo, hi):
        frames.append(
            {
                "frame_index": int(z["frame_index"][i]),
                "sample_index": int(z["sample_index"][i]),
                "session_sample_index": int(z["session_sample_index"][i]),
                "chunk_seconds": round(float(i * hop_s), 6),
                "rms_db": float(z["rms_db"][i]),
                "jump_db": float(z["jump_db"][i]),
                "flux_raw": float(z["flux_raw"][i]),
                "jump_z": float(z["jump_z"][i]),
                "flux_z": float(z["flux_z"][i]),
                "silence_bonus": float(z["silence_bonus"][i]),
                "composite_score": float(z["composite_score"][i]),
                "near_silence": bool(z["near_silence"][i]),
                "center": i == idx,
            }
        )
    return {
        "center_frame_index": int(z["frame_index"][idx]),
        "norm": {
            "jump_mean": float(z["jump_mean"]),
            "jump_std": float(z["jump_std"]),
            "flux_mean": float(z["flux_mean"]),
            "flux_std": float(z["flux_std"]),
            "scope": "chunk",
        },
        "frames": frames,
    }


def Path_stem(name: str) -> str:
    return name[:-4] if name.endswith(".wav") else name


if __name__ == "__main__":
    main()
