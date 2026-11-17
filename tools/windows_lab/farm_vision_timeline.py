"""Vision(+ASR) range locker → continuous mute/play times + atomic hop receipts.

Stills-first: each 1s hop gets a still description, optional ASR window, then
merged into non_broadcast/broadcast ranges for the acoustic trainer.

Does NOT mute the TV. Writes timeline gold + audit hops.

Usage
-----
  python -m tools.windows_lab.farm_vision_timeline --session 20261110T1339Z_pluto_cbs_sports_hq
  python -m tools.windows_lab.farm_vision_timeline --session ... --t0 0 --t1 60 --no-asr
  python -m tools.windows_lab.farm_vision_timeline --from-export --limit-sessions 2

Scale notes
-----------
- Failed moondream calls are NOT cached (retryable).
- Candidate files replace per-session rows (no append duplicates).
- Long takes (10–20 min) ≈ thousands of stills — start with --limit-sessions /
  --t0/--t1, or raise --hop, before full --from-export.
- High-conf vision ranges are candidates only — do not train until reviewed.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .coverage_farm import farm_label_dir, streamers_capture_root
from .farm_audit_receipts import append_event, hop_receipt, write_hops
from .farm_draft import (
    AD_HINT,
    SHOW_HINT,
    SPORTS_VISUAL,
    VISION_MODEL,
    VISUAL_AD_HINT,
    _visual_class,
    _wav_duration_sec,
    describe_still,
    nearest_still,
    transcript_for_window,
    unload_ollama_model,
)
from .farm_ontology import BROADCAST, NON_BROADCAST, desired_action

_EPS = 1e-6


def _session_dir(session: str) -> Path:
    sd = streamers_capture_root() / session
    if not sd.is_dir():
        raise FileNotFoundError(f"missing session dir {sd}")
    return sd


def _load_transcript(sd: Path) -> dict[str, Any]:
    path = sd / "farm_transcript.json"
    if not path.is_file():
        return {"ok": False, "segments": []}
    return json.loads(path.read_text(encoding="utf-8"))


def _asr_channel(transcript: dict[str, Any], t: float, *, pad: float = 1.5) -> dict[str, Any]:
    t0, t1 = max(0.0, t - pad), t + pad
    text = transcript_for_window(transcript, t0, t1) if transcript.get("segments") is not None else ""
    text = (text or "").strip()
    ad = bool(AD_HINT.search(text))
    prog = bool(SHOW_HINT.search(text) or SPORTS_VISUAL.search(text)) and not ad
    if ad and prog:
        lex, bucket = "mixed", None
    elif ad:
        lex, bucket = "ad", NON_BROADCAST
    elif prog:
        lex, bucket = "program", BROADCAST
    elif not text:
        lex, bucket = "empty", None
    else:
        lex, bucket = "other", None
    return {
        "ok": True,
        "t0": round(t0, 3),
        "t1": round(t1, 3),
        "text": text[:300],
        "lexicon": lex,
        "acoustic_bucket": bucket,
    }


def _vision_channel(
    sd: Path,
    t: float,
    *,
    model: str,
    cache: dict[str, dict],
    fallback_model: str = "qwen2.5vl:7b",
) -> dict[str, Any]:
    still = nearest_still(sd, t)
    if still is None:
        return {"ok": False, "error": "no_still", "t": t, "class": None, "acoustic_bucket": None}
    key = str(still)
    cached = cache.get(key) or {}
    # Reuse successes and definitive dead stills; retry empty/transient failures.
    if cached.get("ok") and cached.get("visual"):
        meta = cached
    elif str(cached.get("error") or "") in {"black_still", "green_corrupt_still", "missing_still"}:
        meta = cached
    else:
        meta = None
    used_model = model
    if meta is None:
        meta = describe_still(still, model=model)
        # Persistent moondream empties: one VL retry before giving up.
        # Do not VL-fallback black/corrupt/missing stills — that burns minutes per hop.
        err = str(meta.get("error") or "")
        skip_fb = err in {"black_still", "green_corrupt_still", "missing_still"}
        if (
            not skip_fb
            and (not meta.get("ok") or not meta.get("visual"))
            and fallback_model
            and fallback_model != model
        ):
            fb = describe_still(still, model=fallback_model)
            if fb.get("ok") and fb.get("visual"):
                meta = fb
                used_model = fallback_model
        # Only cache successes — empty/500 responses must be retried on the next run.
        # Also cache definitive dead stills so we do not re-hit the VL path every second.
        if meta.get("ok") and meta.get("visual"):
            cache[key] = {**meta, "model": used_model}
        elif skip_fb:
            cache[key] = {"ok": False, "error": err, "still": key, "model": used_model, "visual": ""}
    if not meta.get("ok"):
        return {
            "ok": False,
            "error": meta.get("error"),
            "still": key,
            "model": used_model,
            "class": None,
            "acoustic_bucket": None,
        }
    visual = str(meta.get("visual") or "")
    cls = _visual_class(visual)
    if cls == "ad":
        bucket = NON_BROADCAST
    elif cls == "program":
        bucket = BROADCAST
    else:
        bucket = None  # mixed/other → uncertain, no auto gold
    # Strong visual ad lexicon even if class=other
    if bucket is None and VISUAL_AD_HINT.search(visual):
        cls = "ad"
        bucket = NON_BROADCAST
    return {
        "ok": True,
        "still": key,
        "still_name": Path(key).name,
        "model": model,
        "visual": visual[:400],
        "class": cls,
        "acoustic_bucket": bucket,
    }


def _vote_bucket(vision: dict[str, Any], asr: dict[str, Any] | None) -> tuple[str | None, str]:
    """Return (acoustic_bucket|None, confidence). Auto-lock only when high + clear."""
    vb = vision.get("acoustic_bucket") if vision.get("ok") else None
    ab = (asr or {}).get("acoustic_bucket") if asr and asr.get("ok") else None
    if vb and ab and vb == ab:
        return vb, "high"
    if vb and ab and vb != ab:
        return None, "conflict"  # needs human
    if vb == NON_BROADCAST and vision.get("class") == "ad":
        return vb, "medium"  # vision-only ad
    if vb == BROADCAST and (not asr or (asr.get("lexicon") in {"empty", "other", "program"})):
        return vb, "medium"
    if ab and not vb:
        return ab, "low"
    return None, "uncertain"


def _merge_ranges(hops: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge consecutive hops with same locked bucket into intervals."""
    locked = []
    for h in hops:
        extra = h.get("extra") or {}
        bucket = extra.get("lock_bucket")
        conf = extra.get("lock_confidence")
        if not bucket or conf not in {"high", "medium"}:
            continue
        locked.append((float(h["t"]), float(h["t"]) + 1.0, bucket, conf, h))
    if not locked:
        return []
    out = []
    t0, t1, bucket, conf, seed = locked[0]
    clips = [seed]
    for nt0, nt1, nb, nc, h in locked[1:]:
        if nb == bucket and nt0 <= t1 + _EPS:
            t1 = max(t1, nt1)
            if nc == "high":
                conf = "high"
            clips.append(h)
        else:
            out.append(_range_row(t0, t1, bucket, conf, clips))
            t0, t1, bucket, conf, clips = nt0, nt1, nb, nc, [h]
    out.append(_range_row(t0, t1, bucket, conf, clips))
    return out


