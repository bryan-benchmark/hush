"""Extract live-stack frame_mn10 embeddings for farm session WAVs + hop receipts.

Writes:
  C:\\OHushData\\gpu_lab\\audio_learn\\embeddings\\farm\\<session>.npz
  session/audit/hops_acoustic.jsonl  (p + action per hop)
  indexes/farm_labels/audit/<session>/...

Never touches sealed optical holdouts.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np

from .coverage_farm import farm_label_dir, streamers_capture_root
from .export_farm_acoustic_gold import OUT as FARM_ACCEPTED
from .farm_audit_receipts import append_event, hop_receipt, write_hops
from .farm_draft import _read_wav_mono16, _wav_duration_sec
from .farm_live_scorecard import (
    BATCH,
    CONTEXT_S,
    HOP_S,
    WINDOW_S,
    _cover_ranges,
    _device,
    _infer_session,
    _load_models,
)
from .farm_ontology import BROADCAST, NON_BROADCAST

EMBED_ROOT = Path(r"C:\OHushData\gpu_lab\audio_learn\embeddings\farm")
SR = 16000


def _sessions_from_accepted() -> list[str]:
    if not FARM_ACCEPTED.is_file():
        return []
    seen: list[str] = []
    for line in FARM_ACCEPTED.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        s = json.loads(line).get("session")
        if s and s not in seen:
            seen.append(s)
    return seen


def _gold_at(session: str, t: float) -> dict[str, Any] | None:
    if not FARM_ACCEPTED.is_file():
        return None
    for line in FARM_ACCEPTED.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("session") != session:
            continue
        if float(r["start_s"]) <= t < float(r["end_s"]):
            return {
                "bucket": r["bucket"],
                "start_s": r["start_s"],
                "end_s": r["end_s"],
                "desired_action": r.get("desired_action"),
                "source": r.get("source"),
            }
    return None


def extract_session(session: str, *, t_end: float | None = None, use_cache: bool = True) -> dict[str, Any]:
    sd = streamers_capture_root() / session
    wav = sd / "audio.wav"
    if not wav.is_file():
        raise FileNotFoundError(str(wav))
    duration = _wav_duration_sec(wav)
    end = float(t_end) if t_end is not None else duration

    device = _device()
    encoder, head, weights, head_path = _load_models(device)
    cache_dir = farm_label_dir() / "live_scorecard_cache"
    cache_path = (cache_dir / f"{session}.npz") if use_cache else None

    # Force recompute embeddings into farm embed root; still reuse scorecard cache for probs when present
    times, probs, decisions = _infer_session(wav, end, encoder, head, device, cache_path=cache_path)

    # Materialize embedding cache for training (same stamps as live infer).
    emb_path = EMBED_ROOT / f"{session}.npz"
    meta_path = emb_path.with_suffix(".json")
    if not emb_path.is_file():
        from experiments.audio_learn.encoder import embed_numpy
        from experiments.audio_learn.windows import pack_past_batch

        audio, rate = _read_wav_mono16(wav, 0.0, min(end, duration))
        if rate != SR:
            raise RuntimeError(f"expected 16k, got {rate}")
        times_e = np.asarray(times, dtype=np.float64)
        parts = []
        for start in range(0, len(times_e), BATCH):
            chunk = times_e[start : start + BATCH]
            waves = pack_past_batch(audio, 0.0, chunk, WINDOW_S, CONTEXT_S, SR)
            parts.append(embed_numpy(encoder, device, waves))
        emb = np.concatenate(parts, axis=0).astype(np.float16)
        labels = np.full(len(times_e), -1, dtype=np.int8)
        for i, t in enumerate(times_e):
            g = _gold_at(session, float(t))
            if not g:
                continue
            if g["bucket"] == NON_BROADCAST:
                labels[i] = 1
            elif g["bucket"] == BROADCAST:
                labels[i] = 0
        EMBED_ROOT.mkdir(parents=True, exist_ok=True)
        p_arr = np.asarray(probs, dtype=np.float32)
        if len(p_arr) != len(times_e):
            p_arr = p_arr[: len(times_e)]
        np.savez_compressed(emb_path, t=times_e, emb=emb, label=labels, p=p_arr)
        meta_path.write_text(
            json.dumps(
                {
                    "session": session,
                    "kind": "farm",
                    "encoder": "frame_mn10",
                    "weights": weights,
                    "head": head_path,
                    "window_s": WINDOW_S,
                    "context_s": CONTEXT_S,
                    "hop_s": HOP_S,
                    "sr": SR,
                    "n": int(len(times_e)),
                    "n_mute": int((labels == 1).sum()),
                    "n_play": int((labels == 0).sum()),
                    "n_unlabeled": int((labels < 0).sum()),
                    "causal": "audio [t-window, t) right-aligned in 10s buffer",
                    "wav": str(wav),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    # Atomic acoustic hops (subsample to 1s for readability, keep all in jsonl)
    hops = []
    for d in decisions:
        t = float(d["available_at"])
        hops.append(
            hop_receipt(
                session=session,
                t=t,
                vision=None,
                asr=None,
                acoustic={
                    "ok": True,
                    "p": round(float(d["probability"]), 4),
                    "action": d["action"],
                    "force_play": bool(d.get("force_play")),
                    "hop_s": HOP_S,
                    "controller": "0.90/0.50 x 8/2 + 8s cooldown",
                },
                gold=_gold_at(session, t),
            )
        )
    # Write full acoustic hops + a 1s-decimated combined-friendly copy
    meta = write_hops(session, hops, session_dir=sd, kind="acoustic")
    # 1s decimated for MD readability already handled in write_hops table — OK

    cover = _cover_ranges(decisions, (0.0, float(times[-1]) if len(times) else end))
    append_event(
        session,
        {
            "event": "embed_extract",
            "emb_path": str(emb_path),
            "n_decisions": len(decisions),
            "n_cover_spans": len(cover),
            "device": str(device),
        },
        session_dir=sd,
    )
    return {
        "ok": True,
        "session": session,
        "emb_path": str(emb_path),
        "meta_path": str(meta_path),
        "n_decisions": len(decisions),
        "audit": meta,
        "device": str(device),
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Farm WAV → frame_mn10 embeddings + acoustic audit hops")
    p.add_argument("--session", type=str, default=None)
    p.add_argument("--from-export", action="store_true")
    p.add_argument("--limit-sessions", type=int, default=None)
    p.add_argument("--t-end", type=float, default=None)
    p.add_argument("--no-cache", action="store_true")
    args = p.parse_args(argv)

    if args.session:
        sessions = [args.session]
    elif args.from_export:
        sessions = _sessions_from_accepted()
    else:
        p.error("pass --session or --from-export")
    if args.limit_sessions is not None:
        sessions = sessions[: args.limit_sessions]

    results = []
    for s in sessions:
        print(json.dumps({"starting": s}), flush=True)
        results.append(extract_session(s, t_end=args.t_end, use_cache=not args.no_cache))
    print(json.dumps({"ok": True, "n": len(results), "results": results}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
