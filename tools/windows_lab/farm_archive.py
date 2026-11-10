"""Farm archive: temporary media analysis → retain factual labels + audio.

Legal/storage shape:
  - Analyze authorized video/stills locally while hot.
  - Retain on Backblaze: audio.wav + JSON facts/meta (no frames, no video).
  - Stills @ 1 fps stay local only while labeling; purge after facts + human grab.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import DEFAULT_STILL_INTERVAL_SEC, data_root, ensure_data_layout
from .coverage_farm import farm_label_dir, streamers_capture_root
from .visual_archive import distill_video_to_stills

# Retained forever (local gold + cloud).
RETAIN_NAMES = {
    "audio.wav",
    "take.json",
    "label_aid.json",
    "transcript.json",
    "timeline_facts.jsonl",
    "label_manifest.json",
}
# Local-only while labeling (never B2).
LOCAL_TEMP_PREFIXES = ("stills/",)
DROP_AFTER_PREPARE = (
    "video.mp4",
    "av.mp4",
    "audio.log",
    "whisper.err",
    "whisper.log",
    "upload_stderr.log",
    "upload_stdout.log",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _still_count(session_dir: Path) -> int:
    stills = session_dir / "stills"
    if not stills.is_dir():
        return 0
    return len(list(stills.glob("still_t*.jpg")))


def iter_takes(root: Path | None = None) -> list[Path]:
    base = streamers_capture_root(root)
    if not base.is_dir():
        return []
    return sorted(p for p in base.iterdir() if p.is_dir() and (p / "audio.wav").is_file())


def extract_timeline_facts(session_dir: Path) -> dict[str, Any]:
    """Build timeline_facts.jsonl from transcript + label_aid + grab judgments.

    Frames themselves are not retained in the fact file — only t_s and factual fields.
    """
    session_dir = Path(session_dir)
    session = session_dir.name
    rows: list[dict[str, Any]] = []

    aid_path = session_dir / "label_aid.json"
    if aid_path.is_file():
        aid = json.loads(aid_path.read_text(encoding="utf-8"))
        for item in aid.get("timeline") or []:
            rows.append(
                {
                    "t_s": float(item.get("t_s") or 0),
                    "source": "label_aid",
                    "bucket": _map_aid_bucket(str(item.get("kind") or "")),
                    "kind": item.get("kind"),
                    "brand": item.get("brand"),
                    "product": item.get("product"),
                    "onscreen_text": item.get("onscreen_text") or [],
                    "notes": item.get("notes"),
                    "league": item.get("league"),
                    "teams": item.get("teams"),
                }
            )

    transcript_path = session_dir / "transcript.json"
    if transcript_path.is_file():
        tr = json.loads(transcript_path.read_text(encoding="utf-8"))
        for seg in tr.get("segments") or []:
            rows.append(
                {
                    "t_s": float(seg.get("start") or 0),
                    "t_end_s": float(seg.get("end") or 0),
                    "source": "whisper_transcript",
                    "text": seg.get("text"),
                }
            )

    # Human grab regions from /farm
    grab_path = farm_label_dir() / "take_judgments.json"
    if grab_path.is_file():
        grabs = json.loads(grab_path.read_text(encoding="utf-8"))
        judgment = grabs.get(session) or {}
        for region in judgment.get("regions") or []:
            rows.append(
                {
                    "t_s": float(region.get("start_s") or 0),
                    "t_end_s": float(region.get("end_s") or 0),
                    "source": "human_grab",
                    "bucket": region.get("bucket"),
                    "kind": region.get("kind"),
                    "notes": region.get("note"),
                }
            )

    # Still index only (paths local-temp; cloud keeps the index times, not JPEGs)
    stills = session_dir / "stills"
    if stills.is_dir():
        for path in sorted(stills.glob("still_t*.jpg")):
            m = path.name.replace("still_t", "").replace(".jpg", "")
            try:
                t_s = float(m)
            except ValueError:
                continue
            rows.append(
                {
                    "t_s": t_s,
                    "source": "still_index",
                    "local_still": f"stills/{path.name}",
                    "retained_image": False,
                }
            )

    rows.sort(key=lambda r: (float(r.get("t_s") or 0), str(r.get("source") or "")))
    out_path = session_dir / "timeline_facts.jsonl"
    with out_path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return {
        "ok": True,
        "path": str(out_path),
        "rows": len(rows),
        "session": session,
    }


def _map_aid_bucket(kind: str) -> str:
    k = (kind or "").lower()
    if k in ("commercial", "dry_vo", "music_bed_ad"):
        return "paid_ad"
    if k in ("promo_show", "show_promo"):
        return "show_promo"
    if k in ("sponsor_bug", "program_mention", "in_show_sponsorship"):
        return "program_mention"
    if k.startswith("program") or k in ("pip_ad_over_sports",):
        return "program"
    return "uncertain"


def prepare_take(
    session_dir: Path,
    *,
    interval_sec: float = DEFAULT_STILL_INTERVAL_SEC,
    delete_video: bool = True,
    purge_stills: bool = False,
) -> dict[str, Any]:
    """Densify stills for local labeling, extract facts, drop video (and optional stills)."""
    session_dir = Path(session_dir)
    if not (session_dir / "audio.wav").is_file():
        return {"ok": False, "session_dir": str(session_dir), "error": "missing audio.wav"}
    if interval_sec > 1.0:
        return {
            "ok": False,
            "session_dir": str(session_dir),
            "error": "interval must be ≤ 1.0 (1 fps labeling standard)",
        }

    actions: list[str] = []
    densify: dict[str, Any] | None = None
    n_stills = _still_count(session_dir)
    video = session_dir / "video.mp4"
    av = session_dir / "av.mp4"
    source_video = video if video.is_file() else av if av.is_file() else None
    duration_s = (session_dir / "audio.wav").stat().st_size / 192000.0
    need = max(1, int(duration_s / max(interval_sec, 0.5)) - 5)

    if source_video is not None and n_stills < need:
        densify = distill_video_to_stills(
            source_video,
            session_dir=session_dir,
            interval_sec=interval_sec,
            delete_video=False,
        )
        actions.append("densified_stills")
        n_stills = int(densify.get("still_count") or _still_count(session_dir))
    elif n_stills >= need:
        actions.append("stills_already_dense")
    elif source_video is None and n_stills < need:
        actions.append("sparse_stills_no_video")

    facts = extract_timeline_facts(session_dir)
    actions.append("wrote_timeline_facts")

    deleted: list[str] = []
    locked: list[str] = []
    freed = 0

    def _try_unlink(path: Path, label: str) -> None:
        nonlocal freed
        if not path.is_file():
            return
        size = path.stat().st_size
        try:
            path.unlink()
        except PermissionError:
            locked.append(label)
            actions.append(f"locked:{label}")
            return
        freed += size
        deleted.append(label)
        actions.append(f"deleted:{label}")

    if delete_video:
        for name in DROP_AFTER_PREPARE:
            _try_unlink(session_dir / name, name)

    for path in session_dir.glob("frame_*s.jpg"):
        _try_unlink(path, path.name)

    if purge_stills:
        stills = session_dir / "stills"
        if stills.is_dir():
            for path in stills.glob("still_t*.jpg"):
                _try_unlink(path, f"stills/{path.name}")
            actions.append("purged_stills_after_facts")
            n_stills = _still_count(session_dir)

    files = _retain_files(session_dir)
    local_temp_bytes = 0
    stills = session_dir / "stills"
    if stills.is_dir():
        local_temp_bytes = sum(p.stat().st_size for p in stills.glob("still_t*.jpg"))

    manifest = {
        "version": 2,
        "prepared_utc": _now(),
        "session": session_dir.name,
        "session_dir": str(session_dir),
        "doctrine": "retain audio + factual JSON; stills local-temp; never archive video",
        "still_interval_sec": interval_sec,
        "still_count_local": n_stills,
        "timeline_facts_rows": facts.get("rows"),
        "cloud_objects": "audio.wav + JSON only (no stills, no video)",
        "retain_files": files,
        "retain_bytes": sum(int(f["bytes"]) for f in files),
        "local_temp_still_bytes": local_temp_bytes,
        "actions": actions,
        "deleted": deleted,
        "locked": locked,
        "freed_bytes": freed,
        "densify": densify,
    }
    (session_dir / "label_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return {"ok": True, **manifest}


def _retain_files(session_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name in sorted(RETAIN_NAMES):
        path = session_dir / name
        if not path.is_file():
            continue
        rows.append({"path": name, "bytes": path.stat().st_size, "sha256": _sha256(path)})
    return rows


def prepare_all(
    root: Path | None = None,
    *,
    delete_video: bool = True,
    purge_stills: bool = False,
) -> dict[str, Any]:
    results = [
        prepare_take(d, delete_video=delete_video, purge_stills=purge_stills) for d in iter_takes(root)
    ]
    return {
        "ok": all(r.get("ok") for r in results) if results else True,
        "takes": len(results),
        "results": results,
    }


def write_package_index(root: Path | None = None) -> dict[str, Any]:
    """Manifest of retained objects only (audio + JSON) for Backblaze."""
    root = ensure_data_layout(root)
    out = streamers_capture_root(root) / "package_manifest.jsonl"
    rows: list[dict[str, Any]] = []
    for take in iter_takes(root):
        man_path = take / "label_manifest.json"
        if not man_path.is_file():
            prepare_take(take, delete_video=False, purge_stills=False)
        man = json.loads(man_path.read_text(encoding="utf-8")) if man_path.is_file() else {}
        for f in man.get("retain_files") or _retain_files(take):
            rows.append(
                {
                    "session": take.name,
                    "path": f["path"],
                    "bytes": f["bytes"],
                    "sha256": f.get("sha256"),
                    "local": str(take / f["path"]),
                }
            )
    with out.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")
    total = sum(int(r["bytes"]) for r in rows)
    return {
        "ok": True,
        "manifest": str(out),
        "objects": len(rows),
        "bytes_total": total,
        "gb_total": round(total / (1024**3), 3),
        "note": "B2 retain set: audio + JSON facts. Stills/video excluded.",
    }


def rclone_sync_command(
    *,
    remote: str | None = None,
    prefix: str | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    root = data_root() if root is None else root
    remote = remote or os.environ.get("OHUSH_B2_RCLONE_REMOTE") or "b2:ohush-farm"
    prefix = prefix or os.environ.get("OHUSH_B2_PREFIX") or "streamers"
    src = streamers_capture_root(root)
    filter_path = src / "rclone_label_stack.filter"
    filter_path.write_text(
        "\n".join(
            [
                "+ audio.wav",
                "+ take.json",
                "+ label_aid.json",
                "+ transcript.json",
                "+ timeline_facts.jsonl",
                "+ label_manifest.json",
                "+ package_manifest.jsonl",
                "- stills/**",
                "- video.mp4",
                "- av.mp4",
                "- frame_*.jpg",
                "- **",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    dest = f"{remote.rstrip('/')}/{prefix.strip('/')}"
    cmd = [
        "rclone",
        "sync",
        str(src),
        dest,
        "--filter-from",
        str(filter_path),
        "--fast-list",
        "--progress",
    ]
    return {
        "cmd": cmd,
        "cmd_line": subprocess.list2cmdline(cmd),
        "filter": str(filter_path),
        "dest": dest,
        "hint": (
            "Configure rclone B2 remote, set OHUSH_B2_RCLONE_REMOTE, then "
            "python -m tools.windows_lab farm upload-b2 --execute"
        ),
    }


def upload_b2(*, execute: bool = False, root: Path | None = None) -> dict[str, Any]:
    write_package_index(root)
    plan = rclone_sync_command(root=root)
    if not execute:
        return {"ok": True, "dry_run": True, **plan}
    if shutil.which("rclone") is None:
        return {
            "ok": False,
            "error": "rclone not on PATH — install rclone and configure a B2 remote",
            **plan,
        }
    proc = subprocess.run(plan["cmd"], capture_output=True, text=True)
    return {
        "ok": proc.returncode == 0,
        "dry_run": False,
        "returncode": proc.returncode,
        "stdout": (proc.stdout or "")[-4000:],
        "stderr": (proc.stderr or "")[-4000:],
        **plan,
    }


def score_drafts_vs_grab(root: Path | None = None) -> dict[str, Any]:
    label_dir = farm_label_dir(root)
    key_path = label_dir / "key.jsonl"
    grab_path = label_dir / "take_judgments.json"
    if not grab_path.is_file():
        return {"ok": False, "error": "no take_judgments.json — label grabs at /farm first"}
    grabs = json.loads(grab_path.read_text(encoding="utf-8"))
    drafts: list[dict[str, Any]] = []
    if key_path.is_file():
        for line in key_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                drafts.append(json.loads(line))

    compared = 0
    agree = 0
    rows: list[dict[str, Any]] = []
    for draft in drafts:
        clip = str(draft.get("clip") or "")
        session = None
        t0 = t1 = None
        for take_id in grabs:
            if clip.startswith(take_id):
                session = take_id
                rest = clip[len(take_id) + 1 :]
                parts = rest.replace("p", ".").split("_")
                if len(parts) >= 2:
                    try:
                        t0 = float(parts[0])
                        t1 = float(parts[1])
                    except ValueError:
                        t0 = t1 = None
                break
        if session is None or t0 is None or t1 is None:
            continue
        mid = 0.5 * (t0 + t1)
        hit = None
        for region in (grabs.get(session) or {}).get("regions") or []:
            if float(region["start_s"]) <= mid <= float(region["end_s"]):
                hit = region
                break
        if hit is None:
            continue
        compared += 1
        same = str(draft.get("bucket")) == str(hit.get("bucket"))
        if same:
            agree += 1
        rows.append(
            {
                "clip": clip,
                "draft_bucket": draft.get("bucket"),
                "gold_bucket": hit.get("bucket"),
                "agree": same,
            }
        )

    rate = (agree / compared) if compared else None
    out = {
        "ok": True,
        "compared": compared,
        "agree": agree,
        "agree_rate": None if rate is None else round(rate, 3),
        "promote_autonomy": bool(rate is not None and rate >= 0.9 and compared >= 20),
        "rule": (
            "Widen auto-accept only if agree_rate≥0.90 on ≥20 grab overlaps "
            "from takes labeled before drafts were read."
        ),
        "rows": rows[:50],
    }
    (label_dir / "draft_score.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    return out
