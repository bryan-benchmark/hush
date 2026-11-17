"""Measure how label-window length affects evidence + agreement with locked gold.

DRAFT-AID ONLY — not live mute accuracy.
Mute accuracy: python -m tools.windows_lab.farm_live_scorecard

Does NOT require 1s labeling units. Uses existing takes + gold locks:
  for each locked clip, evaluate sub-windows of length L ∈ {1,3,5,10,15,20}
  and report ASR emptiness, lexicon match to gold bucket, and optional Ollama.

90/10 framing:
  - Decision can be fine-grained; *evidence* usually needs several seconds of speech.
  - 1s stills stay; the question is how wide the ASR+vision context must be.

Usage:
  python -m tools.windows_lab.label_granularity_probe
  python -m tools.windows_lab.label_granularity_probe --ollama --limit 8
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .coverage_farm import farm_label_dir
from .farm_draft import (
    AD_HINT,
    SHOW_HINT,
    SPORTS_VISUAL,
    VISUAL_AD_HINT,
    apply_common_sense,
    is_black_or_corrupt_still,
    nearest_still,
    transcript_for_window,
)

LENGTHS = (1, 3, 5, 10, 15, 20)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def _lexicon_guess(text: str, visual: str) -> str | None:
    ad = bool(AD_HINT.search(text or "") or VISUAL_AD_HINT.search(visual or ""))
    prog = bool(SHOW_HINT.search(text or "") or SPORTS_VISUAL.search(text or "") or SPORTS_VISUAL.search(visual or ""))
    if ad and not prog:
        return "paid_ad"
    if prog and not ad:
        return "program"
    return None


def _windows(t0: float, t1: float, length: float) -> list[tuple[float, float]]:
    """Tile [t0,t1] into length-sec windows (last may be shorter if >=1s)."""
    span = t1 - t0
    if span <= 0:
        return []
    if span <= length:
        return [(t0, t1)]
    out: list[tuple[float, float]] = []
    t = t0
    while t + 0.5 < t1:
        u = min(t1, t + length)
        if u - t >= min(1.0, length):
            out.append((t, u))
        t += length
    return out or [(t0, t1)]


def run_probe(
    *,
    lengths: tuple[int, ...] = LENGTHS,
    ollama: bool = False,
    model: str = "qwen2.5:14b",
    limit_clips: int | None = None,
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
    ]
    if limit_clips is not None:
        locked = locked[:limit_clips]

    # stats[L][metric]
    stats: dict[int, Counter[str]] = {int(L): Counter() for L in lengths}
    examples: dict[str, list] = defaultdict(list)
    transcript_cache: dict[str, dict[str, Any]] = {}
    missing_asr = 0

    for gold in locked:
        clip = str(gold["clip"])
        q = queue.get(clip) or {}
        sd = Path(str(q.get("session_dir") or ""))
        if not sd.is_dir():
            continue
        try:
            gt0 = float(gold.get("t0") if gold.get("t0") is not None else q.get("t0") or 0)
            gt1 = float(gold.get("t1") if gold.get("t1") is not None else q.get("t1") or (gt0 + 20))
        except (TypeError, ValueError):
            continue
        truth = str(gold.get("bucket"))
        if str(sd) not in transcript_cache:
            cache = sd / "farm_transcript.json"
            if cache.is_file():
                try:
                    transcript_cache[str(sd)] = json.loads(cache.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    transcript_cache[str(sd)] = {"ok": False, "segments": []}
            else:
                missing_asr += 1
                transcript_cache[str(sd)] = {"ok": False, "segments": []}
        tr = transcript_cache[str(sd)]

        for L in lengths:
            wins = _windows(gt0, gt1, float(L))
            # Centered evidence window of length L inside the gold span
            mid = 0.5 * (gt0 + gt1)
            half = float(L) / 2.0
            centered = (max(gt0, mid - half), min(gt1, mid + half))
            eval_wins = [("tile", w) for w in wins[:3]] + [("center", centered)]

            for mode, (a, b) in eval_wins:
                if b - a < 0.4:
                    continue
                stats[L]["windows"] += 1
                # pad=0 so L is the true ASR evidence width (not inflated by farm ASR_PAD)
                text = transcript_for_window(tr, a, b, pad=0.0) if tr and tr.get("ok") else ""
                asr_empty = not bool(text.strip())
                if asr_empty:
                    stats[L]["asr_empty"] += 1
                still = nearest_still(sd, 0.5 * (a + b))
                dead = is_black_or_corrupt_still(still)
                if dead:
                    stats[L][f"still_{dead}"] += 1
                    stats[L]["would_skip_black"] += 1
                    continue
                visual = ""
                guess = _lexicon_guess(text, visual)
                rescued = apply_common_sense(
                    {"bucket": "uncertain", "kind": "unknown", "confidence": "low", "why": "probe"},
                    text,
                    visual,
                )
                bucket = rescued["bucket"] if rescued["bucket"] != "uncertain" else (guess or "uncertain")
                if bucket == "uncertain":
                    stats[L]["uncertain"] += 1
                elif bucket == truth:
                    stats[L]["lexicon_match_gold"] += 1
                else:
                    stats[L]["lexicon_mismatch"] += 1
                    if len(examples[f"mis_L{L}"]) < 5:
                        examples[f"mis_L{L}"].append(
                            {"clip": clip, "truth": truth, "guess": bucket, "t0": a, "t1": b, "text": text[:100]}
                        )

                if ollama and mode == "center":
                    try:
                        from .farm_draft import _ask_ollama_text

                        draft = _ask_ollama_text(model, text or "(no speech in window)", visual)
                        draft = apply_common_sense(draft, text, visual)
                        stats[L]["ollama_n"] += 1
                        if draft.get("bucket") == truth:
                            stats[L]["ollama_match_gold"] += 1
                        elif draft.get("bucket") in {"uncertain", ""}:
                            stats[L]["ollama_uncertain"] += 1
                        else:
                            stats[L]["ollama_mismatch"] += 1
                            if len(examples[f"ollama_mis_L{L}"]) < 4:
                                examples[f"ollama_mis_L{L}"].append(
                                    {
                                        "clip": clip,
                                        "truth": truth,
                                        "guess": draft.get("bucket"),
                                        "why": str(draft.get("why") or "")[:120],
                                        "text": text[:120],
                                    }
                                )
                    except Exception as exc:  # noqa: BLE001
                        stats[L]["ollama_error"] += 1
                        if len(examples["ollama_err"]) < 3:
                            examples["ollama_err"].append(str(exc)[:120])

    # Rates
    table = []
    for L in lengths:
        s = stats[L]
        n = max(1, int(s["windows"]))
        row = {
            "length_s": L,
            "windows": int(s["windows"]),
            "asr_empty_pct": round(100 * s["asr_empty"] / n, 1),
            "black_or_corrupt_pct": round(100 * s["would_skip_black"] / n, 1),
            "uncertain_pct": round(100 * s["uncertain"] / n, 1),
            "lexicon_match_gold_pct": round(100 * s["lexicon_match_gold"] / n, 1),
            "lexicon_mismatch_pct": round(100 * s["lexicon_mismatch"] / n, 1),
            "ollama_n": int(s["ollama_n"]),
            "ollama_match_gold_pct": (
                round(100 * s["ollama_match_gold"] / s["ollama_n"], 1) if s["ollama_n"] else None
            ),
            "ollama_uncertain_pct": (
                round(100 * s["ollama_uncertain"] / s["ollama_n"], 1) if s["ollama_n"] else None
            ),
            "ollama_mismatch_pct": (
                round(100 * s["ollama_mismatch"] / s["ollama_n"], 1) if s["ollama_n"] else None
            ),
        }
        table.append(row)

    # Prefer ollama accuracy when present; else lexicon proxy
    def _score(r: dict[str, Any]) -> float:
        if r.get("ollama_n"):
            return float(r["ollama_match_gold_pct"] or 0) - 0.25 * float(r["ollama_uncertain_pct"] or 0)
        return float(r["lexicon_match_gold_pct"]) - 0.3 * float(r["asr_empty_pct"]) - 0.2 * float(
            r["uncertain_pct"]
        )

    best = max((r for r in table if r["windows"] > 0), key=_score, default=None)
    metric = "ollama=gold" if any(r.get("ollama_n") for r in table) else "lexicon=gold"

    out = {
        "generated_utc": _now(),
        "gold_clips": len(locked),
        "sessions_missing_asr": missing_asr,
        "lengths_s": list(lengths),
        "method": (
            "Tile+center windows inside each locked gold span; ASR pad=0 so L is true evidence width. "
            "Lexicon/common-sense vs gold (cheap). Optional center-window Ollama."
        ),
        "insight": (
            "1s stills measure picture change; label *decisions* need enough ASR for brand/game words. "
            "You can still emit 1s decisions by sliding a wider evidence window (e.g. ±4s) around each second."
        ),
        "table": table,
        "recommend_length_s": (best or {}).get("length_s"),
        "recommend_why": (
            f"Best {metric} among {list(lengths)}s on {len(locked)} gold clips"
            if best
            else None
        ),
        "examples": dict(examples),
        "next": (
            "If recommend ≥10s: keep ~10–15s label clips, use 1s stills only for cuts. "
            "If 3–5s close to 10s: try sliding 5s evidence / 1s hop for finer maps without 1s-only ASR."
        ),
    }
    path = label / "GRANULARITY_PROBE.json"
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    md = [
        f"# Granularity probe — {out['generated_utc'][:19]}Z",
        "",
        f"Gold clips: **{len(locked)}** (uncertain excluded)",
        "",
        "| L (s) | windows | ASR empty % | black % | lex uncertain % | lexicon=gold % | ollama=gold % | ollama uncertain % |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in table:
        md.append(
            f"| {r['length_s']} | {r['windows']} | {r['asr_empty_pct']} | {r['black_or_corrupt_pct']} | "
            f"{r['uncertain_pct']} | {r['lexicon_match_gold_pct']} | {r['ollama_match_gold_pct']} | "
            f"{r['ollama_uncertain_pct']} |"
        )
    md.extend(
        [
            "",
            f"**Recommend evidence width:** **{out.get('recommend_length_s')}s** — {out.get('recommend_why')}",
            "",
            out["insight"],
            "",
            out["next"],
            "",
            f"JSON: `{path}`",
            "",
        ]
    )
    md_path = label / "GRANULARITY_PROBE.md"
    md_path.write_text("\n".join(md), encoding="utf-8")
    out["md_path"] = str(md_path)
    out["json_path"] = str(path)
    return out


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="Label window granularity probe vs gold")
    p.add_argument("--ollama", action="store_true", help="Also score center windows with qwen")
    p.add_argument("--model", default="qwen2.5:14b")
    p.add_argument("--limit", type=int, default=None, help="Max gold clips")
    p.add_argument("--lengths", default="1,3,5,10,15,20")
    args = p.parse_args(argv)
    lengths = tuple(int(x) for x in str(args.lengths).split(",") if x.strip())
    out = run_probe(lengths=lengths, ollama=args.ollama, model=args.model, limit_clips=args.limit)
    print(json.dumps({k: out[k] for k in ("gold_clips", "table", "recommend_length_s", "recommend_why", "md_path")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
