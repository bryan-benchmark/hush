"""Blinded precision queue. Gold and model scores stay in queue_key.json.

The public file is what the review page is allowed to fetch. Do not add
scores or labels to it.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from experiments.broadcast_intelligence.batch1 import commercials, coverage, load_catalog

REPO = Path(__file__).resolve().parents[2]
RED = "hush_20260913_150934"
ROOT = REPO / "docs/ohush/swarm/adjudication"
STARTS = REPO / "docs/ohush/research/CONTINUOUS_DSP_001/starts.csv"


def main() -> None:
    starts = list(csv.DictReader(STARTS.open(encoding="utf-8")))
    catalog = load_catalog()
    spans = coverage()
    span = {}
    for row in spans:
        span.setdefault(row["session"], (float(row["from_seconds"]), float(row["to_seconds"])))

    def match_start(session: str, t: float):
        best = None
        for row in starts:
            if row["session"] != session:
                continue
            delta = abs(float(row["boundary_s"]) - t)
            if best is None or delta < best[0]:
                best = (delta, row)
        if best is None or best[0] > 0.05:
            return None
        return best[1]

    pods = []
    for gold in commercials(spans):
        sid = gold["session"]
        info = catalog.get(sid, {})
        if (info.get("content_type") or "") != "sports" or sid == RED:
            continue
        hit = match_start(sid, float(gold["start_seconds"]))
        pods.append({
            "session": sid,
            "network": info.get("network_or_service") or "unknown",
            "start": float(gold["start_seconds"]),
            "end": float(gold["end_seconds"]),
            "within3": bool(hit and hit["or_within_3"] == "True"),
        })

    def take(pred, n):
        chosen = []
        for pod in pods:
            if len(chosen) >= n:
                break
            if pred(pod) and pod["start"] >= 12:
                chosen.append(pod)
        return chosen

    rows = []

    def add(kind, pod, reason, center):
        if center < 12:
            return
        rows.append((kind, pod, reason, center))

    specs = [
        ("dsp_miss_nbc", lambda p: p["network"] == "NBC" and not p["within3"], 4),
        ("dsp_miss_prime", lambda p: p["network"] == "Prime" and not p["within3"], 2),
        ("dsp_miss_prime_video", lambda p: p["network"] == "Prime Video" and not p["within3"], 2),
        ("dsp_miss_espn", lambda p: p["network"] == "ESPN" and not p["within3"], 2),
        ("dsp_miss_cable", lambda p: "Cable" in p["network"] and not p["within3"], 3),
        ("dsp_hit_nbc", lambda p: p["network"] == "NBC" and p["within3"], 3),
        ("dsp_hit_prime", lambda p: p["network"] == "Prime" and p["within3"], 2),
        ("dsp_hit_prime_video", lambda p: p["network"] == "Prime Video" and p["within3"], 2),
        ("dsp_hit_espn", lambda p: p["network"] == "ESPN" and p["within3"], 2),
        ("dsp_hit_cable", lambda p: "Cable" in p["network"] and p["within3"], 3),
    ]
    for reason, pred, n in specs:
        for pod in take(pred, n):
            add("start", pod, reason, pod["start"])

    end_left = {"NBC": 2, "Prime": 1, "Prime Video": 1, "ESPN": 2, "Cable / antenna": 2}
    for pod in pods:
        if end_left.get(pod["network"], 0) <= 0:
            continue
        end_left[pod["network"]] -= 1
        add("end", pod, "gold_end", pod["end"])

    for sid, (cov0, cov1) in span.items():
        info = catalog.get(sid, {})
        if (info.get("content_type") or "") != "sports" or sid == RED:
            continue
        here = [pod for pod in pods if pod["session"] == sid]
        t = cov0 + 200.0
        while t + 20 < cov1:
            if not any(pod["start"] - 60 <= t <= pod["end"] + 60 for pod in here):
                add("program", {"session": sid, "network": info.get("network_or_service"), "start": t, "end": t}, "program_far", t)
                break
            t += 40.0

    for t in (500, 1600, 2800, 4200, 5600):
        add("redzone", {"session": RED, "network": "FOX", "start": t, "end": t}, "redzone", float(t))

    interiors = 0
    for pod in pods:
        if pod["end"] - pod["start"] < 90:
            continue
        add("interior", pod, "pod_interior", pod["start"] + 40)
        interiors += 1
        if interiors >= 6:
            break

    public, key = [], []
    for index, (kind, pod, reason, center) in enumerate(rows, start=1):
        qid = f"q{index:03d}"
        public.append({"id": qid, "session": pod["session"], "play_start": round(center - 10, 3), "duration": 20.0})
        key.append({
            "id": qid,
            "session": pod["session"],
            "network": pod["network"],
            "reason": reason,
            "candidate_kind": kind,
            "center_s": round(center, 3),
        })
    ROOT.mkdir(parents=True, exist_ok=True)
    (ROOT / "queue_public.json").write_text(
        json.dumps(
            {
                "instructions": "The moment under review is 10.000 seconds into the clip. This file contains no gold label and no model score.",
                "items": public,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (ROOT / "queue_key.json").write_text(json.dumps(key, indent=2) + "\n", encoding="utf-8")
    print(len(public))


if __name__ == "__main__":
    main()
