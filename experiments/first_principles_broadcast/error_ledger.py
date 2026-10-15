"""Error ledger for the accuracy north star.

This is not a new detector and not a mute policy. It joins the frozen
continuous-DSP start table to the closed pod lengths and counts seconds.

Two accountings, both audio-only:

- Ceiling: unmute at the gold end. That return is not something the device
  knows. It isolates how many commercial seconds the start trigger alone
  would still leave exposed.
- Causal episode: mute only while an OR episode is on. That is what the
  frozen scan actually marks, with no hold and no learned return.

99.99% of a three-hour broadcast is 1.08 seconds of total error. It is a
north star, not a result.
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

from experiments.broadcast_intelligence.batch1 import commercials, coverage

REPO = Path(__file__).resolve().parents[2]
REDZONE = "hush_20260913_150934"
STARTS = REPO / "docs/ohush/research/CONTINUOUS_DSP_001/starts.csv"
EPISODES = REPO / "docs/ohush/research/CANDIDATE_VERIFICATION_001/episodes.csv"
OUT = REPO / "docs/ohush/research/ACCURACY_NORTH_STAR_001"
PROGRAM_SECONDS = 18.73 * 3600.0


def main() -> None:
    starts = {
        (row["session"], round(float(row["boundary_s"]), 3)): row
        for row in csv.DictReader(STARTS.open(encoding="utf-8"))
    }
    pods = []
    for gold in commercials(coverage()):
        candidates = [
            (abs(float(key[1]) - float(gold["start_seconds"])), key)
            for key in starts
            if key[0] == gold["session"]
        ]
        if not candidates:
            continue
        candidates.sort()
        if candidates[0][0] > 0.05:
            continue
        row = starts[candidates[0][1]]
        if row["content"] != "sports" or gold["session"] == REDZONE:
            continue
        delay = None if row["or_delay_s"] == "" else float(row["or_delay_s"])
        length = float(gold["end_seconds"]) - float(gold["start_seconds"])
        pods.append({
            "session": gold["session"],
            "network": row["network"],
            "length": length,
            "delay": delay,
            "within_3": row["or_within_3"] == "True" and delay is not None,
            "within_30": row["or_within_30"] == "True" and delay is not None,
        })
    ad_seconds = sum(pod["length"] for pod in pods)
    hit3 = [pod for pod in pods if pod["within_3"]]
    miss3 = [pod for pod in pods if not pod["within_3"]]
    hit30 = [pod for pod in pods if pod["within_30"]]
    miss30 = [pod for pod in pods if not pod["within_30"]]
    seconds = defaultdict(float)
    counts = defaultdict(int)
    for row in csv.DictReader(EPISODES.open(encoding="utf-8")):
        if row["content"] != "sports":
            continue
        key = "redzone" if row["session"] == REDZONE else row["class"]
        seconds[key] += float(row["n_seconds"])
        counts[key] += 1
    corpus = PROGRAM_SECONDS + ad_seconds
    payload = {
        "football_pods": len(pods),
        "ad_seconds": round(ad_seconds, 1),
        "program_seconds_published": PROGRAM_SECONDS,
        "corpus_seconds": round(corpus, 1),
        "budget_99_99_seconds": round(0.0001 * corpus, 2),
        "budget_99_99_three_hour_game_seconds": round(0.0001 * 3 * 3600, 2),
        "ceiling_perfect_return": {
            "within_3s": {
                "pods_muted": len(hit3),
                "delay_seconds_on_those_pods": round(sum(min(pod["delay"], pod["length"]) for pod in hit3), 1),
                "missed_pods": len(miss3),
                "missed_pod_seconds": round(sum(pod["length"] for pod in miss3), 1),
                "ad_seconds_heard": round(
                    sum(min(pod["delay"], pod["length"]) for pod in hit3) + sum(pod["length"] for pod in miss3), 1
                ),
            },
            "within_30s": {
                "pods_muted": len(hit30),
                "delay_seconds_on_those_pods": round(sum(min(pod["delay"], pod["length"]) for pod in hit30), 1),
                "missed_pods": len(miss30),
                "missed_pod_seconds": round(sum(pod["length"] for pod in miss30), 1),
                "ad_seconds_heard": round(
                    sum(min(pod["delay"], pod["length"]) for pod in hit30) + sum(pod["length"] for pod in miss30), 1
                ),
            },
            "if_every_pod_were_caught_at_1_12s": round(len(pods) * 1.12, 1),
        },
        "causal_or_episode_seconds": {key: round(value, 1) for key, value in sorted(seconds.items())},
        "causal_or_episode_counts": {key: value for key, value in sorted(counts.items())},
        "note": "Perfect return is an accounting device. The causal episode totals are the frozen scan.",
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
