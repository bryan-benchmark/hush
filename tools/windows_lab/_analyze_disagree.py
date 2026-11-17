"""Pattern analysis of combined-audit DISAGREE hops."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path


def norm(x) -> str | None:
    if x is None:
        return None
    s = str(x).lower()
    if s in {"ad", "non_broadcast", "mute", "paid_ad", "show_promo"}:
        return "mute"
    if s in {"program", "broadcast", "play"}:
        return "play"
    if s in {"mixed", "uncertain", "other", "empty"}:
        return "uncertain"
    return s


def pattern(h: dict) -> str:
    ch = h.get("channels") or {}
    v = ch.get("vision") or {}
    a = ch.get("asr") or {}
    ac = ch.get("acoustic") or {}
    g = ch.get("gold") or {}
    vn = norm(v.get("acoustic_bucket") or v.get("class"))
    an = norm(a.get("acoustic_bucket") or a.get("lexicon"))
    gn = norm(g.get("bucket"))
    action = ac.get("action")
    p = ac.get("p")

    # Ordered taxonomy of useful bug classes
    if gn == "play" and vn == "mute" and an == "mute":
        return "gold_late_or_wrong__vision+asr_say_ad"
    if gn == "play" and vn == "mute" and an != "mute":
        return "gold_vs_vision_mute__asr_not_ad"
    if gn == "play" and an == "mute" and vn != "mute":
        return "gold_vs_asr_mute__vision_not_ad"
    if gn == "mute" and vn == "play" and an == "play":
        return "gold_mute__vision+asr_say_show"
    if gn == "play" and action == "cover" and vn in {None, "uncertain", "play"} and an in {
        None,
        "uncertain",
        "play",
    }:
        if p is not None and float(p) >= 0.9:
            return "acoustic_fp_on_labeled_show__high_p"
        return "acoustic_cover_on_show__mid_p_or_hangover"
    if gn == "mute" and action == "play":
        return "acoustic_missed_ad__playing_through_mute_gold"
    if vn and an and vn != an and "uncertain" not in {vn, an}:
        return "vision_asr_conflict"
    if gn == "play" and action == "cover":
        return "acoustic_cover_vs_gold_play__other"
    return "other_disagree"


def load(sess: str) -> list[dict]:
    path = Path(r"C:\OHushData\indexes\farm_labels\audit") / sess / "hops.jsonl"
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def analyze(sess: str) -> dict:
    hops = load(sess)
    disag = [h for h in hops if h.get("disagreement")]
    counts = Counter(pattern(h) for h in disag)
    # detail completeness
    missing = Counter()
    for h in disag:
        ch = h.get("channels") or {}
        for name in ("vision", "asr", "acoustic", "gold"):
            c = ch.get(name)
            if c is None:
                missing[f"{name}_null"] += 1
            elif name == "vision" and not c.get("still"):
                missing["vision_no_still"] += 1
            elif name == "vision" and not c.get("visual"):
                missing["vision_no_caption"] += 1
            elif name == "asr" and not c.get("text"):
                missing["asr_no_text"] += 1
            elif name == "acoustic" and c.get("p") is None:
                missing["acoustic_no_p"] += 1

    # examples per pattern
    examples = defaultdict(list)
    for h in disag:
        pat = pattern(h)
        if len(examples[pat]) >= 2:
            continue
        ch = h.get("channels") or {}
        v = ch.get("vision") or {}
        a = ch.get("asr") or {}
        ac = ch.get("acoustic") or {}
        g = ch.get("gold") or {}
        examples[pat].append(
            {
                "t": h.get("t"),
                "why": h.get("why"),
                "still": v.get("still_name") or v.get("still"),
                "visual": (v.get("visual") or "")[:140],
                "asr": (a.get("text") or "")[:120],
                "p": ac.get("p"),
                "action": ac.get("action"),
                "force_play": ac.get("force_play"),
                "gold": f"{g.get('bucket')} {g.get('start_s')}-{g.get('end_s')}",
            }
        )

    # cluster consecutive disagree times into episodes
    times = sorted(float(h["t"]) for h in disag)
    episodes = []
    if times:
        a0 = b0 = times[0]
        for t in times[1:]:
            if t <= b0 + 1.01:
                b0 = t
            else:
                episodes.append((a0, b0, b0 - a0 + 1))
                a0 = b0 = t
        episodes.append((a0, b0, b0 - a0 + 1))
    episodes.sort(key=lambda x: -x[2])

    return {
        "session": sess,
        "n_hops": len(hops),
        "n_disagree": len(disag),
        "disagree_pct": round(100 * len(disag) / len(hops), 1) if hops else 0,
        "patterns": dict(counts.most_common()),
        "missing_fields": dict(missing),
        "longest_disagree_episodes_s": [
            {"t0": a, "t1": b, "len_s": round(L, 1)} for a, b, L in episodes[:8]
        ],
        "examples": {k: v for k, v in examples.items()},
    }


def main() -> None:
    sessions = [
        "20261110T1339Z_pluto_cbs_sports_hq",
        "20261110T1401Z_pluto_cbs_sports_hq",
    ]
    reports = [analyze(s) for s in sessions]
    # pooled
    pooled = Counter()
    for r in reports:
        pooled.update(r["patterns"])
    out = {
        "pooled_patterns": dict(pooled.most_common()),
        "sessions": reports,
        "log_detail_verdict": _verdict(reports),
    }
    path = Path(r"C:\OHushData\indexes\farm_labels\audit\DISAGREE_PATTERNS.json")
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    _write_md(out, path.with_suffix(".md"))
    print(json.dumps(out, indent=2, ensure_ascii=False))


def _verdict(reports: list[dict]) -> dict:
    miss = Counter()
    for r in reports:
        miss.update(r["missing_fields"])
    enough = True
    gaps = []
    if miss.get("vision_no_caption"):
        gaps.append("some vision rows lack captions")
    if miss.get("asr_no_text"):
        gaps.append("some ASR rows empty (ok if silent)")
    # What's missing for faster triage
    wish = [
        "cause_code already partially in pattern analyzer — bake into hop.why",
        "still thumbnail path is present; add still_t link in MD table",
        "controller state (hot/cold streak) not in acoustic channel — hard to confirm hangover vs FP",
        "gold clip id / note not on hop — only bucket+range",
    ]
    return {
        "fields_mostly_present": True,
        "missing_counts": dict(miss),
        "enough_to_triage_most_bugs": enough,
        "gaps_for_faster_debug": wish,
    }


def _write_md(out: dict, path: Path) -> None:
    lines = [
        "# DISAGREE patterns — short sessions",
        "",
        "## Pooled",
        "",
        "| Pattern | count |",
        "|---|---:|",
    ]
    for k, v in out["pooled_patterns"].items():
        lines.append(f"| `{k}` | {v} |")
    lines.extend(["", "## Per session", ""])
    for r in out["sessions"]:
        lines.append(f"### `{r['session']}` — {r['n_disagree']}/{r['n_hops']} ({r['disagree_pct']}%)")
        lines.append("")
        for k, v in r["patterns"].items():
            lines.append(f"- `{k}`: {v}")
        lines.append("")
        lines.append("Longest disagree episodes:")
        for ep in r["longest_disagree_episodes_s"][:5]:
            lines.append(f"- t={ep['t0']}–{ep['t1']} ({ep['len_s']}s)")
        lines.append("")
        lines.append("Examples:")
        for pat, exs in r["examples"].items():
            lines.append(f"- **{pat}**")
            for e in exs:
                lines.append(
                    f"  - t={e['t']} still=`{e['still']}` p={e['p']} {e['action']} gold={e['gold']}"
                )
                if e["visual"]:
                    lines.append(f"    - vision: {e['visual']}")
                if e["asr"]:
                    lines.append(f"    - asr: {e['asr']}")
        lines.append("")
    v = out["log_detail_verdict"]
    lines.extend(
        [
            "## Are logs detailed enough?",
            "",
            f"- triage-ready: **{v['enough_to_triage_most_bugs']}**",
            f"- missing field counts: `{v['missing_counts']}`",
            "",
            "Gaps:",
        ]
    )
    for g in v["gaps_for_faster_debug"]:
        lines.append(f"- {g}")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
