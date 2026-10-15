"""POD-REMOVAL-001. Isolated shadow replay. Not a mute.

Count 10, the 5-second query, chronological enrollment, and gold stay as
published. The five reference pods that the accuracy audit associated with
the most false program seconds are removed from the library, and best_match
is run again. Top-one and top-ten removals are the same procedure.

Subtracting those pods from the old ledger is not a result. A query whose
winning pod was removed can land on the next pod.
"""

from __future__ import annotations

import csv
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "experiments/broadcast_intelligence/third_party/audfprint"))
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))

from experiments.broadcast_intelligence.batch1 import commercials, coverage, load_catalog  # noqa: E402
from experiments.broadcast_intelligence.known_ad_fingerprint import (  # noqa: E402
    HOP,
    TARGET_SR,
    allow_mask,
    best_match,
    window_hashes,
)
from experiments.universal_v1.replay import (  # noqa: E402
    COUNT_ABLATION,
    COUNT_V1,
    RECORDINGS,
    REDZONE,
    STREAM_HOP_S,
    actions_for,
    build_refs,
    fingerprint_sessions,
    overlap,
    score_group,
    subtract,
)
from hush.audio import find_session, load_session  # noqa: E402

DECISIONS = REPO / "docs/ohush/research/UNIVERSAL_V1/decisions.jsonl"
AUDIT = REPO / "docs/ohush/research/ACCURACY_AUDIT_001/false_incidents_by_reference.csv"
OUT = REPO / "docs/ohush/research/POD_REMOVAL_001"
HOLDOUTS = ("hush_20260917_205513", "hush_20260920_200635")
FRAME_S = HOP / TARGET_SR


def load_decisions() -> dict[tuple[str, float], dict]:
    found = {}
    for line in DECISIONS.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row["session"] in HOLDOUTS:
            raise SystemExit("refusing a sealed holdout")
        found[(row["session"], round(float(row["query_t0"]), 3))] = row
    return found


def damage_rank() -> list[tuple[tuple[str, float], float]]:
    totals: dict[tuple[str, float], float] = defaultdict(float)
    with AUDIT.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["population"] != "football":
                continue
            key = (row["ref_session"], round(float(row["ref_start"]), 3))
            totals[key] += float(row["program_seconds"])
    return sorted(totals.items(), key=lambda item: (-item[1], item[0][0], item[0][1]))


def prepare() -> tuple[dict, list[dict], list[dict], dict]:
    catalog = load_catalog()
    spans = coverage()
    raw_pods = commercials(spans)
    if len(raw_pods) != 166:
        raise SystemExit(f"expected 166 commercials, found {len(raw_pods)}")
    sessions = {}
    for span in spans:
        sid = span["session"]
        if sid in HOLDOUTS:
            raise SystemExit("refusing a sealed holdout")
        folder = find_session(RECORDINGS, sid)
        meta = load_session(folder)
        info = catalog.get(sid, {})
        sessions[sid] = {
            "dir": folder,
            "meta": meta,
            "coverage": (float(span["from_seconds"]), float(span["to_seconds"])),
            "network": info.get("network_or_service") or "unknown",
            "content": info.get("content_type") or "",
        }
    pods = []
    for index, row in enumerate(raw_pods):
        sid = row["session"]
        pods.append(
            {
                "id": index,
                "session": sid,
                "network": sessions[sid]["network"],
                "content": sessions[sid]["content"],
                "start": float(row["start_seconds"]),
                "end": float(row["end_seconds"]),
            }
        )
    print("fingerprinting", flush=True)
    landmarks, holes, _missing = fingerprint_sessions(sessions, {})
    refs, index = build_refs(pods, landmarks)
    return sessions, pods, holes, {"landmarks": landmarks, "refs": refs, "index": index}


