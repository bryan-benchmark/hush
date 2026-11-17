"""Run vision(+ASR) → acoustic → combine → consensus locks → triage.

Brings still/VL + transcript lexicon + acoustic onto one hop spine.
Agree → auto gold (farm_consensus). Disagree episodes → /verdict.

  python -m tools.windows_lab.farm_multichannel_pass
  python -m tools.windows_lab.farm_multichannel_pass --all-prepared --limit 4
  python -m tools.windows_lab.farm_multichannel_pass --skip-vision   # combine+consensus only
"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .coverage_farm import farm_label_dir
from .export_farm_acoustic_gold import OUT as FARM_ACCEPTED
from .export_farm_acoustic_gold import export as export_farm_gold
from .farm_atomic_audit import combine_session, write_index
from .farm_consensus import apply_consensus_locks, prepared_sessions
from .farm_episode_triage import run as triage_run
from .farm_label_timing import rebuild_snapshot, timed_step
from .farm_vision_timeline import run_session as vision_run


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _accepted_sessions() -> list[str]:
    if not FARM_ACCEPTED.is_file():
        return []
    out: list[str] = []
    for line in FARM_ACCEPTED.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        s = json.loads(line).get("session")
        if s and s not in out:
            out.append(s)
    return out


def _help_asks_by_session() -> dict[str, int]:
    key_path = farm_label_dir() / "key.jsonl"
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


def _sessions_needing_work(sessions: list[str]) -> list[str]:
    """Prefer sessions missing hops, ordered by largest farm help pile first."""
    label = farm_label_dir()
    help_n = _help_asks_by_session()
    missing: list[str] = []
    ready: list[str] = []
    for s in sessions:
        d = label / "audit" / s
        has_v = not _needs_vision(s)
        has_a = (d / "hops_acoustic.jsonl").is_file()
        if has_v and has_a and (d / "hops.jsonl").is_file():
            ready.append(s)
        else:
            missing.append(s)
    missing.sort(key=lambda s: (-int(help_n.get(s) or 0), s))
    ready.sort(key=lambda s: (-int(help_n.get(s) or 0), s))
    return missing + ready


def _vision_coverage(session: str, *, hop_s: float = 5.0) -> dict[str, Any]:
    """How far vision got vs expected hops (checkpoint files can exist mid-tape)."""
    path = farm_label_dir() / "audit" / session / "hops_vision.jsonl"
    if not path.is_file():
        return {"path": str(path), "exists": False, "done": 0, "expect": None, "complete": False}
    done = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        vision = (row.get("channels") or {}).get("vision") or {}
        if vision.get("ok") and vision.get("visual"):
            done += 1
            continue
        err = str(vision.get("error") or "")
        if err in {"black_still", "green_corrupt_still", "missing_still", "no_still"}:
            done += 1
    expect = None
    try:
        from .coverage_farm import streamers_capture_root
        from .farm_draft import _wav_duration_sec

        wav = streamers_capture_root() / session / "audio.wav"
        if wav.is_file():
            dur = float(_wav_duration_sec(wav) or 0.0)
            if dur > 0 and hop_s > 0:
                expect = max(1, int(dur / float(hop_s)) + 1)
    except Exception:
        expect = None
    complete = bool(expect is not None and done >= int(expect * 0.98))
    return {
        "path": str(path),
        "exists": True,
        "done": done,
        "expect": expect,
        "complete": complete,
    }


def _needs_vision(session: str, *, hop_s: float = 5.0) -> bool:
    cov = _vision_coverage(session, hop_s=hop_s)
    if not cov.get("exists"):
        return True
    # Mid-run checkpoints create the file early — keep vision until coverage is ~full.
    if cov.get("expect") is None:
        return cov.get("done", 0) < 10
    return not bool(cov.get("complete"))


def _needs_acoustic(session: str) -> bool:
    path = farm_label_dir() / "audit" / session / "hops_acoustic.jsonl"
    return not path.is_file()


def _hop_stats(session: str) -> dict[str, Any]:
    path = farm_label_dir() / "audit" / session / "hops.jsonl"
    if not path.is_file():
        return {"session": session, "ok": False, "error": "missing hops.jsonl"}
    hops = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    why = Counter()
    n_dis = 0
    channels = Counter()
    for h in hops:
        ch = h.get("channels") or {}
        if ch.get("vision"):
            channels["vision"] += 1
        if ch.get("asr"):
            channels["asr"] += 1
        if ch.get("acoustic"):
            channels["acoustic"] += 1
        if ch.get("gold"):
            channels["gold"] += 1
        if h.get("disagreement"):
            n_dis += 1
            why[str(h.get("why") or "DISAGREE")] += 1
    return {
        "session": session,
        "ok": True,
        "n_hops": len(hops),
        "n_disagree": n_dis,
        "disagree_rate": round(n_dis / len(hops), 4) if hops else 0.0,
        "channels": dict(channels),
        "why_top": why.most_common(8),
    }


def run(
    *,
    skip_vision: bool = False,
    skip_acoustic: bool = False,
    apply_consensus: bool = True,
    all_prepared: bool = False,
    limit: int | None = None,
    hop_s: float = 5.0,
    model: str = "qwen2.5vl:7b",
) -> dict[str, Any]:
    """Vision default: qwen2.5vl @ 5s — moondream returns empty on many farm stills here."""
    if all_prepared:
        sessions = _sessions_needing_work(prepared_sessions())
    else:
        sessions = _accepted_sessions()
    if limit is not None:
        sessions = sessions[: max(0, int(limit))]

    pass_t0 = time.perf_counter()
    vision_results: list[dict[str, Any]] = []
    if not skip_vision:
        from .farm_draft import prepare_vision_gpu, unload_ollama_model

        todo = [s for s in sessions if _needs_vision(s, hop_s=hop_s)]
        # One VL resident for the whole vision leg — unload siblings (moondream) first.
        gpu_prep = prepare_vision_gpu(model)
        print(json.dumps({"vision_gpu_prep": gpu_prep}), flush=True)
        for i, session in enumerate(todo, 1):
            cov = _vision_coverage(session, hop_s=hop_s)
            print(
                json.dumps(
                    {
                        "vision_start": session,
                        "i": i,
                        "of": len(todo),
                        "hop_s": hop_s,
                        "model": model,
                        "keep_hot": True,
                        "resume_done": cov.get("done"),
                        "resume_expect": cov.get("expect"),
                    }
                ),
                flush=True,
            )
            try:
                from .farm_label_lock import heartbeat as label_heartbeat
                from .lab_status import write_status

                label_heartbeat(
                    phase="vision",
                    session=session,
                    session_i=i,
                    session_of=len(todo),
                    hop_s=hop_s,
                    model=model,
                    note="vision_tape_start",
                )
                write_status(
                    progress={
                        "phase": "vision",
                        "session": session,
                        "session_i": i,
                        "session_of": len(todo),
                        "hop_s": hop_s,
                        "model": model,
                        "note": "vision_tape_start",
                    }
                )
            except Exception:
                pass
            try:
                # Keep qwen hot across tapes; unload once after the vision leg.
                vision_results.append(
                    vision_run(
                        session,
                        use_asr=True,
                        use_vision=True,
                        hop_s=float(hop_s),
                        model=model,
                        unload_after=False,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                vision_results.append({"ok": False, "session": session, "error": str(exc)})
                print(json.dumps({"vision_fail": session, "error": str(exc)}), flush=True)
        if todo:
            print(json.dumps({"vision_unload": unload_ollama_model(model)}), flush=True)

    acoustic_results: list[dict[str, Any]] = []
    if not skip_acoustic:
        from .farm_embed_extract import extract_session

        todo_a = [s for s in sessions if _needs_acoustic(s)]
        for i, session in enumerate(todo_a, 1):
            print(json.dumps({"acoustic_start": session, "i": i, "of": len(todo_a)}), flush=True)
            try:
                from .farm_label_lock import heartbeat as label_heartbeat
                from .lab_status import write_status

                label_heartbeat(
                    phase="acoustic",
                    session=session,
                    session_i=i,
                    session_of=len(todo_a),
                    note="sound_tape_start",
                )
                write_status(
                    progress={
                        "phase": "acoustic",
                        "session": session,
                        "session_i": i,
                        "session_of": len(todo_a),
                        "note": "sound_tape_start",
                    }
                )
            except Exception:
                pass
            try:
                with timed_step(session, "acoustic", session_i=i, session_of=len(todo_a)) as _t:
                    acoustic_results.append(extract_session(session, use_cache=True))
            except Exception as exc:  # noqa: BLE001
                acoustic_results.append({"ok": False, "session": session, "error": str(exc)})
                print(json.dumps({"acoustic_fail": session, "error": str(exc)}), flush=True)

    combine_results: list[dict[str, Any]] = []
    for session in sessions:
        try:
            with timed_step(session, "combine") as _t:
                combine_results.append(combine_session(session))
        except Exception as exc:  # noqa: BLE001
            combine_results.append({"ok": False, "session": session, "error": str(exc)})
    write_index(combine_results)

    consensus_results: list[dict[str, Any]] = []
    if apply_consensus:
        for session in sessions:
            try:
                with timed_step(session, "consensus") as _t:
                    consensus_results.append(apply_consensus_locks(session))
            except Exception as exc:  # noqa: BLE001
                consensus_results.append({"ok": False, "session": session, "error": str(exc)})

    export_receipt: dict[str, Any] | None = None
    if apply_consensus and any(int(r.get("locked_n") or 0) > 0 for r in consensus_results):
        try:
            export_receipt = export_farm_gold(rebuild=True, clean_only=True)
        except Exception as exc:  # noqa: BLE001
            export_receipt = {"ok": False, "error": str(exc)}

    triage = triage_run(apply=False)
    hop_stats = [_hop_stats(s) for s in sessions]
    n_dis = sum(int(s.get("n_disagree") or 0) for s in hop_stats if s.get("ok"))
    n_eps = sum(len(r.get("episodes") or []) for r in triage.get("sessions") or [])
    locked_total = sum(int(r.get("locked_n") or 0) for r in consensus_results)

    timing_snap = rebuild_snapshot()
    out = {
        "generated_utc": _now(),
        "mode": "all_prepared" if all_prepared else "farm_accepted",
        "sessions": sessions,
        "vision": {"ran": not skip_vision, "results": vision_results},
        "acoustic": {"ran": not skip_acoustic, "results": acoustic_results},
        "combine": combine_results,
        "consensus": consensus_results,
        "consensus_locked_total": locked_total,
        "export": export_receipt,
        "hop_stats": hop_stats,
        "triage_episodes": n_eps,
        "disagree_hops_total": n_dis,
        "pass_wall_s": round(time.perf_counter() - pass_t0, 1),
        "timing": {
            "totals": timing_snap.get("totals"),
            "by_step": timing_snap.get("by_step"),
            "ledger": str(farm_label_dir() / "audit" / "LABEL_TIMING.jsonl"),
        },
        "triage_tag_summary": {r["session"]: r.get("tag_counts") for r in triage.get("sessions") or []},
        "next": [
            "Open https://ohush.co/verdict (or :3020) — Done queue is disagree episodes",
            "After labeling: python -m tools.windows_lab.farm_apply_you_marks",
            "Then export + farm_live_scorecard --no-cache + farm_you_shadow_refit",
            "Ship only on KEEP",
        ],
    }
    root = farm_label_dir() / "audit"
    root.mkdir(parents=True, exist_ok=True)
    path = root / "MULTICHANNEL_PASS.json"
    path.write_text(json.dumps(out, indent=2, default=str) + "\n", encoding="utf-8")
    lines = [
        f"# Multichannel pass — {out['generated_utc'][:19]}Z",
        "",
        f"mode: **{out['mode']}** · sessions: **{len(sessions)}** · "
        f"disagree hops: **{n_dis}** · triage episodes: **{n_eps}** · "
        f"consensus locked: **{locked_total}**",
        "",
        "| Session | hops | disagree | vision | asr | acoustic | gold |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for s in hop_stats:
        if not s.get("ok"):
            lines.append(f"| `{s.get('session')}` | — | — | — | — | — | {s.get('error')} |")
            continue
        ch = s.get("channels") or {}
        lines.append(
            f"| `{s['session']}` | {s['n_hops']} | {s['n_disagree']} | "
            f"{ch.get('vision', 0)} | {ch.get('asr', 0)} | {ch.get('acoustic', 0)} | {ch.get('gold', 0)} |"
        )
    lines.extend(["", "## Next", ""])
    for n in out["next"]:
        lines.append(f"- {n}")
    lines.append("")
    md = root / "MULTICHANNEL_PASS.md"
    md.write_text("\n".join(lines), encoding="utf-8")
    out["receipt"] = str(path)
    out["md"] = str(md)
    try:
        from .lab_status import write_status

        write_status(
            progress={
                "phase": "idle",
                "note": "multichannel pass finished",
                "disagree_hops_total": n_dis,
                "triage_episodes": n_eps,
                "consensus_locked_total": locked_total,
            }
        )
    except Exception:
        pass
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Vision+ASR+acoustic multichannel farm pass")
    p.add_argument("--skip-vision", action="store_true")
    p.add_argument("--skip-acoustic", action="store_true")
    p.add_argument("--no-consensus", action="store_true")
    p.add_argument("--all-prepared", action="store_true", help="All prepared capture sessions, not only farm_accepted")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--hop-s", type=float, default=5.0)
    p.add_argument("--model", type=str, default="qwen2.5vl:7b")
    args = p.parse_args(argv)
    out = run(
        skip_vision=bool(args.skip_vision),
        skip_acoustic=bool(args.skip_acoustic),
        apply_consensus=not bool(args.no_consensus),
        all_prepared=bool(args.all_prepared),
        limit=args.limit,
        hop_s=float(args.hop_s),
        model=str(args.model),
    )
    print(
        json.dumps(
            {
                "ok": True,
                "mode": out.get("mode"),
                "sessions": len(out["sessions"]),
                "disagree_hops_total": out["disagree_hops_total"],
                "triage_episodes": out["triage_episodes"],
                "consensus_locked_total": out.get("consensus_locked_total"),
                "md": out["md"],
                "receipt": out["receipt"],
            },
            indent=2,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
