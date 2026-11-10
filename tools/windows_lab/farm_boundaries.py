"""Boundary-based farm clips + gold lock from label_aid / still diffs.

Fixed 20s windows straddle ad↔program cuts. Prefer:
1) label_aid kind changes (human/aid timeline)
2) still-to-still visual jumps when aid is a stub
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .config import data_root
from .coverage_farm import _infer_slot, _iter_streamers_takes, _load_json, _map_aid_kind, farm_label_dir

MAX_CLIP_SEC = 40.0
MIN_CLIP_SEC = 6.0
STILL_JUMP_THRESH = 28.0  # mean abs pixel diff 0–255; tuned for 1fps ADB stills
STUB_NOTE_RE = re.compile(r"^imported session clip @", re.I)


def _aid_is_stub(aid: dict[str, Any]) -> bool:
    timeline = list(aid.get("timeline") or [])
    if not timeline:
        return True
    if aid.get("source") == "authorized_session_import":
        kinds = {str(r.get("kind") or "") for r in timeline}
        if kinds <= {"program"} and all(STUB_NOTE_RE.search(str(r.get("notes") or "")) for r in timeline):
            return True
    return False


def _merge_aid_segments(aid: dict[str, Any]) -> list[dict[str, Any]]:
    """Collapse consecutive same-bucket aid rows into full boundary spans."""
    timeline = list(aid.get("timeline") or [])
    if not timeline:
        return []
    duration = float((aid.get("media") or {}).get("duration_s") or 0.0)
    times = [float(r.get("t_s") or 0.0) for r in timeline]
    if duration <= 0:
        duration = (times[-1] + 12.0) if times else 0.0

    raw: list[dict[str, Any]] = []
    for i, row in enumerate(timeline):
        t0 = float(row.get("t_s") or 0.0)
        t1 = float(timeline[i + 1].get("t_s") or duration) if i + 1 < len(timeline) else duration
        if t1 <= t0:
            t1 = t0 + MIN_CLIP_SEC
        bucket, kind = _map_aid_kind(str(row.get("kind") or ""))
        note_bits = []
        if row.get("brand"):
            note_bits.append(str(row["brand"]))
        if row.get("notes"):
            note_bits.append(str(row["notes"]))
        raw.append(
            {
                "t0": t0,
                "t1": t1,
                "bucket": bucket,
                "kind": kind,
                "aid_kind": row.get("kind"),
                "note": " · ".join(note_bits)[:200],
                "source": "label_aid_boundary",
            }
        )

    merged: list[dict[str, Any]] = []
    for seg in raw:
        if merged and merged[-1]["bucket"] == seg["bucket"] and merged[-1]["kind"] == seg["kind"]:
            merged[-1]["t1"] = seg["t1"]
            if seg.get("note") and seg["note"] not in (merged[-1].get("note") or ""):
                merged[-1]["note"] = ((merged[-1].get("note") or "") + " · " + seg["note"])[:200]
        else:
            merged.append(dict(seg))
    # Drop tiny tail crumbs (< MIN) by folding into previous span.
    cleaned: list[dict[str, Any]] = []
    for seg in merged:
        if cleaned and (float(seg["t1"]) - float(seg["t0"])) < MIN_CLIP_SEC:
            cleaned[-1]["t1"] = seg["t1"]
            continue
        cleaned.append(seg)
    return _split_long(cleaned)


def _split_long(segs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for seg in segs:
        t0 = float(seg["t0"])
        t1 = float(seg["t1"])
        if t1 - t0 <= MAX_CLIP_SEC:
            out.append(seg)
            continue
        t = t0
        while t < t1 - 0.5:
            u = min(t1, t + MAX_CLIP_SEC)
            if u - t < MIN_CLIP_SEC and out:
                out[-1]["t1"] = t1
                break
            piece = dict(seg)
            piece["t0"] = t
            piece["t1"] = u
            out.append(piece)
            t = u
    return out


def _still_times(session_dir: Path) -> list[tuple[float, Path]]:
    stills = session_dir / "stills"
    if not stills.is_dir():
        return []
    rows: list[tuple[float, Path]] = []
    for path in stills.glob("still_t*.jpg"):
        try:
            tt = float(path.stem.replace("still_t", ""))
        except ValueError:
            continue
        rows.append((tt, path))
    rows.sort(key=lambda x: x[0])
    return rows


def _mean_abs_diff(a: Path, b: Path) -> float:
    """Cheap still jump score without heavy deps — downsample via raw JPEG decode if Pillow present."""
    try:
        from PIL import Image
        import numpy as np

        ia = Image.open(a).convert("L").resize((160, 90))
        ib = Image.open(b).convert("L").resize((160, 90))
        da = np.asarray(ia, dtype=np.float32)
        db = np.asarray(ib, dtype=np.float32)
        return float(np.mean(np.abs(da - db)))
    except Exception:
        # Fallback: file-size delta is weak but better than fixed clocks.
        try:
            return abs(a.stat().st_size - b.stat().st_size) / 1000.0
        except OSError:
            return 0.0


def still_diff_boundaries(session_dir: Path, *, duration_s: float | None = None) -> list[dict[str, Any]]:
    """Propose cuts where consecutive 1fps stills jump hard.

    Returns [] when stills are flat/duplicates (common on lagged ADB captures).
    """
    rows = _still_times(session_dir)
    if len(rows) < 4:
        return []
    dur = duration_s
    if dur is None:
        aid = _load_json(session_dir / "label_aid.json") or {}
        dur = float((aid.get("media") or {}).get("duration_s") or rows[-1][0] + 1.0)

    # Adaptive threshold from this take — absolute 28 was for 0–255; many stills are near-dupes.
    scores: list[float] = []
    for i in range(1, len(rows)):
        scores.append(_mean_abs_diff(rows[i - 1][1], rows[i][1]))
    if not scores:
        return []
    scores_sorted = sorted(scores)
    p95 = scores_sorted[int(0.95 * (len(scores_sorted) - 1))]
    p99 = scores_sorted[int(0.99 * (len(scores_sorted) - 1))]
    # If almost no motion, still-diff cannot cut this take.
    if p99 < 1.0:
        return []
    thresh = max(STILL_JUMP_THRESH if p99 >= STILL_JUMP_THRESH else p95 * 1.5, p95)

    cuts = [0.0]
    for i in range(1, len(rows)):
        score = scores[i - 1]
        t = rows[i][0]
        if score >= thresh and (t - cuts[-1]) >= MIN_CLIP_SEC:
            cuts.append(t)
    if len(cuts) < 2:
        return []
    if cuts[-1] < dur - 1.0:
        cuts.append(float(dur))

    segs: list[dict[str, Any]] = []
    for i in range(len(cuts) - 1):
        t0, t1 = cuts[i], cuts[i + 1]
        if t1 - t0 < MIN_CLIP_SEC:
            continue
        segs.append(
            {
                "t0": t0,
                "t1": t1,
                "bucket": "uncertain",
                "kind": "unknown",
                "aid_kind": None,
                "note": f"still_diff_boundary thresh={thresh:.2f}",
                "source": "still_diff_boundary",
            }
        )
    return _split_long(segs)


_AD_LEX = re.compile(
    r"\b("
    r"percent|apr|financing|limited time|order now|buy now|learn more|"
    r"geico|insurance|credit card|outlander|hump day|mitsubishi|sapphire|"
    r"qr code|scan the|visit|www\.|\.com|call now|save \d|dollar|dealership|"
    r"sponsored by|brought to you by|commercial break"
    r")\b",
    re.I,
)


def transcript_boundaries(session_dir: Path, *, duration_s: float | None = None) -> list[dict[str, Any]]:
    """Cut on transcript gaps and ad-lexicon on/off flips (uses cached farm_transcript.json)."""
    cache = session_dir / "farm_transcript.json"
    if not cache.is_file():
        return []
    try:
        tr = json.loads(cache.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    segs = list(tr.get("segments") or [])
    if len(segs) < 2:
        return []
    dur = float(duration_s or tr.get("duration_s") or segs[-1].get("end") or 0.0)
    if dur <= 0:
        return []

    cuts = [0.0]
    prev_ad = None
    prev_end = 0.0
    for seg in segs:
        start = float(seg.get("start") or 0.0)
        end = float(seg.get("end") or start)
        text = str(seg.get("text") or "")
        # Silence / gap between utterances.
        if start - prev_end >= 2.5 and (start - cuts[-1]) >= MIN_CLIP_SEC:
            cuts.append(start)
        ad_now = bool(_AD_LEX.search(text))
        if prev_ad is not None and ad_now != prev_ad and (start - cuts[-1]) >= MIN_CLIP_SEC:
            cuts.append(start)
        prev_ad = ad_now
        prev_end = end
    if cuts[-1] < dur - 1.0:
        cuts.append(dur)

    if len(cuts) < 3:
        return []

    out: list[dict[str, Any]] = []
    for i in range(len(cuts) - 1):
        t0, t1 = cuts[i], cuts[i + 1]
        if t1 - t0 < MIN_CLIP_SEC:
            continue
        out.append(
            {
                "t0": t0,
                "t1": t1,
                "bucket": "uncertain",
                "kind": "unknown",
                "note": "transcript_boundary",
                "source": "transcript_boundary",
            }
        )
    return _split_long(out)


def segments_for_take(take_dir: Path) -> list[dict[str, Any]]:
    aid = _load_json(take_dir / "label_aid.json") or {}
    if not _aid_is_stub(aid) and (aid.get("timeline") or []):
        return _merge_aid_segments(aid)
    dur = float((aid.get("media") or {}).get("duration_s") or 0.0)
    segs = still_diff_boundaries(take_dir, duration_s=dur or None)
    if segs:
        return segs
    segs = transcript_boundaries(take_dir, duration_s=dur or None)
    if segs:
        return segs
    # Last resort: coarse 30s tiles (better than 12s stubs for review).
    if dur <= 0:
        return []
    out = []
    t = 0.0
    while t < dur:
        u = min(dur, t + 30.0)
        out.append(
            {
                "t0": t,
                "t1": u,
                "bucket": "uncertain",
                "kind": "unknown",
                "note": "fallback_tile",
                "source": "fallback_tile",
            }
        )
        t = u
    return out


def _clip_id(session: str, t0: float, t1: float) -> str:
    return f"{session}_{t0:.0f}_{t1:.0f}"


def rebuild_queue_and_gold(
    root: Path | None = None,
    *,
    lock_rich_aid: bool = True,
) -> dict[str, Any]:
    """Rebuild queue from boundaries; lock gold keys from rich label_aid takes."""
    root = root or data_root()
    label_dir = farm_label_dir(root)
    label_dir.mkdir(parents=True, exist_ok=True)

    queue_rows: list[dict[str, Any]] = []
    gold_rows: list[dict[str, Any]] = []
    key_rows: dict[str, dict[str, Any]] = {}
    takes_n = 0
    rich_n = 0
    stub_n = 0

    for take_dir in _iter_streamers_takes(root):
        takes_n += 1
        aid = _load_json(take_dir / "label_aid.json") or {}
        session = str(aid.get("session") or take_dir.name)
        guide = aid.get("guide") or {}
        slot = _infer_slot(guide.get("name") or session)
        stub = _aid_is_stub(aid)
        if stub:
            stub_n += 1
        else:
            rich_n += 1

        segs = segments_for_take(take_dir)
        # Persist boundaries next to the take for audit.
        (take_dir / "farm_boundaries.json").write_text(
            json.dumps(
                {
                    "session": session,
                    "stub_aid": stub,
                    "segments": segs,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        for seg in segs:
            t0 = float(seg["t0"])
            t1 = float(seg["t1"])
            clip = _clip_id(session, t0, t1)
            queue_rows.append(
                {
                    "clip": clip,
                    "session": session,
                    "session_dir": str(take_dir),
                    "audio_rel": "audio.wav",
                    "t0": t0,
                    "t1": t1,
                    "play_start": max(0.0, t0 - 0.5),
                    "duration": (t1 - t0) + 1.0,
                    "slot": slot,
                    "channel": guide.get("name"),
                    "why": f"{seg.get('source')} · {seg.get('aid_kind') or seg.get('bucket')} · {guide.get('name')}",
                    "priority": 1 if not stub else 5,
                    "caption": seg.get("note") or "",
                    "rank": len(queue_rows),
                    "source": seg.get("source") or "boundary",
                    "expect_bucket": seg.get("bucket") if not stub else None,
                }
            )

            if lock_rich_aid and not stub and seg.get("bucket") in {
                "paid_ad",
                "program",
                "show_promo",
                "program_mention",
            }:
                gold = {
                    "clip": clip,
                    "bucket": seg["bucket"],
                    "kind": seg.get("kind") or "unknown",
                    "confidence": "high",
                    "ask": "locked",
                    "note": seg.get("note") or "",
                    "source": "gold",
                    "human_note": seg.get("note") or "",
                    "gold": True,
                    "model": None,
                    "slot": slot,
                    "session": session,
                    "t0": t0,
                    "t1": t1,
                    "locked_from": "label_aid_boundary",
                }
                gold_rows.append(gold)
                key_rows[clip] = gold

    # Preserve prior human locks not regenerated this pass.
    key_path = label_dir / "key.jsonl"
    if key_path.is_file():
        for line in key_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            clip = row.get("clip")
            if not clip or clip in key_rows:
                continue
            if row.get("gold") or row.get("source") == "human" or row.get("ask") == "locked":
                key_rows[clip] = row

    queue_path = label_dir / "queue.jsonl"
    with queue_path.open("w", encoding="utf-8") as fh:
        for row in queue_rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    gold_path = label_dir / "gold.jsonl"
    with gold_path.open("w", encoding="utf-8") as fh:
        for row in gold_rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    with key_path.open("w", encoding="utf-8") as fh:
        for clip, row in key_rows.items():
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    # Trust gate: overnight auto stays off until enough gold exists.
    trust = {
        "gold_clips": len(gold_rows),
        "auto_paid_ad_enabled": False,
        "min_gold_for_auto": 30,
        "why": "Auto paid_ad disabled until gold set ≥30 and probe precision checked",
    }
    (label_dir / "trust_gate.json").write_text(json.dumps(trust, indent=2), encoding="utf-8")

    candidates = _propose_gold_candidates(root, existing={g["clip"] for g in gold_rows})
    cand_path = label_dir / "gold_candidates.jsonl"
    with cand_path.open("w", encoding="utf-8") as fh:
        for row in candidates:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    # Prepend candidates into queue at high priority if not already present.
    have = {r["clip"] for r in queue_rows}
    prepend = []
    for row in candidates:
        if row["clip"] in have:
            continue
        prepend.append(
            {
                "clip": row["clip"],
                "session": row["session"],
                "session_dir": row["session_dir"],
                "audio_rel": "audio.wav",
                "t0": row["t0"],
                "t1": row["t1"],
                "play_start": max(0.0, row["t0"] - 0.5),
                "duration": (row["t1"] - row["t0"]) + 1.0,
                "slot": row.get("slot") or "fast",
                "channel": row.get("channel"),
                "why": f"gold_candidate · {row.get('expect_bucket')}",
                "priority": 0,
                "caption": row.get("note") or "",
                "rank": 0,
                "source": "gold_candidate",
                "expect_bucket": row.get("expect_bucket"),
            }
        )
    if prepend:
        queue_rows = prepend + queue_rows
        with queue_path.open("w", encoding="utf-8") as fh:
            for row in queue_rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    md = [
        "# Farm gold + boundaries",
        "",
        f"- takes: **{takes_n}** (rich aid {rich_n}, stub {stub_n})",
        f"- queue clips: **{len(queue_rows)}**",
        f"- gold locked: **{len(gold_rows)}**",
        f"- gold candidates (confirm at /farm): **{len(candidates)}**",
        f"- auto paid_ad: **off** until gold ≥30",
        "",
        "| clip | bucket | kind | note |",
        "|---|---|---|---|",
    ]
    for g in gold_rows[:40]:
        md.append(
            f"| `{g['clip']}` | {g['bucket']} | {g['kind']} | {(g.get('note') or '')[:60]} |"
        )
    if candidates:
        md.extend(["", "## Candidates (need human lock)", ""])
        for c in candidates[:30]:
            md.append(
                f"- `{c['clip']}` expect **{c.get('expect_bucket')}** — {(c.get('note') or '')[:80]}"
            )
    (label_dir / "GOLD.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    return {
        "takes": takes_n,
        "rich_aid_takes": rich_n,
        "stub_aid_takes": stub_n,
        "queue_clips": len(queue_rows),
        "gold_locked": len(gold_rows),
        "gold_candidates": len(candidates),
        "queue_path": str(queue_path),
        "gold_path": str(gold_path),
        "key_path": str(key_path),
        "trust_gate": trust,
        "review_url": "http://127.0.0.1:3010/farm",
    }


def confirm_gold_candidates(
    root: Path | None = None,
    *,
    clips: list[str] | None = None,
    all_candidates: bool = False,
) -> dict[str, Any]:
    """Promote reviewed gold_candidates into locked gold + key."""
    root = root or data_root()
    label_dir = farm_label_dir(root)
    cand_path = label_dir / "gold_candidates.jsonl"
    if not cand_path.is_file():
        return {"ok": False, "error": "missing gold_candidates.jsonl"}
    cands = [json.loads(l) for l in cand_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    want = set(clips or [])
    if all_candidates:
        chosen = cands
    else:
        chosen = [c for c in cands if c.get("clip") in want]
    if not chosen:
        return {"ok": False, "error": "no candidates selected — pass --clip ID or --all-candidates"}

    gold_path = label_dir / "gold.jsonl"
    key_path = label_dir / "key.jsonl"
    gold_by: dict[str, dict[str, Any]] = {}
    if gold_path.is_file():
        for line in gold_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                gold_by[row["clip"]] = row
    key_by: dict[str, dict[str, Any]] = {}
    if key_path.is_file():
        for line in key_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                key_by[row["clip"]] = row

    locked = 0
    for c in chosen:
        clip = c["clip"]
        gold = {
            "clip": clip,
            "bucket": c.get("expect_bucket") or "paid_ad",
            "kind": "dry_vo" if (c.get("expect_bucket") == "paid_ad") else "unknown",
            "confidence": "high",
            "ask": "locked",
            "note": c.get("note") or "",
            "source": "gold",
            "human_note": c.get("note") or "",
            "gold": True,
            "model": None,
            "session": c.get("session"),
            "t0": c.get("t0"),
            "t1": c.get("t1"),
            "locked_from": "gold_candidate_confirm",
        }
        gold_by[clip] = gold
        key_by[clip] = gold
        locked += 1

    with gold_path.open("w", encoding="utf-8") as fh:
        for row in gold_by.values():
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    with key_path.open("w", encoding="utf-8") as fh:
        for row in key_by.values():
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    trust_path = label_dir / "trust_gate.json"
    trust = {
        "gold_clips": len(gold_by),
        "auto_paid_ad_enabled": len(gold_by) >= 30,
        "min_gold_for_auto": 30,
        "why": (
            "Auto paid_ad enabled"
            if len(gold_by) >= 30
            else "Auto paid_ad disabled until gold set ≥30 and probe precision checked"
        ),
    }
    trust_path.write_text(json.dumps(trust, indent=2), encoding="utf-8")
    return {
        "ok": True,
        "locked": locked,
        "gold_clips": len(gold_by),
        "trust_gate": trust,
        "review_url": "http://127.0.0.1:3010/farm",
    }


def _propose_gold_candidates(root: Path, *, existing: set[str]) -> list[dict[str, Any]]:
    """Transcript windows with strong ad lexicon → human-confirm candidates (not locked)."""
    out: list[dict[str, Any]] = []
    for take_dir in _iter_streamers_takes(root):
        aid = _load_json(take_dir / "label_aid.json") or {}
        if not _aid_is_stub(aid):
            continue  # rich aid already gold-locked
        cache = take_dir / "farm_transcript.json"
        if not cache.is_file():
            continue
        try:
            tr = json.loads(cache.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        session = str(aid.get("session") or take_dir.name)
        guide = aid.get("guide") or {}
        slot = _infer_slot(guide.get("name") or session)
        dur = float(tr.get("duration_s") or (aid.get("media") or {}).get("duration_s") or 0.0)
        segs = list(tr.get("segments") or [])
        # Slide 16s windows; keep those with ≥2 ad lexicon hits.
        t = 0.0
        while t + 12.0 <= max(dur, 12.0):
            u = t + 16.0
            texts = [
                str(s.get("text") or "")
                for s in segs
                if float(s.get("end") or 0) >= t and float(s.get("start") or 0) <= u
            ]
            blob = " ".join(texts)
            hits = _AD_LEX.findall(blob)
            if len(hits) >= 2:
                clip = _clip_id(session, t, u)
                if clip not in existing:
                    out.append(
                        {
                            "clip": clip,
                            "session": session,
                            "session_dir": str(take_dir),
                            "t0": t,
                            "t1": u,
                            "expect_bucket": "paid_ad",
                            "note": f"ad_lexicon×{len(hits)}: " + blob[:120],
                            "slot": slot,
                            "channel": guide.get("name"),
                            "source": "gold_candidate",
                            "gold": False,
                            "ask": "confirm_gold",
                        }
                    )
            t += 12.0
            if len(out) >= 40:
                return out
    return out