def stream(sessions: dict, refs: list[dict], index: dict, excluded: set[int]) -> list[dict]:
    by_session = defaultdict(list)
    for ref in refs:
        by_session[ref["session"]].append(ref)
    order = sorted(sessions)
    rows = []
    for sid in order:
        cov0, cov1 = sessions[sid]["coverage"]
        earlier = [
            ref["id"]
            for name in order
            if name < sid
            for ref in by_session[name]
            if ref["id"] not in excluded
        ]
        allow = allow_mask(len(refs), earlier)
        bag = sessions[sid]["landmarks"]
        t = cov0 + STREAM_HOP_S
        while t + STREAM_HOP_S <= cov1:
            frames, hashes = window_hashes(bag["frames"], bag["hashes"], bag["dts"], t, t + STREAM_HOP_S)
            hit = best_match(frames, hashes, index, allow)
            ref = None if hit["ref_id"] is None else refs[hit["ref_id"]]
            rows.append(
                {
                    "session": sid,
                    "network": sessions[sid]["network"],
                    "content": sessions[sid]["content"],
                    "query_t0": round(t, 3),
                    "query_t1": round(t + STREAM_HOP_S, 3),
                    "available_at": round(t + STREAM_HOP_S, 3),
                    "score": int(hit["score"]),
                    "n_hashes": int(hit["n_hashes"]),
                    "ref_session": None if ref is None else ref["session"],
                    "ref_start": None if ref is None else round(float(ref["start"]), 3),
                    "ref_end": None if ref is None else round(float(ref["end"]), 3),
                    "same_session": bool(ref is not None and ref["session"] == sid),
                    "offset_frames": None if hit["offset"] is None else int(hit["offset"]),
                }
            )
            t += STREAM_HOP_S
        print(f"  queried {sid} excluded {len(excluded)}", flush=True)
    return rows


def reproduce(rows: list[dict], frozen: dict[tuple[str, float], dict]) -> None:
    if len(rows) != len(frozen):
        raise SystemExit(f"query count {len(rows)} != frozen {len(frozen)}")
    bad = []
    for row in rows:
        key = (row["session"], row["query_t0"])
        old = frozen.get(key)
        if old is None:
            bad.append({"key": key, "reason": "missing"})
            continue
        old_start = None if old["ref_start"] is None else round(float(old["ref_start"]), 3)
        if (
            int(old["score"]) != row["score"]
            or int(old["n_hashes"]) != row["n_hashes"]
            or old["ref_session"] != row["ref_session"]
            or old_start != row["ref_start"]
            or bool(old["same_session"]) != row["same_session"]
        ):
            bad.append(
                {
                    "session": row["session"],
                    "query_t0": row["query_t0"],
                    "frozen_score": old["score"],
                    "new_score": row["score"],
                    "frozen_ref": [old["ref_session"], old_start],
                    "new_ref": [row["ref_session"], row["ref_start"]],
                }
            )
    if bad:
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "mismatch.json").write_text(json.dumps(bad[:20], indent=2) + "\n", encoding="utf-8")
        raise SystemExit(f"rematch did not reproduce decisions.jsonl ({len(bad)} rows). See mismatch.json")


def actions_of(sessions: dict, rows: list[dict], count: int) -> dict:
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["session"]].append(row)
    return {sid: actions_for(bag, grouped.get(sid, []), count) for sid, bag in sessions.items()}


def population(name: str, sessions: dict, pods: list[dict], holes: list[dict], actions: dict, count: int) -> dict:
    scored = score_group(name, sessions, pods, holes, actions, count)
    muted = round(sum(row["ad_seconds"] for row in scored["sessions"]) - scored["commercial_seconds_heard"], 1)
    scored["commercial_seconds_muted"] = muted
    return scored


def position_s(row: dict) -> float | None:
    if row["offset_frames"] is None or row["ref_start"] is None:
        return None
    return row["query_t0"] + row["offset_frames"] * FRAME_S - row["ref_start"]


