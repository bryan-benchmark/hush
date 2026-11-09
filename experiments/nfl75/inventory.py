"""Where each recording sits for NFL75. Reads gold. Does not open sealed audio."""

from __future__ import annotations

import json
from pathlib import Path

from experiments.ledger import GOLD, TRUTH_PATH, read_jsonl, resolve_ledger, sha256_file
from experiments.measurement.metrics import Interval, target_commercials

from tools.gpu_lab.splits import (
    CALIBRATE,
    CONTROL,
    DEVELOP,
    HOLDOUTS,
    OUT_OF_SCOPE,
    TRAIN,
)

from tools.gpu_lab.eligibility import gap_around, load_probes

from experiments.nfl75.score import always_play, score_product


def excluded_ranges(session: str, intervals: list[Interval]) -> list[tuple[float, float]]:
    """Unmarked spots already named by the eligibility probes. Not a relabel."""
    commercials = target_commercials(intervals)
    ranges = []
    for probe in load_probes():
        if probe["session"] != session:
            continue
        start, end = gap_around(commercials, float(probe["probe_seconds"]))
        ranges.append((start, end))
    return ranges

REPO = Path(__file__).resolve().parents[2]
CAUSAL_AVAILABILITY = REPO / "docs/ohush/research/FINGERPRINT_CAUSAL_STREAM_001/causal_availability.jsonl"
PUBLISHED_DECISIONS = REPO / "docs/ohush/research/UNIVERSAL_V1/decisions.jsonl"
LIVE_LABELS = GOLD / "live_label_sessions.json"

# Names are the ones already written in STATUS.md, HANDOFF.md, and live_label_sessions.json.
BROADCAST = {
    "hush_20261008_205100": ("Prime Video", "Thursday Night Football", "2026-10-08"),
    "hush_20260924_220624": ("Prime Video", "Prime football", "2026-09-24"),
    "hush_20260909_213047": ("NBC", "football", "2026-09-09"),
    "hush_20260913_210542": ("NBC", "football", "2026-09-13"),
    "hush_20260914_212529": ("ESPN", "football", "2026-09-14"),
    "hush_20260913_150934": ("FOX", "RedZone", "2026-09-13"),
    "hush_20261010_222400": ("Cable", "Saturday football", "2026-10-10"),
    "hush_20261011_135700": ("Cable", "Sunday afternoon", "2026-10-11"),
    "hush_20261011_204300": ("Cable", "Sunday night", "2026-10-11"),
    "hush_20261012_204200": ("Cable", "Monday Night Football", "2026-10-12"),
    "hush_20260827_135935": ("Hulu", "scripted", "2026-08-27"),
    "hush_20261007_220650": ("Hulu", "scripted", "2026-10-07"),
    "hush_20260921_204539": ("ESPN", "unlabeled", "2026-09-21"),
    "hush_20261004_204010": ("NBC", "unlabeled", "2026-10-04"),
    "hush_20260910_205330": ("Netflix", "unlabeled", "2026-09-10"),
}

# October was already inspected. The supervised head was fit on TRAIN.
# ESPN selected the fingerprint operating count. None of these are an untouched exam.
INSPECTED = set(TRAIN + CALIBRATE + DEVELOP + CONTROL + OUT_OF_SCOPE)

PRIME_DEV = ("hush_20261008_205100", "hush_20260924_220624")

UNLABELED = (
    "hush_20260921_204539",
    "hush_20261004_204010",
    "hush_20260910_205330",
)


def _role(session: str) -> str:
    if session in HOLDOUTS:
        return "sealed"
    if session in PRIME_DEV:
        return "development_prime"
    if session in UNLABELED:
        return "unlabeled_not_an_exam_set"
    if session in INSPECTED:
        return "development_other"
    return "unlisted"


def _split(session: str) -> str:
    if session in TRAIN:
        return "train"
    if session in CALIBRATE:
        return "calibrate"
    if session in DEVELOP:
        return "develop"
    if session in CONTROL:
        return "control"
    if session in OUT_OF_SCOPE:
        return "out_of_scope"
    if session in HOLDOUTS:
        return "sealed_holdout"
    return "none"


def active_intervals(session: str) -> list[Interval]:
    raw = read_jsonl(TRUTH_PATH)
    if any(row.get("session") in HOLDOUTS for row in raw):
        raise RuntimeError("sealed holdout is named in the truth ledger")
    superseded = {row["supersedes"] for row in raw if row.get("supersedes")}
    intervals = []
    for row in resolve_ledger(raw, "gold_id"):
        if row.get("session") != session:
            continue
        if row.get("retracted") or row.get("event") == "retracted":
            continue
        if row.get("gold_id") in superseded:
            continue
        if "start_seconds" not in row or "end_seconds" not in row:
            continue
        intervals.append(
            Interval(
                start=float(row["start_seconds"]),
                end=float(row["end_seconds"]),
                event_class=str(row.get("event_class") or ""),
                desired_action=str(row.get("desired_action") or ""),
                confidence=str(row.get("confidence") or ""),
            )
        )
    return intervals


def coverage_by_session() -> dict[str, tuple[float, float]]:
    found: dict[str, tuple[float, float]] = {}
    for name in ("GOLD_DATASET_20261013.json", "GOLD_DEV_V1.json", "GOLD_REPLICATION_V1.json"):
        doc = json.loads((GOLD / name).read_text(encoding="utf-8"))
        for row in doc["coverage"]:
            if not row.get("fully_annotated"):
                continue
            session = row["session"]
            if session in HOLDOUTS:
                raise RuntimeError(f"sealed holdout {session} has coverage")
            span = (float(row["from_seconds"]), float(row["to_seconds"]))
            if session in found and found[session] != span:
                raise RuntimeError(f"{session} has two different coverage spans")
            found[session] = span
    return found


