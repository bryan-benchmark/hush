"""Causal TNF lab replay. Does not rewrite published decisions.

Offline count-10 and count-200 rows are historical. They can read future audio.
The bounded-query scores are a prior causal measurement of four Thursday windows.
The state machine below is driven only by those scores and by a clock, not by gold.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from ohush_live.tnf_lab import TnfLab

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs/ohush/research/TNF_LAB_001"


def _offline() -> dict:
    v1 = json.loads((ROOT / "docs/ohush/research/UNIVERSAL_V1/results.json").read_text(encoding="utf-8"))
    sessions = v1["groups"]["v1"]["football"]["sessions"]
    thursday = next(row for row in sessions if row["session"] == "hush_20261008_205100")
    count10 = None
    with (ROOT / "docs/ohush/research/FINGERPRINT_WARM_CONTEXT_002/per_session.csv").open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if (
                row["arm"] == "cold_query_cold_reference"
                and row["count"] == "count_10"
                and row["session"] == "hush_20261008_205100"
            ):
                count10 = {key: float(row[key]) if key.endswith("_s") or "seconds" in key or key.startswith("ad_") or key.startswith("program") or key.startswith("worst") or key.startswith("unscorable") or key == "false_cover_incidents" else row[key] for key in row}
                count10["false_cover_incidents"] = int(float(row["false_cover_incidents"]))
                break
    return {"count_200": thursday, "count_10": count10}


def _let_go(scores: dict[int, float], gate: float) -> dict:
    covered = [second for second, score in scores.items() if score >= gate]
    pod_start, pod_end = 139.874, 376.900
    return {
        "gate": gate,
        "commercial_seconds_covered": sum(1 for t in covered if pod_start <= t < pod_end),
        "program_seconds_covered": sum(1 for t in covered if t < pod_start or t >= pod_end),
        "clock": "cover only while a causal score is at or above the gate",
    }


def _stay_covered(scores: dict[int, float], end_s: float, gate: float, fail_open_s: float) -> dict:
    """Walk one second at a time. The pod end is applied only after the run."""
    lab = TnfLab()
    lab.configure(mode="auto", return_policy="manual", fail_open_s=fail_open_s, t=0)
    covered = []
    for second in range(0, int(end_s) + 240):
        score = scores.get(second, 0.0)
        hot = score >= gate
        families = {
            "audio": {"departure": 0.2 if hot else 0.0, "strong_departure": score >= 200},
            "speaker": None,
            "semantic": None,
        }
        lab.tick(second, second * 48000, families)
        if lab.covering:
            covered.append(second)
    pod_start, pod_end = 139.874, end_s
    ad = sum(1 for t in covered if pod_start <= t < pod_end)
    program = sum(1 for t in covered if t < pod_start or t >= pod_end)
    return {
        "gate": gate,
        "fail_open_s": fail_open_s,
        "commercial_seconds_covered": ad,
        "program_seconds_covered": program,
        "machine_covers": lab.machine_covers,
        "clock": "causal windows only; a missing score does not uncover",
    }


def main() -> None:
    bounded = json.loads((ROOT / "docs/ohush/research/FINGERPRINT_BOUNDED_QUERY_001/results.json").read_text(encoding="utf-8"))
    causal_scores = {
        int(row["query_t0"]): int(row["score"])
        for row in bounded["controls"]
        if row["session"] == "hush_20261008_205100"
    }
    # Spread each 5-second causal window across its own five seconds. No other seconds fire.
    timeline = {}
    for start, score in causal_scores.items():
        for offset in range(5):
            timeline[start + offset] = score
    stay_10 = _stay_covered(timeline, 376.900, gate=10, fail_open_s=180)
    stay_200 = _stay_covered(timeline, 376.900, gate=200, fail_open_s=180)
    letgo = _let_go(timeline, gate=10)
    offline = _offline()
    result = {
        "product": "TNF_LAB_001",
        "session": "hush_20261008_205100",
        "offline_historical": {
            "note": "90-second block alignment can read future audio. Not a live claim.",
            "count_200": offline["count_200"],
            "count_10": offline["count_10"],
        },
        "prior_causal_windows": {
            "note": "FINGERPRINT_BOUNDED_QUERY_001. No audio after the query. Not re-fingerprinted tonight.",
            "scores": {str(second): score for second, score in sorted(causal_scores.items())},
        },
        "new_causal_state_machine": {
            "note": "Driven by those four windows only. A missing score is not a return. Gold is used after the run to count seconds.",
            "gate_200_fail_open_180": stay_200,
            "gate_10_letgo_5s": letgo,
            "gate_10_stay_fail_open_180": stay_10,
        },
        "fingerprint_full_file": "NOT RUN",
        "retrieve_and_verify": "NOT RUN",
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    count10 = offline["count_10"] or {}
    report = f"""# TNF lab 001

Not a mute. Production Auto was not retuned. Playback defaults stay as they were. This file is the 15 October experiment receipt.

## Offline historical, October 8 Prime

These rows can see future audio. They are not a live rate.

| Rule | Commercial seconds covered | Program seconds covered | Incidents | Worst |
| --- | ---: | ---: | ---: | ---: |
| Count 200 | {offline['count_200'].get('ad_seconds', 0) - offline['count_200'].get('ad_seconds_heard', 0):.1f} | {offline['count_200'].get('program_seconds_covered', 0)} | {offline['count_200'].get('false_cover_incidents', 0)} | {offline['count_200'].get('worst_program_interruption_s', 0)} |
| Count 10 | {count10.get('commercial_seconds_covered', 'missing')} | {count10.get('program_seconds_covered', 'missing')} | {count10.get('false_cover_incidents', 'missing')} | {count10.get('worst_program_interruption_s', 'missing')} |

## Causal, four measured Thursday windows

Bounded query, no audio after the query: {", ".join(str(causal_scores[s]) for s in sorted(causal_scores))}. Full-file causal fingerprint was not run again.

| Candidate | Commercial seconds covered inside 139.9–376.9 | Program seconds covered |
| --- | ---: | ---: |
| Gate 200, fail-open 180 s | {stay_200['commercial_seconds_covered']} | {stay_200['program_seconds_covered']} |
| Gate 10, cover only while the score holds | {letgo['commercial_seconds_covered']} | {letgo['program_seconds_covered']} |
| Gate 10, stay until 180 s fail-open | {stay_10['commercial_seconds_covered']} | {stay_10['program_seconds_covered']} |

The 180-second row is a timer, not a detected return. Retrieve-and-verify was not run.
"""
    (OUT / "REPORT.md").write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
