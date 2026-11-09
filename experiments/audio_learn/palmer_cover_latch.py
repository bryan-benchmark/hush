"""Cover-only James Palmer panel on champion research latch.

Palmer is not in the 5-name ECAPA cache. This builds a causal same-tape
prototype from the owner deep labels (intro after Clarissa/Whit handoff),
scores cosine on speech windows, and runs product scorecard KEEP/REJECT.

Live / frozen head / holdouts untouched.
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
from experiments.audio_learn.product_scorecard import DATA, FROZEN, load_frozen_probs, score_run
from experiments.audio_learn.research_latch import apply_research_latch
from experiments.audio_learn.splits import EVAL
from experiments.audio_learn.studio_fit import CONTROLLER
from experiments.ledger import RECORDINGS
from experiments.nfl75.protect_embed import MODEL, SR, _clip, _embed_windows, _load_encoder
from hush.audio import RAW_SR, analysis_pieces, find_session, load_session, read_stereo, resample_concat

OUT = DATA / "palmer_cover_latch"

# Causal enroll: cosine hunt vs injury Palmer proto found a hot run 6220–6253
# (before injury 6267). 6180 "Palmer report" focus is Clarissa/Whit handoff only
# (max cos 0.13). Enroll the open of that run so injury + desk #5 can clear.
ENROLL = (
    {
        "session": "hush_20260924_220624",
        "play_start": 6220.1,
        "duration": 15.0,
        "available_at": 6235.1,
        "note": "earlier_palmer_hunt hot run open (cos~0.75 vs injury Palmer)",
    },
)
MARGINS = (0.00, 0.10, 0.15)


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


def build_palmer_cache(encoder) -> dict[str, Path]:
    OUT.mkdir(parents=True, exist_ok=True)
    paths = {}
    # enroll vectors
    vectors = []
    ready = []
    for row in ENROLL:
        audio = _clip(row["session"], float(row["play_start"]), float(row["duration"]))
        vec = _embed_windows(audio, [(0.0, len(audio) / SR)], encoder, 1)[0]
        vectors.append(vec)
        ready.append(float(row["available_at"]))
        print(f"enroll Palmer {row['play_start']}-{row['play_start']+row['duration']} avail@{row['available_at']}", flush=True)

    for session in EVAL:
        dest = OUT / f"{session}_palmer.npz"
        if dest.is_file():
            print(f"cached {dest.name}", flush=True)
            paths[session] = dest
            continue
        # reuse speech window ends from existing ECAPA cache
        base = np.load(ECAPA / f"{session}.npz")
        ends = np.asarray(base["end"], dtype=np.float64)
        starts = np.asarray(base["start"], dtype=np.float64)
        people5 = np.asarray(base["people"], dtype=np.float64)
        audio, audio_start = _session_audio(session)
        # windows as offsets into audio buffer
        windows = [(float(s - audio_start), float(e - audio_start)) for s, e in zip(starts, ends)]
        print(f"{session} embed {len(windows)} windows for Palmer", flush=True)
        embedded = _embed_windows(audio, windows, encoder, 16)
        units = embedded / np.maximum(np.linalg.norm(embedded, axis=1, keepdims=True), 1e-12)
        palmer = np.full(len(ends), np.nan, dtype=np.float64)
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
            palmer[index] = float(units[index] @ proto)
        np.savez(
            dest,
            start=starts,
            end=ends,
            palmer=palmer.astype(np.float32),
            people5=people5.astype(np.float32),
            enroll=ENROLL,
        )
        paths[session] = dest
        finite = np.isfinite(palmer)
        print(
            f"  palmer ge_line={int(np.sum(palmer[finite] >= LINE))} / {int(finite.sum())} "
            f"max={float(np.nanmax(palmer)):.3f}",
            flush=True,
        )
    return paths


def _hot_ends(session: str, margin: float, paths: dict[str, Path]) -> np.ndarray:
    data = np.load(paths[session])
    ends = data["end"]
    palmer = data["palmer"].astype(np.float64)
    people5 = data["people5"].astype(np.float64)
    order = np.argsort(ends)
    ends = ends[order]
    palmer = palmer[order]
    people5 = people5[order]
    with np.errstate(invalid="ignore"):
        rival = np.nanmax(people5, axis=1)
    hot = np.isfinite(palmer) & (palmer >= LINE) & ((palmer - np.nan_to_num(rival, nan=-1.0)) >= margin)
    return ends[hot]


def _apply(times, probs, hot_ends):
    rows = decisions(times.tolist(), probs.tolist(), **CONTROLLER)
    covering = np.array([r["action"] == "cover" for r in rows], dtype=bool)
    right = np.searchsorted(hot_ends, times, side="right")
    left = np.searchsorted(hot_ends, times - HOLD_S, side="left")
    out = np.array(probs, dtype=np.float64, copy=True)
    out[covering & (right > left)] = 0.0
    return out


def _delta(base: dict, other: dict) -> dict:
    return {
        "cov_delta": round((other["non_broadcast_coverage"] or 0) - (base["non_broadcast_coverage"] or 0), 4),
        "broadcast_muted_delta": round(
            (other["broadcast_muted_s"] or 0) - (base["broadcast_muted_s"] or 0), 1
        ),
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


def _focus_span_muted(game: dict, start: float, end: float) -> float:
    total = 0.0
    for ep in game.get("episodes", []):
        total += max(0.0, min(ep["end_s"], end) - max(ep["start_s"], start))
    return round(total, 2)


def _decide(name: str, base: dict, other: dict, injury_delta: float, desk5_delta: float) -> dict:
    d = _delta(base, other)
    d["injury_muted_delta"] = round(injury_delta, 2)
    d["desk5_muted_delta"] = round(desk5_delta, 2)
    reasons = []
    decision = "KEEP"
    if -d["cov_delta"] > 0.02:
        decision = "REJECT"
        reasons.append(f"coverage drop {-d['cov_delta']:.4f} > 0.02")
    if d["amex_delta"] < -2 or d["chilis_delta"] < -2:
        decision = "REJECT"
        reasons.append(f"spot leak amex={d['amex_delta']} chilis={d['chilis_delta']}")
    # Target: free Palmer injury / desk5 mass
    if injury_delta > -5 and desk5_delta > -5 and d["desk_delta"] > -10:
        decision = "REJECT"
        reasons.append(
            f"Palmer targets not freed injury_d={injury_delta} desk5_d={desk5_delta} desk_d={d['desk_delta']}"
        )
    if decision == "KEEP" and not reasons:
        reasons.append("coverage held; spots held; Palmer desk freed")
    return {"run": name, "decision": decision, "reasons": reasons, "delta": d}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    print("load encoder", flush=True)
    encoder = _load_encoder(MODEL)
    paths = build_palmer_cache(encoder)

    # probe injury / #5 / enroll region
    probe = {}
    data = np.load(paths["hush_20260924_220624"])
    ends = data["end"]
    palmer = data["palmer"]
    for name, a, b in [("enroll_src", 6194, 6207.8), ("injury", 6267.8, 6287.2), ("desk5", 6315.2, 6336.5)]:
        m = (ends >= a) & (ends <= b) & np.isfinite(palmer)
        vals = palmer[m]
        probe[name] = {
            "n": int(m.sum()),
            "ge_line": int(np.sum(vals >= LINE)) if vals.size else 0,
            "max": None if not vals.size else round(float(np.max(vals)), 3),
            "mean": None if not vals.size else round(float(np.mean(vals)), 3),
        }
    (OUT / "palmer_span_probe.json").write_text(json.dumps(probe, indent=2), encoding="utf-8")
    print("probe", json.dumps(probe), flush=True)

    frozen = load_frozen_probs()
    champion = {}
    for session in EVAL:
        t, p = frozen[session]
        champion[session] = (t, apply_research_latch(session, t, p))
    base_rep = score_run("champion", champion, OUT)
    base = base_rep["aggregate"]
    g24b = next(g for g in base_rep["games"] if g["session"] == "hush_20260924_220624")
    injury_base = _focus_span_muted(g24b, 6267.8, 6287.2)
    desk5_base = _focus_span_muted(g24b, 6315.2, 6336.5)

    decisions_out = {}
    aggregates = {"champion": base}
    print(f"{'run':32} {'cov':7} {'desk':7} {'odell':7} {'amex':7} {'chilis':7}", flush=True)
    f24 = base["focus"]["hush_20260924_220624"]
    f08 = base["focus"]["hush_20261008_205100"]
    print(
        f"{'champion':32} {base['non_broadcast_coverage']:7.4f} {base['cells']['desk_s']:7.1f} "
        f"{f24['odell']:7.1f} {f08['amex']:7.1f} {f24['chilis']:7.1f}",
        flush=True,
    )

    for margin in MARGINS:
        name = f"champion_palmer_m{margin:.2f}"
        probs = {}
        for session in EVAL:
            t, p = champion[session]
            hot = _hot_ends(session, margin, paths) if session in paths else np.array([], dtype=float)
            probs[session] = (t, _apply(t, p, hot))
        other_rep = score_run(name, probs, OUT)
        other = other_rep["aggregate"]
        aggregates[name] = other
        g24 = next(g for g in other_rep["games"] if g["session"] == "hush_20260924_220624")
        injury_now = _focus_span_muted(g24, 6267.8, 6287.2)
        desk5_now = _focus_span_muted(g24, 6315.2, 6336.5)
        decisions_out[name] = _decide(
            name,
            base,
            other,
            injury_now - injury_base,
            desk5_now - desk5_base,
        )
        decisions_out[name]["delta"]["injury_muted_s"] = injury_now
        decisions_out[name]["delta"]["desk5_muted_s"] = desk5_now
        decisions_out[name]["delta"]["injury_muted_base"] = injury_base
        decisions_out[name]["delta"]["desk5_muted_base"] = desk5_base
        f24 = other["focus"]["hush_20260924_220624"]
        f08 = other["focus"]["hush_20261008_205100"]
        print(
            f"{name:32} {other['non_broadcast_coverage']:7.4f} {other['cells']['desk_s']:7.1f} "
            f"{f24['odell']:7.1f} {f08['amex']:7.1f} {f24['chilis']:7.1f}  "
            f"{decisions_out[name]['decision']}",
            flush=True,
        )

    summary = {
        "enroll": ENROLL,
        "probe": probe,
        "line": LINE,
        "margins": list(MARGINS),
        "decisions": decisions_out,
        "aggregates": aggregates,
    }
    (OUT / "SUMMARY.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    lines = ["# Palmer cover latch vs champion", ""]
    for name, row in decisions_out.items():
        lines.append(f"## {name}")
        lines.append(f"- **{row['decision']}**")
        for reason in row["reasons"]:
            lines.append(f"- {reason}")
        lines.append(f"- `{json.dumps(row['delta'])}`")
        lines.append("")
    (OUT / "KEEP_REJECT.md").write_text("\n".join(lines), encoding="utf-8")
    print("WROTE", OUT / "KEEP_REJECT.md", flush=True)


if __name__ == "__main__":
    main()
