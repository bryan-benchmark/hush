"""Apply episode-viewer You marks (keep/mute/drop) into farm key.jsonl gold.

You is source of truth for labeled seconds: carves overlapping clips and
upserts locked program/paid_ad ranges, then refreshes GOLD_CLEAN membership.

``drop`` carves those seconds out of gold and does not upsert a train row
(guide chrome, black frames, junk).

  python -m tools.windows_lab.farm_apply_you_marks
  python -m tools.windows_lab.farm_apply_you_marks --dry-run
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .coverage_farm import farm_label_dir, streamers_capture_root

YOU_TO_BUCKET = {
    "keep": ("program", "program_sports"),
    "mute": ("paid_ad", "you_cut"),
}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _human_path() -> Path:
    return farm_label_dir() / "audit" / "EPISODE_HUMAN_FRAMES.json"


def _load_human() -> dict[str, Any]:
    path = _human_path()
    if not path.is_file():
        return {"sessions": {}, "cuts": {}, "done": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def _merge_marks(
    marks: dict[str, str],
    *,
    include_drop: bool = False,
    drop_hop_s: float = 5.0,
) -> list[tuple[float, float, str]]:
    """Collapse per-second marks into half-open [t0,t1) ranges.

    keep/mute become gold. drop is only returned when include_drop=True
    (carve-out / exclude from train — no gold upsert).

    Guide stills are usually one mark per hop (every ~5s). Merge neighboring
    ``drop`` marks across that hop gap so the carve covers the chrome, not a
    single second.
    """
    allowed = set(YOU_TO_BUCKET)
    if include_drop:
        allowed = allowed | {"drop"}
    try:
        hop = max(1.0, float(drop_hop_s))
    except (TypeError, ValueError):
        hop = 5.0
    items: list[tuple[float, str]] = []
    for k, v in (marks or {}).items():
        if v not in allowed:
            continue
        try:
            t = float(k)
        except ValueError:
            continue
        items.append((t, v))
    if not items:
        return []
    items.sort(key=lambda x: x[0])
    out: list[tuple[float, float, str]] = []
    t0, lab = items[0]
    prev = t0
    for t, v in items[1:]:
        # keep/mute: contiguous seconds. drop: allow hop-spaced guide stills.
        max_gap = hop if lab == "drop" and v == "drop" else 1.0
        if v == lab and t <= prev + max_gap + 1e-6:
            prev = t
            continue
        # Point drop at T covers [T, T+hop) of tape when isolated.
        end = prev + (hop if lab == "drop" else 1.0)
        out.append((t0, end, lab))
        t0, lab, prev = t, v, t
    end = prev + (hop if lab == "drop" else 1.0)
    out.append((t0, end, lab))
    return out


def _carve(
    segments: list[tuple[float, float, dict[str, Any]]],
    t0: float,
    t1: float,
) -> list[tuple[float, float, dict[str, Any]]]:
    """Remove [t0,t1) from existing segments (keep leftovers)."""
    out: list[tuple[float, float, dict[str, Any]]] = []
    for a, b, row in segments:
        if b <= t0 + 1e-9 or a >= t1 - 1e-9:
            out.append((a, b, row))
            continue
        if a < t0 - 1e-9:
            out.append((a, t0, row))
        if b > t1 + 1e-9:
            out.append((t1, b, row))
    return out


def _row_for_range(
    base: dict[str, Any] | None,
    *,
    session: str,
    t0: float,
    t1: float,
    label: str,
    utc: str,
) -> dict[str, Any]:
    bucket, kind = YOU_TO_BUCKET[label]
    clip = f"{session}_you_{int(t0)}_{int(t1)}"
    sd = streamers_capture_root() / session
    row = {
        "clip": clip,
        "bucket": bucket,
        "kind": kind,
        "confidence": "high",
        "ask": "locked",
        "note": f"episode You mark: {label} [{t0:g},{t1:g})",
        "source": "human",
        "human_note": f"viewer You → {label}",
        "gold": True,
        "model": None,
        "slot": "fast",
        "session": session,
        "t0": float(t0),
        "t1": float(t1),
        "locked_from": "episode_you",
        "channel": (base or {}).get("channel") or "",
        "session_dir": str(sd),
        "episode_you_utc": utc,
    }
    if base and base.get("channel"):
        row["channel"] = base["channel"]
    return row


def apply(*, dry_run: bool = False) -> dict[str, Any]:
    human = _load_human()
    marks_by_session = human.get("sessions") or {}
    utc = _now()
    label = farm_label_dir()
    key_path = label / "key.jsonl"
    rows = [json.loads(l) for l in key_path.read_text(encoding="utf-8").splitlines() if l.strip()]

    touched_sessions: list[str] = []
    new_clips: list[str] = []
    carved_n = 0
    range_n = 0
    out_rows: list[dict[str, Any]] = []
    session_channel: dict[str, str] = {}

    for r in rows:
        s = str(r.get("session") or "")
        if s and r.get("channel") and s not in session_channel:
            session_channel[s] = str(r["channel"])

    # Keep non-target sessions as-is; rebuild target sessions from carved segments.
    target = {s for s, m in marks_by_session.items() if m}
    kept = [r for r in rows if str(r.get("session") or "") not in target]

    for session in sorted(target):
        touched_sessions.append(session)
        marks = marks_by_session.get(session) or {}
        # Drop carves gold out; keep/mute carve + upsert train rows.
        all_ranges = _merge_marks(marks, include_drop=True)
        gold_ranges = [(a, b, lab) for a, b, lab in all_ranges if lab in YOU_TO_BUCKET]
        range_n += len(gold_ranges)
        segs: list[tuple[float, float, dict[str, Any]]] = []
        for r in rows:
            if str(r.get("session") or "") != session:
                continue
            try:
                a = float(r.get("t0") or 0)
                b = float(r.get("t1") or 0)
            except (TypeError, ValueError):
                continue
            if b <= a:
                continue
            segs.append((a, b, r))

        for t0, t1, _lab in all_ranges:
            segs = _carve(segs, t0, t1)
            carved_n += 1

        # Leftover pieces from old clips (may be tiny)
        rebuilt: list[dict[str, Any]] = []
        for a, b, base in sorted(segs, key=lambda x: (x[0], x[1])):
            if b - a < 0.05:
                continue
            row = dict(base)
            row["t0"] = float(a)
            row["t1"] = float(b)
            # Stable-ish id when bounds change
            old_clip = str(base.get("clip") or "")
            if abs(float(base.get("t0") or 0) - a) > 1e-6 or abs(float(base.get("t1") or 0) - b) > 1e-6:
                row["clip"] = f"{old_clip}__{int(a)}_{int(b)}" if old_clip else f"{session}_{int(a)}_{int(b)}"
                row["note"] = (str(row.get("note") or "") + f" · carved for You @ {utc}").strip(" ·")
            rebuilt.append(row)

        for t0, t1, lab in gold_ranges:
            if t1 - t0 < 0.05:
                continue
            base = {"channel": session_channel.get(session, "")}
            you_row = _row_for_range(base, session=session, t0=t0, t1=t1, label=lab, utc=utc)
            rebuilt.append(you_row)
            new_clips.append(you_row["clip"])

        rebuilt.sort(key=lambda r: (float(r["t0"]), float(r["t1"]), str(r["clip"])))
        out_rows.extend(rebuilt)

    final_rows = kept + out_rows
    # de-dupe by clip id (last wins)
    by_clip: dict[str, dict[str, Any]] = {}
    for r in final_rows:
        by_clip[str(r.get("clip"))] = r
    ordered = list(by_clip.values())
    ordered.sort(key=lambda r: (str(r.get("session") or ""), float(r.get("t0") or 0), str(r.get("clip") or "")))

    receipt = {
        "ok": True,
        "dry_run": dry_run,
        "utc": utc,
        "sessions": touched_sessions,
        "you_ranges": range_n,
        "carve_ops": carved_n,
        "new_you_clips": new_clips,
        "new_you_clips_n": len(new_clips),
        "key_rows_before": len(rows),
        "key_rows_after": len(ordered),
        "human_path": str(_human_path()),
    }

    if dry_run:
        return receipt

    bak = key_path.with_suffix(f".jsonl.bak_you_{utc.replace(':', '').replace('-', '')}")
    shutil.copy2(key_path, bak)
    receipt["backup"] = str(bak)
    key_path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in ordered) + "\n",
        encoding="utf-8",
    )

    clean_path = label / "GOLD_CLEAN.json"
    if clean_path.is_file():
        blob = json.loads(clean_path.read_text(encoding="utf-8"))
        clips = list(blob.get("clips") or [])
        old_session_clips = {str(r.get("clip")) for r in rows if str(r.get("session") or "") in target}
        rebuilt_clips = {str(r["clip"]) for r in out_rows}
        clips = [c for c in clips if c not in old_session_clips]
        for c in sorted(rebuilt_clips):
            if c not in clips:
                clips.append(c)
        blob["clips"] = clips
        blob["n"] = len(clips)
        blob["episode_you_utc"] = utc
        clean_path.write_text(json.dumps(blob, indent=2) + "\n", encoding="utf-8")
        receipt["gold_clean_n"] = len(clips)

    receipt_path = label / "audit" / "EPISODE_YOU_APPLY.json"
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    receipt["receipt"] = str(receipt_path)
    return receipt


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Apply viewer You marks into key.jsonl gold")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)
    out = apply(dry_run=bool(args.dry_run))
    print(json.dumps(out, indent=2))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
