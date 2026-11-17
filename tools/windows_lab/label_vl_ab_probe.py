"""A/B: current text stack vs Qwen2.5-VL on locked gold clips.

DRAFT-AID ONLY — not live mute accuracy.
Mute accuracy is tools.windows_lab.farm_live_scorecard (WAV → frame_mn10 stack).

Experiment (confirm on this box)
--------------------------------
Same gold locks, same Whisper window, two judges:

  A) baseline — moondream captions (3 stills) → qwen2.5:14b text  [today's draft]
  B) vl       — qwen2.5vl:7b sees the JPEG pixels + transcript     [candidate]

Metric: % bucket match to human gold; uncertain %; mean seconds/clip.
This measures draft-helper quality for humans. It does not KEEP/ship the Mac muter.

Win rule (improve draft helper only):
  vl_match_pct >= baseline_match_pct + 5  OR
  (vl_match >= baseline AND vl_uncertain < baseline_uncertain - 5)

Usage
-----
  ollama pull qwen2.5vl:7b
  python -m tools.windows_lab.label_vl_ab_probe
  python -m tools.windows_lab.label_vl_ab_probe --limit 12 --max-stills 5
"""

from __future__ import annotations

import base64
import json
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from .coverage_farm import farm_label_dir
from .farm_draft import (
    OLLAMA_KEEP_ALIVE,
    OLLAMA_URL,
    PROMPT,
    _ask_ollama_text,
    _parse_label_payload,
    apply_common_sense,
    describe_clip_stills,
    nearest_still,
    transcript_for_window,
)

VL_MODEL = "qwen2.5vl:7b"
BASE_TEXT = "qwen2.5:14b"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def _stills_for_clip(session_dir: Path, t0: float, t1: float, *, max_stills: int) -> list[Path]:
    """Evenly sample up to max_stills JPEGs inside [t0, t1]."""
    stills_dir = session_dir / "stills"
    if not stills_dir.is_dir():
        return []
    rows: list[tuple[float, Path]] = []
    for p in stills_dir.glob("still_t*.jpg"):
        try:
            tt = float(p.stem.replace("still_t", ""))
        except ValueError:
            continue
        if t0 - 0.05 <= tt <= t1 + 0.05:
            rows.append((tt, p))
    rows.sort()
    if not rows:
        mid = nearest_still(session_dir, 0.5 * (t0 + t1))
        return [mid] if mid else []
    if len(rows) <= max_stills:
        return [p for _, p in rows]
    # Even indices including ends
    idxs = sorted({int(round(i * (len(rows) - 1) / (max_stills - 1))) for i in range(max_stills)})
    return [rows[i][1] for i in idxs]


def _ask_vl(model: str, text: str, stills: list[Path]) -> dict[str, Any]:
    prompt = (
        PROMPT.replace("<<TEXT>>", (text or "(no speech)").strip()[:1600]).replace(
            "<<VISUAL>>",
            f"(see {len(stills)} attached TV stills in time order — prefer pixels over guesses)",
        )
    )
    images = [base64.b64encode(p.read_bytes()).decode("ascii") for p in stills if p.is_file()]
    # Images eat context fast; default 4k blows up with ≥3–5 stills (HTTP 400).
    body = json.dumps(
        {
            "model": model,
            "prompt": prompt,
            "images": images,
            "stream": False,
            "format": "json",
            "keep_alive": OLLAMA_KEEP_ALIVE,
            "options": {
                "temperature": 0,
                "num_predict": 140,
                "num_ctx": 32768,
            },
        }
    ).encode()
    req = Request(OLLAMA_URL, data=body, headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=300) as resp:
            raw = json.loads(resp.read().decode())
    except Exception as exc:  # noqa: BLE001
        # Surface Ollama body (context overflow etc.)
        detail = str(exc)
        if hasattr(exc, "read"):
            try:
                detail = exc.read().decode()[:400]  # type: ignore[attr-defined]
            except Exception:
                pass
        raise RuntimeError(detail) from exc
    return _parse_label_payload(raw.get("response") or "{}")


def _load_transcript(sd: Path) -> dict[str, Any]:
    cache = sd / "farm_transcript.json"
    if not cache.is_file():
        return {"ok": False, "segments": []}
    try:
        data = json.loads(cache.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"ok": False, "segments": []}
    return data if data.get("ok") else {"ok": False, "segments": data.get("segments") or []}


