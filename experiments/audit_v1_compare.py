#!/usr/bin/env python3
"""Compare discontinuity_v1 to discontinuity_legacy_v0 on frozen GOLD_DEV_V1.

Does not modify truth. Answers: does temporal break structure explain enough
of the legacy errors that this should become the next detector architecture?
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

import event_match
import ledger

# Baseline root-cause categories from the frozen hour (for delta reporting).
BASELINE_CAUSES_PATH = ledger.ROOT / "experiments/reports/baseline_root_cause_GOLD_DEV_V1.json"


def load_keeps(run_id: str, session: str, cov_to: float) -> list[dict]:
    rows = ledger.read_jsonl(ledger.RUNS / run_id / "candidates.jsonl")
    return [
        r
        for r in rows
        if r.get("session") == session and 0 <= float(r["elapsed_seconds"]) < cov_to
    ]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--legacy-run", required=True)
    ap.add_argument("--v1-run", required=True)
    ap.add_argument("--gold", default="GOLD_DEV_V1")
    ap.add_argument("--collar", type=float, default=event_match.DEFAULT_COLLAR_S)
    args = ap.parse_args()

    manifest = ledger.load_gold_manifest(args.gold)
    ranges = [r for r in (manifest.get("coverage") or []) if r.get("fully_annotated")]
    if not ranges:
        raise SystemExit("no fully_annotated coverage")
    session = ranges[0]["session"]
    cov_from = float(ranges[0]["from_seconds"])
    cov_to = float(ranges[0]["to_seconds"])

    truth = ledger.resolve_ledger(ledger.read_jsonl(ledger.TRUTH_PATH), "gold_id")
    truth = [
        t
        for t in truth
        if t.get("event", "ad_break") == "ad_break"
        and t["session"] == session
        and cov_from <= float(t["start_seconds"]) < cov_to
    ]
    truth.sort(key=lambda t: float(t["start_seconds"]))

    legacy = load_keeps(args.legacy_run, session, cov_to)
    v1 = load_keeps(args.v1_run, session, cov_to)

    legacy_score = event_match.score_onset(truth, legacy, ranges, args.collar)
    v1_score = event_match.score_onset(truth, v1, ranges, args.collar)

    # Map gold_id → baseline cause
    baseline = {}
    if BASELINE_CAUSES_PATH.exists():
        raw = json.loads(BASELINE_CAUSES_PATH.read_text(encoding="utf-8"))
        for ev in raw.get("events") or []:
            if ev.get("gold_id"):
                baseline[ev["gold_id"]] = ev.get("cause")
        by_in = {round(float(ev["gold_in"]), 1): ev.get("cause") for ev in raw.get("events") or []}
    else:
        by_in = {}

    def matched_set(scored):
        matched_g = set()
        for pair in scored.get("pairs") or []:
            matched_g.add(pair["gold"]["gold_id"])
        # score_onset stores pairs only in full return - check
        return matched_g

    # Recompute pairs for receipts (score_onset includes pairs before strip in audit)
    def with_pairs(golds, props):
        return event_match.score_onset(golds, props, ranges, args.collar)

    leg = with_pairs(truth, legacy)
    vv = with_pairs(truth, v1)
    leg_tp = {p["gold"]["gold_id"] for p in leg["pairs"]}
    v1_tp = {p["gold"]["gold_id"] for p in vv["pairs"]}

    per_gold = []
    cause_delta = defaultdict(lambda: Counter())
    for g in truth:
        gid = g["gold_id"]
        t = float(g["start_seconds"])
        cause = baseline.get(gid) or by_in.get(round(t, 1)) or "unknown"
        was = gid in leg_tp
        now = gid in v1_tp
        if was and now:
            change = "still_tp"
        elif (not was) and now:
            change = "improved_fn_to_tp"
        elif was and (not now):
            change = "regressed_tp_to_fn"
        else:
            change = "still_fn"
        cause_delta[cause][change] += 1

        def nearest(props):
            if not props:
                return None, None
            best = min(props, key=lambda r: abs(float(r["elapsed_seconds"]) - t))
            return float(best["elapsed_seconds"]), float(best["elapsed_seconds"]) - t

        lt, ld = nearest(legacy)
        vt, vd = nearest(v1)
        per_gold.append(
            {
                "gold_id": gid,
                "gold_in": t,
                "baseline_cause": cause,
                "legacy_tp": was,
                "v1_tp": now,
                "change": change,
                "nearest_legacy": lt,
                "legacy_delta": None if ld is None else round(ld, 3),
                "nearest_v1": vt,
                "v1_delta": None if vd is None else round(vd, 3),
            }
        )

    # FP change: legacy FPs that land inside gold intervals vs v1
    def inside_break(t):
        for g in truth:
            if float(g["start_seconds"]) < t < float(g["end_seconds"]):
                return True
        return False

    leg_fp = [p for p in legacy if p["proposal_id"] in set(leg["fp_proposal_ids"])]
    v1_fp = [p for p in v1 if p["proposal_id"] in set(vv["fp_proposal_ids"])]

    report = {
        "question": (
            "Does temporal break structure explain enough of the current errors "
            "that this should become the next detector architecture?"
        ),
        "gold": args.gold,
        "session": session,
        "coverage": [cov_from, cov_to],
        "collar_s": args.collar,
        "legacy_run": args.legacy_run,
        "v1_run": args.v1_run,
        "legacy": {
            "proposal_count": leg["proposal_count"],
            "tp": leg["tp"],
            "fp": leg["fp"],
            "fn": leg["fn"],
            "precision": leg["precision"],
            "recall": leg["recall"],
            "in_error": leg["in_error"],
        },
        "v1": {
            "proposal_count": vv["proposal_count"],
            "tp": vv["tp"],
            "fp": vv["fp"],
            "fn": vv["fn"],
            "precision": vv["precision"],
            "recall": vv["recall"],
            "in_error": vv["in_error"],
        },
        "delta": {
            "tp": vv["tp"] - leg["tp"],
            "fp": vv["fp"] - leg["fp"],
            "fn": vv["fn"] - leg["fn"],
            "precision": None
            if leg["precision"] is None or vv["precision"] is None
            else vv["precision"] - leg["precision"],
            "recall": None
            if leg["recall"] is None or vv["recall"] is None
            else vv["recall"] - leg["recall"],
        },
        "by_baseline_cause": {k: dict(v) for k, v in cause_delta.items()},
        "legacy_fp_inside_break": sum(1 for p in leg_fp if inside_break(float(p["elapsed_seconds"]))),
        "v1_fp_inside_break": sum(1 for p in v1_fp if inside_break(float(p["elapsed_seconds"]))),
        "per_gold": per_gold,
        "truth_frozen": True,
    }

    # Verdict heuristic (not a ship gate — architecture decision aid)
    improved = sum(1 for r in per_gold if r["change"] == "improved_fn_to_tp")
    regressed = sum(1 for r in per_gold if r["change"] == "regressed_tp_to_fn")
    fp_down = (vv["fp"] < leg["fp"])
    inside_down = report["v1_fp_inside_break"] < report["legacy_fp_inside_break"]
    if improved >= 3 and regressed == 0 and (fp_down or inside_down):
        verdict = "YES — iterate this architecture"
    elif improved >= 2 and regressed <= 1:
        verdict = "PROMISING — iterate with param receipts, do not abandon"
    elif improved == 0 and vv["fp"] >= leg["fp"]:
        verdict = "NO — structure hypothesis not supported by this first rule; try next evidence hypothesis"
    else:
        verdict = "MIXED — inspect per_gold and components before choosing"
    report["architecture_verdict"] = verdict

    out = ledger.ROOT / "experiments/reports" / f"compare_v1_vs_legacy_{args.v1_run}_{args.gold}.json"
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    md = [
        "# V1 vs legacy_v0 — frozen GOLD_DEV_V1",
        "",
        report["question"],
        "",
        f"**Verdict:** {verdict}",
        "",
        "## Scores (±2s collar)",
        "",
        f"| | legacy_v0 | discontinuity_v1 | Δ |",
        f"|---|---:|---:|---:|",
        f"| TP | {leg['tp']} | {vv['tp']} | {vv['tp']-leg['tp']:+d} |",
        f"| FP | {leg['fp']} | {vv['fp']} | {vv['fp']-leg['fp']:+d} |",
        f"| FN | {leg['fn']} | {vv['fn']} | {vv['fn']-leg['fn']:+d} |",
        f"| Recall | {leg['recall']:.1%} | {vv['recall']:.1%} | |",
        f"| Precision | {leg['precision']:.1%} | {vv['precision']:.1%} | |",
        f"| Proposals in coverage | {leg['proposal_count']} | {vv['proposal_count']} | |",
        f"| FPs inside a true break | {report['legacy_fp_inside_break']} | {report['v1_fp_inside_break']} | |",
        "",
        "## Change by baseline FN cause",
        "",
    ]
    for cause, counts in sorted(cause_delta.items()):
        md.append(f"- **{cause}**: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    md += ["", "## Each gold commercial", ""]
    for row in per_gold:
        md.append(
            f"- `{row['gold_in']:.1f}` · {row['baseline_cause']} · **{row['change']}** · "
            f"legacy Δ={row['legacy_delta']} · v1 Δ={row['v1_delta']}"
        )
    md_path = out.with_suffix(".md")
    md_path.write_text("\n".join(md) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("architecture_verdict", "legacy", "v1", "delta", "by_baseline_cause")}, indent=2))
    print("wrote", out)
    print("wrote", md_path)


if __name__ == "__main__":
    main()
