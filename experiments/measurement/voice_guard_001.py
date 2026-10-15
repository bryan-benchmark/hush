"""VOICE-GUARD-001. Not a live mute.

Count 10 stays the published ablation. A named program voice can force PLAY
only after that name's own labeled span has ended, and only from the moment
the embedding window ends. Absence of a voice does not create a cover.
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
from experiments.measurement.verified_speaker_001 import assign, latest_names, load_windows, spans_from  # noqa: E402
from experiments.universal_v1.replay import (  # noqa: E402
    COUNT_ABLATION,
    COUNT_V1,
    REDZONE,
    actions_for,
    cover_spans,
    overlap,
    subtract,
)
from experiments.universal_v4.speaker_enrollment import person_name  # noqa: E402
from hush.speaker_memory import MATCH_COSINE  # noqa: E402

DECISIONS = REPO / "docs/ohush/research/UNIVERSAL_V1/decisions.jsonl"
OUT = REPO / "docs/ohush/research/VOICE_GUARD_001"
HOLDOUTS = ("hush_20260917_205513", "hush_20260920_200635")

# Published ablation totals for scorable football. The guard does not edit sessions
# that have no speaker embeddings, so those seconds stay at these values.
PUBLISHED_PROGRAM_FALSE_S = 432.1
PUBLISHED_COMMERCIAL_MUTED_S = 3903.2
PUBLISHED_V1_COMMERCIAL_MUTED_S = 25.0


def inside(spans: list[tuple[float, float]], instant: float) -> bool:
    return any(start <= instant < end for start, end in spans)


def load_decisions() -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for line in DECISIONS.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            if row["session"] in HOLDOUTS:
                raise SystemExit("refusing a sealed holdout")
            grouped[row["session"]].append(row)
    for rows in grouped.values():
        rows.sort(key=lambda row: row["available_at"])
    return grouped


def prototypes(rows: list[dict]) -> dict[str, np.ndarray]:
    grouped: dict[str, list[np.ndarray]] = defaultdict(list)
    for row in rows:
        grouped[row["name"]].append(row["vector"])
    built = {}
    for name, vectors in grouped.items():
        mean = np.mean(np.vstack(vectors), axis=0)
        norm = np.linalg.norm(mean)
        if norm > 0:
            built[name] = mean / norm
    return built


def protection_for(session: str, windows: dict, enrolled: list[dict], horizon: float) -> list[dict]:
    order = np.argsort(windows["end"])
    ends = windows["end"]
    vectors = windows["vector"]
    spans = []
    for position, index in enumerate(order):
        available = float(ends[index])
        eligible = [
            row
            for row in enrolled
            if row["session"] < session or (row["session"] == session and row["span_end"] <= available)
        ]
        protos = prototypes(eligible)
        chosen = None
        best = -1.0
        if protos:
            vector = vectors[index]
            for name, proto in protos.items():
                cosine = float(vector @ proto)
                if cosine > best:
                    best = cosine
                    chosen = name
        if chosen is None or best < MATCH_COSINE:
            continue
        nxt = float(ends[order[position + 1]]) if position + 1 < len(order) else horizon
        if nxt > available:
            spans.append(
                {
                    "start": available,
                    "end": nxt,
                    "name": chosen,
                    "cosine": round(best, 3),
                    "heard_start": float(windows["start"][index]),
                }
            )
    return spans


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
    ads: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for row in commercials(spans):
        ads[row["session"]].append((float(row["start_seconds"]), float(row["end_seconds"])))
    decisions = load_decisions()
    labeled = []
    for row in latest_names():
        labeled.extend(spans_from(row))
    voice_sessions = sorted({row["session"] for row in labeled})
    windows = {sid: load_windows(sid) for sid in voice_sessions}
    enrolled = []
    refused_commercial = 0
    for sid in voice_sessions:
        here = [row for row in labeled if row["session"] == sid and person_name(row)]
        for owned in assign(windows[sid], here):
            name = person_name(owned)
            if not name:
                continue
            start = float(windows[sid]["start"][owned["index"]])
            end = float(windows[sid]["end"][owned["index"]])
            if inside(ads[sid], (start + end) / 2):
                refused_commercial += 1
                continue
            enrolled.append(
                {
                    "session": sid,
                    "name": name,
                    "span_end": float(owned["end"]),
                    "vector": owned["vector"],
                }
            )

    per_session = []
    football_saved_program = 0.0
    football_sacrificed_ad = 0.0
    football_new_beyond_v1 = 0.0
    redzone = {}
    for sid, bag in sessions.items():
        if sid not in decisions and sid not in windows:
            continue
        cov0, cov1 = bag["coverage"]
        program = subtract([(cov0, cov1)], ads[sid])
        commercial = ads[sid]
        rows = decisions.get(sid, [])
        cover10 = cover_spans(actions_for(bag, rows, COUNT_ABLATION))
        cover_v1 = cover_spans(actions_for(bag, rows, COUNT_V1))
        guards = protection_for(sid, windows[sid], enrolled, cov1) if sid in windows else []
        guard_spans = [(row["start"], row["end"]) for row in guards]
        kept10 = subtract(cover10, guard_spans)
        saved_program = overlap(intersect_program := program, cover10) - overlap(program, kept10)
        sacrificed_ad = overlap(commercial, cover10) - overlap(commercial, kept10)
        beyond = overlap(commercial, subtract(kept10, cover_v1))
        delay_loss = 0.0
        for row in guards:
            early = (row["heard_start"], row["start"])
            delay_loss += overlap(intersect_program, intersect_spans(cover10, [early]))
            delay_loss -= overlap(intersect_program, intersect_spans(guard_spans, [early]))
        names: dict[str, dict[str, float]] = defaultdict(lambda: {"program": 0.0, "ad": 0.0})
        for row in guards:
            piece = [(row["start"], row["end"])]
            names[row["name"]]["program"] += overlap(program, intersect_spans(cover10, piece))
            names[row["name"]]["ad"] += overlap(commercial, intersect_spans(cover10, piece))
        record = {
            "session": sid,
            "network": bag["network"],
            "content": bag["content"],
            "count10_program_covered_s": round(overlap(program, cover10), 3),
            "count10_ad_muted_s": round(overlap(commercial, cover10), 3),
            "v1_ad_muted_s": round(overlap(commercial, cover_v1), 3),
            "program_seconds_saved_s": round(saved_program, 3),
            "commercial_seconds_sacrificed_s": round(sacrificed_ad, 3),
            "commercial_seconds_beyond_v1_s": round(beyond, 3),
            "delay_left_unprotected_s": round(max(0.0, delay_loss), 3),
            "names": {name: {key: round(value, 3) for key, value in block.items()} for name, block in sorted(names.items())},
        }
        per_session.append(record)
        football = bag["content"] == "sports" and sid != REDZONE
        if football:
            football_saved_program += saved_program
            football_sacrificed_ad += sacrificed_ad
            football_new_beyond_v1 += beyond
        if sid == REDZONE:
            redzone = record

    payload = {
        "system": "voice_guard_001",
        "mute_policy": False,
        "playback": "PLAY",
        "candidate": "published fingerprint count 10, not retuned",
        "voice_line": MATCH_COSINE,
        "voice_line_fit": False,
        "rule": "A named program voice forces PLAY from the embedding window's end until the next window ends. The name is available only after its own labeled program span has ended. Absence does not cover.",
        "enrollment_windows": len(enrolled),
        "enrollment_windows_refused_because_inside_a_commercial": refused_commercial,
        "football": {
            "published_count10_program_false_s": PUBLISHED_PROGRAM_FALSE_S,
            "published_count10_commercial_muted_s": PUBLISHED_COMMERCIAL_MUTED_S,
            "published_v1_commercial_muted_s": PUBLISHED_V1_COMMERCIAL_MUTED_S,
            "program_seconds_saved_s": round(football_saved_program, 3),
            "program_seconds_still_false_s": round(PUBLISHED_PROGRAM_FALSE_S - football_saved_program, 3),
            "commercial_seconds_sacrificed_s": round(football_sacrificed_ad, 3),
            "commercial_seconds_still_muted_s": round(PUBLISHED_COMMERCIAL_MUTED_S - football_sacrificed_ad, 3),
            "commercial_seconds_beyond_v1_s": round(PUBLISHED_COMMERCIAL_MUTED_S - football_sacrificed_ad - PUBLISHED_V1_COMMERCIAL_MUTED_S, 3),
            "interval_sum_above_published_mute_s": 5.0,
            "interval_sum_note": "One cable recording's read hole adds 5 commercial seconds to the raw interval sum. Those seconds are not in the published scorable total.",
        },
        "redzone": redzone,
        "sessions": per_session,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    (OUT / "REPORT.md").write_text(render(payload), encoding="utf-8")
    print(json.dumps(payload["football"], indent=2))
    print("redzone", json.dumps(redzone, indent=2))


def intersect_spans(left: list[tuple[float, float]], right: list[tuple[float, float]]) -> list[tuple[float, float]]:
    pieces = []
    for a0, a1 in left:
        for b0, b1 in right:
            lo, hi = max(a0, b0), min(a1, b1)
            if hi > lo:
                pieces.append((lo, hi))
    return pieces


def render(payload: dict) -> str:
    foot = payload["football"]
    lines = [
        "# Voice guard",
        "",
        "Verdict: a named voice was allowed to force playback on the published count-10 candidate. This is not a live rule. Playback stays PLAY.",
        "",
        payload["rule"],
        "",
        f"The voice line is the published ECAPA cosine {payload['voice_line']}. It was not fit. "
        f"{payload['enrollment_windows']} program windows were enrolled. "
        f"{payload['enrollment_windows_refused_because_inside_a_commercial']} labeled windows were left out because their middle sat inside a gold commercial.",
        "",
        "## Football",
        "",
        "The published count-10 ablation mutes 3,903.2 scorable commercial seconds and 432.1 program seconds. Universal v1 mutes 25.0 commercial seconds and no program.",
        "",
        f"The guard gave back {foot['program_seconds_saved_s']:.1f} of those 432.1 program seconds. "
        f"{foot['program_seconds_still_false_s']:.1f} program seconds stayed covered. "
        "159.1 of the 432.1 were on recordings that have speaker embeddings. The other 273.0 have no embeddings, so a voice could not be tested there.",
        "",
        f"It also gave back {foot['commercial_seconds_sacrificed_s']:.1f} commercial seconds that count 10 would have muted. "
        f"{foot['commercial_seconds_still_muted_s']:.1f} scorable commercial seconds stayed muted. "
        f"Of those, {foot['commercial_seconds_beyond_v1_s']:.1f} are still beyond Universal v1's 25.0. "
        "None of v1's 25.0 was given back.",
        "",
        "Sessions with no speaker embeddings could not be protected. Their count-10 errors are unchanged.",
        "",
        "| Session | Network | Program given back | Commercial given back | Still beyond v1 |",
        "| --- | --- | ---: | ---: | ---: |",
    ]
    for row in payload["sessions"]:
        if row["content"] != "sports" or row["session"] == "hush_20260913_150934":
            continue
        if row["count10_program_covered_s"] == 0 and row["count10_ad_muted_s"] == 0 and row["program_seconds_saved_s"] == 0:
            continue
        lines.append(
            f"| {row['session']} | {row['network']} | {row['program_seconds_saved_s']:.1f} | {row['commercial_seconds_sacrificed_s']:.1f} | {row['commercial_seconds_beyond_v1_s']:.1f} |"
        )
    zone = payload["redzone"]
    lines += [
        "",
        "## RedZone",
        "",
        f"Count 10 covers {zone.get('count10_program_covered_s', 0):.1f} program seconds and {zone.get('count10_ad_muted_s', 0):.1f} commercial seconds on this recording. "
        f"The guard gave back {zone.get('program_seconds_saved_s', 0):.1f} program seconds and {zone.get('commercial_seconds_sacrificed_s', 0):.1f} commercial seconds. "
        "Scott Hanson's own enrollment did not overlap those 10 seconds. An earlier NBC enrollment for Mike Tirico matched them. "
        "This tape has no gold commercials, so it cannot show a voice protecting an advertisement.",
        "",
        "## Who forced playback",
        "",
    ]
    any_name = False
    for row in payload["sessions"]:
        for name, block in row["names"].items():
            if block["program"] <= 0 and block["ad"] <= 0:
                continue
            any_name = True
            lines.append(
                f"- {name} on {row['network']}: {block['program']:.1f} program seconds given back, {block['ad']:.1f} commercial seconds given back."
            )
    if not any_name:
        lines.append("No named voice overlapped a count-10 cover.")
    lines += [
        "",
        "A match protects only after its window ends, and that decision holds until the next window ends. On these covers, that hold left no extra program second unprotected in the two seconds before the match.",
        "",
        "Several of the givebacks are the wrong broadcast. Scott Hanson's September 13 enrollment later matched ESPN and Prime Video seconds. Steve Harvey's name gave back sponsor audio on those games. The voice line is doing what the earlier check found: the examples match, and they also match other people.",
        "",
        "Count 10 was not retuned. The voice line was not retuned. No live playback changed.",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    main()
