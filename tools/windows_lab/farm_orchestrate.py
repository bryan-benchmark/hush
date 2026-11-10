"""Three farm operations.

1. RECORD  — hierarchy + guide windows → prioritize what to capture next
2. LABEL   — open-source model drafts; track how far behind we are
3. HUMAN   — /farm grab only when required (backlog / model trouble)

Always save captures. Ollama runs periodically. Owner intervenes on gate only.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import data_root, ensure_data_layout
from .coverage_farm import (
    build_capture_plan,
    build_coverage_board,
    capacity_report,
    capture_plan_path,
    coverage_board_md_path,
    dispatch_report,
    hierarchy_snapshot,
    indexes_dir,
)
from .farm_worker import backlog_report, tick as label_tick
from .streamers_lag import CLEAN_CONCURRENT, scan_recent_lag

REVIEW_URL = "http://127.0.0.1:3010/farm"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def op1_record(root: Path | None = None, *, chunk_minutes: int = 20) -> dict[str, Any]:
    """Autonomous recording plan: what we need, when live windows hit, what to prioritize."""
    root = ensure_data_layout(root)
    hier = hierarchy_snapshot()
    plan = build_capture_plan(root, chunk_minutes=chunk_minutes)
    board = build_coverage_board(root)
    capacity = capacity_report(root)
    dispatch = dispatch_report(root, dry_run=True)
    upcoming = [w for w in (plan.get("live_windows") or []) if not w.get("active_now")]
    active = [w for w in (plan.get("live_windows") or []) if w.get("active_now")]
    lag = scan_recent_lag(root)
    # Streamers lags on one already — never plan past clean concurrent.
    max_conc = min(
        int(capacity.get("max_concurrent_streamers") or CLEAN_CONCURRENT),
        CLEAN_CONCURRENT,
    )
    return {
        "op": 1,
        "name": "record",
        "updated_utc": _now(),
        "summary": (
            "Find hierarchy gaps, use guide/live windows for availability, "
            "assign ready instances to highest priority on-air targets. "
            "Watch Streamers lag (cap ≤2; wait+re-dump before taps)."
        ),
        "hierarchy": hier,
        "live_active": active,
        "live_upcoming": upcoming,
        "assignments": plan.get("assignments") or [],
        "coverage_gaps": plan.get("coverage_gaps") or [],
        "capacity": {
            "ready_instances": capacity.get("ready_count"),
            "max_concurrent": max_conc,
            "isolation_ok": (capacity.get("isolation") or {}).get("ok"),
            "streamers_lag_cap": CLEAN_CONCURRENT,
        },
        "streamers_lag": {
            "overall": lag.get("overall"),
            "sessions_scanned": lag.get("sessions_scanned"),
            "recent": (lag.get("recent") or [])[:5],
            "rule": lag.get("rule"),
            "ui_ops": lag.get("ui_ops"),
            "avoid_third_instance": True,
        },
        "dispatch_steps": len(dispatch.get("steps") or []),
        "paths": {
            "capture_plan": str(capture_plan_path(root)),
            "board_md": str(coverage_board_md_path(root)),
            "dispatch": str(indexes_dir(root) / "capture_dispatch.json"),
        },
        "next": (
            "Tune with a fresh UI dump after Streamers settles (lag makes dumps stale). "
            "No EXAMPLE recipe. session start --no-channel-apply once picture is live. "
            "Keep ≤2 concurrent instances."
        ),
    }


def op2_label(
    root: Path | None = None,
    *,
    run_tick: bool = False,
    model: str = "qwen2.5:14b",
    draft_limit: int = 30,
) -> dict[str, Any]:
    """Autonomous open-source labeling + how far behind we are."""
    root = ensure_data_layout(root)
    tick_out = None
    if run_tick:
        tick_out = label_tick(
            root,
            draft=True,
            model=model,
            draft_limit=draft_limit,
            prepare=True,
            delete_video=True,
        )
    backlog = backlog_report(root)
    behind = {
        "takes_unprepared": backlog.get("takes_unprepared"),
        "draft_review_asks": backlog.get("draft_review_asks"),
        "level": backlog.get("level"),
        "more_gpu_needed": backlog.get("more_gpu_needed"),
    }
    return {
        "op": 2,
        "name": "label",
        "updated_utc": _now(),
        "summary": (
            "Whisper + qwen2.5:14b draft unlabeled takes. Track backlog distance. "
            "Auto-accept only clear paid_ad."
        ),
        "model": model,
        "behind": behind,
        "backlog": backlog,
        "tick": tick_out,
        "next": (
            "Run periodically: python -m tools.windows_lab farm label --tick. "
            "If level is warn/critical, see op3 human."
        ),
    }


def op3_human(root: Path | None = None) -> dict[str, Any]:
    """Human-in-the-loop — /farm is always the help desk for model-unsure clips."""
    backlog = backlog_report(root)
    required = bool(backlog.get("human_needed"))
    help_n = int(backlog.get("draft_help_asks") or 0)
    return {
        "op": 3,
        "name": "human",
        "updated_utc": _now(),
        "summary": "Label at /farm whenever the open-source draft needs help; warn when the pile is large.",
        "required": required,
        "reason": (
            backlog.get("reasons")
            or (["backlog ok — no help clips waiting"] if help_n == 0 else [f"{help_n} help clips at /farm"])
        ),
        "review_url": REVIEW_URL,
        "how": (
            "Open review_url. Pick what each clip is, optional note, Add, Done. "
            "Model-unsure clips stay at the front of the queue after each draft tick."
        ),
        "backlog_level": backlog.get("level"),
        "help_asks": help_n,
    }


def orchestrate_status(root: Path | None = None) -> dict[str, Any]:
    """Single dashboard for all three operations."""
    root = ensure_data_layout(root)
    record = op1_record(root)
    label = op2_label(root, run_tick=False)
    human = op3_human(root)
    out = {
        "updated_utc": _now(),
        "operations": {
            "1_record": {
                "daypart": (record.get("hierarchy") or {}).get("daypart"),
                "live_preempt": bool(record.get("live_active")),
                "assignments": len(record.get("assignments") or []),
                "ready_instances": (record.get("capacity") or {}).get("ready_instances"),
                "top": (record.get("assignments") or [{}])[0].get("channel_id"),
                "streamers_lag": (record.get("streamers_lag") or {}).get("overall"),
            },
            "2_label": {
                "behind": label.get("behind"),
                "human_needed": (label.get("backlog") or {}).get("human_needed"),
                "more_gpu_needed": (label.get("behind") or {}).get("more_gpu_needed"),
            },
            "3_human": {
                "required": human.get("required"),
                "review_url": human.get("review_url"),
                "reason": human.get("reason"),
            },
        },
        "record": record,
        "label": label,
        "human": human,
        "loop": [
            "1) farm record  — plan/prioritize captures from hierarchy + guide windows",
            "2) farm label --tick — prepare + Ollama; watch behind.*",
            "3) farm human — open /farm only when required=true",
        ],
    }
    path = indexes_dir(root) / "farm_orchestrate.json"
    path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="Farm orchestration (record / label / human)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="Dashboard for all three operations")
    sub.add_parser("orchestrate", help="Alias for status")

    r = sub.add_parser("record", help="Op1: hierarchy + guide plan + dispatch")
    r.add_argument("--chunk-minutes", type=int, default=20)

    lab = sub.add_parser("label", help="Op2: backlog + optional Ollama tick")
    lab.add_argument("--tick", action="store_true", help="Run prepare+draft this pass")
    lab.add_argument("--model", default="qwen2.5:14b")
    lab.add_argument("--limit", type=int, default=30)

    sub.add_parser("human", help="Op3: whether /farm is required right now")

    args = p.parse_args(argv)
    root = data_root()

    if args.cmd in {"status", "orchestrate"}:
        print(json.dumps(orchestrate_status(root), indent=2))
        return 0
    if args.cmd == "record":
        print(json.dumps(op1_record(root, chunk_minutes=args.chunk_minutes), indent=2))
        return 0
    if args.cmd == "label":
        print(
            json.dumps(
                op2_label(
                    root,
                    run_tick=bool(args.tick),
                    model=args.model,
                    draft_limit=args.limit,
                ),
                indent=2,
            )
        )
        return 0
    if args.cmd == "human":
        print(json.dumps(op3_human(root), indent=2))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
