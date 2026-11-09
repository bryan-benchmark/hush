"""A correction and the note written when a sitting stops.

A button press is not a label. The football gold stays where it is.
"""

from __future__ import annotations

import json
from pathlib import Path

from ohush_live.sports import PRODUCT

BEFORE_S = 15.0
AFTER_S = 10.0

RECOVERY = (
    "Show the game returns the audio and holds the next automatic cover until this break goes quiet.",
    "If this program stops, turn the television speakers up. The computer is not a relay.",
    "Automatic cover uses the speaker and the audio together. A missing speaker keeps the show on.",
)


def correction_row(
    timestamp: float,
    kind: str,
    *,
    hearing: str,
    auto: bool,
    decision_mode: str,
    families: dict,
    shadow: dict | None,
    lag_ms: float | None,
    chunk: str,
    machine: str,
    speaker_ready: bool,
    departure_votes: int,
) -> dict:
    if kind not in ("missed_ad", "muted_show"):
        raise ValueError(kind)
    t = float(timestamp)
    last = shadow or {}
    return {
        "t": round(t, 3),
        "event": "correction",
        "kind": kind,
        "ground_truth": False,
        "hearing": hearing,
        "auto": bool(auto),
        "decision_mode": decision_mode,
        "machine": machine,
        "speaker_ready": bool(speaker_ready),
        "departure_votes": int(departure_votes),
        "shadow_would": last.get("would"),
        "shadow_reason": last.get("reason"),
        "families": {
            name: reading if isinstance(reading, dict) else None
            for name, reading in families.items()
        },
        "lag_ms": None if lag_ms is None else round(float(lag_ms), 1),
        "audio_ref": {
            "chunk": chunk,
            "t0": round(max(0.0, t - BEFORE_S), 3),
            "t1": round(t + AFTER_S, 3),
            "note": "Session clock on the untouched optical chunks. The clip is not copied.",
        },
        "product": PRODUCT,
    }


def _rows(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def build_report(folder: Path) -> dict:
    session_path = folder / "session.json"
    session = {}
    if session_path.is_file():
        try:
            loaded = json.loads(session_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                session = loaded
        except json.JSONDecodeError:
            session = {}
    corrections = [row for row in _rows(folder / "corrections.jsonl") if row.get("event") == "correction"]
    decisions = _rows(folder / "decisions.jsonl")
    missed = [row for row in corrections if row.get("kind") == "missed_ad"]
    muted = [row for row in corrections if row.get("kind") == "muted_show"]
    manual_returns = [
        row
        for row in decisions
        if row.get("decision_source") == "human"
        and row.get("state") == "REPLACEMENT_TO_PROGRAM"
        and not row.get("noop")
    ]
    manual_covers = [
        row
        for row in decisions
        if row.get("decision_source") == "human"
        and row.get("state") == "PROGRAM_TO_REPLACEMENT"
        and not row.get("noop")
    ]
    auto_covers = [
        row
        for row in decisions
        if row.get("decision_source") == "auto" and row.get("state") == "PROGRAM_TO_REPLACEMENT"
    ]
    events = []
    for row in missed:
        events.append({"t": row.get("t"), "kind": "missed_ad", "ground_truth": False})
    for row in muted:
        events.append({"t": row.get("t"), "kind": "muted_show", "ground_truth": False})
    for row in manual_returns:
        events.append({"t": row.get("t"), "kind": "manual_return", "ground_truth": False})
    events.sort(key=lambda row: float(row.get("t") or 0))
    return {
        "product": PRODUCT,
        "show": session.get("show") or "",
        "service": session.get("service") or "",
        "broadcast": session.get("broadcast") or "unspecified",
        "decision_mode": session.get("decision_mode") or "two_family",
        "missed_ad": len(missed),
        "muted_show": len(muted),
        "manual_returns": len(manual_returns),
        "manual_covers": len(manual_covers),
        "auto_covers": len(auto_covers),
        "capture_gaps": len(session.get("gaps") or []),
        "events": events,
        "ground_truth": False,
        "note": "Button presses are reports. They are not labels and they do not change closed gold.",
    }


def write_report(folder: Path) -> dict:
    report = build_report(folder)
    (folder / "session_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    lines = [
        "Hush session report",
        f"{report['show'] or 'Untitled'} · {report['service'] or 'unknown service'} · {report['broadcast']}",
        f"Decision mode {report['decision_mode']}",
        "",
        f"Missed-ad reports     {report['missed_ad']}",
        f"Muted-show reports    {report['muted_show']}",
        f"Manual returns        {report['manual_returns']}",
        f"Manual covers         {report['manual_covers']}",
        f"Automatic covers      {report['auto_covers']}",
        f"Capture gaps          {report['capture_gaps']}",
        "",
        report["note"],
        "",
    ]
    if report["events"]:
        lines.append("Events")
        for row in report["events"]:
            lines.append(f"  {row['t']}  {row['kind']}")
    else:
        lines.append("No corrections or manual returns were stored.")
    lines.extend(["", *RECOVERY, ""])
    (folder / "session_report.txt").write_text("\n".join(lines), encoding="utf-8")
    return report
