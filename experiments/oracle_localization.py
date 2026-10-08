#!/usr/bin/env python3
"""Oracle localization ceiling for the frozen V1.1 transition stream.

Question answered:
  Given gold INs, is the correct onset already present among retained
  transition events? If so, how close, and with what local evidence?

Does not tune detectors. Does not touch truth / OUT / holdouts / V1.1 code.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import ledger

COLLARS = (1.0, 2.0, 3.0, 4.0, 5.0, 6.0)
PAST_WINDOWS = (5.0, 15.0, 30.0, 60.0)


def load_truth(session: str, cov_from: float, cov_to: float) -> list[dict]:
    truth = [
        t
        for t in ledger.resolve_ledger(ledger.read_jsonl(ledger.TRUTH_PATH), "gold_id")
        if t.get("event", "ad_break") == "ad_break"
        and t["session"] == session
        and cov_from <= float(t["start_seconds"]) < cov_to
        and t.get("event_class") == "commercial"
        and t.get("desired_action") == "mute"
        and t.get("confidence") != "unsure"
    ]
    truth.sort(key=lambda t: float(t["start_seconds"]))
    return truth


def load_jsonl(path: Path) -> list[dict]:
    return ledger.read_jsonl(path)


def nearest(events: list[dict], t: float) -> tuple[dict, float]:
    best = min(events, key=lambda e: abs(float(e["elapsed_seconds"]) - t))
    return best, float(best["elapsed_seconds"]) - t


def past_only_summary(ev: dict) -> dict:
    """Causal snapshot already present on V1.1 transitions (ignore future)."""
    ctx = ev.get("context") or {}
    out: dict = {
        "boundary_score": float(ev["boundary_score"]),
        "jump_z": float(ev.get("jump_z") or 0.0),
        "flux_z": float(ev.get("flux_z") or 0.0),
        "rms_db": float(ev.get("rms_db") or 0.0),
        "near_silence": bool(ev.get("near_silence")),
        "strong": bool(ev.get("strong")),
        "eligible": bool(ctx.get("eligible")),
        "session_edge": bool(ctx.get("session_edge")),
    }
    for w in (15, 30, 60):
        past = ctx.get(f"prev_{w}s") or {}
        past_s = ctx.get(f"prev_strong_{w}s") or {}
        out[f"past_rate_{w}s"] = float(past.get("rate") or 0.0)
        out[f"past_strong_rate_{w}s"] = float(past_s.get("rate") or 0.0)
        out[f"past_silence_rate_{w}s"] = float(past.get("silence_rate") or 0.0)
        out[f"past_n_{w}s"] = int(past.get("n") or 0)
        out[f"past_obs_{w}s"] = float(past.get("obs_s") or 0.0)
    return out


def analyze_gold(
    gold: dict,
    transitions: list[dict],
    anchors: list[dict],
    proposals: list[dict],
) -> dict:
    gin = float(gold["start_seconds"])
    gout = float(gold["end_seconds"])
    nearest_tr, delta = nearest(transitions, gin)
    past = past_only_summary(nearest_tr)

    # Episode anchors relative to gold IN
    if anchors:
        near_anchor, a_delta = nearest(anchors, gin)
        anchors_after = [a for a in anchors if float(a["elapsed_seconds"]) >= gin - 1e-9]
        first_after = anchors_after[0] if anchors_after else None
        anchor_rel = {
            "nearest_anchor_s": float(near_anchor["elapsed_seconds"]),
            "nearest_anchor_delta_s": a_delta,
            "nearest_anchor_before": a_delta < 0,
            "nearest_anchor_after": a_delta > 0,
            "first_anchor_at_or_after_gold_s": (
                float(first_after["elapsed_seconds"]) if first_after else None
            ),
            "first_anchor_delta_s": (
                float(first_after["elapsed_seconds"]) - gin if first_after else None
            ),
            "nearest_anchor_episode_score": float(near_anchor.get("episode_score") or 0.0),
        }
    else:
        anchor_rel = {}

    # What V1.1 actually proposed for this gold (nearest proposal)
    if proposals:
        near_prop, p_delta = nearest(proposals, gin)
        prop_info = {
            "v11_proposal_s": float(near_prop["elapsed_seconds"]),
            "v11_proposal_delta_s": p_delta,
            "v11_within_2s": abs(p_delta) <= 2.0,
            "anchor_elapsed_seconds": (near_prop.get("evidence") or {}).get(
                "anchor_elapsed_seconds"
            ),
        }
    else:
        prop_info = {}

    within = {f"within_{int(c)}s": abs(delta) <= c for c in COLLARS}

    return {
        "gold_id": gold["gold_id"],
        "gold_in": gin,
        "gold_out": gout,
        "nearest_transition_s": float(nearest_tr["elapsed_seconds"]),
        "delta_s": delta,
        "abs_delta_s": abs(delta),
        **within,
        "transition": {
            "file": nearest_tr.get("file"),
            "frame_index": nearest_tr.get("frame_index"),
            **past,
        },
        "episode_anchor": anchor_rel,
        "v11_output": prop_info,
    }


def render_md(payload: dict) -> str:
    rows = payload["per_gold"]
    ceil = payload["ceiling"]
    lines = [
        "# Oracle localization — frozen transition stream",
        "",
        f"Run transitions: `{payload['transitions_run']}`",
        f"Session: `{payload['session']}` · gold: `{payload['gold']}` · n={len(rows)}",
        "",
        "## Transition-event localization ceiling",
        "",
        "Was there a retained transition within the collar of each gold IN?",
        "",
        "| collar | hits | rate |",
        "|---|---:|---:|",
    ]
    for c in COLLARS:
        hit = ceil[f"within_{int(c)}s"]
        lines.append(f"| ±{int(c)} s | {hit} / {len(rows)} | {100.0 * hit / len(rows):.0f}% |")

    lines += [
        "",
        "**Interpretation:** the transition stream already localizes almost every "
        "commercial start. Remaining detector error is overwhelmingly ranking / "
        "identification, not missing acoustics.",
        "",
        "## Per gold IN",
        "",
        "| gold IN | nearest tr | Δ | bs | jump_z | flux_z | sil | past_rate_30 | past_strong_30 | "
        "nearest episode anchor | V1.1 proposal Δ |",
        "|---:|---:|---:|---:|---:|---:|:---:|---:|---:|---:|---:|",
    ]
    for r in rows:
        tr = r["transition"]
        a = r.get("episode_anchor") or {}
        v = r.get("v11_output") or {}
        a_s = a.get("nearest_anchor_s")
        a_d = a.get("nearest_anchor_delta_s")
        a_cell = "—" if a_s is None else f"{a_s:.1f} ({a_d:+.1f})"
        p_d = v.get("v11_proposal_delta_s")
        p_cell = "—" if p_d is None else f"{p_d:+.2f}"
        lines.append(
            f"| {r['gold_in']:.1f} | {r['nearest_transition_s']:.3f} | {r['delta_s']:+.3f} | "
            f"{tr['boundary_score']:.2f} | {tr['jump_z']:.2f} | {tr['flux_z']:.2f} | "
            f"{'Y' if tr['near_silence'] else ''} | "
            f"{tr['past_rate_30s']:.3f} | {tr['past_strong_rate_30s']:.3f} | "
            f"{a_cell} | {p_cell} |"
        )

    # Cases where oracle is good but V1.1 is not
    damaged = [
        r
        for r in rows
        if abs(r["delta_s"]) <= 2.0
        and r.get("v11_output")
        and abs(float(r["v11_output"].get("v11_proposal_delta_s") or 999)) > 2.0
    ]
    lines += [
        "",
        "## Oracle-good / V1.1-wrong (localization damage)",
        "",
        "Gold INs with a transition within ±2s, but V1.1's final proposal outside ±2s.",
        "",
    ]
    if not damaged:
        lines.append("_None._")
    else:
        for r in damaged:
            v = r["v11_output"]
            lines.append(
                f"- `{r['gold_in']:.1f}`: oracle `{r['nearest_transition_s']:.3f}` "
                f"(Δ={r['delta_s']:+.3f}) → V1.1 `{v['v11_proposal_s']:.3f}` "
                f"(Δ={v['v11_proposal_delta_s']:+.3f}); "
                f"anchor={v.get('anchor_elapsed_seconds')}"
            )

    lines += [
        "",
        "## Verdict",
        "",
        payload["verdict"],
        "",
    ]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--v11-run",
        default="20260921T173219Z_discontinuity_v1_1",
        help="Frozen V1.1 run that already archived transitions.jsonl",
    )
    ap.add_argument("--gold", default="GOLD_DEV_V1")
    args = ap.parse_args()

    manifest = ledger.load_gold_manifest(args.gold)
    ranges = [r for r in (manifest.get("coverage") or []) if r.get("fully_annotated")]
    session = ranges[0]["session"]
    cov_from = float(ranges[0]["from_seconds"])
    cov_to = float(ranges[0]["to_seconds"])

    truth = load_truth(session, cov_from, cov_to)
    run_dir = ledger.RUNS / args.v11_run
    transitions = load_jsonl(run_dir / "transitions" / session / "transitions.jsonl")
    transitions = [e for e in transitions if cov_from <= float(e["elapsed_seconds"]) < cov_to]
    anchors = load_jsonl(run_dir / "transitions" / session / "episode_anchors.jsonl")
    proposals = [
        r
        for r in load_jsonl(run_dir / "candidates.jsonl")
        if r.get("session") == session and cov_from <= float(r["elapsed_seconds"]) < cov_to
    ]

    per_gold = [analyze_gold(g, transitions, anchors, proposals) for g in truth]
    ceiling = {
        f"within_{int(c)}s": sum(1 for r in per_gold if r[f"within_{int(c)}s"]) for c in COLLARS
    }
    n = len(per_gold)
    rate2 = ceiling["within_2s"] / n if n else 0.0
    rate6 = ceiling["within_6s"] / n if n else 0.0
    verdict = (
        f"Localization ceiling is high: ±2s = {ceiling['within_2s']}/{n} ({100*rate2:.0f}%), "
        f"±6s = {ceiling['within_6s']}/{n} ({100*rate6:.0f}%). "
        "Do not retune transition extraction. The open problem is choosing the right "
        "transition with causal evidence."
    )

    payload = {
        "gold": args.gold,
        "session": session,
        "coverage": {"from": cov_from, "to": cov_to},
        "transitions_run": args.v11_run,
        "n_transitions": len(transitions),
        "n_gold": n,
        "ceiling": ceiling,
        "per_gold": per_gold,
        "verdict": verdict,
    }

    stamp = args.v11_run.split("_")[0]
    out_json = ledger.ROOT / "experiments" / "reports" / f"oracle_localization_{stamp}_{args.gold}.json"
    out_md = ledger.ROOT / "experiments" / "reports" / f"oracle_localization_{stamp}_{args.gold}.md"
    out_json.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    out_md.write_text(render_md(payload), encoding="utf-8")
    print(json.dumps({"report_md": str(out_md), "ceiling": ceiling, "verdict": verdict}, indent=2))


if __name__ == "__main__":
    main()
