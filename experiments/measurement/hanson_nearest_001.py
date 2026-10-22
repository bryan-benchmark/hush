"""Nearest-name test for the RedZone show lock. Not a mute.

The published ECAPA cosine stays 0.25. No new line is searched.

A window is Scott Hanson only when his prototype is at least 0.25 and
strictly nearer than every other enrolled person. Tirico, Buck, and the
labeled advertisement windows are the rejection set. Hanson windows are
scored against the other Hanson clip only.

The five-minute quiet is counted on the one labeled RedZone span. No
second RedZone recording with commercials is in the labeled set.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from experiments.broadcast_intelligence.batch1 import commercials, coverage, load_catalog  # noqa: E402
from experiments.measurement.verified_speaker_001 import (  # noqa: E402
    assign,
    latest_names,
    load_windows,
    prototype,
    spans_from,
)
from experiments.universal_v4.speaker_enrollment import person_name  # noqa: E402
from hush.speaker_memory import MATCH_COSINE  # noqa: E402

OUT = REPO / "docs/ohush/research/HANSON_NEAREST_001"
REDZONE = "hush_20260913_150934"
QUIET_S = 300.0
LINE = MATCH_COSINE


def owned_people():
    spans = []
    for row in latest_names():
        spans.extend(spans_from(row))
    by_session = defaultdict(list)
    for span in spans:
        by_session[span["session"]].append(span)
    owned = []
    for session, group in by_session.items():
        path = REPO / "experiments/exp002" / session / "speaker_segments.parquet"
        if not path.exists():
            continue
        windows = load_windows(session)
        for row in assign(windows, group):
            name = person_name(row)
            if name is None and row["kind"] != "ad":
                continue
            owned.append({**row, "person": name, "windows": windows})
    return owned


def proto_bank(rows, skip_clip=None, skip_person=None):
    grouped = defaultdict(list)
    for row in rows:
        if row["person"] is None:
            continue
        if skip_person and row["person"] == skip_person and skip_clip and row["clip_id"] == skip_clip:
            continue
        grouped[row["person"]].append(row)
    bank = {}
    for name, group in grouped.items():
        built = prototype(group)
        if built is not None:
            bank[name] = built
    return bank


def nearest(vector, bank):
    ranking = []
    for name, proto in bank.items():
        ranking.append((float(vector @ proto), name))
    ranking.sort(reverse=True)
    return ranking


def is_hanson(ranking):
    if not ranking:
        return False
    score, name = ranking[0]
    if name != "Scott Hanson" or score < LINE:
        return False
    if len(ranking) > 1 and ranking[1][0] >= score:
        return False
    return True


def pack(rows, hanson):
    return {
        "n": len(rows),
        "called_hanson": hanson,
        "called_someone_else_or_nobody": len(rows) - hanson,
    }


def main():
    rows = owned_people()
    hanson_rows = [row for row in rows if row["person"] == "Scott Hanson"]
    tirico_rows = [row for row in rows if row["person"] == "Mike Tirico"]
    buck_rows = [row for row in rows if row["person"] == "Joe Buck"]
    ad_rows = [row for row in rows if row["kind"] == "ad"]

    def judge(group, held_out):
        called = []
        for row in group:
            if held_out:
                bank = proto_bank(rows, skip_clip=row["clip_id"], skip_person=row["person"])
            else:
                bank = proto_bank(rows)
            ranking = nearest(row["vector"], bank)
            called.append({
                "clip_id": row["clip_id"],
                "session": row["session"],
                "who": row["who"],
                "hanson": is_hanson(ranking),
                "top": ranking[0][1] if ranking else None,
                "top_cosine": round(ranking[0][0], 3) if ranking else None,
                "hanson_cosine": round(next((score for score, name in ranking if name == "Scott Hanson"), -1), 3),
            })
        return called

    hanson_calls = judge(hanson_rows, held_out=True)
    tirico_calls = judge(tirico_rows, held_out=True)
    buck_calls = judge(buck_rows, held_out=True)
    ad_calls = judge(ad_rows, held_out=False)

    # Causal lock on the labeled RedZone span. Examples count only after they end.
    windows = load_windows(REDZONE)
    enrollments = [row for row in rows if row["person"]]
    hits = []
    for index, end in enumerate(windows["end"]):
        start = float(windows["start"][index])
        if float(end) > 7200:
            continue
        eligible = [row for row in enrollments if row["end"] <= float(end)]
        bank = proto_bank(eligible)
        ranking = nearest(windows["vector"][index], bank)
        if is_hanson(ranking):
            hits.append({"start": start, "end": float(end), "cosine": round(ranking[0][0], 3)})
    gaps = []
    for previous, nxt in zip(hits, hits[1:]):
        gaps.append(round(nxt["start"] - previous["end"], 3))
    long_gaps = [gap for gap in gaps if gap >= QUIET_S]
    catalog = load_catalog()
    redzone_notes = [
        {
            "session": sid,
            "show": info.get("show"),
            "notes": info.get("notes"),
        }
        for sid, info in catalog.items()
        if "redzone" in f"{info.get('show','')} {info.get('notes','')}".lower() or sid == REDZONE
    ]
    later_commercials = []
    for row in commercials(coverage()):
        if row["session"] <= REDZONE or catalog.get(row["session"], {}).get("content_type") != "sports":
            continue
        if row["session"] == REDZONE:
            continue
        later_commercials.append(row)
    commercial_hits = 0
    commercial_windows = 0
    locked_commercial_s = 0.0
    locked_pods = 0
    by_session = defaultdict(list)
    for row in later_commercials:
        by_session[row["session"]].append((float(row["start_seconds"]), float(row["end_seconds"])))
    for session, pods in by_session.items():
        path = REPO / "experiments/exp002" / session / "speaker_segments.parquet"
        if not path.exists():
            continue
        other = load_windows(session)
        hit_ends = []
        for index, end in enumerate(other["end"]):
            eligible = [
                row for row in enrollments
                if row["session"] < session or (row["session"] == session and row["end"] <= float(end))
            ]
            bank = proto_bank(eligible)
            if not is_hanson(nearest(other["vector"][index], bank)):
                continue
            hit_ends.append(float(end))
            mid = (float(other["start"][index]) + float(end)) / 2
            if any(start <= mid < stop for start, stop in pods):
                commercial_hits += 1
        for index, end in enumerate(other["end"]):
            mid = (float(other["start"][index]) + float(end)) / 2
            if any(start <= mid < stop for start, stop in pods):
                commercial_windows += 1
        for start, stop in pods:
            pieces = []
            for hit_end in hit_ends:
                left = max(start, hit_end)
                right = min(stop, hit_end + QUIET_S)
                if right > left:
                    pieces.append((left, right))
            pieces.sort()
            merged = []
            for left, right in pieces:
                if merged and left <= merged[-1][1]:
                    merged[-1][1] = max(merged[-1][1], right)
                else:
                    merged.append([left, right])
            covered = sum(right - left for left, right in merged)
            if covered > 0:
                locked_pods += 1
                locked_commercial_s += covered

    payload = {
        "line": LINE,
        "line_fit": False,
        "rule": "Hanson only when his cosine is at least 0.25 and strictly greater than every other enrolled person.",
        "quiet_s": QUIET_S,
        "second_redzone_with_commercials": False,
        "redzone_catalog_hits": redzone_notes,
        "hanson_held_out": pack(hanson_rows, sum(row["hanson"] for row in hanson_calls)),
        "tirico_not_hanson": pack(tirico_rows, sum(row["hanson"] for row in tirico_calls)),
        "buck_not_hanson": pack(buck_rows, sum(row["hanson"] for row in buck_calls)),
        "ads_not_hanson": pack(ad_rows, sum(row["hanson"] for row in ad_calls)),
        "rejection_failures": [row for row in tirico_calls + buck_calls + ad_calls if row["hanson"]],
        "hanson_misses": [row for row in hanson_calls if not row["hanson"]],
        "redzone_hits": len(hits),
        "redzone_gaps": len(gaps),
        "redzone_gaps_at_least_5_min": len(long_gaps),
        "redzone_longest_gap_s": max(gaps) if gaps else None,
        "later_football_commercial_windows": commercial_windows,
        "later_football_commercial_windows_called_hanson": commercial_hits,
        "later_football_commercial_seconds_inside_a_5_min_lock": round(locked_commercial_s, 1),
        "later_football_pods_touched_by_the_lock": locked_pods,
        "later_football_pods": len(later_commercials),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: payload[key] for key in payload if key != "redzone_catalog_hits"}, indent=2))


if __name__ == "__main__":
    main()
