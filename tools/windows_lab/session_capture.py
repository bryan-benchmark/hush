"""Chunked Streamers / OTA capture sessions (AV default, audio-only switch).

Default media `av` keeps full archival WAV plus sparse stills for labeling
context. Pass `av_full` to retain video_*.mp4. Contested edges use
`python -m tools.windows_lab archive edge-clip`.
"""

from __future__ import annotations

import json
import os
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
from .config import DEFAULT_STILL_INTERVAL_SEC, MEDIA_MODES, SOURCE_KINDS, ensure_data_layout
from .ingest import ingest
from .instances import (
    find_window_title,
    ffmpeg_path,
    get_instance,
    launch_bluestacks,
    wait_for_adb,
)
from .locks import acquire, release
from .streamers_lag import attach_lag_to_meta, wait_for_window
from .visual_archive import (
    record_stills_adb,
    record_stills_gdigrab,
    write_visual_archive_meta,
)

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


def _record_audio(
    *,
    device_substr: str | None = None,
    process_pid: int | None = None,
    seconds: float,
    out_dir: Path,
    chunk_minutes: float = CHUNK_MINUTES,
    stop_event: threading.Event | None = None,
) -> list[dict[str, Any]]:
    """Prefer process-PID loopback (no cable); fall back to device WASAPI loopback."""
    if process_pid:
        from .process_loopback import record_process_loopback_chunks

        return record_process_loopback_chunks(
            pid=int(process_pid),
            seconds=seconds,
            out_dir=out_dir,
            chunk_minutes=chunk_minutes,
            stop_event=stop_event,
        )
    if not device_substr:
        raise ValueError("device_substr or process_pid required for audio capture")
    return _record_audio_loopback(
        device_substr=device_substr,
        seconds=seconds,
        out_dir=out_dir,
        chunk_minutes=chunk_minutes,
        stop_event=stop_event,
    )


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