def _range_row(t0: float, t1: float, bucket: str, conf: str, hops: list[dict[str, Any]]) -> dict[str, Any]:
    stills = []
    for h in hops:
        v = (h.get("channels") or {}).get("vision") or {}
        if v.get("still"):
            stills.append(v["still"])
    return {
        "start_s": round(t0, 3),
        "end_s": round(t1, 3),
        "dur_s": round(t1 - t0, 3),
        "bucket": bucket,
        "desired_action": desired_action(bucket),
        "confidence": conf,
        "source": "vision_auto",
        "model_id": f"vision_timeline:{VISION_MODEL}",
        "n_hops": len(hops),
        "stills": stills[:8],
        "still_flip": _still_flip(hops),
    }


def _still_flip(hops: list[dict[str, Any]]) -> bool:
    classes = []
    for h in hops:
        v = (h.get("channels") or {}).get("vision") or {}
        c = v.get("class")
        if c in {"ad", "program"}:
            classes.append(c)
    return "ad" in classes and "program" in classes


def run_session(
    session: str,
    *,
    t0: float = 0.0,
    t1: float | None = None,
    hop_s: float = 1.0,
    use_asr: bool = True,
    use_vision: bool = True,
    model: str = VISION_MODEL,
    auto_export: bool = True,
) -> dict[str, Any]:
    sd = _session_dir(session)
    wav = sd / "audio.wav"
    if not wav.is_file():
        raise FileNotFoundError(f"missing {wav}")
    duration = _wav_duration_sec(wav)
    end = min(duration, float(t1) if t1 is not None else duration)
    start = max(0.0, float(t0))

    transcript = _load_transcript(sd) if use_asr else {"segments": []}
    # Ensure transcript exists when requested
    if use_asr and not (sd / "farm_transcript.json").is_file():
        from .farm_draft import ensure_take_transcript

        ensure_take_transcript(sd)
        transcript = _load_transcript(sd)

    cache: dict[str, dict] = {}
    cache_path = sd / "audit" / "vision_still_cache.json"
    if cache_path.is_file():
        try:
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            cache = {}

    # Merge with prior vision hops so partial --t0/--t1 runs do not wipe audit.
    prior_path = farm_label_dir() / "audit" / session / "hops_vision.jsonl"
    prior_by_t: dict[float, dict[str, Any]] = {}
    if prior_path.is_file():
        for line in prior_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            prior_by_t[round(float(row["t"]), 3)] = row

    hops_new: list[dict[str, Any]] = []
    t = start
    n_expect = max(1, int((end - start) / hop_s) + 1)
    i_hop = 0
    while t < end - 1e-9:
        vision = _vision_channel(sd, t, model=model, cache=cache) if use_vision else None
        asr = _asr_channel(transcript, t) if use_asr else None
        lock_bucket, lock_conf = _vote_bucket(vision or {}, asr)
        hops_new.append(
            hop_receipt(
                session=session,
                t=t,
                vision=vision,
                asr=asr,
                acoustic=None,
                gold=None,
                extra={
                    "lock_bucket": lock_bucket,
                    "lock_confidence": lock_conf,
                    "auto_lock": lock_bucket is not None and lock_conf == "high",
                },
            )
        )
        i_hop += 1
        if i_hop == 1 or i_hop % 25 == 0 or t + hop_s >= end - 1e-9:
            prog = {
                "vision_progress": session,
                "i": i_hop,
                "of": n_expect,
                "t": round(t, 1),
                "model": model,
            }
            print(json.dumps(prog), flush=True)
            try:
                from .lab_status import write_status

                write_status(
                    progress={
                        "phase": "vision",
                        "session": session,
                        "hop_i": i_hop,
                        "hop_of": n_expect,
                        "t": round(t, 1),
                        "model": model,
                    }
                )
            except Exception:
                pass
        t += hop_s

    for h in hops_new:
        prior_by_t[round(float(h["t"]), 3)] = h
    hops = [prior_by_t[k] for k in sorted(prior_by_t.keys())]

    # Persist vision cache
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    # Only store serializable still→meta
    slim = {k: {kk: vv for kk, vv in v.items() if kk in {"ok", "visual", "error", "model", "still"}} for k, v in cache.items()}
    cache_path.write_text(json.dumps(slim, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    ranges = _merge_ranges(hops)
    # Write vision timeline sidecar (candidate gold)
    vision_tl = sd / "farm_timeline_vision.jsonl"
    rows = []
    for r in ranges:
        rows.append(
            {
                "session": session,
                "session_dir": str(sd),
                "start_s": r["start_s"],
                "end_s": r["end_s"],
                "dur_s": r["dur_s"],
                "bucket": r["bucket"],
                "kind": "vision_range",
                "desired_action": r["desired_action"],
                "source": "vision_auto",
                "confidence": r["confidence"],
                "status": "accepted" if r["confidence"] == "high" else "needs_human",
                "note": f"vision_auto hops={r['n_hops']} flip={r['still_flip']}",
                "model_id": r["model_id"],
                "stills": r["stills"],
            }
        )
    vision_tl.write_text(
        "\n".join(json.dumps(x, ensure_ascii=False) for x in rows) + ("\n" if rows else ""),
        encoding="utf-8",
    )

    # High-conf only → replace this session's rows (never append-duplicate on re-runs)
    high = [r for r in rows if r["confidence"] == "high" and r["status"] == "accepted"]
    patch_path = farm_label_dir() / "vision_timeline_candidates.jsonl"
    _rewrite_session_jsonl(patch_path, session, high)

    audit_meta = write_hops(session, hops, session_dir=sd, kind="vision")
    append_event(
        session,
        {
            "event": "vision_timeline",
            "t0": start,
            "t1": end,
            "n_hops": len(hops),
            "n_ranges": len(ranges),
            "n_high_conf": len(high),
            "vision_timeline": str(vision_tl),
        },
        session_dir=sd,
    )

    if use_vision:
        unload_ollama_model(model)

    export_receipt = None
    if auto_export and high:
        # Rebuild human timelines then note vision candidates separately
        from .export_farm_acoustic_gold import export as export_farm_gold

        export_receipt = export_farm_gold(rebuild=True, clean_only=True)
        # Also write vision-high into a dedicated accepted-adjacent file
        vpath = Path(r"C:\OHushData\gpu_lab\audio_learn\broadcast_labels\farm_vision_candidates.jsonl")
        vpath.parent.mkdir(parents=True, exist_ok=True)
        existing = []
        if vpath.is_file():
            for line in vpath.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    existing.append(json.loads(line))
        # Replace this session's rows
        existing = [r for r in existing if r.get("session") != session]
        existing.extend(
            {
                "session": r["session"],
                "start_s": r["start_s"],
                "end_s": r["end_s"],
                "dur_s": r["dur_s"],
                "bucket": r["bucket"],
                "kind": r["kind"],
                "desired_action": r["desired_action"],
                "source": "farm:vision_auto",
                "confidence": r["confidence"],
                "note": r["note"],
                "status": "candidate",  # not yet folded into train until reviewed
                "model_id": r["model_id"],
            }
            for r in high
        )
        vpath.write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in existing) + "\n",
            encoding="utf-8",
        )

    return {
        "ok": True,
        "session": session,
        "session_dir": str(sd),
        "t0": start,
        "t1": end,
        "n_hops": len(hops),
        "n_ranges": len(ranges),
        "n_high_conf_ranges": len(high),
        "n_needs_human": sum(1 for r in rows if r["status"] == "needs_human"),
        "vision_timeline": str(vision_tl),
        "audit": audit_meta,
        "export": export_receipt,
        "how_to_audit": [
            f"Open {audit_meta.get('md_path')}",
            f"grep DISAGREE {audit_meta.get('hops_path')}",
            f"Vision ranges: {vision_tl}",
        ],
    }


