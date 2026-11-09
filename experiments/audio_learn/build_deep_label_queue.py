"""Build BROADCAST_DEEP_LABEL_001 queue + agent key drafts."""

from __future__ import annotations

import json
from pathlib import Path

from experiments.audio_learn.studio_fit import DESK_SPANS

OUT = Path(r"c:\Users\faceo\Projects\ohush\docs\ohush\research\BROADCAST_DEEP_LABEL_001")
OUT.mkdir(parents=True, exist_ok=True)
BOARD = Path(r"C:\OHushData\gpu_lab\audio_learn\label_board\champion_decisions\RANKED_FOR_LABELING.json")
board = json.loads(BOARD.read_text(encoding="utf-8"))

DRAFTS = {
    ("hush_20260924_220624", 6180.7): {
        "kind": "sideline_report",
        "phase": "",
        "setting": "sideline_or_remote",
        "speaker": "James Palmer",
        "bucket": "broadcast",
        "note": "Insider James Palmer after break; ASR names Palmer.",
        "confidence": "agent_high",
        "ask": "Confirm phase.",
    },
    ("hush_20260924_220624", 6267.8): {
        "kind": "injury_desk",
        "phase": "",
        "setting": "studio_or_remote",
        "speaker": "",
        "bucket": "broadcast",
        "note": "Elbow injury consult. ECAPA cold — needs speaker ID.",
        "confidence": "agent_medium",
        "ask": "Who is talking? Phase?",
    },
    ("hush_20260924_220624", 6315.2): {
        "kind": "sideline_report",
        "phase": "",
        "setting": "sideline_or_remote",
        "speaker": "",
        "bucket": "broadcast",
        "note": "Will Anderson / team meeting. Top contiguous FP. Needs speaker + phase.",
        "confidence": "agent_medium",
        "ask": "Who is talking? Phase?",
    },
    ("hush_20260924_220624", 7035.0): {
        "kind": "studio_desk",
        "phase": "",
        "setting": "studio_desk",
        "speaker": "Andrew Whitworth / Clarissa Thompson (mixed)",
        "bucket": "broadcast",
        "note": "Odell catch desk; mid-span Fits&Whit podcast promo (in-show).",
        "confidence": "agent_high",
        "ask": "Confirm phase. Note promo if you want it split.",
    },
    ("hush_20260924_220624", 7406.8): {
        "kind": "studio_desk",
        "phase": "",
        "setting": "studio_desk",
        "speaker": "Andrew Whitworth",
        "bucket": "broadcast",
        "note": "Whitworth desk focus.",
        "confidence": "agent_high",
        "ask": "Confirm phase.",
    },
    ("hush_20260924_220624", 5026.8): {
        "kind": "highlights",
        "phase": "",
        "setting": "package",
        "speaker": "",
        "bucket": "broadcast",
        "note": "ASR mentions Falcons at halftime / fourth quarter.",
        "confidence": "agent_high",
        "ask": "Confirm phase (halftime package vs later highlights).",
    },
    ("hush_20260924_220624", 2969.8): {
        "kind": "dry_vo",
        "phase": "n/a",
        "setting": "spot",
        "speaker": "",
        "bucket": "non_broadcast",
        "note": "Chili's dry VO contrast anchor.",
        "confidence": "agent_high",
        "ask": "Confirm dry_vo / spot.",
    },
    ("hush_20261008_205100", 1749.8): {
        "kind": "feature_package",
        "phase": "",
        "setting": "package",
        "speaker": "",
        "bucket": "broadcast",
        "note": "Jerry/Gene Jones feature. Needs narrator + phase.",
        "confidence": "agent_medium",
        "ask": "Who is narrating? Phase?",
    },
    ("hush_20261008_205100", 3384.3): {
        "kind": "dry_vo",
        "phase": "n/a",
        "setting": "spot",
        "speaker": "",
        "bucket": "non_broadcast",
        "note": "Amex Platinum dry VO contrast anchor.",
        "confidence": "agent_high",
        "ask": "Confirm dry_vo / spot.",
    },
    ("hush_20261008_205100", 3974.0): {
        "kind": "unknown",
        "phase": "",
        "setting": "unknown",
        "speaker": "",
        "bucket": "",
        "note": "Unlabeled champion FP. ASR: no speech.",
        "confidence": "agent_low",
        "ask": "Broadcast, commercial, or neither?",
    },
}

PAD = 1.5
MIN_FP_S = 2.0


