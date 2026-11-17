"""Timed 2→3 Streamers capacity probe with system + lag samples.

Measures: HD-Player RSS/CPU, machine CPU/RAM, uiautomator dump latency,
window presence, process-loopback audio ok. Writes capacity_probe.jsonl + board.
"""

from __future__ import annotations

import json
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import ensure_data_layout
from .instances import (
    adb,
    connect_adb,
    get_instance,
    launch_bluestacks,
    list_instances,
    wait_for_adb,
)
from .process_loopback import record_process_loopback, resolve_hd_player_pid
from .streamers_open import _dump_ui


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ps(command: str, timeout: float = 20.0) -> str:
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return (proc.stdout or "").strip()


def sample_system() -> dict[str, Any]:
    raw = _ps(
        r"""
$os = Get-CimInstance Win32_OperatingSystem
$cpu = (Get-CimInstance Win32_Processor | Measure-Object -Property LoadPercentage -Average).Average
$procs = Get-Process HD-Player -ErrorAction SilentlyContinue | ForEach-Object {
  [pscustomobject]@{
    pid = $_.Id
    title = $_.MainWindowTitle
    ws_mb = [math]::Round($_.WorkingSet64/1MB,1)
    cpu_s = [math]::Round($_.CPU,1)
  }
}
[pscustomobject]@{
  cpu_pct = $cpu
  ram_used_gb = [math]::Round(($os.TotalVisibleMemorySize - $os.FreePhysicalMemory)/1MB,2)
  ram_free_gb = [math]::Round($os.FreePhysicalMemory/1MB,2)
  hd_players = @($procs)
} | ConvertTo-Json -Compress -Depth 4
"""
    )
    try:
        return json.loads(raw) if raw else {"error": "empty"}
    except json.JSONDecodeError:
        return {"error": "bad_json", "raw": raw[:500]}


def dump_latency(instance_id: str, dest: Path) -> dict[str, Any]:
    t0 = time.perf_counter()
    try:
        inst = get_instance(instance_id)
        connect_adb(inst)
        _dump_ui(inst, dest)
        ms = (time.perf_counter() - t0) * 1000
        return {"ok": True, "ms": round(ms, 1)}
    except Exception as e:
        ms = (time.perf_counter() - t0) * 1000
        return {"ok": False, "ms": round(ms, 1), "error": str(e)[:200]}


def ensure_streamers(instance_ids: list[str]) -> list[dict[str, Any]]:
    out = []
    for iid in instance_ids:
        inst = get_instance(iid)
        launch_bluestacks(inst, launch_app=True)
        connect_adb(inst)
        ready = wait_for_adb(inst, seconds=45)
        # Bring package forward
        adb(
            inst,
            [
                "shell",
                "monkey",
                "-p",
                str(inst.get("package") or "ar.tvplayer.tv"),
                "-c",
                "android.intent.category.LAUNCHER",
                "1",
            ],
        )
        time.sleep(1.5)
        pid_info = {}
        try:
            pid_info = resolve_hd_player_pid(
                window_title=str(inst.get("window_title") or ""),
                instance_id=iid,
            )
        except Exception as e:
            pid_info = {"error": str(e)}
        out.append({"id": iid, "adb_ready": ready, "pid": pid_info})
    return out


