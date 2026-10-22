"""Later airings of a commercial the fingerprint already cleared at 200.

A reference counts as known only after a query scores at least 200 against
it. Later queries that name that same reference are not a lower line for
everything else. This does not mute, and it does not pick a new count.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "docs/ohush/research/V1_KNOWN_001"
COMMERCIAL_S = 17648.4


def load() -> tuple[dict, dict]:
    pods: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for line in (REPO / "docs/ohush/research/START_END_001/receipts.jsonl").read_text().splitlines():
        if line.strip():
            row = json.loads(line)
            pods[row["session"]].append((float(row["start"]), float(row["end"])))
    decisions: dict[str, list[dict]] = defaultdict(list)
    for line in (REPO / "docs/ohush/research/UNIVERSAL_V1/decisions.jsonl").read_text().splitlines():
        if line.strip():
            row = json.loads(line)
            if row.get("content") != "scripted" and row["session"] in pods:
                decisions[row["session"]].append(row)
    for rows in decisions.values():
        rows.sort(key=lambda row: float(row["available_at"]))
    return pods, decisions


def inside(pods: list[tuple[float, float]], t: float) -> bool:
    return any(start <= t < end for start, end in pods)


def ref_key(row: dict) -> tuple[str, int] | None:
    if not row.get("ref_session") or row.get("ref_start") is None or row.get("same_session"):
        return None
    return (row["ref_session"], int(round(float(row["ref_start"]))))


def main() -> None:
    pods, decisions = load()
    known: dict[tuple[str, int], dict] = {}
    for session in sorted(decisions):
        for row in decisions[session]:
            if row["score"] < 200:
                continue
            key = ref_key(row)
            if key is None or not inside(pods[session], float(row["available_at"])):
                continue
            known.setdefault(
                key,
                {
                    "ref_session": key[0],
                    "ref_start": key[1],
                    "first_session": session,
                    "first_at": float(row["available_at"]),
                    "first_score": row["score"],
                },
            )

    later = []
    for session in sorted(decisions):
        rows = decisions[session]
        for index, row in enumerate(rows):
            key = ref_key(row)
            if key not in known:
                continue
            if (session, float(row["available_at"])) <= (known[key]["first_session"], known[key]["first_at"]):
                continue
            start = float(row["available_at"])
            end = float(rows[index + 1]["available_at"]) if index + 1 < len(rows) else start
            in_ad = inside(pods[session], start)
            later.append(
                {
                    "session": session,
                    "at": start,
                    "until": end,
                    "score": row["score"],
                    "ref_session": key[0],
                    "ref_start": key[1],
                    "in_ad": in_ad,
                }
            )

    def span_seconds(rows: list[dict], pred) -> float:
        return round(sum(row["until"] - row["at"] for row in rows if pred(row)), 3)

    program_rows = [row for row in later if not row["in_ad"]]
    ad_rows = [row for row in later if row["in_ad"]]
    program_max = max((row["score"] for row in program_rows), default=0)
    payload = {
        "system": "v1_known_001",
        "mute_policy": False,
        "installed": False,
        "known_refs": list(known.values()),
        "later_queries": len(later),
        "later_ad_queries": len(ad_rows),
        "later_program_queries": len(program_rows),
        "later_ad_s": span_seconds(later, lambda row: row["in_ad"]),
        "later_program_s": span_seconds(later, lambda row: not row["in_ad"]),
        "program_max_score": program_max,
        "ad_scores": sorted({row["score"] for row in ad_rows}, reverse=True),
        "note": "Known means a query already scored at least 200 on that reference inside a commercial. No new count is chosen.",
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(payload, indent=2) + "\n")
    (OUT / "later.jsonl").write_text("".join(json.dumps(row) + "\n" for row in later))
    print(json.dumps({k: payload[k] for k in payload if k != "ad_scores"}, indent=2))
    print("ad score count", len(payload["ad_scores"]), "top", payload["ad_scores"][:12], "low", payload["ad_scores"][-8:])


if __name__ == "__main__":
    main()
