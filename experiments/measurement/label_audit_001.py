"""Build a blinded listen for whether gold matches the listener's rule.

The queue does not carry model scores. The key does. Gold is not edited.
The head is the one already fit. Nothing here mutes.
"""

from __future__ import annotations

import json
import random
import sys
from collections import Counter
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from experiments.ledger import TRUTH_PATH, read_jsonl, resolve_ledger  # noqa: E402
from experiments.measurement.supervised_clear_ceiling_001 import _lookback_commercial  # noqa: E402
from experiments.measurement.supervised_heldout_001 import FIT, WINDOW_S, _fit, _scores  # noqa: E402
from tools.gpu_lab.ladder import pairs  # noqa: E402
from tools.gpu_lab.learning_net.data import bridge_masks  # noqa: E402

OUT = REPO / "docs" / "ohush" / "research" / "LABEL_AUDIT_001"
SEED = 23
NAMED = (
    {
        "session": "hush_20260913_210542",
        "t0": 70.0,
        "t1": 105.0,
        "why": "FanDuel line already heard outside a gold commercial, 75–100",
    },
    {
        "session": "hush_20260909_213047",
        "t0": 220.0,
        "t1": 260.0,
        "why": "Prior listen: Tirico sign-off then an AWS spot, not in gold, around 240",
    },
    {
        "session": "hush_20260913_210542",
        "t0": 149.0,
        "t1": 159.0,
        "why": "Mixed boundary that set the 12.155 line, decision at 154",
    },
    {
        "session": "hush_20260913_210542",
        "t0": 11407.0,
        "t1": 11417.0,
        "why": "Highest clear show second, 11412, Music",
    },
)


def active_counts() -> dict:
    raw = read_jsonl(TRUTH_PATH)
    superseded = {row["supersedes"] for row in raw if row.get("supersedes")}
    counts: Counter[str] = Counter()
    for row in resolve_ledger(raw, "gold_id"):
        if row.get("retracted") or row.get("event") == "retracted":
            continue
        if row.get("gold_id") in superseded:
            continue
        if "start_seconds" not in row:
            continue
        counts[f"{row.get('event_class')}|{row.get('desired_action')}|{row.get('confidence')}"] += 1
    return dict(counts)


def _middle(moment: float, commercials: list[tuple[float, float]], pad: float = 15.0) -> bool:
    return any(start + pad <= moment <= end - pad for start, end in commercials)


def main() -> None:
    masks = bridge_masks()
    head, receipt = _fit(FIT)
    if abs(receipt["train_accuracy"] - 0.9273) > 1e-4:
        raise SystemExit(f"training agreement moved: {receipt['train_accuracy']}")
    program_rows = []
    commercial_rows = []
    for session in FIT:
        times, scores, labels = _scores(head, session)
        commercials = pairs(masks[session], "verified_commercial")
        for moment, score, label in zip(times, scores, labels):
            moment = float(moment)
            if int(label) == 0 and _lookback_commercial(moment, commercials) <= 1e-9:
                program_rows.append((float(score), session, moment))
            elif int(label) == 1 and _middle(moment, commercials):
                commercial_rows.append((float(score), session, moment))
    program_rows.sort(reverse=True)
    commercial_rows.sort()
    chosen = list(NAMED)
    for _score, session, moment in program_rows:
        if len([row for row in chosen if row["why"].startswith("clear show")]) >= 25:
            break
        if any(row["session"] == session and abs(((row["t0"] + row["t1"]) / 2) - moment) < 8 for row in chosen):
            continue
        chosen.append(
            {
                "session": session,
                "t0": round(moment - 4.0, 3),
                "t1": round(moment + 4.0, 3),
                "why": "clear show second among the highest scores on the two NBC games",
            }
        )
    for _score, session, moment in commercial_rows:
        if len([row for row in chosen if row["why"].startswith("middle")]) >= 25:
            break
        if any(row["session"] == session and abs(((row["t0"] + row["t1"]) / 2) - moment) < 8 for row in chosen):
            continue
        chosen.append(
            {
                "session": session,
                "t0": round(moment - 4.0, 3),
                "t1": round(moment + 4.0, 3),
                "why": "middle of a gold commercial among the lowest scores on the two NBC games",
            }
        )
    for session in FIT:
        commercials = pairs(masks[session], "verified_commercial")
        step = max(1, len(commercials) // 8)
        for index, (start, end) in enumerate(commercials):
            if index % step:
                continue
            chosen.append(
                {
                    "session": session,
                    "t0": round(start - 15.0, 3),
                    "t1": round(start + 15.0, 3),
                    "why": "fifteen seconds on each side of a labeled commercial start",
                }
            )
            chosen.append(
                {
                    "session": session,
                    "t0": round(end - 15.0, 3),
                    "t1": round(end + 15.0, 3),
                    "why": "fifteen seconds on each side of a labeled commercial end",
                }
            )
            if len([row for row in chosen if "labeled commercial start" in row["why"]]) >= 15:
                break
    controls = 0
    for session, mask in masks.items():
        if session not in (*FIT, "hush_20260913_150934"):
            continue
        commercials = pairs(mask, "verified_commercial")
        coverage = pairs(mask, "coverage")[0]
        moment = coverage[0] + 90.0
        while moment < coverage[1] and controls < 20:
            if not any(start - 30 <= moment <= end + 30 for start, end in commercials):
                chosen.append(
                    {
                        "session": session,
                        "t0": round(moment - 4.0, 3),
                        "t1": round(moment + 4.0, 3),
                        "why": "ordinary show or RedZone, away from a labeled break",
                    }
                )
                controls += 1
            moment += 600.0
    order = list(range(len(chosen)))
    random.Random(SEED).shuffle(order)
    queue = []
    key = []
    for number, index in enumerate(order, start=1):
        row = chosen[index]
        clip = f"q{number:03d}"
        queue.append(
            {
                "clip": clip,
                "session": row["session"],
                "t0": row["t0"],
                "t1": row["t1"],
                "broadcast_context": "",
                "content_type": "",
                "desired_action": "",
                "original_label": "",
                "note": "",
            }
        )
        key.append({"clip": clip, **row})
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "queue.jsonl").write_text("".join(json.dumps(row) + "\n" for row in queue), encoding="utf-8")
    (OUT / "key.jsonl").write_text("".join(json.dumps(row) + "\n" for row in key), encoding="utf-8")
    summary = {
        "clips": len(queue),
        "train_accuracy": receipt["train_accuracy"],
        "train_rows": receipt["rows"],
        "annotation_counts": active_counts(),
        "always_program_accuracy": round(receipt["program_rows"] / receipt["rows"], 4),
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
