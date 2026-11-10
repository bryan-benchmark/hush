"""Promote authorized_sources session captures into farm takes for labeling.

session start writes audio_000N.wav + stills under authorized_sources/.
farm prepare/draft expect work/capture/streamers/*/audio.wav (+ optional label_aid).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import ensure_data_layout
from .coverage_farm import _infer_slot, _prominence_rank, farm_label_dir, streamers_capture_root

# Coarser windows: 20 min → ~20 clips (was 100 @ 12s / 40 @ 30s). Fewer Ollama calls.
CLIP_SEC = 60.0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _take_name(session_id: str, channel_id: str) -> str:
    m = re.search(r"(\d{8}T\d{6})Z", session_id)
    stamp = (m.group(1)[:13] + "Z") if m else datetime.now(timezone.utc).strftime("%Y%m%dT%H%MZ")
    slug = re.sub(r"[^a-z0-9]+", "_", (channel_id or "streamers").lower()).strip("_")[:48]
    return f"{stamp}_{slug}"


def _concat_wavs(parts: list[Path], dest: Path) -> dict[str, Any]:
    if not parts:
        raise FileNotFoundError("no audio chunks")
    if len(parts) == 1:
        shutil.copy2(parts[0], dest)
        with wave.open(str(dest), "rb") as wf:
            frames = wf.getnframes()
            rate = wf.getframerate()
        return {"chunks": 1, "duration_s": frames / float(rate), "copied": True}

    params = None
    frames_data: list[bytes] = []
    total = 0
    rate = 48000
    for part in parts:
        with wave.open(str(part), "rb") as wf:
            p = wf.getparams()
            if params is None:
                params = p
                rate = p.framerate
            elif (p.nchannels, p.sampwidth, p.framerate) != (
                params.nchannels,
                params.sampwidth,
                params.framerate,
            ):
                raise RuntimeError(f"wav param mismatch: {part}")
            raw = wf.readframes(wf.getnframes())
            frames_data.append(raw)
            total += wf.getnframes()
    assert params is not None
    dest.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(dest), "wb") as out:
        out.setparams(params)
        for raw in frames_data:
            out.writeframes(raw)
    return {"chunks": len(parts), "duration_s": total / float(rate), "copied": False}


def _link_or_copy_stills(src: Path, dest: Path) -> dict[str, Any]:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        return {"ok": True, "mode": "exists", "count": len(list(dest.glob("still_t*.jpg")))}
    files = sorted(src.glob("still_t*.jpg")) if src.is_dir() else []
    if not files:
        dest.mkdir(parents=True, exist_ok=True)
        return {"ok": True, "mode": "empty", "count": 0}
    # Prefer directory junction on Windows (no duplicate GB).
    try:
        os.symlink(src, dest, target_is_directory=True)
        return {"ok": True, "mode": "symlink", "count": len(files)}
    except OSError:
        pass
    dest.mkdir(parents=True, exist_ok=True)
    linked = 0
    copied = 0
    for f in files:
        target = dest / f.name
        if target.exists():
            continue
        try:
            os.link(f, target)
            linked += 1
        except OSError:
            shutil.copy2(f, target)
            copied += 1
    return {"ok": True, "mode": "hardlink_or_copy", "linked": linked, "copied": copied, "count": len(files)}


def _stub_label_aid(
    *,
    session: str,
    channel_id: str,
    duration_s: float,
    recorded_utc: str,
    instance: str | None,
) -> dict[str, Any]:
    timeline = []
    t = 0.0
    while t < duration_s:
        timeline.append(
            {
                "t_s": round(t, 1),
                "kind": "program",
                "notes": f"imported session clip @ {t:.0f}s",
            }
        )
        t += CLIP_SEC
    return {
        "session": session,
        "recorded_utc": recorded_utc,
        "guide": {"name": channel_id, "group": None},
        "media": {"duration_s": duration_s, "audio": "audio.wav"},
        "instance": instance,
        "source": "authorized_session_import",
        "timeline": timeline,
    }


def _enqueue_take(take_dir: Path, root: Path | None = None) -> dict[str, Any]:
    """Append review clips for one take without wiping existing queue/key drafts."""
    from .farm_boundaries import segments_for_take

    aid = json.loads((take_dir / "label_aid.json").read_text(encoding="utf-8"))
    session = str(aid.get("session") or take_dir.name)
    guide = aid.get("guide") or {}
    slot = _infer_slot(guide.get("name") or session)

    label_dir = farm_label_dir(root)
    label_dir.mkdir(parents=True, exist_ok=True)
    queue_path = label_dir / "queue.jsonl"

    existing_clips: set[str] = set()
    if queue_path.is_file():
        for line in queue_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                existing_clips.add(json.loads(line)["clip"])

    # Boundary cuts (aid kind changes or still diffs) — not fixed stub clocks.
    # Key rows come from Ollama draft / gold-lock — do not trip human gate early.
    added = 0
    with queue_path.open("a", encoding="utf-8") as qfh:
        for seg in segments_for_take(take_dir):
            t0 = float(seg["t0"])
            t1 = float(seg["t1"])
            clip = f"{session}_{t0:.0f}_{t1:.0f}"
            if clip in existing_clips:
                continue
            qfh.write(
                json.dumps(
                    {
                        "clip": clip,
                        "session": session,
                        "session_dir": str(take_dir),
                        "audio_rel": "audio.wav",
                        "t0": t0,
                        "t1": t1,
                        "play_start": max(0.0, t0 - 0.5),
                        "duration": (t1 - t0) + 1.0,
                        "slot": slot,
                        "channel": guide.get("name"),
                        "why": f"{seg.get('source')} · imported · {guide.get('name')}",
                        "priority": _prominence_rank(
                            "main_linear" if "local" in str(guide.get("name") or "").lower() else slot
                        ),
                        "caption": str(seg.get("note") or seg.get("kind") or ""),
                        "rank": len(existing_clips) + added,
                        "source": seg.get("source") or "authorized_session_import",
                        "expect_bucket": seg.get("bucket"),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
            existing_clips.add(clip)
            added += 1
    return {"session": session, "clips_added": added, "queue_path": str(queue_path)}


def import_session(session_dir: Path, root: Path | None = None) -> dict[str, Any]:
    """Copy/link one authorized session into work/capture/streamers for labeling."""
    root = ensure_data_layout(root)
    session_dir = Path(session_dir)
    meta_path = session_dir / "meta.json"
    if not meta_path.is_file():
        return {"ok": False, "session_dir": str(session_dir), "error": "missing meta.json"}
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    session_id = str(meta.get("session_id") or session_dir.name)
    channel_id = str(meta.get("channel_id") or "UNKNOWN")
    take_name = _take_name(session_id, channel_id)
    take_dir = streamers_capture_root(root) / take_name
    marker = take_dir / "source_session.json"

    if marker.is_file() and (take_dir / "audio.wav").is_file():
        return {
            "ok": True,
            "skipped": True,
            "take_dir": str(take_dir),
            "session_id": session_id,
            "reason": "already_imported",
        }

    chunks = sorted(session_dir.glob("audio_*.wav"))
    if not chunks and (session_dir / "audio.wav").is_file():
        chunks = [session_dir / "audio.wav"]
    if not chunks:
        return {"ok": False, "session_dir": str(session_dir), "error": "no audio chunks"}

    take_dir.mkdir(parents=True, exist_ok=True)
    audio_info = _concat_wavs(chunks, take_dir / "audio.wav")
    stills_info = _link_or_copy_stills(session_dir / "stills", take_dir / "stills")

    duration_s = float(audio_info["duration_s"])
    recorded = str(meta.get("capture_utc_start") or _now())
    take = {
        "session": take_name,
        "source_session_id": session_id,
        "source_session_dir": str(session_dir),
        "recorded_utc": recorded,
        "channel_id": channel_id,
        "instance": meta.get("instance_id"),
        "duration_s": duration_s,
        "still_count": (meta.get("visual_archive") or {}).get("still_count"),
        "media": meta.get("media"),
        "rights_status": meta.get("rights_status"),
        "streamers_lag": meta.get("streamers_lag"),
        "imported_utc": _now(),
    }
    (take_dir / "take.json").write_text(json.dumps(take, indent=2), encoding="utf-8")
    aid = _stub_label_aid(
        session=take_name,
        channel_id=channel_id,
        duration_s=duration_s,
        recorded_utc=recorded,
        instance=meta.get("instance_id"),
    )
    (take_dir / "label_aid.json").write_text(json.dumps(aid, indent=2), encoding="utf-8")
    marker.write_text(
        json.dumps(
            {
                "session_id": session_id,
                "session_dir": str(session_dir),
                "imported_utc": _now(),
                "take_dir": str(take_dir),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    # Keep a copy of meta for lag / provenance.
    shutil.copy2(meta_path, take_dir / "session_meta.json")

    enqueue = _enqueue_take(take_dir, root=root)
    return {
        "ok": True,
        "skipped": False,
        "session_id": session_id,
        "take_dir": str(take_dir),
        "take_name": take_name,
        "audio": audio_info,
        "stills": stills_info,
        "enqueue": enqueue,
    }


def import_pending_sessions(root: Path | None = None) -> dict[str, Any]:
    """Import all streamers_* authorized sessions not yet in the farm take tree."""
    root = ensure_data_layout(root)
    src = root / "authorized_sources"
    results: list[dict[str, Any]] = []
    if not src.is_dir():
        return {"ok": True, "imported": 0, "skipped": 0, "results": []}
    for d in sorted(p for p in src.iterdir() if p.is_dir() and p.name.startswith("streamers_")):
        if not (d / "meta.json").is_file():
            continue
        results.append(import_session(d, root=root))
    imported = sum(1 for r in results if r.get("ok") and not r.get("skipped"))
    skipped = sum(1 for r in results if r.get("skipped"))
    failed = [r for r in results if not r.get("ok")]
    return {
        "ok": not failed,
        "imported": imported,
        "skipped": skipped,
        "failed": len(failed),
        "results": results,
        "checked_utc": _now(),
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="Import authorized sessions into farm takes")
    p.add_argument("--session-dir", action="append", default=[])
    args = p.parse_args(argv)
    if args.session_dir:
        out = {"results": [import_session(Path(s)) for s in args.session_dir]}
        out["ok"] = all(r.get("ok") for r in out["results"])
    else:
        out = import_pending_sessions()
    print(json.dumps(out, indent=2))
    return 0 if out.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
