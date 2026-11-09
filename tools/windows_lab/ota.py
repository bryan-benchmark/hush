"""OTA antenna / ATSC tuner backend for the capture farm."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import ensure_data_layout, ota_config_path
from .instances import ffmpeg_path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_ota_config() -> dict[str, Any]:
    return {
        "updated_utc": _now(),
        "antenna": "HD 4-1 (delivered)",
        "default_tuner": "default",
        "tuners": {
            "default": {
                "label": "USB ATSC tuner (attach when available)",
                "ffmpeg_video_device": "",
                "ffmpeg_audio_device": "",
                "dshow_video": "",
                "dshow_audio": "",
                "audio_device": "",
                "loopback_device": "",
                "window_title": "",
                "notes": (
                    "Antenna is RF only. Plug a USB/PCIe ATSC tuner, then set "
                    "dshow_video / dshow_audio (or ffmpeg device names) and run ota scan."
                ),
            }
        },
        "channel_map": {},
    }


def get_ota_config(root: Path | None = None) -> dict[str, Any]:
    ensure_data_layout(root)
    path = ota_config_path(root)
    if not path.is_file():
        cfg = default_ota_config()
        save_ota_config(cfg, root)
        return cfg
    return json.loads(path.read_text(encoding="utf-8"))


def save_ota_config(cfg: dict[str, Any], root: Path | None = None) -> Path:
    ensure_data_layout(root)
    path = ota_config_path(root)
    cfg = dict(cfg)
    cfg["updated_utc"] = _now()
    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return path


def resolve_tuner(tuner_id: str, root: Path | None = None) -> dict[str, Any]:
    cfg = get_ota_config(root)
    tuners = cfg.get("tuners") or {}
    if tuner_id not in tuners:
        raise KeyError(f"unknown tuner {tuner_id!r}; known={list(tuners)}")
    return {"id": tuner_id, **tuners[tuner_id]}


def _run(cmd: list[str], timeout: float = 30.0) -> tuple[int, str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        return int(proc.returncode), ((proc.stdout or "") + (proc.stderr or "")).strip()
    except FileNotFoundError as e:
        return 127, str(e)
    except subprocess.TimeoutExpired:
        return 124, "timeout"


def list_dshow_devices() -> dict[str, Any]:
    ff = ffmpeg_path()
    if not ff:
        return {"video": [], "audio": [], "error": ["ffmpeg missing"]}
    # ffmpeg prints device list to stderr (format varies by build)
    code, out = _run([ff, "-hide_banner", "-list_devices", "true", "-f", "dshow", "-i", "dummy"], timeout=20.0)
    video: list[str] = []
    audio: list[str] = []
    section = None
    for line in out.splitlines():
        lower = line.lower()
        if "directshow video devices" in lower or "dshow video devices" in lower:
            section = "video"
            continue
        if "directshow audio devices" in lower or "dshow audio devices" in lower:
            section = "audio"
            continue
        if '"' not in line:
            continue
        name = line.split('"', 1)[1].rsplit('"', 1)[0]
        if not name or name.startswith("@"):
            continue
        # Newer ffmpeg: `"Name" (audio)` / `"Name" (none)` / `"Name" (video)`
        if "(audio)" in lower:
            audio.append(name)
            continue
        if "(video)" in lower:
            video.append(name)
            continue
        if "(none)" in lower:
            # Often a video device (e.g. OBS Virtual Camera) when type is none
            video.append(name)
            continue
        if section == "video":
            video.append(name)
        elif section == "audio":
            audio.append(name)
    return {"video": video, "audio": audio, "ffmpeg_rc": code}


def doctor(root: Path | None = None) -> dict[str, Any]:
    cfg = get_ota_config(root)
    devices = list_dshow_devices()
    tuners = []
    for tid, tcfg in (cfg.get("tuners") or {}).items():
        video = str(tcfg.get("dshow_video") or tcfg.get("ffmpeg_video_device") or "")
        audio = str(tcfg.get("dshow_audio") or tcfg.get("ffmpeg_audio_device") or tcfg.get("audio_device") or "")
        video_ok = bool(video) and (not devices.get("video") or video in devices.get("video", []))
        audio_ok = bool(audio) and (
            not devices.get("audio") or audio in devices.get("audio", []) or bool(tcfg.get("loopback_device"))
        )
        # Without a tuner attached, configured blanks are expected — report not ready.
        ready = bool(video) and (bool(audio) or bool(tcfg.get("loopback_device")))
        tuners.append(
            {
                "id": tid,
                "ready": ready,
                "video_device": video,
                "audio_device": audio,
                "video_seen": video_ok if video else False,
                "audio_seen": audio_ok if audio else False,
                "notes": tcfg.get("notes"),
            }
        )
    any_ready = any(t["ready"] for t in tuners)
    return {
        "checked_utc": _now(),
        "ok": any_ready,
        "antenna": cfg.get("antenna"),
        "ffmpeg": ffmpeg_path(),
        "dshow_devices": devices,
        "tuners": tuners,
        "channel_map_count": len(cfg.get("channel_map") or {}),
        "guidance": (
            "Tuner ready."
            if any_ready
            else "Attach a USB ATSC tuner to the HD 4-1 antenna, set dshow_video/dshow_audio in farm/ota.json, then re-run doctor."
        ),
        "config_path": str(ota_config_path(root)),
    }


def scan(root: Path | None = None) -> dict[str, Any]:
    """Record discovered DirectShow devices; channel scan requires tuner-specific tooling."""
    cfg = get_ota_config(root)
    devices = list_dshow_devices()
    cfg["last_scan_utc"] = _now()
    cfg["last_scan_devices"] = devices
    save_ota_config(cfg, root)
    return {
        "ok": True,
        "scanned_utc": cfg["last_scan_utc"],
        "devices": devices,
        "note": (
            "Device list refreshed. Map RF virtual channels in farm/ota.json channel_map "
            "(e.g. {\"7.1\": {\"major\": 7, \"minor\": 1, \"label\": \"ABC\"}})."
        ),
        "channel_map": cfg.get("channel_map") or {},
    }


def upsert_channel(
    channel_id: str,
    *,
    major: int | None = None,
    minor: int | None = None,
    label: str | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    cfg = get_ota_config(root)
    cmap = dict(cfg.get("channel_map") or {})
    row = dict(cmap.get(channel_id) or {})
    if major is not None:
        row["major"] = major
    if minor is not None:
        row["minor"] = minor
    if label is not None:
        row["label"] = label
    row.setdefault("label", channel_id)
    cmap[channel_id] = row
    cfg["channel_map"] = cmap
    save_ota_config(cfg, root)
    # Also write a recipe stub for scheduler channel apply path consistency.
    from .channel import save_recipe

    save_recipe(
        channel_id,
        {
            "source_kind": "ota_antenna",
            "label": row.get("label") or channel_id,
            "tune": row,
            "steps": [{"action": "note", "text": "OTA tune handled by ota.tune_channel"}],
        },
        root=root,
    )
    return row


def tune_channel(channel_id: str, *, tuner_id: str = "default", root: Path | None = None) -> dict[str, Any]:
    cfg = get_ota_config(root)
    cmap = cfg.get("channel_map") or {}
    if channel_id not in cmap:
        return {
            "ok": False,
            "channel_id": channel_id,
            "error": f"channel {channel_id!r} missing from ota channel_map; run ota upsert-channel",
        }
    tuner = resolve_tuner(tuner_id, root)
    video = str(tuner.get("dshow_video") or tuner.get("ffmpeg_video_device") or "")
    if not video:
        return {
            "ok": False,
            "channel_id": channel_id,
            "error": "tuner has no dshow_video configured",
            "tuner_id": tuner_id,
        }
    # Many USB tuners expose a single capture device already tuned by vendor software.
    # We record the intended virtual channel in meta; vendor tune APIs vary.
    return {
        "ok": True,
        "channel_id": channel_id,
        "tuner_id": tuner_id,
        "map": cmap[channel_id],
        "note": "Ensure the tuner is on this virtual channel (vendor app or prior tune).",
        "tuned_utc": _now(),
    }


def capture_ota_session(
    *,
    tuner_id: str,
    channel_id: str,
    seconds: float,
    out_dir: Path,
    media: str = "av",
    chunk_minutes: float = 15.0,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Capture from DirectShow tuner devices into chunked video/audio files."""
    from .session_capture import CHUNK_MINUTES, _record_audio_loopback

    tuner = resolve_tuner(tuner_id)
    warnings: list[str] = []
    chunks: list[dict[str, Any]] = []
    ff = ffmpeg_path()
    video_dev = str(tuner.get("dshow_video") or tuner.get("ffmpeg_video_device") or "")
    audio_dev = str(tuner.get("dshow_audio") or tuner.get("ffmpeg_audio_device") or "")
    loopback = str(tuner.get("loopback_device") or tuner.get("audio_device") or "")

    if media == "audio":
        if not loopback and not audio_dev:
            raise RuntimeError("OTA audio capture needs audio_device/loopback_device or dshow_audio")
        if loopback:
            chunks = _record_audio_loopback(
                device_substr=loopback,
                seconds=seconds,
                out_dir=out_dir,
                chunk_minutes=chunk_minutes,
            )
            return chunks, warnings
        # fall through to ffmpeg audio-only from dshow

    if not ff:
        raise RuntimeError("ffmpeg required for OTA AV capture")
    if not video_dev and media == "av":
        raise RuntimeError("OTA AV capture needs dshow_video configured on the tuner")

    chunk_seconds = (chunk_minutes or CHUNK_MINUTES) * 60.0
    n_chunks = max(1, int((seconds + chunk_seconds - 1) // chunk_seconds))
    import time

    t0 = time.perf_counter()
    for i in range(n_chunks):
        remaining = seconds - (time.perf_counter() - t0)
        if remaining <= 0.5:
            break
        this_len = min(chunk_seconds, remaining)
        video_name = f"video_{i:04d}.mp4"
        audio_name = f"audio_{i:04d}.wav"
        video_path = out_dir / video_name
        audio_path = out_dir / audio_name
        cmd = [ff, "-y", "-hide_banner", "-loglevel", "error"]
        if media == "av" and video_dev:
            cmd.extend(["-f", "dshow", "-i", f"video={video_dev}" + (f":audio={audio_dev}" if audio_dev else "")])
        elif audio_dev:
            cmd.extend(["-f", "dshow", "-i", f"audio={audio_dev}"])
        else:
            raise RuntimeError("no OTA capture devices configured")

        if media == "av":
            # Write mp4; extract wav in a second pass if needed.
            cmd.extend(
                [
                    "-t",
                    str(this_len),
                    "-c:v",
                    "libx264",
                    "-preset",
                    "veryfast",
                    "-crf",
                    "23",
                    "-c:a",
                    "aac",
                    str(video_path),
                ]
            )
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=this_len + 120)
            if proc.returncode != 0 or not video_path.is_file():
                warnings.append(f"ota_video_{i}: {(proc.stderr or '')[-500:]}")
                chunks.append({"index": i, "video": None, "audio": None})
                continue
            # Extract PCM wav for archival / ingest.
            ext = subprocess.run(
                [
                    ff,
                    "-y",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-i",
                    str(video_path),
                    "-ac",
                    "2",
                    "-ar",
                    "48000",
                    "-sample_fmt",
                    "s16",
                    str(audio_path),
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if ext.returncode != 0 or not audio_path.is_file():
                warnings.append(f"ota_audio_extract_{i}: {(ext.stderr or '')[-500:]}")
                chunks.append({"index": i, "video": video_name, "audio": None})
            else:
                chunks.append(
                    {
                        "index": i,
                        "video": video_name,
                        "audio": audio_name,
                        "duration_sec": this_len,
                    }
                )
        else:
            cmd.extend(
                [
                    "-t",
                    str(this_len),
                    "-ac",
                    "2",
                    "-ar",
                    "48000",
                    "-sample_fmt",
                    "s16",
                    str(audio_path),
                ]
            )
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=this_len + 120)
            if proc.returncode != 0 or not audio_path.is_file():
                warnings.append(f"ota_audio_{i}: {(proc.stderr or '')[-500:]}")
                chunks.append({"index": i, "audio": None})
            else:
                chunks.append({"index": i, "audio": audio_name, "duration_sec": this_len})

    return chunks, warnings


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="OTA antenna / tuner helpers")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor")
    sub.add_parser("scan")
    u = sub.add_parser("upsert-channel")
    u.add_argument("--channel", required=True)
    u.add_argument("--major", type=int)
    u.add_argument("--minor", type=int)
    u.add_argument("--label")
    t = sub.add_parser("tune")
    t.add_argument("--channel", required=True)
    t.add_argument("--tuner", default="default")
    s = sub.add_parser("set-tuner")
    s.add_argument("--tuner", default="default")
    s.add_argument("--dshow-video")
    s.add_argument("--dshow-audio")
    s.add_argument("--loopback-device")
    s.add_argument("--label")

    args = p.parse_args(argv)
    if args.cmd == "doctor":
        report = doctor()
        print(json.dumps(report, indent=2))
        return 0 if report.get("ok") else 1
    if args.cmd == "scan":
        print(json.dumps(scan(), indent=2))
        return 0
    if args.cmd == "upsert-channel":
        row = upsert_channel(args.channel, major=args.major, minor=args.minor, label=args.label)
        print(json.dumps({"ok": True, "channel": row}, indent=2))
        return 0
    if args.cmd == "tune":
        print(json.dumps(tune_channel(args.channel, tuner_id=args.tuner), indent=2))
        return 0
    if args.cmd == "set-tuner":
        cfg = get_ota_config()
        tuners = dict(cfg.get("tuners") or {})
        row = dict(tuners.get(args.tuner) or {})
        if args.dshow_video:
            row["dshow_video"] = args.dshow_video
        if args.dshow_audio:
            row["dshow_audio"] = args.dshow_audio
        if args.loopback_device:
            row["loopback_device"] = args.loopback_device
        if args.label:
            row["label"] = args.label
        tuners[args.tuner] = row
        cfg["tuners"] = tuners
        save_ota_config(cfg)
        print(json.dumps({"ok": True, "tuner": {"id": args.tuner, **row}}, indent=2))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
