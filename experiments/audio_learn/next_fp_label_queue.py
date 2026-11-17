"""Queue next-worst stack covers on hush_20261015 outside labeled ad pods.

Prepends onset/mid/tail slices to BROADCAST_DEEP_LABEL_001 for /deep.
Keeps prior judgments. Idempotent for this wave's clip ids.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from experiments.audio_learn.controller import decisions
from experiments.audio_learn.encoder import DATA_ROOT
from experiments.audio_learn.research_latch import apply_research_latch
from experiments.audio_learn.studio_fit import CONTROLLER
from experiments.nfl75.score import playback_from_decisions

OUT = Path(r"c:\Users\faceo\Projects\ohush\docs\ohush\research\BROADCAST_DEEP_LABEL_001")
SESSION = "hush_20261015_210805"
COVERAGE = (0.0, 12753.749)
PAD = 1.5
TOP_N = 6
WAVE = "next_fp"
# Already listen-labeled ad pods (full cover cores).
KNOWN = (
    (4667.0, 4797.25),
    (8088.25, 8200.75),
    (7782.5, 7876.0),
    (3167.75, 3259.75),
)


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def _merge_covers(times: np.ndarray, probs: np.ndarray) -> list[tuple[float, float]]:
    rows = decisions(times.tolist(), probs.tolist(), **CONTROLLER)
    spans = playback_from_decisions(COVERAGE, rows)
    merged: list[list[float]] = []
    for span in spans:
        if span.state != "covered":
            continue
        if merged and abs(span.start - merged[-1][1]) <= 1e-6:
            merged[-1][1] = float(span.end)
        else:
            merged.append([float(span.start), float(span.end)])
    return [(a, b) for a, b in merged if b > a]


def _candidates() -> list[dict]:
    pred = np.load(DATA_ROOT / "predictions" / "frozen" / f"{SESSION}.npz")
    times = pred["t"].astype(np.float64)
    frozen_p = pred["p"].astype(np.float64)
    stack_p = apply_research_latch(SESSION, times, frozen_p, with_voice=True)
    out = []
    for a, b in _merge_covers(times, stack_p):
        dur = b - a
        if dur < 8.0:
            continue
        ol = sum(_overlap(a, b, x, y) for x, y in KNOWN)
        if ol / dur > 0.5:
            continue
        out.append({"start_s": a, "end_s": b, "length_s": dur, "known_ol": ol})
    out.sort(key=lambda r: -r["length_s"])
    return out[:TOP_N]


def _slices(t0: float, t1: float) -> list[tuple[str, float, float]]:
    mid = 0.5 * (t0 + t1)
    return [
        ("onset", t0, min(t0 + 30.0, t1)),
        ("mid", max(t0, mid - 15.0), min(t1, mid + 15.0)),
        ("tail", max(t0, t1 - 30.0), t1),
    ]


def _clip_id(t0: float, t1: float) -> str:
    return f"{SESSION}_{t0:.1f}_{t1:.1f}".replace(".", "p")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    cands = _candidates()
    (OUT / "NEXT_FP_CANDIDATES.json").write_text(json.dumps(cands, indent=2), encoding="utf-8")

    old_queue = []
    qpath = OUT / "queue.jsonl"
    if qpath.is_file():
        old_queue = [json.loads(line) for line in qpath.read_text(encoding="utf-8").splitlines() if line.strip()]

    # Drop previous next_fp wave only (keep labeled blind covers + older desk queue).
    old_queue = [r for r in old_queue if WAVE not in str(r.get("why", ""))]

    old_key: dict[str, dict] = {}
    kpath = OUT / "key.jsonl"
    if kpath.is_file():
        for line in kpath.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            clip = row.get("clip")
            if clip:
                old_key[clip] = row

    new_items: list[dict] = []
    new_keys: list[dict] = []
    rank = 0
    for i, cand in enumerate(cands, 1):
        a0, b0 = float(cand["start_s"]), float(cand["end_s"])
        for band, a, b in _slices(a0, b0):
            if b - a < 5.0:
                continue
            rank += 1
            cid = _clip_id(a, b)
            play0 = max(0.0, a - PAD)
            play1 = b + PAD
            why = f"{WAVE} · stack cover #{i} · {cand['length_s']:.0f}s · {band}"
            new_items.append(
                {
                    "clip": cid,
                    "session": SESSION,
                    "t0": round(a, 3),
                    "t1": round(b, 3),
                    "play_start": round(play0, 3),
                    "duration": round(play1 - play0, 3),
                    "why": why,
                    "priority": 0,
                    "caption": f"{SESSION} · {a:.1f}–{b:.1f}s · {why}",
                    "rank": rank,
                }
            )
            new_keys.append(
                {
                    "clip": cid,
                    "kind": "",
                    "phase": "",
                    "setting": "",
                    "speaker": "",
                    "bucket": "",
                    "note": (
                        f"Outside the four labeled ad pods. Stack still covers {cand['length_s']:.1f}s "
                        f"({a0:.1f}–{b0:.1f}). Band={band}. Ad vs desk/booth?"
                    ),
                    "confidence": "agent_low",
                    "ask": "broadcast or non_broadcast? Who talks?",
                }
            )

    for i, row in enumerate(old_queue, start=len(new_items) + 1):
        row = dict(row)
        row["rank"] = i
        # demote prior waves
        if row.get("priority", 99) == 0 and "blind TNF" in str(row.get("why", "")):
            row["priority"] = 1
        new_items.append(row)

    with qpath.open("w", encoding="utf-8") as fh:
        for row in new_items:
            fh.write(json.dumps(row) + "\n")

    # Prefer new keys; keep old for other clips
    with kpath.open("w", encoding="utf-8") as fh:
        seen = set()
        for row in new_keys:
            fh.write(json.dumps(row) + "\n")
            seen.add(row["clip"])
        for clip, row in old_key.items():
            if clip in seen:
                continue
            fh.write(json.dumps(row) + "\n")

    (OUT / "NEXT_FP.md").write_text(
        "\n".join(
            [
                "# Next FP wave — unlabeled stack covers on 10-15",
                "",
                "Four labeled pods excluded. Open **http://127.0.0.1:3010/deep** (priority 0).",
                "",
                "| # | span | length |",
                "|---|---|---|",
                *[
                    f"| {i} | {c['start_s']:.1f}–{c['end_s']:.1f} | {c['length_s']:.1f}s |"
                    for i, c in enumerate(cands, 1)
                ],
                "",
                f"{len(new_keys)} slices (onset/mid/tail). Save broadcast vs non_broadcast.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(f"queued {len(new_keys)} slices from {len(cands)} covers · total queue {len(new_items)}")
    for row in new_items[:12]:
        print(f"{row['rank']:2} {row['caption'][:110]}")


if __name__ == "__main__":
    main()
