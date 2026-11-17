"""Add streams one-by-one: real short AV record + system/lag watch.

Default ramp: Nougat32 → +Nougat32_1 → +Nougat32_2… (same SKU clones only).
Tiramisu64 is not in the default ramp — different Android, flaky ADB login.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .capacity_probe_3 import dump_latency, sample_system
from .config import ensure_data_layout, farm_dir
from .instances import connect_adb, get_instance, launch_bluestacks, list_instances, wait_for_adb
from .process_loopback import resolve_hd_player_pid
from .session_capture import start_session
from .streamers_lag import CLEAN_CONCURRENT, assess_session_lag


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_desk_limits(
    *,
    max_ok_n: int,
    clean_n: int = 0,
    root: Path | None = None,
    source: str = "progressive_capacity",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist proven concurrent stream cap for the desk cron.

    Clean ``*_ok`` (no warnings) raises ``OHUSH_DESK_MAX_STREAMS``.
    ``*_ok_with_warnings`` records the probe but does not raise above the last
    clean floor (or CLEAN_CONCURRENT).
    """
    root = ensure_data_layout(root)
    path = farm_dir(root) / "desk_limits.json"
    prev: dict[str, Any] = {}
    if path.is_file():
        try:
            prev = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            prev = {}
    prev_clean = int(prev.get("clean_n") or prev.get("OHUSH_DESK_MAX_STREAMS") or CLEAN_CONCURRENT)
    floor = max(int(CLEAN_CONCURRENT), int(prev_clean or 0))
    if clean_n > 0:
        desk_max = max(floor, int(clean_n))
        reason = f"{source}: clean_ok n={clean_n}"
    else:
        desk_max = floor
        reason = f"{source}: max_ok_n={max_ok_n} had warnings — holding desk at {desk_max}"
    row = {
        "OHUSH_DESK_MAX_STREAMS": int(desk_max),
        "clean_n": int(clean_n or prev.get("clean_n") or 0),
        "max_ok_n": int(max_ok_n),
        "set_utc": _now(),
        "reason": reason,
        "source": source,
    }
    if extra:
        row["extra"] = extra
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(row, indent=2), encoding="utf-8")
    return row


def _ensure_instance(iid: str) -> dict[str, Any]:
    inst = get_instance(iid)
    launch_bluestacks(inst, launch_app=True)
    connect_adb(inst)
    ready = wait_for_adb(inst, seconds=60)
    recover = None
    try:
        from .streamers_recover import ensure_picture

        recover = ensure_picture(iid)
    except Exception as e:  # noqa: BLE001
        recover = {"ok": False, "error": str(e)}
    pid = None
    try:
        pid = resolve_hd_player_pid(
            window_title=str(inst.get("window_title") or ""),
            instance_id=iid,
        )
    except Exception as e:
        pid = {"error": str(e)}
    return {
        "id": iid,
        "adb_ready": ready,
        "pid": pid,
        "recover": recover,
        "instance": inst,
    }


def _record_one(
    *,
    iid: str,
    minutes: float,
    channel: str,
    out_box: dict[str, Any],
) -> None:
    try:
        meta = start_session(
            source_kind="streamers",
            channel_id=channel,
            minutes=minutes,
            media="av",
            still_interval_sec=1.0,
            instance_id=iid,
            apply_channel=False,  # already on a picture; don't retune mid-probe
        )
        if not meta.get("ok", True) or meta.get("error"):
            out_box[iid] = {
                "ok": False,
                "error": meta.get("error") or "session returned not ok",
                "meta": meta,
            }
            return
        lag = assess_session_lag(meta)
        session_dir = Path(str(meta.get("session_dir") or ""))
        wavs = list(session_dir.glob("**/*.wav")) if session_dir.is_dir() else []
        wav_bytes = sum(w.stat().st_size for w in wavs)
        stills = (
            len(list(session_dir.glob("**/still_t*.jpg")))
            + len(list(session_dir.glob("**/stills/*.jpg")))
            if session_dir.is_dir()
            else 0
        )
        if wav_bytes < 50_000:
            out_box[iid] = {
                "ok": False,
                "error": f"wav too small ({wav_bytes} bytes)",
                "meta": meta,
                "lag": lag,
            }
            return
        out_box[iid] = {
            "ok": True,
            "meta": meta,
            "lag": lag,
            "wav_bytes": wav_bytes,
            "still_count": stills,
        }
    except Exception as e:
        out_box[iid] = {"ok": False, "error": str(e)}


