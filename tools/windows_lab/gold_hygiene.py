"""Scrub farm gold so A/B and trust use a dataset we can stand behind.

Flags / demotes locks that are:
  - A/V content desync (early program ASR + late ad ASR, or picture-vs-speech clash)
  - Human note is pure ad_lexicon paste while visual/why looks like news packaging
  - Explicit av_mismatch / discarded in judgments

Proud gold = ask=locked (or gold/human) AND bucket real AND NOT demoted.

Usage:
  python -m tools.windows_lab.gold_hygiene              # dry-run report
  python -m tools.windows_lab.gold_hygiene --apply      # rewrite key ask=skip for poisoned
  python -m tools.windows_lab.gold_hygiene --apply --write-clean-list
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .coverage_farm import farm_label_dir
from .farm_draft import (
    AD_HINT,
    SHOW_HINT,
    SPORTS_VISUAL,
    VISUAL_AD_HINT,
    detect_av_content_desync,
    transcript_for_window,
)
from .farm_label_audit import _read_jsonl, atomic_write_jsonl, append_draft_events


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_transcript(sd: Path) -> dict[str, Any]:
    cache = sd / "farm_transcript.json"
    if not cache.is_file():
        return {"ok": False, "segments": []}
    try:
        data = json.loads(cache.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"ok": False, "segments": []}
    return data if data.get("ok") else {"ok": False, "segments": data.get("segments") or []}


def _is_locked_gold(k: dict[str, Any]) -> bool:
    if str(k.get("bucket") or "") in {"", "uncertain"}:
        return False
    return bool(
        k.get("ask") == "locked"
        or k.get("gold")
        or k.get("source") in {"gold", "human"}
    )


def audit_gold(root: Path | None = None) -> dict[str, Any]:
    label = farm_label_dir(root)
    keys = {str(r["clip"]): r for r in _read_jsonl(label / "key.jsonl") if r.get("clip")}
    queue = {str(r["clip"]): r for r in _read_jsonl(label / "queue.jsonl") if r.get("clip")}
    jud: dict[str, Any] = {}
    jp = label / "take_judgments.json"
    if jp.is_file():
        try:
            jud = json.loads(jp.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            jud = {}

    locked = [k for k in keys.values() if _is_locked_gold(k)]
    poisoned: list[dict[str, Any]] = []
    clean: list[dict[str, Any]] = []
    reasons = Counter()

    for k in locked:
        clip = str(k["clip"])
        q = queue.get(clip) or {}
        j = jud.get(clip) or {}
        issues: list[str] = []

        if j.get("discarded") or j.get("av_mismatch"):
            issues.append("judgment_av_or_discard")

        try:
            t0 = float(k.get("t0") if k.get("t0") is not None else q.get("t0") or 0)
            t1 = float(k.get("t1") if k.get("t1") is not None else q.get("t1") or (t0 + 15))
        except (TypeError, ValueError):
            t0, t1 = 0.0, 15.0
        span = t1 - t0

        sd = Path(str(q.get("session_dir") or ""))
        text = str(k.get("whisper_text") or "")
        vis = str(k.get("visual_text") or "")
        why = str(k.get("why") or "")
        note = str(k.get("human_note") or k.get("note") or "")
        if sd.is_dir() and (not text or len(text) < 40):
            tr = _load_transcript(sd)
            if tr.get("ok"):
                text = transcript_for_window(tr, t0, t1, pad=0.0)

        head = text[: max(80, int(len(text) * 0.45))]
        desync = detect_av_content_desync(
            head_text=head,
            visual=f"{vis}\n{why}",
            full_text=text,
            still_classes=list(k.get("still_classes") or []),
            span_s=span,
        )
        if desync:
            issues.append(str(desync.get("kind") or "av_desync"))

        # Classic poison: locked paid_ad from ad_lexicon note, but visual/why is news packaging.
        bucket = str(k.get("bucket") or "")
        news_pack = bool(
            VISUAL_AD_HINT.search(vis)
            or SPORTS_VISUAL.search(vis)
            or SHOW_HINT.search(vis)
            or SPORTS_VISUAL.search(why)
            or SHOW_HINT.search(why)
            or ("pants on fire" in f"{vis} {why}".lower())
            or ("caught our eye" in f"{vis} {why}".lower())
            or ("cbs mornings" in f"{vis} {why}".lower())
        )
        # Soft: paid_ad lock whose human note is only lexicon paste + program-ish visual words in why
        if bucket == "paid_ad" and note.startswith("ad_lexicon") and (
            "pants on fire" in f"{vis} {why}".lower()
            or "caught our eye" in f"{vis} {why}".lower()
            or (SHOW_HINT.search(why) and not AD_HINT.search(vis or why))
        ):
            issues.append("paid_ad_lock_on_news_packaging")

        # Pants-on-fire family from VL A/B root cause (hard list if still locked)
        if "pants" in f"{vis} {why} {note}".lower() and bucket == "paid_ad":
            issues.append("pants_on_fire_paid_ad_lock")

        # Known desync locks from root-cause (picture news / ASR ad) — proud gold must drop these.
        KNOWN_POISON = {
            "20261110T1533Z_cbs_local_flagship_372_388",
            "20261110T1533Z_cbs_local_flagship_384_400",
            "20261110T1636Z_abc_local_flagship_276_292",
            "20261110T1636Z_abc_local_flagship_288_304",
        }
        if clip in KNOWN_POISON:
            issues.append("known_desync_rootcause")

        if issues:
            for i in issues:
                reasons[i] += 1
            poisoned.append(
                {
                    "clip": clip,
                    "bucket": bucket,
                    "issues": issues,
                    "human_note": note[:120],
                    "why": why[:120],
                    "span_s": round(span, 1),
                }
            )
        else:
            clean.append(
                {
                    "clip": clip,
                    "bucket": bucket,
                    "source": k.get("source"),
                    "span_s": round(span, 1),
                }
            )

    out = {
        "generated_utc": _now(),
        "locked_n": len(locked),
        "clean_n": len(clean),
        "poisoned_n": len(poisoned),
        "poison_reasons": dict(reasons),
        "poisoned": poisoned,
        "clean": clean,
        "proud_rule": (
            "Gold for scoring = locked + real bucket + not desync/news-packaging/av_mismatch. "
            "Poisoned locks → ask=skip (same as A/V discard), stay out of VL A/B and trust."
        ),
    }
    path = label / "GOLD_HYGIENE.json"
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    md = [
        f"# Gold hygiene — {out['generated_utc'][:19]}Z",
        "",
        f"Locked: **{out['locked_n']}** · Clean (proud): **{out['clean_n']}** · Poisoned: **{out['poisoned_n']}**",
        "",
        "## Poison reasons",
        "",
    ]
    for r, n in reasons.most_common():
        md.append(f"- `{r}`: {n}")
    md.extend(["", "## Poisoned clips", ""])
    for p in poisoned[:40]:
        md.append(f"- `{p['clip']}` · gold={p['bucket']} · {', '.join(p['issues'])}")
    if len(poisoned) > 40:
        md.append(f"- … +{len(poisoned) - 40} more")
    md.extend(["", out["proud_rule"], "", f"JSON: `{path}`", ""])
    md_path = label / "GOLD_HYGIENE.md"
    md_path.write_text("\n".join(md), encoding="utf-8")
    out["md_path"] = str(md_path)
    out["json_path"] = str(path)
    return out


def apply_scrub(root: Path | None = None, *, write_clean_list: bool = True) -> dict[str, Any]:
    """Demote poisoned gold to ask=skip so they leave scoring sets."""
    report = audit_gold(root)
    label = farm_label_dir(root)
    key_path = label / "key.jsonl"
    keys = {str(r["clip"]): r for r in _read_jsonl(key_path) if r.get("clip")}
    tick = f"gold_hygiene:{_now()}"
    events: list[dict[str, Any]] = []
    scrubbed = 0
    for row in report["poisoned"]:
        clip = row["clip"]
        prior = keys.get(clip)
        if not prior:
            continue
        if prior.get("ask") == "skip" and "skip_gold_hygiene" in str(prior.get("why") or ""):
            continue
        issues = ",".join(row.get("issues") or [])
        keys[clip] = {
            **prior,
            "ask": "skip",
            "gold": False,
            "source": "skip_gold_hygiene",
            "prior_bucket": prior.get("bucket"),
            "prior_ask": prior.get("ask"),
            "why": f"skip_gold_hygiene:{issues}",
            "scrubbed_utc": tick,
        }
        scrubbed += 1
        events.append(
            {
                "utc": tick,
                "clip": clip,
                "ask": "skip",
                "bucket": "uncertain",
                "why": keys[clip]["why"],
                "prior_ask": prior.get("ask"),
                "prior_bucket": prior.get("bucket"),
            }
        )
    if scrubbed:
        atomic_write_jsonl(key_path, list(keys.values()))
        append_draft_events(events, root=root, tick_id=tick)
    clean_clips = [c["clip"] for c in report["clean"]]
    if write_clean_list:
        (label / "GOLD_CLEAN.json").write_text(
            json.dumps(
                {
                    "generated_utc": _now(),
                    "n": len(clean_clips),
                    "clips": clean_clips,
                    "note": "Use only these for VL A/B / trust until more proud locks added via /farm",
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    report["scrubbed"] = scrubbed
    report["clean_list"] = str(label / "GOLD_CLEAN.json") if write_clean_list else None
    return report


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="Audit/scrub poisoned farm gold")
    p.add_argument("--apply", action="store_true", help="Demote poisoned locks to ask=skip")
    p.add_argument("--write-clean-list", action="store_true", default=True)
    p.add_argument("--no-clean-list", action="store_true")
    args = p.parse_args(argv)
    if args.apply:
        out = apply_scrub(write_clean_list=not args.no_clean_list)
        print(
            json.dumps(
                {
                    k: out[k]
                    for k in (
                        "locked_n",
                        "clean_n",
                        "poisoned_n",
                        "scrubbed",
                        "poison_reasons",
                        "md_path",
                        "clean_list",
                    )
                },
                indent=2,
            )
        )
    else:
        out = audit_gold()
        print(
            json.dumps(
                {
                    k: out[k]
                    for k in ("locked_n", "clean_n", "poisoned_n", "poison_reasons", "md_path")
                },
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
