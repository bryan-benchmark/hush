#!/usr/bin/env python3
"""Diff two runs by time, not by proposal id."""

from __future__ import annotations

import argparse
import json

import event_match
import ledger


def keeps(run_id: str) -> list[dict]:
    path = ledger.RUNS / run_id / "candidates.jsonl"
    if not path.exists():
        raise SystemExit(f"no candidates in {run_id}")
    return ledger.read_jsonl(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_a")
    ap.add_argument("run_b")
    ap.add_argument("--collar", type=float, default=event_match.DEFAULT_COLLAR_S)
    args = ap.parse_args()
    diff = event_match.diff_keeps(keeps(args.run_a), keeps(args.run_b), args.collar)
    truth = ledger.resolve_ledger(ledger.read_jsonl(ledger.TRUTH_PATH), "gold_id")
    reviews = ledger.resolve_ledger(ledger.read_jsonl(ledger.REVIEWS_PATH), "review_id")
    for bucket in ("kept_in_both", "moved", "score_shifted", "removed", "added"):
        for row in diff[bucket]:
            t = float(row.get("a_seconds", row.get("seconds")))
            session = row["session"]
            row["nearby_gold_ids"] = [
                g["gold_id"]
                for g in truth
                if g.get("session") == session and abs(float(g["start_seconds"]) - t) <= args.collar
            ]
            ids = [row.get("a_proposal_id"), row.get("b_proposal_id"), row.get("proposal_id")]
            row["review_ids"] = [r["review_id"] for r in reviews if r.get("proposal_id") in ids]
    out = ledger.ROOT / "experiments" / "reports" / f"diff_{args.run_a}__{args.run_b}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    summary = {k: (len(v) if isinstance(v, list) else v) for k, v in diff.items()}
    out.write_text(json.dumps({"summary": summary, **diff}, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