def draft_for(session: str, t0: float) -> dict | None:
    for (s, st), d in DRAFTS.items():
        if s == session and abs(st - t0) < 1.0:
            return dict(d)
    return None


def covered_by_desk(session: str, t0: float, t1: float) -> bool:
    for a, b in DESK_SPANS.get(session, []):
        if min(b, t1) - max(a, t0) > 0.5:
            return True
    return False


items: list[dict] = []
seen: set[tuple] = set()
keys: dict[str, dict] = {}


def add(session: str, t0: float, t1: float, *, why: str, priority: int) -> None:
    key = (session, round(t0, 1), round(t1, 1))
    if key in seen:
        return
    if t1 - t0 < 0.8:
        return
    seen.add(key)
    play0 = max(0.0, t0 - PAD)
    play1 = t1 + PAD
    clip_id = f"{session}_{t0:.1f}_{t1:.1f}".replace(".", "p")
    row = {
        "clip": clip_id,
        "session": session,
        "t0": round(t0, 3),
        "t1": round(t1, 3),
        "play_start": round(play0, 3),
        "duration": round(play1 - play0, 3),
        "why": why,
        "priority": priority,
        "caption": f"{session} · {t0:.1f}–{t1:.1f}s · {why}",
    }
    items.append(row)
    d = draft_for(session, t0)
    if d:
        keys[clip_id] = d


# Whole Prime desk spans first (human unit of work)
for session, spans in DESK_SPANS.items():
    for i, (a, b) in enumerate(spans):
        pri = 10
        why = f"Prime desk span #{i}"
        d = draft_for(session, a)
        if d and not d.get("speaker"):
            pri = 1
            why += " · needs speaker"
        elif d and not d.get("phase"):
            pri = 2
        add(session, a, b, why=why, priority=pri)

# Champion FPs that are not already inside a desk span (unlabeled / other / sticky)
for row in board:
    session = row["session"]
    t0, t1 = float(row["start_s"]), float(row["end_s"])
    if t1 - t0 < MIN_FP_S:
        continue
    if covered_by_desk(session, t0, t1):
        continue
    why = f"champion FP · {row['cell']} · {row['dur_s']}s"
    pri = 5 if row["cell"] == "unlabeled" else 15
    add(session, t0, t1, why=why, priority=pri)

# Dry VO contrast anchors
add("hush_20260924_220624", 2969.8, 3006.5, why="Chili's dry VO contrast", priority=40)
add("hush_20261008_205100", 3384.3, 3437.1, why="Amex dry VO contrast", priority=40)

items.sort(key=lambda r: (r["priority"], r["session"], r["t0"]))
for i, row in enumerate(items, 1):
    row["rank"] = i

with (OUT / "queue.jsonl").open("w", encoding="utf-8") as fh:
    for row in items:
        fh.write(json.dumps(row) + "\n")

with (OUT / "key.jsonl").open("w", encoding="utf-8") as fh:
    for row in items:
        draft = keys.get(row["clip"]) or {
            "kind": "",
            "phase": "",
            "setting": "",
            "speaker": "",
            "bucket": "broadcast" if "desk" in row["why"] else "",
            "note": "",
            "confidence": "none",
            "ask": "Fill phase + speaker + kind.",
        }
        fh.write(json.dumps({"clip": row["clip"], **draft}) + "\n")

if not (OUT / "judgments.json").exists():
    (OUT / "judgments.json").write_text("{}\n", encoding="utf-8")

(OUT / "REPORT.md").write_text(
    """# BROADCAST_DEEP_LABEL_001

Deep labels so Prime desk vs dry commercial can be stratified.

## Open

http://127.0.0.1:3010/deep

(Requires `./scripts/desk ui` or the monitor app.)

## Fields

| field | why |
|---|---|
| bucket | broadcast / non_broadcast / unsure |
| kind | desk subtype or ad shape |
| phase | pregame / Q / half / post — your ear when ASR is silent |
| setting | studio / sideline / package / spot |
| speaker | who talks — especially enroll-cold desks |
| note | free text |

Agent drafts are in `key.jsonl` and show as hints. Saves go to `judgments.json`.

## Queue shape

1. Desk spans that need speaker/phase
2. Other Prime desk spans
3. Non-desk champion FPs (unlabeled / other)
4. Chili's + Amex dry VO contrast
""",
    encoding="utf-8",
)

print("clips", len(items))
print("drafts", len(keys))
for row in items[:8]:
    print(f"{row['rank']:2} p={row['priority']:2} {row['caption'][:90]}")
