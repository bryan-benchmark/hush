"""Append-only label audit + daily review digest.

Ideal daily loop:
1. Overnight (00–06 ET): draft clips → append every decision to label_draft.jsonl
2. Dawn: write DAILY_LABEL.md / daily_label.json (counts + today's review batch)
3. Morning human: clear only the active batch at /farm (needs_human, then high-value review)
4. Rest of the pile stays parked until the next digest

key.jsonl remains the live snapshot; label_draft.jsonl is the audit trail.
"""

from __future__ import annotations

import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .coverage_farm import farm_label_dir

ET = ZoneInfo("America/New_York")
# How many help clips the owner should clear each morning before the pile grows again.
MORNING_REVIEW_BUDGET = 50
DRAFT_LOG_NAME = "label_draft.jsonl"
DAILY_JSON = "daily_label.json"
DAILY_MD = "DAILY_LABEL.md"


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today_et(now: datetime | None = None) -> str:
    local = (now or datetime.now(ET)).astimezone(ET)
    return local.date().isoformat()


def atomic_write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    """Crash-safe rewrite: temp in same dir, then replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    try:
        with tmp.open("w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.is_file():
            try:
                tmp.unlink()
            except OSError:
                pass


def append_draft_events(
    events: list[dict[str, Any]],
    root: Path | None = None,
    *,
    tick_id: str | None = None,
) -> Path:
    """Append one JSON object per drafted clip (never rewrite history)."""
    label_dir = farm_label_dir(root)
    path = label_dir / DRAFT_LOG_NAME
    label_dir.mkdir(parents=True, exist_ok=True)
    tick = tick_id or _now_utc()
    with path.open("a", encoding="utf-8") as fh:
        for ev in events:
            row = {
                "utc": ev.get("utc") or _now_utc(),
                "tick_id": tick,
                "clip": ev.get("clip"),
                "session": ev.get("session"),
                "t0": ev.get("t0"),
                "t1": ev.get("t1"),
                "ask": ev.get("ask"),
                "bucket": ev.get("bucket"),
                "kind": ev.get("kind"),
                "confidence": ev.get("confidence"),
                "why": (str(ev.get("why") or ""))[:240] or None,
                "model": ev.get("model"),
                "vision_source": ev.get("vision_source"),
                "text_source": ev.get("text_source"),
                "asr_empty": ev.get("asr_empty"),
                "stills_agree": ev.get("stills_agree"),
                "prior_ask": ev.get("prior_ask"),
                "prior_bucket": ev.get("prior_bucket"),
            }
            row = {k: v for k, v in row.items() if v is not None}
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        fh.flush()
    return path


def review_priority(key: dict[str, Any]) -> int | None:
    """Lower = sooner in /farm. None = leave existing priority alone.

    90/10 order: easy confirms (high paid_ad) before hard needs_human empties.
    """
    ask = str(key.get("ask") or "")
    if key.get("gold") or ask == "locked" or key.get("source") in {"gold", "human"}:
        return None
    bucket = str(key.get("bucket") or "")
    conf = str(key.get("confidence") or "")
    why = str(key.get("why") or "")
    has_asr = bool(str(key.get("whisper_text") or "").strip()) and not key.get("asr_empty")

    if ask == "skip":
        return 99
    if ask == "optional_confirm":
        return 90
    # Easy fruit first — grow gold / trust.
    if ask == "review" and bucket == "paid_ad" and conf == "high":
        return 8
    if ask == "review" and bucket == "paid_ad":
        return 9
    if ask == "review" and bucket == "program" and conf == "high":
        return 10
    if ask == "review" and conf == "high":
        return 12
    if ask == "review" and conf == "medium":
        return 16
    if ask == "review" and bucket == "uncertain":
        return 24
    if ask == "review":
        return 20
    if ask == "needs_human":
        # Empty/silent windows — park; boundaries with no ASR — later.
        if "no_transcript_and_no_visual" in why:
            return 48
        if "stills_disagree" in why and not has_asr:
            return 36
        if "stills_disagree" in why and has_asr:
            return 22  # should be rare after retriage
        return 28
    return None


def apply_morning_batch(
    queue_rows: list[dict[str, Any]],
    *,
    budget: int = MORNING_REVIEW_BUDGET,
    day_et: str | None = None,
) -> dict[str, Any]:
    """Mark today's active review batch; park the rest so /farm is finishable."""
    day = day_et or _today_et()
    help_idxs = [
        i
        for i, row in enumerate(queue_rows)
        if str(row.get("ask") or "") in {"needs_human", "review"}
        and int(row.get("priority") or 99) < 80
    ]
    help_idxs.sort(
        key=lambda i: (
            int(queue_rows[i].get("priority") or 99),
            str(queue_rows[i].get("session") or ""),
            float(queue_rows[i].get("t0") or 0),
        )
    )
    active = set(help_idxs[: max(0, budget)])
    for i, row in enumerate(queue_rows):
        ask = str(row.get("ask") or "")
        if ask not in {"needs_human", "review"}:
            row.pop("review_batch", None)
            row.pop("review_day", None)
            continue
        if i in active:
            row["review_batch"] = "active"
            row["review_day"] = day
        else:
            # Park behind today's batch without losing ask metadata.
            row["review_batch"] = "parked"
            row["review_day"] = day
            row["priority"] = max(int(row.get("priority") or 99), 40)
    return {
        "day_et": day,
        "budget": budget,
        "active": len(active),
        "parked": max(0, len(help_idxs) - len(active)),
        "help_total": len(help_idxs),
    }


