"""Queue voice-hot / stack-cleared spans on 10-15 for /deep listen-label.

These are where the KEEP panel fired (or cleared cool cover) — desk/return class,
not longest-mute ads.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from experiments.audio_learn.controller import decisions
from experiments.audio_learn.desk_voice_hold import HOLD_S
from experiments.audio_learn.encoder import DATA_ROOT
from experiments.audio_learn.research_latch import _panel_hot_ends, apply_research_latch
from experiments.audio_learn.studio_fit import CONTROLLER

OUT = Path(r"c:\Users\faceo\Projects\ohush\docs\ohush\research\BROADCAST_DEEP_LABEL_001")
CAND_OUT = Path(r"C:\OHushData\gpu_lab\audio_learn\blind_prime_1015")
SESSION = "hush_20261015_210805"
PAD = 1.5
WAVE = "voice_hot"
CONTEXT_PAD = 5.0
MAX_CLIP_S = 25.0
TOP_CLEARED = 10
TOP_HOT = 8


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


def _clip_window(a: float, b: float) -> tuple[float, float]:
    mid = 0.5 * (a + b)
    half = min(MAX_CLIP_S, max(b - a + 2 * CONTEXT_PAD, 12.0)) / 2.0
    return max(0.0, mid - half), mid + half


def _clip_id(t0: float, t1: float) -> str:
    return f"{SESSION}_{t0:.1f}_{t1:.1f}".replace(".", "p")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    CAND_OUT.mkdir(parents=True, exist_ok=True)
    pred = np.load(DATA_ROOT / "predictions" / "frozen" / f"{SESSION}.npz")
    times = pred["t"].astype(np.float64)
    frozen_p = pred["p"].astype(np.float64)
    cool_p = apply_research_latch(SESSION, times, frozen_p, with_voice=False)
    stack_p = apply_research_latch(SESSION, times, frozen_p, with_voice=True)
    cool_rows = decisions(times.tolist(), cool_p.tolist(), **CONTROLLER)
    stack_rows = decisions(times.tolist(), stack_p.tolist(), **CONTROLLER)
    hot = _panel_hot_ends(SESSION)
    right = np.searchsorted(hot, times, side="right")
    left = np.searchsorted(hot, times - HOLD_S, side="left")
    panel_hot = right > left

    cool_cover = np.array([r["action"] == "cover" for r in cool_rows])
    stack_cover = np.array([r["action"] == "cover" for r in stack_rows])
    cleared_mask = cool_cover & ~stack_cover
    hot_fp_mask = cool_cover & panel_hot

    cleared = sorted(_regions(cleared_mask, times), key=lambda r: -(r[1] - r[0]))
    hot_fps = sorted(_regions(hot_fp_mask, times), key=lambda r: -(r[1] - r[0]))

    picks: list[dict] = []
    seen: set[tuple[float, float]] = set()

    def add(kind: str, a: float, b: float, extra: str) -> None:
        c0, c1 = _clip_window(a, b)
        key = (round(c0, 1), round(c1, 1))
        if key in seen:
            return
        if c1 - c0 < 6.0:
            return
        seen.add(key)
        picks.append(
            {
                "kind": kind,
                "core_start": round(a, 3),
                "core_end": round(b, 3),
                "t0": round(c0, 3),
                "t1": round(c1, 3),
                "note": extra,
            }
        )

    for a, b, hops in cleared[:TOP_CLEARED]:
        if b - a < 2.0:
            continue
        add(
            "stack_cleared",
            a,
            b,
            f"cool covered, stack played ({b - a:.1f}s, {hops} hops). Latch cleared — desk/return or burned ad?",
        )
    for a, b, hops in hot_fps[:TOP_HOT]:
        if b - a < 2.0:
            continue
        add(
            "cool_cover_panel_hot",
            a,
            b,
            f"cool cover + KEEP panel hot ({b - a:.1f}s, {hops} hops). Desk FP class the latch targets.",
        )

    (CAND_OUT / "VOICE_HOT_CANDIDATES.json").write_text(json.dumps(picks, indent=2), encoding="utf-8")

    old_queue = []
    qpath = OUT / "queue.jsonl"
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
        a, b = float(pick["t0"]), float(pick["t1"])
        cid = _clip_id(a, b)
        play0 = max(0.0, a - PAD)
        play1 = b + PAD
        why = f"{WAVE} · {pick['kind']} · #{i}"
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
                "ask": "broadcast (desk/booth/return) or non_broadcast (ad)? Who talks?",
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
        seen_clips = set()
        for row in new_keys:
            fh.write(json.dumps(row) + "\n")
            seen_clips.add(row["clip"])
        for clip, row in old_key.items():
            if clip in seen_clips:
                continue
            fh.write(json.dumps(row) + "\n")

    (OUT / "VOICE_HOT.md").write_text(
        "\n".join(
            [
                "# Voice-hot / stack-cleared listen wave",
                "",
                "Not longest-mute. These are where Clarissa∪Whit∪Palmer∪Fitz fired or cleared cool cover.",
                "",
                "Open **http://127.0.0.1:3010/deep**",
                "",
                "| # | kind | window |",
                "|---|---|---|",
                *[
                    f"| {i} | {p['kind']} | {p['t0']:.1f}–{p['t1']:.1f} (core {p['core_start']:.1f}–{p['core_end']:.1f}) |"
                    for i, p in enumerate(picks, 1)
                ],
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(f"queued {len(new_keys)} voice-hot clips · total queue {len(new_items)}")
    for row in new_items[:12]:
        print(f"{row['rank']:2} {row['caption']}")


if __name__ == "__main__":
    main()
