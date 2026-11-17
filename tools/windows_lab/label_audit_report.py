"""One-shot label audit report → farm_labels/LABEL_AUDIT.*"""

from __future__ import annotations

import json
import re
import wave
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from tools.windows_lab.coverage_farm import farm_label_dir
from tools.windows_lab.farm_resources import memory_snapshot

AD = re.compile(
    r"\b("
    r"geico|mitsubishi|financing|hump day|sapphire|percent|apr|outlander|"
    r"draft\s*kings|fanduel|oxy-?clean|no win no fee|limited time|order now|"
    r"buy now|credit card|insurance company|psoriatic|lerner\s*&?\s*rowe"
    r")\b",
    re.I,
)
SPORT = re.compile(
    r"\b("
    r"touchdown|scorebug|quarterback|basketball|soccer|kickoff|final score|"
    r"yard line|halftime|play[- ]by[- ]play|first down|inning|referee"
    r")\b",
    re.I,
)
SPORT_VIS = re.compile(
    r"\b(soccer|football|basketball|scorebug|scoreboard|stadium|players? on the)\b",
    re.I,
)


def main() -> int:
    label = farm_label_dir()
    keys = {
        json.loads(l)["clip"]: json.loads(l)
        for l in (label / "key.jsonl").read_text(encoding="utf-8").splitlines()
        if l.strip()
    }
    queue = {
        json.loads(l)["clip"]: json.loads(l)
        for l in (label / "queue.jsonl").read_text(encoding="utf-8").splitlines()
        if l.strip() and "clip" in l
    }
    judgments: dict = {}
    jp = label / "take_judgments.json"
    if jp.is_file():
        judgments = json.loads(jp.read_text(encoding="utf-8"))

    asks = Counter(str(k.get("ask")) for k in keys.values())
    buckets = Counter(str(k.get("bucket")) for k in keys.values())
    confs = Counter(str(k.get("confidence")) for k in keys.values() if k.get("ask") == "review")

    contra: list[dict] = []
    empty_evidence: list[dict] = []
    stills_disagree: list[dict] = []
    missing_wav: list[str] = []
    missing_still: list[str] = []
    short_clip: list[dict] = []
    easy_ad_uncertain: list[dict] = []
    easy_sport_uncertain: list[dict] = []
    high_paid: list[dict] = []
    wav_checked = 0
    wav_ok = 0

    for clip, k in keys.items():
        ask = str(k.get("ask") or "")
        bucket = str(k.get("bucket") or "")
        conf = str(k.get("confidence") or "")
        text = str(k.get("whisper_text") or "")
        vis = str(k.get("visual_text") or "")
        why = str(k.get("why") or "")
        q = queue.get(clip) or {}
        sd = Path(str(q.get("session_dir") or ""))

        if ask == "needs_human" and why == "no_transcript_and_no_visual":
            empty_evidence.append(
                {
                    "clip": clip,
                    "session": k.get("session") or q.get("session"),
                    "t0": k.get("t0") if k.get("t0") is not None else q.get("t0"),
                    "t1": k.get("t1") if k.get("t1") is not None else q.get("t1"),
                    "wav_exists": (sd / "audio.wav").is_file() if sd.is_dir() else False,
                    "still_exists": bool(k.get("still") and Path(str(k["still"])).is_file()),
                }
            )
        if ask == "needs_human" and "stills_disagree" in why:
            stills_disagree.append(
                {
                    "clip": clip,
                    "session": k.get("session") or q.get("session"),
                    "has_asr": bool(text.strip()),
                    "whisper": text[:120],
                }
            )

        if ask in {"review", "locked"}:
            if bucket == "program" and AD.search(text) and not SPORT.search(text):
                contra.append(
                    {
                        "type": "ad_speech_but_program",
                        "clip": clip,
                        "confidence": conf,
                        "ask": ask,
                        "whisper": text[:140],
                    }
                )
            if bucket == "paid_ad" and SPORT.search(text) and not AD.search(text) and SPORT_VIS.search(vis):
                contra.append(
                    {
                        "type": "sports_but_paid_ad",
                        "clip": clip,
                        "confidence": conf,
                        "ask": ask,
                        "whisper": text[:140],
                    }
                )
            if bucket == "uncertain" and AD.search(text) and not SPORT.search(text):
                easy_ad_uncertain.append(
                    {"clip": clip, "confidence": conf, "whisper": text[:140], "why": why[:100]}
                )
            if bucket == "uncertain" and (SPORT.search(text) or SPORT_VIS.search(vis)) and not AD.search(text):
                easy_sport_uncertain.append(
                    {"clip": clip, "confidence": conf, "whisper": text[:100], "visual": vis[:80], "why": why[:80]}
                )

        if ask == "review" and bucket == "paid_ad" and conf == "high":
            high_paid.append(
                {
                    "clip": clip,
                    "session": k.get("session") or q.get("session"),
                    "why": why[:120],
                    "whisper": text[:100],
                    "has_visual": bool(vis.strip()),
                }
            )

        # Media health (all help asks)
        if ask in {"review", "needs_human"}:
            if not sd.is_dir() or not (sd / "audio.wav").is_file():
                missing_wav.append(clip)
            st = k.get("still")
            if st and not Path(str(st)).is_file():
                missing_still.append(clip)
            t0 = k.get("t0") if k.get("t0") is not None else q.get("t0")
            t1 = k.get("t1") if k.get("t1") is not None else q.get("t1")
            try:
                if t0 is not None and t1 is not None and float(t1) - float(t0) < 3.0:
                    short_clip.append({"clip": clip, "dur": float(t1) - float(t0), "ask": ask})
            except (TypeError, ValueError):
                pass

    # Spot-check wav open on empty-evidence sample
    for row in empty_evidence[:40]:
        q = queue.get(row["clip"]) or {}
        sd = Path(str(q.get("session_dir") or ""))
        wav = sd / "audio.wav"
        wav_checked += 1
        if not wav.is_file():
            continue
        try:
            with wave.open(str(wav), "rb") as w:
                dur = w.getnframes() / float(w.getframerate() or 1)
            row["take_dur_s"] = round(dur, 1)
            wav_ok += 1
        except Exception as exc:  # noqa: BLE001
            row["wav_error"] = str(exc)

    # Human vs model from audit
    prior_agree = prior_disagree = 0
    prior_rows: list[dict] = []
    audit = label / "label_draft.jsonl"
    if audit.is_file():
        for line in audit.open(encoding="utf-8"):
            if not line.strip():
                continue
            r = json.loads(line)
            if not str(r.get("tick_id") or "").startswith("human:"):
                continue
            if not r.get("prior_bucket"):
                continue
            ok = r.get("prior_bucket") == r.get("bucket")
            if ok:
                prior_agree += 1
            else:
                prior_disagree += 1
            prior_rows.append(
                {
                    "clip": r.get("clip"),
                    "model": r.get("prior_bucket"),
                    "human": r.get("bucket"),
                    "match": ok,
                }
            )

    human_n = sum(1 for j in judgments.values() if (j.get("regions") or []))
    batch_active = sum(1 for r in queue.values() if r.get("review_batch") == "active")
    batch_parked = sum(1 for r in queue.values() if r.get("review_batch") == "parked")

    payload = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "memory": {k: memory_snapshot().get(k) for k in ("avail_gb", "load_pct", "allow_label")},
        "counts": {
            "key_n": len(keys),
            "queue_n": len(queue),
            "asks": dict(asks),
            "buckets": dict(buckets),
            "review_confidence": dict(confs),
            "has_model": sum(1 for k in keys.values() if k.get("model")),
            "human_judgments": human_n,
            "morning_active": batch_active,
            "morning_parked": batch_parked,
        },
        "findings": {
            "contradictions": {
                "n": len(contra),
                "by_type": dict(Counter(c["type"] for c in contra)),
                "rows": contra[:50],
            },
            "empty_evidence_needs_human": {
                "n": len(empty_evidence),
                "wav_spotcheck_ok": wav_ok,
                "wav_spotcheck_n": wav_checked,
                "note": "WAV often exists; ASR+vision returned empty for the window — process gap, not missing file.",
                "rows": empty_evidence[:40],
            },
            "stills_disagree_needs_human": {
                "n": len(stills_disagree),
                "with_asr": sum(1 for r in stills_disagree if r.get("has_asr")),
                "rows": stills_disagree[:30],
            },
            "uncertain_but_clear_ad_lexicon": {
                "n": len(easy_ad_uncertain),
                "rows": easy_ad_uncertain[:40],
            },
            "uncertain_but_clear_sports": {
                "n": len(easy_sport_uncertain),
                "rows": easy_sport_uncertain[:40],
            },
            "high_paid_ad_review_easy_confirms": {
                "n": len(high_paid),
                "rows": high_paid[:50],
            },
            "missing_wav": {"n": len(missing_wav), "clips": missing_wav[:30]},
            "missing_still_path": {"n": len(missing_still), "clips": missing_still[:30]},
            "very_short_clips_lt_3s": {"n": len(short_clip), "rows": short_clip[:30]},
            "human_vs_model_audit_locks": {
                "agree": prior_agree,
                "disagree": prior_disagree,
                "n": prior_agree + prior_disagree,
                "rows": prior_rows,
            },
        },
        "owner_actions": [
            f"Clear ~{len(high_paid)} high paid_ad reviews at /farm first (easy gold).",
            f"Re-draft or rescue ~{len(easy_sport_uncertain)} uncertain clips with clear sports cues.",
            f"Investigate {len(empty_evidence)} needs_human with empty ASR/visual despite wav on disk.",
            f"Soft-handle {len(stills_disagree)} stills_disagree (many have ASR) — don't park as top batch.",
            "Only " + str(prior_agree + prior_disagree) + " human↔model audited locks — keep labeling to measure accuracy.",
        ],
    }

    json_path = label / "LABEL_AUDIT.json"
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    f = payload["findings"]
    lines = [
        f"# Label audit — {payload['generated_utc'][:19]}Z",
        "",
        "## Snapshot",
        f"- key: **{payload['counts']['key_n']}** · queue: **{payload['counts']['queue_n']}**",
        f"- asks: `{payload['counts']['asks']}`",
        f"- model-scored: **{payload['counts']['has_model']}** · human judgments: **{human_n}**",
        f"- morning batch: **{batch_active}** active / **{batch_parked}** parked",
        "",
        "## Errors / suspects",
        f"- Lexicon contradictions: **{f['contradictions']['n']}** `{f['contradictions']['by_type']}`",
        f"- `needs_human` empty ASR+visual: **{f['empty_evidence_needs_human']['n']}** "
        f"(wav spotcheck {wav_ok}/{wav_checked} open OK)",
        f"- `needs_human` stills_disagree: **{f['stills_disagree_needs_human']['n']}** "
        f"({f['stills_disagree_needs_human']['with_asr']} have ASR)",
        f"- Uncertain but clear **ad** lexicon: **{f['uncertain_but_clear_ad_lexicon']['n']}**",
        f"- Uncertain but clear **sports**: **{f['uncertain_but_clear_sports']['n']}**",
        f"- High paid_ad review (easy confirms): **{f['high_paid_ad_review_easy_confirms']['n']}**",
        f"- Missing wav: **{f['missing_wav']['n']}** · missing still path: **{f['missing_still_path']['n']}**",
        f"- Clips < 3s: **{f['very_short_clips_lt_3s']['n']}**",
        "",
        "## Accuracy so far (tiny)",
        f"- Human lock vs model prior: **{prior_agree} agree / {prior_disagree} disagree** "
        f"(n={prior_agree + prior_disagree})",
        "",
        "## Owner actions",
    ]
    for a in payload["owner_actions"]:
        lines.append(f"- {a}")
    lines.extend(
        [
            "",
            "## Sample contradictions",
        ]
    )
    for row in contra[:15]:
        lines.append(
            f"- `{row['type']}` · `{row['clip']}` · {row.get('confidence')} — {(row.get('whisper') or '')[:90]}"
        )
    lines.extend(["", "## Sample empty-evidence (wav often present)", ""])
    for row in empty_evidence[:12]:
        lines.append(
            f"- `{row['clip']}` wav={row.get('wav_exists')} still={row.get('still_exists')} "
            f"t={row.get('t0')}-{row.get('t1')}"
        )
    lines.extend(["", f"Full JSON: `{json_path}`", ""])
    md_path = label / "LABEL_AUDIT.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"ok": True, "md": str(md_path), "json": str(json_path), "summary": payload["findings"]["contradictions"]["by_type"], "empty": len(empty_evidence), "stills_disagree": len(stills_disagree), "high_paid": len(high_paid), "easy_sport": len(easy_sport_uncertain), "easy_ad": len(easy_ad_uncertain)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