def write_daily_digest(root: Path | None = None, *, budget: int = MORNING_REVIEW_BUDGET) -> dict[str, Any]:
    """Snapshot overnight drafts + today's review batch for the owner."""
    from .farm_worker import backlog_report

    label_dir = farm_label_dir(root)
    day = _today_et()
    draft_path = label_dir / DRAFT_LOG_NAME
    asks: Counter[str] = Counter()
    buckets: Counter[str] = Counter()
    drafted_today = 0
    if draft_path.is_file():
        for line in draft_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            utc = str(row.get("utc") or "")
            try:
                when = datetime.fromisoformat(utc.replace("Z", "+00:00")).astimezone(ET)
            except ValueError:
                continue
            # Overnight 00–06 ET and any later same-day drafts roll into this morning's digest.
            if when.date().isoformat() != day:
                continue
            drafted_today += 1
            asks[str(row.get("ask") or "?")] += 1
            buckets[str(row.get("bucket") or "?")] += 1

    backlog = backlog_report(root)
    payload = {
        "day_et": day,
        "updated_utc": _now_utc(),
        "review_url": "http://127.0.0.1:3010/farm",
        "overnight_drafted": drafted_today,
        "asks": dict(asks),
        "buckets": dict(buckets.most_common(12)),
        "backlog": {
            "level": backlog.get("level"),
            "help_asks": backlog.get("draft_help_asks"),
            "needs_human": backlog.get("draft_needs_human"),
            "review": backlog.get("draft_review_asks"),
            "takes_unprepared": backlog.get("takes_unprepared"),
            "more_gpu_needed": backlog.get("more_gpu_needed"),
        },
        "morning_batch": {
            "budget": budget,
            "instruction": (
                f"Open /farm and clear the top {budget} (review_batch=active). "
                "Order: needs_human → paid_ad high → program high → rest."
            ),
        },
        "audit_path": str(draft_path),
        "key_path": str(label_dir / "key.jsonl"),
    }
    label_dir.mkdir(parents=True, exist_ok=True)
    (label_dir / DAILY_JSON).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    verdict_board = label_dir / "OVERNIGHT_VERDICT.md"
    verdict_note = (
        f"- Verdict overnight board: `{verdict_board}` (02:00–06:00 ET standard)"
        if verdict_board.is_file()
        else "- Verdict overnight board: run multichannel/backfill to create OVERNIGHT_VERDICT.md"
    )
    lines = [
        f"# Daily label — {day} ET",
        "",
        f"- Overnight drafted (legacy Ollama audit): **{drafted_today}**",
        verdict_note,
        f"- Help pile (legacy farm): **{backlog.get('draft_help_asks')}** "
        f"(needs_human {backlog.get('draft_needs_human')}, review {backlog.get('draft_review_asks')})",
        f"- Unprepared takes: **{backlog.get('takes_unprepared')}**",
        f"- Level: **{backlog.get('level')}**",
        f"- Owner desk: **http://127.0.0.1:3020/** (/verdict). "
        f"Legacy morning farm batch (~{budget}) only while pile drains.",
        "",
        "## Asks overnight",
    ]
    for k, v in asks.most_common():
        lines.append(f"- `{k}`: {v}")
    lines.extend(["", "## Buckets overnight"])
    for k, v in buckets.most_common(12):
        lines.append(f"- `{k}`: {v}")
    lines.extend(
        [
            "",
            "## Audit",
            f"- Append-only: `{draft_path}`",
            f"- Live snapshot: `{label_dir / 'key.jsonl'}`",
            "",
        ]
    )
    (label_dir / DAILY_MD).write_text("\n".join(lines), encoding="utf-8")
    return payload


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file() or path.stat().st_size == 0:
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def retriage_needs_human(root: Path | None = None) -> dict[str, Any]:
    """90/10 offline: boundary+ASR → review; black+silent / A/V desync → skip. No GPU."""
    from .farm_draft import (
        apply_common_sense,
        detect_av_content_desync,
        is_black_or_corrupt_still,
        nearest_still,
        promote_help_queue,
    )

    label_dir = farm_label_dir(root)
    key_path = label_dir / "key.jsonl"
    queue_path = label_dir / "queue.jsonl"
    keys = {str(r.get("clip")): r for r in _read_jsonl(key_path) if r.get("clip")}
    queue = {str(r.get("clip")): r for r in _read_jsonl(queue_path) if r.get("clip")}
    lifted = 0
    rescued = 0
    skipped = 0
    skipped_desync = 0
    events: list[dict[str, Any]] = []
    tick = f"retriage:{_now_utc()}"
    for clip, key in list(keys.items()):
        ask = str(key.get("ask") or "")
        # Retriage needs_human + review (desync skip); leave locked alone.
        if ask not in {"needs_human", "review"}:
            continue
        why = str(key.get("why") or "")
        text = str(key.get("whisper_text") or "")
        vis = str(key.get("visual_text") or "")
        prior_ask = key.get("ask")
        prior_bucket = key.get("bucket")
        q = queue.get(clip) or {}
        sd = Path(str(q.get("session_dir") or ""))
        t0 = float(key.get("t0") if key.get("t0") is not None else q.get("t0") or 0)
        t1 = float(key.get("t1") if key.get("t1") is not None else q.get("t1") or (t0 + 10))

        # 90/10: picture ad + early program ASR (or reverse) → skip like A/V lag.
        if text.strip() and vis.strip() and "skip_av_desync" not in why:
            desync = detect_av_content_desync(
                head_text=text[:400],
                visual=vis,
                still_classes=list(key.get("still_classes") or []),
                span_s=float(t1 - t0),
            )
            if desync:
                key = {
                    **key,
                    "ask": "skip",
                    "why": f"{desync['why']} | retriage",
                    "bucket": "uncertain",
                    "confidence": "low",
                    "av_desync": desync.get("kind"),
                    "retriaged_utc": tick,
                }
                keys[clip] = key
                skipped += 1
                skipped_desync += 1
                events.append(
                    {
                        "utc": tick,
                        "clip": clip,
                        "session": key.get("session"),
                        "t0": key.get("t0"),
                        "t1": key.get("t1"),
                        "ask": "skip",
                        "bucket": "uncertain",
                        "why": key.get("why"),
                        "prior_ask": prior_ask,
                        "prior_bucket": prior_bucket,
                    }
                )
                continue

        if ask != "needs_human":
            continue

        # Black / corrupt + no ASR → skip (throw out of /farm).
        if not text.strip():
            still = Path(str(key["still"])) if key.get("still") else None
            if still is None and sd.is_dir():
                still = nearest_still(sd, 0.5 * (t0 + t1))
            dead = is_black_or_corrupt_still(still)
            if dead in {"black", "green_corrupt"} or (
                "no_transcript_and_no_visual" in why and (still is None or not still.is_file())
            ):
                tag = dead or "black"
                key = {
                    **key,
                    "ask": "skip",
                    "why": f"skip_{tag}_silent | retriage",
                    "bucket": "uncertain",
                    "confidence": "low",
                    "retriaged_utc": tick,
                }
                keys[clip] = key
                skipped += 1
                events.append(
                    {
                        "utc": tick,
                        "clip": clip,
                        "session": key.get("session"),
                        "t0": key.get("t0"),
                        "t1": key.get("t1"),
                        "ask": "skip",
                        "bucket": "uncertain",
                        "why": key.get("why"),
                        "prior_ask": prior_ask,
                        "prior_bucket": prior_bucket,
                    }
                )
                continue
            # Real picture but empty ASR/vision — leave needs_human for possible redraft.
            if "stills_disagree" not in why:
                continue

        if "stills_disagree" not in why:
            continue
        if not text.strip():
            continue
        draft = {
            "bucket": str(key.get("bucket") or "uncertain"),
            "kind": str(key.get("kind") or "unknown"),
            "confidence": str(key.get("confidence") or "low"),
            "why": why,
        }
        draft = apply_common_sense(draft, text, vis)
        key = {
            **key,
            "bucket": draft["bucket"],
            "kind": draft["kind"],
            "confidence": draft["confidence"],
            "why": (str(draft.get("why") or why)[:180] + " | retriage:boundary_with_asr").strip(),
            "ask": "review",
            "retriaged_utc": tick,
        }
        if draft["bucket"] != "uncertain" and draft["bucket"] != prior_bucket:
            rescued += 1
        keys[clip] = key
        lifted += 1
        events.append(
            {
                "utc": tick,
                "clip": clip,
                "session": key.get("session"),
                "t0": key.get("t0"),
                "t1": key.get("t1"),
                "ask": "review",
                "bucket": key.get("bucket"),
                "kind": key.get("kind"),
                "confidence": key.get("confidence"),
                "why": key.get("why"),
                "model": key.get("model"),
                "prior_ask": prior_ask,
                "prior_bucket": prior_bucket,
            }
        )
    if lifted or skipped:
        atomic_write_jsonl(key_path, list(keys.values()))
        append_draft_events(events, root=root, tick_id=tick)
    queue = promote_help_queue(root)
    return {
        "ok": True,
        "lifted_to_review": lifted,
        "lexicon_rescued": rescued,
        "skipped_black_silent": skipped - skipped_desync,
        "skipped_av_desync": skipped_desync,
        "morning_batch": (queue or {}).get("morning_batch"),
        "queue": queue,
    }