def run_probe(
    *,
    seconds: float = 75.0,
    instance_ids: list[str] | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    root = ensure_data_layout(root)
    probe_dir = root / "work" / "capacity_probe_3"
    probe_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    if not instance_ids:
        rows = list_instances(root)
        instance_ids = [r["id"] for r in rows if r.get("enabled", True)][:3]
        # Prefer known trio if present
        prefer = ["Nougat32", "Nougat32_1", "Tiramisu64"]
        have = {r["id"] for r in rows}
        if all(p in have for p in prefer):
            instance_ids = prefer

    baseline = sample_system()
    boot = ensure_streamers(instance_ids)

    # Resolve PIDs for audio
    pids: dict[str, int] = {}
    for row in boot:
        pid = (row.get("pid") or {}).get("pid")
        if pid:
            pids[row["id"]] = int(pid)

    audio_results: dict[str, Any] = {}
    audio_errors: dict[str, str] = {}

    def _rec(iid: str, pid: int) -> None:
        wav = probe_dir / f"{stamp}_{iid}_pid{pid}.wav"
        try:
            audio_results[iid] = record_process_loopback(
                pid=pid, seconds=seconds, out_path=wav
            )
        except Exception as e:
            audio_errors[iid] = str(e)

    threads = [
        threading.Thread(target=_rec, args=(iid, pid), daemon=True)
        for iid, pid in pids.items()
    ]
    t_audio0 = time.perf_counter()
    for t in threads:
        t.start()

    samples: list[dict[str, Any]] = []
    dump_samples: list[dict[str, Any]] = []
    deadline = time.time() + float(seconds)
    i = 0
    while time.time() < deadline:
        sys_s = sample_system()
        dumps = {}
        for iid in instance_ids:
            dumps[iid] = dump_latency(iid, probe_dir / f"dump_{stamp}_{iid}_{i}.xml")
        samples.append({"t": _now(), "i": i, "system": sys_s})
        dump_samples.append({"t": _now(), "i": i, "dumps": dumps})
        i += 1
        time.sleep(8.0)

    for t in threads:
        t.join(timeout=seconds + 30)
    audio_wall_s = time.perf_counter() - t_audio0

    # Summarize lag signals
    dump_ms = [
        d["dumps"][iid]["ms"]
        for d in dump_samples
        for iid in d["dumps"]
        if d["dumps"][iid].get("ms") is not None
    ]
    dump_fail = sum(
        1
        for d in dump_samples
        for iid in d["dumps"]
        if not d["dumps"][iid].get("ok")
    )
    cpu_vals = [
        float(s["system"].get("cpu_pct") or 0)
        for s in samples
        if isinstance(s.get("system"), dict) and s["system"].get("cpu_pct") is not None
    ]
    hd_counts = []
    for s in samples:
        hp = (s.get("system") or {}).get("hd_players") or []
        if isinstance(hp, dict):
            hp = [hp]
        hd_counts.append(len(hp))

    audio_ok = {
        iid: bool((audio_results.get(iid) or {}).get("ok") or (audio_results.get(iid) or {}).get("path"))
        or (
            isinstance(audio_results.get(iid), dict)
            and Path(str((audio_results[iid] or {}).get("path") or "")).is_file()
        )
        for iid in pids
    }
    # Fix audio_ok: record_process_loopback returns dict with path
    for iid, row in audio_results.items():
        p = Path(str(row.get("path") or row.get("out_path") or ""))
        if not p.is_file():
            # try known path
            guess = probe_dir / f"{stamp}_{iid}_pid{pids[iid]}.wav"
            audio_ok[iid] = guess.is_file() and guess.stat().st_size > 1000
        else:
            audio_ok[iid] = p.stat().st_size > 1000

    n = len(instance_ids)
    mean_dump = sum(dump_ms) / len(dump_ms) if dump_ms else None
    max_dump = max(dump_ms) if dump_ms else None
    mean_cpu = sum(cpu_vals) / len(cpu_vals) if cpu_vals else None
    max_cpu = max(cpu_vals) if cpu_vals else None

    # Verdict heuristics (not gospel — measured this run)
    warnings: list[str] = []
    if dump_fail:
        warnings.append(f"ui_dump_failures={dump_fail}")
    if max_dump and max_dump > 5000:
        warnings.append(f"ui_dump_max_ms={max_dump:.0f}")
    if mean_dump and mean_dump > 2500:
        warnings.append(f"ui_dump_mean_ms={mean_dump:.0f}")
    if max_cpu and max_cpu > 90:
        warnings.append(f"cpu_max_pct={max_cpu:.0f}")
    if any(c < n for c in hd_counts):
        warnings.append("hd_player_count_dropped")
    if not all(audio_ok.values()):
        warnings.append(f"audio_fail={{{k:v for k,v in audio_ok.items() if not v}}}")

    if n >= 3 and not warnings:
        verdict = "3_ok_this_run"
    elif n >= 3 and dump_fail == 0 and all(audio_ok.values()) and (not max_dump or max_dump < 8000):
        verdict = "3_usable_with_caution"
    elif n >= 3:
        verdict = "3_stressed"
    else:
        verdict = f"{n}_measured"

    report = {
        "ok": verdict in ("3_ok_this_run", "3_usable_with_caution", "2_measured"),
        "verdict": verdict,
        "checked_utc": _now(),
        "seconds": seconds,
        "instance_ids": instance_ids,
        "boot": boot,
        "pids": pids,
        "baseline": baseline,
        "sample_count": len(samples),
        "system_summary": {
            "cpu_mean_pct": round(mean_cpu, 1) if mean_cpu is not None else None,
            "cpu_max_pct": round(max_cpu, 1) if max_cpu is not None else None,
            "hd_player_count_min": min(hd_counts) if hd_counts else None,
            "hd_player_count_max": max(hd_counts) if hd_counts else None,
        },
        "dump_summary": {
            "mean_ms": round(mean_dump, 1) if mean_dump is not None else None,
            "max_ms": round(max_dump, 1) if max_dump is not None else None,
            "failures": dump_fail,
            "samples": len(dump_ms),
        },
        "audio": {
            "wall_s": round(audio_wall_s, 1),
            "ok": audio_ok,
            "errors": audio_errors,
            "results": {
                k: {
                    "path": v.get("path") or v.get("out_path"),
                    "bytes": v.get("bytes") or v.get("size"),
                }
                for k, v in audio_results.items()
            },
        },
        "warnings": warnings,
        "samples_tail": samples[-3:],
        "dump_tail": dump_samples[-3:],
        "probe_dir": str(probe_dir),
    }

    jsonl = root / "indexes" / "capacity_probe.jsonl"
    with jsonl.open("a", encoding="utf-8") as f:
        f.write(json.dumps(report) + "\n")

    board = root / "indexes" / "CAPACITY_PROBE_3.md"
    lines = [
        "# Capacity probe — 3 streams",
        "",
        f"Checked `{report['checked_utc']}` · **{seconds:g}s** · verdict **`{verdict}`**",
        "",
        f"Instances: {', '.join(instance_ids)}",
        "",
        "## System",
        f"- CPU mean/max: {report['system_summary']['cpu_mean_pct']} / {report['system_summary']['cpu_max_pct']} %",
        f"- HD-Player count min/max: {report['system_summary']['hd_player_count_min']} / {report['system_summary']['hd_player_count_max']}",
        "",
        "## UI dump latency (lag proxy)",
        f"- mean/max: {report['dump_summary']['mean_ms']} / {report['dump_summary']['max_ms']} ms",
        f"- failures: {dump_fail}",
        "",
        "## Process-loopback audio",
    ]
    for iid in instance_ids:
        lines.append(f"- `{iid}` pid={pids.get(iid)} ok={audio_ok.get(iid)} err={audio_errors.get(iid) or '—'}")
    lines.extend(["", "## Warnings", ""])
    if warnings:
        for w in warnings:
            lines.append(f"- {w}")
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "Audio isolation is per-PID (no extra cable). Bottleneck under test = Streamers/BlueStacks lag.",
            "",
            f"Raw: `{jsonl}` · wavs: `{probe_dir}`",
            "",
        ]
    )
    board.write_text("\n".join(lines), encoding="utf-8")
    report["board"] = str(board)
    report["jsonl"] = str(jsonl)
    return report


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="3-stream capacity + lag probe")
    p.add_argument("--seconds", type=float, default=75.0)
    p.add_argument("--instances", nargs="*", default=None)
    args = p.parse_args(argv)
    report = run_probe(seconds=args.seconds, instance_ids=args.instances)
    print(json.dumps(report, indent=2))
    return 0 if report.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
