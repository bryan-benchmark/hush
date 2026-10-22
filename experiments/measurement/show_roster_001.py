"""Score each show against its own booth only.

Scott Hanson is scored on the RedZone span and nowhere else. Mike Tirico is
scored on the NBC Sunday Night Football recordings and nowhere else. The
published cosine stays 0.25. No live mute.
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

from experiments.broadcast_intelligence.batch1 import commercials, coverage  # noqa: E402
from experiments.measurement.verified_speaker_001 import (  # noqa: E402
    assign,
    latest_names,
    load_windows,
    prototype,
    spans_from,
)
from experiments.universal_v4.speaker_enrollment import person_name  # noqa: E402
from hush.show_roster import RELEASE_S, SHOWS, decide  # noqa: E402
from hush.speaker_memory import MATCH_COSINE  # noqa: E402

OUT = REPO / "docs/ohush/research/SHOW_ROSTER_001"
REDZONE = "hush_20260913_150934"

# Channel and show title already say which broadcast this is.
SESSION_SHOW = {
    REDZONE: "redzone",
    "hush_20260909_213047": "snf",
    "hush_20260913_210542": "snf",
    "hush_20260914_212529": "mnf",
    "hush_20260924_220624": "tnf",
    "hush_20261008_205100": "tnf",
}


def enrolled_vectors():
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
            if name:
                owned.append({**row, "person": name})
    return owned


def show_prototypes(owned, show):
    wanted = set(SHOWS[show])
    grouped = defaultdict(list)
    for row in owned:
        if row["person"] in wanted:
            grouped[row["person"]].append(row)
    built = {}
    missing = []
    for name in SHOWS[show]:
        proto = prototype(grouped.get(name, []))
        if proto is None:
            missing.append(name)
        else:
            built[name] = proto
    return built, missing


def hit_ends(session, prototypes, limit):
    path = REPO / "experiments/exp002" / session / "speaker_segments.parquet"
    if not path.exists() or not prototypes:
        return []
    windows = load_windows(session)
    ends = []
    names = list(prototypes)
    matrix = np.vstack([prototypes[name] for name in names])
    for index, end in enumerate(windows["end"]):
        if limit is not None and float(end) > limit:
            continue
        scores = windows["vector"][index] @ matrix.T
        if float(np.max(scores)) >= MATCH_COSINE:
            ends.append(float(end))
    return ends


def gaps_of(ends):
    return [round(b - a, 3) for a, b in zip(ends, ends[1:])]


def main():
    owned = enrolled_vectors()
    pods = defaultdict(list)
    for row in commercials(coverage()):
        if row["session"] in SESSION_SHOW:
            pods[row["session"]].append((float(row["start_seconds"]), float(row["end_seconds"])))
    shows = {}
    for show in SHOWS:
        prototypes, missing = show_prototypes(owned, show)
        sessions = []
        for session, assigned in SESSION_SHOW.items():
            if assigned != show:
                continue
            limit = 7200.0 if session == REDZONE else None
            ends = hit_ends(session, prototypes, limit)
            gaps = gaps_of(ends)
            ad_inside = 0.0
            if ends:
                for start, stop in pods.get(session, []):
                    pieces = []
                    for end in ends:
                        left = max(start, end)
                        right = min(stop, end + RELEASE_S)
                        if right > left:
                            pieces.append((left, right))
                    pieces.sort()
                    merged = []
                    for left, right in pieces:
                        if merged and left <= merged[-1][1]:
                            merged[-1][1] = max(merged[-1][1], right)
                        else:
                            merged.append([left, right])
                    ad_inside += sum(right - left for left, right in merged)
            sessions.append({
                "session": session,
                "hits": len(ends),
                "longest_gap_s": max(gaps) if gaps else None,
                "gaps_at_least_5_min": sum(gap >= RELEASE_S for gap in gaps),
                "commercial_seconds_while_show_still_owns_audio": round(ad_inside, 1),
                "commercial_seconds": round(sum(stop - start for start, stop in pods.get(session, [])), 1),
                "five_minutes_after_a_hit": decide(show, 0)["commercial_rules"],
                "after_five_quiet_minutes": decide(show, RELEASE_S)["commercial_rules"],
            })
        shows[show] = {
            "roster": list(SHOWS[show]),
            "enrolled": sorted(prototypes),
            "not_enrolled": missing,
            "sessions": sessions,
        }
    payload = {
        "line": MATCH_COSINE,
        "line_fit": False,
        "release_s": RELEASE_S,
        "hanson_scored_on": ["redzone"],
        "tirico_scored_on": ["snf"],
        "shows": shows,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
