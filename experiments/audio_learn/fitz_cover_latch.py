"""Cover-only Ryan Fitzpatrick on the KEEP research stack.

Fitz is in TNF cast / VOICE_ENROLL labels but not the 5-name ECAPA cache.
Builds a side cosine (like Palmer) from owner deep label + Oct clear enroll,
scores product cells, KEEP/REJECT vs stack and vs cooldown cumulative gate.

Live untouched.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

CACHE = REPO / "ohush_live" / "cache"
os.environ.setdefault("HF_HOME", str(CACHE / "hf"))
os.environ.setdefault("HUGGINGFACE_HUB_CACHE", str(CACHE / "hf" / "hub"))
os.environ.setdefault("TORCH_HOME", str(CACHE / "torch"))

from experiments.audio_learn.controller import decisions
from experiments.audio_learn.desk_voice_hold import ECAPA, HOLD_S, LINE, NAMES
from experiments.audio_learn.product_scorecard import DATA, load_frozen_probs, score_run
from experiments.audio_learn.research_latch import apply_research_latch
from experiments.audio_learn.splits import EVAL
from experiments.audio_learn.studio_fit import CONTROLLER
from experiments.ledger import RECORDINGS
from experiments.nfl75.protect_embed import MODEL, SR, _clip, _embed_windows, _load_encoder
from hush.audio import RAW_SR, analysis_pieces, find_session, load_session, read_stereo, resample_concat

OUT = DATA / "fitz_cover_latch"
MARGINS = (0.10, 0.15)

# Causal same-tape / prior-tape enrolls only.
ENROLL = (
    {
        "session": "hush_20260924_220624",
        "play_start": 6599.5,
        "duration": 6.2,
        "available_at": 6605.7,
        "note": "deep label: fitz postgame (before Odell 7035)",
    },
    {
        "session": "hush_20261008_205100",
        "play_start": 3349.7,
        "duration": 3.0,
        "available_at": 3352.7,
        "note": "VOICE_ENROLL_001 e0150 clear Fitz",
    },
)


def _session_audio(session: str) -> tuple[np.ndarray, float]:
    folder = find_session(RECORDINGS, session)
    meta = load_session(folder)
    chunks = meta.get("chunks") or []
    start = float(chunks[0]["start_elapsed_seconds"]) if chunks else 0.0
    end = float(chunks[-1]["end_elapsed_seconds"]) if chunks else float(meta.get("audio_seconds") or 0)
    pieces = analysis_pieces(folder, meta, start, end)
    mono = [read_stereo(piece).mean(axis=1) for piece in pieces]
    audio = np.asarray(resample_concat(mono, up=1, down=RAW_SR // SR), dtype=np.float32)
    return audio, start


def build_cache(encoder) -> dict[str, Path]:
    OUT.mkdir(parents=True, exist_ok=True)
    by_session: dict[str, list[dict]] = {}
    for row in ENROLL:
        by_session.setdefault(row["session"], []).append(row)

    paths = {}
    for session in EVAL:
        dest = OUT / f"{session}_fitz.npz"
        if dest.is_file():
            print(f"cached {dest.name}", flush=True)
            paths[session] = dest
            continue
        # causal: this session's clips + any earlier-session enrolls
        vectors = []
        ready = []
        for row in ENROLL:
            if row["session"] == session:
                audio = _clip(row["session"], float(row["play_start"]), float(row["duration"]))
                vec = _embed_windows(audio, [(0.0, len(audio) / SR)], encoder, 1)[0]
                vectors.append(vec)
                ready.append(float(row["available_at"]))
                print(f"enroll Fitz {row['session']} {row['play_start']} avail@{row['available_at']}", flush=True)
            elif row["session"] < session:  # string stamp order hush_YYYYMMDD...
                audio = _clip(row["session"], float(row["play_start"]), float(row["duration"]))
                vec = _embed_windows(audio, [(0.0, len(audio) / SR)], encoder, 1)[0]
                vectors.append(vec)
                ready.append(0.0)  # prior tape available at kickoff
                print(f"enroll Fitz prior {row['session']} {row['play_start']} avail@0", flush=True)
        if not vectors:
            # still write empty so latch can no-op
            base = np.load(ECAPA / f"{session}.npz")
            np.savez(
                dest,
                start=base["start"],
                end=base["end"],
                fitz=np.full(len(base["end"]), np.nan, dtype=np.float32),
                people5=base["people"].astype(np.float32),
                enroll=[],
            )
            paths[session] = dest
            print(f"{session}: no Fitz enroll vectors", flush=True)
            continue

        base = np.load(ECAPA / f"{session}.npz")
        ends = np.asarray(base["end"], dtype=np.float64)
        starts = np.asarray(base["start"], dtype=np.float64)
        people5 = np.asarray(base["people"], dtype=np.float64)
        audio, audio_start = _session_audio(session)
        windows = [(float(s - audio_start), float(e - audio_start)) for s, e in zip(starts, ends)]
        print(f"{session} embed {len(windows)} windows for Fitz", flush=True)
        embedded = _embed_windows(audio, windows, encoder, 16)
        units = embedded / np.maximum(np.linalg.norm(embedded, axis=1, keepdims=True), 1e-12)
        fitz = np.full(len(ends), np.nan, dtype=np.float64)
        order = np.argsort(ends)
        running = np.zeros(units.shape[1], dtype=np.float64)
        cursor = 0
        ready_arr = np.asarray(ready, dtype=np.float64)
        vec_stack = np.stack(vectors)
        rank = np.argsort(ready_arr)
        ready_arr = ready_arr[rank]
        vec_stack = vec_stack[rank]
        for index in order:
            moment = float(ends[index])
            while cursor < len(ready_arr) and ready_arr[cursor] <= moment + 1e-9:
                running += vec_stack[cursor]
                cursor += 1
            if cursor == 0:
                continue
            proto = running / max(np.linalg.norm(running), 1e-12)
            fitz[index] = float(units[index] @ proto)
        np.savez(
            dest,
            start=starts,
            end=ends,
            fitz=fitz.astype(np.float32),
            people5=people5.astype(np.float32),
            enroll=ENROLL,
        )
        paths[session] = dest
        finite = np.isfinite(fitz)
        print(
            f"  fitz ge_line={int(np.sum(fitz[finite] >= LINE))} / {int(finite.sum())} "
            f"max={float(np.nanmax(fitz)):.3f}",
            flush=True,
        )
    return paths


def _hot_ends(session: str, margin: float, paths: dict[str, Path]) -> np.ndarray:
    path = paths.get(session)
    if path is None or not path.is_file():
        return np.array([], dtype=float)
    data = np.load(path)
    ends = data["end"]
    fitz = data["fitz"].astype(np.float64)
    people5 = data["people5"].astype(np.float64)
    order = np.argsort(ends)
    ends = ends[order]
    fitz = fitz[order]
    people5 = people5[order]
    with np.errstate(invalid="ignore"):
        rival = np.nanmax(people5, axis=1)
    hot = np.isfinite(fitz) & (fitz >= LINE) & ((fitz - np.nan_to_num(rival, nan=-1.0)) >= margin)
    return ends[hot]


def _apply(times, probs, hot_ends):
    rows = decisions(times.tolist(), probs.tolist(), **CONTROLLER)
    covering = np.array([r["action"] == "cover" for r in rows], dtype=bool)
    right = np.searchsorted(hot_ends, times, side="right")
    left = np.searchsorted(hot_ends, times - HOLD_S, side="left")
    out = np.array(probs, dtype=np.float64, copy=True)
    out[covering & (right > left)] = 0.0
    return out


def _span_muted(game: dict, start: float, end: float) -> float:
    total = 0.0
    for ep in game.get("episodes", []):
        total += max(0.0, min(float(ep["end_s"]), end) - max(float(ep["start_s"]), start))
    return round(total, 2)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    print("load encoder", flush=True)
    encoder = _load_encoder(MODEL)
    paths = build_cache(encoder)

    # probe Odell / fitz desk on 09-24
    probe = {}
    if "hush_20260924_220624" in paths:
        data = np.load(paths["hush_20260924_220624"])
        ends = data["end"]
        fitz = data["fitz"]
        for name, a, b in [("fitz_enroll", 6599.5, 6605.7), ("odell", 7035.0, 7095.2), ("odell_chunk", 7047.5, 7065.0)]:
            m = (ends >= a) & (ends <= b) & np.isfinite(fitz)
            vals = fitz[m]
            probe[name] = {
                "n": int(m.sum()),
                "ge_line": int(np.sum(vals >= LINE)) if vals.size else 0,
                "max": None if not vals.size else round(float(np.max(vals)), 3),
                "mean": None if not vals.size else round(float(np.mean(vals)), 3),
            }
    (OUT / "fitz_span_probe.json").write_text(json.dumps(probe, indent=2), encoding="utf-8")
    print("probe", json.dumps(probe), flush=True)

    frozen = load_frozen_probs(EVAL)
    stack = {s: (t, apply_research_latch(s, t, p)) for s, (t, p) in frozen.items()}
    cool = {s: (t, apply_research_latch(s, t, p, with_voice=False)) for s, (t, p) in frozen.items()}
    stack_rep = score_run("stack_baseline", stack, OUT)
    cool_rep = score_run("cooldown_only", cool, OUT)
    base = stack_rep["aggregate"]
    cool_a = cool_rep["aggregate"]

    decisions_out = {}
    print(f"{'run':28} {'cov':7} {'desk':7} {'odell':7} {'amex':7} {'chilis':7}", flush=True)
    print(
        f"{'stack':28} {base['non_broadcast_coverage']:7.4f} {base['cells']['desk_s']:7.1f} "
        f"{base['focus']['hush_20260924_220624']['odell']:7.1f} "
        f"{base['focus']['hush_20261008_205100']['amex']:7.1f} "
        f"{base['focus']['hush_20260924_220624']['chilis']:7.1f}",
        flush=True,
    )

    for margin in MARGINS:
        name = f"stack_fitz_m{margin:.2f}"
        keyed = {}
        for session, (t, p) in stack.items():
            hot = _hot_ends(session, margin, paths)
            keyed[session] = (t, _apply(t, p, hot))
        other_rep = score_run(name, keyed, OUT)
        other = other_rep["aggregate"]
        d = {
            "cov_delta_vs_stack": round(other["non_broadcast_coverage"] - base["non_broadcast_coverage"], 4),
            "cov_delta_vs_cool": round(other["non_broadcast_coverage"] - cool_a["non_broadcast_coverage"], 4),
            "desk_delta": round(other["cells"]["desk_s"] - base["cells"]["desk_s"], 1),
            "odell_delta": round(
                other["focus"]["hush_20260924_220624"]["odell"] - base["focus"]["hush_20260924_220624"]["odell"],
                2,
            ),
            "amex_delta": round(
                other["focus"]["hush_20261008_205100"]["amex"] - base["focus"]["hush_20261008_205100"]["amex"],
                2,
            ),
            "chilis_delta": round(
                other["focus"]["hush_20260924_220624"]["chilis"] - base["focus"]["hush_20260924_220624"]["chilis"],
                2,
            ),
        }
        g24 = next(g for g in other_rep["games"] if g["session"] == "hush_20260924_220624")
        g24b = next(g for g in stack_rep["games"] if g["session"] == "hush_20260924_220624")
        d["odell_chunk_muted"] = _span_muted(g24, 7047.5, 7065.0)
        d["odell_chunk_base"] = _span_muted(g24b, 7047.5, 7065.0)
        d["fitz_desk_muted"] = _span_muted(g24, 6599.5, 6605.7)
        d["fitz_desk_base"] = _span_muted(g24b, 6599.5, 6605.7)

        reasons = []
        decision = "KEEP"
        if -d["cov_delta_vs_cool"] > 0.02:
            decision = "REJECT"
            reasons.append(f"cumulative cov vs cooldown {-d['cov_delta_vs_cool']:.4f} > 0.02")
        if d["amex_delta"] < -2 or d["chilis_delta"] < -2:
            decision = "REJECT"
            reasons.append(f"spot leak amex={d['amex_delta']} chilis={d['chilis_delta']}")
        if d["desk_delta"] > -3 and d["odell_delta"] > -1:
            decision = "REJECT"
            reasons.append(f"not materially freed desk={d['desk_delta']} odell={d['odell_delta']}")
        if decision == "KEEP" and not reasons:
            reasons.append("cumulative cov held; spots held; desk/Odell freed")
        decisions_out[name] = {"run": name, "decision": decision, "reasons": reasons, "delta": d}
        print(
            f"{name:28} {other['non_broadcast_coverage']:7.4f} {other['cells']['desk_s']:7.1f} "
            f"{other['focus']['hush_20260924_220624']['odell']:7.1f} "
            f"{other['focus']['hush_20261008_205100']['amex']:7.1f} "
            f"{other['focus']['hush_20260924_220624']['chilis']:7.1f}  {decision}",
            flush=True,
        )

    summary = {"enroll": ENROLL, "probe": probe, "decisions": decisions_out}
    (OUT / "SUMMARY.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    lines = ["# Fitz cover on research stack", ""]
    for name, row in decisions_out.items():
        lines += [
            f"## {name}",
            f"- **{row['decision']}**",
            *[f"- {r}" for r in row["reasons"]],
            f"- `{json.dumps(row['delta'])}`",
            "",
        ]
    (OUT / "KEEP_REJECT.md").write_text("\n".join(lines), encoding="utf-8")
    print("WROTE", OUT, flush=True)


if __name__ == "__main__":
    main()
