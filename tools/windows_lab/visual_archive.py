"""Sparse visual archive for labeling: stills by default, short edge clips on demand.

Full audio stays in the session. Full video is optional (`av_full`) or temporary
input for distill. Contested label windows keep short clips under edge_clips/.
"""

from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .instances import ffmpeg_path

DEFAULT_STILL_INTERVAL_SEC = 1.0
DEFAULT_EDGE_PAD_SEC = 10.0
STILLS_DIRNAME = "stills"
EDGE_CLIPS_DIRNAME = "edge_clips"
MANIFEST_NAME = "manifest.jsonl"
ARCHIVE_META_NAME = "archive.json"

_STILL_NAME_RE = re.compile(r"^still_t(\d+(?:\.\d+)?)\.(?:jpg|jpeg|png)$", re.I)
_VIDEO_CHUNK_RE = re.compile(r"^video_(\d+)\.mp4$", re.I)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def stills_dir(session_dir: Path) -> Path:
    return Path(session_dir) / STILLS_DIRNAME


def edge_clips_dir(session_dir: Path) -> Path:
    return Path(session_dir) / EDGE_CLIPS_DIRNAME


def still_filename(t_sec: float) -> str:
    return f"still_t{t_sec:07.1f}.jpg"


def load_meta(session_dir: Path) -> dict[str, Any]:
    path = Path(session_dir) / "meta.json"
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_meta(session_dir: Path, meta: dict[str, Any]) -> Path:
    path = Path(session_dir) / "meta.json"
    path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return path


def append_still_manifest(session_dir: Path, rows: list[dict[str, Any]]) -> Path:
    path = stills_dir(session_dir) / MANIFEST_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path


def read_still_manifest(session_dir: Path) -> list[dict[str, Any]]:
    path = stills_dir(session_dir) / MANIFEST_NAME
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def list_session_videos(session_dir: Path) -> list[tuple[int, Path]]:
    found: list[tuple[int, Path]] = []
    for path in sorted(Path(session_dir).glob("video_*.mp4")):
        m = _VIDEO_CHUNK_RE.match(path.name)
        idx = int(m.group(1)) if m else len(found)
        found.append((idx, path))
    return found


