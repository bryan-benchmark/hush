"""Continuous farm worker: always save captures; periodically Ollama-label.

/farm is always the help desk — drafts that need a human are promoted into the queue.
Backlog warn/critical means the pile is large, not that you should ignore /farm until then.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import data_root, ensure_data_layout
from .coverage_farm import farm_label_dir, streamers_capture_root
from .farm_archive import iter_takes, prepare_take, write_package_index
from .farm_draft import draft_queue
from .farm_import import import_pending_sessions

# Backlog thresholds (takes / draft clips) before we call for human or more GPU.
WARN_UNPREPARED_TAKES = 3
WARN_REVIEW_ASKS = 40
CRITICAL_REVIEW_ASKS = 120
CRITICAL_UNPREPARED_TAKES = 10


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _take_prepared(session_dir: Path) -> bool:
    return (session_dir / "label_manifest.json").is_file() and (
        (session_dir / "timeline_facts.jsonl").is_file()
    )


def backlog_report(root: Path | None = None) -> dict[str, Any]:
    root = root or data_root()
    takes = iter_takes(root)
    unprepared = [str(t) for t in takes if not _take_prepared(t)]
    label_dir = farm_label_dir(root)
    review_asks = 0
    needs_human_asks = 0
    auto_n = 0
    key_path = label_dir / "key.jsonl"
    if key_path.is_file():
        for line in key_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            ask = str(row.get("ask") or "")
            # Count only model-scored (or human) asks — ignore import stubs.
            scored = bool(row.get("model")) or str(row.get("confidence") or "") not in {
                "",
                "aid",
            }
            if ask == "needs_human":
                needs_human_asks += 1
            if ask == "review" and scored:
                review_asks += 1
            if ask == "optional_confirm":
                auto_n += 1
    grab_path = label_dir / "take_judgments.json"
    grab_takes = 0
    if grab_path.is_file():
        grabs = json.loads(grab_path.read_text(encoding="utf-8"))
        grab_takes = sum(1 for v in grabs.values() if (v.get("regions") or []))

    help_asks = needs_human_asks + review_asks
    level = "ok"
    reasons: list[str] = []
    if len(unprepared) >= CRITICAL_UNPREPARED_TAKES or help_asks >= CRITICAL_REVIEW_ASKS:
        level = "critical"
        if len(unprepared) >= CRITICAL_UNPREPARED_TAKES:
            reasons.append("takes unprepared — overnight draft falling behind (GPU/time)")
        if help_asks >= CRITICAL_REVIEW_ASKS:
            reasons.append("help pile huge — clear DAILY_LABEL morning batch at /farm")
    elif len(unprepared) >= WARN_UNPREPARED_TAKES or help_asks >= WARN_REVIEW_ASKS:
        level = "warn"
        reasons.append("help queue growing — clear today's review_batch=active at /farm")
    elif help_asks > 0:
        reasons.append(f"{help_asks} clips need a human at /farm (model unsure or review)")

    return {
        "checked_utc": _now(),
        "takes_total": len(takes),
        "takes_unprepared": len(unprepared),
        "unprepared": unprepared[:20],
        "draft_review_asks": review_asks,
        "draft_needs_human": needs_human_asks,
        "draft_help_asks": help_asks,
        "draft_auto_optional": auto_n,
        "grab_labeled_takes": grab_takes,
        "level": level,
        "reasons": reasons,
        "human_needed": level in {"warn", "critical"} or help_asks > 0,
        # GPU helps draft/prepare — not clearing the human review pile.
        "more_gpu_needed": len(unprepared) >= CRITICAL_UNPREPARED_TAKES,
        "thresholds": {
            "warn_unprepared_takes": WARN_UNPREPARED_TAKES,
            "warn_review_asks": WARN_REVIEW_ASKS,
            "critical_unprepared_takes": CRITICAL_UNPREPARED_TAKES,
            "critical_review_asks": CRITICAL_REVIEW_ASKS,
        },
        "owner_action": (
            "Overnight drafts; morning clear review_batch=active at /farm "
            f"(~{CRITICAL_REVIEW_ASKS}+ help asks → spend the daily batch). "
            "Add GPU only when takes_unprepared stays high."
        ),
        "review_url": "http://127.0.0.1:3010/farm",
    }


def tick(
    root: Path | None = None,
    *,
    draft: bool = True,
    model: str = "qwen2.5:14b",
    draft_limit: int | None = 30,
    prepare: bool = True,
    delete_video: bool = True,
) -> dict[str, Any]:
    """One worker pass: import sessions → prepare → Ollama draft → backlog."""
    root = ensure_data_layout(root)
    imported = import_pending_sessions(root)
    prepared: list[dict[str, Any]] = []
    if prepare:
        for take in iter_takes(root):
            if _take_prepared(take):
                continue
            prepared.append(prepare_take(take, delete_video=delete_video, purge_stills=False))

    draft_out: dict[str, Any] | None = None
    draft_error: str | None = None
    if draft:
        queue = farm_label_dir(root) / "queue.jsonl"
        if not queue.is_file():
            from .coverage_farm import seed_queue_from_streamers_takes

            seed_queue_from_streamers_takes(root)
        try:
            draft_out = draft_queue(model=model, use_whisper=True, root=root, limit=draft_limit)
        except Exception as exc:  # noqa: BLE001
            draft_error = str(exc)
            draft_out = {"ok": False, "error": draft_error}

    pkg = write_package_index(root)
    backlog = backlog_report(root)
    cloud_sync: dict[str, Any] | None = None
    if os.environ.get("OHUSH_FARM_CLOUD_SYNC", "").strip() in {"1", "true", "yes"}:
        try:
            from .farm_cloud_sync import sync as farm_cloud_sync

            cloud_sync = farm_cloud_sync(root=root, limit=int(os.environ.get("OHUSH_FARM_CLOUD_LIMIT") or 80))
        except Exception as exc:  # noqa: BLE001
            cloud_sync = {"ok": False, "error": str(exc)}
    out = {
        "ok": draft_error is None and bool(imported.get("ok", True)),
        "ticked_utc": _now(),
        "imported": imported,
        "prepared": prepared,
        "draft": draft_out,
        "draft_error": draft_error,
        "package": pkg,
        "backlog": backlog,
        "cloud_sync": cloud_sync,
        "review_url": "http://127.0.0.1:3010/farm",
        "public_url": "https://ohush.co/farm",
    }
    path = streamers_capture_root(root) / "worker_tick.json"
    path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    backlog_path = streamers_capture_root(root) / "backlog.json"
    backlog_path.write_text(json.dumps(backlog, indent=2), encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="Farm worker: periodic Ollama labeling + backlog")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("backlog", help="Report unlabeled / review backlog")
    sub.add_parser("label-audit", help="Write LABEL_AUDIT.md contradiction/empty-evidence report")
    sub.add_parser("digest", help="Write DAILY_LABEL.md + refresh morning /farm batch")
    sub.add_parser("backfill-audit", help="Mirror key.jsonl into append-only label_draft.jsonl")
    sub.add_parser("enrich", help="Patch session/t0/t1 onto key+audit from queue (no GPU)")
    sub.add_parser(
        "retriage",
        help="90/10: stills_disagree+ASR → review; park silent needs_human; refresh morning batch",
    )
    sub.add_parser("sync-judgments", help="Lock key from take_judgments.json + refresh trust gate")
    rd = sub.add_parser(
        "redraft-weak",
        help="Re-draft unscored + uncertain/low clips (full Whisper/vision audit)",
    )
    rd.add_argument("--limit", type=int, default=80)
    tk = sub.add_parser("tick", help="Prepare new takes + draft with Ollama + backlog")
    tk.add_argument("--model", default="qwen2.5:14b")
    tk.add_argument("--limit", type=int, default=30, help="Max new drafts this tick")
    tk.add_argument("--no-draft", action="store_true")
    tk.add_argument("--no-prepare", action="store_true")
    tk.add_argument("--keep-video", action="store_true")
    args = p.parse_args(argv)
    root = data_root()
    if args.cmd == "backlog":
        print(json.dumps(backlog_report(root), indent=2))
        return 0
    if args.cmd == "label-audit":
        from .label_audit_report import main as label_audit_main
        return label_audit_main()
    if args.cmd == "digest":
        from .farm_draft import promote_help_queue
        from .farm_label_audit import refresh_trust_gate, write_daily_digest

        batch = promote_help_queue(root)
        trust = refresh_trust_gate(root)
        digest = write_daily_digest(root)
        print(json.dumps({"digest": digest, "queue": batch, "trust_gate": trust}, indent=2, default=str))
        return 0
    if args.cmd == "backfill-audit":
        from .farm_label_audit import backfill_draft_audit, write_daily_digest

        out = backfill_draft_audit(root)
        out["daily"] = write_daily_digest(root)
        print(json.dumps(out, indent=2, default=str))
        return 0
    if args.cmd == "enrich":
        from .farm_label_audit import enrich_keys_from_queue, write_daily_digest

        out = enrich_keys_from_queue(root)
        out["daily"] = write_daily_digest(root)
        print(json.dumps(out, indent=2, default=str))
        return 0
    if args.cmd == "retriage":
        from .farm_label_audit import retriage_needs_human, write_daily_digest

        out = retriage_needs_human(root)
        out["daily"] = write_daily_digest(root)
        print(json.dumps(out, indent=2, default=str))
        return 0
    if args.cmd == "redraft-weak":
        from .farm_draft import draft_queue
        from .farm_label_audit import write_daily_digest

        # only_unscored path also re-visits uncertain+low for a real audited tick.
        out = draft_queue(
            root=root,
            limit=args.limit,
            only_unscored=True,
            use_whisper=True,
            use_vision=True,
        )
        out["daily"] = write_daily_digest(root)
        print(json.dumps(out, indent=2, default=str))
        return 0
    if args.cmd == "sync-judgments":
        from .farm_draft import promote_help_queue
        from .farm_label_audit import sync_judgments_to_locks, write_daily_digest

        out = sync_judgments_to_locks(root)
        out["queue"] = promote_help_queue(root)
        out["daily"] = write_daily_digest(root)
        print(json.dumps(out, indent=2, default=str))
        return 0
    if args.cmd == "tick":
        print(
            json.dumps(
                tick(
                    root,
                    draft=not args.no_draft,
                    model=args.model,
                    draft_limit=args.limit,
                    prepare=not args.no_prepare,
                    delete_video=not args.keep_video,
                ),
                indent=2,
            )
        )
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
