"""Blinded return-cue queue. Gold stays in the key, not the public file.

The clip is centered on a gold commercial end. The page does not say that.
Judgments append to a separate log and do not edit gold.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from experiments.broadcast_intelligence.batch1 import commercials, coverage, load_catalog

REPO = Path(__file__).resolve().parents[2]
ROOT = REPO / "docs/ohush/research/BOUNDARY_EVIDENCE_001"
RED = "hush_20260913_150934"
PER_NETWORK = 4


def main() -> None:
    catalog = load_catalog()
    pods = []
    for row in commercials(coverage()):
        sid = row["session"]
        info = catalog.get(sid, {})
        if (info.get("content_type") or "") != "sports" or sid == RED:
            continue
        end = float(row["end_seconds"])
        if end < 12:
            continue
        pods.append({
            "session": sid,
            "network": info.get("network_or_service") or "unknown",
            "end": end,
        })
    pods.sort(key=lambda pod: (pod["session"], pod["end"]))
    by_network = defaultdict(list)
    for pod in pods:
        by_network[pod["network"]].append(pod)
    chosen = []
    for network in sorted(by_network):
        group = by_network[network]
        if len(group) <= PER_NETWORK:
            picked = group
        else:
            step = len(group) / PER_NETWORK
            picked = [group[min(len(group) - 1, int(index * step))] for index in range(PER_NETWORK)]
        chosen.extend(picked)
    public, key = [], []
    for index, pod in enumerate(chosen, start=1):
        qid = f"r{index:03d}"
        public.append({
            "id": qid,
            "session": pod["session"],
            "play_start": round(pod["end"] - 10, 3),
            "duration": 20.0,
        })
        key.append({
            "id": qid,
            "session": pod["session"],
            "network": pod["network"],
            "candidate_kind": "gold_end",
            "center_s": round(pod["end"], 3),
        })
    ROOT.mkdir(parents=True, exist_ok=True)
    (ROOT / "returns_public.json").write_text(
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
    (ROOT / "returns_key.json").write_text(json.dumps(key, indent=2) + "\n", encoding="utf-8")
    print(len(public))


if __name__ == "__main__":
    main()
