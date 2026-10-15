"""VOICE-ERROR-RECEIPT-002. Not a mute.

Corrects the speech-overlap sum, checks that the published 27.5 second
giveback is a union, and joins each wrong mute to the fingerprint query
that caused it. No threshold change, no new embedding, no gold edit.
"""

from __future__ import annotations

import csv
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
    REDZONE,
    actions_for,
    cover_spans,
    intersect,
    overlap,
    subtract,
)
from experiments.universal_v4.speaker_enrollment import person_name  # noqa: E402
from hush.audio import find_session, load_session  # noqa: E402
from hush.speaker_memory import MATCH_COSINE  # noqa: E402

DECISIONS = REPO / "docs/ohush/research/UNIVERSAL_V1/decisions.jsonl"
SPEECH_DIR = REPO / "docs/ohush/research/UNIVERSAL_V4_SPEECH_001"
OUT = REPO / "docs/ohush/research/VOICE_ERROR_RECEIPT_002"
HOLDOUTS = ("hush_20260917_205513", "hush_20260920_200635")
RECORDINGS = REPO / "recordings"
BLOCK_S = 90.0
HOP_S = 5.0
NBC = "hush_20260913_210542"
AFTERNOON = "hush_20261011_135700"


def union_seconds(window: tuple[float, float], spans: list[tuple[float, float]]) -> float:
    pieces = intersect([window], spans)
    return sum(right - left for left, right in pieces)


def union_seconds_many(windows: list[tuple[float, float]], spans: list[tuple[float, float]]) -> float:
    return sum(right - left for left, right in intersect(windows, spans))


def gap(a0: float, a1: float, b0: float, b1: float) -> float:
    if a1 <= b0:
        return b0 - a1
    if b1 <= a0:
        return a0 - b1
    return 0.0


def on_block_start(instant: float, origin: float) -> bool:
    relative = instant - origin
    if relative < -1e-6:
        return False
    remainder = relative % BLOCK_S
    return remainder < 1e-3 or BLOCK_S - remainder < 1e-3


