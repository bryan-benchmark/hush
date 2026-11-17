"""Append-only audit for overnight / pause-day verdict multichannel ticks.

Writes:
  indexes/farm_labels/audit/verdict_ticks.jsonl   (one JSON object per tick)
  indexes/farm_labels/OVERNIGHT_VERDICT.md        (rolling human board)
  indexes/farm_labels/overnight_verdict.json      (latest snapshot)

Purpose: continuous root-cause — why a night labeled 0, skipped for lock,
RAM, or consensus locked N / disagree M.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .coverage_farm import farm_label_dir
from .farm_consensus import prepared_sessions

ET = ZoneInfo("America/New_York")
TICK_LOG = "verdict_ticks.jsonl"
BOARD_MD = "OVERNIGHT_VERDICT.md"
BOARD_JSON = "overnight_verdict.json"


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today_et() -> str:
    return datetime.now(ET).date().isoformat()


def append_verdict_tick(event: dict[str, Any], root: Path | None = None) -> Path:
    """Append one tick receipt; never rewrite history."""
    label = farm_label_dir(root)
    audit = label / "audit"
    audit.mkdir(parents=True, exist_ok=True)
    path = audit / TICK_LOG
    row = {
        "utc": event.get("utc") or _now_utc(),
        "day_et": event.get("day_et") or _today_et(),
        "mode": event.get("mode"),
        "ok": event.get("ok"),
        "trigger": event.get("trigger"),  # overnight | capture_pause | manual
        "sessions": event.get("sessions") or [],
        "sessions_n": event.get("sessions_n"),
        "consensus_locked": event.get("consensus_locked"),
        "disagree_hops": event.get("disagree_hops"),
        "triage_episodes": event.get("triage_episodes"),
        "help_asks_before": event.get("help_asks_before"),
        "help_asks_after": event.get("help_asks_after"),
        "label_gate": event.get("label_gate"),
        "skip_reason": event.get("skip_reason"),
        "error": event.get("error"),
        "receipt": event.get("receipt"),
        "memory_avail_gb": event.get("memory_avail_gb"),
        "why": event.get("why"),
    }
    row = {k: v for k, v in row.items() if v is not None}
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        fh.flush()
    write_overnight_board(root=root)
    return path


def _read_ticks(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
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


def _help_asks(root: Path | None = None) -> int:
    try:
        from .farm_worker import backlog_report

        return int(backlog_report(root).get("draft_help_asks") or 0)
    except Exception:
        return -1


def _audit_coverage(root: Path | None = None) -> dict[str, Any]:
    prepared = prepared_sessions(root)
    label = farm_label_dir(root)
    with_hops = 0
    for s in prepared:
        if (label / "audit" / s / "hops.jsonl").is_file():
            with_hops += 1
    return {
        "prepared_sessions": len(prepared),
        "with_hops": with_hops,
        "missing_hops": max(0, len(prepared) - with_hops),
    }


def _help_asks_by_session(root: Path | None = None) -> dict[str, int]:
    key_path = farm_label_dir(root) / "key.jsonl"
    counts: Counter[str] = Counter()
    if not key_path.is_file():
        return {}
    for line in key_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if str(row.get("ask") or "") not in {"review", "needs_human"}:
            continue
        s = str(row.get("session") or "")
        if s:
            counts[s] += 1
    return dict(counts)


def _channel_flags(session: str, label: Path) -> dict[str, bool]:
    d = label / "audit" / session
    vision = (d / "hops_vision.jsonl").is_file()
    acoustic = (d / "hops_acoustic.jsonl").is_file()
    combined = (d / "hops.jsonl").is_file()
    # ASR is written with the vision timeline; treat vision file as ASR done too.
    gold = (d / "CONSENSUS_LOCK.json").is_file()
    return {
        "vision": vision,
        "asr": vision,
        "acoustic": acoustic,
        "gold": gold,
        "combined": combined,
    }


def _session_next_step(flags: dict[str, bool]) -> str:
    if not flags.get("vision"):
        return "vision"
    if not flags.get("acoustic"):
        return "acoustic"
    if not flags.get("combined"):
        return "combine"
    if not flags.get("gold"):
        return "consensus"
    return "done"


def backlog_hierarchy(
    root: Path | None = None,
    *,
    live_job: dict[str, Any] | None = None,
    queue_limit: int = 40,
) -> dict[str, Any]:
    """Top-down backlog: pipeline → stages → per-session 4-channel status."""
    label = farm_label_dir(root)
    prepared = prepared_sessions(root)
    help_n = _help_asks_by_session(root)
    live = dict(live_job or {})
    live_session = str(live.get("session") or "") if live.get("active") else ""
    live_phase = str(live.get("phase") or "")

    sessions_out: list[dict[str, Any]] = []
    pipe = Counter()
    for s in prepared:
        flags = _channel_flags(s, label)
        for ch in ("vision", "asr", "acoustic", "gold"):
            if flags.get(ch):
                pipe[ch] += 1
        if flags.get("combined"):
            pipe["combined"] += 1
        nxt = _session_next_step(flags)
        status = "done" if nxt == "done" else "queued"
        if live_session and s == live_session:
            status = "running"
            nxt = live_phase or nxt
        d = label / "audit" / s
        locked_n = 0
        disagree = None
        n_hops = None
        lock_path = d / "CONSENSUS_LOCK.json"
        if lock_path.is_file():
            try:
                lock = json.loads(lock_path.read_text(encoding="utf-8"))
                locked_n = int(lock.get("locked_n") or 0)
                hs = lock.get("hop_summary") or {}
                disagree = hs.get("n_disagree_hops")
                n_hops = hs.get("n_hops")
            except (json.JSONDecodeError, TypeError, ValueError):
                pass
        if n_hops is None:
            meta = d / "meta_combined.json"
            if meta.is_file():
                try:
                    m = json.loads(meta.read_text(encoding="utf-8"))
                    n_hops = m.get("n_hops")
                    disagree = m.get("n_disagree") if disagree is None else disagree
                except (json.JSONDecodeError, TypeError, ValueError):
                    pass
        sessions_out.append(
            {
                "session": s,
                "help": int(help_n.get(s) or 0),
                "status": status,
                "next": nxt,
                "channels": {
                    "vision": flags["vision"],
                    "asr": flags["asr"],
                    "acoustic": flags["acoustic"],
                    "gold": flags["gold"],
                },
                "combined": flags["combined"],
                "locked_n": locked_n,
                "n_hops": n_hops,
                "n_disagree": disagree,
            }
        )

    # Queue order: running first, then missing work by help pile, then done.
    def _sort_key(row: dict[str, Any]) -> tuple:
        st = row["status"]
        rank = 0 if st == "running" else (2 if st == "done" else 1)
        return (rank, -int(row.get("help") or 0), str(row.get("session") or ""))

    sessions_out.sort(key=_sort_key)
    of_n = len(prepared)
    pipeline = []
    for ch, title in (
        ("vision", "Vision"),
        ("asr", "ASR"),
        ("acoustic", "Acoustic"),
        ("gold", "Gold / consensus"),
    ):
        done = int(pipe.get(ch) or 0)
        left = max(0, of_n - done)
        pct = round(100.0 * done / of_n, 1) if of_n else 0.0
        pipeline.append(
            {
                "id": ch,
                "label": title,
                "done": done,
                "of": of_n,
                "left": left,
                "pct": pct,
            }
        )

    need_vision = sum(1 for r in sessions_out if r["next"] == "vision" and r["status"] != "running")
    need_acoustic = sum(1 for r in sessions_out if r["next"] == "acoustic" and r["status"] != "running")
    need_combine = sum(1 for r in sessions_out if r["next"] == "combine" and r["status"] != "running")
    need_consensus = sum(1 for r in sessions_out if r["next"] == "consensus" and r["status"] != "running")
    done_n = sum(1 for r in sessions_out if r["status"] == "done" or r["next"] == "done")
    running_n = sum(1 for r in sessions_out if r["status"] == "running")

    return {
        "prepared_n": of_n,
        "pipeline": pipeline,
        "stages": {
            "running": running_n,
            "need_vision": need_vision,
            "need_acoustic": need_acoustic,
            "need_combine": need_combine,
            "need_consensus": need_consensus,
            "done": done_n,
            "left": max(0, of_n - done_n),
        },
        "queue": sessions_out[: max(1, int(queue_limit))],
        "queue_total": of_n,
        "queue_shown": min(of_n, max(1, int(queue_limit))),
        "help_by_queued_top": sum(int(r.get("help") or 0) for r in sessions_out if r["status"] != "done"),
    }


def write_overnight_board(root: Path | None = None) -> dict[str, Any]:
    """Refresh OVERNIGHT_VERDICT.md from today's ticks + coverage."""
    label = farm_label_dir(root)
    audit = label / "audit"
    ticks = _read_ticks(audit / TICK_LOG)
    day = _today_et()
    today = [t for t in ticks if str(t.get("day_et") or "") == day]
    skips = Counter(str(t.get("skip_reason") or "ran") for t in today)
    locked = sum(int(t.get("consensus_locked") or 0) for t in today)
    disagree = sum(int(t.get("disagree_hops") or 0) for t in today)
    errors = [t for t in today if t.get("error") or t.get("ok") is False]
    cov = _audit_coverage(root)
    help_n = _help_asks(root)
    last = today[-1] if today else (ticks[-1] if ticks else None)
    payload = {
        "day_et": day,
        "updated_utc": _now_utc(),
        "ticks_today": len(today),
        "consensus_locked_today": locked,
        "disagree_hops_today": disagree,
        "skip_reasons": dict(skips),
        "errors_today": len(errors),
        "help_asks_now": help_n,
        "coverage": cov,
        "last_tick": last,
        "review_url": "http://127.0.0.1:3020/",
        "farm_url": "http://127.0.0.1:3010/farm",
        "tick_log": str(audit / TICK_LOG),
        "standard": (
            "02:00–06:00 ET every night: multichannel consensus auto-locks; "
            "disagreements → /verdict. Capture pause also runs backfill."
        ),
    }
    label.mkdir(parents=True, exist_ok=True)
    (label / BOARD_JSON).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    lines = [
        f"# Overnight verdict — {day} ET",
        "",
        payload["standard"],
        "",
        f"- Updated: `{payload['updated_utc']}`",
        f"- Ticks today: **{len(today)}**",
        f"- Consensus locked today: **{locked}**",
        f"- Disagree hops seen today: **{disagree}**",
        f"- Help pile now: **{help_n}**",
        f"- Prepared sessions with hops: **{cov['with_hops']}/{cov['prepared_sessions']}** "
        f"(missing {cov['missing_hops']})",
        f"- Owner desk: {payload['review_url']} (legacy farm {payload['farm_url']})",
        "",
        "## Skip / run reasons today",
    ]
    for k, v in skips.most_common():
        lines.append(f"- `{k}`: {v}")
    if errors:
        lines.extend(["", "## Errors today"])
        for t in errors[-8:]:
            lines.append(f"- `{t.get('utc')}` {t.get('error') or t.get('skip_reason')}")
    lines.extend(
        [
            "",
            "## Last tick",
            "```json",
            json.dumps(last, indent=2, default=str) if last else "null",
            "```",
            "",
            "## Audit",
            f"- Append-only: `{audit / TICK_LOG}`",
            f"- Snapshot: `{label / BOARD_JSON}`",
            "",
            "## Root-cause checklist (if overnight locked 0)",
            "1. `skip_reason=live_audio_lock` — take still writing WAV past 02:00; wait or end job",
            "2. `skip_reason=label_pass_busy` — worker already running (OK if ticks continue)",
            "3. `skip_reason=ollama_down` — start Ollama / qwen2.5vl:7b",
            "4. `skip_reason=ram_pressure` — free RAM < label floor",
            "5. `hold_new_captures` in schedule_run_due.log — good (overnight must not start TV)",
            "6. `error` / missing hops — `work/logs/verdict_worker_*.log`",
            "",
        ]
    )
    (label / BOARD_MD).write_text("\n".join(lines), encoding="utf-8")
    return payload


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="Refresh overnight verdict audit board")
    p.add_argument("--refresh", action="store_true")
    args = p.parse_args(argv)
    out = write_overnight_board()
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
