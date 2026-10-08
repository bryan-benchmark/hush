#!/usr/bin/env python3
"""Event-level audit. Recall is refused outside fully annotated coverage."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import event_match
import ledger
import legacy_detector as det


def load_run(run_id: str) -> Path:
    path = ledger.RUNS / run_id
    if not path.is_dir():
        raise SystemExit(f"no run: {run_id}")
    return path


def keeps(run: Path) -> list[dict]:
    return ledger.read_jsonl(run / "candidates.jsonl")


def coverage_ranges(manifest: dict) -> list[dict]:
    return list(manifest.get("coverage") or [])


def fully_annotated(ranges: list[dict]) -> list[dict]:
    return [r for r in ranges if r.get("fully_annotated")]


def out_errors(pairs: list[dict], mode: str) -> dict:
    signed = []
    for pair in pairs:
        gold = pair["gold"]
        if gold.get("end_seconds") is None:
            continue
        if mode == "end_to_end":
            suggested = pair["proposal"].get("suggested_out") or {}
            if suggested.get("elapsed_seconds") is None:
                continue
            detected = float(suggested["elapsed_seconds"])
        else:
            detected = pair.get("oracle_out_seconds")
            if detected is None:
                continue
        signed.append(detected - float(gold["end_seconds"]))
    return event_match.error_stats(signed)


def oracle_outs(pairs: list[dict], sessions: dict[str, Path]) -> None:
    for pair in pairs:
        gold = pair["gold"]
        session = gold["session"]
        if session not in sessions:
            continue
        try:
            result = det.break_at_session_in(sessions[session], float(gold["start_seconds"]))
        except RuntimeError:
            pair["oracle_out_seconds"] = None
            continue
        best = result.get("best_out")
        pair["oracle_out_seconds"] = None if not best else float(best["elapsed_seconds"])


def slice_counts(rows: list[dict], key_fn) -> dict:
    buckets = defaultdict(int)
    for row in rows:
        buckets[str(key_fn(row))] += 1
    return dict(buckets)


def score_band(score: float) -> str:
    if score < 6:
        return "<6"
    if score < 8:
        return "6-8"
    if score < 10:
        return "8-10"
    return ">=10"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--gold", default="GOLD_DEV_V1")
    ap.add_argument("--collar", type=float, default=event_match.DEFAULT_COLLAR_S)
    ap.add_argument("--no-oracle", action="store_true")
    args = ap.parse_args()
    run = load_run(args.run)
    manifest = ledger.load_gold_manifest(args.gold)
    ranges = coverage_ranges(manifest)
    annotated = fully_annotated(ranges)
    proposals = keeps(run)
    truth = ledger.resolve_ledger(ledger.read_jsonl(ledger.TRUTH_PATH), "gold_id")
    truth = [t for t in truth if t.get("event", "ad_break") == "ad_break"]
    reviews = ledger.resolve_ledger(ledger.read_jsonl(ledger.REVIEWS_PATH), "review_id")
    unsure = [r for r in reviews if r.get("verdict") == "unsure" and r.get("run_id") == args.run]

    report = {
        "run_id": args.run,
        "gold": args.gold,
        "coverage_ranges": len(annotated),
        "unsure_reviews_excluded_from_primary": len(unsure),
        "holdout_warning": _holdout_warning(proposals),
    }
    if not annotated:
        report["recall"] = None
        report["reason"] = "no fully_annotated coverage; refusing precision and recall"
        report["run_keep_count"] = len(proposals)
        _emit(run, args.gold, report)
        return

    primary = event_match.score_onset(truth, proposals, ranges, args.collar)
    collars = {}
    for collar in event_match.COLLARS_S:
        scored = event_match.score_onset(truth, proposals, ranges, collar)
        collars[str(collar)] = {
            k: scored[k]
            for k in ("gold_count", "proposal_count", "tp", "fp", "fn", "precision", "recall", "f1", "in_error")
        }
    if not args.no_oracle and primary["pairs"]:
        sessions = _session_dirs(proposals)
        oracle_outs(primary["pairs"], sessions)
    report["primary_collar_s"] = args.collar
    report["in"] = {k: v for k, v in primary.items() if k != "pairs"}
    report["collars"] = collars
    report["out_end_to_end"] = out_errors(primary["pairs"], "end_to_end")
    report["out_oracle_in"] = out_errors(primary["pairs"], "oracle")
    report["slices"] = {
        "score_band": slice_counts(proposals, lambda p: score_band(float(p["score"]))),
        "near_silence": slice_counts(proposals, lambda p: p.get("near_silence")),
        "error_tag": slice_counts(
            [r for r in reviews if r.get("run_id") == args.run and r.get("verdict") != "unsure"],
            lambda r: r.get("error_tag") or "untagged",
        ),
    }
    _emit(run, args.gold, report)


def _session_dirs(proposals: list[dict]) -> dict[str, Path]:
    found = {}
    for day in ledger.RECORDINGS.iterdir() if ledger.RECORDINGS.exists() else []:
        if not day.is_dir():
            continue
        for sess in day.iterdir():
            if sess.is_dir() and (sess / "session.json").exists():
                found[sess.name] = sess
    return found


def _holdout_warning(proposals: list[dict]) -> list[str]:
    import datasets

    sealed = sorted({p["session"] for p in proposals if datasets.role_of(p["session"]) == "holdout"})
    if not sealed:
        return []
    return [f"{name} is sealed in HOLDOUT_V1; this audit is not a tuning set" for name in sealed]


def _emit(run: Path, gold: str, report: dict) -> None:
    out_dir = ledger.ROOT / "experiments" / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"audit_{run.name}_{gold}.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "slices"}, indent=2))
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