def run_ab(
    *,
    vl_model: str = VL_MODEL,
    text_model: str = BASE_TEXT,
    limit: int | None = None,
    max_stills: int = 5,
    skip_baseline: bool = False,
    root: Path | None = None,
) -> dict[str, Any]:
    from .config import ensure_data_layout

    ensure_data_layout(root)
    label = farm_label_dir(root)
    queue = {r["clip"]: r for r in _read_jsonl(label / "queue.jsonl") if r.get("clip")}
    keys = _read_jsonl(label / "key.jsonl")
    locked = [
        k
        for k in keys
        if (k.get("ask") == "locked" or k.get("gold") or k.get("source") in {"gold", "human"})
        and str(k.get("bucket") or "") not in {"", "uncertain"}
        and k.get("ask") != "skip"
        and str(k.get("source") or "") != "skip_gold_hygiene"
    ]
    # Prefer proud clean list when gold_hygiene has written one.
    clean_path = label / "GOLD_CLEAN.json"
    if clean_path.is_file():
        try:
            clean_set = set(json.loads(clean_path.read_text(encoding="utf-8")).get("clips") or [])
            if clean_set:
                locked = [k for k in locked if str(k.get("clip")) in clean_set]
        except json.JSONDecodeError:
            pass
    if limit is not None:
        locked = locked[:limit]

    stats = {
        "baseline": Counter(),
        "vl": Counter(),
    }
    times = {"baseline": [], "vl": []}
    rows_out: list[dict[str, Any]] = []

    for gold in locked:
        clip = str(gold["clip"])
        q = queue.get(clip) or {}
        sd = Path(str(q.get("session_dir") or gold.get("session_dir") or ""))
        if not sd.is_dir():
            continue
        try:
            t0 = float(gold.get("t0") if gold.get("t0") is not None else q.get("t0") or 0)
            t1 = float(gold.get("t1") if gold.get("t1") is not None else q.get("t1") or (t0 + 15))
        except (TypeError, ValueError):
            continue
        truth = str(gold.get("bucket"))
        tr = _load_transcript(sd)
        text = transcript_for_window(tr, t0, t1, pad=0.0) if tr.get("ok") else ""
        stills = _stills_for_clip(sd, t0, t1, max_stills=max_stills)
        if not stills:
            continue

        row: dict[str, Any] = {
            "clip": clip,
            "truth": truth,
            "t0": t0,
            "t1": t1,
            "n_stills": len(stills),
            "asr_chars": len(text),
        }

        # --- A: baseline moondream → text qwen ---
        if not skip_baseline:
            t_a = time.perf_counter()
            try:
                vis_meta = describe_clip_stills(sd, t0, t1, model="moondream")
                visual = str(vis_meta.get("visual") or "") if vis_meta.get("ok") else ""
                draft_a = _ask_ollama_text(text_model, text, visual)
                draft_a = apply_common_sense(draft_a, text, visual)
                bucket_a = str(draft_a.get("bucket") or "uncertain")
                stats["baseline"]["n"] += 1
                if bucket_a == truth:
                    stats["baseline"]["match"] += 1
                elif bucket_a == "uncertain":
                    stats["baseline"]["uncertain"] += 1
                else:
                    stats["baseline"]["wrong"] += 1
                row["baseline"] = {
                    "bucket": bucket_a,
                    "confidence": draft_a.get("confidence"),
                    "why": str(draft_a.get("why") or "")[:120],
                }
            except Exception as exc:  # noqa: BLE001
                stats["baseline"]["n"] += 1
                stats["baseline"]["error"] += 1
                row["baseline"] = {"error": str(exc)[:120]}
            times["baseline"].append(time.perf_counter() - t_a)

        # --- B: VL sees pixels ---
        t_b = time.perf_counter()
        try:
            draft_b = _ask_vl(vl_model, text, stills)
            # Pass why into rescue (apply_common_sense also folds why now).
            draft_b = apply_common_sense(draft_b, text, str(draft_b.get("why") or ""))
            bucket_b = str(draft_b.get("bucket") or "uncertain")
            stats["vl"]["n"] += 1
            if bucket_b == truth:
                stats["vl"]["match"] += 1
            elif bucket_b == "uncertain":
                stats["vl"]["uncertain"] += 1
            else:
                stats["vl"]["wrong"] += 1
            row["vl"] = {
                "bucket": bucket_b,
                "confidence": draft_b.get("confidence"),
                "why": str(draft_b.get("why") or "")[:120],
            }
        except Exception as exc:  # noqa: BLE001
            stats["vl"]["n"] += 1
            stats["vl"]["error"] += 1
            row["vl"] = {"error": str(exc)[:160]}
        times["vl"].append(time.perf_counter() - t_b)
        rows_out.append(row)

    def _pct(arm: str, key: str) -> float | None:
        n = int(stats[arm]["n"] or 0)
        if not n:
            return None
        return round(100 * stats[arm][key] / n, 1)

    def _mean(xs: list[float]) -> float | None:
        return round(sum(xs) / len(xs), 2) if xs else None

    summary = {
        "baseline_match_pct": _pct("baseline", "match"),
        "baseline_uncertain_pct": _pct("baseline", "uncertain"),
        "baseline_wrong_pct": _pct("baseline", "wrong"),
        "baseline_sec_per_clip": _mean(times["baseline"]),
        "vl_match_pct": _pct("vl", "match"),
        "vl_uncertain_pct": _pct("vl", "uncertain"),
        "vl_wrong_pct": _pct("vl", "wrong"),
        "vl_sec_per_clip": _mean(times["vl"]),
        "n": int(stats["vl"]["n"]),
    }
    b_m = summary["baseline_match_pct"]
    v_m = summary["vl_match_pct"]
    b_u = summary["baseline_uncertain_pct"] or 0
    v_u = summary["vl_uncertain_pct"] or 0
    if b_m is None or v_m is None:
        verdict = "incomplete"
        ship = False
    else:
        ship = (v_m >= b_m + 5) or (v_m >= b_m and v_u <= b_u - 5)
        verdict = "IMPROVE_DRAFT_AID" if ship else "KEEP_DRAFT_BASELINE"
        if v_m < b_m - 5:
            verdict = "VL_DRAFT_WORSE"

    out = {
        "generated_utc": _now(),
        "experiment": "A/B gold label: moondream→qwen14b vs qwen2.5vl:7b (pixels+ASR)",
        "not_live_mute_accuracy": True,
        "live_mute_scorecard": "python -m tools.windows_lab.farm_live_scorecard",
        "hardware_note": "RTX 4070 SUPER 12GB — draft-aid labeling only; not the Mac muter",
        "models": {"baseline_text": text_model, "baseline_vision": "moondream", "vl": vl_model},
        "max_stills": max_stills,
        "gold_n": len(locked),
        "scored_n": summary["n"],
        "summary": summary,
        "counts": {k: dict(v) for k, v in stats.items()},
        "verdict": verdict,
        "ship_vl_into_draft": ship if isinstance(ship, bool) else False,
        "win_rule": "draft-aid only: vl_match >= baseline+5 OR (vl_match>=baseline AND uncertain drops ≥5pts)",
        "how_you_confirm": [
            "DRAFT AID ONLY — do not treat this as live mute accuracy.",
            "Live mute score: python -m tools.windows_lab.farm_live_scorecard → LIVE_SCORECARD.md",
            "Open VL_AB_PROBE.md — compare match % and uncertain % for human draft helpers.",
            "If IMPROVE_DRAFT_AID: optional wire qwen2.5vl into farm_draft (labeling only).",
            "If VL_DRAFT_WORSE / KEEP: keep baseline draft path.",
        ],
        "rows": rows_out,
    }
    json_path = label / "VL_AB_PROBE.json"
    json_path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    md = [
        f"# VL A/B probe — {out['generated_utc'][:19]}Z",
        "",
        f"**Verdict: `{verdict}`** · scored **{summary['n']}** gold clips · max_stills={max_stills}",
        "",
        "> Draft-aid only. Live mute accuracy: `python -m tools.windows_lab.farm_live_scorecard`",
        "",
        "| Arm | Match gold % | Uncertain % | Wrong % | sec/clip |",
        "|---|---:|---:|---:|---:|",
        f"| A baseline (moondream→{text_model}) | {summary['baseline_match_pct']} | "
        f"{summary['baseline_uncertain_pct']} | {summary['baseline_wrong_pct']} | {summary['baseline_sec_per_clip']} |",
        f"| B **{vl_model}** (pixels+ASR) | {summary['vl_match_pct']} | "
        f"{summary['vl_uncertain_pct']} | {summary['vl_wrong_pct']} | {summary['vl_sec_per_clip']} |",
        "",
        f"Win rule: {out['win_rule']}",
        "",
        "## How to confirm",
        "",
    ]
    md.extend(f"- {x}" for x in out["how_you_confirm"])
    md.extend(["", f"JSON: `{json_path}`", ""])
    md_path = label / "VL_AB_PROBE.md"
    md_path.write_text("\n".join(md), encoding="utf-8")
    out["md_path"] = str(md_path)
    out["json_path"] = str(json_path)
    return out


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="A/B qwen2.5vl vs moondream→qwen on gold")
    p.add_argument("--vl-model", default=VL_MODEL)
    p.add_argument("--text-model", default=BASE_TEXT)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--max-stills", type=int, default=5)
    p.add_argument("--skip-baseline", action="store_true", help="Only run VL arm (faster)")
    args = p.parse_args(argv)
    out = run_ab(
        vl_model=args.vl_model,
        text_model=args.text_model,
        limit=args.limit,
        max_stills=args.max_stills,
        skip_baseline=args.skip_baseline,
    )
    print(
        json.dumps(
            {
                k: out[k]
                for k in (
                    "scored_n",
                    "summary",
                    "verdict",
                    "ship_vl_into_draft",
                    "md_path",
                )
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