def _rewrite_session_jsonl(path: Path, session: str, rows: list[dict[str, Any]]) -> None:
    """Replace all rows for one session; keep other sessions intact."""
    path.parent.mkdir(parents=True, exist_ok=True)
    kept: list[dict[str, Any]] = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("session") != session:
                kept.append(row)
    kept.extend(rows)
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in kept) + ("\n" if kept else ""),
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Vision range locker + atomic audit hops")
    p.add_argument("--session", type=str, default=None)
    p.add_argument("--from-export", action="store_true", help="Run every session in farm_accepted")
    p.add_argument("--t0", type=float, default=0.0)
    p.add_argument("--t1", type=float, default=None)
    p.add_argument("--hop", type=float, default=1.0)
    p.add_argument("--no-asr", action="store_true")
    p.add_argument("--no-vision", action="store_true", help="ASR-only (debug)")
    p.add_argument("--model", type=str, default=VISION_MODEL)
    p.add_argument("--limit-sessions", type=int, default=None)
    args = p.parse_args(argv)

    sessions: list[str] = []
    if args.session:
        sessions = [args.session]
    elif args.from_export:
        path = Path(r"C:\OHushData\gpu_lab\audio_learn\broadcast_labels\farm_accepted.jsonl")
        seen = []
        if path.is_file():
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                s = json.loads(line).get("session")
                if s and s not in seen:
                    seen.append(s)
        sessions = seen
    else:
        p.error("pass --session or --from-export")

    if args.limit_sessions is not None:
        sessions = sessions[: args.limit_sessions]

    results = []
    for session in sessions:
        print(json.dumps({"starting": session}), flush=True)
        results.append(
            run_session(
                session,
                t0=args.t0,
                t1=args.t1,
                hop_s=args.hop,
                use_asr=not args.no_asr,
                use_vision=not args.no_vision,
                model=args.model,
            )
        )
    print(json.dumps({"ok": True, "n": len(results), "results": results}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    # ensure_session_transcript may not exist — check
    raise SystemExit(main())
