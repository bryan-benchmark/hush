"""Emit atomic combined log for farm live scorecard review."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from tools.windows_lab.coverage_farm import farm_label_dir
from tools.windows_lab.farm_draft import transcript_for_window
from tools.windows_lab.farm_live_scorecard import (
    HOP_S,
    OFF,
    ON,
    PLAY_WANT,
    MUTE_WANT,
    _cover_ranges,
    _infer_session,
    _load_models,
    _device,
    _overlap,
    load_gold_clips,
)


def _keys() -> dict[str, dict]:
    path = farm_label_dir() / "key.jsonl"
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("clip"):
            out[str(row["clip"])] = row
    return out


def main() -> int:
    label = farm_label_dir()
    scorecard = json.loads((label / "LIVE_SCORECARD.json").read_text(encoding="utf-8"))
    keys = _keys()
    gold = {c["clip"]: c for c in load_gold_clips(clean_only=True)}

    # Pick review set: all program mutes + all ad misses/partials + a few clean ad hits
    review_clips: list[dict] = []
    seen = set()
    for s in scorecard["sessions"]:
        if "clips" not in s:
            continue
        for c in s["clips"]:
            want = False
            if c["role"] == "play" and float(c["covered_s"]) > 0:
                want = True
            if c["role"] == "mute" and (not c["ok"] or float(c["frac_covered"]) < 0.95):
                want = True
            if want and c["clip"] not in seen:
                seen.add(c["clip"])
                review_clips.append({**c, "session": s["session"], "session_dir": s["session_dir"]})

    # Add up to 5 clean full ad hits for contrast
    clean_ads = []
    for s in scorecard["sessions"]:
        for c in s.get("clips") or []:
            if c["role"] == "mute" and c["ok"] and float(c["frac_covered"]) >= 0.95:
                clean_ads.append({**c, "session": s["session"], "session_dir": s["session_dir"]})
    clean_ads.sort(key=lambda x: -float(x["covered_s"]))
    for c in clean_ads[:5]:
        if c["clip"] not in seen:
            seen.add(c["clip"])
            review_clips.append(c)

    review_clips.sort(key=lambda x: (x["session"], float(x["t0"])))

    # Group by session and re-run controller from cache for hop-level lines
    by_sess: dict[str, list[dict]] = {}
    for c in review_clips:
        by_sess.setdefault(c["session"], []).append(c)

    device = _device()
    encoder, head, _, _ = _load_models(device)
    cache_dir = label / "live_scorecard_cache"

    lines: list[str] = []
    lines.append("# Farm live scorecard — atomic combined log")
    lines.append("")
    lines.append(f"Generated from `{label / 'LIVE_SCORECARD.json'}`")
    lines.append("Stack: frame_mn10 + frozen_head + LiveController 0.90/0.50 × 8/2 + 8s cooldown")
    lines.append("")
    lines.append("Legend:")
    lines.append("- WANT_MUTE / WANT_PLAY = human gold role for that clip")
    lines.append("- COVER / PLAY = live muter action at that hop")
    lines.append("- p = P(commercial); cover needs p≥0.90 for 8 hops; return p≤0.50 for 2 hops")
    lines.append("- FALSE_MUTE = covered while gold says play")
    lines.append("- AD_HELD / AD_LEAK = covered / playing while gold says mute")
    lines.append("")

    for session, clips in by_sess.items():
        sd = Path(clips[0]["session_dir"])
        wav = sd / "audio.wav"
        t_end = max(float(c["t1"]) for c in clips) + 4.0
        # Also need session max from scorecard session for cache consistency
        sess_row = next(s for s in scorecard["sessions"] if s["session"] == session)
        t_end = max(t_end, float(max(c["t1"] for c in sess_row["clips"])) + 4.0)
        cache_path = cache_dir / f"{session}.npz"
        times, probs, decisions = _infer_session(
            wav, t_end, encoder, head, device, cache_path=cache_path
        )
        cover = _cover_ranges(decisions, (0.0, float(max(c["t1"] for c in sess_row["clips"]))))
        # index decisions by time
        dec_by_t = {round(float(d["available_at"]), 3): d for d in decisions}

        lines.append("---")
        lines.append(f"## Session `{session}`")
        lines.append(f"wav: `{wav}`")
        lines.append(
            f"session score: mute_cov={sess_row.get('commercial_coverage')} "
            f"program_muted_s={sess_row.get('program_muted_s')} broken={sess_row.get('broken')}"
        )
        lines.append("")

        for c in clips:
            t0, t1 = float(c["t0"]), float(c["t1"])
            key = keys.get(c["clip"], {})
            g = gold.get(c["clip"], {})
            note = str(key.get("note") or key.get("human_note") or "")[:140]
            role = c["role"]
            want = "WANT_MUTE" if role == "mute" else "WANT_PLAY"
            verdict = (
                "FALSE_MUTE"
                if role == "play" and float(c["covered_s"]) > 0
                else (
                    "AD_HELD"
                    if role == "mute" and float(c["frac_covered"]) >= 0.95
                    else ("AD_PARTIAL" if role == "mute" and float(c["covered_s"]) > 0 else "AD_LEAK")
                )
            )
            # transcript snippet (context only — not used by the muter)
            text = ""
            tr_path = sd / "farm_transcript.json"
            if tr_path.is_file():
                try:
                    tr = json.loads(tr_path.read_text(encoding="utf-8"))
                    text = transcript_for_window(tr, t0, t1).replace("\n", " ")[:180]
                except Exception as exc:  # noqa: BLE001
                    text = f"(transcript err: {exc})"

            lines.append(
                f"### [{verdict}] {want} `{c['clip']}`  t={t0:.1f}–{t1:.1f}s  "
                f"bucket={c['bucket']}  covered={c['covered_s']}s ({100*float(c['frac_covered']):.0f}%)"
            )
            if note:
                lines.append(f"- gold note: {note}")
            if text:
                lines.append(f"- ASR: {text}")
            lines.append("- hops (1 every 0.25s inside clip; show action changes + extremes):")

            # Collect hops inside clip
            hops = []
            for d in decisions:
                t = float(d["available_at"])
                if t < t0 - 1e-6 or t > t1 + 1e-6:
                    continue
                hops.append(d)

            if not hops:
                lines.append("  (no hops in range)")
                lines.append("")
                continue

            # Compress: emit when action changes, or every 1s, always first/last
            prev_action = None
            last_emitted_t = None
            for i, d in enumerate(hops):
                t = float(d["available_at"])
                action = d["action"]
                p = float(d["probability"])
                change = action != prev_action
                boundary = i == 0 or i == len(hops) - 1
                one_sec = last_emitted_t is None or (t - last_emitted_t) >= 0.999
                extreme = p >= ON or p <= OFF
                if not (change or boundary or one_sec or extreme):
                    continue
                tag = "COVER" if action == "cover" else "PLAY "
                flag = ""
                if role == "play" and action == "cover":
                    flag = "  << FALSE_MUTE"
                elif role == "mute" and action == "play":
                    flag = "  << AD_AUDIBLE"
                fp = " force_play" if d.get("force_play") else ""
                lines.append(f"  t={t:7.2f}  p={p:.3f}  {tag}{fp}{flag}")
                prev_action = action
                last_emitted_t = t
            lines.append("")

    out_md = label / "LIVE_SCORECARD_ATOMIC.md"
    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "path": str(out_md), "clips": len(review_clips), "sessions": len(by_sess)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
