"""Fold voice_hot judgments and score latch: desk free vs ad burn."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from experiments.audio_learn.blind_cover_fold_score import ACCEPTED, OUT, SESSION, score_one
from experiments.audio_learn.encoder import DATA_ROOT
from experiments.audio_learn.product_scorecard import load_accepted
from experiments.audio_learn.research_latch import apply_research_latch
from experiments.ledger import sha256_file

JUDGMENTS = Path(r"c:\Users\faceo\Projects\ohush\docs\ohush\research\BROADCAST_DEEP_LABEL_001\judgments.json")
QUEUE = Path(r"c:\Users\faceo\Projects\ohush\docs\ohush\research\BROADCAST_DEEP_LABEL_001\queue.jsonl")
SOURCE = "deep_label_voice_hot"
WAVE = "voice_hot"


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


def fold() -> tuple[list[dict], dict]:
    judgments = json.loads(JUDGMENTS.read_text(encoding="utf-8"))
    queue = {
        json.loads(line)["clip"]: json.loads(line)
        for line in QUEUE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    nb: list[tuple[float, float, str, str]] = []
    bc: list[tuple[float, float, str, str]] = []
    tally = {"broadcast_clips": 0, "non_broadcast_clips": 0, "unsure_clips": 0, "splits": []}

    for clip, item in judgments.items():
        q = queue.get(clip)
        if not q or WAVE not in str(q.get("why", "")):
            continue
        a, b = float(q["t0"]), float(q["t1"])
        bucket = item.get("bucket")
        kind = item.get("kind") or "unknown"
        speaker = (item.get("speaker") or "").lower()
        if bucket == "unsure":
            tally["unsure_clips"] += 1
            continue

        # Explicit mixed returns from owner notes (seconds into clip).
        # 6618/6619: ~2–3s Royal Caribbean then Clarissa desk
        if "royal" in speaker and "clarissa" in speaker:
            split = a + 3.0
            nb.append((a, split, "standalone_spot", "royal caribbean open"))
            bc.append((split, b, "postgame_desk" if "postgame" in kind or "postgame" in speaker else "studio_desk", "clarissa after spot"))
            tally["splits"].append(f"{a:.1f}-{b:.1f} royal→desk @+3s")
            tally["broadcast_clips"] += 1
            continue
        # 9507: 9s apple watch then Michaels booth
        if "apple watch" in speaker and "michaels" in speaker:
            split = a + 9.0
            nb.append((a, split, "standalone_spot", "apple watch"))
            bc.append((split, b, "booth", "al michaels"))
            tally["splits"].append(f"{a:.1f}-{b:.1f} apple→booth @+9s")
            tally["broadcast_clips"] += 1
            continue
        # 1924: Michaels outro 3s then DraftKings Clarissa (owner: non_broadcast / in_show_sponsorship)
        if "draft kings" in speaker or "draftkings" in speaker.replace(" ", ""):
            if "outro" in speaker or "first 3" in speaker:
                split = a + 3.0
                bc.append((a, split, "booth", "michaels outro"))
                nb.append((split, b, "in_show_sponsorship", "draftkings clarissa"))
                tally["splits"].append(f"{a:.1f}-{b:.1f} outro→DraftKings @+3s")
            else:
                nb.append((a, b, "in_show_sponsorship", "draftkings"))
            tally["non_broadcast_clips"] += 1
            continue
        # 10977: 10s energizer then rx
        if "energizer" in speaker and "10" in speaker:
            # whole clip ads
            nb.append((a, b, "standalone_spot", "energizer/rx"))
            tally["non_broadcast_clips"] += 1
            continue
        # 5222: 8s PNC then drink
        if "pnc" in speaker:
            nb.append((a, b, "standalone_spot", "pnc/drink"))
            tally["non_broadcast_clips"] += 1
            continue

        if bucket == "non_broadcast":
            nb.append((a, b, kind if kind != "unknown" else "standalone_spot", speaker[:80]))
            tally["non_broadcast_clips"] += 1
        elif bucket == "broadcast":
            bc.append((a, b, kind if kind != "unknown" else "studio_desk", speaker[:80]))
            tally["broadcast_clips"] += 1

    rows: list[dict] = []
    for a, b, kind, note in _merge_triples(nb):
        rows.append(_row(a, b, "non_broadcast", kind, note))
    for a, b, kind, note in _merge_triples(bc):
        rows.append(_row(a, b, "broadcast", kind, note))
    return rows, tally


def _merge_triples(items: list[tuple[float, float, str, str]]) -> list[tuple[float, float, str, str]]:
    if not items:
        return []
    ordered = sorted(items, key=lambda r: (r[0], r[1]))
    out = [list(ordered[0])]
    for a, b, kind, note in ordered[1:]:
        if a <= out[-1][1] + 0.5 and kind == out[-1][2]:
            out[-1][1] = max(out[-1][1], b)
        elif a <= out[-1][1] + 0.5:
            # overlap different kinds — keep longer / don't merge kinds
            out.append([a, b, kind, note])
        else:
            out.append([a, b, kind, note])
    return [(float(a), float(b), str(k), str(n)) for a, b, k, n in out]


def _row(a: float, b: float, bucket: str, kind: str, note: str) -> dict:
    return {
        "session": SESSION,
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
    kept = [r for r in existing if not (r.get("session") == SESSION and r.get("source") == SOURCE)]
    kept.extend(rows)
    ACCEPTED.parent.mkdir(parents=True, exist_ok=True)
    ACCEPTED.write_text("".join(json.dumps(r) + "\n" for r in kept), encoding="utf-8")
    return len(rows)


def latch_audit(accepted: list[dict], times: np.ndarray, cool_p: np.ndarray, stack_p: np.ndarray) -> dict:
    """Seconds the latch freed that are labeled broadcast vs non_broadcast."""
    from experiments.audio_learn.controller import decisions
    from experiments.audio_learn.studio_fit import CONTROLLER

    cool_rows = decisions(times.tolist(), cool_p.tolist(), **CONTROLLER)
    stack_rows = decisions(times.tolist(), stack_p.tolist(), **CONTROLLER)
    hop = 0.25
    freed_broadcast = 0.0
    freed_ad = 0.0
    freed_unlab = 0.0
    for i, (c, s) in enumerate(zip(cool_rows, stack_rows)):
        if c["action"] != "cover" or s["action"] == "cover":
            continue
        t = float(times[i])
        hit = None
        for r in accepted:
            if r.get("session") != SESSION:
                continue
            if float(r["start_s"]) <= t < float(r["end_s"]):
                hit = r
                break
        if hit is None:
            freed_unlab += hop
        elif hit["bucket"] == "broadcast":
            freed_broadcast += hop
        elif hit["bucket"] == "non_broadcast":
            freed_ad += hop
        else:
            freed_unlab += hop
    return {
        "freed_broadcast_s": round(freed_broadcast, 2),
        "freed_ad_s": round(freed_ad, 2),
        "freed_unlabeled_s": round(freed_unlab, 2),
        "latch_precision_on_labeled": (
            None
            if (freed_broadcast + freed_ad) <= 0
            else round(freed_broadcast / (freed_broadcast + freed_ad), 3)
        ),
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rows, tally = fold()
    n = append_source(rows)
    accepted = load_accepted()
    pred = np.load(DATA_ROOT / "predictions" / "frozen" / f"{SESSION}.npz")
    times = pred["t"].astype(np.float64)
    frozen_p = pred["p"].astype(np.float64)
    cool_p = apply_research_latch(SESSION, times, frozen_p, with_voice=False)
    stack_p = apply_research_latch(SESSION, times, frozen_p, with_voice=True)
    results = {
        "cool": score_one(times, cool_p, accepted),
        "stack": score_one(times, stack_p, accepted),
    }
    cool, stack = results["cool"], results["stack"]
    audit = latch_audit(accepted, times, cool_p, stack_p)
    delta = {
        "cov_delta": round(
            (stack["non_broadcast_coverage"] or 0) - (cool["non_broadcast_coverage"] or 0), 4
        ),
        "broadcast_muted_delta": round(stack["broadcast_muted_s"] - cool["broadcast_muted_s"], 1),
        "deskish_delta": round(
            (stack["cells"]["show_return_s"] + stack["cells"]["other_broadcast_s"])
            - (cool["cells"]["show_return_s"] + cool["cells"]["other_broadcast_s"]),
            1,
        ),
    }
    decision = "KEEP"
    reasons = []
    if -delta["cov_delta"] > 0.02:
        decision = "REJECT"
        reasons.append(f"coverage drop {-delta['cov_delta']:.4f} > 0.02")
    if audit["freed_ad_s"] > audit["freed_broadcast_s"] and audit["freed_ad_s"] >= 8:
        reasons.append(
            f"latch freed more labeled ads ({audit['freed_ad_s']}s) than broadcast ({audit['freed_broadcast_s']}s) on this sample"
        )
        if decision == "KEEP":
            decision = "WATCH"
    if decision == "KEEP":
        reasons.append("desk clears present; cov held on labeled ads")

    nb_s = sum(r["dur_s"] for r in rows if r["bucket"] == "non_broadcast")
    bc_s = sum(r["dur_s"] for r in rows if r["bucket"] == "broadcast")
    summary = {
        "session": SESSION,
        "wave": WAVE,
        "n_appended": n,
        "folded_non_broadcast_s": round(nb_s, 2),
        "folded_broadcast_s": round(bc_s, 2),
        "tally": tally,
        "latch_audit": audit,
        "decision_vs_cool": {"decision": decision, "reasons": reasons, "delta": delta},
        "results": results,
        "verdict": (
            "Voice-hot sample is mixed: Clarissa desk/pregame clears are real broadcast; "
            "DraftKings/Chase/PNC/Energizer clears are ad burns (Clarissa also voices DraftKings). "
            f"Latch precision on labeled freed seconds: {audit['latch_precision_on_labeled']}."
        ),
        "frozen_head_sha256": sha256_file(DATA_ROOT / "checkpoints" / "frozen_head.pt"),
    }
    (OUT / "VOICE_HOT_LABELED_SCORE.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    lines = [
        "# Voice-hot wave — labeled latch audit",
        "",
        summary["verdict"],
        "",
        f"## vs cool: **{decision}**",
        *[f"- {r}" for r in reasons],
        f"- delta `{json.dumps(delta)}`",
        f"- latch audit `{json.dumps(audit)}`",
        "",
        f"Folded {n} rows ({nb_s:.0f}s ads, {bc_s:.0f}s broadcast).",
        "",
        "## Cool",
        f"- coverage {cool['non_broadcast_coverage']}",
        f"- non_broadcast {cool['non_broadcast_covered_s']} / {cool['non_broadcast_s']}",
        f"- broadcast_muted_s {cool['broadcast_muted_s']}",
        f"- cells {cool['cells']}",
        "",
        "## Stack",
        f"- coverage {stack['non_broadcast_coverage']}",
        f"- non_broadcast {stack['non_broadcast_covered_s']} / {stack['non_broadcast_s']}",
        f"- broadcast_muted_s {stack['broadcast_muted_s']}",
        f"- cells {stack['cells']}",
        "",
    ]
    (OUT / "VOICE_HOT_LABELED_SCORE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"decision": decision, "delta": delta, "audit": audit, "nb_s": nb_s, "bc_s": bc_s}, indent=2))


if __name__ == "__main__":
    main()
