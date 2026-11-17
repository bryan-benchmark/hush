"""Drain prepared-session hops backlog via multichannel + consensus.

Intended for capture_pause days and overnight catch-up:

  python -m tools.windows_lab.farm_verdict_backfill --batch 2
  python -m tools.windows_lab.farm_verdict_backfill --batch 1 --until-hour-et 6

Each batch appends a verdict_ticks.jsonl audit row. Holds farm_label_lock
so FarmLoop cannot stack a second pass.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from .capture_pause import is_paused
from .farm_label_lock import acquire as acquire_label_lock
from .farm_label_lock import release as release_label_lock
from .farm_label_lock import status as label_lock_status
from .farm_multichannel_pass import run as multichannel_run
from .farm_verdict_audit import append_verdict_tick, write_overnight_board
from .farm_worker import backlog_report

ET = ZoneInfo("America/New_York")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ollama_ok() -> dict[str, Any]:
    try:
        import urllib.request

        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=3) as resp:
            ok = 200 <= int(resp.status) < 300
            return {"ok": ok, "status": int(resp.status)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def run_batches(
    *,
    batch: int = 2,
    max_batches: int | None = None,
    hop_s: float = 5.0,
    require_pause: bool = False,
    until_hour_et: int | None = None,
    sleep_s: float = 2.0,
    trigger: str = "backfill",
) -> dict[str, Any]:
    lock = acquire_label_lock(reason=f"verdict_backfill:{trigger}")
    if not lock.get("ok"):
        tick = {
            "utc": _now(),
            "ok": True,
            "trigger": trigger,
            "skip_reason": "label_pass_busy",
            "label_lock": label_lock_status(),
            "why": "another multichannel pass holds the single-flight lock",
        }
        append_verdict_tick(tick)
        return {"ok": True, "batches": 0, "skipped": tick, "lock": lock}

    ollama = _ollama_ok()
    if not ollama.get("ok"):
        append_verdict_tick(
            {
                "utc": _now(),
                "ok": False,
                "trigger": trigger,
                "skip_reason": "ollama_down",
                "error": ollama.get("error") or ollama,
                "why": "Ollama not reachable at :11434 — vision/ASR pass cannot run",
            }
        )
        release_label_lock()
        return {"ok": False, "batches": 0, "ollama": ollama}

    results: list[dict[str, Any]] = []
    n = 0
    try:
        while True:
            if require_pause and not is_paused().get("active"):
                break
            if until_hour_et is not None and datetime.now(ET).hour >= int(until_hour_et):
                break
            if max_batches is not None and n >= max_batches:
                break
            help_before = int(backlog_report().get("draft_help_asks") or 0)
            try:
                multi = multichannel_run(
                    all_prepared=True,
                    limit=int(batch),
                    hop_s=float(hop_s),
                    apply_consensus=True,
                )
                err = None
                ok = True
            except Exception as exc:  # noqa: BLE001
                multi = {}
                err = str(exc)
                ok = False
            help_after = int(backlog_report().get("draft_help_asks") or 0)
            tick = {
                "utc": _now(),
                "mode": multi.get("mode") or "all_prepared",
                "ok": ok,
                "trigger": trigger,
                "sessions": multi.get("sessions") or [],
                "sessions_n": len(multi.get("sessions") or []),
                "consensus_locked": multi.get("consensus_locked_total"),
                "disagree_hops": multi.get("disagree_hops_total"),
                "triage_episodes": multi.get("triage_episodes"),
                "help_asks_before": help_before,
                "help_asks_after": help_after,
                "receipt": multi.get("receipt"),
                "error": err,
                "why": "verdict_backfill_batch",
            }
            append_verdict_tick(tick)
            results.append(tick)
            n += 1
            print(
                json.dumps({"batch": n, **{k: tick[k] for k in tick if k != "sessions"}}, default=str),
                flush=True,
            )
            from .farm_verdict_audit import _audit_coverage

            cov = _audit_coverage()
            if not ok:
                break
            if cov.get("missing_hops", 0) <= 0:
                break
            if sleep_s > 0:
                time.sleep(float(sleep_s))
    finally:
        release_label_lock()

    board = write_overnight_board()
    return {
        "ok": True,
        "batches": n,
        "results": results,
        "board": board.get("day_et"),
        "help_asks_now": board.get("help_asks_now"),
        "coverage": board.get("coverage"),
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Continuous verdict multichannel backfill")
    p.add_argument("--batch", type=int, default=2, help="Sessions per multichannel pass")
    p.add_argument("--max-batches", type=int, default=None)
    p.add_argument("--hop-s", type=float, default=5.0)
    p.add_argument("--require-pause", action="store_true", help="Stop when capture_pause clears")
    p.add_argument(
        "--until-hour-et",
        type=int,
        default=None,
        help="Stop when local ET hour >= this (overnight use 6)",
    )
    p.add_argument("--sleep-s", type=float, default=2.0)
    p.add_argument("--trigger", type=str, default="backfill")
    args = p.parse_args(argv)
    out = run_batches(
        batch=int(args.batch),
        max_batches=args.max_batches,
        hop_s=float(args.hop_s),
        require_pause=bool(args.require_pause),
        until_hour_et=args.until_hour_et,
        sleep_s=float(args.sleep_s),
        trigger=str(args.trigger),
    )
    print(json.dumps({k: out[k] for k in out if k != "results"}, indent=2, default=str))
    return 0 if out.get("ok") is not False else 1


if __name__ == "__main__":
    raise SystemExit(main())