def enrich_keys_from_queue(root: Path | None = None) -> dict[str, Any]:
    """Patch session/t0/t1 (and channel) onto key + audit from queue — no GPU.

    Pre-audit drafts were missing linkage; this makes /farm and label_draft.jsonl auditable.
    """
    label_dir = farm_label_dir(root)
    key_path = label_dir / "key.jsonl"
    queue_path = label_dir / "queue.jsonl"
    keys = {str(r.get("clip")): r for r in _read_jsonl(key_path) if r.get("clip")}
    queue = {str(r.get("clip")): r for r in _read_jsonl(queue_path) if r.get("clip")}
    patched = 0
    events: list[dict[str, Any]] = []
    tick = f"enrich:{_now_utc()}"
    for clip, key in keys.items():
        q = queue.get(clip)
        if not q:
            continue
        changed = False
        for field in ("session", "t0", "t1", "channel", "session_dir"):
            if key.get(field) in (None, "", "?") and q.get(field) not in (None, ""):
                key[field] = q.get(field)
                changed = True
        if not changed:
            continue
        keys[clip] = key
        patched += 1
        events.append(
            {
                "utc": tick,
                "clip": clip,
                "session": key.get("session"),
                "t0": key.get("t0"),
                "t1": key.get("t1"),
                "ask": key.get("ask"),
                "bucket": key.get("bucket"),
                "kind": key.get("kind"),
                "confidence": key.get("confidence"),
                "why": "enrich_from_queue",
                "model": key.get("model"),
                "prior_ask": key.get("ask"),
                "prior_bucket": key.get("bucket"),
            }
        )
    if patched:
        atomic_write_jsonl(key_path, list(keys.values()))
        # Also patch audit rows that lack session for these clips (append enrich events only).
        append_draft_events(events, root=root, tick_id=tick)
    return {"ok": True, "patched": patched, "key_n": len(keys), "queue_n": len(queue)}