def load_speech() -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for path in sorted(SPEECH_DIR.glob("chunks*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            grouped[row["session"]].append(row)
    return grouped


def main() -> None:
    catalog = load_catalog()
    spans = [span for span in coverage() if span["session"] not in HOLDOUTS]
    sessions = {}
    for span in spans:
        sid = span["session"]
        folder = find_session(RECORDINGS, sid)
        info = catalog.get(sid, {})
        sessions[sid] = {
            "dir": folder,
            "meta": load_session(folder),
            "coverage": (float(span["from_seconds"]), float(span["to_seconds"])),
            "network": info.get("network_or_service") or "unknown",
            "content": info.get("content_type") or "",
        }
    ads: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for row in commercials(spans):
        ads[row["session"]].append((float(row["start_seconds"]), float(row["end_seconds"])))
    decisions: dict[str, list[dict]] = defaultdict(list)
    for line in DECISIONS.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            if row["session"] in HOLDOUTS:
                raise SystemExit("refusing a sealed holdout")
            decisions[row["session"]].append(row)
    for rows in decisions.values():
        rows.sort(key=lambda row: row["available_at"])

    labeled = []
    for row in latest_names():
        labeled.extend(spans_from(row))
    windows = {}
    for sid in sorted({row["session"] for row in labeled}):
        try:
            windows[sid] = load_windows(sid)
        except FileNotFoundError:
            continue
    enrolled = []
    for sid, bag in windows.items():
        here = [row for row in labeled if row["session"] == sid and person_name(row)]
        for owned in assign(bag, here):
            name = person_name(owned)
            if not name:
                continue
            win_start = float(bag["start"][owned["index"]])
            win_end = float(bag["end"][owned["index"]])
            midpoint = (win_start + win_end) / 2.0
            if any(left <= midpoint < right for left, right in ads[sid]):
                continue
            enrolled.append(
                {"session": sid, "name": name, "span_end": float(owned["end"]), "vector": owned["vector"]}
            )
    speech = load_speech()
    names_by_session: dict[str, list[dict]] = defaultdict(list)
    for span in labeled:
        if person_name(span):
            names_by_session[span["session"]].append(span)

    rows_out = []
    redzone_guards = []
    summed = defaultdict(float)
    united = defaultdict(float)
    for sid, bag in sessions.items():
        cov0, cov1 = bag["coverage"]
        program = subtract([(cov0, cov1)], ads[sid])
        covers = cover_spans(actions_for(bag, decisions.get(sid, []), COUNT_ABLATION))
        pieces = intersect(covers, program)
        speech_spans = []
        if sid in windows:
            speech_spans = list(zip(windows[sid]["start"].tolist(), windows[sid]["end"].tolist()))
        guards = protection_for(sid, windows[sid], enrolled, cov1) if sid in windows else []
        guard_spans = [(row["start"], row["end"]) for row in guards]
        kind = "redzone" if sid == REDZONE else "football" if bag["content"] == "sports" else "scripted"
        saved_union = overlap(program, covers) - overlap(program, subtract(covers, guard_spans))
        if kind == "football":
            united["football_guard_union"] += saved_union
        for index, (left, right) in enumerate(pieces, start=1):
            raw_speech = overlap([(left, right)], speech_spans) if speech_spans else 0.0
            union_speech = union_seconds((left, right), speech_spans) if speech_spans else 0.0
            raw_named = overlap([(left, right)], guard_spans)
            union_named = union_seconds((left, right), guard_spans)
            summed[kind] += raw_speech
            united[kind] += union_speech
            hop_rows = []
            bag_rows = decisions.get(sid, [])
            for position, row in enumerate(bag_rows):
                start = float(row["available_at"])
                end = cov1 if position + 1 == len(bag_rows) else float(bag_rows[position + 1]["available_at"])
                if end <= left or start >= right:
                    continue
                if row["score"] < COUNT_ABLATION or row["same_session"]:
                    continue
                query_t0 = float(row["query_t0"])
                hop_rows.append(
                    {
                        "query_t0": query_t0,
                        "query_t1": float(row["query_t1"]),
                        "available_at": start,
                        "score": int(row["score"]),
                        "n_hashes": int(row["n_hashes"]),
                        "ref_session": row["ref_session"],
                        "ref_start": row["ref_start"],
                        "block_start": on_block_start(query_t0, cov0),
                        "seconds_into_block": round((query_t0 - cov0) % BLOCK_S, 3),
                    }
                )
            nearest = None
            for a0, a1 in ads[sid]:
                distance = gap(left, right, a0, a1)
                nearest = distance if nearest is None else min(nearest, distance)
            quoted = []
            for chunk in speech.get(sid, []):
                if float(chunk["t1"]) <= left - HOP_S or float(chunk["t0"]) >= right:
                    continue
                text = " ".join((chunk.get("text") or "").split())
                if text:
                    quoted.append(f"{float(chunk['t0']):.0f}-{float(chunk['t1']):.0f} {text}")
            named_here = sorted(
                {
                    person_name(span)
                    for span in names_by_session.get(sid, [])
                    if union_seconds((left - HOP_S, right), [(span["start"], span["end"])]) > 0
                }
            )
            if kind == "redzone":
                for guard in guards:
                    if union_seconds((left, right), [(guard["start"], guard["end"])]) <= 0:
                        continue
                    redzone_guards.append(
                        {
                            "incident_start": left,
                            "incident_end": right,
                            "name": guard["name"],
                            "cosine": guard["cosine"],
                            "embedding_window_start": guard["heard_start"],
                            "embedding_window_end": guard["start"],
                            "protection_end": guard["end"],
                            "embedding_overlaps_incident": union_seconds(
                                (left, right), [(guard["heard_start"], guard["start"])]
                            )
                            > 0,
                            "protection_overlaps_incident_s": round(
                                union_seconds((left, right), [(guard["start"], guard["end"])]), 3
                            ),
                        }
                    )
            rows_out.append(
                {
                    "population": kind,
                    "session": sid,
                    "network": bag["network"],
                    "incident": index,
                    "start_s": round(left, 3),
                    "end_s": round(right, 3),
                    "seconds": round(right - left, 3),
                    "embedded_speech_summed_s": round(raw_speech, 3),
                    "embedded_speech_union_s": round(union_speech, 3),
                    "named_match_summed_s": round(raw_named, 3),
                    "named_match_union_s": round(union_named, 3),
                    "speech_sum_exceeded_incident": raw_speech > (right - left) + 1e-6,
                    "queries": len(hop_rows),
                    "all_queries_at_block_start": bool(hop_rows) and all(row["block_start"] for row in hop_rows),
                    "scores": ",".join(str(row["score"]) for row in hop_rows),
                    "refs": ";".join(
                        f"{row['ref_session']}@{row['ref_start']}" for row in hop_rows
                    ),
                    "seconds_into_block": ",".join(str(row["seconds_into_block"]) for row in hop_rows),
                    "nearest_gold_commercial_s": None if nearest is None else round(nearest, 3),
                    "saved_names_overlapping": "|".join(name for name in named_here if name),
                    "transcript": " | ".join(quoted),
                    "hops": hop_rows,
                }
            )

    hold = {"football_in_window_s": 0.0, "football_held_forward_s": 0.0}
    for sid, bag in sessions.items():
        if bag["content"] != "sports" or sid == REDZONE or sid not in windows:
            continue
        cov0, cov1 = bag["coverage"]
        program = subtract([(cov0, cov1)], ads[sid])
        covers = cover_spans(actions_for(bag, decisions.get(sid, []), COUNT_ABLATION))
        false_program = intersect(covers, program)
        guards = protection_for(sid, windows[sid], enrolled, cov1)
        heard = [(row["heard_start"], row["start"]) for row in guards]
        held = [(row["start"], row["end"]) for row in guards]
        hold["football_in_window_s"] += union_seconds_many(false_program, heard)
        hold["football_held_forward_s"] += union_seconds_many(false_program, held)

    rates = {}
    for sid in (AFTERNOON, NBC):
        bag = sessions[sid]
        cov0, cov1 = bag["coverage"]
        program = subtract([(cov0, cov1)], ads[sid])
        rows = decisions.get(sid, [])
        counts = {"block_queries_on_program": 0, "block_hits": 0, "other_queries_on_program": 0, "other_hits": 0}
        for position, row in enumerate(rows):
            start = float(row["available_at"])
            end = cov1 if position + 1 == len(rows) else float(rows[position + 1]["available_at"])
            if overlap([(start, end)], program) <= 0:
                continue
            hit = row["score"] >= COUNT_ABLATION and not row["same_session"]
            if on_block_start(float(row["query_t0"]), cov0):
                counts["block_queries_on_program"] += 1
                counts["block_hits"] += int(hit)
            else:
                counts["other_queries_on_program"] += 1
                counts["other_hits"] += int(hit)
        rates[sid] = counts

    counterfactual = {}
    for sid, bag in sessions.items():
        if bag["content"] != "sports" or sid == REDZONE:
            continue
        cov0, cov1 = bag["coverage"]
        program = subtract([(cov0, cov1)], ads[sid])
        commercial = ads[sid]
        covers = cover_spans(actions_for(bag, decisions.get(sid, []), COUNT_ABLATION))
        kept_rows = []
        bag_rows = decisions.get(sid, [])
        for row in bag_rows:
            if on_block_start(float(row["query_t0"]), cov0):
                kept_rows.append({**row, "score": 0})
            else:
                kept_rows.append(row)
        kept = cover_spans(actions_for(bag, kept_rows, COUNT_ABLATION))
        counterfactual[sid] = {
            "program_seconds_no_longer_covered": round(overlap(program, covers) - overlap(program, kept), 3),
            "commercial_seconds_no_longer_covered": round(overlap(commercial, covers) - overlap(commercial, kept), 3),
        }
    counterfactual_totals = {
        "program_seconds_no_longer_covered": round(
            sum(row["program_seconds_no_longer_covered"] for row in counterfactual.values()), 3
        ),
        "commercial_seconds_no_longer_covered": round(
            sum(row["commercial_seconds_no_longer_covered"] for row in counterfactual.values()), 3
        ),
        "note": "Diagnostic only. Queries that start on a 90-second fingerprint read are ignored. Count 10 is not changed.",
    }

    football = [row for row in rows_out if row["population"] == "football"]
    afternoon = [row for row in football if row["session"] == AFTERNOON]
    nbc = [row for row in football if row["session"] == NBC]
    block_rows = [row for row in football if row["all_queries_at_block_start"]]
    payload = {
        "system": "voice_error_receipt_002",
        "mute_policy": False,
        "playback": "PLAY",
        "match_line": MATCH_COSINE,
        "match_line_fit": False,
        "embeddings_computed": False,
        "gold_edited": False,
        "holdouts_opened": False,
        "speech_accounting": {
            "note": "Summed overlap counts the same second once per embedding window. Union clips each window to the incident and merges overlaps.",
            "football_embedded_speech_summed_s": round(summed["football"], 3),
            "football_embedded_speech_union_s": round(united["football"], 3),
            "football_named_match_union_via_subtract_s": round(united["football_guard_union"], 3),
            "published_named_match_s": 27.506,
            "incidents_where_summed_speech_exceeded_duration": sum(
                1 for row in football if row["speech_sum_exceeded_incident"]
            ),
            "football_named_match_inside_embedding_window_s": round(hold["football_in_window_s"], 3),
            "football_named_match_held_until_next_window_s": round(hold["football_held_forward_s"], 3),
        },
        "program_query_hit_rates": rates,
        "ignore_block_start_queries_diagnostic": {
            "totals": counterfactual_totals,
            "afternoon": counterfactual[AFTERNOON],
            "sessions": counterfactual,
        },
        "block_pattern": {
            "block_s": BLOCK_S,
            "hop_s": HOP_S,
            "football_incidents": len(football),
            "football_incidents_whose_every_query_starts_on_a_90s_block": len(block_rows),
            "football_seconds_in_those_incidents": round(sum(row["seconds"] for row in block_rows), 3),
            "afternoon_incidents": len(afternoon),
            "afternoon_incidents_on_block_start": sum(1 for row in afternoon if row["all_queries_at_block_start"]),
            "afternoon_seconds_on_block_start": round(
                sum(row["seconds"] for row in afternoon if row["all_queries_at_block_start"]), 3
            ),
        },
        "redzone_guard_windows": redzone_guards,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "summary.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    (OUT / "redzone_guards.json").write_text(json.dumps(redzone_guards, indent=2) + "\n", encoding="utf-8")
    fieldnames = [key for key in rows_out[0].keys() if key != "hops"]
    with (OUT / "per_incident.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows_out:
            writer.writerow({key: row[key] for key in fieldnames})
    with (OUT / "queries.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows_out:
            handle.write(
                json.dumps(
                    {
                        "session": row["session"],
                        "incident": row["incident"],
                        "start_s": row["start_s"],
                        "hops": row["hops"],
                    }
                )
                + "\n"
            )
    print(json.dumps(payload["speech_accounting"], indent=2))
    print(json.dumps(payload["block_pattern"], indent=2))
    print("afternoon")
    for row in afternoon:
        print(
            row["start_s"],
            row["seconds"],
            row["all_queries_at_block_start"],
            row["scores"],
            row["seconds_into_block"],
            row["nearest_gold_commercial_s"],
            row["refs"][:80],
        )
    print("nbc")
    for row in nbc:
        print(
            row["incident"],
            row["start_s"],
            row["seconds"],
            "speech",
            row["embedded_speech_summed_s"],
            "->",
            row["embedded_speech_union_s"],
            "named",
            row["named_match_union_s"],
            "names",
            row["saved_names_overlapping"] or "-",
            "gold",
            row["nearest_gold_commercial_s"],
            "block",
            row["all_queries_at_block_start"],
            "text",
            (row["transcript"][:180] or "-"),
        )


if __name__ == "__main__":
    main()
