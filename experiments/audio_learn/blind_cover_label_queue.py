"""Prepend blind TNF 10-15 long-cover listen slices onto BROADCAST_DEEP_LABEL_001.

Does not wipe existing judgments. Open http://127.0.0.1:3010/deep
"""

from __future__ import annotations

import json
from pathlib import Path

OUT = Path(r"c:\Users\faceo\Projects\ohush\docs\ohush\research\BROADCAST_DEEP_LABEL_001")
SESSION = "hush_20261015_210805"
PAD = 1.5

# Remaining research_stack covers (longest first) from blind_prime_1015.
COVERS = (
    {
        "name": "cover_130s",
        "t0": 4667.0,
        "t1": 4797.25,
        "note": (
            "Longest stack cover. Onset: Michaels ge0.25 (16 hops). "
            "Mid/tail: Clarissa/Whit often 'best' but all <0.25 — panel never hot. nn≈commercial."
        ),
    },
    {
        "name": "cover_112s",
        "t0": 8088.25,
        "t1": 8200.75,
        "note": "Stack cover. Voice almost never ≥0.25; Whit dominates tail best-name but cold. nn≈commercial.",
    },
    {
        "name": "cover_93s",
        "t0": 7782.5,
        "t1": 7876.0,
        "note": (
            "Stack cover. Onset often Herbstreit/Palmer ≥0.25 (out of KEEP panel / below margin). "
            "Mid Gonzalez cold. Tail Michaels."
        ),
    },
    {
        "name": "cover_92s",
        "t0": 3167.75,
        "t1": 3259.75,
        "note": "Stack cover. Palmer/Gonzalez/Clarissa names appear cold; panel_hot=0 entire span.",
    },
)


def clip_id(session: str, t0: float, t1: float) -> str:
    return f"{session}_{t0:.1f}_{t1:.1f}".replace(".", "p")


def slices(t0: float, t1: float) -> list[tuple[str, float, float]]:
    """Onset / mid / tail so each listen is ~30s."""
    mid = 0.5 * (t0 + t1)
    return [
        ("onset", t0, min(t0 + 30.0, t1)),
        ("mid", max(t0, mid - 15.0), min(t1, mid + 15.0)),
        ("tail", max(t0, t1 - 30.0), t1),
    ]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    old_queue = []
    qpath = OUT / "queue.jsonl"
    if qpath.is_file():
        old_queue = [json.loads(line) for line in qpath.read_text(encoding="utf-8").splitlines() if line.strip()]

    # Drop prior blind inserts so re-runs are idempotent.
    old_queue = [row for row in old_queue if not str(row.get("clip", "")).startswith(f"{SESSION}_")]

    old_key: dict[str, dict] = {}
    kpath = OUT / "key.jsonl"
    if kpath.is_file():
        for line in kpath.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("clip") and not str(row["clip"]).startswith(f"{SESSION}_"):
                old_key[row["clip"]] = row

    new_items: list[dict] = []
    new_keys: list[dict] = []
    rank = 0
    for cover in COVERS:
        for band, a, b in slices(float(cover["t0"]), float(cover["t1"])):
            if b - a < 5.0:
                continue
            rank += 1
            cid = clip_id(SESSION, a, b)
            play0 = max(0.0, a - PAD)
            play1 = b + PAD
            why = f"blind TNF stack cover · {cover['name']} · {band}"
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
                    "note": cover["note"] + f" Band={band}.",
                    "confidence": "agent_low",
                    "ask": "Broadcast (desk/booth/package) or non_broadcast (ad)? Who is talking?",
                }
            )

    # Re-rank old items after the blind block.
    for i, row in enumerate(old_queue, start=len(new_items) + 1):
        row = dict(row)
        row["rank"] = i
        new_items.append(row)

    with qpath.open("w", encoding="utf-8") as fh:
        for row in new_items:
            fh.write(json.dumps(row) + "\n")

    with kpath.open("w", encoding="utf-8") as fh:
        for row in new_keys:
            fh.write(json.dumps(row) + "\n")
        for clip, row in old_key.items():
            fh.write(json.dumps(row) + "\n")

    if not (OUT / "judgments.json").is_file():
        (OUT / "judgments.json").write_text("{}\n", encoding="utf-8")

    (OUT / "BLIND_TNF_COVERS.md").write_text(
        "\n".join(
            [
                "# Blind TNF long covers — listen first",
                "",
                f"Session `{SESSION}` (Prime TNF Broncos–Seahawks). No gold yet.",
                "",
                "Open **http://127.0.0.1:3010/deep** — priority-0 clips are onset/mid/tail of the four longest research_stack covers.",
                "",
                "## Spans",
                "",
                "| cover | core | ask |",
                "|---|---|---|",
                *[
                    f"| {c['name']} | {c['t0']:.1f}–{c['t1']:.1f} | {c['note']} |"
                    for c in COVERS
                ],
                "",
                "Save bucket=`broadcast` or `non_broadcast` (or unsure). After all 12 slices are labeled, fold into product ontology and re-score.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(f"blind clips {len(new_keys)} · total queue {len(new_items)}")
    for row in new_items[:12]:
        print(f"{row['rank']:2} {row['caption'][:100]}")


if __name__ == "__main__":
    main()
