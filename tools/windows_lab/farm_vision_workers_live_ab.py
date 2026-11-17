"""Live desk A/B: FARM_VISION_WORKERS 4 vs 5 vs 6 on the running tape.

Restarts verdict_backfill between trials (checkpoint resume). Keeps
OLLAMA_NUM_PARALLEL at max(workers, current) so the server already has slots.

  python -m tools.windows_lab.farm_vision_workers_live_ab
  python -m tools.windows_lab.farm_vision_workers_live_ab --minutes 10 --warmup-s 90
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any

from .coverage_farm import farm_label_dir
from .farm_label_lock import release as release_label_lock


HOST = "127.0.0.1"
DESK = f"http://{HOST}:3020/api/overnight"
BACKFILL_MOD = "tools.windows_lab.farm_verdict_backfill"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _repo() -> Path:
    return Path(__file__).resolve().parents[2]


def _py() -> str:
    venv = _repo() / ".venv" / "Scripts" / "python.exe"
    return str(venv) if venv.is_file() else sys.executable


def _overnight() -> dict[str, Any]:
    with urllib.request.urlopen(DESK, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _snap() -> dict[str, Any]:
    d = _overnight()
    lj = dict(d.get("live_job") or {})
    pic = dict(((d.get("etas") or {}).get("speed") or {}).get("pictures") or {})
    lock = dict(d.get("label_lock") or {})
    return {
        "utc": _now(),
        "phase": lj.get("phase"),
        "session": lj.get("session"),
        "hop_i": lj.get("hop_i"),
        "hop_of": lj.get("hop_of"),
        "workers": lj.get("workers"),
        "pct": lj.get("pct"),
        "live_per_min": pic.get("live_per_min"),
        "stalled": bool(lj.get("stalled") or pic.get("stalled")),
        "lock_pid": lock.get("pid"),
        "lock_held": lock.get("held"),
    }


def _kill_backfills() -> list[int]:
    """Stop farm_verdict_backfill processes (Windows)."""
    killed: list[int] = []
    try:
        out = subprocess.check_output(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                (
                    "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" "
                    "| Where-Object { $_.CommandLine -match 'farm_verdict_backfill' } "
                    "| ForEach-Object { $_.ProcessId }"
                ),
            ],
            text=True,
            timeout=30,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return killed
    for line in out.splitlines():
        line = line.strip()
        if not line.isdigit():
            continue
        pid = int(line)
        try:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/F"],
                check=False,
                capture_output=True,
                timeout=15,
            )
            killed.append(pid)
        except Exception:  # noqa: BLE001
            pass
    return killed


def _start_backfill(*, workers: int, ollama_parallel: int) -> subprocess.Popen[Any]:
    env = os.environ.copy()
    env["FARM_VISION_WORKERS"] = str(int(workers))
    env["OLLAMA_NUM_PARALLEL"] = str(int(ollama_parallel))
    # Persist for any child tools that re-read User env mid-run.
    try:
        subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                (
                    f"[System.Environment]::SetEnvironmentVariable('FARM_VISION_WORKERS','{workers}','User');"
                    f"[System.Environment]::SetEnvironmentVariable('OLLAMA_NUM_PARALLEL','{ollama_parallel}','User')"
                ),
            ],
            check=False,
            capture_output=True,
            timeout=15,
        )
    except Exception:  # noqa: BLE001
        pass
    log_dir = farm_label_dir() / "audit" / "vision_feed_ab"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"backfill_workers_{workers}.log"
    log_f = open(log_path, "a", encoding="utf-8")  # noqa: SIM115
    log_f.write(f"\n--- start {_now()} workers={workers} parallel={ollama_parallel} ---\n")
    log_f.flush()
    proc = subprocess.Popen(
        [
            _py(),
            "-m",
            BACKFILL_MOD,
            "--batch",
            "1",
            "--trigger",
            f"workers_live_ab_{workers}",
        ],
        cwd=str(_repo()),
        env=env,
        stdout=log_f,
        stderr=subprocess.STDOUT,
    )
    return proc


def _wait_vision(*, workers: int, timeout_s: float = 180.0) -> dict[str, Any]:
    t0 = time.monotonic()
    last: dict[str, Any] = {}
    while time.monotonic() - t0 < timeout_s:
        try:
            last = _snap()
        except Exception as exc:  # noqa: BLE001
            last = {"error": str(exc)}
            time.sleep(3)
            continue
        if (
            last.get("phase") == "vision"
            and last.get("hop_i") is not None
            and int(last.get("workers") or 0) == int(workers)
            and not last.get("stalled")
        ):
            return {"ok": True, **last, "wait_s": round(time.monotonic() - t0, 1)}
        time.sleep(3)
    return {"ok": False, "timeout_s": timeout_s, **last}


def _sample_window(*, seconds: float, every_s: float = 15.0) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    t_end = time.monotonic() + float(seconds)
    while time.monotonic() < t_end:
        try:
            rows.append(_snap())
        except Exception as exc:  # noqa: BLE001
            rows.append({"utc": _now(), "error": str(exc)})
        # Sleep the remainder of the interval.
        left = t_end - time.monotonic()
        if left <= 0:
            break
        time.sleep(min(float(every_s), left))
    return rows


def _summarize(trial: dict[str, Any]) -> dict[str, Any]:
    samples = list(trial.get("samples") or [])
    # Drop post-rewind / non-vision samples so a finished tape cannot fake the rate.
    sess0 = trial.get("session") or (samples[0].get("session") if samples else None)
    clean: list[dict[str, Any]] = []
    for s in samples:
        if s.get("error"):
            continue
        if s.get("phase") and s.get("phase") != "vision":
            break
        if sess0 and s.get("session") and str(s.get("session")) != str(sess0):
            break
        if clean and s.get("hop_i") is not None and clean[-1].get("hop_i") is not None:
            if int(s["hop_i"]) + 2 < int(clean[-1]["hop_i"]):
                break
        clean.append(s)
    rates = [
        float(s["live_per_min"])
        for s in clean
        if s.get("live_per_min") is not None and not s.get("stalled")
    ]
    hops = [int(s["hop_i"]) for s in clean if s.get("hop_i") is not None]
    # Prefer wall from first→last clean sample timestamps when available.
    wall_s = float(trial.get("measure_s") or 0)
    if len(clean) >= 2:
        # samples are ~every_s; approximate wall from count if truncated.
        wall_s = min(wall_s, max(1.0, (len(clean) - 1) * float(trial.get("every_s") or 15.0)))
    hop0 = hops[0] if hops else None
    hop1 = hops[-1] if hops else None
    dh = (hop1 - hop0) if (hop0 is not None and hop1 is not None and hop1 >= hop0) else None
    ground = round(60.0 * dh / wall_s, 2) if dh is not None and wall_s > 0 else None
    return {
        "workers": trial.get("workers"),
        "warmup_s": trial.get("warmup_s"),
        "measure_s": trial.get("measure_s"),
        "measure_s_used": round(wall_s, 1) if wall_s else None,
        "session": sess0,
        "hop_start": hop0,
        "hop_end": hop1,
        "hops": dh,
        "samples_kept": len(clean),
        "samples_raw": len(samples),
        "truncated": len(clean) < len(samples),
        "ground_pictures_per_min": ground,
        "meter_n": len(rates),
        "meter_mean": round(sum(rates) / len(rates), 2) if rates else None,
        "meter_median": round(float(median(rates)), 2) if rates else None,
        "meter_min": round(min(rates), 2) if rates else None,
        "meter_max": round(max(rates), 2) if rates else None,
        "ready": trial.get("ready"),
    }


def run(
    *,
    workers_list: list[int] | None = None,
    minutes: float = 10.0,
    warmup_s: float = 90.0,
    every_s: float = 15.0,
    ollama_parallel: int = 6,
    restore_workers: int | None = 6,
) -> dict[str, Any]:
    workers_list = list(workers_list or [4, 5, 6])
    measure_s = float(minutes) * 60.0
    trials: list[dict[str, Any]] = []
    try:
        before = _snap()
    except Exception as exc:  # noqa: BLE001
        before = {"error": str(exc)}

    for n in workers_list:
        print(json.dumps({"trial_start": n, "utc": _now()}), flush=True)
        killed = _kill_backfills()
        time.sleep(1.5)
        rel = release_label_lock(force=True)
        time.sleep(1.0)
        proc = _start_backfill(workers=n, ollama_parallel=max(int(ollama_parallel), int(n)))
        ready = _wait_vision(workers=n, timeout_s=240.0)
        print(json.dumps({"ready": ready, "killed": killed, "release": rel, "pid": proc.pid}), flush=True)
        if not ready.get("ok"):
            trials.append(
                {
                    "workers": n,
                    "ok": False,
                    "ready": ready,
                    "killed": killed,
                    "release": rel,
                    "pid": proc.pid,
                }
            )
            continue
        print(json.dumps({"warmup": warmup_s, "workers": n}), flush=True)
        time.sleep(float(warmup_s))
        # Re-check still on vision after warmup.
        mid = _snap()
        print(json.dumps({"post_warmup": mid}), flush=True)
        t0 = time.monotonic()
        samples = _sample_window(seconds=measure_s, every_s=every_s)
        wall = time.monotonic() - t0
        trial = {
            "ok": True,
            "workers": n,
            "pid": proc.pid,
            "killed": killed,
            "release": rel,
            "ready": ready,
            "session": mid.get("session") or ready.get("session"),
            "warmup_s": float(warmup_s),
            "measure_s": round(wall, 1),
            "every_s": float(every_s),
            "samples": samples,
        }
        trial["summary"] = _summarize(trial)
        trials.append(trial)
        print(json.dumps({"trial_done": trial["summary"]}), flush=True)

    # Restore default workers for ongoing labeling.
    if restore_workers is not None:
        print(json.dumps({"restore": restore_workers, "utc": _now()}), flush=True)
        _kill_backfills()
        time.sleep(1.0)
        release_label_lock(force=True)
        time.sleep(0.5)
        _start_backfill(
            workers=int(restore_workers),
            ollama_parallel=max(int(ollama_parallel), int(restore_workers)),
        )

    summaries = [t.get("summary") or {"workers": t.get("workers"), "ok": t.get("ok")} for t in trials]
    ranked = sorted(
        [s for s in summaries if s.get("ground_pictures_per_min") is not None],
        key=lambda s: float(s["ground_pictures_per_min"]),
        reverse=True,
    )
    out = {
        "ok": True,
        "utc": _now(),
        "before": before,
        "minutes": minutes,
        "warmup_s": warmup_s,
        "every_s": every_s,
        "ollama_parallel": ollama_parallel,
        "restore_workers": restore_workers,
        "trials": trials,
        "summaries": summaries,
        "winner": ranked[0] if ranked else None,
        "note": (
            "ground_pictures_per_min = hop delta / wall over the measure window "
            "(after warmup). meter_* = desk rolling live_per_min samples."
        ),
    }
    out_dir = farm_label_dir() / "audit" / "vision_feed_ab"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"workers_live_ab_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    # Compact samples in on-disk copy if huge — keep full in memory return.
    slim = dict(out)
    slim_trials = []
    for t in trials:
        st = dict(t)
        # keep samples; they're ~40 rows
        slim_trials.append(st)
    slim["trials"] = slim_trials
    path.write_text(json.dumps(slim, indent=2) + "\n", encoding="utf-8")
    out["path"] = str(path)
    print(json.dumps({"wrote": str(path), "summaries": summaries, "winner": out["winner"]}, indent=2), flush=True)
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Live 4/5/6 vision worker A/B on the desk meter")
    p.add_argument("--minutes", type=float, default=10.0)
    p.add_argument("--warmup-s", type=float, default=90.0)
    p.add_argument("--every-s", type=float, default=15.0)
    p.add_argument("--workers", type=str, default="4,5,6", help="Comma list, e.g. 4,5,6")
    p.add_argument("--ollama-parallel", type=int, default=6)
    p.add_argument("--restore-workers", type=int, default=6)
    p.add_argument("--no-restore", action="store_true")
    args = p.parse_args(argv)
    workers = [int(x.strip()) for x in str(args.workers).split(",") if x.strip()]
    run(
        workers_list=workers,
        minutes=float(args.minutes),
        warmup_s=float(args.warmup_s),
        every_s=float(args.every_s),
        ollama_parallel=int(args.ollama_parallel),
        restore_workers=None if args.no_restore else int(args.restore_workers),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
