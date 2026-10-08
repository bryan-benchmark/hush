#!/usr/bin/env python3
"""Compare discontinuity_v1_1 vs v1 vs legacy on frozen GOLD_DEV_V1.

Re-root-causes every FP into:
  inside_break | near_onset | near_return | isolated_program | session_edge | other
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

import event_match
import ledger

BASELINE_CAUSES_PATH = ledger.ROOT / "experiments/reports/baseline_root_cause_GOLD_DEV_V1.json"


def load_keeps(run_id: str, session: str, cov_to: float) -> list[dict]:
    rows = ledger.read_jsonl(ledger.RUNS / run_id / "candidates.jsonl")
    return [r for r in rows if r.get("session") == session and 0 <= float(r["elapsed_seconds"]) < cov_to]


def classify_fp(t: float, truth: list[dict], session_end: float, edge_s: float = 60.0) -> str:
    if t < edge_s or t > session_end - edge_s:
        # Still check if also inside a break
        for g in truth:
            if float(g["start_seconds"]) < t < float(g["end_seconds"]):
                return "inside_break"
        return "session_edge"
    for g in truth:
        if float(g["start_seconds"]) < t < float(g["end_seconds"]):
            return "inside_break"
    near_in = min(abs(t - float(g["start_seconds"])) for g in truth)
    near_out = min(abs(t - float(g["end_seconds"])) for g in truth)
    if near_in <= 30:
        return "near_onset"
    if near_out <= 20:
        return "near_return"
    if near_in > 60 and near_out > 60:
        return "isolated_program"
    return "other"


def score_run(name: str, run_id: str, truth: list[dict], ranges: list[dict], collar: float, session: str, cov_to: float):
    props = load_keeps(run_id, session, cov_to)
    scored = event_match.score_onset(truth, props, ranges, collar)
    session_end = max(float(ranges[0]["to_seconds"]), max(float(g["end_seconds"]) for g in truth))
    fp_ids = set(scored["fp_proposal_ids"])
    fps = [p for p in props if p["proposal_id"] in fp_ids]
    tax = Counter(classify_fp(float(p["elapsed_seconds"]), truth, session_end) for p in fps)
    tp_ids = {p["gold"]["gold_id"] for p in scored["pairs"]}
    return {
        "name": name,
        "run_id": run_id,
        "proposal_count": scored["proposal_count"],
        "tp": scored["tp"],
        "fp": scored["fp"],
        "fn": scored["fn"],
        "precision": scored["precision"],
        "recall": scored["recall"],
        "in_error": scored["in_error"],
        "fp_taxonomy": dict(tax),
        "tp_gold_ids": sorted(tp_ids),
        "pairs": scored["pairs"],
        "props": props,
        "scored": scored,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--legacy-run", required=True)
    ap.add_argument("--v1-run", required=True)
    ap.add_argument("--v11-run", required=True)
    ap.add_argument("--gold", default="GOLD_DEV_V1")
    ap.add_argument("--collar", type=float, default=event_match.DEFAULT_COLLAR_S)
    args = ap.parse_args()

    manifest = ledger.load_gold_manifest(args.gold)
    ranges = [r for r in (manifest.get("coverage") or []) if r.get("fully_annotated")]
    session = ranges[0]["session"]
    cov_from = float(ranges[0]["from_seconds"])
    cov_to = float(ranges[0]["to_seconds"])

    truth = [
        t
        for t in ledger.resolve_ledger(ledger.read_jsonl(ledger.TRUTH_PATH), "gold_id")
        if t.get("event", "ad_break") == "ad_break"
        and t["session"] == session
        and cov_from <= float(t["start_seconds"]) < cov_to
    ]
    truth.sort(key=lambda t: float(t["start_seconds"]))

    baseline = {}
    by_in = {}
    if BASELINE_CAUSES_PATH.exists():
        raw = json.loads(BASELINE_CAUSES_PATH.read_text(encoding="utf-8"))
        for ev in raw.get("events") or []:
            if ev.get("gold_id"):
                baseline[ev["gold_id"]] = ev.get("cause")
            by_in[round(float(ev["gold_in"]), 1)] = ev.get("cause")

    runs = [
        score_run("legacy_v0", args.legacy_run, truth, ranges, args.collar, session, cov_to),
        score_run("v1", args.v1_run, truth, ranges, args.collar, session, cov_to),
        score_run("v1_1", args.v11_run, truth, ranges, args.collar, session, cov_to),
    ]
    by_name = {r["name"]: r for r in runs}

    per_gold = []
    cause_delta = defaultdict(Counter)
    for g in truth:
        gid = g["gold_id"]
        t = float(g["start_seconds"])
        cause = baseline.get(gid) or by_in.get(round(t, 1)) or "unknown"

        def nearest(props):
            best = min(props, key=lambda r: abs(float(r["elapsed_seconds"]) - t))
            return float(best["elapsed_seconds"]), float(best["elapsed_seconds"]) - t

        row = {"gold_id": gid, "gold_in": t, "baseline_cause": cause}
        for name in ("legacy_v0", "v1", "v1_1"):
            r = by_name[name]
            is_tp = gid in set(r["tp_gold_ids"])
            nt, nd = nearest(r["props"])
            row[f"{name}_tp"] = is_tp
            row[f"{name}_nearest"] = nt
            row[f"{name}_delta"] = round(nd, 3)
        # change legacy→v11 and v1→v11
        if row["legacy_v0_tp"] and row["v1_1_tp"]:
            ch = "still_tp"
        elif (not row["legacy_v0_tp"]) and row["v1_1_tp"]:
            ch = "improved_fn_to_tp"
        elif row["legacy_v0_tp"] and (not row["v1_1_tp"]):
            ch = "regressed_tp_to_fn"
        else:
            ch = "still_fn"
        row["change_vs_legacy"] = ch
        if row["v1_tp"] and row["v1_1_tp"]:
            ch2 = "still_tp"
        elif (not row["v1_tp"]) and row["v1_1_tp"]:
            ch2 = "improved_fn_to_tp"
        elif row["v1_tp"] and (not row["v1_1_tp"]):
            ch2 = "regressed_tp_to_fn"
        else:
            ch2 = "still_fn"
        row["change_vs_v1"] = ch2
        cause_delta[cause][ch] += 1
        per_gold.append(row)

    l0, v1, v11 = by_name["legacy_v0"], by_name["v1"], by_name["v1_1"]
    report = {
        "question": (
            "Does separating episode detection from onset localization, with rolling "
            "intensity instead of linked clusters, explain more of the frozen errors?"
        ),
        "gold": args.gold,
        "session": session,
        "coverage": [cov_from, cov_to],
        "collar_s": args.collar,
        "truth_frozen": True,
        "runs": {
            name: {k: by_name[name][k] for k in (
                "run_id", "proposal_count", "tp", "fp", "fn", "precision", "recall", "in_error", "fp_taxonomy"
            )}
            for name in ("legacy_v0", "v1", "v1_1")
        },
        "delta_v11_vs_legacy": {
            "tp": v11["tp"] - l0["tp"],
            "fp": v11["fp"] - l0["fp"],
            "fn": v11["fn"] - l0["fn"],
        },
        "delta_v11_vs_v1": {
            "tp": v11["tp"] - v1["tp"],
            "fp": v11["fp"] - v1["fp"],
            "fn": v11["fn"] - v1["fn"],
        },
        "by_baseline_cause_vs_legacy": {k: dict(v) for k, v in cause_delta.items()},
        "per_gold": per_gold,
    }

    improved = sum(1 for r in per_gold if r["change_vs_legacy"] == "improved_fn_to_tp")
    regressed = sum(1 for r in per_gold if r["change_vs_legacy"] == "regressed_tp_to_fn")
    inside_down = v11["fp_taxonomy"].get("inside_break", 0) < l0["fp_taxonomy"].get("inside_break", 0)
    isolated = v11["fp_taxonomy"].get("isolated_program", 0)
    if improved >= 3 and regressed == 0 and (v11["fp"] <= l0["fp"] or inside_down):
        verdict = "YES — iterate episode+localize architecture"
    elif improved >= 2 and regressed <= 1:
        verdict = "PROMISING — semantics improved; keep iterating without abandoning"
    elif improved == 0 and v11["fp"] >= l0["fp"]:
        verdict = "NO — next evidence hypothesis"
    else:
        verdict = "MIXED — inspect localization receipts and FP taxonomy"
    report["architecture_verdict"] = verdict
    report["notes"] = {
        "isolated_program_fps": isolated,
        "session_edge_fps": v11["fp_taxonomy"].get("session_edge", 0),
    }

    out = ledger.ROOT / "experiments/reports" / f"compare_v1_1_{args.v11_run}_{args.gold}.json"
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    def pct(x):
        return "—" if x is None else f"{x:.1%}"

    md = [
        "# V1.1 vs V1 vs legacy — frozen GOLD_DEV_V1",
        "",
        report["question"],
        "",
        f"**Verdict:** {verdict}",
        "",
        "## Scores (±2s)",
        "",
        "| | legacy_v0 | v1 | v1.1 |",
        "|---|---:|---:|---:|",
        f"| TP | {l0['tp']} | {v1['tp']} | {v11['tp']} |",
        f"| FP | {l0['fp']} | {v1['fp']} | {v11['fp']} |",
        f"| FN | {l0['fn']} | {v1['fn']} | {v11['fn']} |",
        f"| Recall | {pct(l0['recall'])} | {pct(v1['recall'])} | {pct(v11['recall'])} |",
        f"| Precision | {pct(l0['precision'])} | {pct(v1['precision'])} | {pct(v11['precision'])} |",
        f"| Proposals | {l0['proposal_count']} | {v1['proposal_count']} | {v11['proposal_count']} |",
        "",
        "## FP taxonomy (re-rooted)",
        "",
        "| class | legacy | v1 | v1.1 |",
        "|---|---:|---:|---:|",
    ]
    classes = ["inside_break", "near_onset", "near_return", "isolated_program", "session_edge", "other"]
    for c in classes:
        md.append(
            f"| {c} | {l0['fp_taxonomy'].get(c, 0)} | {v1['fp_taxonomy'].get(c, 0)} | {v11['fp_taxonomy'].get(c, 0)} |"
        )
    md += ["", "## Change vs legacy by baseline cause", ""]
    for cause, counts in sorted(cause_delta.items()):
        md.append(f"- **{cause}**: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    md += ["", "## Each gold commercial", ""]
    for row in per_gold:
        md.append(
            f"- `{row['gold_in']:.1f}` · {row['baseline_cause']} · "
            f"legacyΔ={row['legacy_v0_delta']} v1Δ={row['v1_delta']} v11Δ={row['v1_1_delta']} · "
            f"**{row['change_vs_legacy']}** (vs v1: {row['change_vs_v1']})"
        )
    md_path = out.with_suffix(".md")
    md_path.write_text("\n".join(md) + "\n", encoding="utf-8")
    print(json.dumps({
        "architecture_verdict": verdict,
        "runs": report["runs"],
        "delta_v11_vs_legacy": report["delta_v11_vs_legacy"],
        "delta_v11_vs_v1": report["delta_v11_vs_v1"],
        "by_baseline_cause_vs_legacy": report["by_baseline_cause_vs_legacy"],
    }, indent=2))
    print("wrote", out)
    print("wrote", md_path)


if __name__ == "__main__":
    main()
