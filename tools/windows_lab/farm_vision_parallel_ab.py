"""A/B: serial caption vs 2-wide concurrent caption (needs OLLAMA_NUM_PARALLEL>=2)."""

from __future__ import annotations

import argparse
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .coverage_farm import farm_label_dir
from .farm_draft import describe_still, unload_ollama_model
from .farm_vision_feed_ab import QWEN, _sample_from_vision_hops


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _caption_one(still: str) -> dict[str, Any]:
    t0 = time.perf_counter()
    meta = describe_still(Path(still), model=QWEN)
    return {
        "still": still,
        "ok": bool(meta.get("ok") and meta.get("visual")),
        "sec": round(time.perf_counter() - t0, 3),
        "error": meta.get("error"),
        "visual": str(meta.get("visual") or "")[:120],
    }


def _run_serial(stills: list[str]) -> dict[str, Any]:
    t0 = time.perf_counter()
    rows = [_caption_one(s) for s in stills]
    wall = time.perf_counter() - t0
    ok = sum(1 for r in rows if r["ok"])
    return {
        "mode": "serial",
        "n": len(stills),
        "ok_n": ok,
        "wall_s": round(wall, 3),
        "mean_sec_each": round(wall / len(stills), 3) if stills else None,
        "pictures_per_min": round(60.0 * len(stills) / wall, 1) if wall > 0 else None,
        "rows": rows,
    }


def _run_parallel(stills: list[str], *, workers: int) -> dict[str, Any]:
    t0 = time.perf_counter()
    rows: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(_caption_one, s): s for s in stills}
        for fut in as_completed(futs):
            rows.append(fut.result())
    # Keep input order for diffs.
    by = {r["still"]: r for r in rows}
    ordered = [by[s] for s in stills]
    wall = time.perf_counter() - t0
    ok = sum(1 for r in ordered if r["ok"])
    return {
        "mode": f"parallel_{workers}",
        "workers": workers,
        "n": len(stills),
        "ok_n": ok,
        "wall_s": round(wall, 3),
        "mean_sec_each": round(wall / len(stills), 3) if stills else None,
        "pictures_per_min": round(60.0 * len(stills) / wall, 1) if wall > 0 else None,
        "rows": ordered,
    }


def run(*, limit: int = 24, workers: int = 2, worker_list: list[int] | None = None) -> dict[str, Any]:
    pack = _sample_from_vision_hops(per_class=max(6, limit // 3), limit=limit)
    stills = [str(r["still"]) for r in pack]
    unload_ollama_model("moondream:latest")

    # Warm one call so load cost is outside the race.
    if stills:
        _caption_one(stills[0])

    serial = _run_serial(stills)
    widths = worker_list or [workers]
    parallels: dict[str, dict[str, Any]] = {}
    for w in widths:
        parallels[f"parallel_{w}"] = _run_parallel(stills, workers=w)

    ser_ppm = serial.get("pictures_per_min") or 0
    best_w = None
    best_ppm = ser_ppm
    comparisons: dict[str, Any] = {}
    for key, parallel in parallels.items():
        par_ppm = parallel.get("pictures_per_min") or 0
        speedup = round(par_ppm / ser_ppm, 2) if ser_ppm else None
        keep = bool(speedup and speedup >= 1.25 and parallel["ok_n"] >= serial["ok_n"] * 0.95)
        comparisons[key] = {
            "speedup_vs_serial": speedup,
            "keep": keep,
            "ok_n": parallel["ok_n"],
            "pictures_per_min": par_ppm,
            "wall_s": parallel.get("wall_s"),
            "vram_note": "see nvidia-smi after run",
        }
        if keep and par_ppm >= best_ppm * 1.05:
            best_ppm = par_ppm
            best_w = int(key.rsplit("_", 1)[-1])
        elif keep and best_w is None and par_ppm > ser_ppm:
            best_w = int(key.rsplit("_", 1)[-1])
            best_ppm = par_ppm

    # Prefer widest that still beats next-smaller by ≥5%; else stick with prior keep.
    recommended = best_w if best_w is not None else (2 if comparisons.get("parallel_2", {}).get("keep") else 1)

    out = {
        "ok": True,
        "utc": _now(),
        "ollama_num_parallel_env": os.environ.get("OLLAMA_NUM_PARALLEL"),
        "n_stills": len(stills),
        "serial": {k: v for k, v in serial.items() if k != "rows"},
        "parallels": {k: {kk: vv for kk, vv in v.items() if kk != "rows"} for k, v in parallels.items()},
        "comparisons": comparisons,
        "verdict": {
            "recommended_workers": recommended,
            "reasons": [
                f"{k}: {v['speedup_vs_serial']}× serial, {v['pictures_per_min']}/min, keep={v['keep']}"
                for k, v in comparisons.items()
            ]
            + [f"recommend workers={recommended}"],
        },
        "rows": {
            "serial": serial["rows"],
            **{k: v["rows"] for k, v in parallels.items()},
        },
    }
    dest = farm_label_dir() / "audit" / "vision_feed_ab"
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / f"parallel_ab_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    out["path"] = str(path)
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--limit", type=int, default=24)
    p.add_argument("--workers", type=int, default=2)
    p.add_argument(
        "--widths",
        type=str,
        default="",
        help="Comma list e.g. 2,3 — runs each width after serial",
    )
    args = p.parse_args()
    widths = [int(x) for x in args.widths.split(",") if x.strip()] if args.widths else None
    blob = run(limit=args.limit, workers=args.workers, worker_list=widths)
    print(json.dumps({k: v for k, v in blob.items() if k != "rows"}, indent=2))


if __name__ == "__main__":
    main()
