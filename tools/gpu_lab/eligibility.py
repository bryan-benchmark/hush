"""Training eligibility for the shared detector.

Verified commercial and verified program are the only seconds a head may learn.
Unsure gold, audio outside a fully annotated span, and known unlabeled
commercials are excluded. Frozen gold is not edited.
"""

from __future__ import annotations

import json
from pathlib import Path

from experiments.ledger import GOLD, TRUTH_PATH, read_jsonl, resolve_ledger
from experiments.measurement.metrics import (
    Interval,
    excluded,
    program_regions,
    target_commercials,
)

from tools.gpu_lab.splits import HOLDOUTS

REPO = Path(__file__).resolve().parents[2]
EXCLUSIONS_PATH = Path(__file__).with_name("exclusions.json")
COVERAGE_FILES = (
    "GOLD_DATASET_20261013.json",
    "GOLD_DEV_V1.json",
    "GOLD_REPLICATION_V1.json",
)


def _merge(ranges: list[tuple[float, float]]) -> list[tuple[float, float]]:
    ordered = sorted((start, end) for start, end in ranges if end > start)
    if not ordered:
        return []
    out = [ordered[0]]
    for start, end in ordered[1:]:
        prev_s, prev_e = out[-1]
        if start <= prev_e:
            out[-1] = (prev_s, max(prev_e, end))
        else:
            out.append((start, end))
    return out


def _subtract(base: list[tuple[float, float]], cut: list[tuple[float, float]]) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for start, end in _merge(base):
        cursor = start
        for c0, c1 in _merge(cut):
            if c1 <= cursor or c0 >= end:
                continue
            if c0 > cursor:
                out.append((cursor, min(c0, end)))
            cursor = max(cursor, c1)
            if cursor >= end:
                break
        if cursor < end:
            out.append((cursor, end))
    return [(a, b) for a, b in out if b > a]


def _seconds(ranges: list[tuple[float, float]]) -> float:
    return sum(end - start for start, end in ranges)


def coverage_spans() -> list[dict]:
    spans = []
    for name in COVERAGE_FILES:
        doc = json.loads((GOLD / name).read_text(encoding="utf-8"))
        for row in doc["coverage"]:
            if row.get("fully_annotated"):
                spans.append(row)
    return spans


def active_rows() -> list[dict]:
    raw = read_jsonl(TRUTH_PATH)
    superseded = {row["supersedes"] for row in raw if row.get("supersedes")}
    active = []
    for row in resolve_ledger(raw, "gold_id"):
        session = row.get("session")
        if session in HOLDOUTS:
            raise RuntimeError(f"sealed holdout {session} is in the truth ledger")
        if row.get("retracted") or row.get("event") == "retracted":
            continue
        if row.get("gold_id") in superseded:
            continue
        active.append(row)
    return active


def _intervals(rows: list[dict]) -> list[Interval]:
    return [
        Interval(
            start=float(row["start_seconds"]),
            end=float(row["end_seconds"]),
            event_class=str(row.get("event_class") or ""),
            desired_action=str(row.get("desired_action") or ""),
            confidence=str(row.get("confidence") or ""),
        )
        for row in rows
        if "start_seconds" in row and "end_seconds" in row
    ]


def load_probes(path: Path = EXCLUSIONS_PATH) -> list[dict]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    return list(doc["probes"])


def gap_around(commercials: list[tuple[float, float]], probe_s: float) -> tuple[float, float]:
    """Open time between the gold commercials on either side of an unmarked spot."""
    if any(start <= probe_s < end for start, end in commercials):
        raise RuntimeError(f"probe at {probe_s} sits inside a gold commercial")
    before = [end for start, end in commercials if end <= probe_s]
    after = [start for start, end in commercials if start >= probe_s]
    if not before or not after:
        raise RuntimeError(f"probe at {probe_s} has no gold commercial on both sides")
    return max(before), min(after)


def session_eligibility(
    session: str,
    spans: list[dict],
    rows: list[dict],
    probes: list[dict],
) -> dict:
    here = [row for row in spans if row["session"] == session]
    if not here:
        raise RuntimeError(f"{session} has no fully annotated coverage")
    intervals = _intervals([row for row in rows if row.get("session") == session])
    commercials = target_commercials(intervals)
    unsure = excluded(intervals)
    probe_gaps = []
    for probe in probes:
        if probe["session"] != session:
            continue
        start, end = gap_around(commercials, float(probe["probe_seconds"]))
        probe_gaps.append((start, end, probe["reason"]))
    cuts = _merge(unsure + [(start, end) for start, end, _reason in probe_gaps])
    coverage = [(float(row["from_seconds"]), float(row["to_seconds"])) for row in here]
    program = []
    for start, end in coverage:
        program.extend(program_regions((start, end), intervals))
    verified_program = _subtract(program, cuts)
    verified_commercial = _subtract(commercials, cuts)
    if _seconds(verified_commercial) + 1e-6 < _seconds(commercials):
        raise RuntimeError(f"an exclusion cut a gold commercial in {session}")
    return {
        "session": session,
        "coverage": [[a, b] for a, b in coverage],
        "verified_commercial": [[a, b] for a, b in verified_commercial],
        "verified_program": [[a, b] for a, b in verified_program],
        "excluded": [[a, b] for a, b in _subtract(coverage, verified_commercial + verified_program)],
        "probe_gaps": [
            {"start_seconds": start, "end_seconds": end, "reason": reason}
            for start, end, reason in probe_gaps
        ],
        "commercial_s": round(_seconds(verified_commercial), 3),
        "program_s": round(_seconds(verified_program), 3),
        "excluded_s": round(_seconds(_subtract(coverage, verified_commercial + verified_program)), 3),
        "commercials": len(verified_commercial),
    }


def build_masks(sessions: list[str], probes: list[dict] | None = None) -> list[dict]:
    spans = coverage_spans()
    rows = active_rows()
    chosen = load_probes() if probes is None else probes
    return [session_eligibility(session, spans, rows, chosen) for session in sessions]