def backfill_draft_audit(root: Path | None = None) -> dict[str, Any]:
    """One-shot: mirror existing key.jsonl rows into label_draft.jsonl if missing."""
    label_dir = farm_label_dir(root)
    key_path = label_dir / "key.jsonl"
    draft_path = label_dir / DRAFT_LOG_NAME
    keys = _read_jsonl(key_path)
    have = {str(r.get("clip")) for r in _read_jsonl(draft_path) if r.get("clip")}
    events: list[dict[str, Any]] = []
    tick = f"backfill:{_now_utc()}"
    for row in keys:
        clip = str(row.get("clip") or "")
        if not clip or clip in have:
            continue
        events.append(
            {
                "utc": row.get("drafted_utc") or _now_utc(),
                "clip": clip,
                "session": row.get("session"),
                "t0": row.get("t0"),
                "t1": row.get("t1"),
                "ask": row.get("ask"),
                "bucket": row.get("bucket"),
                "kind": row.get("kind"),
                "confidence": row.get("confidence"),
                "why": row.get("why") or "backfill_from_key",
                "model": row.get("model"),
                "vision_source": row.get("vision_source"),
                "text_source": row.get("text_source"),
                "asr_empty": row.get("asr_empty"),
                "stills_agree": row.get("stills_agree"),
                "prior_ask": None,
                "prior_bucket": None,
                "backfill": True,
            }
        )
        have.add(clip)
    if events:
        # Stamp backfill flag onto each append.
        for ev in events:
            ev.setdefault("why", "backfill_from_key")
        append_draft_events(events, root=root, tick_id=tick)
        # Re-open and tag backfill on the just-written lines is awkward; include in event via why.
    return {"ok": True, "backfilled": len(events), "audit_path": str(draft_path), "key_n": len(keys)}


