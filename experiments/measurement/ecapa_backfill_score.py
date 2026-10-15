"""Score the frozen voice guard after the October ECAPA pass.

Count 10 and cosine 0.25 stay published. October recordings have no named
labels, so a new embedding can be protected only by an earlier enrollment.
Absence still does not create a cover. Playback stays PLAY.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from experiments.broadcast_intelligence.batch1 import commercials, coverage, load_catalog  # noqa: E402
from experiments.measurement.verified_speaker_001 import assign, latest_names, load_windows, spans_from  # noqa: E402
from experiments.measurement.voice_guard_001 import (  # noqa: E402
    COUNT_ABLATION,
    COUNT_V1,
    HOLDOUTS,
    PUBLISHED_COMMERCIAL_MUTED_S,
    PUBLISHED_PROGRAM_FALSE_S,
    PUBLISHED_V1_COMMERCIAL_MUTED_S,
    REDZONE,
    inside,
    intersect_spans,
    load_decisions,
    protection_for,
)
from experiments.universal_v1.replay import actions_for, cover_spans, intersect, overlap, subtract  # noqa: E402
from experiments.universal_v4.speaker_enrollment import person_name  # noqa: E402
from hush.speaker_memory import MATCH_COSINE  # noqa: E402

OUT = REPO / "docs/ohush/research/ECAPA_BACKFILL_001"
PRIOR = REPO / "docs/ohush/research/VOICE_GUARD_001/results.json"
EXP = REPO / "experiments/exp002"
BACKFILL = (
    "hush_20261008_205100",
    "hush_20261010_222400",
    "hush_20261011_135700",
    "hush_20261011_204300",
    "hush_20261012_204200",
)


def main() -> None:
    for sid in BACKFILL:
        if not (EXP / sid / "speaker_segments.parquet").exists():
            raise SystemExit(f"missing speaker pass for {sid}")
    prior = json.loads(PRIOR.read_text(encoding="utf-8"))
    prior_by = {row["session"]: row for row in prior["sessions"]}
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
    ads: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for row in commercials(spans):
        ads[row["session"]].append((float(row["start_seconds"]), float(row["end_seconds"])))
    decisions = load_decisions()
    labeled = []
    for row in latest_names():
        labeled.extend(spans_from(row))
    if any(row["session"] in BACKFILL for row in labeled):
        raise SystemExit("an October backfill recording now has a name; that changes enrollment")
    voice_sessions = sorted({row["session"] for row in labeled} | set(BACKFILL))
    windows = {sid: load_windows(sid) for sid in voice_sessions}
    enrolled = []
    refused = 0
    for sid in voice_sessions:
        here = [row for row in labeled if row["session"] == sid and person_name(row)]
        if sid not in windows or not here:
            continue
        for owned in assign(windows[sid], here):
            name = person_name(owned)
            if not name:
                continue
            start = float(windows[sid]["start"][owned["index"]])
            end = float(windows[sid]["end"][owned["index"]])
            if inside(ads[sid], (start + end) / 2):
                refused += 1
                continue
            enrolled.append({"session": sid, "name": name, "span_end": float(owned["end"]), "vector": owned["vector"]})

    per_session = []
    new_program = new_ad = 0.0
    old_program = old_ad = 0.0
    football_incidents_before = football_incidents_after = 0
    backfill_incidents_before = backfill_incidents_after = 0
    football_worst_after = 0.0
    for sid, bag in sessions.items():
        if sid not in decisions and sid not in windows:
            continue
        cov0, cov1 = bag["coverage"]
        program = subtract([(cov0, cov1)], ads[sid])
        rows = decisions.get(sid, [])
        cover10 = cover_spans(actions_for(bag, rows, COUNT_ABLATION))
        cover_v1 = cover_spans(actions_for(bag, rows, COUNT_V1))
        guards = protection_for(sid, windows[sid], enrolled, cov1) if sid in windows else []
        guard_spans = [(row["start"], row["end"]) for row in guards]
        kept10 = subtract(cover10, guard_spans)
        saved_program = overlap(program, cover10) - overlap(program, kept10)
        sacrificed_ad = overlap(ads[sid], cover10) - overlap(ads[sid], kept10)
        before_incidents = intersect(cover10, program)
        after_incidents = intersect(kept10, program)
        names: dict[str, dict[str, float]] = defaultdict(lambda: {"program": 0.0, "ad": 0.0})
        for row in guards:
            piece = [(row["start"], row["end"])]
            names[row["name"]]["program"] += overlap(program, intersect_spans(cover10, piece))
            names[row["name"]]["ad"] += overlap(ads[sid], intersect_spans(cover10, piece))
        record = {
            "session": sid,
            "network": bag["network"],
            "content": bag["content"],
            "backfill": sid in BACKFILL,
            "count10_program_covered_s": round(overlap(program, cover10), 3),
            "count10_ad_muted_s": round(overlap(ads[sid], cover10), 3),
            "v1_ad_muted_s": round(overlap(ads[sid], cover_v1), 3),
            "program_seconds_saved_s": round(saved_program, 3),
            "commercial_seconds_sacrificed_s": round(sacrificed_ad, 3),
            "incidents_before": len(before_incidents),
            "incidents_after": len(after_incidents),
            "worst_interruption_after_s": round(max((end - start for start, end in after_incidents), default=0.0), 3),
            "names": {name: {key: round(value, 3) for key, value in block.items()} for name, block in sorted(names.items()) if block["program"] or block["ad"]},
        }
        per_session.append(record)
        if bag["content"] == "sports" and sid != REDZONE:
            football_incidents_before += len(before_incidents)
            football_incidents_after += len(after_incidents)
            football_worst_after = max(football_worst_after, max((end - start for start, end in after_incidents), default=0.0))
        if sid in BACKFILL:
            new_program += saved_program
            new_ad += sacrificed_ad
            backfill_incidents_before += len(before_incidents)
            backfill_incidents_after += len(after_incidents)
        elif bag["content"] == "sports" and sid != REDZONE:
            old_program += saved_program
            old_ad += sacrificed_ad
        if sid in prior_by and sid not in BACKFILL:
            before = prior_by[sid]
            if abs(before["program_seconds_saved_s"] - record["program_seconds_saved_s"]) > 0.02:
                raise SystemExit(f"{sid} program giveback moved from {before['program_seconds_saved_s']} to {record['program_seconds_saved_s']}")
            if abs(before["commercial_seconds_sacrificed_s"] - record["commercial_seconds_sacrificed_s"]) > 0.02:
                raise SystemExit(f"{sid} commercial giveback moved from {before['commercial_seconds_sacrificed_s']} to {record['commercial_seconds_sacrificed_s']}")

    prior_program = float(prior["football"]["program_seconds_saved_s"])
    prior_commercial = float(prior["football"]["commercial_seconds_sacrificed_s"])
    if abs(old_program - prior_program) > 0.02 or abs(old_ad - prior_commercial) > 0.02:
        raise SystemExit(f"earlier football giveback moved: program {old_program} ad {old_ad}")
    if football_incidents_before != 72:
        raise SystemExit(f"football incidents before the guard were {football_incidents_before}, not 72")
    inaccessible = 273.0
    payload = {
        "system": "ecapa_backfill_001",
        "mute_policy": False,
        "playback": "PLAY",
        "model": "speechbrain/spkrec-ecapa-voxceleb",
        "voice_line": MATCH_COSINE,
        "voice_line_fit": False,
        "count": COUNT_ABLATION,
        "october_labels": 0,
        "enrollment_windows": len(enrolled),
        "enrollment_windows_refused_because_inside_a_commercial": refused,
        "previously_saved_program_s": prior_program,
        "previously_sacrificed_commercial_s": prior_commercial,
        "prior_sessions_unchanged": True,
        "october": {
            "inaccessible_program_s": inaccessible,
            "program_seconds_protected_s": round(new_program, 3),
            "program_seconds_still_unprotected_s": round(inaccessible - new_program, 3),
            "commercial_seconds_exposed_s": round(new_ad, 3),
            "incidents_before": backfill_incidents_before,
            "incidents_after": backfill_incidents_after,
        },
        "football_incidents_before": football_incidents_before,
        "football_incidents_after": football_incidents_after,
        "football_worst_interruption_after_s": round(football_worst_after, 3),
        "football_after": {
            "program_seconds_saved_s": round(old_program + new_program, 3),
            "commercial_seconds_sacrificed_s": round(old_ad + new_ad, 3),
            "program_seconds_still_false_s": round(PUBLISHED_PROGRAM_FALSE_S - old_program - new_program, 3),
            "commercial_seconds_still_muted_s": round(PUBLISHED_COMMERCIAL_MUTED_S - old_ad - new_ad, 3),
            "commercial_seconds_beyond_v1_s": round(
                PUBLISHED_COMMERCIAL_MUTED_S - old_ad - new_ad - PUBLISHED_V1_COMMERCIAL_MUTED_S, 3
            ),
        },
        "sessions": per_session,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    (OUT / "REPORT.md").write_text(render(payload), encoding="utf-8")
    print(json.dumps(payload["october"], indent=2))


def render(payload: dict) -> str:
    october = payload["october"]
    foot = payload["football_after"]
    lines = [
        "# October speaker backfill",
        "",
        "Verdict: the existing ECAPA pass now covers the five recordings that had none. Cosine 0.25 was not moved. Those recordings have no named labels, so only an earlier enrollment can force playback. Playback stays PLAY.",
        "",
        f"Of the {october['inaccessible_program_s']:.1f} false program seconds that had no speaker features, "
        f"{october['program_seconds_protected_s']:.1f} are now given back. "
        f"{october['program_seconds_still_unprotected_s']:.1f} stay covered. "
        f"The same protection gives back {october['commercial_seconds_exposed_s']:.1f} commercial seconds on those recordings. "
        f"Incidents on those recordings go from {october['incidents_before']} to {october['incidents_after']}.",
        "",
        f"The earlier recordings still give back {payload['previously_saved_program_s']:.1f} program seconds and "
        f"{payload['previously_sacrificed_commercial_s']:.1f} commercial seconds. Their rows were checked against the frozen voice-guard result.",
        "",
        f"Together, {foot['program_seconds_saved_s']:.1f} of {PUBLISHED_PROGRAM_FALSE_S:.1f} false program seconds are given back, and "
        f"{foot['commercial_seconds_sacrificed_s']:.1f} commercial seconds are given back. "
        f"{foot['commercial_seconds_still_muted_s']:.1f} scorable commercial seconds stay muted, "
        f"{foot['commercial_seconds_beyond_v1_s']:.1f} of them beyond Universal v1. "
        f"Football incidents go from {payload['football_incidents_before']} to {payload['football_incidents_after']}. "
        f"The longest remaining program interruption is {payload['football_worst_interruption_after_s']:.1f} s.",
        "",
        "Two chunk files were shorter than `session.json`. 144 frames at 48 kHz were filled with silence on the Prime recording, and 16 frames on `hush_20261011_204300`. Later audio was not moved.",
        "",
        "| Session | Network | Count-10 program seconds | Program given back | Commercial given back |",
        "| --- | --- | ---: | ---: | ---: |",
    ]
    for row in payload["sessions"]:
        if not row["backfill"]:
            continue
        lines.append(
            f"| {row['session']} | {row['network']} | {row['count10_program_covered_s']:.1f} | "
            f"{row['program_seconds_saved_s']:.1f} | {row['commercial_seconds_sacrificed_s']:.1f} |"
        )
    lines += ["", "## Who forced playback on the new recordings", ""]
    any_name = False
    for row in payload["sessions"]:
        if not row["backfill"]:
            continue
        for name, block in row["names"].items():
            any_name = True
            lines.append(
                f"- {name} on {row['session']}: {block['program']:.1f} program seconds given back, {block['ad']:.1f} commercial seconds given back."
            )
    if not any_name:
        lines.append("No earlier enrollment overlapped a count-10 cover on these recordings.")
    lines += ["", "Count 10 was not retuned. The voice line was not retuned. No live playback changed.", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    main()
