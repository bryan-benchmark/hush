"""Fold next_fp deep judgments into accepted labels and re-score 10-15."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from experiments.audio_learn.blind_cover_fold_score import (
    ACCEPTED,
    COVERAGE,
    OUT,
    SESSION,
    SOURCE as BLIND_SOURCE,
    append_accepted,
    score_one,
)
from experiments.audio_learn.controller import decisions
from experiments.audio_learn.encoder import DATA_ROOT
from experiments.audio_learn.product_scorecard import load_accepted
from experiments.audio_learn.research_latch import apply_research_latch
from experiments.ledger import sha256_file

JUDGMENTS = Path(r"c:\Users\faceo\Projects\ohush\docs\ohush\research\BROADCAST_DEEP_LABEL_001\judgments.json")
QUEUE = Path(r"c:\Users\faceo\Projects\ohush\docs\ohush\research\BROADCAST_DEEP_LABEL_001\queue.jsonl")
SOURCE = "deep_label_next_fp"
WAVE = "next_fp"

# Top-6 covers that were queued (from NEXT_FP_CANDIDATES).
COVERS = (
    ("fp1_86s", 1955.5, 2041.75),
    ("fp2_78s", 980.25, 1058.25),
    ("fp3_78s", 6256.5, 6334.0),
    ("fp4_71s", 6729.75, 6800.5),
    ("fp5_66s", 3534.5, 3600.25),
    ("fp6_64s", 5419.25, 5483.5),
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


def fold_next_fp() -> list[dict]:
    judgments = json.loads(JUDGMENTS.read_text(encoding="utf-8"))
    queue = {
        json.loads(line)["clip"]: json.loads(line)
        for line in QUEUE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    rows: list[dict] = []
    notes: list[str] = []
    for name, c0, c1 in COVERS:
        nb: list[tuple[float, float]] = []
        bc: list[tuple[float, float]] = []
        skipped = 0
        for clip, item in judgments.items():
            q = queue.get(clip)
            if not q or WAVE not in str(q.get("why", "")):
                continue
            a, b = float(q["t0"]), float(q["t1"])
            if b <= c0 or a >= c1:
                continue
            bucket = item.get("bucket")
            if bucket == "unsure":
                skipped += 1
                notes.append(f"{name}: skipped unsure {a:.1f}-{b:.1f} ({item.get('speaker','')[:60]})")
                continue
            # Tail of fp6: commercial until 28s, then Michaels broadcast.
            if name == "fp6_64s" and abs(a - 5453.5) < 0.2 and abs(b - 5483.5) < 0.2:
                split = a + 28.0
                if bucket == "non_broadcast":
                    nb.append((a, split))
                    bc.append((split, b))
                    notes.append(f"{name}: return at +28s → broadcast {split:.1f}-{b:.1f}")
                continue
            if bucket == "non_broadcast":
                nb.append((a, b))
            elif bucket == "broadcast":
                bc.append((a, b))
        nb_merged = _merge(nb)
        if len(nb_merged) >= 2:
            filled = [nb_merged[0]]
            for a, b in nb_merged[1:]:
                prev_a, prev_b = filled[-1]
                if a - prev_b <= 25.0:
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
                    "note": f"deep label {name} return",
                    "status": "accepted",
                    "cover_name": name,
                }
            )
        if skipped:
            notes.append(f"{name}: {skipped} unsure slice(s) left out of accepted")
    (OUT / "NEXT_FP_FOLD_NOTES.json").write_text(json.dumps({"notes": notes, "rows": rows}, indent=2), encoding="utf-8")
    return rows


def append_source(rows: list[dict], source: str) -> int:
    ACCEPTED.parent.mkdir(parents=True, exist_ok=True)
    existing = []
    if ACCEPTED.is_file():
        existing = [json.loads(line) for line in ACCEPTED.read_text(encoding="utf-8").splitlines() if line.strip()]
    kept = [r for r in existing if not (r.get("session") == SESSION and r.get("source") == source)]
    kept.extend(rows)
    ACCEPTED.write_text("".join(json.dumps(r) + "\n" for r in kept), encoding="utf-8")
    return len(rows)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    folded = fold_next_fp()
    n = append_source(folded, SOURCE)
    accepted = load_accepted()
    # ensure prior blind fold still present
    n_session = sum(1 for r in accepted if r.get("session") == SESSION)
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
        reasons.append("next_fp pods mostly ads; stack holds cov vs cool; return not worsened")

    nb_s = sum(r["dur_s"] for r in folded if r["bucket"] == "non_broadcast")
    bc_s = sum(r["dur_s"] for r in folded if r["bucket"] == "broadcast")
    summary = {
        "session": SESSION,
        "wave": WAVE,
        "n_appended": n,
        "session_accepted_rows": n_session,
        "folded_non_broadcast_s": round(nb_s, 2),
        "folded_broadcast_s": round(bc_s, 2),
        "verdict": (
            "17/18 next_fp slices are commercials. 1 unsure (FanDuel onset 3534–3564) left out. "
            "Show return: last ~2s of 5419–5483 cover (Michaels at +28s on tail)."
        ),
        "decision_vs_cool": {"decision": decision, "reasons": reasons, "delta": delta},
        "results": results,
        "note": "Partial ontology (labeled pods only). Not live-locked.",
        "frozen_head_sha256": sha256_file(DATA_ROOT / "checkpoints" / "frozen_head.pt"),
        "prior_blind_source": BLIND_SOURCE,
    }
    (OUT / "NEXT_FP_LABELED_SCORE.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    lines = [
        "# Next FP wave — labeled score",
        "",
        summary["verdict"],
        "",
        f"## vs cool: **{decision}**",
        *[f"- {r}" for r in reasons],
        f"- `{json.dumps(delta)}`",
        "",
        f"Appended {n} rows ({nb_s:.0f}s ads, {bc_s:.1f}s return). Session accepted rows now {n_session}.",
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
    ]
    (OUT / "NEXT_FP_LABELED_SCORE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "decision": decision,
                "delta": delta,
                "cool_cov": cool["non_broadcast_coverage"],
                "stack_cov": stack["non_broadcast_coverage"],
                "nb_s": nb_s,
                "bc_s": bc_s,
                "n": n,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
