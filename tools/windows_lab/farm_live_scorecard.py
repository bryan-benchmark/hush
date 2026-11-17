"""Score farm gold with the live Mac muter stack (audio → cover/play).

This is the only farm accuracy number that counts toward the live muter.

  WAV → frame_mn10 + frozen_head + LiveController (0.90/0.50 × 8/2 + 8s cooldown)

Whisper / VL / moondream draft probes are labeling aids. They are not this score.

Usage
-----
  python -m tools.windows_lab.farm_live_scorecard
  python -m tools.windows_lab.farm_live_scorecard --limit-sessions 2
  python -m tools.windows_lab.farm_live_scorecard --all-locked   # ignore GOLD_CLEAN filter
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from .coverage_farm import farm_label_dir, streamers_capture_root
from .farm_draft import _read_wav_mono16, _wav_duration_sec
from .farm_ontology import BROADCAST, NON_BROADCAST, to_acoustic_bucket

# Live Mac operating point (ohush_live.research_muter)
ON = 0.90
OFF = 0.50
ON_STREAK = 8
OFF_STREAK = 2
COOLDOWN_S = 8.0
HOP_S = 0.25
SR = 16000
WINDOW_S = 4.0
CONTEXT_S = 10.0
SEQUENCE = 16
BATCH = 8

_EPS = 1e-6


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def _is_locked(row: dict[str, Any]) -> bool:
    if row.get("ask") == "skip":
        return False
    if str(row.get("source") or "") == "skip_gold_hygiene":
        return False
    return bool(row.get("gold") or row.get("ask") == "locked" or row.get("source") in {"gold", "human"})


def _role(bucket: str, kind: str = "") -> str | None:
    """Mute/play from acoustic ontology (program_mention → mute)."""
    ac = to_acoustic_bucket(bucket, kind=kind)
    if ac == NON_BROADCAST:
        return "mute"
    if ac == BROADCAST:
        return "play"
    return None


def load_gold_clips(*, clean_only: bool) -> list[dict[str, Any]]:
    label = farm_label_dir()
    keys = {str(r.get("clip") or ""): r for r in _load_jsonl(label / "key.jsonl") if r.get("clip")}
    queue = {str(r.get("clip") or ""): r for r in _load_jsonl(label / "queue.jsonl") if r.get("clip")}
    allowed: set[str] | None = None
    clean_path = label / "GOLD_CLEAN.json"
    if clean_only and clean_path.is_file():
        blob = json.loads(clean_path.read_text(encoding="utf-8"))
        allowed = {str(c) for c in (blob.get("clips") or [])}

    out: list[dict[str, Any]] = []
    for clip, row in keys.items():
        if not _is_locked(row):
            continue
        if allowed is not None and clip not in allowed:
            continue
        kind = str(row.get("kind") or "")
        role = _role(str(row.get("bucket") or ""), kind)
        if role is None:
            continue
        q = queue.get(clip) or {}
        session = str(row.get("session") or q.get("session") or "")
        if not session:
            continue
        sd = Path(str(row.get("session_dir") or q.get("session_dir") or ""))
        if not sd.is_dir():
            cand = streamers_capture_root() / session
            sd = cand if cand.is_dir() else sd
        out.append(
            {
                "clip": clip,
                "session": session,
                "session_dir": str(sd),
                "t0": float(row.get("t0") if row.get("t0") is not None else q.get("t0") or 0.0),
                "t1": float(row.get("t1") if row.get("t1") is not None else q.get("t1") or 0.0),
                "bucket": str(row.get("bucket") or ""),
                "kind": kind,
                "role": role,
                "acoustic_bucket": to_acoustic_bucket(str(row.get("bucket") or ""), kind=kind),
            }
        )
    out.sort(key=lambda r: (r["session"], r["t0"], r["clip"]))
    return out


def _merge(ranges: list[tuple[float, float]]) -> list[tuple[float, float]]:
    ordered = sorted((a, b) for a, b in ranges if b > a + _EPS)
    if not ordered:
        return []
    out = [list(ordered[0])]
    for a, b in ordered[1:]:
        if a <= out[-1][1] + _EPS:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(float(a), float(b)) for a, b in out]


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def _seconds(ranges: list[tuple[float, float]]) -> float:
    return float(sum(b - a for a, b in ranges))


def _intersect(base: list[tuple[float, float]], cut: list[tuple[float, float]]) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for a0, a1 in base:
        for b0, b1 in cut:
            left, right = max(a0, b0), min(a1, b1)
            if right > left + _EPS:
                out.append((left, right))
    return _merge(out)


def _device():
    import torch

    if torch.cuda.is_available():
        return torch.device("cuda")
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        try:
            x = torch.zeros(1, device="mps")
            _ = (x + 1).cpu()
            return torch.device("mps")
        except Exception:
            return torch.device("cpu")
    return torch.device("cpu")


def _load_models(device):
    import torch

    import experiments.audio_learn.encoder as encoder_mod
    from experiments.audio_learn.encoder import load_encoder
    from experiments.audio_learn.head import load_head
    from ohush_live.research_muter import HEAD, WEIGHTS, assets_ready

    ok, detail = assets_ready()
    if not ok:
        raise RuntimeError(detail)
    # Same load path as ohush_live.research_audio_worker (wrapper strips SED heads).
    encoder_mod.WEIGHTS = WEIGHTS
    torch.set_grad_enabled(False)
    encoder = load_encoder(device)
    head = load_head(HEAD, device)
    return encoder, head, str(WEIGHTS), str(HEAD)


def _infer_session(
    wav: Path,
    t_end: float,
    encoder,
    head,
    device,
    *,
    cache_path: Path | None = None,
) -> tuple[np.ndarray, np.ndarray, list[dict[str, Any]]]:
    """Run live-identical hop scoring on [0, t_end]. Returns times, probs, decision rows."""
    from experiments.audio_learn.encoder import embed_numpy
    from experiments.audio_learn.head import probabilities
    from experiments.audio_learn.windows import pack_past_batch
    from ohush_live.research_muter import LiveController

    if cache_path and cache_path.is_file():
        blob = np.load(cache_path)
        times = np.asarray(blob["times"], dtype=np.float64)
        probs = np.asarray(blob["probs"], dtype=np.float32)
    else:
        duration = min(float(t_end), _wav_duration_sec(wav))
        if duration < WINDOW_S + HOP_S:
            raise RuntimeError(f"{wav} too short ({duration:.1f}s)")
        # Load [0, duration] as 16 kHz mono (same PCM path as farm Whisper).
        audio, rate = _read_wav_mono16(wav, 0.0, duration)
        if rate != SR:
            raise RuntimeError(f"expected 16 kHz after resample, got {rate}")
        # Decision stamps: first at WINDOW_S, then every HOP_S (matches live worker).
        times = np.arange(WINDOW_S, duration + 1e-9, HOP_S, dtype=np.float64)
        # Drop stamps whose window would leave the buffer.
        max_t = len(audio) / float(SR)
        times = times[times <= max_t + 1e-9]
        embeds = []
        for start in range(0, len(times), BATCH):
            chunk = times[start : start + BATCH]
            waves = pack_past_batch(audio, 0.0, chunk, WINDOW_S, CONTEXT_S, SR)
            embeds.append(embed_numpy(encoder, device, waves))
        emb = np.concatenate(embeds, axis=0)
        probs = probabilities(head, emb, times, device, batch=256)
        if cache_path is not None:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            np.savez_compressed(cache_path, times=times, probs=probs, emb=emb)

    controller = LiveController(
        on=ON,
        off=OFF,
        on_streak=ON_STREAK,
        off_streak=OFF_STREAK,
        cooldown_s=COOLDOWN_S,
    )
    rows: list[dict[str, Any]] = []
    for t, p in zip(times.tolist(), probs.tolist()):
        d = controller.step(float(t), float(p))
        rows.append(
            {
                "clock": "capture",
                "available_at": float(t),
                "evidence_through": float(t),
                "action": d["action"],
                "probability": float(p),
                "force_play": bool(d["force_play"]),
            }
        )
    return times, probs, rows


def _cover_ranges(decisions: list[dict[str, Any]], coverage: tuple[float, float]) -> list[tuple[float, float]]:
    """Hold each action until the next decision (nfl75 playback_from_decisions semantics)."""
    c0, c1 = coverage
    spans: list[tuple[float, float]] = []
    cursor = c0
    state = "play"
    for row in decisions:
        available = float(row["available_at"])
        if available > cursor + _EPS and state == "cover":
            spans.append((cursor, available))
        state = "cover" if row["action"] == "cover" else "play"
        cursor = available
    if c1 > cursor + _EPS and state == "cover":
        spans.append((cursor, c1))
    return _merge(spans)


def score_session(clips: list[dict[str, Any]], cover: list[tuple[float, float]]) -> dict[str, Any]:
    mute_iv = _merge([(c["t0"], c["t1"]) for c in clips if c["role"] == "mute"])
    play_iv = _merge([(c["t0"], c["t1"]) for c in clips if c["role"] == "play"])
    mute_s = _seconds(mute_iv)
    play_s = _seconds(play_iv)
    covered_commercial = _seconds(_intersect(mute_iv, cover))
    program_muted = _seconds(_intersect(play_iv, cover))
    broken = program_muted > _EPS
    coverage = (covered_commercial / mute_s) if mute_s > _EPS else None

    clip_rows = []
    for c in clips:
        ol = _seconds(_intersect([(c["t0"], c["t1"])], cover))
        dur = max(_EPS, c["t1"] - c["t0"])
        frac = ol / dur
        if c["role"] == "mute":
            ok = frac >= 0.5  # majority of gold ad held
        else:
            ok = ol <= _EPS  # any program mute is a miss
        clip_rows.append(
            {
                "clip": c["clip"],
                "role": c["role"],
                "bucket": c["bucket"],
                "t0": c["t0"],
                "t1": c["t1"],
                "covered_s": round(ol, 3),
                "frac_covered": round(frac, 4),
                "ok": ok,
            }
        )

    return {
        "mute_labeled_s": round(mute_s, 3),
        "play_labeled_s": round(play_s, 3),
        "commercial_covered_s": round(covered_commercial, 3),
        "commercial_coverage": None if coverage is None else round(coverage, 4),
        "program_muted_s": round(program_muted, 3),
        "broken": broken,
        "accuracy_pct": None if broken or coverage is None else round(100.0 * coverage, 2),
        "clips": clip_rows,
    }


def run(*, clean_only: bool, limit_sessions: int | None, use_cache: bool) -> dict[str, Any]:
    clips = load_gold_clips(clean_only=clean_only)
    by_session: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for c in clips:
        by_session[c["session"]].append(c)

    sessions = sorted(by_session.keys())
    if limit_sessions is not None:
        sessions = sessions[: max(0, int(limit_sessions))]

    label = farm_label_dir()
    cache_dir = label / "live_scorecard_cache"
    device = _device()
    encoder, head, weights_path, head_path = _load_models(device)

    session_rows: list[dict[str, Any]] = []
    for session in sessions:
        group = by_session[session]
        sd = Path(group[0]["session_dir"])
        wav = sd / "audio.wav"
        row: dict[str, Any] = {
            "session": session,
            "session_dir": str(sd),
            "n_clips": len(group),
            "wav_exists": wav.is_file(),
        }
        if not wav.is_file():
            row["error"] = "missing audio.wav"
            session_rows.append(row)
            continue
        t_end = max(c["t1"] for c in group) + HOP_S
        # Need a little pad so the last gold second can be covered by a later decision.
        t_end = max(t_end, max(c["t1"] for c in group) + WINDOW_S)
        cache_path = (cache_dir / f"{session}.npz") if use_cache else None
        try:
            _times, _probs, decisions = _infer_session(
                wav, t_end, encoder, head, device, cache_path=cache_path
            )
        except Exception as exc:  # noqa: BLE001
            row["error"] = str(exc)
            session_rows.append(row)
            continue
        cov0 = 0.0
        cov1 = float(max(c["t1"] for c in group))
        cover = _cover_ranges(decisions, (cov0, cov1))
        scored = score_session(group, cover)
        row.update(scored)
        row["n_decisions"] = len(decisions)
        row["device"] = str(device)
        session_rows.append(row)

    mute_s = sum(float(r.get("mute_labeled_s") or 0) for r in session_rows if "broken" in r)
    play_s = sum(float(r.get("play_labeled_s") or 0) for r in session_rows if "broken" in r)
    covered = sum(float(r.get("commercial_covered_s") or 0) for r in session_rows if "broken" in r)
    program_muted = sum(float(r.get("program_muted_s") or 0) for r in session_rows if "broken" in r)
    any_broken = any(bool(r.get("broken")) for r in session_rows if "broken" in r)
    coverage = (covered / mute_s) if mute_s > _EPS else None
    scored_sessions = sum(1 for r in session_rows if "broken" in r)
    errors = sum(1 for r in session_rows if r.get("error"))

    aggregate = {
        "mute_labeled_s": round(mute_s, 3),
        "play_labeled_s": round(play_s, 3),
        "commercial_covered_s": round(covered, 3),
        "commercial_coverage": None if coverage is None else round(coverage, 4),
        "program_muted_s": round(program_muted, 3),
        "broken": any_broken,
        "accuracy_pct": None if any_broken or coverage is None else round(100.0 * coverage, 2),
        "ladder_note": (
            "Broken if any labeled program second is covered. "
            "accuracy_pct is commercial seconds held / labeled mute seconds — only when not broken."
        ),
    }

    out = {
        "generated_utc": _now(),
        "experiment": "farm_live_scorecard",
        "what_this_is": (
            "Live Mac muter recipe scored on farm human gold (WAV only). "
            "Not Whisper/VL draft match."
        ),
        "stack": {
            "encoder": "frame_mn10",
            "head": "frozen_head",
            "controller": {
                "on": ON,
                "off": OFF,
                "on_streak": ON_STREAK,
                "off_streak": OFF_STREAK,
                "cooldown_s": COOLDOWN_S,
            },
            "weights": weights_path,
            "head_path": head_path,
            "device": str(device),
        },
        "gold": {
            "clean_only": clean_only,
            "n_clips": len(clips),
            "n_sessions_available": len(by_session),
            "n_sessions_scored": scored_sessions,
            "n_session_errors": errors,
            "ontology": "farm_ontology (program_mention→non_broadcast)",
        },
        "aggregate": aggregate,
        "sessions": session_rows,
        "how_you_confirm": [
            "Open LIVE_SCORECARD.md — broken must be false; accuracy_pct is commercial hold only.",
            "A KEEP for the live muter requires this scorecard (or Mac :3010), not VL_AB_PROBE.",
            "Draft aids (Whisper/VL) may still help humans lock gold; they do not set this number.",
        ],
    }
    return out


def _write_report(out: dict[str, Any]) -> tuple[Path, Path]:
    label = farm_label_dir()
    json_path = label / "LIVE_SCORECARD.json"
    md_path = label / "LIVE_SCORECARD.md"
    json_path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    agg = out["aggregate"]
    lines = [
        f"# Farm live scorecard — {out['generated_utc'][:19]}Z",
        "",
        "**This is mute accuracy (live stack on WAV).** Whisper/VL probes are draft aids only.",
        "",
        f"- broken: **`{agg['broken']}`** (any labeled program second covered)",
        f"- commercial coverage: **{agg['commercial_coverage']}** "
        f"({agg['commercial_covered_s']}s / {agg['mute_labeled_s']}s mute gold)",
        f"- program muted: **{agg['program_muted_s']}s** / {agg['play_labeled_s']}s play gold",
        f"- accuracy_pct: **{agg['accuracy_pct']}** (null when broken)",
        "",
        f"Stack: `{out['stack']['encoder']}` + frozen_head + "
        f"{out['stack']['controller']['on']}/{out['stack']['controller']['off']} × "
        f"{out['stack']['controller']['on_streak']}/{out['stack']['controller']['off_streak']} "
        f"+ {out['stack']['controller']['cooldown_s']}s cooldown · device `{out['stack']['device']}`",
        "",
        f"Gold clips: {out['gold']['n_clips']} · sessions scored: {out['gold']['n_sessions_scored']} "
        f"· clean_only={out['gold']['clean_only']}",
        "",
        "| Session | Clips | Mute s | Coverage | Program muted s | Broken |",
        "|---|---:|---:|---:|---:|:---:|",
    ]
    for r in out["sessions"]:
        if r.get("error"):
            lines.append(
                f"| `{r['session']}` | {r.get('n_clips', 0)} | — | — | — | err: {r['error'][:40]} |"
            )
            continue
        lines.append(
            f"| `{r['session']}` | {r.get('n_clips', 0)} | {r.get('mute_labeled_s')} | "
            f"{r.get('commercial_coverage')} | {r.get('program_muted_s')} | {r.get('broken')} |"
        )
    lines.extend(["", "## Confirm", ""])
    for tip in out["how_you_confirm"]:
        lines.append(f"- {tip}")
    lines.append("")
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Score farm gold with the live acoustic muter stack")
    p.add_argument("--all-locked", action="store_true", help="Use all locked keys (ignore GOLD_CLEAN)")
    p.add_argument("--limit-sessions", type=int, default=None, help="Score only the first N sessions")
    p.add_argument("--no-cache", action="store_true", help="Do not read/write embedding cache")
    args = p.parse_args(argv)

    try:
        out = run(
            clean_only=not args.all_locked,
            limit_sessions=args.limit_sessions,
            use_cache=not args.no_cache,
        )
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": str(exc)}), flush=True)
        return 1

    json_path, md_path = _write_report(out)
    agg = out["aggregate"]
    print(
        json.dumps(
            {
                "ok": True,
                "broken": agg["broken"],
                "commercial_coverage": agg["commercial_coverage"],
                "accuracy_pct": agg["accuracy_pct"],
                "program_muted_s": agg["program_muted_s"],
                "sessions_scored": out["gold"]["n_sessions_scored"],
                "json": str(json_path),
                "md": str(md_path),
            },
            indent=2,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