def changed_queries(baseline: list[dict], trial: list[dict], removed: set[tuple[str, float]]) -> list[dict]:
    trial_by = {(row["session"], row["query_t0"]): row for row in trial}
    out = []
    for old in baseline:
        key = (old["ref_session"], old["ref_start"])
        if old["score"] < COUNT_ABLATION or old["same_session"] or key not in removed:
            continue
        new = trial_by[(old["session"], old["query_t0"])]
        out.append(
            {
                "session": old["session"],
                "query_t0": old["query_t0"],
                "available_at": old["available_at"],
                "query_t1": old["query_t1"],
                "old_ref_session": old["ref_session"],
                "old_ref_start": old["ref_start"],
                "old_ref_end": old["ref_end"],
                "old_score": old["score"],
                "old_position_in_pod_s": None if position_s(old) is None else round(position_s(old), 3),
                "new_ref_session": new["ref_session"],
                "new_ref_start": new["ref_start"],
                "new_score": new["score"],
                "new_position_in_pod_s": None if position_s(new) is None else round(position_s(new), 3),
                "still_at_least_10": new["score"] >= COUNT_ABLATION and not new["same_session"],
            }
        )
    return out


def query_seconds(sessions: dict, pods: list[dict], holes: list[dict], rows: list[dict]) -> dict[str, float]:
    """Seconds inside each query's own decision span. Neighboring queries are not merged."""
    ads = defaultdict(list)
    hole_map = defaultdict(list)
    for pod in pods:
        ads[pod["session"]].append((pod["start"], pod["end"]))
    for hole in holes:
        hole_map[hole["session"]].append((hole["start"], hole["end"]))
    program_s = commercial_s = 0.0
    cache: dict[str, tuple[list, list]] = {}
    for row in rows:
        sid = row["session"]
        if sid not in cache:
            cov0, cov1 = sessions[sid]["coverage"]
            cache[sid] = (
                subtract(subtract([(cov0, cov1)], ads[sid]), hole_map[sid]),
                subtract(ads[sid], hole_map[sid]),
            )
        cov1 = sessions[sid]["coverage"][1]
        window = [(row["available_at"], min(row["available_at"] + STREAM_HOP_S, cov1))]
        program, commercial = cache[sid]
        program_s += overlap(program, window)
        commercial_s += overlap(commercial, window)
    return {"program_s": round(program_s, 3), "commercial_s": round(commercial_s, 3)}


