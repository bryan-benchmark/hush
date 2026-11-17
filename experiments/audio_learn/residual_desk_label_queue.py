"""Queue residual desk FP / unlabeled cool covers on product EVAL for /deep.

Target: stack still mutes named desk (Odell etc.), plus longest cool-cover
hops that are not accepted non_broadcast. Not more longest-mute ad pods.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from experiments.audio_learn.controller import decisions
from experiments.audio_learn.product_scorecard import load_accepted, non_broadcast_intervals
from experiments.audio_learn.research_latch import apply_research_latch
from experiments.audio_learn.splits import EVAL
from experiments.audio_learn.studio_fit import CONTROLLER, DESK_SPANS
from experiments.audio_learn.encoder import DATA_ROOT

OUT = Path(r"c:\Users\faceo\Projects\ohush\docs\ohush\research\BROADCAST_DEEP_LABEL_001")
CAND_OUT = Path(r"C:\OHushData\gpu_lab\audio_learn\product_latch_card")
WAVE = "residual_desk"
PAD = 1.5
CONTEXT_PAD = 4.0
MAX_CLIP_S = 22.0
TOP_DESK = 10
TOP_UNLAB = 8


def _regions(mask: np.ndarray, times: np.ndarray) -> list[tuple[float, float, int]]:
    out = []
    i = 0
    n = len(mask)
    while i < n:
        if mask[i]:
            j = i
            while j < n and mask[j]:
                j += 1
            a = float(times[i])
            b = float(times[j - 1]) + 0.25
            out.append((a, b, j - i))
            i = j
        else:
            i += 1
    return out


def _ol(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def _clip_window(a: float, b: float) -> tuple[float, float]:
    mid = 0.5 * (a + b)
    half = min(MAX_CLIP_S, max(b - a + 2 * CONTEXT_PAD, 10.0)) / 2.0
    return max(0.0, mid - half), mid + half


def _clip_id(session: str, t0: float, t1: float) -> str:
    return f"{session}_{t0:.1f}_{t1:.1f}".replace(".", "p")


def _named_desk_hit(session: str, a: float, b: float) -> tuple[float, str]:
    best = 0.0
    label = ""
    for i, (d0, d1) in enumerate(DESK_SPANS.get(session, []), 1):
        ol = _ol(a, b, d0, d1)
        if ol > best:
            best = ol
            label = f"desk_{i}_{d0:.0f}_{d1:.0f}"
    return best, label


def picks_for_session(session: str, accepted: list[dict]) -> list[dict]:
    pred = np.load(DATA_ROOT / "predictions" / "frozen" / f"{session}.npz")
    times = pred["t"].astype(np.float64)
    frozen_p = pred["p"].astype(np.float64)
    cool_p = apply_research_latch(session, times, frozen_p, with_voice=False)
    stack_p = apply_research_latch(session, times, frozen_p, with_voice=True)
    cool_rows = decisions(times.tolist(), cool_p.tolist(), **CONTROLLER)
    stack_rows = decisions(times.tolist(), stack_p.tolist(), **CONTROLLER)
    cool_cover = np.array([r["action"] == "cover" for r in cool_rows])
    stack_cover = np.array([r["action"] == "cover" for r in stack_rows])

    ads = [(float(i.start), float(i.end)) for i in non_broadcast_intervals(session, accepted)]

    def ad_ol(a: float, b: float) -> float:
        return sum(_ol(a, b, x, y) for x, y in ads)

    # Residual named desk: stack still covering inside DESK_SPANS
    desk_picks: list[dict] = []
    for d0, d1 in DESK_SPANS.get(session, []):
        mask = stack_cover & (times >= d0) & (times < d1)
        for a, b, hops in _regions(mask, times):
            if b - a < 1.5:
                continue
            desk_picks.append(
                {
                    "session": session,
                    "kind": "stack_desk_residual",
                    "core_start": round(a, 3),
                    "core_end": round(b, 3),
                    "note": (
                        f"Named desk still muted under KEEP stack ({b - a:.1f}s, {hops} hops). "
                        f"Desk span {d0:.1f}–{d1:.1f}."
                    ),
                    "score": b - a,
                }
            )
    desk_picks.sort(key=lambda r: -r["score"])

    # Cool covers that are mostly not accepted ads and not already named desk
    unlab_picks: list[dict] = []
    for a, b, hops in _regions(cool_cover, times):
        if b - a < 4.0:
            continue
        aol = ad_ol(a, b)
        desk_ol, desk_name = _named_desk_hit(session, a, b)
        if aol / max(b - a, 1e-6) >= 0.5:
            continue
        if desk_ol >= 2.0:
            continue
        unlab_picks.append(
            {
                "session": session,
                "kind": "cool_cover_unlabeled",
                "core_start": round(a, 3),
                "core_end": round(b, 3),
                "note": (
                    f"Cool cover with little accepted ad ({aol:.1f}s) and little named desk "
                    f"({desk_ol:.1f}s). Label: desk/return vs missed ad? {desk_name}"
                ),
                "score": b - a - aol,
            }
        )
    unlab_picks.sort(key=lambda r: -r["score"])

    out: list[dict] = []
    seen: set[tuple[str, float, float]] = set()

    def add(row: dict) -> None:
        c0, c1 = _clip_window(row["core_start"], row["core_end"])
        key = (row["session"], round(c0, 1), round(c1, 1))
        if key in seen:
            return
        seen.add(key)
        out.append({**row, "t0": round(c0, 3), "t1": round(c1, 3)})

    for row in desk_picks[:TOP_DESK]:
        add(row)
    for row in unlab_picks[:TOP_UNLAB]:
        add(row)
    return out


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    CAND_OUT.mkdir(parents=True, exist_ok=True)
    accepted = load_accepted()
    picks: list[dict] = []
    for session in EVAL:
        picks.extend(picks_for_session(session, accepted))
    # Prefer desk residuals first across sessions
    picks.sort(key=lambda r: (0 if r["kind"] == "stack_desk_residual" else 1, -r["score"]))
    (CAND_OUT / "RESIDUAL_DESK_CANDIDATES.json").write_text(json.dumps(picks, indent=2), encoding="utf-8")

    qpath = OUT / "queue.jsonl"
    old_queue = []
    if qpath.is_file():
        old_queue = [json.loads(line) for line in qpath.read_text(encoding="utf-8").splitlines() if line.strip()]
    old_queue = [r for r in old_queue if WAVE not in str(r.get("why", ""))]

    old_key: dict[str, dict] = {}
    kpath = OUT / "key.jsonl"
    if kpath.is_file():
        for line in kpath.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("clip"):
                old_key[row["clip"]] = row

    new_items: list[dict] = []
    new_keys: list[dict] = []
    for i, pick in enumerate(picks, 1):
        session = pick["session"]
        a, b = float(pick["t0"]), float(pick["t1"])
        cid = _clip_id(session, a, b)
        play0 = max(0.0, a - PAD)
        play1 = b + PAD
        why = f"{WAVE} · {pick['kind']} · #{i}"
        new_items.append(
            {
                "clip": cid,
                "session": session,
                "t0": round(a, 3),
                "t1": round(b, 3),
                "play_start": round(play0, 3),
                "duration": round(play1 - play0, 3),
                "why": why,
                "priority": 0,
                "caption": f"{session} · {a:.1f}–{b:.1f}s · {why}",
                "rank": i,
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
                "note": pick["note"] + f" Core {pick['core_start']}–{pick['core_end']}.",
                "confidence": "agent_low",
                "ask": "Still desk/booth (who?) or missed non_broadcast?",
            }
        )

    for i, row in enumerate(old_queue, start=len(new_items) + 1):
        row = dict(row)
        row["rank"] = i
        if row.get("priority", 99) == 0:
            row["priority"] = 1
        new_items.append(row)

    with qpath.open("w", encoding="utf-8") as fh:
        for row in new_items:
            fh.write(json.dumps(row) + "\n")
    with kpath.open("w", encoding="utf-8") as fh:
        seen = set()
        for row in new_keys:
            fh.write(json.dumps(row) + "\n")
            seen.add(row["clip"])
        for clip, row in old_key.items():
            if clip in seen:
                continue
            fh.write(json.dumps(row) + "\n")

    (OUT / "RESIDUAL_DESK.md").write_text(
        "\n".join(
            [
                "# Residual desk / unlabeled cool-cover wave",
                "",
                "Product EVAL only. Stack still on named desk, or cool covers with little accepted ad.",
                "",
                "Open **http://127.0.0.1:3010/deep**",
                "",
                "| # | session | kind | window |",
                "|---|---|---|---|",
                *[
                    f"| {i} | {p['session']} | {p['kind']} | {p['t0']:.1f}–{p['t1']:.1f} |"
                    for i, p in enumerate(picks, 1)
                ],
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(f"queued {len(new_keys)} residual-desk clips · total queue {len(new_items)}")
    for row in new_items[:15]:
        print(f"{row['rank']:2} {row['caption']}")


if __name__ == "__main__":
    main()