def refresh_trust_gate(root: Path | None = None) -> dict[str, Any]:
    """Count locked gold/human clips; enable auto paid_ad at min_gold."""
    label_dir = farm_label_dir(root)
    key_path = label_dir / "key.jsonl"
    gold_n = 0
    for row in _read_jsonl(key_path):
        ask = str(row.get("ask") or "")
        if row.get("gold") or ask == "locked" or row.get("source") in {"gold", "human"}:
            if str(row.get("bucket") or "") != "uncertain":
                gold_n += 1
    path = label_dir / "trust_gate.json"
    prior: dict[str, Any] = {}
    if path.is_file():
        try:
            prior = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            prior = {}
    min_gold = int(prior.get("min_gold_for_auto") or 30)
    probe_ok = True
    probe_path = label_dir / "accuracy_probe_results.json"
    if probe_path.is_file():
        try:
            probe = json.loads(probe_path.read_text(encoding="utf-8"))
            prec = probe.get("precision")
            if prec is None and isinstance(probe.get("paid_ad"), dict):
                prec = probe["paid_ad"].get("precision")
            score = str(probe.get("accuracy_probe_score") or "")
            if prec is not None:
                probe_ok = float(prec) >= 0.85
            elif "/" in score:
                num, den = score.split("/", 1)
                probe_ok = (float(num) / float(den)) >= 0.85 if float(den) else True
        except (json.JSONDecodeError, TypeError, ValueError):
            probe_ok = True
    enabled = gold_n >= min_gold and probe_ok
    trust = {
        "gold_clips": gold_n,
        "auto_paid_ad_enabled": enabled,
        "min_gold_for_auto": min_gold,
        "probe_ok": probe_ok,
        "updated_utc": _now_utc(),
        "why": (
            "Auto paid_ad enabled"
            if enabled
            else (
                f"Auto paid_ad disabled until gold ≥{min_gold}"
                + ("" if probe_ok else " and probe precision ≥0.85")
            )
        ),
    }
    path.write_text(json.dumps(trust, indent=2) + "\n", encoding="utf-8")
    return trust


