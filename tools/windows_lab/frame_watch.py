"""Watch periodic stills/screencaps and decide: playing / stuck / down.

Two layers:
1. **Local heuristics** (PIL) — dark ratio, freeze between frames.
2. **Open vision model** (Ollama ``moondream`` by default) — describe the frame.
   No Cursor tokens.

Farm stills already land at 1 fps under ``session/stills/``. Score newest
frames; optionally trigger ``streamers_recover`` when bad.
"""

from __future__ import annotations

import base64
import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import ensure_data_layout

DEFAULT_VISION_MODEL = os.environ.get("OHUSH_VISION_MODEL", "moondream:latest")
OLLAMA_URL = os.environ.get("OHUSH_OLLAMA_URL", "http://127.0.0.1:11434")
VISION_ENABLED = os.environ.get("OHUSH_VISION", "1").strip().lower() not in {
    "0",
    "false",
    "no",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def log_path(root: Path | None = None) -> Path:
    return ensure_data_layout(root) / "indexes" / "frame_watch.jsonl"


def _append(row: dict[str, Any], root: Path | None = None) -> None:
    path = log_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, default=str) + "\n")


def _parse_vision_json(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    # Prefer first JSON object; moondream sometimes repeats keys / wraps in [].
    m = re.search(r"\{[^{}]*\}", text, re.S)
    if m:
        try:
            row = json.loads(m.group(0))
            if isinstance(row, dict) and row.get("state"):
                return row
        except json.JSONDecodeError:
            pass
    state_m = re.search(
        r'"state"\s*:\s*"(playing|guide|login|error|buffering|black|ads|other)"',
        text,
        re.I,
    )
    stuck_m = re.search(r'"stuck"\s*:\s*(true|false|"true"|"false")', text, re.I)
    detail_m = re.search(r'"detail"\s*:\s*"([^"]{1,120})"', text)
    stuck_raw = (stuck_m.group(1) if stuck_m else "false").strip('"').lower()
    return {
        "state": (state_m.group(1).lower() if state_m else "other"),
        "detail": (detail_m.group(1) if detail_m else text[:200]),
        "stuck": stuck_raw == "true",
    }


def _map_vision_state(state: Any, *, stuck: Any = None) -> str:
    s = str(state or "other").lower().strip()
    table = {
        "playing": "likely_playing",
        "guide": "stuck_guide",
        "login": "login",
        "error": "error_overlay",
        "buffering": "buffering",
        "black": "black_down",
        "ads": "ads",
        "other": "uncertain",
    }
    v = table.get(s, "uncertain")
    # moondream often sets stuck=true even on clear playing frames — trust state first.
    if stuck in (True, "true", "True", 1, "yes") and v in {"uncertain", "other"}:
        v = "stuck_unknown"
    return v


def detect_blue_spinner(im: Any) -> dict[str, Any]:
    """Streamers buffering ring: thin cyan/blue arc over picture center.

    Player-3 failure mode: ad/slate still has high variance so dark/std
    heuristics say ``likely_playing`` while a blue circle sits on the video.

    Run on a full-res center crop (thumbnail washes out the thin arc).
    """
    try:
        import numpy as np
    except ImportError:
        return {"ok": False, "error": "numpy missing", "hit": False}

    full = im.convert("RGB")
    # Keep enough resolution that a 2–4px ring still has blue samples.
    work = full.copy()
    work.thumbnail((960, 540))
    arr = np.asarray(work, dtype=np.int16)
    h, w, _ = arr.shape
    if h < 40 or w < 40:
        return {"ok": True, "hit": False, "reason": "too_small"}

    cy, cx = h // 2, w // 2
    # Spinner sits near geometric center; sweep radii (~3–12% of min side).
    base = max(16, min(h, w) // 12)
    radii = sorted({base, int(base * 1.25), int(base * 1.5), min(h, w) // 8, min(h, w) // 6})

    def _blue_mask(crop: Any) -> Any:
        R, G, B = crop[:, :, 0], crop[:, :, 1], crop[:, :, 2]
        # Measured spinner RGB ~ (38, 149, 236).
        return (B > 120) & (G > 90) & (B > R + 40) & (B >= G) & (R < 160)

    frame_blue = float(_blue_mask(arr).mean())
    best: dict[str, Any] | None = None
    for rad in radii:
        y0, y1 = max(0, cy - rad), min(h, cy + rad)
        x0, x1 = max(0, cx - rad), min(w, cx + rad)
        crop = arr[y0:y1, x0:x1]
        ch, cw = crop.shape[:2]
        if ch < 8 or cw < 8:
            continue
        yy, xx = np.ogrid[:ch, :cw]
        dist = np.sqrt((yy - ch / 2.0) ** 2 + (xx - cw / 2.0) ** 2)
        r = min(ch, cw) / 2.0
        blue = _blue_mask(crop)
        for lo, hi in ((0.22, 0.95), (0.28, 0.92), (0.35, 0.9)):
            ring = (dist > r * lo) & (dist < r * hi)
            disk = dist <= r * 0.18
            ring_n = int(ring.sum()) or 1
            disk_n = int(disk.sum()) or 1
            ring_frac = float(blue[ring].sum() / ring_n)
            disk_frac = float(blue[disk].sum() / disk_n)
            blue_count = int(blue.sum())
            row = {
                "ring_blue_frac": ring_frac,
                "disk_blue_frac": disk_frac,
                "blue_count": blue_count,
                "rad": rad,
                "lo": lo,
                "hi": hi,
            }
            if best is None or ring_frac > float(best["ring_blue_frac"]):
                # Prefer empty-disk candidates even if ring is slightly lower.
                if best is None or disk_frac <= 0.005 or float(best["disk_blue_frac"]) > 0.005:
                    best = row
                elif ring_frac > float(best["ring_blue_frac"]) * 1.2:
                    best = row

    if not best:
        return {"ok": True, "hit": False, "reason": "no_crop"}

    ring_frac = float(best["ring_blue_frac"])
    disk_frac = float(best["disk_blue_frac"])
    blue_count = int(best["blue_count"])
    # Ring of UI blue with hollow center; localized (not a blue-sky broadcast).
    # Thin arcs after ADB compress can be ~15–40 px — still a real spinner.
    hit = bool(
        disk_frac <= 0.005
        and (
            (ring_frac >= 0.01 and ring_frac > frame_blue * 4)
            or (blue_count >= 15 and ring_frac >= 0.0035 and ring_frac > frame_blue * 1.2)
        )
    )
    return {
        "ok": True,
        "hit": hit,
        "ring_blue_frac": round(ring_frac, 5),
        "disk_blue_frac": round(disk_frac, 5),
        "frame_blue_frac": round(frame_blue, 5),
        "blue_count": blue_count,
        "rad": best.get("rad"),
    }


def detect_error_card(im: Any, *, dark: float, bright: float, std: float, mean: float) -> dict[str, Any]:
    """Cloudflare / network / 'go to cloud' style full-frame error cards.

    Typical: mostly dark or flat gray with a pale icon + message block in center.
    """
    try:
        import numpy as np
    except ImportError:
        return {"ok": False, "error": "numpy missing", "hit": False}

    arr = np.asarray(im.convert("RGB"), dtype=np.int16)
    h, w, _ = arr.shape
    cy0, cy1 = int(h * 0.25), int(h * 0.75)
    cx0, cx1 = int(w * 0.25), int(w * 0.75)
    center = arr[cy0:cy1, cx0:cx1]
    c_mean = float(center.mean())
    c_std = float(center.std()) if center.size else 0.0
    # Pale icon / cloud blob in an otherwise dark error panel.
    pale = ((center[:, :, 0] > 170) & (center[:, :, 1] > 170) & (center[:, :, 2] > 170)).mean()
    reasons: list[str] = []
    hit = False
    if dark >= 0.55 and pale >= 0.02 and c_std < 45 and mean < 90:
        hit = True
        reasons.append("dark_panel_pale_center")
    if bright >= 0.08 and dark >= 0.4 and std < 35 and mean < 110:
        hit = True
        reasons.append("flat_error_card")
    # Very low chroma / gray UI with moderate brightness — soft signal only with pale center.
    chroma = float(np.abs(arr[:, :, 0].astype(np.float32) - arr[:, :, 1]).mean())
    if chroma < 6 and 25 <= mean <= 120 and pale >= 0.03 and std < 40:
        hit = True
        reasons.append("gray_cloud_ui")
    return {
        "ok": True,
        "hit": hit,
        "pale_center_frac": round(float(pale), 4),
        "center_mean": round(c_mean, 1),
        "center_std": round(c_std, 1),
        "chroma": round(chroma, 2),
        "reasons": reasons,
    }


def heuristic_score(image_path: Path) -> dict[str, Any]:
    """Cheap local read of one frame — no model."""
    try:
        from PIL import Image, ImageStat
    except ImportError:
        return {"ok": False, "error": "PIL missing"}

    path = Path(image_path)
    if not path.is_file():
        return {"ok": False, "error": f"missing {path}"}

    im = Image.open(path).convert("RGB")
    small = im.copy()
    small.thumbnail((320, 180))
    gray = small.convert("L")
    pix = list(gray.getdata())
    n = len(pix) or 1
    dark = sum(1 for p in pix if p < 28) / n
    bright = sum(1 for p in pix if p > 220) / n
    mean = sum(pix) / n
    stat = ImageStat.Stat(gray)
    std = float(stat.stddev[0]) if stat.stddev else 0.0

    w, h = small.size
    top = gray.crop((0, 0, w, max(1, h // 4)))
    mid = gray.crop((0, h // 4, w, (3 * h) // 4))
    top_mean = sum(top.getdata()) / max(1, top.size[0] * top.size[1])
    mid_mean = sum(mid.getdata()) / max(1, mid.size[0] * mid.size[1])

    # Spinner needs higher-res center samples; error-card OK on thumbnail.
    spinner = detect_blue_spinner(im)
    error_card = detect_error_card(small, dark=dark, bright=bright, std=std, mean=mean)

    reasons: list[str] = []
    if spinner.get("hit"):
        verdict = "blue_spinner"
        reasons.append(
            f"blue_spinner:ring={spinner.get('ring_blue_frac')} disk={spinner.get('disk_blue_frac')}"
        )
    elif error_card.get("hit"):
        verdict = "cloud_network_error"
        reasons.extend(error_card.get("reasons") or ["error_card"])
    elif dark >= 0.85:
        verdict = "black_down"
        reasons.append(f"dark_ratio={dark:.2f}")
    elif dark >= 0.65 and std < 18:
        verdict = "likely_black_or_buffer"
        reasons.extend([f"dark_ratio={dark:.2f}", f"std={std:.1f}"])
    elif std < 12 and mean < 40:
        verdict = "flat_dark"
        reasons.append(f"std={std:.1f}")
    elif std > 25 and dark < 0.55:
        verdict = "likely_playing"
        reasons.extend([f"std={std:.1f}", f"dark_ratio={dark:.2f}"])
    else:
        verdict = "uncertain"
        reasons.extend([f"std={std:.1f}", f"dark_ratio={dark:.2f}"])

    return {
        "ok": True,
        "backend": "heuristic",
        "path": str(path),
        "verdict": verdict,
        "reasons": reasons,
        "picture_ok": verdict == "likely_playing",
        "spinner": spinner,
        "error_card": error_card,
        "metrics": {
            "dark_ratio": round(dark, 3),
            "bright_ratio": round(bright, 3),
            "mean": round(mean, 1),
            "std": round(std, 1),
            "top_mean": round(top_mean, 1),
            "mid_mean": round(mid_mean, 1),
            "size": list(im.size),
        },
    }


def freeze_score(path_a: Path, path_b: Path) -> dict[str, Any]:
    """Compare two successive stills — identical ≈ frozen slate."""
    try:
        from PIL import Image, ImageChops, ImageStat
    except ImportError:
        return {"ok": False, "error": "PIL missing"}
    if not path_a.is_file() or not path_b.is_file():
        return {"ok": False, "error": "need two frames"}
    a = Image.open(path_a).convert("RGB")
    b = Image.open(path_b).convert("RGB")
    b = b.resize(a.size)
    diff = ImageChops.difference(a, b)
    stat = ImageStat.Stat(diff)
    mean_diff = sum(stat.mean) / max(1, len(stat.mean))
    frozen = mean_diff < 2.5
    return {
        "ok": True,
        "mean_diff": round(mean_diff, 2),
        "frozen": frozen,
        "verdict": "frozen_frames" if frozen else "frames_changing",
    }


def vision_moondream(image_path: Path, *, model: str | None = None) -> dict[str, Any]:
    """Ask Ollama moondream what the frame shows (open model, local)."""
    model = model or DEFAULT_VISION_MODEL
    if not VISION_ENABLED:
        return {"ok": False, "error": "OHUSH_VISION=0", "backend": "ollama"}

    prompt = (
        "Look at this TV/emulator screenshot. Reply with ONE line JSON only, keys: "
        "state (one of: playing, guide, login, error, buffering, black, ads, other), "
        "detail (short string), stuck (true/false). "
        "playing=live video picture with no overlay spinner; guide=channel grid; login=credentials; "
        "error=error message or cloud/network 'go to cloud' card; "
        "buffering=blue circular spinner over video; black=blank screen."
    )
    try:
        raw = Path(image_path).read_bytes()
        b64 = base64.b64encode(raw).decode("ascii")
        body = {
            "model": model,
            "prompt": prompt,
            "images": [b64],
            "stream": False,
        }
        req = urllib.request.Request(
            f"{OLLAMA_URL.rstrip('/')}/api/generate",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        text = str(payload.get("response") or "").strip()
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as e:
        return {"ok": False, "error": str(e), "backend": "ollama", "model": model}

    parsed = _parse_vision_json(text)
    verdict = _map_vision_state(parsed.get("state"), stuck=parsed.get("stuck"))
    return {
        "ok": True,
        "backend": "ollama",
        "model": model,
        "raw": text[:500],
        "parsed": parsed,
        "verdict": verdict,
        "stuck": bool(parsed.get("stuck")),
    }


BAD_VERDICTS = frozenset(
    {
        "black_down",
        "likely_black_or_buffer",
        "flat_dark",
        "frozen_frames",
        "stuck_guide",
        "login",
        "error_overlay",
        "buffering",
        "blue_spinner",
        "cloud_network_error",
        "stuck_unknown",
    }
)

PICTURE_HEARTBEAT_NAME = "_picture_heartbeat.json"


def write_picture_heartbeat(
    out_dir: Path,
    *,
    still_path: Path | None = None,
    score: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist picture liveness next to the audio heartbeat (session dir)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if score is None and still_path is not None:
        score = heuristic_score(Path(still_path))
    score = score or {"ok": False, "error": "no_score"}
    verdict = str(score.get("verdict") or "unknown")
    row = {
        "utc": _now(),
        "state": verdict,
        "picture_ok": bool(score.get("picture_ok"))
        if "picture_ok" in score
        else verdict == "likely_playing",
        "still": str(still_path) if still_path else None,
        "reasons": score.get("reasons"),
        "spinner": score.get("spinner"),
        "error_card": score.get("error_card"),
        "metrics": score.get("metrics"),
    }
    path = out_dir / PICTURE_HEARTBEAT_NAME
    path.write_text(json.dumps(row, indent=2), encoding="utf-8")
    row["path"] = str(path)
    return row


def analyze_frame(
    image_path: Path,
    *,
    prev_path: Path | None = None,
    use_vision: bool | None = None,
    model: str | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Heuristic always; vision when uncertain or ``use_vision=True``."""
    image_path = Path(image_path)
    heur = heuristic_score(image_path)
    freeze = freeze_score(prev_path, image_path) if prev_path else None

    need_vision = use_vision
    if need_vision is None:
        need_vision = VISION_ENABLED and (
            not heur.get("ok")
            or heur.get("verdict") in {"uncertain", "likely_black_or_buffer", "flat_dark"}
            or (freeze or {}).get("frozen")
        )

    vision = None
    if need_vision:
        vision = vision_moondream(image_path, model=model)

    # Merge verdict priority: vision (if ok) > freeze > heuristic
    verdict = heur.get("verdict") or "uncertain"
    if freeze and freeze.get("frozen"):
        verdict = "frozen_frames"
    if vision and vision.get("ok") and vision.get("verdict"):
        verdict = vision["verdict"]

    action = "none"
    if verdict in BAD_VERDICTS:
        action = "recover_recommended"
    elif verdict == "likely_playing":
        action = "ok"

    row = {
        "ok": True,
        "checked_utc": _now(),
        "path": str(image_path),
        "verdict": verdict,
        "action": action,
        "heuristic": heur,
        "freeze": freeze,
        "vision": vision,
    }
    _append({"kind": "frame", **row}, root)
    return row


def list_stills(session_dir: Path) -> list[Path]:
    session_dir = Path(session_dir)
    stills = session_dir / "stills"
    paths = sorted(stills.glob("still_t*.jpg")) if stills.is_dir() else []
    if not paths:
        paths = sorted(session_dir.glob("**/still_t*.jpg"))
    return paths


def watch_session_stills(
    session_dir: Path,
    *,
    last_n: int = 5,
    use_vision: bool | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Score the newest stills in a capture session."""
    paths = list_stills(session_dir)
    if not paths:
        return {"ok": False, "error": "no stills", "session_dir": str(session_dir)}
    sample = paths[-max(1, last_n) :]
    rows: list[dict[str, Any]] = []
    prev: Path | None = None
    for p in sample:
        # Vision only on the latest frame to keep cost down
        vision_this = use_vision if p is sample[-1] else False
        if vision_this is None and p is sample[-1]:
            vision_this = None  # allow heuristic gate
        elif p is not sample[-1]:
            vision_this = False
        rows.append(
            analyze_frame(p, prev_path=prev, use_vision=vision_this, root=root)
        )
        prev = p

    bad = [r for r in rows if r.get("verdict") in BAD_VERDICTS]
    latest = rows[-1]
    report = {
        "ok": True,
        "session_dir": str(session_dir),
        "still_count": len(paths),
        "scored": len(rows),
        "latest_verdict": latest.get("verdict"),
        "latest_action": latest.get("action"),
        "bad_count": len(bad),
        "needs_recover": latest.get("action") == "recover_recommended"
        or len(bad) >= max(2, len(rows) // 2),
        "rows": rows,
        "checked_utc": _now(),
    }
    _append({"kind": "session_watch", **{k: v for k, v in report.items() if k != "rows"}}, root)
    return report


def watch_and_recover(
    instance_id: str,
    *,
    session_dir: Path | None = None,
    frame_path: Path | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """If frames look bad, run autonomous streamers_recover."""
    root = ensure_data_layout(root)
    watch: dict[str, Any]
    if session_dir:
        watch = watch_session_stills(Path(session_dir), root=root)
    elif frame_path:
        watch = {
            "ok": True,
            "latest_verdict": None,
            "needs_recover": False,
            "frame": analyze_frame(Path(frame_path), use_vision=None, root=root),
        }
        watch["latest_verdict"] = watch["frame"].get("verdict")
        watch["needs_recover"] = watch["frame"].get("action") == "recover_recommended"
    else:
        # Live screencap via recover snapshot path
        from .streamers_recover import snapshot

        snap = snapshot(instance_id, root=root, take_frame=True)
        fp = snap.get("frame")
        if not fp:
            return {"ok": False, "error": "no frame from snapshot", "snap": snap}
        frame = analyze_frame(Path(fp), use_vision=None, root=root)
        watch = {
            "ok": True,
            "snap_kind": snap.get("kind"),
            "latest_verdict": frame.get("verdict"),
            # Guide / menus are never "ok picture" for a capture — moondream often
            # labels the channel list as playing/US sports and would skip recover.
            "needs_recover": frame.get("action") == "recover_recommended"
            or snap.get("kind")
            in {
                "guide",
                "empty_event_guide",
                "player_decode_error",
                "bluestacks_home",
                "credentials_login",
                "search_ui",
                "section_grid",
            },
            "frame": frame,
            "snap": snap,
        }

    recovery = None
    if watch.get("needs_recover"):
        from .streamers_recover import ensure_picture

        recovery = ensure_picture(instance_id, root=root)

    out = {
        "ok": True,
        "instance_id": instance_id,
        "watch": watch,
        "recovery": recovery,
        "checked_utc": _now(),
    }
    _append({"kind": "watch_and_recover", **out}, root)
    return out


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="Frame watch via heuristics + open vision")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("analyze", help="Score one image")
    a.add_argument("--image", required=True, type=Path)
    a.add_argument("--prev", type=Path, default=None)
    a.add_argument("--vision", action="store_true", help="Force Ollama moondream")
    a.add_argument("--no-vision", action="store_true")

    w = sub.add_parser("session", help="Score newest stills in a session dir")
    w.add_argument("--session-dir", required=True, type=Path)
    w.add_argument("--last-n", type=int, default=5)
    w.add_argument("--vision", action="store_true")

    r = sub.add_parser("watch", help="Live frame + recover if bad")
    r.add_argument("--instance", default="Nougat32")
    r.add_argument("--session-dir", type=Path, default=None)

    args = p.parse_args(argv)
    if args.cmd == "analyze":
        use_v: bool | None
        if args.vision:
            use_v = True
        elif args.no_vision:
            use_v = False
        else:
            use_v = None
        print(json.dumps(analyze_frame(args.image, prev_path=args.prev, use_vision=use_v), indent=2))
        return 0
    if args.cmd == "session":
        print(
            json.dumps(
                watch_session_stills(
                    args.session_dir,
                    last_n=args.last_n,
                    use_vision=True if args.vision else None,
                ),
                indent=2,
            )
        )
        return 0
    if args.cmd == "watch":
        print(
            json.dumps(
                watch_and_recover(args.instance, session_dir=args.session_dir),
                indent=2,
                default=str,
            )
        )
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
