"""Fold residual_desk judgments into accepted labels and re-score product stack."""

from __future__ import annotations

import json
from pathlib import Path

from experiments.audio_learn.product_scorecard import DATA, load_accepted, load_frozen_probs, score_run
from experiments.audio_learn.research_latch import apply_research_latch
from experiments.audio_learn.splits import EVAL
from experiments.ledger import sha256_file

JUDGMENTS = Path(r"c:\Users\faceo\Projects\ohush\docs\ohush\research\BROADCAST_DEEP_LABEL_001\judgments.json")
QUEUE = Path(r"c:\Users\faceo\Projects\ohush\docs\ohush\research\BROADCAST_DEEP_LABEL_001\queue.jsonl")
ACCEPTED = DATA / "broadcast_labels" / "labels_accepted.jsonl"
OUT = DATA / "product_latch_card"
SOURCE = "deep_label_residual_desk"
WAVE = "residual_desk"


def fold() -> tuple[list[dict], dict]:
    judgments = json.loads(JUDGMENTS.read_text(encoding="utf-8"))
    queue = {
        json.loads(line)["clip"]: json.loads(line)
        for line in QUEUE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    rows: list[dict] = []
    tally = {"broadcast_clips": 0, "non_broadcast_clips": 0, "unsure_clips": 0, "splits": []}
    for clip, q in queue.items():
        if WAVE not in str(q.get("why", "")):
            continue
        item = judgments.get(clip)
        if not item:
            continue
        a, b = float(q["t0"]), float(q["t1"])
        session = q["session"]
        bucket = item.get("bucket")
        kind = item.get("kind") or "studio_desk"
        speaker = (item.get("speaker") or "").lower()
        note = (item.get("note") or speaker)[:120]
        if bucket == "unsure":
            tally["unsure_clips"] += 1
            continue
        # 3430: first 7s dog food, then Clarissa intro (owner marked broadcast overall)
        if "dog food" in speaker and "clarissa" in speaker:
            split = a + 7.0
            rows.append(_row(session, a, split, "non_broadcast", "standalone_spot", "dog food commercial"))
            rows.append(_row(session, split, b, "broadcast", "studio_desk", "clarissa intro after spot"))
            tally["splits"].append(f"{session} {a:.1f}-{b:.1f} dogfood→desk @+7s")
            tally["broadcast_clips"] += 1
            tally["non_broadcast_clips"] += 1
            continue
        # 7509: Clarissa outro into commercial at ~8s — keep labeled broadcast window as play
        if bucket == "non_broadcast":
            rows.append(_row(session, a, b, "non_broadcast", kind if kind != "unknown" else "standalone_spot", note))
            tally["non_broadcast_clips"] += 1
        elif bucket == "broadcast":
            rows.append(_row(session, a, b, "broadcast", kind if kind != "unknown" else "studio_desk", note))
            tally["broadcast_clips"] += 1
    return rows, tally


def _row(session: str, a: float, b: float, bucket: str, kind: str, note: str) -> dict:
    return {
        "session": session,
        "start_s": round(a, 3),
        "end_s": round(b, 3),
        "dur_s": round(b - a, 3),
        "bucket": bucket,
        "kind": kind,
        "desired_action": "mute" if bucket == "non_broadcast" else "play",
        "source": SOURCE,
        "confidence": "high",
        "note": note,
        "status": "accepted",
    }


def append_source(rows: list[dict]) -> int:
    existing = []
    if ACCEPTED.is_file():
        existing = [json.loads(line) for line in ACCEPTED.read_text(encoding="utf-8").splitlines() if line.strip()]
    kept = [r for r in existing if r.get("source") != SOURCE]
    kept.extend(rows)
    ACCEPTED.parent.mkdir(parents=True, exist_ok=True)
    ACCEPTED.write_text("".join(json.dumps(r) + "\n" for r in kept), encoding="utf-8")
    return len(rows)


def _span_muted(game: dict, start: float, end: float) -> float:
    total = 0.0
    for ep in game.get("episodes", []):
        total += max(0.0, min(float(ep["end_s"]), end) - max(float(ep["start_s"]), start))
    return round(total, 2)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rows, tally = fold()
    n = append_source(rows)
    frozen = load_frozen_probs(EVAL)
    cool = {s: (t, apply_research_latch(s, t, p, with_voice=False)) for s, (t, p) in frozen.items()}
    stack = {s: (t, apply_research_latch(s, t, p, with_voice=True)) for s, (t, p) in frozen.items()}
    cool_rep = score_run("residual_desk_cool", cool, OUT)
    stack_rep = score_run("residual_desk_stack", stack, OUT)
    cool_a, stack_a = cool_rep["aggregate"], stack_rep["aggregate"]
    g24 = next(g for g in stack_rep["games"] if g["session"] == "hush_20260924_220624")
    g24c = next(g for g in cool_rep["games"] if g["session"] == "hush_20260924_220624")

    delta = {
        "cov_delta": round(stack_a["non_broadcast_coverage"] - cool_a["non_broadcast_coverage"], 4),
        "broadcast_muted_delta": round(stack_a["broadcast_muted_s"] - cool_a["broadcast_muted_s"], 1),
        "desk_delta": round(stack_a["cells"]["desk_s"] - cool_a["cells"]["desk_s"], 1),
        "odell_delta": round(
            stack_a["focus"]["hush_20260924_220624"]["odell"] - cool_a["focus"]["hush_20260924_220624"]["odell"],
            2,
        ),
        "amex_delta": round(
            stack_a["focus"]["hush_20261008_205100"]["amex"] - cool_a["focus"]["hush_20261008_205100"]["amex"],
            2,
        ),
        "chilis_delta": round(
            stack_a["focus"]["hush_20260924_220624"]["chilis"] - cool_a["focus"]["hush_20260924_220624"]["chilis"],
            2,
        ),
        "injury_muted_s": _span_muted(g24, 6267.8, 6287.2),
        "desk5_muted_s": _span_muted(g24, 6315.2, 6336.5),
        "injury_muted_cool": _span_muted(g24c, 6267.8, 6287.2),
        "desk5_muted_cool": _span_muted(g24c, 6315.2, 6336.5),
    }

    # Residual cores still muted under stack (from candidates)
    cand = json.loads((OUT / "RESIDUAL_DESK_CANDIDATES.json").read_text(encoding="utf-8"))
    residual_receipts = []
    for c in cand:
        if c.get("kind") != "stack_desk_residual":
            continue
        game = next(g for g in stack_rep["games"] if g["session"] == c["session"])
        muted = _span_muted(game, float(c["core_start"]), float(c["core_end"]))
        residual_receipts.append(
            {
                "session": c["session"],
                "core": [c["core_start"], c["core_end"]],
                "still_muted_s": muted,
            }
        )

    nb_s = sum(r["dur_s"] for r in rows if r["bucket"] == "non_broadcast")
    bc_s = sum(r["dur_s"] for r in rows if r["bucket"] == "broadcast")
    speakers = sorted(
        {
            (json.loads(JUDGMENTS.read_text(encoding="utf-8")).get(clip, {}).get("speaker") or "")[:40]
            for clip, q in {
                json.loads(line)["clip"]: json.loads(line)
                for line in QUEUE.read_text(encoding="utf-8").splitlines()
                if line.strip()
            }.items()
            if WAVE in str(q.get("why", ""))
        }
    )
    summary = {
        "wave": WAVE,
        "n_appended": n,
        "folded_non_broadcast_s": round(nb_s, 2),
        "folded_broadcast_s": round(bc_s, 2),
        "tally": tally,
        "speaker_notes": [s for s in speakers if s],
        "delta_stack_vs_cool": delta,
        "cool": cool_a,
        "stack": stack_a,
        "residual_cores_still_muted": residual_receipts,
        "verdict": (
            "All residual_desk listens are real broadcast (Whit/Fitz/Gonzalez/Clarissa/Michaels desk or booth). "
            "One split: dog-food spot then Clarissa intro. Stack still leaves named-desk scrap — next latch "
            "needs speakers outside the KEEP panel or stronger Clarissa/Fitz coverage, without Michaels on the OR."
        ),
        "frozen_head_sha256": sha256_file(DATA / "checkpoints" / "frozen_head.pt"),
        "live": False,
    }
    (OUT / "RESIDUAL_DESK_LABELED_SCORE.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    md = [
        "# Residual desk wave — labeled score",
        "",
        summary["verdict"],
        "",
        f"Folded {n} rows ({nb_s:.0f}s ads, {bc_s:.0f}s broadcast).",
        f"- tally `{json.dumps(tally)}`",
        f"- stack vs cool `{json.dumps(delta)}`",
        "",
        "## Cool",
        f"- coverage {cool_a['non_broadcast_coverage']}",
        f"- desk_s {cool_a['cells']['desk_s']}",
        f"- broadcast_muted_s {cool_a['broadcast_muted_s']}",
        "",
        "## Stack",
        f"- coverage {stack_a['non_broadcast_coverage']}",
        f"- desk_s {stack_a['cells']['desk_s']}",
        f"- broadcast_muted_s {stack_a['broadcast_muted_s']}",
        f"- odell {stack_a['focus']['hush_20260924_220624']['odell']}",
        "",
        "## Residual cores still muted under stack",
        *[f"- {r['session']} {r['core'][0]}–{r['core'][1]} → {r['still_muted_s']}s" for r in residual_receipts],
        "",
        "Not wired to ohush_live.",
    ]
    (OUT / "RESIDUAL_DESK_LABELED_SCORE.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(json.dumps({"n": n, "nb_s": nb_s, "bc_s": bc_s, "delta": delta, "desk_stack": stack_a["cells"]["desk_s"]}, indent=2))
    print("WROTE", OUT / "RESIDUAL_DESK_LABELED_SCORE.md")


if __name__ == "__main__":
    main()
