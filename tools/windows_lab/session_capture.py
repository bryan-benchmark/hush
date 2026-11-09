"""Chunked Streamers / OTA capture sessions (AV default, audio-only switch)."""

from __future__ import annotations

import json
import queue
import re
import subprocess
import threading
import time
import wave
from array import array
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import NODE_ID, __version__
from .catalog import append_session
from .channel import apply_recipe
from .config import MEDIA_MODES, SOURCE_KINDS, ensure_data_layout
from .ingest import ingest
from .instances import (
    find_window_title,
    ffmpeg_path,
    get_instance,
    launch_bluestacks,
    wait_for_adb,
)
from .locks import acquire, release

try:
    import soundcard as sc
except ImportError:  # pragma: no cover
    sc = None


CHUNK_MINUTES = 15
RATE = 48000
CHANNELS = 2


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slug(text: str) -> str:
    text = text.strip().replace(" ", "_")
    return re.sub(r"[^A-Za-z0-9._-]+", "_", text)[:80] or "ch"


def _session_id(source_kind: str, channel_id: str, resource_id: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{source_kind}_{stamp}_{_slug(channel_id)}_{_slug(resource_id)}"


def _find_loopback_mic(name_substr: str):
    if sc is None:
        raise RuntimeError("soundcard is required for loopback capture")
    needle = name_substr.lower()
    # Prefer loopback microphones matching the device name.
    for mic in sc.all_microphones(include_loopback=True):
        if needle in mic.name.lower():
            return mic
    for mic in sc.all_microphones(include_loopback=True):
        if "loopback" in mic.name.lower() and needle.split()[0] in mic.name.lower():
            return mic
    names = [m.name for m in sc.all_microphones(include_loopback=True)]
    raise LookupError(f"no loopback mic matching {name_substr!r}: {names}")


def _write_wav(path: Path, pcm: bytes, *, rate: int = RATE, channels: int = CHANNELS) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)


def _record_audio_loopback(
    *,
    device_substr: str,
    seconds: float,
    out_dir: Path,
    chunk_minutes: float = CHUNK_MINUTES,
    stop_event: threading.Event | None = None,
) -> list[dict[str, Any]]:
    mic = _find_loopback_mic(device_substr)
    stop_event = stop_event or threading.Event()
    frames_per_chunk = int(chunk_minutes * 60 * RATE)
    chunks: list[dict[str, Any]] = []
    chunk_idx = 0
    collected = array("h")
    started = _now()
    t0 = time.perf_counter()
    target_frames = int(seconds * RATE)

    with mic.recorder(samplerate=RATE, channels=CHANNELS) as rec:
        while not stop_event.is_set():
            elapsed_frames = int((time.perf_counter() - t0) * RATE)
            if elapsed_frames >= target_frames:
                break
            block = rec.record(numframes=RATE // 2)  # 0.5 s
            # soundcard returns float32 [-1, 1]
            import numpy as np

            pcm = (np.asarray(block, dtype=np.float64) * 32767.0).clip(-32768, 32767).astype("<i2")
            collected.frombytes(pcm.tobytes())
            while len(collected) // CHANNELS >= frames_per_chunk:
                take = frames_per_chunk * CHANNELS
                piece = collected[:take].tobytes()
                del collected[:take]
                name = f"audio_{chunk_idx:04d}.wav"
                path = out_dir / name
                _write_wav(path, piece)
                chunks.append(
                    {
                        "index": chunk_idx,
                        "audio": name,
                        "frames": frames_per_chunk,
                        "duration_sec": chunk_minutes * 60,
                    }
                )
                chunk_idx += 1
            # cooperative stop
            if stop_event.is_set():
                break

    if collected:
        name = f"audio_{chunk_idx:04d}.wav"
        path = out_dir / name
        frames = len(collected) // CHANNELS
        _write_wav(path, collected.tobytes())
        chunks.append(
            {
                "index": chunk_idx,
                "audio": name,
                "frames": frames,
                "duration_sec": round(frames / RATE, 3),
            }
        )

    return chunks


def _ffmpeg_av_chunk(
    *,
    window_title: str,
    audio_device: str | None,
    outfile: Path,
    seconds: float,
) -> dict[str, Any]:
    ff = ffmpeg_path()
    if not ff:
        raise RuntimeError("ffmpeg not found on PATH")
    outfile.parent.mkdir(parents=True, exist_ok=True)
    # gdigrab + optional DirectShow audio. When audio_device is None, capture silent video
    # and rely on separate loopback WAV (more reliable on WASAPI loopback setups).
    cmd = [
        ff,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "gdigrab",
        "-framerate",
        "30",
        "-i",
        f"title={window_title}",
    ]
    if audio_device:
        cmd.extend(["-f", "dshow", "-i", f"audio={audio_device}"])
        cmd.extend(["-t", str(seconds), "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-c:a", "aac", str(outfile)])
    else:
        cmd.extend(
            [
                "-t",
                str(seconds),
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "23",
                str(outfile),
            ]
        )
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=seconds + 120)
    return {
        "cmd": cmd,
        "returncode": proc.returncode,
        "stderr": (proc.stderr or "").strip()[-2000:],
        "outfile": str(outfile),
        "ok": proc.returncode == 0 and outfile.is_file(),
    }