def run_step(
    instance_ids: list[str],
    *,
    minutes: float = 1.5,
    channel: str = "CAPACITY_PROBE",
    root: Path | None = None,
) -> dict[str, Any]:
    root = ensure_data_layout(root)
    probe = root / "work" / "progressive_capacity"
    probe.mkdir(parents=True, exist_ok=True)

    boot = [_ensure_instance(i) for i in instance_ids]
    baseline = sample_system()

    results: dict[str, Any] = {}
    threads = [
        threading.Thread(
            target=_record_one,
            kwargs={"iid": iid, "minutes": minutes, "channel": channel, "out_box": results},
            daemon=True,
        )
        for iid in instance_ids
    ]
    t0 = time.perf_counter()
    for t in threads:
        t.start()

    samples: list[dict[str, Any]] = []
    dumps: list[dict[str, Any]] = []
    deadline = time.time() + minutes * 60.0 + 15.0
    i = 0
    while time.time() < deadline and any(t.is_alive() for t in threads):
        sys_s = sample_system()
        drow = {}
        for iid in instance_ids:
            drow[iid] = dump_latency(iid, probe / f"dump_{len(instance_ids)}_{iid}_{i}.xml")
        samples.append({"t": _now(), "system": sys_s})
        dumps.append({"t": _now(), "dumps": drow})
        i += 1
        time.sleep(10.0)

    for t in threads:
        t.join(timeout=minutes * 60.0 + 60.0)
    wall = time.perf_counter() - t0

    cpu_vals = [
        float(s["system"].get("cpu_pct") or 0)
        for s in samples
        if isinstance(s.get("system"), dict) and s["system"].get("cpu_pct") is not None
    ]
    dump_ms = [
        d["dumps"][iid]["ms"]
        for d in dumps
        for iid in d["dumps"]
        if d["dumps"][iid].get("ms") is not None
    ]
    dump_fail = sum(
        1 for d in dumps for iid in d["dumps"] if not d["dumps"][iid].get("ok")
    )

    rec_ok = {iid: bool((results.get(iid) or {}).get("ok")) for iid in instance_ids}
    lag_levels = {
        iid: ((results.get(iid) or {}).get("lag") or {}).get("level")
        for iid in instance_ids
    }

    # Session artifact sizes
    artifacts: dict[str, Any] = {}
    for iid, row in results.items():
        meta = row.get("meta") or {}
        session_dir = meta.get("session_dir") or meta.get("out_dir")
        wavs = []
        stills = 0
        if session_dir and Path(str(session_dir)).is_dir():
            p = Path(str(session_dir))
            wavs = [str(x) for x in p.glob("**/*.wav")]
            stills = len(list(p.glob("**/still_t*.jpg"))) + len(list(p.glob("**/*.jpg")))
        artifacts[iid] = {
            "session_dir": session_dir,
            "wav_count": len(wavs),
            "wav_bytes": sum(Path(w).stat().st_size for w in wavs if Path(w).is_file()),
            "still_count": stills,
            "lag": row.get("lag"),
            "error": row.get("error"),
        }

    n = len(instance_ids)
    warnings: list[str] = []
    if not all(rec_ok.values()):
        fails = {ik: iv for ik, iv in rec_ok.items() if not iv}
        warnings.append(f"record_fail={fails}")
    if dump_fail:
        warnings.append(f"ui_dump_failures={dump_fail}")
    if dump_ms and max(dump_ms) > 5000:
        warnings.append(f"ui_dump_max_ms={max(dump_ms):.0f}")
    if any(lvl in ("warn", "critical") for lvl in lag_levels.values() if lvl):
        warnings.append(f"streamers_lag={lag_levels}")
    if cpu_vals and max(cpu_vals) > 90:
        warnings.append(f"cpu_max={max(cpu_vals):.0f}")

    if all(rec_ok.values()) and not warnings:
        verdict = f"{n}_ok"
    elif all(rec_ok.values()):
        verdict = f"{n}_ok_with_warnings"
    else:
        verdict = f"{n}_failed"

    return {
        "ok": verdict.startswith(f"{n}_ok"),
        "verdict": verdict,
        "n": n,
        "instance_ids": instance_ids,
        "checked_utc": _now(),
        "minutes": minutes,
        "wall_s": round(wall, 1),
        "boot": [{k: v for k, v in b.items() if k != "instance"} for b in boot],
        "baseline": baseline,
        "system_summary": {
            "cpu_mean_pct": round(sum(cpu_vals) / len(cpu_vals), 1) if cpu_vals else None,
            "cpu_max_pct": round(max(cpu_vals), 1) if cpu_vals else None,
            "sample_count": len(samples),
        },
        "dump_summary": {
            "mean_ms": round(sum(dump_ms) / len(dump_ms), 1) if dump_ms else None,
            "max_ms": round(max(dump_ms), 1) if dump_ms else None,
            "failures": dump_fail,
        },
        "record_ok": rec_ok,
        "lag_levels": lag_levels,
        "artifacts": artifacts,
        "warnings": warnings,
    }