def distill_video_to_stills(
    video_path: Path,
    *,
    session_dir: Path,
    t0_sec: float = 0.0,
    interval_sec: float = DEFAULT_STILL_INTERVAL_SEC,
    chunk_index: int | None = None,
    delete_video: bool = False,
    temp_tag: str | None = None,
) -> dict[str, Any]:
    """Extract one JPEG every interval_sec from a video into session stills/."""
    ff = ffmpeg_path()
    if not ff:
        raise RuntimeError("ffmpeg not found on PATH")
    if interval_sec <= 0:
        raise ValueError("interval_sec must be > 0")
    video_path = Path(video_path)
    if not video_path.is_file():
        raise FileNotFoundError(str(video_path))

    out = stills_dir(session_dir)
    out.mkdir(parents=True, exist_ok=True)
    # Intermediate sequential names; rename to absolute session times.
    tag = temp_tag or f"chunk{chunk_index if chunk_index is not None else 0}"
    pattern = out / f"_{tag}_%06d.jpg"
    fps = 1.0 / float(interval_sec)
    cmd = [
        ff,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(video_path),
        "-vf",
        f"fps={fps}",
        "-q:v",
        "3",
        str(pattern),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if proc.returncode != 0:
        return {
            "ok": False,
            "video": str(video_path),
            "error": (proc.stderr or "").strip()[-1000:] or "ffmpeg distill failed",
            "stills": [],
        }

    temp_files = sorted(out.glob(f"_{tag}_*.jpg"))
    rows: list[dict[str, Any]] = []
    for i, temp in enumerate(temp_files):
        t_sec = round(t0_sec + i * interval_sec, 1)
        name = still_filename(t_sec)
        dest = out / name
        if dest.exists():
            dest.unlink()
        temp.rename(dest)
        rows.append(
            {
                "t_sec": t_sec,
                "path": f"{STILLS_DIRNAME}/{name}",
                "chunk_index": chunk_index,
                "source_video": video_path.name,
                "interval_sec": interval_sec,
            }
        )
    if rows:
        append_still_manifest(session_dir, rows)

    deleted = False
    if delete_video and rows:
        video_path.unlink(missing_ok=True)
        deleted = not video_path.is_file()

    return {
        "ok": True,
        "video": str(video_path),
        "still_count": len(rows),
        "t0_sec": t0_sec,
        "interval_sec": interval_sec,
        "deleted_video": deleted,
        "stills": rows,
    }


def distill_session(
    session_dir: Path,
    *,
    interval_sec: float = DEFAULT_STILL_INTERVAL_SEC,
    delete_videos: bool = True,
    chunk_minutes: float | None = None,
) -> dict[str, Any]:
    """Turn retained video_XXXX.mp4 chunks into sparse stills for labeling."""
    session_dir = Path(session_dir)
    meta = load_meta(session_dir)
    if chunk_minutes is None:
        chunk_minutes = float(meta.get("chunk_minutes") or 15.0)
    chunk_seconds = float(chunk_minutes) * 60.0

    videos = list_session_videos(session_dir)
    results: list[dict[str, Any]] = []
    warnings: list[str] = []
    total = 0
    for idx, path in videos:
        t0 = idx * chunk_seconds
        # Prefer duration from meta chunks when present.
        for ch in meta.get("chunks") or []:
            if ch.get("index") == idx and ch.get("duration_sec") is not None:
                # t0 from prior chunk durations is safer if uneven; keep index*chunk as default.
                break
        row = distill_video_to_stills(
            path,
            session_dir=session_dir,
            t0_sec=t0,
            interval_sec=interval_sec,
            chunk_index=idx,
            delete_video=delete_videos,
        )
        results.append(row)
        if not row.get("ok"):
            warnings.append(f"distill_{idx}: {row.get('error')}")
        else:
            total += int(row.get("still_count") or 0)
            if delete_videos and row.get("deleted_video"):
                for ch in meta.get("chunks") or []:
                    if ch.get("index") == idx:
                        ch["video"] = None
                        ch["video_distilled"] = True

    archive = {
        "mode": "stills",
        "still_interval_sec": interval_sec,
        "stills_dir": STILLS_DIRNAME,
        "still_count": len(read_still_manifest(session_dir)),
        "distilled_utc": _now(),
        "videos_deleted": bool(delete_videos),
        "edge_clips_dir": EDGE_CLIPS_DIRNAME,
    }
    meta["visual_archive"] = archive
    if warnings:
        meta.setdefault("warnings", []).extend(warnings)
    # Drop video names from chunks when deleted.
    if delete_videos:
        for ch in meta.get("chunks") or []:
            if ch.get("video") and not (session_dir / str(ch["video"])).is_file():
                ch["video"] = None
                ch["video_distilled"] = True
    save_meta(session_dir, meta)
    (stills_dir(session_dir) / ARCHIVE_META_NAME).write_text(
        json.dumps(archive, indent=2), encoding="utf-8"
    )
    return {
        "ok": not warnings or total > 0,
        "session_dir": str(session_dir),
        "videos": len(videos),
        "still_count": archive["still_count"],
        "interval_sec": interval_sec,
        "deleted_videos": delete_videos,
        "results": results,
        "warnings": warnings,
        "visual_archive": archive,
    }


def stills_in_window(
    session_dir: Path,
    start_s: float,
    end_s: float,
) -> list[dict[str, Any]]:
    rows = read_still_manifest(session_dir)
    if not rows:
        # Fall back to filename parse if manifest missing.
        for path in sorted(stills_dir(session_dir).glob("still_t*.jpg")):
            m = _STILL_NAME_RE.match(path.name)
            if not m:
                continue
            t = float(m.group(1))
            rows.append({"t_sec": t, "path": f"{STILLS_DIRNAME}/{path.name}"})
    return [r for r in rows if start_s <= float(r.get("t_sec", -1)) <= end_s]


def extract_edge_clip(
    session_dir: Path,
    *,
    start_s: float,
    end_s: float,
    pad_sec: float = DEFAULT_EDGE_PAD_SEC,
    label: str | None = None,
    kind: str = "contested",
) -> dict[str, Any]:
    """Keep a short clip (or still pack) around a contested label boundary.

    Prefers source video when present. Otherwise copies the stills that fall in
    the padded window into edge_clips/<id>/ for review without a full tape.
    """
    session_dir = Path(session_dir)
    if end_s < start_s:
        raise ValueError("end_s must be >= start_s")
    meta = load_meta(session_dir)
    chunk_minutes = float(meta.get("chunk_minutes") or 15.0)
    chunk_seconds = chunk_minutes * 60.0
    clip_start = max(0.0, float(start_s) - float(pad_sec))
    clip_end = float(end_s) + float(pad_sec)
    duration = max(0.1, clip_end - clip_start)

    out_root = edge_clips_dir(session_dir)
    out_root.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", (label or kind))[:48] or "edge"
    clip_id = f"{slug}_{clip_start:.1f}_{clip_end:.1f}".replace(".", "p")
    clip_dir = out_root / clip_id
    clip_dir.mkdir(parents=True, exist_ok=True)

    record: dict[str, Any] = {
        "id": clip_id,
        "kind": kind,
        "label": label,
        "start_s": start_s,
        "end_s": end_s,
        "pad_sec": pad_sec,
        "clip_start_s": clip_start,
        "clip_end_s": clip_end,
        "created_utc": _now(),
        "video": None,
        "stills": [],
        "audio": None,
    }

    # Try video chunk covering clip_start.
    chunk_idx = int(clip_start // chunk_seconds)
    video_name = f"video_{chunk_idx:04d}.mp4"
    video_path = session_dir / video_name
    ff = ffmpeg_path()
    if video_path.is_file() and ff:
        local_t0 = clip_start - chunk_idx * chunk_seconds
        # If window spills into next chunk, clamp to this file; caller can request again.
        max_local = chunk_seconds - local_t0
        take = min(duration, max_local)
        outfile = clip_dir / "clip.mp4"
        cmd = [
            ff,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            str(local_t0),
            "-i",
            str(video_path),
            "-t",
            str(take),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-an",
            str(outfile),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if proc.returncode == 0 and outfile.is_file():
            record["video"] = f"{EDGE_CLIPS_DIRNAME}/{clip_id}/clip.mp4"
        else:
            record["video_error"] = (proc.stderr or "").strip()[-500:] or "ffmpeg edge clip failed"

    # Always attach stills in the padded window for contact-sheet review.
    window_stills = stills_in_window(session_dir, clip_start, clip_end)
    copied: list[dict[str, Any]] = []
    for row in window_stills:
        src = session_dir / str(row["path"])
        if not src.is_file():
            continue
        dest = clip_dir / src.name
        if not dest.exists():
            dest.write_bytes(src.read_bytes())
        copied.append(
            {
                "t_sec": row.get("t_sec"),
                "path": f"{EDGE_CLIPS_DIRNAME}/{clip_id}/{src.name}",
            }
        )
    record["stills"] = copied

    # Optional audio excerpt from chunk wav.
    audio_name = f"audio_{chunk_idx:04d}.wav"
    audio_path = session_dir / audio_name
    if audio_path.is_file() and ff:
        local_t0 = clip_start - chunk_idx * chunk_seconds
        take = min(duration, chunk_seconds - local_t0)
        aout = clip_dir / "clip.wav"
        cmd = [
            ff,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            str(local_t0),
            "-i",
            str(audio_path),
            "-t",
            str(take),
            str(aout),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if proc.returncode == 0 and aout.is_file():
            record["audio"] = f"{EDGE_CLIPS_DIRNAME}/{clip_id}/clip.wav"

    (clip_dir / "edge.json").write_text(json.dumps(record, indent=2), encoding="utf-8")

    edges = list(meta.get("edge_clips") or [])
    edges.append(record)
    meta["edge_clips"] = edges
    archive = dict(meta.get("visual_archive") or {})
    archive.setdefault("mode", "stills" if not list_session_videos(session_dir) else archive.get("mode", "mixed"))
    archive["edge_clips_dir"] = EDGE_CLIPS_DIRNAME
    archive["edge_clip_count"] = len(edges)
    meta["visual_archive"] = archive
    save_meta(session_dir, meta)

    return {
        "ok": bool(record.get("video") or record.get("stills") or record.get("audio")),
        "session_dir": str(session_dir),
        "edge_clip": record,
    }


def session_archive_info(session_dir: Path) -> dict[str, Any]:
    session_dir = Path(session_dir)
    meta = load_meta(session_dir)
    videos = list_session_videos(session_dir)
    stills = read_still_manifest(session_dir)
    audio = sorted(p.name for p in session_dir.glob("audio_*.wav"))
    return {
        "session_dir": str(session_dir),
        "session_id": meta.get("session_id"),
        "media": meta.get("media"),
        "visual_archive": meta.get("visual_archive"),
        "video_count": len(videos),
        "videos": [p.name for _, p in videos],
        "still_count": len(stills),
        "audio_files": audio,
        "edge_clip_count": len(meta.get("edge_clips") or []),
        "label_status": meta.get("label_status"),
    }


# BlueStacks Android screenrecord --time-limit tops out at a few minutes on this build.
ADB_SCREENRECORD_MAX_SEC = 170
ADB_DEVICE_SEG = "/sdcard/ohush_still_seg.mp4"


def record_stills_adb(
    *,
    instance: dict[str, Any],
    seconds: float,
    session_dir: Path,
    interval_sec: float = DEFAULT_STILL_INTERVAL_SEC,
    t0_sec: float = 0.0,
    chunk_index: int | None = None,
) -> dict[str, Any]:
    """Capture stills from the Android framebuffer via ADB.

    Independent of Windows window size, position, z-order, or minimize.
    Uses short `screenrecord` segments (device limit), then distills to 1 fps JPEGs.
    Falls back to timed `screencap` if screenrecord fails.
    """
    from .instances import adb, adb_bytes, connect_adb

    if interval_sec <= 0:
        raise ValueError("interval_sec must be > 0")
    session_dir = Path(session_dir)
    out = stills_dir(session_dir)
    out.mkdir(parents=True, exist_ok=True)
    connect_adb(instance)

    remaining = float(seconds)
    cursor_t = float(t0_sec)
    still_total = 0
    segments: list[dict[str, Any]] = []
    errors: list[str] = []
    mode = "screenrecord"
    seg_i = 0

    while remaining > 0.5:
        seg_len = min(float(ADB_SCREENRECORD_MAX_SEC), remaining)
        local_mp4 = session_dir / f"_adb_seg_{chunk_index if chunk_index is not None else 0}_{seg_i}.mp4"
        adb(instance, ["shell", "rm", "-f", ADB_DEVICE_SEG], timeout=10)
        code, out_txt = adb(
            instance,
            [
                "shell",
                "screenrecord",
                "--time-limit",
                str(max(1, int(round(seg_len)))),
                "--bit-rate",
                "4000000",
                ADB_DEVICE_SEG,
            ],
            timeout=seg_len + 90,
        )
        if code != 0:
            errors.append(f"screenrecord:{out_txt[-400:]}")
            mode = "screencap"
            break

        code, pull_txt = adb(instance, ["pull", ADB_DEVICE_SEG, str(local_mp4)], timeout=120)
        adb(instance, ["shell", "rm", "-f", ADB_DEVICE_SEG], timeout=10)
        if code != 0 or not local_mp4.is_file() or local_mp4.stat().st_size < 1000:
            errors.append(f"pull:{pull_txt[-400:]}")
            mode = "screencap"
            local_mp4.unlink(missing_ok=True)
            break

        distilled = distill_video_to_stills(
            local_mp4,
            session_dir=session_dir,
            t0_sec=cursor_t,
            interval_sec=interval_sec,
            chunk_index=chunk_index,
            delete_video=True,
            temp_tag=f"adb{chunk_index if chunk_index is not None else 0}s{seg_i}",
        )
        n = int(distilled.get("still_count") or 0)
        still_total += n
        segments.append(
            {
                "seg": seg_i,
                "seconds": seg_len,
                "t0_sec": cursor_t,
                "still_count": n,
                "ok": bool(distilled.get("ok")),
                "error": distilled.get("error"),
            }
        )
        if not distilled.get("ok"):
            errors.append(str(distilled.get("error") or "distill failed"))
        cursor_t += seg_len
        remaining -= seg_len
        seg_i += 1

    if mode == "screencap" and remaining > 0.5:
        # Timed PNG dumps — works minimized / covered / odd window sizes.
        import time as _time

        cap_start = _time.perf_counter()
        i = 0
        while (_time.perf_counter() - cap_start) < remaining - 0.05:
            target_t = cursor_t + i * interval_sec
            code, png, err = adb_bytes(instance, ["exec-out", "screencap", "-p"], timeout=20)
            if code != 0 or len(png) < 100:
                errors.append(f"screencap:{err or 'empty'}")
                break
            # BlueStacks sometimes prefixes junk; keep from PNG signature.
            sig = png.find(b"\x89PNG")
            if sig > 0:
                png = png[sig:]
            name = still_filename(round(target_t, 1))
            (out / name).write_bytes(png)
            append_still_manifest(
                session_dir,
                [
                    {
                        "t_sec": round(target_t, 1),
                        "path": f"{STILLS_DIRNAME}/{name}",
                        "chunk_index": chunk_index,
                        "interval_sec": interval_sec,
                        "source": "adb_screencap",
                    }
                ],
            )
            still_total += 1
            i += 1
            sleep_for = (i * interval_sec) - (_time.perf_counter() - cap_start)
            if sleep_for > 0.01:
                _time.sleep(sleep_for)
        segments.append({"seg": "screencap_tail", "still_count": i, "ok": i > 0})

    ok = still_total > 0
    return {
        "ok": ok,
        "source": "adb",
        "mode": mode,
        "still_count": still_total,
        "interval_sec": interval_sec,
        "t0_sec": t0_sec,
        "segments": segments,
        "error": None if ok else ("; ".join(errors)[-1000:] or "adb stills failed"),
        "errors": errors[-8:],
        "note": "Android framebuffer — ignores Windows window size/position/z-order/minimize",
    }


def record_stills_gdigrab(
    *,
    window_title: str,
    seconds: float,
    session_dir: Path,
    interval_sec: float = DEFAULT_STILL_INTERVAL_SEC,
    t0_sec: float = 0.0,
    chunk_index: int | None = None,
) -> dict[str, Any]:
    """Capture sparse stills from a desktop window (needs visible, uncovered window)."""
    ff = ffmpeg_path()
    if not ff:
        raise RuntimeError("ffmpeg not found on PATH")
    if interval_sec <= 0:
        raise ValueError("interval_sec must be > 0")
    out = stills_dir(session_dir)
    out.mkdir(parents=True, exist_ok=True)
    fps = 1.0 / float(interval_sec)
    pattern = out / f"_live{chunk_index if chunk_index is not None else 0}_%06d.jpg"
    cmd = [
        ff,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "gdigrab",
        "-framerate",
        str(fps),
        "-i",
        f"title={window_title}",
        "-t",
        str(seconds),
        "-vf",
        f"fps={fps},scale=trunc(iw/2)*2:trunc(ih/2)*2",
        "-q:v",
        "3",
        str(pattern),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=seconds + 120)
    if proc.returncode != 0:
        return {
            "ok": False,
            "error": (proc.stderr or "").strip()[-1000:] or "ffmpeg stills capture failed",
            "stills": [],
            "cmd": cmd,
        }

    temp_files = sorted(out.glob(f"_live{chunk_index if chunk_index is not None else 0}_*.jpg"))
    rows: list[dict[str, Any]] = []
    for i, temp in enumerate(temp_files):
        t_sec = round(t0_sec + i * interval_sec, 1)
        name = still_filename(t_sec)
        dest = out / name
        if dest.exists():
            dest.unlink()
        temp.rename(dest)
        rows.append(
            {
                "t_sec": t_sec,
                "path": f"{STILLS_DIRNAME}/{name}",
                "chunk_index": chunk_index,
                "interval_sec": interval_sec,
            }
        )
    if rows:
        append_still_manifest(session_dir, rows)
    return {
        "ok": True,
        "still_count": len(rows),
        "interval_sec": interval_sec,
        "t0_sec": t0_sec,
        "stills": rows,
        "cmd": cmd,
    }


def record_stills_dshow(
    *,
    video_device: str,
    seconds: float,
    session_dir: Path,
    interval_sec: float = DEFAULT_STILL_INTERVAL_SEC,
    t0_sec: float = 0.0,
    chunk_index: int | None = None,
) -> dict[str, Any]:
    """Capture sparse stills from a DirectShow video device (OTA)."""
    ff = ffmpeg_path()
    if not ff:
        raise RuntimeError("ffmpeg not found on PATH")
    out = stills_dir(session_dir)
    out.mkdir(parents=True, exist_ok=True)
    fps = 1.0 / float(interval_sec)
    pattern = out / f"_ota{chunk_index if chunk_index is not None else 0}_%06d.jpg"
    cmd = [
        ff,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "dshow",
        "-i",
        f"video={video_device}",
        "-t",
        str(seconds),
        "-vf",
        f"fps={fps}",
        "-q:v",
        "3",
        str(pattern),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=seconds + 120)
    if proc.returncode != 0:
        return {
            "ok": False,
            "error": (proc.stderr or "").strip()[-1000:] or "ffmpeg ota stills failed",
            "stills": [],
            "cmd": cmd,
        }
    temp_files = sorted(out.glob(f"_ota{chunk_index if chunk_index is not None else 0}_*.jpg"))
    rows: list[dict[str, Any]] = []
    for i, temp in enumerate(temp_files):
        t_sec = round(t0_sec + i * interval_sec, 1)
        name = still_filename(t_sec)
        dest = out / name
        if dest.exists():
            dest.unlink()
        temp.rename(dest)
        rows.append(
            {
                "t_sec": t_sec,
                "path": f"{STILLS_DIRNAME}/{name}",
                "chunk_index": chunk_index,
                "interval_sec": interval_sec,
            }
        )
    if rows:
        append_still_manifest(session_dir, rows)
    return {
        "ok": True,
        "still_count": len(rows),
        "interval_sec": interval_sec,
        "t0_sec": t0_sec,
        "stills": rows,
        "cmd": cmd,
    }


def write_visual_archive_meta(
    session_dir: Path,
    *,
    mode: str,
    interval_sec: float,
    still_count: int,
) -> dict[str, Any]:
    """Write stills/archive.json and return the visual_archive dict for meta.json."""
    archive = {
        "mode": mode,
        "still_interval_sec": interval_sec,
        "stills_dir": STILLS_DIRNAME,
        "still_count": still_count,
        "edge_clips_dir": EDGE_CLIPS_DIRNAME,
        "updated_utc": _now(),
    }
    stills_dir(session_dir).mkdir(parents=True, exist_ok=True)
    (stills_dir(session_dir) / ARCHIVE_META_NAME).write_text(
        json.dumps(archive, indent=2), encoding="utf-8"
    )
    return archive


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(
        description="Sparse visual archive: distill videos to stills, keep edge clips"
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("distill", help="Extract stills from session video_*.mp4 and optionally delete them")
    d.add_argument("--session-dir", required=True)
    d.add_argument("--interval", type=float, default=DEFAULT_STILL_INTERVAL_SEC)
    d.add_argument("--keep-video", action="store_true", help="Leave video_*.mp4 in place")

    e = sub.add_parser("edge-clip", help="Store a short contested-boundary clip/still pack")
    e.add_argument("--session-dir", required=True)
    e.add_argument("--start", type=float, required=True, help="Label start seconds")
    e.add_argument("--end", type=float, required=True, help="Label end seconds")
    e.add_argument("--pad", type=float, default=DEFAULT_EDGE_PAD_SEC)
    e.add_argument("--label")
    e.add_argument("--kind", default="contested")

    i = sub.add_parser("info", help="Summarize session visual archive")
    i.add_argument("--session-dir", required=True)

    args = p.parse_args(argv)
    if args.cmd == "distill":
        result = distill_session(
            Path(args.session_dir),
            interval_sec=args.interval,
            delete_videos=not args.keep_video,
        )
        print(json.dumps(result, indent=2, default=str))
        return 0 if result.get("ok") else 1
    if args.cmd == "edge-clip":
        result = extract_edge_clip(
            Path(args.session_dir),
            start_s=args.start,
            end_s=args.end,
            pad_sec=args.pad,
            label=args.label,
            kind=args.kind,
        )
        print(json.dumps(result, indent=2, default=str))
        return 0 if result.get("ok") else 1
    if args.cmd == "info":
        print(json.dumps(session_archive_info(Path(args.session_dir)), indent=2, default=str))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