def _record_av_with_audio(
    *,
    window_title: str,
    loopback_device: str,
    seconds: float,
    out_dir: Path,
    chunk_minutes: float = CHUNK_MINUTES,
    dshow_audio: str | None = None,
    stop_event: threading.Event | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Record video via ffmpeg gdigrab and archival WAV via WASAPI loopback in parallel."""
    stop_event = stop_event or threading.Event()
    warnings: list[str] = []
    chunks: list[dict[str, Any]] = []
    chunk_seconds = chunk_minutes * 60.0
    n_chunks = max(1, int((seconds + chunk_seconds - 1) // chunk_seconds))
    audio_q: queue.Queue = queue.Queue()

    def audio_worker() -> None:
        try:
            rows = _record_audio_loopback(
                device_substr=loopback_device,
                seconds=seconds,
                out_dir=out_dir,
                chunk_minutes=chunk_minutes,
                stop_event=stop_event,
            )
            audio_q.put(("ok", rows))
        except Exception as e:  # noqa: BLE001
            audio_q.put(("err", str(e)))

    th = threading.Thread(target=audio_worker, daemon=True)
    th.start()

    t0 = time.perf_counter()
    for i in range(n_chunks):
        if stop_event.is_set():
            break
        remaining = seconds - (time.perf_counter() - t0)
        if remaining <= 0.5:
            break
        this_len = min(chunk_seconds, remaining)
        video_name = f"video_{i:04d}.mp4"
        video_path = out_dir / video_name
        result = _ffmpeg_av_chunk(
            window_title=window_title,
            audio_device=dshow_audio,
            outfile=video_path,
            seconds=this_len,
        )
        if not result["ok"]:
            warnings.append(f"video_chunk_{i}: {result.get('stderr') or 'ffmpeg failed'}")
        chunks.append({"index": i, "video": video_name if video_path.is_file() else None})

    stop_event.set()
    th.join(timeout=30)
    status, payload = audio_q.get() if not audio_q.empty() else ("err", "audio thread silent")
    if status != "ok":
        warnings.append(f"audio: {payload}")
        audio_chunks: list[dict[str, Any]] = []
    else:
        audio_chunks = payload  # type: ignore[assignment]

    # Merge audio filenames onto chunk rows by index.
    by_idx = {c["index"]: c for c in chunks}
    for a in audio_chunks:
        row = by_idx.setdefault(a["index"], {"index": a["index"]})
        row["audio"] = a.get("audio")
        row["frames"] = a.get("frames")
        row["duration_sec"] = a.get("duration_sec")
    merged = [by_idx[k] for k in sorted(by_idx)]
    return merged, warnings


def start_session(
    *,
    source_kind: str,
    channel_id: str,
    minutes: float,
    media: str = "av",
    instance_id: str | None = None,
    tuner_id: str | None = None,
    rights_status: str = "authorized",
    apply_channel: bool = True,
    dry_run: bool = False,
    root: Path | None = None,
    job_id: str | None = None,
    dshow_audio: str | None = None,
) -> dict[str, Any]:
    if source_kind not in SOURCE_KINDS:
        raise ValueError(f"source_kind must be one of {sorted(SOURCE_KINDS)}")
    if media not in MEDIA_MODES:
        raise ValueError(f"media must be one of {sorted(MEDIA_MODES)}")

    ensure_data_layout(root)
    seconds = float(minutes) * 60.0

    if source_kind == "streamers":
        if not instance_id:
            raise ValueError("instance_id required for streamers")
        resource_id = instance_id
        instance = get_instance(instance_id, root)
        loopback = str(instance.get("loopback_device") or "")
        if not loopback:
            raise RuntimeError(f"instance {instance_id} missing loopback_device")
        window_pat = str(instance.get("window_title") or "BlueStacks")
    else:
        from .ota import get_ota_config, resolve_tuner

        if not tuner_id:
            cfg = get_ota_config(root)
            tuner_id = str(cfg.get("default_tuner") or "default")
        resource_id = tuner_id
        tuner = resolve_tuner(tuner_id, root)
        loopback = str(tuner.get("audio_device") or tuner.get("loopback_device") or "")
        window_pat = str(tuner.get("window_title") or "")
        instance = None

    session_id = _session_id(source_kind, channel_id, resource_id)
    got, existing = acquire(source_kind, resource_id, session_id=session_id, job_id=job_id, root=root)
    if not got:
        return {
            "ok": False,
            "error": "resource busy",
            "lock": existing,
            "session_id": session_id,
        }

    out_dir = ensure_data_layout(root) / "authorized_sources" / session_id
    out_dir.mkdir(parents=True, exist_ok=True)
    meta: dict[str, Any] = {
        "session_id": session_id,
        "node_id": NODE_ID,
        "pipeline_version": __version__,
        "source_kind": source_kind,
        "source_type": "authorized_stream_reference",
        "channel_id": channel_id,
        "resource_id": resource_id,
        "instance_id": instance_id,
        "tuner_id": tuner_id,
        "media": media,
        "rights_status": rights_status,
        "requested_minutes": minutes,
        "chunk_minutes": CHUNK_MINUTES,
        "capture_utc_start": _now(),
        "label_status": "unlabeled",
        "credentials": None,
        "stream_urls": None,
        "chunks": [],
        "warnings": [],
        "job_id": job_id,
    }

    try:
        if dry_run:
            meta["dry_run"] = True
            meta["capture_utc_end"] = _now()
            (out_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
            return {"ok": True, "dry_run": True, "meta": meta, "session_dir": str(out_dir)}

        channel_result = None
        if source_kind == "streamers" and apply_channel:
            channel_result = apply_recipe(
                channel_id=channel_id,
                instance_id=instance_id,  # type: ignore[arg-type]
                root=root,
                dry_run=False,
                launch=True,
            )
            meta["channel_apply"] = {
                "ok": channel_result.get("ok"),
                "steps": len(channel_result.get("steps") or []),
            }
            if not channel_result.get("ok"):
                meta["warnings"].append("channel_apply_failed")
        elif source_kind == "streamers":
            launch_bluestacks(instance, launch_app=True)  # type: ignore[arg-type]
            wait_for_adb(instance, seconds=60)  # type: ignore[arg-type]
        elif source_kind == "ota_antenna" and apply_channel:
            from .ota import tune_channel

            tune = tune_channel(channel_id, tuner_id=resource_id, root=root)
            meta["channel_apply"] = tune
            if not tune.get("ok"):
                meta["warnings"].append("ota_tune_failed")

        warnings: list[str] = []
        chunks: list[dict[str, Any]] = []

        if source_kind == "ota_antenna":
            from .ota import capture_ota_session

            chunks, warnings = capture_ota_session(
                tuner_id=resource_id,
                channel_id=channel_id,
                seconds=seconds,
                out_dir=out_dir,
                media=media,
            )
        elif media == "audio":
            chunks = _record_audio_loopback(
                device_substr=loopback,
                seconds=seconds,
                out_dir=out_dir,
            )
        else:
            title = find_window_title(window_pat) or window_pat
            meta["window_title_resolved"] = title
            # Give Streamers a moment to paint video after channel apply.
            time.sleep(3.0)
            chunks, warnings = _record_av_with_audio(
                window_title=title,
                loopback_device=loopback,
                seconds=seconds,
                out_dir=out_dir,
                dshow_audio=dshow_audio,
            )

        meta["chunks"] = chunks
        meta["warnings"].extend(warnings)
        meta["capture_utc_end"] = _now()
        (out_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

        receipts = []
        for ch in chunks:
            audio_name = ch.get("audio")
            if not audio_name:
                continue
            wav = out_dir / audio_name
            if not wav.is_file():
                continue
            try:
                receipt = ingest(
                    wav,
                    source_label=f"{source_kind}:{channel_id}",
                    source_type="authorized_stream_reference",
                    rights_status=rights_status,
                    capture_utc_start=meta["capture_utc_start"],
                    copy_into_authorized=False,
                )
                receipts.append({"audio": audio_name, "receipt_path": receipt.get("receipt_path")})
            except Exception as e:  # noqa: BLE001
                meta["warnings"].append(f"ingest:{audio_name}:{e}")

        index_row = append_session(
            {
                "session_id": session_id,
                "source_kind": source_kind,
                "channel_id": channel_id,
                "resource_id": resource_id,
                "media": media,
                "session_dir": str(out_dir),
                "duration_min_requested": minutes,
                "chunk_count": len(chunks),
                "label_status": "unlabeled",
                "rights_status": rights_status,
                "capture_utc_start": meta["capture_utc_start"],
                "capture_utc_end": meta["capture_utc_end"],
                "job_id": job_id,
            },
            root=root,
        )
        meta["receipts"] = receipts
        meta["index"] = index_row
        (out_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

        return {
            "ok": True,
            "session_id": session_id,
            "session_dir": str(out_dir),
            "meta": meta,
            "chunk_count": len(chunks),
        }
    finally:
        release(source_kind, resource_id, root=root)


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="Start a capture session")
    p.add_argument(
        "--source",
        required=True,
        choices=sorted(SOURCE_KINDS | {"ota", "antenna"}),
        help="streamers | ota_antenna (aliases: ota, antenna)",
    )
    p.add_argument("--channel", required=True)
    p.add_argument("--minutes", type=float, required=True)
    p.add_argument("--media", default="av", choices=sorted(MEDIA_MODES))
    p.add_argument("--instance")
    p.add_argument("--tuner")
    p.add_argument("--rights-status", default="authorized")
    p.add_argument("--no-channel-apply", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--dshow-audio", help="Optional DirectShow audio device name for ffmpeg mux")
    args = p.parse_args(argv)

    source = {
        "ota": "ota_antenna",
        "antenna": "ota_antenna",
        "ota_antenna": "ota_antenna",
        "streamers": "streamers",
    }.get(args.source, args.source)
    try:
        result = start_session(
            source_kind=source,
            channel_id=args.channel,
            minutes=args.minutes,
            media=args.media,
            instance_id=args.instance,
            tuner_id=args.tuner,
            rights_status=args.rights_status,
            apply_channel=not args.no_channel_apply,
            dry_run=args.dry_run,
            dshow_audio=args.dshow_audio,
        )
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": str(e)}))
        return 1
    print(json.dumps(result, indent=2, default=str))
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
