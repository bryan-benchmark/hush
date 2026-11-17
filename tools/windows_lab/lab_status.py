"""Write / read a one-page lab status blob for the monitor /status UI.

  python -m tools.windows_lab.lab_status
  python -m tools.windows_lab.lab_status --write-progress session=... i=3 of=9
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

from .coverage_farm import farm_label_dir
from .export_farm_acoustic_gold import OUT as FARM_ACCEPTED


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def status_path() -> Path:
    return farm_label_dir() / "audit" / "LAB_STATUS.json"


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


def _probe(url: str, timeout: float = 1.5) -> bool:
    try:
        with urlopen(url, timeout=timeout) as resp:
            return 200 <= int(getattr(resp, "status", 200) or 200) < 500
    except (URLError, TimeoutError, OSError):
        return False


def _verdict_queue() -> dict[str, Any]:
    try:
        from .farm_episode_viewer import _enrich, _load_triage

        blob = _enrich(_load_triage(), chunk_size=4)
        chunk = blob.get("chunk") or {}
        return {
            "pending": chunk.get("pending_total"),
            "done": chunk.get("done_total"),
            "in_chunk": chunk.get("in_chunk"),
            "episodes": chunk.get("episode_total"),
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


def build_status(*, progress: dict[str, Any] | None = None) -> dict[str, Any]:
    audit = farm_label_dir() / "audit"
    sessions = _accepted_sessions()
    rows: list[dict[str, Any]] = []
    for s in sessions:
        d = audit / s
        rows.append(
            {
                "session": s,
                "acoustic": (d / "hops_acoustic.jsonl").is_file(),
                "vision": (d / "hops_vision.jsonl").is_file(),
                "combined": (d / "hops.jsonl").is_file(),
            }
        )
    n_vision = sum(1 for r in rows if r["vision"])
    n_acoustic = sum(1 for r in rows if r["acoustic"])

    score: dict[str, Any] = {}
    sc_path = farm_label_dir() / "LIVE_SCORECARD.json"
    if sc_path.is_file():
        try:
            score = (json.loads(sc_path.read_text(encoding="utf-8")).get("aggregate") or {})
        except json.JSONDecodeError:
            score = {}

    shadow: dict[str, Any] = {}
    sh_path = audit / "EPISODE_YOU_SHADOW_REFIT.json"
    if sh_path.is_file():
        try:
            raw = json.loads(sh_path.read_text(encoding="utf-8"))
            shadow = {
                "keep": (raw.get("verdict") or {}).get("keep"),
                "drop_s": (raw.get("verdict") or {}).get("program_muted_drop_s"),
                "reason": (raw.get("verdict") or {}).get("reason"),
            }
        except json.JSONDecodeError:
            shadow = {}

    prev = {}
    if status_path().is_file():
        try:
            prev = json.loads(status_path().read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            prev = {}

    job = dict(prev.get("job") or {})
    if progress:
        job.update(progress)
        job["updated_utc"] = _now()

    return {
        "updated_utc": _now(),
        "accepted_sessions": len(sessions),
        "channels_ready": {
            "acoustic": n_acoustic,
            "vision": n_vision,
            "combined": sum(1 for r in rows if r["combined"]),
            "of": len(sessions),
        },
        "sessions": rows,
        "verdict_queue": _verdict_queue(),
        "scorecard": {
            "program_muted_s": score.get("program_muted_s"),
            "commercial_coverage": score.get("commercial_coverage"),
            "broken": score.get("broken"),
        },
        "shadow": shadow,
        "job": job,
        "services": {
            "viewer_3020": _probe("http://127.0.0.1:3020/"),
            "engine_8770": _probe("http://127.0.0.1:8770/state"),
            "monitor_3010": _probe("http://127.0.0.1:3010/"),
        },
        "links": {
            "verdict": "/verdict",
            "farm": "/farm",
            "local_viewer": "http://127.0.0.1:3020/",
        },
    }


def write_status(*, progress: dict[str, Any] | None = None) -> Path:
    path = status_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    blob = build_status(progress=progress)
    path.write_text(json.dumps(blob, indent=2) + "\n", encoding="utf-8")
    return path


def write_job_progress(progress: dict[str, Any]) -> Path:
    """Hot-path heartbeat: patch only ``job`` — do not rebuild the whole lab board.

    Full ``write_status`` probes services + verdict queue (~seconds). Vision calls this
    every still; that tax was larger than the GPU gap we were trying to close.
    """
    path = status_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    prev: dict[str, Any] = {}
    if path.is_file():
        try:
            prev = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            prev = {}
    job = dict(prev.get("job") or {})
    job.update(progress or {})
    job["updated_utc"] = _now()
    prev["job"] = job
    prev["updated_utc"] = _now()
    path.write_text(json.dumps(prev, indent=2) + "\n", encoding="utf-8")
    # Feed rolling /min meters (last ~60s wall) — only for the active audit.
    try:
        phase = str(job.get("phase") or "")
        if job.get("hop_i") is not None and phase in {"vision", "acoustic"}:
            from .farm_label_timing import record_label_rate_sample

            record_label_rate_sample(
                hop_i=job.get("hop_i"),
                session=str(job.get("session") or "") or None,
                kind="pictures" if phase == "vision" else "sound",
            )
    except Exception:
        pass
    return path


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Lab status blob for /status")
    p.add_argument("--progress-json", type=str, default=None, help="JSON object merged into job")
    args = p.parse_args(argv)
    progress = json.loads(args.progress_json) if args.progress_json else None
    path = write_status(progress=progress)
    print(json.dumps({"ok": True, "path": str(path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
