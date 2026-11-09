"""Prefix check for a decision stream.

A decision at time t is comparable across a prefix and the full buffer when
its available_at is at or before the cut. The two lists must be identical.
Processing latency is already inside available_at: a decision that is not
ready until after the cut is outside the comparison.

This does not prove a file is causal by itself. A stamp that says the audio
was consumed early can still be wrong if the value changes once later audio
arrives. That is a separate measurement, and the fingerprint reader already
failed it.
"""

from __future__ import annotations

import json
from pathlib import Path

_EPS = 1e-6


def _canon(rows: list[dict]) -> str:
    return json.dumps(rows, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def decisions_ready_by(rows: list[dict], cut_s: float) -> list[dict]:
    return [row for row in rows if float(row["available_at"]) <= cut_s + _EPS]


def prefix_invariant(full_rows: list[dict], prefix_rows: list[dict], cut_s: float) -> dict:
    """True when the prefix run and the full run agree on every ready decision."""
    full_vis = decisions_ready_by(full_rows, cut_s)
    prefix_vis = decisions_ready_by(prefix_rows, cut_s)
    same = _canon(full_vis) == _canon(prefix_vis)
    return {
        "pass": same,
        "cut_s": cut_s,
        "full_decisions_ready": len(full_vis),
        "prefix_decisions_ready": len(prefix_vis),
        "rule": (
            "Decisions with available_at at or before the cut must match. "
            "available_at includes processing latency and is a capture-clock time."
        ),
    }


def stamp_ok(row: dict) -> str | None:
    """Necessary clock order. Not a proof of prefix invariance."""
    required = ("query_t0", "query_t1", "sample_max_consumed_at", "available_at")
    for key in required:
        if key not in row:
            return f"missing {key}"
    query_t0 = float(row["query_t0"])
    query_t1 = float(row["query_t1"])
    consumed = float(row["sample_max_consumed_at"])
    available = float(row["available_at"])
    if query_t1 <= query_t0:
        return "query ends before it starts"
    if consumed + _EPS < query_t1:
        return "sample_max_consumed_at is before the query ends"
    if available + _EPS < consumed:
        return "available_at is before the last sample it claims to have consumed"
    if "decision_effective_at" in row and abs(float(row["decision_effective_at"]) - available) > 1e-3:
        return "decision_effective_at disagrees with available_at"
    return None


def audit_availability_file(path: Path) -> dict:
    failures = []
    rows = 0
    sessions: set[str] = set()
    if not path.exists():
        return {"pass": False, "reason": "file missing", "path": str(path), "rows": 0}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        row = json.loads(line)
        rows += 1
        if row.get("session"):
            sessions.add(row["session"])
        problem = stamp_ok(row)
        if problem is not None and len(failures) < 20:
            failures.append({"line": line_number, "problem": problem, "session": row.get("session")})
    return {
        "pass": not failures and rows > 0,
        "path": str(path),
        "rows": rows,
        "sessions": sorted(sessions),
        "failures": failures,
        "proves_prefix_invariance": False,
        "note": (
            "Stamp order says the row claims not to speak before the sample it names. "
            "Prefix invariance still requires the value to stay the same when later audio is removed."
        ),
    }