def apply_human_lock(
    clip: str,
    *,
    bucket: str,
    kind: str = "unknown",
    note: str = "",
    root: Path | None = None,
    regions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Lock one clip after /farm save; append audit; refresh trust gate."""
    label_dir = farm_label_dir(root)
    key_path = label_dir / "key.jsonl"
    keys = {str(r.get("clip")): r for r in _read_jsonl(key_path) if r.get("clip")}
    prior = dict(keys.get(clip) or {})
    is_gold = bucket != "uncertain"
    locked = {
        **prior,
        "clip": clip,
        "bucket": bucket,
        "kind": kind or prior.get("kind") or "unknown",
        "confidence": "high",
        "ask": "locked",
        "note": (note or prior.get("note") or "")[:240],
        "human_note": (note or "")[:240],
        "source": "human",
        "gold": is_gold,
        "model": prior.get("model"),
        "locked_from": "farm_human",
        "locked_utc": _now_utc(),
        "regions": regions or prior.get("regions"),
    }
    keys[clip] = locked
    atomic_write_jsonl(key_path, list(keys.values()))
    append_draft_events(
        [
            {
                "utc": locked["locked_utc"],
                "clip": clip,
                "session": locked.get("session"),
                "t0": locked.get("t0"),
                "t1": locked.get("t1"),
                "ask": "locked",
                "bucket": bucket,
                "kind": locked.get("kind"),
                "confidence": "high",
                "why": f"human_lock:{note or bucket}",
                "model": None,
                "prior_ask": prior.get("ask"),
                "prior_bucket": prior.get("bucket"),
            }
        ],
        root=root,
        tick_id=f"human:{locked['locked_utc']}",
    )
    # Drop from active morning batch in queue.
    queue_path = label_dir / "queue.jsonl"
    if queue_path.is_file():
        qrows = _read_jsonl(queue_path)
        changed = False
        for row in qrows:
            if str(row.get("clip")) != clip:
                continue
            row["ask"] = "locked"
            row["priority"] = 99
            row["review_batch"] = "done"
            changed = True
        if changed:
            atomic_write_jsonl(queue_path, qrows)
    trust = refresh_trust_gate(root)
    try:
        from .farm_ops import emit

        emit(
            "label_human_lock",
            detail=f"{clip}→{bucket}",
            ok=True,
            extra={"clip": clip, "bucket": bucket, "gold": is_gold, "trust": trust},
            root=root,
        )
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, "clip": clip, "locked": locked, "trust_gate": trust}


def sync_judgments_to_locks(root: Path | None = None) -> dict[str, Any]:
    """Apply take_judgments.json into key locks (idempotent)."""
    label_dir = farm_label_dir(root)
    path = label_dir / "take_judgments.json"
    if not path.is_file():
        return {"ok": True, "locked": 0, "skipped": 0}
    try:
        judgments = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"ok": False, "error": "bad take_judgments.json"}
    locked_n = 0
    skipped = 0
    for clip, judgment in judgments.items():
        regions = judgment.get("regions") or []
        if not regions:
            skipped += 1
            continue
        # Prefer first non-uncertain region; else first region.
        pick = next((r for r in regions if r.get("bucket") != "uncertain"), regions[0])
        key_rows = {str(r.get("clip")): r for r in _read_jsonl(label_dir / "key.jsonl") if r.get("clip")}
        prior = key_rows.get(str(clip)) or {}
        if prior.get("ask") == "locked" and prior.get("source") in {"human", "gold"}:
            skipped += 1
            continue
        apply_human_lock(
            str(clip),
            bucket=str(pick.get("bucket") or "uncertain"),
            kind=str(pick.get("kind") or "unknown"),
            note=str(pick.get("note") or ""),
            root=root,
            regions=regions,
        )
        locked_n += 1
    trust = refresh_trust_gate(root)
    return {"ok": True, "locked": locked_n, "skipped": skipped, "trust_gate": trust}
