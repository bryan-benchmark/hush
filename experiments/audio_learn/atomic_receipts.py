"""Atomic receipts for the named desk mutes and nearby ads.

Writes one JSON receipt per focus span: every hop's gold, probability,
controller action, and TP/FP/TN/FN. Trains nothing.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from experiments.audio_learn.controller import decisions
from experiments.audio_learn.studio_fit import CONTROLLER
from experiments.measurement.metrics import target_commercials
from experiments.nfl75.inventory import active_intervals, coverage_by_session

FROZEN = Path(r"C:\OHushData\gpu_lab\audio_learn\predictions\frozen")
ECAPA = Path(r"c:\Users\faceo\Projects\ohush\docs\ohush\research\NFL75_PROTECT_001\cache")
REVIEWED = Path(r"c:\Users\faceo\Projects\ohush\docs\ohush\research\OHUSH_STUDIO_HEAD_001\reviewed_boundaries.json")
OUT = Path(r"C:\OHushData\gpu_lab\audio_learn\atomic_receipts")
SEMANTIC = Path(r"C:\OHushData\gpu_lab\audio_learn\semantic_probe\action_qwen2.5_14b.jsonl")
NAMES = ["Al Michaels", "Kirk Herbstreit", "Clarissa Thompson", "Andrew Whitworth", "Tony Gonzalez"]

FOCUS = [
    ("hush_20260924_220624", "odell", 7035.0, 7095.2, "program_studio"),
    ("hush_20260924_220624", "whitworth", 7406.8, 7436.2, "program_studio"),
    ("hush_20260924_220624", "palmer", 6180.7, 6207.8, "program_studio"),
    ("hush_20260924_220624", "injury", 6267.8, 6287.2, "program_studio"),
    ("hush_20260924_220624", "chilis_reviewed_spot", 2969.8, 3006.5, "reviewed_commercial"),
    ("hush_20260924_220624", "live_ok", 1208.0, 1216.0, "program_live"),
    ("hush_20261008_205100", "amex_reviewed_spot", 3384.3, 3437.1, "reviewed_commercial"),
    ("hush_20261008_205100", "welcome_back", 3437.1, 3443.0, "program_transition"),
]


def _gold_at(moment: float, ads: list[tuple[float, float]], reviewed: list[tuple[float, float]]) -> str:
    if any(a0 <= moment < a1 for a0, a1 in ads):
        return "commercial"
    if any(a0 <= moment < a1 for a0, a1 in reviewed):
        return "reviewed_commercial"
    return "program"


def _cell(gold: str, action: str) -> str:
    want_cover = gold in {"commercial", "reviewed_commercial"}
    did_cover = action == "cover"
    if want_cover and did_cover:
        return "TP"
    if want_cover and not did_cover:
        return "FN"
    if not want_cover and did_cover:
        return "FP"
    return "TN"


def _voice(session: str, t0: float, t1: float) -> list[dict]:
    path = ECAPA / f"{session}.npz"
    if not path.is_file():
        return []
    data = np.load(path)
    start, end, people = data["start"], data["end"], data["people"]
    rows = []
    for i in range(len(end)):
        if end[i] < t0 - 2 or start[i] > t1 + 2:
            continue
        with np.errstate(invalid="ignore"):
            scores = {name: float(people[i, slot]) for slot, name in enumerate(NAMES) if np.isfinite(people[i, slot])}
        if not scores:
            continue
        best = max(scores, key=scores.get)
        rows.append(
            {
                "window_start": round(float(start[i]), 3),
                "window_end": round(float(end[i]), 3),
                "best": best,
                "cosine": round(scores[best], 3),
                "ge_0.25": scores[best] >= 0.25,
                "scores": {k: round(v, 3) for k, v in scores.items()},
            }
        )
    return rows


def _semantic(session: str, t0: float, t1: float) -> list[dict]:
    probe_path = Path(r"C:\OHushData\gpu_lab\audio_learn\semantic_probe\rows.jsonl")
    if not SEMANTIC.is_file() or not probe_path.is_file():
        return []
    actions = {
        json.loads(line)["id"]: json.loads(line)
        for line in SEMANTIC.read_text(encoding="utf-8").splitlines()
        if line
    }
    kept = []
    for line in probe_path.read_text(encoding="utf-8").splitlines():
        if not line:
            continue
        src = json.loads(line)
        if src["session"] != session:
            continue
        if not (t0 - 1 <= src["t"] <= t1 + 1):
            continue
        row = actions.get(src["id"], {})
        kept.append(
            {
                "id": src["id"],
                "t": src["t"],
                "horizon_s": src["horizon_s"],
                "text": src["text"],
                "action_14b": row.get("action"),
                "old_label_3b": src.get("label"),
                "frozen_p": src.get("frozen_p"),
            }
        )
    return kept


def _receipt(session: str, name: str, t0: float, t1: float, kind: str) -> dict:
    pred = np.load(FROZEN / f"{session}.npz")
    coverage = coverage_by_session()[session]
    ads = target_commercials(active_intervals(session))
    reviewed_doc = json.loads(REVIEWED.read_text(encoding="utf-8"))["commercials"]
    reviewed = [(float(r["start_s"]), float(r["end_s"])) for r in reviewed_doc if r["session"] == session]
    rows = decisions(pred["t"].tolist(), pred["p"].tolist(), **CONTROLLER)
    by_t = {round(float(r["available_at"]), 6): r for r in rows}
    # pad 4s before for streak context
    left, right = t0 - 4.0, t1 + 2.0
    hops = []
    counts = {"TP": 0, "FP": 0, "TN": 0, "FN": 0}
    for t, p, lab in zip(pred["t"], pred["p"], pred["label"]):
        t = float(t)
        if t < left or t >= right:
            continue
        decision = by_t.get(round(t, 6))
        action = decision["action"] if decision else "missing"
        gold = _gold_at(t, ads, reviewed)
        cell = _cell(gold, action) if action in {"cover", "play"} else "missing"
        if cell in counts:
            # only count inside the span itself for the confusion matrix of the event
            if t0 <= t < t1:
                counts[cell] += 1
        hops.append(
            {
                "t": round(t, 3),
                "p": round(float(p), 4),
                "label_in_npz": int(lab),
                "gold": gold,
                "action": action,
                "cell": cell if t0 <= t < t1 else "context",
                "ge_on": float(p) >= CONTROLLER["on"],
                "le_off": float(p) <= CONTROLLER["off"],
            }
        )
    # find cover open inside or touching
    cover_open = None
    for hop in hops:
        if hop["t"] < t0:
            continue
        if hop["action"] == "cover":
            cover_open = hop["t"]
            break
    inside = [h for h in hops if t0 <= h["t"] < t1]
    return {
        "session": session,
        "name": name,
        "kind": kind,
        "span": [t0, t1],
        "controller": CONTROLLER,
        "confusion_hops_inside_span": counts,
        "n_hops_inside": len(inside),
        "p_median_inside": None if not inside else round(float(np.median([h["p"] for h in inside])), 4),
        "p_min_inside": None if not inside else round(float(min(h["p"] for h in inside)), 4),
        "p_max_inside": None if not inside else round(float(max(h["p"] for h in inside)), 4),
        "share_p_ge_0.90": None if not inside else round(sum(1 for h in inside if h["ge_on"]) / len(inside), 3),
        "first_cover_at_or_after_start": cover_open,
        "what_model_thinks": (
            "commercial"
            if inside and float(np.median([h["p"] for h in inside])) >= 0.90
            else "lean_commercial"
            if inside and float(np.median([h["p"] for h in inside])) >= 0.50
            else "program"
        ),
        "what_gold_is": "commercial" if kind.startswith("reviewed") else "program",
        "voice_windows": _voice(session, t0, t1),
        "semantic_probes": _semantic(session, t0, t1),
        "hops": hops,
        "logging_gap": [
            "no per-hop reason string beyond p and action",
            "no speaker identity in the acoustic decision record",
            "no transcript attached to the hop",
            "label field in npz is training gold class, not the controller belief",
        ],
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    index = []
    for session, name, t0, t1, kind in FOCUS:
        receipt = _receipt(session, name, t0, t1, kind)
        path = OUT / f"{session}_{name}.json"
        path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
        index.append(
            {
                "file": path.name,
                "name": name,
                "kind": kind,
                "span": [t0, t1],
                "confusion": receipt["confusion_hops_inside_span"],
                "p_median": receipt["p_median_inside"],
                "what_model_thinks": receipt["what_model_thinks"],
                "what_gold_is": receipt["what_gold_is"],
                "first_cover": receipt["first_cover_at_or_after_start"],
                "voice_hits_ge_0.25": sum(1 for v in receipt["voice_windows"] if v["ge_0.25"]),
                "semantic": [
                    {"id": s["id"], "action_14b": s["action_14b"], "text": s["text"][:80]}
                    for s in receipt["semantic_probes"]
                ],
            }
        )
        print(name, receipt["confusion_hops_inside_span"], "p_med", receipt["p_median_inside"], flush=True)
    (OUT / "index.json").write_text(json.dumps(index, indent=2), encoding="utf-8")
    print("wrote", OUT / "index.json", flush=True)


if __name__ == "__main__":
    main()