def _merge_audio_chunks(
    visual_chunks: list[dict[str, Any]],
    audio_chunks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_idx = {c["index"]: c for c in visual_chunks}
    for a in audio_chunks:
        row = by_idx.setdefault(a["index"], {"index": a["index"]})
        row["audio"] = a.get("audio")
        row["frames"] = a.get("frames")
        row["duration_sec"] = a.get("duration_sec")
    return [by_idx[k] for k in sorted(by_idx)]


def _record_av_with_audio(
    *,
    window_title: str,
    loopback_device: str | None = None,
    process_pid: int | None = None,
    seconds: float,
    out_dir: Path,
    chunk_minutes: float = CHUNK_MINUTES,
    dshow_audio: str | None = None,
    stop_event: threading.Event | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Record full video via ffmpeg gdigrab and archival WAV via process/device loopback."""
    stop_event = stop_event or threading.Event()
    warnings: list[str] = []
    chunks: list[dict[str, Any]] = []
    chunk_seconds = chunk_minutes * 60.0
    n_chunks = max(1, int((seconds + chunk_seconds - 1) // chunk_seconds))
    audio_q: queue.Queue = queue.Queue()

    def audio_worker() -> None:
        try:
            rows = _record_audio(
                device_substr=loopback_device,
                process_pid=process_pid,
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

    return _merge_audio_chunks(chunks, audio_chunks), warnings


def _record_stills_with_audio(
    *,
    window_title: str,
    loopback_device: str | None = None,
    process_pid: int | None = None,
    seconds: float,
    out_dir: Path,
    chunk_minutes: float = CHUNK_MINUTES,
    still_interval_sec: float = DEFAULT_STILL_INTERVAL_SEC,
    stop_event: threading.Event | None = None,
    window_pattern: str | None = None,
    instance: dict[str, Any] | None = None,
    stills_source: str = "adb",
) -> tuple[list[dict[str, Any]], list[str], int]:
    """Record sparse stills + archival WAV. No full video library.

    Default stills_source=adb reads the Android framebuffer (works minimized,
    covered, or resized). gdigrab is the fallback when ADB fails.
    Audio prefers process-PID loopback when process_pid is set (no cable).
    """
    stop_event = stop_event or threading.Event()
    warnings: list[str] = []
    chunks: list[dict[str, Any]] = []
    chunk_seconds = chunk_minutes * 60.0
    n_chunks = max(1, int((seconds + chunk_seconds - 1) // chunk_seconds))
    audio_q: queue.Queue = queue.Queue()
    still_total = 0
    pattern = window_pattern or window_title
    title = window_title
    use_adb = stills_source == "adb" and instance is not None

    def audio_worker() -> None:
        try:
            rows = _record_audio(
                device_substr=loopback_device,
                process_pid=process_pid,
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
        t0_sec = i * chunk_seconds
        result: dict[str, Any] | None = None
        if use_adb:
            result = record_stills_adb(
                instance=instance,  # type: ignore[arg-type]
                seconds=this_len,
                session_dir=out_dir,
                interval_sec=still_interval_sec,
                t0_sec=t0_sec,
                chunk_index=i,
            )
            if not result.get("ok"):
                warnings.append(
                    f"stills_chunk_{i}_adb: {result.get('error') or 'adb stills failed'}; "
                    "falling back to gdigrab"
                )
                use_adb = False
                result = None
        if result is None:
            resolved, lag_notes = wait_for_window(pattern)
            warnings.extend(lag_notes)
            if not resolved:
                warnings.append(f"stills_chunk_{i}: window lost (Streamers lag)")
                chunks.append({"index": i, "stills": 0})
                continue
            title = resolved
            result = record_stills_gdigrab(
                window_title=title,
                seconds=this_len,
                session_dir=out_dir,
                interval_sec=still_interval_sec,
                t0_sec=t0_sec,
                chunk_index=i,
            )
        if not result.get("ok"):
            warnings.append(f"stills_chunk_{i}: {result.get('error') or 'stills capture failed'}")
            chunks.append({"index": i, "stills": 0})
        else:
            count = int(result.get("still_count") or 0)
            still_total += count
            chunks.append(
                {
                    "index": i,
                    "stills": count,
                    "still_interval_sec": still_interval_sec,
                    "stills_source": result.get("source") or "gdigrab",
                    "stills_mode": result.get("mode"),
                }
            )

    stop_event.set()
    th.join(timeout=30)
    status, payload = audio_q.get() if not audio_q.empty() else ("err", "audio thread silent")
    if status != "ok":
        warnings.append(f"audio: {payload}")
        audio_chunks: list[dict[str, Any]] = []
    else:
        audio_chunks = payload  # type: ignore[assignment]

    return _merge_audio_chunks(chunks, audio_chunks), warnings, still_total


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
    still_interval_sec: float = DEFAULT_STILL_INTERVAL_SEC,
) -> dict[str, Any]:
    if source_kind not in SOURCE_KINDS:
        raise ValueError(f"source_kind must be one of {sorted(SOURCE_KINDS)}")
    if media not in MEDIA_MODES:
        raise ValueError(f"media must be one of {sorted(MEDIA_MODES)}")
    if still_interval_sec <= 0:
        raise ValueError("still_interval_sec must be > 0")
    # Labeling archive is locked at ≤1s between stills (1 fps or denser).
    if media == "av" and still_interval_sec > 1.0:
        raise ValueError(
            "still_interval_sec must be ≤ 1.0 for media=av (1 frame per second labeling standard)"
        )

    ensure_data_layout(root)
    seconds = float(minutes) * 60.0

    process_pid: int | None = None
    if source_kind == "streamers":
        if not instance_id:
            raise ValueError("instance_id required for streamers")
        resource_id = instance_id
        instance = get_instance(instance_id, root)
        loopback = str(instance.get("loopback_device") or "")
        window_pat = str(instance.get("window_title") or "BlueStacks")
        # Prefer process loopback (no cable). Device loopback remains fallback.
        audio_mode = str(instance.get("audio_capture") or "process").lower()
        if audio_mode in ("process", "process_loopback", "pid", "auto"):
            try:
                from .process_loopback import resolve_hd_player_pid

                hit = resolve_hd_player_pid(window_title=window_pat, instance_id=instance_id)
                process_pid = int(hit["pid"])
            except Exception as e:  # noqa: BLE001
                if not loopback:
                    raise RuntimeError(
                        f"instance {instance_id}: process loopback resolve failed and no loopback_device: {e}"
                    ) from e
        elif not loopback:
            raise RuntimeError(f"instance {instance_id} missing loopback_device (audio_capture={audio_mode})")
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
    got, existing = acquire(
        source_kind,
        resource_id,
        session_id=session_id,
        job_id=job_id,
        holder_pid=os.getpid(),
        allow_upgrade_job_id=str(job_id) if job_id else None,
        root=root,
    )
    if not got:
        try:
            from .farm_ops import emit

            emit(
                "claimed",
                detail="resource_busy",
                job_id=job_id,
                session_id=session_id,
                instance_id=str(resource_id),
                ok=False,
                extra={"lock": existing},
                root=root,
            )
        except Exception:  # noqa: BLE001
            pass
        return {
            "ok": False,
            "error": "resource busy",
            "lock": existing,
            "session_id": session_id,
        }

    try:
        from .farm_ops import emit

        emit(
            "claimed",
            detail=f"{source_kind}:{channel_id}",
            job_id=job_id,
            session_id=session_id,
            instance_id=str(resource_id),
            ok=True,
            root=root,
        )
    except Exception:  # noqa: BLE001
        pass

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
        "still_interval_sec": still_interval_sec if media == "av" else None,
        "capture_utc_start": _now(),
        "label_status": "unlabeled",
        "credentials": None,
        "stream_urls": None,
        "chunks": [],
        "warnings": [],
        "job_id": job_id,
        "visual_archive": None,
        "audio_capture": "process_loopback" if process_pid else "device_loopback",
        "audio_pid": process_pid,
    }
    # Early meta so mid-take chunk_ok events can resolve job_id/session.
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    try:
        if dry_run:
            meta["dry_run"] = True
            if media == "av":
                meta["visual_archive"] = {
                    "mode": "stills",
                    "still_interval_sec": still_interval_sec,
                    "stills_dir": "stills",
                    "edge_clips_dir": "edge_clips",
                    "planned": True,
                }
            elif media == "av_full":
                meta["visual_archive"] = {"mode": "full_video", "planned": True}
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
            try:
                from .farm_ops import emit

                emit(
                    "opened",
                    detail="channel_apply",
                    job_id=job_id,
                    session_id=session_id,
                    instance_id=str(resource_id),
                    ok=bool(channel_result.get("ok")),
                    root=root,
                )
            except Exception:  # noqa: BLE001
                pass
        elif source_kind == "streamers":
            launch_bluestacks(instance, launch_app=True)  # type: ignore[arg-type]
            wait_for_adb(instance, seconds=60)  # type: ignore[arg-type]
            try:
                from .farm_ops import emit

                emit(
                    "opened",
                    detail="launch_only",
                    job_id=job_id,
                    session_id=session_id,
                    instance_id=str(resource_id),
                    ok=True,
                    root=root,
                )
            except Exception:  # noqa: BLE001
                pass
        elif source_kind == "ota_antenna" and apply_channel:
            from .ota import tune_channel

            tune = tune_channel(channel_id, tuner_id=resource_id, root=root)
            meta["channel_apply"] = tune
            if not tune.get("ok"):
                meta["warnings"].append("ota_tune_failed")

        warnings: list[str] = []
        chunks: list[dict[str, Any]] = []
        still_count = 0
        try:
            from .farm_ops import emit

            emit(
                "capturing",
                detail=str(media),
                job_id=job_id,
                session_id=session_id,
                instance_id=str(resource_id),
                pid=process_pid,
                ok=True,
                root=root,
            )
        except Exception:  # noqa: BLE001
            pass

        if source_kind == "ota_antenna":
            from .ota import capture_ota_session

            chunks, warnings = capture_ota_session(
                tuner_id=resource_id,
                channel_id=channel_id,
                seconds=seconds,
                out_dir=out_dir,
                media=media,
                still_interval_sec=still_interval_sec,
            )
            if media == "av":
                still_count = sum(int(c.get("stills") or 0) for c in chunks)
        elif media == "audio":
            chunks = _record_audio(
                device_substr=loopback or None,
                process_pid=process_pid,
                seconds=seconds,
                out_dir=out_dir,
            )
        elif media == "av_full":
            title = find_window_title(window_pat) or window_pat
            meta["window_title_resolved"] = title
            # Give Streamers a moment to paint video after channel apply.
            time.sleep(3.0)
            chunks, warnings = _record_av_with_audio(
                window_title=title,
                loopback_device=loopback or None,
                process_pid=process_pid,
                seconds=seconds,
                out_dir=out_dir,
                dshow_audio=dshow_audio,
            )
        else:
            # Default av: ADB framebuffer stills + full audio (no video library).
            # ADB ignores Windows window size / position / z-order / minimize.
            title = find_window_title(window_pat) or window_pat
            meta["window_title_resolved"] = title
            meta["stills_source"] = "adb"
            time.sleep(3.0)
            chunks, warnings, still_count = _record_stills_with_audio(
                window_title=title,
                loopback_device=loopback or None,
                process_pid=process_pid,
                seconds=seconds,
                out_dir=out_dir,
                still_interval_sec=still_interval_sec,
                window_pattern=window_pat,
                instance=instance if source_kind == "streamers" else None,
                stills_source="adb",
            )

        meta["chunks"] = chunks
        meta["warnings"].extend(warnings)
        if media == "av":
            meta["visual_archive"] = write_visual_archive_meta(
                out_dir,
                mode="stills",
                interval_sec=still_interval_sec,
                still_count=still_count,
            )
        elif media == "av_full":
            meta["visual_archive"] = {
                "mode": "full_video",
                "stills_dir": "stills",
                "edge_clips_dir": "edge_clips",
                "note": "Distill later with: python -m tools.windows_lab archive distill --session-dir <dir>",
            }
        meta["capture_utc_end"] = _now()
        if source_kind == "streamers":
            attach_lag_to_meta(meta, still_count=still_count if media == "av" else None)
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
                "visual_archive_mode": (meta.get("visual_archive") or {}).get("mode"),
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

        try:
            from .farm_ops import emit

            emit(
                "closed",
                detail="session_complete",
                job_id=job_id,
                session_id=session_id,
                instance_id=str(resource_id),
                stills=still_count if media == "av" else None,
                audio_s=sum(float(c.get("duration_sec") or 0) for c in chunks) or None,
                ok=True,
                extra={"chunk_count": len(chunks)},
                root=root,
            )
        except Exception:  # noqa: BLE001
            pass

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
    p.add_argument(
        "--media",
        default="av",
        choices=sorted(MEDIA_MODES),
        help="av=audio+stills (default), av_full=audio+video files, audio=WAV only",
    )
    p.add_argument(
        "--still-interval",
        type=float,
        default=DEFAULT_STILL_INTERVAL_SEC,
        help="Seconds between labeling stills when media=av (default 1; must be ≤1)",
    )
    p.add_argument("--instance")
    p.add_argument("--tuner")
    p.add_argument("--rights-status", default="authorized")
    p.add_argument("--no-channel-apply", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--dshow-audio", help="Optional DirectShow audio device name for ffmpeg mux")
    p.add_argument("--job-id", help="Schedule job id stamped into meta/lock")
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
            still_interval_sec=args.still_interval,
            job_id=args.job_id,
        )
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": str(e)}))
        return 1
    print(json.dumps(result, indent=2, default=str))
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
