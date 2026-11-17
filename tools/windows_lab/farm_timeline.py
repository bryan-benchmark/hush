"""Build continuous acoustic timelines from farm locks (and later vision).

Writes:
  <session_dir>/farm_timeline.jsonl
  indexes/farm_labels/timelines.jsonl   (all sessions, flat)
  indexes/farm_labels/TIMELINE.md

ASAP path: human/gold locks in key.jsonl → merged broadcast/non_broadcast ranges.
Vision range locker will append source=vision_auto later.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .coverage_farm import farm_label_dir, streamers_capture_root
from .farm_ontology import BROADCAST, NON_BROADCAST, interval_from_farm_row

_EPS = 1e-6


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def _is_locked(row: dict[str, Any]) -> bool:
    if row.get("ask") == "skip":
        return False
    if str(row.get("source") or "") == "skip_gold_hygiene":
        return False
    return bool(
        row.get("gold")
        or row.get("ask") == "locked"
        or row.get("source") in {"gold", "human", "multichannel_consensus"}
    )


def _merge_same_bucket(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge overlapping/adjacent intervals that share session+bucket."""
    by_key: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_key[(r["session"], r["bucket"])].append(r)
    out: list[dict[str, Any]] = []
    for (session, bucket), group in sorted(by_key.items()):
        ordered = sorted(group, key=lambda x: (float(x["start_s"]), float(x["end_s"])))
        cur = dict(ordered[0])
        for nxt in ordered[1:]:
            if float(nxt["start_s"]) <= float(cur["end_s"]) + _EPS:
                cur["end_s"] = max(float(cur["end_s"]), float(nxt["end_s"]))
                cur["dur_s"] = round(float(cur["end_s"]) - float(cur["start_s"]), 3)
                # Prefer human over vision_auto when merging
                if str(nxt.get("source") or "") == "human" or str(cur.get("source") or "") != "human":
                    if str(nxt.get("source") or "") in {"human", "gold"}:
                        cur["source"] = nxt["source"]
                notes = [str(cur.get("note") or ""), str(nxt.get("note") or "")]
                cur["note"] = " | ".join(n for n in notes if n)[:240]
                clips = [str(cur.get("clip") or ""), str(nxt.get("clip") or "")]
                cur["clip"] = ",".join(c for c in clips if c)[:200]
            else:
                out.append(cur)
                cur = dict(nxt)
        out.append(cur)
    out.sort(key=lambda r: (r["session"], float(r["start_s"]), r["bucket"]))
    return out


def load_locked_farm_rows(*, clean_only: bool = True) -> list[dict[str, Any]]:
    label = farm_label_dir()
    keys = {str(r.get("clip") or ""): r for r in _load_jsonl(label / "key.jsonl") if r.get("clip")}
    queue = {str(r.get("clip") or ""): r for r in _load_jsonl(label / "queue.jsonl") if r.get("clip")}
    allowed: set[str] | None = None
    clean_path = label / "GOLD_CLEAN.json"
    if clean_only and clean_path.is_file():
        blob = json.loads(clean_path.read_text(encoding="utf-8"))
        allowed = {str(c) for c in (blob.get("clips") or [])}

    rows: list[dict[str, Any]] = []
    for clip, row in keys.items():
        if not _is_locked(row):
            continue
        if allowed is not None and clip not in allowed:
            continue
        q = queue.get(clip) or {}
        session = str(row.get("session") or q.get("session") or "")
        sd = Path(str(row.get("session_dir") or q.get("session_dir") or ""))
        if not sd.is_dir() and session:
            cand = streamers_capture_root() / session
            if cand.is_dir():
                sd = cand
        source = str(row.get("source") or "human")
        if source == "gold":
            source = "human"
        merged = {
            **row,
            "clip": clip,
            "session": session,
            "session_dir": str(sd),
            "t0": float(row.get("t0") if row.get("t0") is not None else q.get("t0") or 0.0),
            "t1": float(row.get("t1") if row.get("t1") is not None else q.get("t1") or 0.0),
            "note": row.get("note") or row.get("human_note") or q.get("note") or "",
        }
        iv = interval_from_farm_row(merged, source=source, model_id="farm_lock_v1")
        if iv is None:
            continue
        rows.append(iv)
    return rows


def build_timelines(*, clean_only: bool = True) -> dict[str, Any]:
    raw = load_locked_farm_rows(clean_only=clean_only)
    merged = _merge_same_bucket(raw)
    by_session: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in merged:
        by_session[r["session"]].append(r)

    label = farm_label_dir()
    index_path = label / "timelines.jsonl"
    lines = [json.dumps(r, ensure_ascii=False) for r in merged]
    index_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")

    written_sessions = []
    for session, rows in by_session.items():
        sd = Path(str(rows[0].get("session_dir") or ""))
        if not sd.is_dir():
            sd = streamers_capture_root() / session
        if sd.is_dir():
            path = sd / "farm_timeline.jsonl"
            path.write_text(
                "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
                encoding="utf-8",
            )
            written_sessions.append({"session": session, "path": str(path), "n": len(rows)})

    nb_s = sum(float(r["dur_s"]) for r in merged if r["bucket"] == NON_BROADCAST)
    bc_s = sum(float(r["dur_s"]) for r in merged if r["bucket"] == BROADCAST)
    summary = {
        "generated_utc": _now(),
        "clean_only": clean_only,
        "n_intervals": len(merged),
        "n_sessions": len(by_session),
        "non_broadcast_s": round(nb_s, 3),
        "broadcast_s": round(bc_s, 3),
        "index": str(index_path),
        "sessions_written": written_sessions,
        "what_this_is": (
            "Acoustic timeline gold from farm locks. "
            "Vision never mutes; these intervals train/score the audio stack."
        ),
    }
    (label / "TIMELINE.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    md = [
        f"# Farm acoustic timelines — {summary['generated_utc'][:19]}Z",
        "",
        f"- intervals: **{summary['n_intervals']}** across **{summary['n_sessions']}** sessions",
        f"- non_broadcast (mute): **{summary['non_broadcast_s']}s**",
        f"- broadcast (play): **{summary['broadcast_s']}s**",
        f"- index: `{index_path}`",
        "",
        "program_mention / L-wrap → non_broadcast (audio hears the ad).",
        "",
        "| Session | Intervals |",
        "|---|---:|",
    ]
    for session, rows in sorted(by_session.items()):
        md.append(f"| `{session}` | {len(rows)} |")
    md.append("")
    (label / "TIMELINE.md").write_text("\n".join(md), encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Build farm → acoustic timelines from locks")
    p.add_argument("--all-locked", action="store_true", help="Ignore GOLD_CLEAN filter")
    args = p.parse_args(argv)
    summary = build_timelines(clean_only=not args.all_locked)
    print(json.dumps({"ok": True, **{k: summary[k] for k in summary if k != "sessions_written"}, "sessions_written_n": len(summary["sessions_written"])}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
