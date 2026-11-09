"""Walk-forward read of the frozen chronological fingerprint queries.

The matches were computed in KNOWN_AD_FINGERPRINT_001. This script does not
hash audio again and does not choose a new count. A query's library is
earlier recordings only. The current game and every later game are absent.
Count 200 stays the published line. Scores under that line are reported so
the transfer is visible. They are not a new mute.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
QUERIES = REPO / "docs/ohush/research/KNOWN_AD_FINGERPRINT_001/pod_queries.csv"
OUT = REPO / "docs/ohush/research/WALKFORWARD_FINGERPRINT_001"
COUNT = 200

# Football, in capture order. Scripted Hulu sits in the library when it is
# earlier, and it is not a step in this table. RedZone has no commercial pods.
STEPS = (
    ("hush_20260909_213047", "Sept 9 NBC"),
    ("hush_20260913_210542", "Sept 13 NBC"),
    ("hush_20260914_212529", "Sept 14 ESPN"),
    ("hush_20260924_220624", "Sept 24 Prime"),
    ("hush_20261008_205100", "Oct 8 Prime Video"),
    ("hush_20261010_222400", "Oct 10 cable"),
    ("hush_20261011_135700", "Oct 11 afternoon"),
    ("hush_20261011_204300", "Oct 11 night"),
    ("hush_20261012_204200", "Oct 12 MNF"),
)
NAMES = dict(STEPS)


def load() -> list[dict]:
    rows = []
    with QUERIES.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            row["score"] = int(row["score"])
            row["duration_s"] = int(row["duration_s"])
            rows.append(row)
    return rows


def one_per_pod(rows: list[dict]) -> list[dict]:
    chosen: dict[str, dict] = {}
    for row in rows:
        chosen[row["pod_id"]] = row
    return list(chosen.values())


def summarize(vals: list[dict], prior: list[str]) -> dict:
    scores = sorted(row["score"] for row in vals)
    prior_set = set(prior)

    def at(threshold: int) -> int:
        return sum(row["score"] >= threshold for row in vals)

    sports_refs = [
        row for row in vals
        if row["ref_session"] in prior_set and row["score"] > 0
    ]
    return {
        "pods": len(vals),
        "max_score": scores[-1] if scores else 0,
        "median_score": scores[len(scores) // 2] if scores else 0,
        "at_200": at(200),
        "at_50": at(50),
        "at_20": at(20),
        "at_10": at(10),
        "winner_is_earlier_football": sum(
            row["ref_session"] in prior_set and row["score"] >= COUNT for row in vals
        ),
        "top": [
            {
                "score": row["score"],
                "pod_start": float(row["start"]),
                "ref_session": row["ref_session"] or None,
                "ref_name": NAMES.get(row["ref_session"], row["ref_network"] or None),
                "ref_start": float(row["ref_start"]) if row["ref_start"] else None,
            }
            for row in sorted(vals, key=lambda item: -item["score"])[:5]
            if row["score"] > 0
        ],
        "sports_ref_rows": len(sports_refs),
    }


def main() -> None:
    rows = load()
    prior: list[str] = []
    steps = []
    for sid, name in STEPS:
        step = {"session": sid, "name": name, "library_sessions": list(prior)}
        for duration in (5, 10):
            chosen = one_per_pod(
                row for row in rows
                if row["session"] == sid
                and row["library"] == "chronological"
                and row["duration_s"] == duration
            )
            step[f"open_{duration}s"] = summarize(chosen, prior)
            inside = one_per_pod(
                row for row in rows
                if row["session"] == sid
                and row["library"] == "within_session"
                and row["duration_s"] == duration
            )
            step[f"within_{duration}s_at_200"] = sum(row["score"] >= COUNT for row in inside)
            step[f"within_{duration}s_max"] = max((row["score"] for row in inside), default=0)
        steps.append(step)
        prior.append(sid)

    # Pairs: an opening whose best earlier match clears 50, so the repeated
    # element is visible. Count 200 remains the only accept line.
    pairs = []
    seen_prior: list[str] = []
    allowed = set()
    for sid, name in STEPS:
        allowed.add(sid)
        for row in rows:
            if row["session"] != sid or row["library"] != "chronological" or row["duration_s"] != 10:
                continue
            if row["score"] < 50 or row["ref_session"] not in allowed or row["ref_session"] == sid:
                continue
            # ref must be earlier. Session ids sort in time.
            if row["ref_session"] >= sid:
                continue
            pairs.append({
                "score": row["score"],
                "from": NAMES.get(row["ref_session"], row["ref_session"]),
                "to": name,
                "from_session": row["ref_session"],
                "to_session": sid,
                "pod_start": round(float(row["start"]), 3),
                "ref_start": round(float(row["ref_start"]), 3) if row["ref_start"] else None,
                "clears_200": row["score"] >= COUNT,
            })
        seen_prior.append(sid)

    payload = {
        "id": "WALKFORWARD_FINGERPRINT_001",
        "source": "docs/ohush/research/KNOWN_AD_FINGERPRINT_001/pod_queries.csv",
        "rule": {
            "library": "earlier recordings only; this game and later games excluded",
            "query": "opening of a gold commercial, landmarks inside that opening",
            "accept": 200,
            "counts_below_200": "reported, not selected",
            "holdouts": "not opened",
            "live_mute": False,
        },
        "steps": steps,
        "pairs_at_or_above_50": sorted(pairs, key=lambda item: -item["score"]),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "steps": [
            {
                "name": step["name"],
                "library": len(step["library_sessions"]),
                "open10_max": step["open_10s"]["max_score"],
                "open10_at_200": step["open_10s"]["at_200"],
                "open10_at_50": step["open_10s"]["at_50"],
                "open5_at_200": step["open_5s"]["at_200"],
                "within10_max": step["within_10s_max"],
            }
            for step in steps
        ],
        "pairs": len(pairs),
    }, indent=2))


if __name__ == "__main__":
    main()
