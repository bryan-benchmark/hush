"""Push farm help clips to GCS for ohush.co/farm; pull cloud judgments back.

Requires: gsutil on PATH, ADC (gcloud auth application-default login).

  python -m tools.windows_lab.farm_cloud_sync
  python -m tools.windows_lab.farm_cloud_sync --limit 40
  python -m tools.windows_lab.farm_cloud_sync --pull-only
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from .config import data_root
from .coverage_farm import farm_label_dir

BUCKET = os.environ.get("FARM_BUCKET") or os.environ.get("CROWD_BUCKET") or "hushdev-748439071367-crowd"
SITE = (os.environ.get("OHUSH_FARM_SITE") or "https://ohush.co").rstrip("/")
QUEUE_OBJECT = "farm/queue.json"


def _gsutil(*args: str) -> None:
    exe = shutil.which("gsutil") or shutil.which("gsutil.cmd")
    if not exe:
        raise FileNotFoundError("gsutil not on PATH")
    cmd = [exe, "-q", *args]
    # Windows Cloud SDK ships gsutil.cmd — needs shell for .cmd resolution.
    subprocess.run(cmd, check=True, shell=os.name == "nt")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _judgments(root: Path | None = None) -> dict[str, Any]:
    path = farm_label_dir(root) / "take_judgments.json"
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_judgments(notes: dict[str, Any], root: Path | None = None) -> None:
    path = farm_label_dir(root) / "take_judgments.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(notes, indent=2) + "\n", encoding="utf-8")


def _slice_wav(src: Path, dest: Path, t0: float, t1: float) -> None:
    with wave.open(str(src), "rb") as fh:
        rate = fh.getframerate()
        channels = fh.getnchannels()
        width = fh.getsampwidth()
        start = max(0, int(t0 * rate))
        n = max(1, int((t1 - t0) * rate))
        fh.setpos(start)
        frames = fh.readframes(n)
    with wave.open(str(dest), "wb") as out:
        out.setnchannels(channels)
        out.setsampwidth(width)
        out.setframerate(rate)
        out.writeframes(frames)


def _pick_stills(session_dir: Path, t0: float, t1: float, limit: int = 5) -> list[tuple[float, Path]]:
    stills_dir = session_dir / "stills"
    found: list[tuple[float, Path]] = []
    if stills_dir.is_dir():
        for path in stills_dir.iterdir():
            m = path.name
            if not m.lower().endswith((".jpg", ".jpeg")):
                continue
            # still_t00020.0.jpg
            try:
                num = m.split("_t", 1)[1]
                num = num.rsplit(".", 1)[0]
                t = float(num)
            except (IndexError, ValueError):
                continue
            if t0 - 0.05 <= t <= t1 + 0.05:
                found.append((t - t0, path))
    found.sort(key=lambda row: row[0])
    if not found:
        return []
    if len(found) <= limit:
        return found
    # evenly sample
    step = (len(found) - 1) / (limit - 1)
    idxs = sorted({int(round(i * step)) for i in range(limit)})
    return [found[i] for i in idxs]


def build_cloud_items(*, root: Path | None = None, limit: int = 80) -> list[dict[str, Any]]:
    root = root or data_root()
    label_dir = farm_label_dir(root)
    judged = {
        k
        for k, v in _judgments(root).items()
        if isinstance(v, dict) and (v.get("regions") or [])
    }
    keys = {str(r.get("clip")): r for r in _read_jsonl(label_dir / "key.jsonl") if r.get("clip")}
    queue = _read_jsonl(label_dir / "queue.jsonl")
    items: list[dict[str, Any]] = []
    for row in queue:
        clip = str(row.get("clip") or "")
        if not clip or clip in judged:
            continue
        key = keys.get(clip) or {}
        ask = str(row.get("ask") or key.get("ask") or "")
        if ask == "optional_confirm" or ask == "locked" or key.get("gold"):
            continue
        session_dir = Path(str(row.get("session_dir") or ""))
        wav = session_dir / str(row.get("audio_rel") or "audio.wav")
        if not wav.is_file():
            continue
        t0 = float(row.get("t0") or 0)
        t1 = float(row.get("t1") or t0 + 12)
        if t1 <= t0:
            continue
        help_ask = ask in {"needs_human", "review"} or str(row.get("source") or "") == "gold_candidate"
        items.append(
            {
                "id": clip,
                "channel": str(row.get("channel") or row.get("session") or "channel"),
                "duration_s": round(t1 - t0, 3),
                "caption": str(row.get("caption") or row.get("why") or key.get("why") or "")[:200],
                "why": str(row.get("why") or key.get("why") or "")[:240] or None,
                "ask": ask or None,
                "help": help_ask,
                "priority": int(row.get("priority") or (10 if ask == "needs_human" else 20 if ask == "review" else 40)),
                "source": str(row.get("source") or "queue"),
                "expect_bucket": row.get("expect_bucket") or None,
                "session_dir": str(session_dir),
                "t0": t0,
                "t1": t1,
                "wav": str(wav),
            }
        )
    items.sort(key=lambda r: (0 if r.get("help") else 1, int(r.get("priority") or 99), r["id"]))
    return items[:limit]


def push_clips(items: list[dict[str, Any]], *, work: Path) -> list[dict[str, Any]]:
    cloud: list[dict[str, Any]] = []
    for row in items:
        clip_id = row["id"]
        safe = clip_id.replace(":", "_").replace("/", "_")
        local_wav = work / f"{safe}.wav"
        _slice_wav(Path(row["wav"]), local_wav, float(row["t0"]), float(row["t1"]))
        audio_object = f"farm/clips/{safe}.wav"
        _gsutil("cp", str(local_wav), f"gs://{BUCKET}/{audio_object}")

        frames: list[dict[str, Any]] = []
        stills = _pick_stills(Path(row["session_dir"]), float(row["t0"]), float(row["t1"]))
        for i, (t_s, path) in enumerate(stills):
            object_name = f"farm/clips/{safe}/still_{i}.jpg"
            _gsutil("cp", str(path), f"gs://{BUCKET}/{object_name}")
            frames.append({"t_s": round(float(t_s), 2), "object": object_name})

        cloud.append(
            {
                "id": clip_id,
                "channel": row["channel"],
                "duration_s": row["duration_s"],
                "caption": row.get("caption") or "",
                "why": row.get("why"),
                "ask": row.get("ask"),
                "help": bool(row.get("help")),
                "priority": row.get("priority") or 40,
                "source": row.get("source") or "queue",
                "expect_bucket": row.get("expect_bucket"),
                "audio_object": audio_object,
                "frames": frames,
                "whole_clip": True,
            }
        )
        print(f"uploaded {clip_id} frames={len(frames)}", flush=True)
    return cloud


def write_queue_object(cloud_items: list[dict[str, Any]], *, work: Path) -> None:
    payload = {"items": cloud_items, "updated_utc": __import__("datetime").datetime.now(
        __import__("datetime").timezone.utc
    ).isoformat()}
    local = work / "queue.json"
    local.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    _gsutil("cp", str(local), f"gs://{BUCKET}/{QUEUE_OBJECT}")


def pull_judgments(*, root: Path | None = None, code: str | None = None) -> dict[str, Any]:
    """Pull saved labels from ohush.co into local take_judgments.json."""
    code = (code or os.environ.get("OHUSH_FARM_CODE") or os.environ.get("OHUSH_PHONE_CODE") or "").strip()
    if not code:
        return {"ok": False, "error": "set OHUSH_FARM_CODE or OHUSH_PHONE_CODE to pull"}

    # Cookie session via enter + GET
    enter_req = Request(
        f"{SITE}/api/farm/enter",
        data=json.dumps({"code": code}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(enter_req, timeout=30) as res:
        cookie = res.headers.get("Set-Cookie") or ""
        body = res.read()
        if res.status >= 400:
            return {"ok": False, "error": body.decode("utf-8", "replace")}
    # crude cookie parse
    token = ""
    for part in cookie.split(";"):
        if part.strip().startswith("ohush_farm="):
            token = part.strip().split("=", 1)[1]
            break
    if not token:
        return {"ok": False, "error": "no farm cookie from site (deploy password secret?)"}

    get_req = Request(f"{SITE}/api/farm-takes", headers={"Cookie": f"ohush_farm={token}"}, method="GET")
    with urlopen(get_req, timeout=60) as res:
        data = json.loads(res.read().decode("utf-8"))
    saved = data.get("saved") or []
    notes = _judgments(root)
    merged = 0
    for row in saved:
        if not isinstance(row, dict) or not row.get("id"):
            continue
        if not (row.get("regions") or []):
            continue
        notes[str(row["id"])] = row
        merged += 1
    _write_judgments(notes, root)
    return {"ok": True, "merged": merged, "site": SITE}


def sync(*, root: Path | None = None, limit: int = 80, pull: bool = True, push: bool = True) -> dict[str, Any]:
    root = root or data_root()
    out: dict[str, Any] = {"bucket": BUCKET, "site": SITE}
    if push:
        items = build_cloud_items(root=root, limit=limit)
        with tempfile.TemporaryDirectory(prefix="ohush-farm-") as tmp:
            work = Path(tmp)
            cloud = push_clips(items, work=work)
            write_queue_object(cloud, work=work)
            out["pushed"] = len(cloud)
            out["queue_object"] = f"gs://{BUCKET}/{QUEUE_OBJECT}"
    if pull:
        out["pull"] = pull_judgments(root=root)
    return out


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="Sync farm help clips to ohush.co GCS")
    p.add_argument("--limit", type=int, default=80)
    p.add_argument("--pull-only", action="store_true")
    p.add_argument("--push-only", action="store_true")
    args = p.parse_args(argv)
    if not shutil.which("gsutil"):
        raise SystemExit("gsutil not on PATH — install Google Cloud SDK")
    out = sync(
        limit=args.limit,
        pull=not args.push_only,
        push=not args.pull_only,
    )
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