def offset_summary(rows: list[dict]) -> dict:
    placed = [
        row
        for row in rows
        if row["old_position_in_pod_s"] is not None and row["old_ref_end"] is not None
    ]
    if not placed:
        return {"n": 0}
    values = [row["old_position_in_pod_s"] for row in placed]
    ordered = sorted(values)

    def share(predicate) -> float:
        return round(sum(1 for row in placed if predicate(row)) / len(placed), 3)

    return {
        "n": len(placed),
        "median_s": round(ordered[len(ordered) // 2], 3),
        "min_s": round(ordered[0], 3),
        "max_s": round(ordered[-1], 3),
        "share_first_5s": share(lambda row: 0 <= row["old_position_in_pod_s"] < 5),
        "share_last_5s": share(
            lambda row: row["old_ref_end"] - 5 <= row["old_ref_start"] + row["old_position_in_pod_s"] <= row["old_ref_end"]
        ),
    }


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def render(payload: dict) -> str:
    lines = [
        "# Reference-pod removal",
        "",
        "Verdict: exploratory. The pods were chosen from the same false mutes this replay scores. A gain here is not a rule for the next recording. Playback stays PLAY.",
        "",
        "Count 10, the query clock, chronological enrollment, and gold were not changed. `best_match` was run again with the chosen pods absent from the library. The published decisions were reproduced first, including the reference each query named.",
        "",
        "The ranking is whole-pod attribution from the accuracy audit. It is not proof that the pod contains a bumper or a promo.",
        "",
        "| Removal | Program seconds | Incidents | Commercial seconds muted | Commercial seconds lost | Program seconds eliminated | Worst interruption | RedZone program seconds |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    base = payload["count10"]
    for name in ("top_1", "top_5", "top_10"):
        row = payload["removals"][name]
        lines.append(
            f"| {name.replace('_', ' ')} | {row['football']['program_seconds_covered']:.1f} | {row['football']['false_cover_incidents']} | "
            f"{row['football']['commercial_seconds_muted']:.1f} | {row['commercial_seconds_lost']:.1f} | "
            f"{row['program_seconds_eliminated']:.1f} | {row['football']['worst_continuous_program_interruption_s']:.1f} | "
            f"{row['redzone']['program_seconds_covered']:.1f} |"
        )
    lines += [
        "",
        f"Count 10 before removal: {base['football']['program_seconds_covered']:.1f} program seconds, "
        f"{base['football']['false_cover_incidents']} incidents, "
        f"{base['football']['commercial_seconds_muted']:.1f} commercial seconds muted, "
        f"worst interruption {base['football']['worst_continuous_program_interruption_s']:.1f} s, "
        f"RedZone {base['redzone']['program_seconds_covered']:.1f} program seconds.",
        "",
        f"Universal v1 on the same reproduced queries: {payload['v1']['football']['program_seconds_covered']:.1f} program seconds and "
        f"{payload['v1']['football']['commercial_seconds_muted']:.1f} commercial seconds muted.",
        "",
        "## Where the removed queries went",
        "",
    ]
    for name in ("top_1", "top_5", "top_10"):
        row = payload["removals"][name]
        move = row["moved"]
        lines.append(
            f"- {name.replace('_', ' ')}: {move['queries']} queries had named a removed pod at count 10 or above. "
            f"{move['still_covered']} still matched some other earlier pod at 10 or above "
            f"({move['replacement_program_s']:.1f} program seconds, {move['replacement_commercial_s']:.1f} commercial seconds on those query spans). "
            f"{move['fell_below']} fell below 10 "
            f"({move['released_program_s']:.1f} program seconds, {move['released_commercial_s']:.1f} commercial seconds on those query spans)."
        )
        if row["replacement_pods"]:
            lead = row["replacement_pods"][0]
            lines.append(
                f"  The busiest replacement was {lead['session']} at {lead['start']:.3f}: "
                f"{lead['queries']} queries, {lead['program_s']:.1f} program seconds, {lead['commercial_s']:.1f} commercial seconds."
            )
    lines += [
        "",
        "A query span is the interval from that decision to the next one. The table above is the merged timeline, so those two second-counts do not add to the eliminated total when neighboring queries still cover the same stretch.",
        "",
        "## Pods removed",
        "",
        "| Rank | Reference session | Pod start | Audit program seconds |",
        "| ---: | --- | ---: | ---: |",
    ]
    for index, pod in enumerate(payload["ranked_pods"], start=1):
        lines.append(
            f"| {index} | {pod['session']} | {pod['start']:.3f} | {pod['audit_program_s']:.1f} |"
        )
    lines += [
        "",
        payload["offset_note"],
        "",
        "No threshold was retuned. No live playback changed.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    started = time.perf_counter()
    ranked = damage_rank()
    if not ranked or ranked[0][0] != ("hush_20260913_210542", 9680.14):
        raise SystemExit(f"audit ranking did not start at the published pod: {ranked[:3]}")
    top5_s = round(sum(item[1] for item in ranked[:5]), 1)
    if abs(top5_s - 216.2) > 0.2:
        raise SystemExit(f"top-five audit seconds {top5_s} are not the published 216.2")
    sessions, pods, holes, built = prepare()
    for sid, bag in sessions.items():
        bag["landmarks"] = built["landmarks"][sid]
    frozen = load_decisions()
    print("baseline rematch", flush=True)
    baseline = stream(sessions, built["refs"], built["index"], set())
    reproduce(baseline, frozen)
    by_key = {}
    for ref in built["refs"]:
        key = (ref["session"], round(float(ref["start"]), 3))
        if key in by_key:
            raise SystemExit(f"two pods round to {key}")
        by_key[key] = ref["id"]
    chosen = []
    for key, seconds in ranked[:10]:
        if key not in by_key:
            raise SystemExit(f"ranked pod is not in the library: {key}")
        chosen.append({"session": key[0], "start": key[1], "audit_program_s": round(seconds, 3), "id": by_key[key]})
    v1_actions = actions_of(sessions, baseline, COUNT_V1)
    base_actions = actions_of(sessions, baseline, COUNT_ABLATION)
    v1 = {
        "football": population("football", sessions, pods, holes, v1_actions, COUNT_V1),
        "redzone": population("redzone", sessions, pods, holes, v1_actions, COUNT_V1),
    }
    count10 = {
        "football": population("football", sessions, pods, holes, base_actions, COUNT_ABLATION),
        "redzone": population("redzone", sessions, pods, holes, base_actions, COUNT_ABLATION),
    }
    if count10["football"]["false_cover_incidents"] != 72 or abs(count10["football"]["program_seconds_covered"] - 432.1) > 0.05:
        raise SystemExit(f"count 10 did not reproduce: {count10['football']}")
    if abs(count10["football"]["commercial_seconds_muted"] - 3903.2) > 0.05:
        raise SystemExit(f"count 10 mute total did not reproduce: {count10['football']}")
    if abs(count10["redzone"]["program_seconds_covered"] - 10.0) > 0.05:
        raise SystemExit(f"RedZone did not reproduce: {count10['redzone']}")
    if v1["football"]["program_seconds_covered"] != 0.0 or abs(v1["football"]["commercial_seconds_muted"] - 25.0) > 0.05:
        raise SystemExit(f"v1 did not reproduce: {v1['football']}")

    removals = {}
    for label, width in (("top_1", 1), ("top_5", 5), ("top_10", 10)):
        ids = {pod["id"] for pod in chosen[:width]}
        keys = {(pod["session"], pod["start"]) for pod in chosen[:width]}
        print(f"rematch {label}", flush=True)
        trial = stream(sessions, built["refs"], built["index"], ids)
        actions = actions_of(sessions, trial, COUNT_ABLATION)
        foot = population("football", sessions, pods, holes, actions, COUNT_ABLATION)
        zone = population("redzone", sessions, pods, holes, actions, COUNT_ABLATION)
        moved_rows = changed_queries(baseline, trial, keys)
        kept = [row for row in moved_rows if row["still_at_least_10"]]
        dropped = [row for row in moved_rows if not row["still_at_least_10"]]
        kept_s = query_seconds(sessions, pods, holes, kept)
        dropped_s = query_seconds(sessions, pods, holes, dropped)
        grouped: dict[tuple, dict] = defaultdict(lambda: {"queries": 0, "rows": []})
        for row in kept:
            grouped[(row["new_ref_session"], row["new_ref_start"])]["queries"] += 1
            grouped[(row["new_ref_session"], row["new_ref_start"])]["rows"].append(row)
        replacement_pods = []
        for key, block in grouped.items():
            seconds = query_seconds(sessions, pods, holes, block["rows"])
            replacement_pods.append(
                {
                    "session": key[0],
                    "start": key[1],
                    "queries": block["queries"],
                    "program_s": seconds["program_s"],
                    "commercial_s": seconds["commercial_s"],
                }
            )
        replacement_pods.sort(key=lambda item: (-item["program_s"], -item["queries"], item["session"], item["start"]))
        write_csv(OUT / f"{label}_changed_queries.csv", moved_rows)
        removals[label] = {
            "pods_removed": chosen[:width],
            "football": {key: foot[key] for key in (
                "program_seconds_covered",
                "false_cover_incidents",
                "commercial_seconds_muted",
                "commercial_seconds_heard",
                "worst_continuous_program_interruption_s",
            )},
            "redzone": {
                "program_seconds_covered": zone["program_seconds_covered"],
                "false_cover_incidents": zone["false_cover_incidents"],
                "commercial_seconds_muted": zone["commercial_seconds_muted"],
            },
            "program_seconds_eliminated": round(
                count10["football"]["program_seconds_covered"] - foot["program_seconds_covered"], 1
            ),
            "incidents_eliminated": count10["football"]["false_cover_incidents"] - foot["false_cover_incidents"],
            "commercial_seconds_lost": round(
                count10["football"]["commercial_seconds_muted"] - foot["commercial_seconds_muted"], 1
            ),
            "v1_commercial_still_ahead_s": round(foot["commercial_seconds_muted"] - v1["football"]["commercial_seconds_muted"], 1),
            "moved": {
                "queries": len(moved_rows),
                "still_covered": len(kept),
                "fell_below": len(dropped),
                "replacement_program_s": kept_s["program_s"],
                "replacement_commercial_s": kept_s["commercial_s"],
                "released_program_s": dropped_s["program_s"],
                "released_commercial_s": dropped_s["commercial_s"],
            },
            "offset_on_removed_matches": offset_summary(moved_rows),
            "replacement_pods": replacement_pods[:8],
        }
        del trial

    top5 = removals["top_5"]
    improved = top5["program_seconds_eliminated"] >= 50
    if improved:
        note = (
            f"Top-five removal cut {top5['program_seconds_eliminated']:.1f} program seconds, so the alignment offset "
            f"`best_match` already computed was kept for those queries. "
            f"On {top5['offset_on_removed_matches'].get('n', 0)} of them the implied position inside the old pod has median "
            f"{top5['offset_on_removed_matches'].get('median_s')} s. "
            f"{top5['offset_on_removed_matches'].get('share_first_5s')} fall in the first 5 seconds and "
            f"{top5['offset_on_removed_matches'].get('share_last_5s')} fall in the last 5 seconds. "
            "That locates the match. It does not name the audio as a bumper, a promo, or an advertisement."
        )
    else:
        note = (
            f"Top-five removal eliminated {top5['program_seconds_eliminated']:.1f} program seconds. "
            "That is not a large enough drop to justify reading the interior of the pods as the cause. "
            "Offsets for the rematched queries are in the changed-query files. A creative-level library was not built."
        )
    payload = {
        "system": "pod_removal_001",
        "mute_policy": False,
        "playback": "PLAY",
        "selection": "same football errors as ACCURACY_AUDIT_001; exploratory until a later recording",
        "matcher_rerun": True,
        "ledger_subtraction": False,
        "baseline_reproduced_decisions": True,
        "ranked_pods": [{key: pod[key] for key in ("session", "start", "audit_program_s")} for pod in chosen],
        "v1": {
            "football": {key: v1["football"][key] for key in ("program_seconds_covered", "commercial_seconds_muted", "false_cover_incidents")},
            "redzone": {"program_seconds_covered": v1["redzone"]["program_seconds_covered"]},
        },
        "count10": {
            "football": {key: count10["football"][key] for key in (
                "program_seconds_covered",
                "false_cover_incidents",
                "commercial_seconds_muted",
                "worst_continuous_program_interruption_s",
            )},
            "redzone": {"program_seconds_covered": count10["redzone"]["program_seconds_covered"]},
        },
        "removals": removals,
        "offset_note": note,
        "substantial_program_drop": improved,
        "wall_s": round(time.perf_counter() - started, 1),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    (OUT / "REPORT.md").write_text(render(payload), encoding="utf-8")
    print(json.dumps({
        "top_1": removals["top_1"]["program_seconds_eliminated"],
        "top_5_program": top5["program_seconds_eliminated"],
        "top_5_commercial_lost": top5["commercial_seconds_lost"],
        "top_10": removals["top_10"]["program_seconds_eliminated"],
    }, indent=2))


if __name__ == "__main__":
    main()
