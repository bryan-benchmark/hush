"""Outro-song fingerprint, then the broadcaster two minutes later.

The outro window is the 8 seconds that end at a labeled commercial start.
That placement uses the gold mark. The match itself uses only earlier
outros. Nothing here is a mute, and no count is chosen from these scores.

Frozen before the scores are read:

- Window 8 seconds, ending at the labeled start. A break with less than 8
  seconds of tape before it is skipped.
- audfprint landmarks, 11025 Hz, density 100, match window 2 frames.
  Reported counts are the published short-query counts: 10, 20, 50, and 200.
- A reference is an earlier outro whose audio has already ended. Later
  breaks and later games stay out of the library.
- Program probes are an 8-second window every 30 seconds, at least 20
  seconds from a commercial and clear of every outro window.
- One ad probe sits at the middle of a pod when that window starts at
  least 12 seconds after the pod start.
- The cover, if this path were followed, starts when the window ends.
  Two minutes later the look uses the locked return: the highest enrolled
  cosine in the last 30 seconds, at or over 0.10. The published 0.25 line
  is recorded beside it. A show with no enrolled booth does not start this
  path. If the booth never arrives, the look stops 180 seconds after it
  opened.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "experiments/broadcast_intelligence/third_party/audfprint"))

from experiments.broadcast_intelligence.batch1 import (  # noqa: E402
    HOLDOUTS,
    find_session,
    load_session,
    read_span,
)
from experiments.broadcast_intelligence.known_ad_fingerprint import (  # noqa: E402
    RECORDINGS,
    allow_mask,
    best_match,
    build_index,
    fingerprint,
    to_11025,
)
from hush.break_trace import BOOTH_LINE  # noqa: E402
from hush.outro_return import LOOK_S, describe_look, overlap, rolling_maxes, union_seconds  # noqa: E402
from hush.voice_floor import FLOOR  # noqa: E402

OUT = REPO / "docs/ohush/research/OUTRO_RETURN_001"
WINDOW_S = 8.0
PROBE_STEP_S = 30.0
POD_CLEAR_S = 20.0
AD_LEAD_S = 12.0
COUNTS = (10, 20, 50, 200)
REDZONE = "hush_20260913_150934"


def overlaps(a0: float, a1: float, b0: float, b1: float) -> bool:
    return min(a1, b1) - max(a0, b0) > 0


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round(q * (len(ordered) - 1))))
    return ordered[index]


def band(score: int) -> str:
    if score <= 0:
        return "0"
    if score < 10:
        return "1-9"
    if score < 20:
        return "10-19"
    if score < 50:
        return "20-49"
    if score < 200:
        return "50-199"
    return "200+"


def earlier_ids(outros: list[dict], row: dict) -> list[int]:
    chosen = []
    for ref in outros:
        if ref["session"] < row["session"] or (ref["session"] == row["session"] and ref["t1"] <= row["t0"]):
            chosen.append(ref["id"])
    return chosen


def main() -> None:
    receipts = [
        json.loads(line)
        for line in (REPO / "docs/ohush/research/START_END_001/receipts.jsonl").read_text().splitlines()
        if line.strip()
    ]
    pods: dict[str, list[tuple[float, float]]] = defaultdict(list)
    network: dict[str, str] = {}
    for row in receipts:
        if row["session"] in HOLDOUTS:
            raise SystemExit("refusing a sealed holdout")
        pods[row["session"]].append((float(row["start"]), float(row["end"])))
        network[row["session"]] = row["network"]
    for edges in pods.values():
        edges.sort()
    network[REDZONE] = "FOX RedZone"

    decisions: dict[str, list[dict]] = defaultdict(list)
    for line in (REPO / "docs/ohush/research/BREAK_TRACE_001/decisions.jsonl").read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row["session"] in HOLDOUTS:
            raise SystemExit("refusing a sealed holdout")
        decisions[row["session"]].append(row)
    for rows in decisions.values():
        rows.sort(key=lambda item: float(item["t"]))
        for item, score in zip(rows, rolling_maxes(rows)):
            item["roll"] = score
    enrolled = {
        session
        for session, rows in decisions.items()
        if any(item.get("cosine") is not None for item in rows)
    }

    windows: list[dict] = []
    skipped_short = 0
    for session, edges in pods.items():
        for start, end in edges:
            if start < WINDOW_S:
                skipped_short += 1
                continue
            windows.append(make_window("outro", session, network[session], start - WINDOW_S, start, start, end))
            mid = (start + end) / 2.0
            if mid - 4.0 >= start + AD_LEAD_S and mid + 4.0 <= end:
                windows.append(make_window("ad", session, network[session], mid - 4.0, mid + 4.0, start, end))

    outro_spans = [(row["session"], row["t0"], row["t1"]) for row in windows if row["kind"] == "outro"]
    for session, rows in decisions.items():
        if not rows:
            continue
        last = float(rows[-1]["t"])
        edges = pods.get(session, [])
        t = WINDOW_S
        while t <= last:
            t0 = t - WINDOW_S
            blocked = any(overlaps(t0, t, start - POD_CLEAR_S, end + POD_CLEAR_S) for start, end in edges)
            if not blocked:
                blocked = any(name == session and overlaps(t0, t, a, b) for name, a, b in outro_spans)
            if not blocked:
                kind = "redzone" if session == REDZONE else "program"
                label = network.get(session, rows[0].get("show") or "unknown")
                windows.append(make_window(kind, session, label, t0, t, None, None))
            t += PROBE_STEP_S

    loaded = {}
    for row in windows:
        session = row["session"]
        if session not in loaded:
            if session in HOLDOUTS:
                raise SystemExit("refusing a sealed holdout")
            folder = find_session(RECORDINGS, session)
            loaded[session] = {"dir": folder, "meta": load_session(folder)}

    print(f"windows {len(windows)} skipped_short {skipped_short}", flush=True)
    missing = 0
    for index, row in enumerate(windows):
        bag = loaded[row["session"]]
        try:
            audio = read_span(bag["dir"], bag["meta"], row["t0"], row["t1"])
        except RuntimeError:
            missing += 1
            row["frames"] = row["hashes"] = empty_hashes()
            row["n_hashes"] = 0
            row["missing"] = True
            continue
        frames, hashes, _dts = fingerprint(to_11025(audio), 0)
        row["frames"] = frames
        row["hashes"] = hashes
        row["n_hashes"] = int(frames.size)
        row["missing"] = False
        if index and index % 400 == 0:
            print(f"  fingerprinted {index}", flush=True)
    print(f"fingerprinted {len(windows)} missing {missing}", flush=True)

    outros = [row for row in windows if row["kind"] == "outro" and not row["missing"]]
    for index, row in enumerate(outros):
        row["id"] = index
    self_scores = []
    for row in outros:
        solo = {"id": 0, "frames": row["frames"], "hashes": row["hashes"]}
        hit = best_match(row["frames"], row["hashes"], build_index([solo]), allow_mask(1, [0]))
        row["self_score"] = int(hit["score"])
        self_scores.append(row["self_score"])
    library = build_index(outros)
    print(
        f"self-match median {percentile(self_scores, 0.5)} min {min(self_scores) if self_scores else None}",
        flush=True,
    )

    matched = []
    for row in windows:
        if row["missing"]:
            continue
        allow = earlier_ids(outros, row)
        hit = best_match(row["frames"], row["hashes"], library, allow_mask(len(outros), allow))
        ref = None if hit["ref_id"] is None else outros[hit["ref_id"]]
        look = describe_look(
            decisions.get(row["session"], []),
            pods.get(row["session"], []),
            row["t1"],
            row["session"] in enrolled,
        )
        matched.append(
            {
                "kind": row["kind"],
                "session": row["session"],
                "network": row["network"],
                "t": row["t1"],
                "t0": row["t0"],
                "n_hashes": row["n_hashes"],
                "library": len(allow),
                "score": int(hit["score"]),
                "self_score": row.get("self_score"),
                "ref_session": None if ref is None else ref["session"],
                "ref_t": None if ref is None else ref["t1"],
                "ref_network": None if ref is None else ref["network"],
                "same_session": bool(ref and ref["session"] == row["session"]),
                "pod_start": row["pod_start"],
                "pod_end": row["pod_end"],
                "enrolled": row["session"] in enrolled,
                **look,
            }
        )

    summary = summarize(matched, pods, skipped_short, missing, self_scores)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(summary, indent=2) + "\n")
    kept = []
    for row in matched:
        kept.append({key: value for key, value in row.items() if key not in {"frames", "hashes"}})
    (OUT / "receipts.jsonl").write_text("".join(json.dumps(row) + "\n" for row in kept))
    print(json.dumps({key: summary[key] for key in ("self_match", "kinds", "oracle_enrolled_outros")}, indent=2))
    for count, detail in summary["counts_detail"].items():
        print(count, detail["by_network"], detail["path"])


def empty_hashes():
    import numpy as np

    return np.zeros(0, np.int32)


def make_window(kind, session, network, t0, t1, pod_start, pod_end) -> dict:
    return {
        "kind": kind,
        "session": session,
        "network": network,
        "t0": float(t0),
        "t1": float(t1),
        "pod_start": pod_start,
        "pod_end": pod_end,
    }


def hits_at(rows: list[dict], count: int) -> list[dict]:
    return [row for row in rows if row["library"] > 0 and row["score"] >= count]


def rate(count: int, probes: int) -> float | None:
    if probes <= 0:
        return None
    return round(count / (probes * PROBE_STEP_S / 3600.0), 3)


def pack(group: list[dict]) -> dict:
    scores = [row["score"] for row in group if row["library"] > 0]
    bands: dict[str, int] = defaultdict(int)
    for score in scores:
        bands[band(score)] += 1
    return {
        "n": len(group),
        "with_library": len(scores),
        "score_median": percentile(scores, 0.5),
        "score_p90": percentile(scores, 0.9),
        "score_max": max(scores) if scores else None,
        "bands": dict(bands),
        "hits": {str(count): len(hits_at(group, count)) for count in COUNTS},
    }


def summarize(rows: list[dict], pods, skipped_short: int, missing: int, self_scores: list[int]) -> dict:
    by_kind = {kind: pack([row for row in rows if row["kind"] == kind]) for kind in ("outro", "program", "ad", "redzone")}
    covers = {}
    for count in COUNTS:
        by_net: dict[str, dict] = {}
        for row in rows:
            if row["kind"] != "outro" or row["library"] <= 0:
                continue
            cell = by_net.setdefault(row["network"], {"library": 0, "hits": 0, "same_game": 0})
            cell["library"] += 1
            if row["score"] >= count:
                cell["hits"] += 1
                if row["same_session"]:
                    cell["same_game"] += 1
        program = [row for row in rows if row["kind"] == "program"]
        enrolled_program = [row for row in program if row["enrolled"]]
        cable = [row for row in program if row["network"] == "Cable / antenna"]
        redzone = [row for row in rows if row["kind"] == "redzone"]
        started = [
            (row["session"], float(row["t"]), float(row["cover_end"]))
            for row in rows
            if row["library"] > 0 and row["score"] >= count and row["enrolled"] and row["cover_end"] is not None
        ]
        covers[str(count)] = {
            "by_network": by_net,
            "program_hits": len(hits_at(program, count)),
            "program_per_hour": rate(len(hits_at(program, count)), len(program)),
            "enrolled_program_hits": len(hits_at(enrolled_program, count)),
            "enrolled_program_per_hour": rate(len(hits_at(enrolled_program, count)), len(enrolled_program)),
            "cable_program_hits": len(hits_at(cable, count)),
            "ad_hits": len(hits_at([row for row in rows if row["kind"] == "ad"], count)),
            "redzone_hits": len(hits_at(redzone, count)),
            "redzone_per_hour": rate(len(hits_at(redzone, count)), len(redzone)),
            "path": union_seconds(started, pods),
        }

    oracle_rows = [row for row in rows if row["kind"] == "outro" and row["enrolled"]]
    oracle_spans = [
        (row["session"], float(row["t"]), float(row["cover_end"]))
        for row in oracle_rows
        if row["cover_end"] is not None
    ]
    line_spans = [
        (row["session"], float(row["t"]), float(row["line_t"]) if row["line_t"] is not None else float(row["look_at"]) + 180.0)
        for row in oracle_rows
    ]
    reasons: dict[str, dict] = {}
    for row in oracle_rows:
        if row["fail_open"]:
            reason = "look_expires"
        elif row["look_region"] == "game":
            reason = "look_opens_after_the_game_returned"
        elif row["floor_region"] == "ad":
            reason = "broadcaster_found_inside_an_ad"
        else:
            reason = "broadcaster_found_after_the_ad"
        start, end = float(row["t"]), float(row["cover_end"])
        ad = overlap(start, end, pods.get(row["session"], []))
        cell = reasons.setdefault(reason, {"n": 0, "program_s": 0.0})
        cell["n"] += 1
        cell["program_s"] += (end - start) - ad
    for cell in reasons.values():
        cell["program_s"] = round(cell["program_s"], 3)
    where: dict[str, int] = defaultdict(int)
    game_already = []
    ad_left = []
    for row in oracle_rows:
        where[row["floor_region"] or "none"] += 1
        if row["pod_end"] is None:
            continue
        look_at = float(row["look_at"])
        if look_at > float(row["pod_end"]):
            game_already.append(round(look_at - float(row["pod_end"]), 3))
        else:
            ad_left.append(round(float(row["pod_end"]) - look_at, 3))
    return {
        "system": "outro_return_001",
        "mute_policy": False,
        "installed": False,
        "window_s": WINDOW_S,
        "look_s": LOOK_S,
        "floor": FLOOR,
        "booth_line": BOOTH_LINE,
        "counts": list(COUNTS),
        "skipped_under_8s": skipped_short,
        "missing_audio": missing,
        "self_match": {
            "n": len(self_scores),
            "min": min(self_scores) if self_scores else None,
            "median": percentile(self_scores, 0.5),
        },
        "kinds": by_kind,
        "counts_detail": covers,
        "oracle_enrolled_outros": {
            "n": len(oracle_rows),
            "where_the_broadcaster_is_found": dict(where),
            "look_opens_after_the_game_returned": len(game_already),
            "look_opens_while_the_ad_is_still_on": len(ad_left),
            "game_already_median_s": percentile(game_already, 0.5),
            "ad_still_on_median_s": percentile(ad_left, 0.5),
            "fail_open": sum(1 for row in oracle_rows if row["fail_open"]),
            "program_seconds_by_reason": reasons,
            "path_if_every_outro_were_known": union_seconds(oracle_spans, pods),
            "path_at_the_published_0_25_line": union_seconds(line_spans, pods),
        },
    }


if __name__ == "__main__":
    main()