def wall_gaps() -> dict[str, float]:
    if not LIVE_LABELS.exists():
        return {}
    doc = json.loads(LIVE_LABELS.read_text(encoding="utf-8"))
    totals = {}
    for sitting in doc.get("sittings", []):
        totals[sitting["session"]] = sum(float(gap["wall_gap_s"]) for gap in sitting.get("gaps", []))
    return totals


def feature_status() -> dict:
    recordings = REPO / "recordings"
    return {
        "recordings_present": recordings.exists() and any(recordings.glob("*/*")),
        "published_universal_v1_decisions": {
            "path": str(PUBLISHED_DECISIONS),
            "present": PUBLISHED_DECISIONS.exists(),
            "cited_sha256": "08b1b8d9a56c33681b493dff1d3337951ac9a51b812c83d2e6009afdefb86713",
            "causal": False,
            "why": (
                "The file is the published fingerprint stream. "
                "FINGERPRINT_CAUSAL_STREAM_001 found interior hashes still changing "
                "after 7.989 seconds of later audio. TNF_FAILURES_001 says this stream "
                "can read future audio. It is not an NFL75 baseline."
            ),
        },
        "causal_availability_log": {
            "path": str(CAUSAL_AVAILABILITY),
            "present": CAUSAL_AVAILABILITY.exists(),
            "claimed_latency_s": 8.0,
            "prefix_invariant": False,
            "why": (
                "Rows are stamped about 8 seconds after the 5-second query, when that "
                "many later frames have arrived. The same report's first gate failed: "
                "more audio still changed the hash. The stamp is not prefix invariance."
            ),
        },
        "ast_score_cache_present": False,
        "enrollment_library_can_see_later_games": True,
    }


def build_inventory() -> dict:
    coverage = coverage_by_session()
    gaps = wall_gaps()
    raw = read_jsonl(TRUTH_PATH)
    superseded = {row["supersedes"] for row in raw if row.get("supersedes")}
    active = []
    for row in resolve_ledger(raw, "gold_id"):
        if row.get("retracted") or row.get("event") == "retracted":
            continue
        if row.get("gold_id") in superseded:
            continue
        if "start_seconds" in row:
            active.append(row)
    rows = []
    for session, span in sorted(coverage.items()):
        broadcaster, show, day = BROADCAST.get(session, ("unlisted", "unlisted", ""))
        intervals = active_intervals(session)
        scored = score_product(
            span,
            intervals,
            always_play(span),
            session=session,
            excluded_ranges=excluded_ranges(session, intervals),
            wall_gap_s=gaps.get(session, 0.0),
        )
        rows.append(
            {
                "session": session,
                "broadcaster": broadcaster,
                "show": show,
                "day": day,
                "role": _role(session),
                "split": _split(session),
                "inspected_or_tuned": session in INSPECTED,
                "coverage_start_s": span[0],
                "coverage_end_s": span[1],
                "coverage_s": round(span[1] - span[0], 3),
                "fully_annotated": True,
                "active_marks": sum(1 for row in active if row.get("session") == session),
                "commercial_breaks": len(scored["breaks"]),
                "commercial_s": round(scored["commercial_s"], 3),
                "program_s": round(scored["program_s"], 3),
                "unsure_s": round(scored["unsure_s"], 3),
                "excluded_unmarked_s": round(scored["excluded_unmarked_s"], 3),
                "wall_gap_s": round(gaps.get(session, 0.0), 3),
                "wall_gap_note": (
                    "Elapsed time already skips this hole. It is not silence inside the coverage clock "
                    "and it is not counted as heard or covered."
                    if gaps.get(session, 0.0)
                    else ""
                ),
                "audio_in_checkout": False,
                "prefix_invariant_features_in_checkout": False,
            }
        )
    sealed = []
    for session in sorted(HOLDOUTS):
        broadcaster, show, day = BROADCAST.get(session, ("unopened", "unopened", ""))
        sealed.append(
            {
                "session": session,
                "broadcaster": broadcaster,
                "show": show,
                "role": "sealed",
                "split": "sealed_holdout",
                "inspected_or_tuned": False,
                "fully_annotated": False,
                "opened_by_nfl75": False,
                "note": "Leave sealed. Not an NFL75 exam recording. No gold was read.",
            }
        )
    unlabeled = []
    for session in UNLABELED:
        broadcaster, show, day = BROADCAST[session]
        unlabeled.append(
            {
                "session": session,
                "broadcaster": broadcaster,
                "show": show,
                "day": day,
                "role": "unlabeled_not_an_exam_set",
                "fully_annotated": False,
                "note": "Named in dataset STATUS as unlabeled. Not a future NFL75 holdout.",
            }
        )
    prime = [row for row in rows if row["role"] == "development_prime"]
    return {
        "truth_sha256": sha256_file(TRUTH_PATH),
        "active_marks": len(active),
        "documented_active_marks": 177,
        "future_untouched_prime_holdout": None,
        "why_no_untouched_prime_holdout": (
            "Both labeled Prime games have already been inspected. "
            "October is a development score. September 24 is in the supervised train split. "
            "The sealed sessions have no NFL75 labels and were not opened. "
            "A 20-hour exam set is not in this checkout."
        ),
        "features": feature_status(),
        "development_prime": prime,
        "annotated": rows,
        "sealed": sealed,
        "unlabeled": unlabeled,
    }
