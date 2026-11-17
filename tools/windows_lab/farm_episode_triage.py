"""Triage DISAGREE hops as still-run episodes; propose/apply clear gold boundary fixes.

Usage
-----
  python -m tools.windows_lab.farm_episode_triage
  python -m tools.windows_lab.farm_episode_triage --apply-clear-fixes
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .coverage_farm import farm_label_dir
from .export_farm_acoustic_gold import export as export_farm_gold

# Prefer these first; run() also auto-includes any audit/*/hops.jsonl with disagrees.
SESSIONS = (
    "20261110T1339Z_pluto_cbs_sports_hq",
    "20261110T1401Z_pluto_cbs_sports_hq",
)


def _sessions_with_hops() -> list[str]:
    root = farm_label_dir() / "audit"
    if not root.is_dir():
        return list(SESSIONS)
    found: list[str] = []
    for path in sorted(root.iterdir()):
        if not path.is_dir():
            continue
        hops = path / "hops.jsonl"
        if not hops.is_file():
            continue
        # Skip empty / no-disagree sessions — they only clutter the Done queue.
        try:
            n_dis = sum(
                1
                for line in hops.read_text(encoding="utf-8").splitlines()
                if line.strip() and json.loads(line).get("disagreement")
            )
        except json.JSONDecodeError:
            continue
        if n_dis <= 0:
            continue
        found.append(path.name)
    ordered = [s for s in SESSIONS if s in found]
    ordered.extend(s for s in found if s not in ordered)
    return ordered or list(SESSIONS)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_hops(session: str) -> list[dict[str, Any]]:
    path = farm_label_dir() / "audit" / session / "hops.jsonl"
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def _episodes(disag_times: list[float]) -> list[tuple[float, float]]:
    if not disag_times:
        return []
    times = sorted(disag_times)
    out = []
    a = b = times[0]
    for t in times[1:]:
        if t <= b + 1.01:
            b = t
        else:
            out.append((a, b))
            a = b = t
    out.append((a, b))
    return out


def _tag_episode(seq: list[dict[str, Any]]) -> str:
    n = len(seq) or 1
    # Channel changes during capture leave Streamers guide chrome in the stills.
    # Picture captions already say so — never send those to human review.
    try:
        from .farm_draft import vision_caption_is_guide

        guide_n = sum(1 for s in seq if vision_caption_is_guide(s.get("visual")))
        if guide_n / n >= 0.8:
            return "streamers_guide"
    except Exception:  # noqa: BLE001
        pass
    mute_v = sum(1 for s in seq if s.get("vb") == "non_broadcast" or s.get("v") == "ad")
    mute_a = sum(1 for s in seq if s.get("ab") == "non_broadcast")
    play_g = sum(1 for s in seq if s.get("g") in {"broadcast", "program"})
    cover = sum(1 for s in seq if s.get("act") == "cover")
    high_p = sum(1 for s in seq if s.get("p") is not None and float(s["p"]) >= 0.9 and s.get("act") == "cover")
    hang = sum(1 for s in seq if s.get("act") == "cover" and s.get("p") is not None and float(s["p"]) < 0.9)
    if mute_v / n >= 0.4 and mute_a / n >= 0.3 and play_g / n >= 0.5:
        return "boundary_late"
    if mute_v / n >= 0.5 and play_g / n >= 0.5:
        return "soft_gold_or_vision_ad"
    if hang / n >= 0.4 and cover / n >= 0.5:
        return "hangover"
    if high_p / n >= 0.5 and play_g / n >= 0.5 and mute_v / n < 0.3 and mute_a / n < 0.3:
        return "true_acoustic_fp"
    return "mixed_review"


def triage_session(session: str) -> dict[str, Any]:
    hops = _load_hops(session)
    by_t = {round(float(h["t"]), 1): h for h in hops}
    disag = [h for h in hops if h.get("disagreement")]
    eps = _episodes([float(h["t"]) for h in disag])
    episodes = []
    for a, b in eps:
        # Keep every disagree run (incl. 1–2s) for human You labeling in the viewer.
        if b - a + 1 < 1:
            continue
        seq = []
        for t in range(int(a), int(b) + 1):
            h = by_t.get(float(t))
            if not h:
                continue
            ch = h.get("channels") or {}
            v = ch.get("vision") or {}
            asr = ch.get("asr") or {}
            ac = ch.get("acoustic") or {}
            g = ch.get("gold") or {}
            seq.append(
                {
                    "t": t,
                    "v": v.get("class") or v.get("acoustic_bucket"),
                    "vb": v.get("acoustic_bucket"),
                    "a": asr.get("lexicon") or asr.get("acoustic_bucket"),
                    "ab": asr.get("acoustic_bucket"),
                    "p": ac.get("p"),
                    "act": ac.get("action"),
                    "fp": ac.get("force_play"),
                    "g": g.get("bucket"),
                    "still": v.get("still_name"),
                    # Keep enough caption for guide-chrome detection (search bar / Streamers UI).
                    "visual": (v.get("visual") or "")[:320],
                    "asr": (asr.get("text") or "")[:80],
                }
            )
        tag = _tag_episode(seq)
        # still-run story every ~2s
        story = seq[:: max(1, len(seq) // 10)]
        episodes.append(
            {
                "t0": a,
                "t1": b,
                "len_s": round(b - a + 1, 1),
                "tag": tag,
                "action": _action_for_tag(tag, session, a, b, seq),
                "story": [
                    {
                        "t": s["t"],
                        "still": s["still"],
                        "vision": s["v"],
                        "asr": s["a"],
                        "acoustic": s["act"],
                        "p": s["p"],
                        "gold": s["g"],
                        "visual": s["visual"],
                    }
                    for s in story
                ],
            }
        )
    return {
        "session": session,
        "n_disagree_hops": len(disag),
        "n_episodes": len(episodes),
        "episodes": episodes,
        "tag_counts": _count_tags(episodes),
    }


def _count_tags(episodes: list[dict[str, Any]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for e in episodes:
        out[e["tag"]] = out.get(e["tag"], 0) + 1
    return out


def _action_for_tag(tag: str, session: str, t0: float, t1: float, seq: list[dict[str, Any]]) -> dict[str, Any]:
    if tag == "streamers_guide":
        return {
            "do": "drop_guide",
            "detail": "Streamers guide/UI chrome (picture caption) — exclude from muter train; channel-change junk",
            "patch_id": None,
        }
    if tag == "boundary_late" and session.endswith("1339Z_pluto_cbs_sports_hq") and t0 <= 30 <= t1:
        return {
            "do": "fix_gold_boundary",
            "detail": "Chase L-wrap: cut soccer program at 27s; non_broadcast from 27–60",
            "patch_id": "1339_chase_27",
        }
    if tag == "true_acoustic_fp" and session.endswith("1339Z_pluto_cbs_sports_hq") and 59 <= t0 <= 65 and t1 >= 75:
        # subway/office creative before GEICO — soft gold
        return {
            "do": "fix_gold_soft_ad",
            "detail": "60–80 labeled program but stills are spot creative; retag 62–80 paid_ad",
            "patch_id": "1339_pre_geico_62",
        }
    if tag == "true_acoustic_fp":
        return {
            "do": "keep_as_muter_hard_negative",
            "detail": "Stills/ASR support show; acoustic cover is live-stack FP for later train",
            "patch_id": None,
        }
    if tag == "hangover":
        return {
            "do": "controller_return_bug",
            "detail": "Sticky cover after break; do not retune on game night — measure separately",
            "patch_id": None,
        }
    return {"do": "human_review", "detail": "mixed signals — inspect still run", "patch_id": None}


def clear_patches() -> list[dict[str, Any]]:
    """Human-lock patches we will apply when --apply-clear-fixes."""
    return [
        {
            "patch_id": "1339_chase_27",
            "session": "20261110T1339Z_pluto_cbs_sports_hq",
            "ops": [
                {
                    "clip": "20261110T1339Z_pluto_cbs_sports_hq_20_40",
                    "set": {
                        "t1": 27.0,
                        "note": "Live women's soccer until Chase L-wrap; boundary fixed 20–27 (was 20–40)",
                        "human_note": "episode_triage: cut at 27s when Sapphire L-wrap starts",
                    },
                },
                {
                    "clip": "20261110T1339Z_pluto_cbs_sports_hq_40_60",
                    "set": {
                        "t0": 27.0,
                        "bucket": "paid_ad",
                        "kind": "l_wrap",
                        "note": "Chase Sapphire L-wrap from 27s (was labeled 40–60 program_mention)",
                        "human_note": "episode_triage: vision+ASR ad from ~27s",
                    },
                },
            ],
        },
        {
            "patch_id": "1339_pre_geico_62",
            "session": "20261110T1339Z_pluto_cbs_sports_hq",
            "ops": [
                {
                    "clip": "20261110T1339Z_pluto_cbs_sports_hq_60_80",
                    "set": {
                        "t0": 62.0,
                        "bucket": "paid_ad",
                        "kind": "dry_vo",
                        "note": "Spot creative (subway/office) before GEICO hump-day; was mislabeled program 60–80",
                        "human_note": "episode_triage: soft_gold → paid_ad 62–80",
                    },
                },
                {
                    # Keep a short program bridge 60–62 if soccer still true
                    "upsert_clip": {
                        "clip": "20261110T1339Z_pluto_cbs_sports_hq_60_62",
                        "bucket": "program",
                        "kind": "program_sports",
                        "confidence": "high",
                        "ask": "locked",
                        "note": "Brief soccer return before pre-GEICO spot",
                        "source": "human",
                        "human_note": "episode_triage split from 60_80",
                        "gold": True,
                        "session": "20261110T1339Z_pluto_cbs_sports_hq",
                        "t0": 60.0,
                        "t1": 62.0,
                        "locked_from": "episode_triage",
                        "channel": "(PLUTO USA) CBS Sports HQ",
                        "session_dir": r"C:\OHushData\work\capture\streamers\20261110T1339Z_pluto_cbs_sports_hq",
                    }
                },
            ],
        },
    ]


def apply_patches(patches: list[dict[str, Any]]) -> dict[str, Any]:
    label = farm_label_dir()
    key_path = label / "key.jsonl"
    rows = [json.loads(l) for l in key_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    by_clip = {str(r.get("clip")): r for r in rows}
    applied = []
    for patch in patches:
        for op in patch["ops"]:
            if "clip" in op and "set" in op:
                clip = op["clip"]
                if clip not in by_clip:
                    continue
                before = dict(by_clip[clip])
                by_clip[clip].update(op["set"])
                by_clip[clip]["ask"] = "locked"
                by_clip[clip]["gold"] = True
                by_clip[clip]["source"] = "human"
                by_clip[clip]["episode_triage_utc"] = _now()
                by_clip[clip]["episode_triage_patch"] = patch["patch_id"]
                applied.append({"patch_id": patch["patch_id"], "clip": clip, "before": before, "after": dict(by_clip[clip])})
            if "upsert_clip" in op:
                row = dict(op["upsert_clip"])
                clip = str(row["clip"])
                row["episode_triage_utc"] = _now()
                row["episode_triage_patch"] = patch["patch_id"]
                by_clip[clip] = row
                applied.append({"patch_id": patch["patch_id"], "clip": clip, "before": None, "after": row})
    # preserve order: old order then new clips
    ordered = []
    seen = set()
    for r in rows:
        c = str(r.get("clip"))
        ordered.append(by_clip[c])
        seen.add(c)
    for c, r in by_clip.items():
        if c not in seen:
            ordered.append(r)
    key_path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in ordered) + "\n", encoding="utf-8"
    )
    # Ensure new clip in GOLD_CLEAN
    clean_path = label / "GOLD_CLEAN.json"
    if clean_path.is_file():
        blob = json.loads(clean_path.read_text(encoding="utf-8"))
        clips = list(blob.get("clips") or [])
        for a in applied:
            if a["clip"] not in clips:
                clips.append(a["clip"])
        blob["clips"] = clips
        blob["n"] = len(clips)
        blob["episode_triage_utc"] = _now()
        clean_path.write_text(json.dumps(blob, indent=2) + "\n", encoding="utf-8")
    return {"ok": True, "applied_n": len(applied), "applied": applied}


def run(*, apply: bool) -> dict[str, Any]:
    reports = [triage_session(s) for s in _sessions_with_hops()]
    patch_plan = clear_patches()
    apply_receipt = None
    export_receipt = None
    scorecard = None
    if apply:
        apply_receipt = apply_patches(patch_plan)
        export_receipt = export_farm_gold(rebuild=True, clean_only=True)
        # scorecard on patched sessions only
        from .farm_live_scorecard import run as score_run, _write_report

        scorecard = score_run(clean_only=True, limit_sessions=None, use_cache=True)
        _write_report(scorecard)

    out = {
        "generated_utc": _now(),
        "applied": apply,
        "sessions": reports,
        "clear_patches": patch_plan,
        "apply_receipt": apply_receipt,
        "export": export_receipt,
        "scorecard_aggregate": (scorecard or {}).get("aggregate") if scorecard else None,
        "muter_hard_negatives": [
            {
                "session": r["session"],
                "t0": e["t0"],
                "t1": e["t1"],
                "len_s": e["len_s"],
            }
            for r in reports
            for e in r["episodes"]
            if e["tag"] == "true_acoustic_fp" and (e.get("action") or {}).get("do") == "keep_as_muter_hard_negative"
        ],
    }
    root = farm_label_dir() / "audit"
    root.mkdir(parents=True, exist_ok=True)
    (root / "EPISODE_TRIAGE.json").write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    _write_md(out, root / "EPISODE_TRIAGE.md")
    # Standing rule: Drop guide chrome out of the You-queue *and* carve it out of gold.
    try:
        from .farm_episode_viewer import auto_drop_guides_from_vision

        out["auto_drop_guides"] = auto_drop_guides_from_vision(dry_run=False)
    except Exception as exc:  # noqa: BLE001
        out["auto_drop_guides"] = {"ok": False, "error": str(exc)}
    try:
        from .farm_apply_you_marks import apply as apply_you_marks

        # Always carve current Drop marks into key.jsonl (no keep/mute upsert required).
        out["apply_you_marks"] = apply_you_marks(dry_run=False)
    except Exception as exc:  # noqa: BLE001
        out["apply_you_marks"] = {"ok": False, "error": str(exc)}
    return out


def _write_md(out: dict[str, Any], path: Path) -> None:
    lines = [
        f"# Episode triage — {out['generated_utc'][:19]}Z",
        "",
        f"applied_clear_fixes: **{out['applied']}**",
        "",
    ]
    if out.get("scorecard_aggregate"):
        agg = out["scorecard_aggregate"]
        lines.extend(
            [
                "## Scorecard after patches",
                f"- broken: `{agg.get('broken')}`",
                f"- commercial_coverage: `{agg.get('commercial_coverage')}`",
                f"- program_muted_s: `{agg.get('program_muted_s')}`",
                f"- accuracy_pct: `{agg.get('accuracy_pct')}`",
                "",
            ]
        )
    for r in out["sessions"]:
        lines.append(f"## `{r['session']}` — {r['n_episodes']} episodes / {r['n_disagree_hops']} disagree hops")
        lines.append("")
        lines.append(f"tags: `{r['tag_counts']}`")
        lines.append("")
        for e in r["episodes"]:
            lines.append(
                f"### t={e['t0']}–{e['t1']} ({e['len_s']}s) — `{e['tag']}` → {e['action']['do']}"
            )
            lines.append(f"- {e['action']['detail']}")
            lines.append("- still run:")
            for s in e["story"]:
                lines.append(
                    f"  - t={s['t']} `{s['still']}` vis={s['vision']} asr={s['asr']} "
                    f"{s['acoustic']} p={s['p']} gold={s['gold']}"
                )
            lines.append("")
    lines.extend(
        [
            "## Muter hard-negatives (confirmed show, acoustic cover)",
            "",
        ]
    )
    for hn in out.get("muter_hard_negatives") or []:
        lines.append(f"- `{hn['session']}` t={hn['t0']}–{hn['t1']} ({hn['len_s']}s)")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Episode triage + clear gold boundary fixes")
    p.add_argument("--apply-clear-fixes", action="store_true")
    args = p.parse_args(argv)
    out = run(apply=bool(args.apply_clear_fixes))
    print(
        json.dumps(
            {
                "ok": True,
                "applied": out["applied"],
                "md": str(farm_label_dir() / "audit" / "EPISODE_TRIAGE.md"),
                "tag_summary": {r["session"]: r["tag_counts"] for r in out["sessions"]},
                "scorecard": out.get("scorecard_aggregate"),
                "hard_negatives_n": len(out.get("muter_hard_negatives") or []),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
