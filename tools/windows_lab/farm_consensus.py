"""Multichannel consensus → auto gold locks; disagrees stay for /verdict.

Voters (when present):
  vision, ASR, acoustic (live muter). Gold is an output of consensus on raw
  tape, not a fourth independent detector.

Agree (mute/play) → write ask=locked into key.jsonl (source=multichannel_consensus).
Disagree / uncertain → leave farm review rows alone; episode triage feeds /verdict.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .coverage_farm import farm_label_dir, streamers_capture_root
from .farm_label_audit import append_draft_events, atomic_write_jsonl
from .farm_ontology import BROADCAST, NON_BROADCAST

CONSENSUS_SOURCE = "multichannel_consensus"
# Vision hops are often 5s; allow merge across that spine (+slack).
HOP_MERGE_GAP_S = 6.0

# Desk cache for channel-agreement rollup (hops scan is ~seconds).
_AGREE_CACHE: dict[str, Any] = {"sig": None, "payload": None}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file() or path.stat().st_size == 0:
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def norm_vote(x: Any) -> str | None:
    if x is None:
        return None
    s = str(x).lower()
    if s in {"ad", "non_broadcast", "mute", "paid_ad", "show_promo", "cover"}:
        return "mute"
    if s in {"program", "broadcast", "play"}:
        return "play"
    if s in {"mixed", "uncertain", "other", ""}:
        return "uncertain"
    return s


def prepared_sessions(root: Path | None = None) -> list[str]:
    """Short session ids under work/capture/streamers with audio + label_manifest."""
    cap = streamers_capture_root(root)
    if not cap.is_dir():
        return []
    out: list[str] = []
    for d in sorted(cap.iterdir()):
        if not d.is_dir():
            continue
        if not (d / "label_manifest.json").is_file():
            continue
        if not (d / "audio.wav").is_file():
            continue
        out.append(d.name)
    return out


def _hop_votes(hop: dict[str, Any]) -> dict[str, str | None]:
    ch = hop.get("channels") or {}
    votes = hop.get("votes") or {}
    vision = votes.get("vision")
    asr = votes.get("asr")
    if vision is None and isinstance(ch.get("vision"), dict):
        v = ch["vision"]
        vision = v.get("acoustic_bucket") or v.get("class")
    if asr is None and isinstance(ch.get("asr"), dict):
        a = ch["asr"]
        asr = a.get("acoustic_bucket") or a.get("lexicon")
    ac_action = votes.get("acoustic_action")
    if ac_action is None and isinstance(ch.get("acoustic"), dict):
        ac_action = ch["acoustic"].get("action")
    return {
        "vision": norm_vote(vision),
        "asr": norm_vote(asr),
        "acoustic": norm_vote(ac_action),
    }


def consensus_at_hop(hop: dict[str, Any]) -> dict[str, Any]:
    """Return {label: mute|play|None, why, disagree, voters}."""
    v = _hop_votes(hop)
    voters = {k: val for k, val in v.items() if val in {"mute", "play"}}
    if len(voters) < 2:
        return {
            "label": None,
            "disagree": False,
            "why": "need_2_voters",
            "voters": v,
        }
    labels = set(voters.values())
    if len(labels) > 1:
        return {
            "label": None,
            "disagree": True,
            "why": "voter_conflict:" + ",".join(f"{k}={voters[k]}" for k in sorted(voters)),
            "voters": v,
        }
    label = next(iter(labels))
    # Soft check: if a third voter exists and conflicts, treat as disagree.
    for name, val in v.items():
        if name in voters:
            continue
        if val in {"mute", "play"} and val != label:
            return {
                "label": None,
                "disagree": True,
                "why": f"third_voter_conflict:{name}={val}",
                "voters": v,
            }
    return {
        "label": label,
        "disagree": False,
        "why": "agree:" + ",".join(f"{k}={voters[k]}" for k in sorted(voters)),
        "voters": v,
    }


def _infer_hop_s(times: list[float]) -> float:
    if len(times) < 2:
        return 5.0
    deltas = sorted(t1 - t0 for t0, t1 in zip(times, times[1:]) if t1 > t0)
    if not deltas:
        return 5.0
    mid = deltas[len(deltas) // 2]
    return float(mid if mid > 0.5 else 5.0)


def _merge_ranges(
    points: list[tuple[float, str, str]],
) -> list[dict[str, Any]]:
    """Merge consecutive same-label hop times into [t0,t1) ranges."""
    if not points:
        return []
    points = sorted(points, key=lambda x: x[0])
    hop_s = _infer_hop_s([p[0] for p in points])
    gap = max(HOP_MERGE_GAP_S, hop_s + 0.5)
    out: list[dict[str, Any]] = []
    t0, label, why = points[0]
    prev = t0
    whys = [why]
    for t, lab, w in points[1:]:
        if lab == label and t <= prev + gap:
            prev = t
            whys.append(w)
            continue
        out.append(
            {
                "t0": float(t0),
                "t1": float(prev + hop_s),
                "label": label,
                "why": whys[0],
            }
        )
        t0, label, why = t, lab, w
        prev = t
        whys = [why]
    out.append(
        {
            "t0": float(t0),
            "t1": float(prev + hop_s),
            "label": label,
            "why": whys[0],
        }
    )
    return out


def consensus_ranges_for_session(session: str, root: Path | None = None) -> dict[str, Any]:
    hops_path = farm_label_dir(root) / "audit" / session / "hops.jsonl"
    hops = _read_jsonl(hops_path)
    agree_pts: list[tuple[float, str, str]] = []
    disagree_n = 0
    skip_n = 0
    for h in hops:
        c = consensus_at_hop(h)
        if c["disagree"]:
            disagree_n += 1
            continue
        if not c["label"]:
            skip_n += 1
            continue
        agree_pts.append((float(h.get("t") or 0), str(c["label"]), str(c["why"])))
    ranges = _merge_ranges(agree_pts)
    return {
        "ok": hops_path.is_file(),
        "session": session,
        "n_hops": len(hops),
        "n_disagree_hops": disagree_n,
        "n_skip_hops": skip_n,
        "n_agree_hops": len(agree_pts),
        "ranges": ranges,
        "hops_path": str(hops_path),
    }


def _farm_bucket(label: str) -> tuple[str, str]:
    if label == "mute":
        return "paid_ad", "consensus_mute"
    return "program", "consensus_play"


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def apply_consensus_locks(
    session: str,
    root: Path | None = None,
    *,
    dry_run: bool = False,
    min_range_s: float = 2.0,
) -> dict[str, Any]:
    """Lock key.jsonl clips fully covered by consensus ranges; append GOLD_CLEAN."""
    label_dir = farm_label_dir(root)
    key_path = label_dir / "key.jsonl"
    queue_path = label_dir / "queue.jsonl"
    keys = {str(r.get("clip")): r for r in _read_jsonl(key_path) if r.get("clip")}
    queue = _read_jsonl(queue_path)
    summary = consensus_ranges_for_session(session, root=root)
    ranges = [
        r
        for r in summary.get("ranges") or []
        if float(r["t1"]) - float(r["t0"]) >= float(min_range_s)
    ]
    utc = _now()
    locked_clips: list[str] = []
    events: list[dict[str, Any]] = []
    new_rows: list[dict[str, Any]] = []

    session_keys = [
        (clip, row)
        for clip, row in keys.items()
        if str(row.get("session") or "") == session
        and str(row.get("ask") or "") in {"review", "needs_human", "optional_confirm", ""}
    ]

    for clip, row in session_keys:
        try:
            t0 = float(row.get("t0") if row.get("t0") is not None else 0)
            t1 = float(row.get("t1") if row.get("t1") is not None else t0)
        except (TypeError, ValueError):
            continue
        if t1 <= t0:
            continue
        span = t1 - t0
        best: dict[str, Any] | None = None
        best_cov = 0.0
        for r in ranges:
            cov = _overlap(t0, t1, float(r["t0"]), float(r["t1"])) / span
            if cov > best_cov:
                best_cov = cov
                best = r
        # Require near-full coverage so boundaries stay for verdict.
        if best is None or best_cov < 0.85:
            continue
        bucket, kind = _farm_bucket(str(best["label"]))
        prior_ask = row.get("ask")
        prior_bucket = row.get("bucket")
        locked = {
            **row,
            "clip": clip,
            "bucket": bucket,
            "kind": kind,
            "confidence": "high",
            "ask": "locked",
            "gold": True,
            "source": CONSENSUS_SOURCE,
            "model": None,
            "locked_from": CONSENSUS_SOURCE,
            "locked_utc": utc,
            "note": (str(row.get("note") or "")[:120] + f" | consensus:{best['why']}").strip(" |"),
            "human_note": f"auto consensus {best['label']} cov={best_cov:.2f}",
            "why": f"consensus:{best['why']}",
        }
        keys[clip] = locked
        locked_clips.append(clip)
        events.append(
            {
                "utc": utc,
                "clip": clip,
                "session": session,
                "t0": t0,
                "t1": t1,
                "ask": "locked",
                "bucket": bucket,
                "kind": kind,
                "confidence": "high",
                "why": locked["why"],
                "prior_ask": prior_ask,
                "prior_bucket": prior_bucket,
            }
        )

    # Synthetic range rows when no overlapping key clips (session still gets gold).
    for r in ranges:
        t0, t1 = float(r["t0"]), float(r["t1"])
        covered = any(
            _overlap(t0, t1, float(keys[c].get("t0") or 0), float(keys[c].get("t1") or 0)) > 0.5
            for c in locked_clips
            if c in keys
        )
        if covered:
            continue
        bucket, kind = _farm_bucket(str(r["label"]))
        clip = f"{session}_consensus_{int(t0)}_{int(t1)}"
        if clip in keys and keys[clip].get("ask") == "locked":
            continue
        row = {
            "clip": clip,
            "session": session,
            "session_dir": str(streamers_capture_root(root) / session),
            "t0": t0,
            "t1": t1,
            "bucket": bucket,
            "kind": kind,
            "confidence": "high",
            "ask": "locked",
            "gold": True,
            "source": CONSENSUS_SOURCE,
            "locked_from": CONSENSUS_SOURCE,
            "locked_utc": utc,
            "note": f"consensus range {r['why']}",
            "human_note": f"auto consensus {r['label']}",
            "why": f"consensus:{r['why']}",
            "slot": "consensus",
        }
        keys[clip] = row
        new_rows.append(row)
        locked_clips.append(clip)
        events.append(
            {
                "utc": utc,
                "clip": clip,
                "session": session,
                "t0": t0,
                "t1": t1,
                "ask": "locked",
                "bucket": bucket,
                "kind": kind,
                "confidence": "high",
                "why": row["why"],
            }
        )

    receipt = {
        "ok": True,
        "dry_run": dry_run,
        "session": session,
        "locked_n": len(locked_clips),
        "locked_clips": locked_clips[:40],
        "new_range_rows": len(new_rows),
        "ranges_used": len(ranges),
        "hop_summary": {
            k: summary.get(k)
            for k in ("n_hops", "n_agree_hops", "n_disagree_hops", "n_skip_hops")
        },
        "utc": utc,
    }
    if dry_run:
        return receipt

    if locked_clips:
        atomic_write_jsonl(key_path, list(keys.values()))
        append_draft_events(events, root=root, tick_id=f"consensus:{utc}")
        if queue_path.is_file():
            for row in queue:
                if str(row.get("clip")) in set(locked_clips):
                    row["ask"] = "locked"
                    row["priority"] = 99
                    row["review_batch"] = "done"
            atomic_write_jsonl(queue_path, queue)
        clean_path = label_dir / "GOLD_CLEAN.json"
        clips: list[str] = []
        blob: dict[str, Any] = {"clips": []}
        if clean_path.is_file():
            try:
                blob = json.loads(clean_path.read_text(encoding="utf-8"))
                clips = list(blob.get("clips") or [])
            except json.JSONDecodeError:
                clips = []
        for c in locked_clips:
            if c not in clips:
                clips.append(c)
        blob["clips"] = clips
        blob["n"] = len(clips)
        blob["consensus_utc"] = utc
        clean_path.write_text(json.dumps(blob, indent=2) + "\n", encoding="utf-8")

    path = farm_label_dir(root) / "audit" / session
    path.mkdir(parents=True, exist_ok=True)
    (path / "CONSENSUS_LOCK.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt


def _pct(num: int, den: int) -> float | None:
    if den <= 0:
        return None
    return round(100.0 * float(num) / float(den), 1)


def channel_agreement_stats(root: Path | None = None) -> dict[str, Any]:
    """Rollup pic/txt/snd hard-vote coverage + pairwise / 2-of-3 agreement.

    Cached on max hops.jsonl mtime so the desk can poll without re-scanning.
    """
    audit = farm_label_dir(root) / "audit"
    if not audit.is_dir():
        return {"ok": False, "error": "no audit dir", "hops_total": 0}

    hops_files = sorted(
        p for p in audit.glob("*/hops.jsonl") if p.is_file() and p.stat().st_size > 0
    )
    sig = tuple((str(p), int(p.stat().st_mtime_ns), int(p.stat().st_size)) for p in hops_files)
    cached = _AGREE_CACHE.get("payload")
    if _AGREE_CACHE.get("sig") == sig and isinstance(cached, dict):
        return dict(cached)

    present: Counter[str] = Counter()
    pair_agree: Counter[tuple[str, str]] = Counter()
    pair_disagree: Counter[tuple[str, str]] = Counter()
    pair_n: Counter[tuple[str, str]] = Counter()
    mute_rate: Counter[str] = Counter()  # channel -> mute count among hard
    hard_n: Counter[str] = Counter()
    vis_snd: Counter[tuple[str, str]] = Counter()
    trio_n = 0
    trio_unanimous = 0
    odd_out: Counter[str] = Counter()
    lock_coalition: Counter[str] = Counter()
    auto_lock_n = 0
    n_hops = 0
    sessions = 0

    for path in hops_files:
        sessions += 1
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                hop = json.loads(line)
            except json.JSONDecodeError:
                continue
            n_hops += 1
            votes = _hop_votes(hop)
            hard = {k: v for k, v in votes.items() if v in {"mute", "play"}}
            for k, v in hard.items():
                present[k] += 1
                hard_n[k] += 1
                if v == "mute":
                    mute_rate[k] += 1
            for a, b in (("vision", "asr"), ("vision", "acoustic"), ("asr", "acoustic")):
                if a in hard and b in hard:
                    pair_n[(a, b)] += 1
                    if hard[a] == hard[b]:
                        pair_agree[(a, b)] += 1
                    else:
                        pair_disagree[(a, b)] += 1
            if "vision" in hard and "acoustic" in hard:
                vis_snd[(hard["vision"], hard["acoustic"])] += 1

            cons = consensus_at_hop(hop)
            if cons.get("label") in {"mute", "play"}:
                auto_lock_n += 1
                who = "+".join(sorted(k for k, v in hard.items() if v == cons["label"]))
                lock_coalition[who] += 1

            if len(hard) == 3:
                trio_n += 1
                labs = set(hard.values())
                if len(labs) == 1:
                    trio_unanimous += 1
                else:
                    maj, nmaj = Counter(hard.values()).most_common(1)[0]
                    if nmaj == 2:
                        odd = next(k for k, v in hard.items() if v != maj)
                        odd_out[odd] += 1

    odd_total = sum(odd_out.values())
    lock_total = sum(lock_coalition.values()) or 1
    payload: dict[str, Any] = {
        "ok": True,
        "utc": _now(),
        "sessions": sessions,
        "hops_total": n_hops,
        "coverage": {
            "acoustic": {
                "n": present["acoustic"],
                "pct": _pct(present["acoustic"], n_hops),
                "mute_pct": _pct(mute_rate["acoustic"], hard_n["acoustic"]),
            },
            "vision": {
                "n": present["vision"],
                "pct": _pct(present["vision"], n_hops),
                "mute_pct": _pct(mute_rate["vision"], hard_n["vision"]),
            },
            "asr": {
                "n": present["asr"],
                "pct": _pct(present["asr"], n_hops),
                "mute_pct": _pct(mute_rate["asr"], hard_n["asr"]),
            },
        },
        "pairwise": {
            "sound_transcript": {
                "n": pair_n[("asr", "acoustic")],
                "agree_pct": _pct(pair_agree[("asr", "acoustic")], pair_n[("asr", "acoustic")]),
            },
            "pictures_transcript": {
                "n": pair_n[("vision", "asr")],
                "agree_pct": _pct(pair_agree[("vision", "asr")], pair_n[("vision", "asr")]),
            },
            "sound_pictures": {
                "n": pair_n[("vision", "acoustic")],
                "agree_pct": _pct(pair_agree[("vision", "acoustic")], pair_n[("vision", "acoustic")]),
            },
        },
        "vision_vs_sound": {
            "pic_mute_snd_play": vis_snd[("mute", "play")],
            "pic_play_snd_play": vis_snd[("play", "play")],
            "pic_mute_snd_mute": vis_snd[("mute", "mute")],
            "pic_play_snd_mute": vis_snd[("play", "mute")],
        },
        "trio": {
            "n": trio_n,
            "unanimous": trio_unanimous,
            "unanimous_pct": _pct(trio_unanimous, trio_n),
            "odd_one_out": {
                "vision": {"n": odd_out["vision"], "pct": _pct(odd_out["vision"], odd_total)},
                "asr": {"n": odd_out["asr"], "pct": _pct(odd_out["asr"], odd_total)},
                "acoustic": {"n": odd_out["acoustic"], "pct": _pct(odd_out["acoustic"], odd_total)},
            },
        },
        "auto_lock": {
            "n": auto_lock_n,
            "coalitions": {
                k: {"n": v, "pct": _pct(v, lock_total)}
                for k, v in lock_coalition.most_common()
            },
        },
        "plain": (
            f"{sessions} sessions / {n_hops} hops · "
            f"hard votes snd {_pct(present['acoustic'], n_hops)}% · "
            f"pic {_pct(present['vision'], n_hops)}% · "
            f"txt {_pct(present['asr'], n_hops)}% · "
            f"snd↔txt {_pct(pair_agree[('asr', 'acoustic')], pair_n[('asr', 'acoustic')])}% · "
            f"snd↔pic {_pct(pair_agree[('vision', 'acoustic')], pair_n[('vision', 'acoustic')])}%"
        ),
    }
    _AGREE_CACHE["sig"] = sig
    _AGREE_CACHE["payload"] = payload
    return dict(payload)


def apply_all_ready(
    root: Path | None = None,
    *,
    sessions: list[str] | None = None,
    dry_run: bool = False,
    limit: int | None = None,
) -> dict[str, Any]:
    sess = sessions or prepared_sessions(root)
    if limit is not None:
        sess = sess[: max(0, int(limit))]
    results = []
    for s in sess:
        hops = farm_label_dir(root) / "audit" / s / "hops.jsonl"
        if not hops.is_file():
            results.append({"ok": False, "session": s, "error": "missing hops.jsonl"})
            continue
        results.append(apply_consensus_locks(s, root=root, dry_run=dry_run))
    return {
        "ok": True,
        "utc": _now(),
        "n": len(results),
        "locked_total": sum(int(r.get("locked_n") or 0) for r in results),
        "results": results,
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="Apply multichannel consensus locks")
    p.add_argument("--session", type=str, default=None)
    p.add_argument("--all-ready", action="store_true")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)
    if args.session:
        out = apply_consensus_locks(args.session, dry_run=bool(args.dry_run))
    elif args.all_ready:
        out = apply_all_ready(dry_run=bool(args.dry_run), limit=args.limit)
    else:
        p.error("pass --session or --all-ready")
    print(json.dumps(out, indent=2, default=str))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
