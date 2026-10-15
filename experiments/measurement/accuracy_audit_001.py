"""Phase-0 accuracy audit. No new model and no mute.

Count 10 and the voice guard are replayed from the saved query log.
The alignment offset inside a reference pod was not saved, so this audit
names the pod and does not claim which seconds inside it matched.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from experiments.broadcast_intelligence.batch1 import commercials, coverage, load_catalog  # noqa: E402
from experiments.measurement.verified_speaker_001 import assign, latest_names, load_windows, spans_from  # noqa: E402
from experiments.measurement.voice_guard_001 import protection_for  # noqa: E402
from experiments.universal_v1.replay import (  # noqa: E402
    COUNT_ABLATION,
    COUNT_V1,
    REDZONE,
    actions_for,
    cover_spans,
    intersect,
    overlap,
    subtract,
)
from experiments.universal_v4.speaker_enrollment import person_name  # noqa: E402
from hush.audio import find_session  # noqa: E402

DECISIONS = REPO / "docs/ohush/research/UNIVERSAL_V1/decisions.jsonl"
RECEIPTS = REPO / "docs/ohush/research/UNIVERSAL_V1/receipts.jsonl"
RECORDINGS = REPO / "recordings"
EXP = REPO / "experiments/exp002"
OUT = REPO / "docs/ohush/research/ACCURACY_AUDIT_001"
HOLDOUTS = ("hush_20260917_205513", "hush_20260920_200635")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def pieces(left, right):
    found = []
    for a0, a1 in left:
        for b0, b1 in right:
            lo, hi = max(a0, b0), min(a1, b1)
            if hi > lo:
                found.append((lo, hi))
    return found


def load_decisions():
    grouped = defaultdict(list)
    for line in DECISIONS.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row["session"] in HOLDOUTS:
            raise SystemExit("refusing a sealed holdout")
        grouped[row["session"]].append(row)
    for rows in grouped.values():
        rows.sort(key=lambda row: row["available_at"])
    return grouped


def recording_present(session: str) -> bool:
    try:
        find_session(RECORDINGS, session)
    except RuntimeError:
        return False
    return True


def main() -> None:
    catalog = load_catalog()
    spans = coverage()
    sessions = {}
    for span in spans:
        sid = span["session"]
        if sid in HOLDOUTS:
            raise SystemExit("refusing a sealed holdout")
        info = catalog.get(sid, {})
        sessions[sid] = {
            "coverage": (float(span["from_seconds"]), float(span["to_seconds"])),
            "network": info.get("network_or_service") or "unknown",
            "content": info.get("content_type") or "",
        }
    ads = defaultdict(list)
    pods = []
    for row in commercials(spans):
        start, end = float(row["start_seconds"]), float(row["end_seconds"])
        ads[row["session"]].append((start, end))
        pods.append({"session": row["session"], "start": start, "end": end})
    decisions = load_decisions()
    labeled = []
    for row in latest_names():
        labeled.extend(spans_from(row))
    voice_sessions = sorted({row["session"] for row in labeled})
    windows = {sid: load_windows(sid) for sid in voice_sessions}
    enrolled = []
    homes = defaultdict(set)
    for sid in voice_sessions:
        here = [row for row in labeled if row["session"] == sid and person_name(row)]
        for owned in assign(windows[sid], here):
            name = person_name(owned)
            if not name:
                continue
            start = float(windows[sid]["start"][owned["index"]])
            end = float(windows[sid]["end"][owned["index"]])
            if any(a0 <= (start + end) / 2 < a1 for a0, a1 in ads[sid]):
                continue
            enrolled.append({"session": sid, "name": name, "span_end": float(owned["end"]), "vector": owned["vector"]})
            homes[name].add(sid)

    incident_rows = []
    coverage_rows = []
    guard_rows = []
    football_program = 0.0
    football_incidents = 0
    for sid, bag in sorted(sessions.items()):
        if bag["content"] != "sports":
            continue
        cov0, cov1 = bag["coverage"]
        program = subtract([(cov0, cov1)], ads[sid])
        rows = decisions.get(sid, [])
        covers = cover_spans(actions_for(bag, rows, COUNT_ABLATION))
        incidents = intersect(covers, program)
        if sid != REDZONE:
            football_program += sum(end - start for start, end in incidents)
            football_incidents += len(incidents)
        has_embed = (EXP / sid / "speaker_segments.parquet").exists()
        false_s = sum(end - start for start, end in incidents)
        coverage_rows.append(
            {
                "session": sid,
                "network": bag["network"],
                "in_football_432": sid != REDZONE,
                "false_program_s": round(false_s, 3),
                "embedding_parquet": has_embed,
                "recording_present": recording_present(sid),
                "root_cause": "embeddings present" if has_embed else "Exp002 speaker pass was not run; recording is a separate question",
            }
        )
        queries = []
        for index, row in enumerate(rows):
            start = row["available_at"]
            end = cov1 if index + 1 == len(rows) else rows[index + 1]["available_at"]
            if row["score"] >= COUNT_ABLATION and not row["same_session"] and row.get("ref_session"):
                queries.append((start, end, row))
        for number, (left, right) in enumerate(incidents, start=1):
            for q0, q1, row in queries:
                seconds = max(0.0, min(right, q1) - max(left, q0))
                if seconds <= 0:
                    continue
                ref = next((pod for pod in pods if pod["session"] == row["ref_session"] and abs(pod["start"] - float(row["ref_start"])) < 0.01), None)
                incident_rows.append(
                    {
                        "population": "redzone" if sid == REDZONE else "football",
                        "incident": f"{sid}:{number}",
                        "session": sid,
                        "network": bag["network"],
                        "incident_start": round(left, 3),
                        "incident_end": round(right, 3),
                        "ref_session": row["ref_session"],
                        "ref_start": row["ref_start"],
                        "ref_end": None if ref is None else round(ref["end"], 3),
                        "query_t0": row["query_t0"],
                        "query_t1": row["query_t1"],
                        "available_at": row["available_at"],
                        "score": row["score"],
                        "program_seconds": round(seconds, 3),
                        "match_offset_inside_reference": None,
                    }
                )
        if sid in windows:
            for guard in protection_for(sid, windows[sid], enrolled, cov1):
                piece = [(guard["start"], guard["end"])]
                program_s = overlap(program, pieces(covers, piece))
                ad_s = overlap(ads[sid], pieces(covers, piece))
                if program_s <= 0 and ad_s <= 0:
                    continue
                same = sid in homes[guard["name"]]
                guard_rows.append(
                    {
                        "session": sid,
                        "network": bag["network"],
                        "name": guard["name"],
                        "start": round(guard["start"], 3),
                        "end": round(guard["end"], 3),
                        "cosine": guard["cosine"],
                        "program_seconds": round(program_s, 3),
                        "ad_seconds": round(ad_s, 3),
                        "enrolled_on": sorted(homes[guard["name"]]),
                        "relation": "same_recording" if same else "other_recording",
                        "gold": "both" if program_s > 0 and ad_s > 0 else "program" if program_s > 0 else "ad",
                    }
                )

    if abs(football_program - 432.1) > 0.2 or football_incidents != 72:
        raise SystemExit(f"football incidents did not reproduce: {football_incidents} incidents, {football_program:.3f}s")

    OUT.mkdir(parents=True, exist_ok=True)
    write_csv(OUT / "false_incidents_by_reference.csv", incident_rows)
    write_csv(OUT / "missing_embedding_seconds.csv", coverage_rows)
    write_csv(OUT / "guard_match_cases.csv", guard_rows)
    summary = summarize(incident_rows, coverage_rows, guard_rows)
    (OUT / "FRONTIER.json").write_text(json.dumps(frontier(summary), indent=2) + "\n", encoding="utf-8")
    (OUT / "A_FALSE_REFERENCE_AUDIT.md").write_text(audit_md(summary), encoding="utf-8")
    (OUT / "B_FEATURE_COVERAGE.md").write_text(coverage_md(summary), encoding="utf-8")
    (OUT / "C_VOICE_GUARD_ATTRIBUTION.md").write_text(guard_md(summary), encoding="utf-8")
    (OUT / "NEXT_CHOICE.md").write_text(choice_md(summary), encoding="utf-8")
    (OUT / "receipts.json").write_text(json.dumps(receipt_payload(summary), indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"incidents": football_incidents, "program_s": round(football_program, 3), "top_share": summary["top5_share"]}, indent=2))


def write_csv(path: Path, rows: list[dict]) -> None:
    import csv

    fields = list(rows[0]) if rows else ["empty"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def summarize(incidents, coverage_rows, guard_rows) -> dict:
    football = [row for row in incidents if row["population"] == "football"]
    by_ref = defaultdict(float)
    by_incident_refs = defaultdict(set)
    for row in football:
        key = (row["ref_session"], row["ref_start"])
        by_ref[key] += row["program_seconds"]
        by_incident_refs[row["incident"]].add(key)
    ranked = sorted(by_ref.items(), key=lambda item: -item[1])
    total = sum(by_ref.values())
    def share(n):
        return sum(seconds for _key, seconds in ranked[:n])
    missing = [row for row in coverage_rows if row["in_football_432"] and not row["embedding_parquet"]]
    present = [row for row in coverage_rows if row["in_football_432"] and row["embedding_parquet"]]
    relation = defaultdict(lambda: {"program": 0.0, "ad": 0.0})
    for row in guard_rows:
        if row["session"] == REDZONE:
            bucket = relation["redzone_" + row["relation"]]
        else:
            bucket = relation[row["relation"] + "_" + row["gold"]]
        bucket["program"] += row["program_seconds"]
        bucket["ad"] += row["ad_seconds"]
    return {
        "ranked": [{"ref_session": key[0], "ref_start": key[1], "program_seconds": round(seconds, 3)} for key, seconds in ranked],
        "total_attributed_s": round(total, 3),
        "n_refs": len(ranked),
        "n_incidents": len({row["incident"] for row in football}),
        "top1_s": round(share(1), 3),
        "top5_s": round(share(5), 3),
        "top10_s": round(share(10), 3),
        "top5_share": round(share(5) / total, 3) if total else None,
        "top10_share": round(share(10) / total, 3) if total else None,
        "incidents_with_multiple_refs": sum(1 for refs in by_incident_refs.values() if len(refs) > 1),
        "missing": missing,
        "present": present,
        "missing_s": round(sum(round(row["false_program_s"], 1) for row in missing), 1),
        "present_s": round(sum(round(row["false_program_s"], 1) for row in present), 1),
        "relation": {key: {name: round(value, 3) for name, value in block.items()} for key, block in relation.items()},
        "guard_rows": len(guard_rows),
    }


def frontier(summary) -> dict:
    return {
        "denominator": {
            "scorable_football_commercial_s": 17555.7,
            "football_program_seconds_published_18_73h": 67428,
            "note": "18.73 hours times 3600 is 67428. The scorable program total used with read holes removed is 67560.4 in the v2 gate.",
        },
        "universal_v1": {"commercial_muted_s": 25.0, "program_false_s": 0.0, "incidents": 0, "redzone_program_false_s": 0.0},
        "count_10": {"commercial_muted_s": 3903.2, "program_false_s": 432.1, "incidents": summary["n_incidents"], "redzone_program_false_s": 10.0},
        "count_10_plus_voice_guard": {
            "commercial_muted_s": 3814.306,
            "program_false_s": 404.594,
            "incidents": None,
            "incidents_note": "The guard report did not republish the incident count. This audit does not invent one.",
            "redzone_program_false_s": 0.0,
            "redzone_note": "The 10.0 RedZone seconds were forced to play by a Mike Tirico match, not by Scott Hanson.",
        },
    }


def audit_md(summary) -> str:
    lines = [
        "# False-reference audit",
        "",
        "The local `decisions.jsonl` is not empty. Each count-10 cover names a reference pod through `ref_session` and `ref_start`. The alignment offset inside that pod was computed by `best_match` and then discarded. It is not in `decisions.jsonl` or `receipts.jsonl`. `receipts.jsonl` is the count-200 action log, 9.2 MB locally, and its fingerprint block also has no interior offset.",
        "",
        f"Football reproduced {summary['n_incidents']} incidents. The raw program-second sum is {summary['total_attributed_s']:.3f}, which is the published 432.1 after each session is rounded to a tenth.",
        "",
        f"They point at {summary['n_refs']} earlier commercial pods. {summary['incidents_with_multiple_refs']} incidents touch more than one pod. "
        f"The largest pod accounts for {summary['top1_s']:.1f} seconds. The top 5 account for {summary['top5_s']:.1f} seconds ({summary['top5_share']:.0%}). The top 10 account for {summary['top10_s']:.1f} seconds ({summary['top10_share']:.0%}).",
        "",
        "That is concentration across whole pods. It is not evidence that the match landed on a bumper, a promo, or reused program audio. The interior offset is the missing measurement, so this audit stops before that claim.",
        "",
        "| Rank | Reference session | Pod start | Program seconds |",
        "| ---: | --- | ---: | ---: |",
    ]
    for rank, row in enumerate(summary["ranked"][:10], start=1):
        lines.append(f"| {rank} | {row['ref_session']} | {row['ref_start']} | {row['program_seconds']:.1f} |")
    lines += ["", "Every query that contributes to an incident is in `false_incidents_by_reference.csv`. `match_offset_inside_reference` is null on every row.", ""]
    return "\n".join(lines)


def coverage_md(summary) -> str:
    lines = [
        "# Speaker-embedding coverage of the false program seconds",
        "",
        f"Of the 432.1 false program seconds, {summary['present_s']:.1f} are on recordings whose Exp002 embedding parquet exists. {summary['missing_s']:.1f} are on recordings with no speaker pass.",
        "",
        "The missing recordings are still on disk. The embeddings were not extracted. This is not a read hole and not a clock mismatch.",
        "",
        "| Session | Network | False program seconds | Embeddings | Recording present |",
        "| --- | --- | ---: | --- | --- |",
    ]
    for row in summary["missing"] + summary["present"]:
        lines.append(
            f"| {row['session']} | {row['network']} | {row['false_program_s']:.1f} | {row['embedding_parquet']} | {row['recording_present']} |"
        )
    lines.append("")
    return "\n".join(lines)


def guard_md(summary) -> str:
    relation = summary["relation"]
    lines = [
        "# Voice-guard attribution",
        "",
        "A second is credited to the name whose match forced playback, and only where that interval overlaps a count-10 cover. Same recording means this broadcast contains a program enrollment for that name. Other recording means the name was enrolled on a different tape.",
        "",
        "Each row is one name on one recording.",
        "",
    ]
    for key in sorted(relation):
        block = relation[key]
        lines.append(f"- {key}: {block['program']:.1f} program seconds, {block['ad']:.1f} commercial seconds.")
    lines += [
        "",
        "The RedZone 10.0 program seconds are in the `redzone_other_recording` row. That match is Mike Tirico, enrolled on an earlier NBC tape. Scott Hanson was not the name on those seconds.",
        "",
        "Case rows are in `guard_match_cases.csv`.",
        "",
    ]
    return "\n".join(lines)


def choice_md(summary) -> str:
    return "\n".join(
        [
            "# Next choice",
            "",
            "Neither EX-A nor EX-B is justified as the next experiment.",
            "",
            f"The largest measured pile is the {summary['missing_s']:.1f} false program seconds on tapes that never received a speaker pass. Running a new voice model, or a source-aware guard, cannot see those seconds until the existing ECAPA pass exists for them. That extraction is not EX-B, and it is not authorized by this audit.",
            "",
            f"The pod ranking is real: the top 10 earlier commercials account for {summary['top10_share']:.0%} of the 432.1 seconds. EX-A would rebuild the library at creative level. The match offset inside each pod was not saved, so this audit cannot tell a contaminated bumper from a genuine ad that happens to resemble the program. Rebuilding the library before that offset exists would spend the experiment on an untested cause.",
            "",
            "The justified next measurement, when authorized, is to replay the frozen count-10 queries and keep the alignment offset `best_match` already computes. No new threshold, no new model, and no claim about the interior of a pod until those offsets are on disk.",
            "",
            "Playback stays play. Universal v1 stays the baseline. Count 10 stays an ablation.",
            "",
        ]
    )


def receipt_payload(summary) -> dict:
    return {
        "git_head": "18c7179cfd0df1e4776f0d5b3bc25c30d25e8cff",
        "decisions_sha256": sha256(DECISIONS),
        "receipts_sha256": sha256(RECEIPTS),
        "receipts_bytes": RECEIPTS.stat().st_size,
        "receipts_are_count": COUNT_V1,
        "ablation_count": COUNT_ABLATION,
        "voice_line": 0.25,
        "voice_line_fit": False,
        "match_offset_saved": False,
        "holdouts_opened": False,
        "gold_edited": False,
        "playback": "PLAY",
        "clock": "recording seconds; a cover starts at available_at, which is the end of the 5-second query",
        "holes": "Football incident total reproduced at 432.1 seconds and 72 incidents without subtracting read holes, so those holes do not sit inside the false program intervals.",
        "top5_share": summary["top5_share"],
        "missing_embedding_s": summary["missing_s"],
    }


if __name__ == "__main__":
    main()