def run_ramp(
    *,
    minutes: float = 1.5,
    root: Path | None = None,
    stop_on_fail: bool = True,
) -> dict[str, Any]:
    root = ensure_data_layout(root)
    # Same-SKU Nougat clones only. Discover Nougat32_* that are registered+enabled.
    nougats = ["Nougat32"]
    for row in list_instances(root):
        iid = str(row.get("id") or "")
        if not row.get("enabled", True):
            continue
        if iid.startswith("Nougat32_") and iid not in nougats:
            nougats.append(iid)
    nougats.sort(key=lambda x: (0 if x == "Nougat32" else 1, x))
    ramp: list[list[str]] = []
    # Fleet may be ~10 ready clones; only ramp as many as exist and stay healthy.
    for n in range(1, min(len(nougats), 10) + 1):
        ramp.append(nougats[:n])

    steps: list[dict[str, Any]] = []
    for ids in ramp:
        step = run_step(ids, minutes=minutes, root=root)
        steps.append(step)
        if stop_on_fail and not step.get("ok"):
            break

    board_lines = [
        "# Progressive capacity (add streams one-by-one)",
        "",
        f"Checked `{_now()}` · {minutes:g} min AV each step",
        "",
        "| N | Instances | Verdict | CPU max | Dump max ms | Lag | Warnings |",
        "|--:|---|---|--:|--:|---|---|",
    ]
    for s in steps:
        board_lines.append(
            f"| {s['n']} | {', '.join(s['instance_ids'])} | `{s['verdict']}` | "
            f"{(s.get('system_summary') or {}).get('cpu_max_pct')} | "
            f"{(s.get('dump_summary') or {}).get('max_ms')} | "
            f"{s.get('lag_levels')} | {'; '.join(s.get('warnings') or []) or '—'} |"
        )
    board_lines.extend(["", "Artifacts per step are under each session dir.", ""])
    board = root / "indexes" / "PROGRESSIVE_CAPACITY.md"
    board.write_text("\n".join(board_lines), encoding="utf-8")

    jsonl = root / "indexes" / "capacity_probe.jsonl"
    with jsonl.open("a", encoding="utf-8") as f:
        f.write(
            json.dumps(
                {
                    "kind": "progressive_capacity",
                    "checked_utc": _now(),
                    "steps": [
                        {k: v for k, v in s.items() if k not in ("boot",)}
                        for s in steps
                    ],
                    "board": str(board),
                }
            )
            + "\n"
        )

    max_ok_n = max((s["n"] for s in steps if s.get("ok")), default=0)
    # Only auto-raise desk cap on clean *_ok (no warnings). Warnings stay provisional.
    clean_n = max(
        (s["n"] for s in steps if s.get("ok") and not (s.get("warnings") or [])),
        default=0,
    )
    limits = write_desk_limits(
        max_ok_n=max_ok_n,
        clean_n=clean_n,
        root=root,
        source="progressive_capacity_ramp",
        extra={"steps": [{"n": s["n"], "verdict": s.get("verdict")} for s in steps]},
    )
    return {
        "ok": all(s.get("ok") for s in steps),
        "steps": steps,
        "board": str(board),
        "max_ok_n": max_ok_n,
        "desk_limits": limits,
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="Progressive 1→2→3 stream capacity")
    p.add_argument("--minutes", type=float, default=1.5)
    p.add_argument("--step", type=int, default=0, help="Run only N streams (1/2/3); 0=full ramp")
    p.add_argument("--instances", nargs="*", default=None)
    args = p.parse_args(argv)

    if args.instances:
        report = run_step(args.instances, minutes=args.minutes)
        n = int(report.get("n") or len(args.instances))
        clean = n if report.get("ok") and not (report.get("warnings") or []) else 0
        report["desk_limits"] = write_desk_limits(
            max_ok_n=n if report.get("ok") else 0,
            clean_n=clean,
            source="progressive_capacity_step",
            extra={"verdict": report.get("verdict"), "instances": args.instances},
        )
    elif args.step:
        nougats = ["Nougat32"] + sorted(
            str(r["id"])
            for r in list_instances()
            if str(r.get("id") or "").startswith("Nougat32_") and r.get("enabled", True)
        )
        if args.step > len(nougats):
            print(
                json.dumps(
                    {
                        "ok": False,
                        "error": f"need {args.step} Nougat clones; have {nougats}",
                        "hint": "Clone Nougat32 in Multi-Instance Manager, then multi sync-discovered",
                    },
                    indent=2,
                )
            )
            return 2
        report = run_step(nougats[: args.step], minutes=args.minutes)
        # also append board snippet
        root = ensure_data_layout()
        board = root / "indexes" / "PROGRESSIVE_CAPACITY.md"
        with board.open("a", encoding="utf-8") as f:
            f.write(
                f"\n## Manual step {args.step} @ {_now()}\n\n"
                f"```json\n{json.dumps({k: report[k] for k in ('verdict','record_ok','lag_levels','system_summary','dump_summary','warnings','artifacts')}, indent=2)}\n```\n"
            )
        report["board"] = str(board)
        clean = int(args.step) if report.get("ok") and not (report.get("warnings") or []) else 0
        report["desk_limits"] = write_desk_limits(
            max_ok_n=int(args.step) if report.get("ok") else 0,
            clean_n=clean,
            root=root,
            source="progressive_capacity_step",
            extra={"verdict": report.get("verdict")},
        )
    else:
        report = run_ramp(minutes=args.minutes)

    print(json.dumps(report, indent=2, default=str))
    return 0 if report.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
