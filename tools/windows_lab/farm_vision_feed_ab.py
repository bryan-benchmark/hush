"""Sealed A/B: caption (current) vs JSON classify vs moondream on farm stills.

Measures pictures/min + empty rate + class agreement. Does not change the live path.
"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from .coverage_farm import farm_label_dir, streamers_capture_root
from .farm_draft import (
    OLLAMA_KEEP_ALIVE,
    OLLAMA_URL,
    VISION_MAX_EDGE,
    _still_jpeg_b64,
    _visual_class,
    describe_still,
    unload_ollama_model,
)

QWEN = "qwen2.5vl:7b"
MOON = "moondream:latest"

CLASSIFY_PROMPT = """This is one TV frame. Classify it for an ad-skip dataset.

Reply with one JSON object only:
{"class":"ad"|"program"|"other","confidence":"high"|"medium"|"low","why":"≤12 words"}

Rules:
- ad = standalone commercial, product/car end-card, brand logo ad, offer screen
- program = live game, scorebug, field/court action, anchors, sports desk, talk show set
- other = guide/UI chrome, black/blank, transition, or unclear
- If both ad and program cues appear, pick the dominant one; else other
"""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sample_stills(sessions: list[str], *, per_session: int, seed: int = 17) -> list[dict[str, Any]]:
    root = streamers_capture_root()
    out: list[dict[str, Any]] = []
    for sess in sessions:
        sd = root / sess / "stills"
        if not sd.is_dir():
            continue
        paths = sorted(sd.glob("still_t*.jpg"))
        if not paths:
            continue
        n = len(paths)
        # Even indices — sealed, reproducible (not random shuffle of live labeling).
        if n <= per_session:
            picks = paths
        else:
            idxs = sorted({int(round(i * (n - 1) / (per_session - 1))) for i in range(per_session)})
            picks = [paths[i] for i in idxs]
        for p in picks:
            out.append({"session": sess, "still": str(p), "name": p.name})
    return out


def _sample_from_vision_hops(*, per_class: int = 16, limit: int = 48) -> list[dict[str, Any]]:
    """Sealed stills from finished hops_vision — already caption-labeled ad/program/other."""
    audit = farm_label_dir() / "audit"
    buckets: dict[str, list[dict[str, Any]]] = {"ad": [], "program": [], "other": []}
    seen: set[str] = set()
    for path in sorted(audit.glob("*/hops_vision.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            vision = (row.get("channels") or {}).get("vision") or {}
            if not vision.get("ok"):
                continue
            cls = str(vision.get("class") or "")
            if cls not in buckets:
                continue
            still = str(vision.get("still") or "")
            if not still or still in seen or not Path(still).is_file():
                continue
            # Skip Streamers guide chrome — not broadcast content.
            vis = str(vision.get("visual") or "").lower()
            if "search bar" in vis or "channel listing" in vis or "tv interface" in vis:
                continue
            seen.add(still)
            buckets[cls].append(
                {
                    "session": row.get("session"),
                    "still": still,
                    "name": Path(still).name,
                    "t": row.get("t"),
                    "ref_class": cls,
                    "ref_visual": str(vision.get("visual") or "")[:240],
                }
            )
    out: list[dict[str, Any]] = []
    for cls, rows in buckets.items():
        if not rows:
            continue
        n = min(per_class, len(rows))
        if len(rows) <= n:
            picks = rows
        else:
            idxs = sorted({int(round(i * (len(rows) - 1) / (n - 1))) for i in range(n)})
            picks = [rows[i] for i in idxs]
        out.extend(picks)
    # Stable order by session/t for readability.
    out.sort(key=lambda r: (str(r.get("session") or ""), float(r.get("t") or 0.0)))
    if limit and len(out) > limit:
        step = len(out) / limit
        out = [out[int(i * step)] for i in range(limit)]
    return out


def _parse_class_json(raw: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw or "{}")
    except json.JSONDecodeError:
        payload = {}
    cls = str(payload.get("class") or "other").strip().lower()
    if cls in {"paid_ad", "commercial", "advertisement"}:
        cls = "ad"
    if cls in {"show", "game", "sports", "broadcast"}:
        cls = "program"
    if cls not in {"ad", "program", "other"}:
        cls = "other"
    conf = str(payload.get("confidence") or "low").strip().lower()
    if conf not in {"high", "medium", "low"}:
        conf = "low"
    why = str(payload.get("why") or "").strip()[:120]
    return {"class": cls, "confidence": conf, "why": why, "raw": (raw or "")[:300]}


def classify_still(image_path: Path, *, model: str = QWEN) -> dict[str, Any]:
    from .farm_draft import is_black_or_corrupt_still

    t0 = time.perf_counter()
    dead = is_black_or_corrupt_still(image_path)
    if dead:
        return {
            "ok": False,
            "error": f"{dead}_still",
            "class": None,
            "mode": "classify",
            "model": model,
            "sec": round(time.perf_counter() - t0, 3),
        }
    try:
        b64, enc = _still_jpeg_b64(image_path, max_edge=VISION_MAX_EDGE)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"encode:{exc}", "sec": round(time.perf_counter() - t0, 3)}
    body = json.dumps(
        {
            "model": model,
            "prompt": CLASSIFY_PROMPT,
            "images": [b64],
            "stream": False,
            "format": "json",
            "keep_alive": OLLAMA_KEEP_ALIVE,
            "options": {"temperature": 0, "num_predict": 48},
        }
    ).encode()
    try:
        req = Request(OLLAMA_URL, data=body, headers={"Content-Type": "application/json"})
        with urlopen(req, timeout=180) as resp:
            raw = json.loads(resp.read().decode())
        parsed = _parse_class_json(str(raw.get("response") or ""))
        return {
            "ok": True,
            "model": model,
            "mode": "classify",
            "class": parsed["class"],
            "confidence": parsed["confidence"],
            "why": parsed["why"],
            "visual": parsed["why"],
            "encode": enc,
            "sec": round(time.perf_counter() - t0, 3),
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc), "model": model, "mode": "classify", "sec": round(time.perf_counter() - t0, 3)}


def caption_still(image_path: Path, *, model: str) -> dict[str, Any]:
    t0 = time.perf_counter()
    meta = describe_still(image_path, model=model)
    meta["sec"] = round(time.perf_counter() - t0, 3)
    meta["mode"] = "caption"
    if meta.get("ok") and meta.get("visual"):
        meta["class"] = _visual_class(str(meta.get("visual") or ""))
    else:
        meta["class"] = None
    return meta


def _arm_summary(rows: list[dict[str, Any]], *, name: str) -> dict[str, Any]:
    ok = [r for r in rows if r.get("ok") and r.get("class")]
    empty = [r for r in rows if not r.get("ok") or not r.get("class")]
    secs = [float(r.get("sec") or 0) for r in rows if r.get("sec") is not None]
    mean = (sum(secs) / len(secs)) if secs else None
    classes = Counter(str(r.get("class")) for r in ok)
    return {
        "arm": name,
        "n": len(rows),
        "ok_n": len(ok),
        "empty_or_fail_n": len(empty),
        "empty_pct": round(100.0 * len(empty) / len(rows), 1) if rows else None,
        "mean_sec": round(mean, 3) if mean is not None else None,
        "pictures_per_min": round(60.0 / mean, 1) if mean and mean > 0 else None,
        "class_counts": dict(classes),
    }


def _agree(a: list[dict[str, Any]], b: list[dict[str, Any]]) -> dict[str, Any]:
    both = 0
    match = 0
    decisive = 0
    decisive_match = 0
    conf: Counter[str] = Counter()
    for x, y in zip(a, b):
        cx, cy = x.get("class"), y.get("class")
        if not cx or not cy:
            continue
        both += 1
        if cx == cy:
            match += 1
        key = f"{cx}->{cy}"
        conf[key] += 1
        if cx in {"ad", "program"} or cy in {"ad", "program"}:
            decisive += 1
            if cx == cy:
                decisive_match += 1
    return {
        "paired_ok": both,
        "agree_pct": round(100.0 * match / both, 1) if both else None,
        "decisive_paired": decisive,
        "decisive_agree_pct": round(100.0 * decisive_match / decisive, 1) if decisive else None,
        "top_confusions": conf.most_common(8),
    }


def run(
    *,
    limit: int = 48,
    per_session: int = 16,
    sessions: list[str] | None = None,
    from_hops: bool = True,
) -> dict[str, Any]:
    sessions = sessions or [
        "20261114T0000Z_fox_local",
        "20261114T1730Z_abc_local",
        "20261110T1805Z_on_air_continue",
    ]
    if from_hops:
        pack = _sample_from_vision_hops(per_class=max(8, limit // 3), limit=limit)
    else:
        pack = _sample_stills(sessions, per_session=per_session)
        if limit and len(pack) > limit:
            step = len(pack) / limit
            pack = [pack[int(i * step)] for i in range(limit)]

    out_dir = farm_label_dir() / "audit" / "vision_feed_ab"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    # Warm qwen once, then caption + classify (same resident model).
    unload_ollama_model(MOON)
    qwen_cap: list[dict[str, Any]] = []
    qwen_clf: list[dict[str, Any]] = []
    for row in pack:
        p = Path(row["still"])
        cap = caption_still(p, model=QWEN)
        qwen_cap.append({**row, **cap})
        clf = classify_still(p, model=QWEN)
        qwen_clf.append({**row, **clf})

    # Switch to moondream.
    unload_ollama_model(QWEN)
    moon_cap: list[dict[str, Any]] = []
    for row in pack:
        p = Path(row["still"])
        cap = caption_still(p, model=MOON)
        moon_cap.append({**row, **cap})
    # Leave qwen hot for the farm labeler.
    unload_ollama_model(MOON)

    # Against sealed prior caption labels when available (replacement test).
    ref_rows = [
        {"class": r.get("ref_class"), "ok": bool(r.get("ref_class")), "still": r.get("still")}
        for r in pack
    ]
    has_ref = any(r.get("ref_class") for r in pack)

    summary = {
        "ok": True,
        "utc": _now(),
        "n_stills": len(pack),
        "pack_mode": "vision_hops" if from_hops else "even_stills",
        "sessions": sorted({str(r.get("session")) for r in pack}),
        "arms": {
            "qwen_caption": _arm_summary(qwen_cap, name="qwen_caption"),
            "qwen_classify": _arm_summary(qwen_clf, name="qwen_classify"),
            "moondream_caption": _arm_summary(moon_cap, name="moondream_caption"),
        },
        "agreement": {
            "classify_vs_caption": _agree(qwen_clf, qwen_cap),
            "moondream_vs_caption": _agree(moon_cap, qwen_cap),
            "moondream_vs_classify": _agree(moon_cap, qwen_clf),
            "classify_vs_ref": _agree(qwen_clf, ref_rows) if has_ref else None,
            "caption_vs_ref": _agree(qwen_cap, ref_rows) if has_ref else None,
            "moondream_vs_ref": _agree(moon_cap, ref_rows) if has_ref else None,
        },
        "verdict": None,
    }

    cap_s = summary["arms"]["qwen_caption"]
    clf_s = summary["arms"]["qwen_classify"]
    moon_s = summary["arms"]["moondream_caption"]
    agr = summary["agreement"]["classify_vs_ref"] or summary["agreement"]["classify_vs_caption"]
    moon_agr = summary["agreement"]["moondream_vs_ref"] or summary["agreement"]["moondream_vs_caption"]

    keep_classify = False
    reasons: list[str] = []
    if (clf_s.get("mean_sec") or 99) < (cap_s.get("mean_sec") or 0) * 0.85:
        reasons.append("classify ≥15% faster than caption")
        keep_classify = True
    else:
        reasons.append("classify not clearly faster")
    if (agr.get("agree_pct") or 0) >= 80:
        reasons.append(f"classify agrees with sealed caption labels {agr.get('agree_pct')}%")
    else:
        reasons.append(f"classify agreement too low ({agr.get('agree_pct')}%)")
        keep_classify = False
    if (moon_s.get("empty_pct") or 0) >= 25:
        reasons.append(f"moondream empty/fail {moon_s.get('empty_pct')}% — not a caption replacement")
    elif (moon_agr.get("agree_pct") or 0) >= 80 and (moon_s.get("mean_sec") or 99) < (cap_s.get("mean_sec") or 0):
        reasons.append("moondream competitive — consider triage role")
    else:
        reasons.append("moondream slower or disagrees too much for triage win")

    summary["verdict"] = {
        "keep_classify_over_caption": bool(
            keep_classify
            and (agr.get("agree_pct") or 0) >= 80
            and (clf_s.get("mean_sec") or 99) <= (cap_s.get("mean_sec") or 0)
        ),
        "keep_moondream": bool(
            (moon_s.get("empty_pct") or 100) < 15
            and (moon_agr.get("agree_pct") or 0) >= 80
            and (moon_s.get("mean_sec") or 99) < (cap_s.get("mean_sec") or 0) * 0.9
        ),
        "reasons": reasons,
    }

    path = out_dir / f"feed_ab_{stamp}.json"
    path.write_text(
        json.dumps(
            {
                **summary,
                "rows": {
                    "qwen_caption": qwen_cap,
                    "qwen_classify": qwen_clf,
                    "moondream_caption": moon_cap,
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    summary["path"] = str(path)
    return summary


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--limit", type=int, default=48)
    p.add_argument("--per-session", type=int, default=16)
    p.add_argument("--even-stills", action="store_true", help="Old even-still pack (includes guide chrome)")
    args = p.parse_args()
    blob = run(limit=args.limit, per_session=args.per_session, from_hops=not args.even_stills)
    # Compact stdout for the desk / chat.
    slim = {
        "ok": blob.get("ok"),
        "n_stills": blob.get("n_stills"),
        "arms": blob.get("arms"),
        "agreement": blob.get("agreement"),
        "verdict": blob.get("verdict"),
        "path": blob.get("path"),
    }
    print(json.dumps(slim, indent=2))


if __name__ == "__main__":
    main()
