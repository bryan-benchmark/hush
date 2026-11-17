"""Fold deep judgments for hush_20261015 covers into accepted labels + score.

Writes:
  C:\\OHushData\\gpu_lab\\audio_learn\\broadcast_labels\\labels_accepted.jsonl (append)
  C:\\OHushData\\gpu_lab\\audio_learn\\blind_prime_1015\\LABELED_SCORE.*
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from experiments.audio_learn.controller import decisions
from experiments.audio_learn.encoder import DATA_ROOT
from experiments.audio_learn.product_scorecard import DATA, _ol, load_accepted
from experiments.audio_learn.research_latch import apply_research_latch
from experiments.audio_learn.studio_fit import CONTROLLER as CTRL
from experiments.ledger import sha256_file
from experiments.nfl75.score import playback_from_decisions, score_product

SESSION = "hush_20261015_210805"
COVERAGE = (0.0, 12753.749)
JUDGMENTS = Path(r"c:\Users\faceo\Projects\ohush\docs\ohush\research\BROADCAST_DEEP_LABEL_001\judgments.json")
QUEUE = Path(r"c:\Users\faceo\Projects\ohush\docs\ohush\research\BROADCAST_DEEP_LABEL_001\queue.jsonl")
ACCEPTED = DATA / "broadcast_labels" / "labels_accepted.jsonl"
OUT = DATA / "blind_prime_1015"
SOURCE = "deep_label_blind_tnf_covers"


COVERS = (
    ("cover_130s", 4667.0, 4797.25),
    ("cover_112s", 8088.25, 8200.75),
    ("cover_93s", 7782.5, 7876.0),
    ("cover_92s", 3167.75, 3259.75),
)


def _merge(ranges: list[tuple[float, float]]) -> list[tuple[float, float]]:
    if not ranges:
        return []
    ordered = sorted(ranges)
    out = [list(ordered[0])]
    for a, b in ordered[1:]:
        if a <= out[-1][1] + 1e-6:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


def fold_labels() -> list[dict]:
    judgments = json.loads(JUDGMENTS.read_text(encoding="utf-8"))
    queue = {
        json.loads(line)["clip"]: json.loads(line)
        for line in QUEUE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    rows: list[dict] = []
    for name, c0, c1 in COVERS:
        nb: list[tuple[float, float]] = []
        bc: list[tuple[float, float]] = []
        for clip, item in judgments.items():
            if not clip.startswith(SESSION):
                continue
            q = queue.get(clip)
            if not q:
                continue
            a, b = float(q["t0"]), float(q["t1"])
            if b <= c0 or a >= c1:
                continue
            # Owner: last 22s of 130s tail are broadcast return.
            if name == "cover_130s" and abs(a - 4767.2) < 0.2 and abs(b - 4797.2) < 0.2:
                split = b - 22.0
                nb.append((a, split))
                bc.append((split, b))
                continue
            if item.get("bucket") == "non_broadcast":
                nb.append((a, b))
            elif item.get("bucket") == "broadcast":
                bc.append((a, b))
        # Fill interior gaps inside the cover when both sides are ads.
        nb_merged = _merge(nb)
        if len(nb_merged) >= 2:
            filled = [nb_merged[0]]
            for a, b in nb_merged[1:]:
                prev_a, prev_b = filled[-1]
                if a - prev_b <= 25.0:  # onset/mid/tail spacing
                    filled[-1] = (prev_a, b)
                else:
                    filled.append((a, b))
            nb_merged = filled
        for a, b in nb_merged:
            rows.append(
                {
                    "session": SESSION,
                    "start_s": round(a, 3),
                    "end_s": round(b, 3),
                    "dur_s": round(b - a, 3),
                    "bucket": "non_broadcast",
                    "kind": "standalone_spot",
                    "desired_action": "mute",
                    "source": SOURCE,
                    "confidence": "high",
                    "note": f"deep label {name}",
                    "status": "accepted",
                    "cover_name": name,
                }
            )
        for a, b in _merge(bc):
            rows.append(
                {
                    "session": SESSION,
                    "start_s": round(a, 3),
                    "end_s": round(b, 3),
                    "dur_s": round(b - a, 3),
                    "bucket": "broadcast",
                    "kind": "show_return",
                    "desired_action": "play",
                    "source": SOURCE,
                    "confidence": "high",
                    "note": f"deep label {name} return (last 22s of tail)",
                    "status": "accepted",
                    "cover_name": name,
                }
            )
    return rows


def append_accepted(rows: list[dict]) -> int:
    ACCEPTED.parent.mkdir(parents=True, exist_ok=True)
    existing = []
    if ACCEPTED.is_file():
        existing = [json.loads(line) for line in ACCEPTED.read_text(encoding="utf-8").splitlines() if line.strip()]
    # drop prior folds from this source/session
    kept = [
        r
        for r in existing
        if not (r.get("session") == SESSION and r.get("source") == SOURCE)
    ]
    kept.extend(rows)
    ACCEPTED.write_text("".join(json.dumps(r) + "\n" for r in kept), encoding="utf-8")
    return len(rows)


def score_one(times: np.ndarray, probs: np.ndarray, accepted: list[dict]) -> dict:
    from experiments.audio_learn.product_scorecard import broadcast_rows, non_broadcast_intervals

    intervals = non_broadcast_intervals(SESSION, accepted)
    rows = decisions(times.tolist(), probs.tolist(), **CTRL)
    spans = playback_from_decisions(COVERAGE, rows)
    scored = score_product(
        COVERAGE,
        intervals,
        spans,
        session=SESSION,
        excluded_ranges=[],
        wall_gap_s=0.0,
        audio_present=True,
    )
    brows = broadcast_rows(SESSION, accepted)
    cells = {
        "desk_s": 0.0,
        "show_return_s": 0.0,
        "other_broadcast_s": 0.0,
        "unlabeled_program_s": 0.0,
    }
    for ep in scored["episodes"]:
        a0, a1 = float(ep["start_s"]), float(ep["end_s"])
        dur = float(ep["duration_s"])
        ret_ol = sum(
            _ol(a0, a1, float(r["start_s"]), float(r["end_s"]))
            for r in brows
            if r.get("kind") == "show_return"
        )
        other_ol = sum(
            _ol(a0, a1, float(r["start_s"]), float(r["end_s"]))
            for r in brows
            if r.get("kind") != "show_return"
        )
        ret_part = min(dur, ret_ol)
        rem = max(0.0, dur - ret_part)
        other_part = min(rem, other_ol)
        unlab = max(0.0, rem - other_part)
        cells["show_return_s"] += ret_part
        cells["other_broadcast_s"] += other_part
        cells["unlabeled_program_s"] += unlab
    focus = {}
    for name, c0, c1 in COVERS:
        focus[name] = round(sum(_ol(float(ep["start_s"]), float(ep["end_s"]), c0, c1) for ep in scored["episodes"]), 3)
    return {
        "session": SESSION,
        "non_broadcast_coverage": scored.get("commercial_coverage"),
        "non_broadcast_covered_s": round(float(scored.get("commercial_covered_s") or 0), 3),
        "non_broadcast_s": round(float(scored.get("commercial_s") or 0), 3),
        "broadcast_muted_s": round(float(scored.get("program_covered_s") or 0), 3),
        "false_mute_episodes": scored.get("false_mute_episodes"),
        "longest_false_mute_s": scored.get("longest_false_mute_s"),
        "cells": {k: round(v, 3) for k, v in cells.items()},
        "focus_cover_muted_s": focus,
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    folded = fold_labels()
    n = append_accepted(folded)
    accepted = load_accepted()
    pred = np.load(DATA_ROOT / "predictions" / "frozen" / f"{SESSION}.npz")
    times = pred["t"].astype(np.float64)
    frozen_p = pred["p"].astype(np.float64)
    cool_p = apply_research_latch(SESSION, times, frozen_p, with_voice=False)
    stack_p = apply_research_latch(SESSION, times, frozen_p, with_voice=True)

    results = {
        "frozen": score_one(times, frozen_p, accepted),
        "cool": score_one(times, cool_p, accepted),
        "stack": score_one(times, stack_p, accepted),
    }
    cool, stack = results["cool"], results["stack"]
    delta = {
        "cov_delta": round(
            (stack["non_broadcast_coverage"] or 0) - (cool["non_broadcast_coverage"] or 0), 4
        ),
        "broadcast_muted_delta": round(stack["broadcast_muted_s"] - cool["broadcast_muted_s"], 1),
        "show_return_delta": round(
            stack["cells"]["show_return_s"] - cool["cells"]["show_return_s"], 1
        ),
        "longest_fp_delta": round(
            float(stack["longest_false_mute_s"] or 0) - float(cool["longest_false_mute_s"] or 0), 2
        ),
    }
    decision = "KEEP"
    reasons = []
    if -delta["cov_delta"] > 0.02:
        decision = "REJECT"
        reasons.append(f"coverage drop {-delta['cov_delta']:.4f} > 0.02")
    if delta["show_return_delta"] > 2:
        decision = "REJECT"
        reasons.append(f"show_return muted grew {delta['show_return_delta']}")
    if decision == "KEEP":
        reasons.append("labeled covers are ads; stack holds coverage vs cool within 2pt; return not worsened")

    summary = {
        "session": SESSION,
        "folded_rows": folded,
        "n_appended": n,
        "verdict": (
            "All 12 listen slices are commercials (non_broadcast). "
            "One show_return: last 22s of cover_130s tail (~4775–4797)."
        ),
        "decision_vs_cool": {"decision": decision, "reasons": reasons, "delta": delta},
        "results": results,
        "note": "Partial ontology on this tape (four pods only). Not a full-game gold score.",
        "frozen_head_sha256": sha256_file(DATA_ROOT / "checkpoints" / "frozen_head.pt"),
    }
    (OUT / "LABELED_SCORE.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    lines = [
        "# Blind TNF covers — labeled score",
        "",
        summary["verdict"],
        "",
        f"## vs cool: **{decision}**",
        *[f"- {r}" for r in reasons],
        f"- `{json.dumps(delta)}`",
        "",
        "## Cool",
        f"- coverage {cool['non_broadcast_coverage']}",
        f"- non_broadcast {cool['non_broadcast_covered_s']} / {cool['non_broadcast_s']}",
        f"- broadcast_muted_s {cool['broadcast_muted_s']}",
        f"- show_return_s {cool['cells']['show_return_s']}",
        f"- longest_fp {cool['longest_false_mute_s']}",
        "",
        "## Stack",
        f"- coverage {stack['non_broadcast_coverage']}",
        f"- non_broadcast {stack['non_broadcast_covered_s']} / {stack['non_broadcast_s']}",
        f"- broadcast_muted_s {stack['broadcast_muted_s']}",
        f"- show_return_s {stack['cells']['show_return_s']}",
        f"- longest_fp {stack['longest_false_mute_s']}",
        "",
        "## Cover muted (stack)",
        *[f"- {k}: {v}s" for k, v in stack["focus_cover_muted_s"].items()],
        "",
        "Partial labels only — four pods. Not live-locked.",
    ]
    (OUT / "LABELED_SCORE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"decision": decision, "delta": delta, "cool_cov": cool["non_broadcast_coverage"], "stack_cov": stack["non_broadcast_coverage"]}, indent=2))


if __name__ == "__main__":
    main()
