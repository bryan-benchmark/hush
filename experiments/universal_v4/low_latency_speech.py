"""Low-latency handoff evidence. Not a mute.

The benchmark is the 20-second full-stream scan. This run uses 5-second
chunks, chosen as one quarter of that chunk before these scores are read.
The phrase list is not expanded. Spoken time and chunk-end time stay separate.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import experiments.universal_v3.speech_evidence as speech

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "docs/ohush/research/UNIVERSAL_V4_SPEECH_001"
V3 = REPO / "docs/ohush/research/UNIVERSAL_V3_SPEECH_001"
CHUNK_S = 5.0


def strong_hits(folder: Path) -> list[dict]:
    hits = []
    for path in sorted(folder.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            for hit in row.get("hits") or []:
                if hit.get("kind") == "strong":
                    hits.append({**hit, "session": row["session"]})
    return hits


def pod_flags(hits: list[dict], pods: list[tuple]) -> dict:
    spoken = {}
    causal = {}
    for sid, start, _end, network in pods:
        early = [hit for hit in hits if hit["session"] == sid and start - 30.0 <= hit["spoken_end"] <= start]
        known = [hit for hit in early if hit["available_at"] <= start]
        key = (sid, round(start, 3))
        if early:
            spoken[key] = {"network": network, "start": start, "spoken_end": early[0]["spoken_end"], "available_at": early[0]["available_at"], "phrase": early[0]["phrase"]}
        if known:
            causal[key] = {**spoken.get(key, {}), "spoken_end": known[0]["spoken_end"], "available_at": known[0]["available_at"], "phrase": known[0]["phrase"]}
    return {"spoken": spoken, "causal": causal}


def compare() -> None:
    from experiments.broadcast_intelligence.batch1 import commercials, coverage, load_catalog

    catalog = load_catalog()
    spans = coverage()
    pods = []
    for row in commercials(spans):
        sid = row["session"]
        info = catalog.get(sid, {})
        if (info.get("content_type") or "") != "sports" or sid == speech.REDZONE:
            continue
        pods.append((sid, float(row["start_seconds"]), float(row["end_seconds"]), info.get("network_or_service") or "unknown"))
    benchmark = pod_flags(strong_hits(V3), pods)
    current = pod_flags(strong_hits(OUT), pods)
    became = [key for key in benchmark["spoken"] if key in current["causal"] and key not in benchmark["causal"]]
    summary_path = OUT / "results.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
    summary.update({
        "system": "universal_v4_low_latency_speech",
        "mute_policy": False,
        "chunk_s": CHUNK_S,
        "benchmark_chunk_s": 20.0,
        "football_pods": len(pods),
        "pods_with_strong_phrase_spoken_in_the_30s_before_the_start": len(current["spoken"]),
        "of_those_known_before_the_start": len(current["causal"]),
        "benchmark_spoken_before": len(benchmark["spoken"]),
        "benchmark_known_before": len(benchmark["causal"]),
        "benchmark_spoken_that_this_chunk_makes_causal": len(became),
        "still_not_an_action_policy": True,
    })
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: summary[key] for key in summary if key != "examples_before"}, indent=2))


def main() -> None:
    speech.CHUNK_S = CHUNK_S
    speech.OUT = OUT
    speech.main()
    if os.environ.get("SPEECH_SCORE_ONLY") == "1":
        compare()


if __name__ == "__main__":
    main()
