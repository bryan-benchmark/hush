"""Gate Clarissa clears when ASR hears ad/sponsorship language.

KEEP research path: blocked spans are written to blocked_spans.json and
consumed by research_latch (Clarissa clears skipped inside those windows).
Does not touch ohush_live. Rebuild cache with this module; --reuse reclassifies.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

import numpy as np

from experiments.audio_learn.broadcast_labels import SHOW_RE
from experiments.audio_learn.controller import decisions
from experiments.audio_learn.desk_voice_hold import HOLD_S, LINE
from experiments.audio_learn.product_scorecard import DATA, load_frozen_probs, score_run
from experiments.audio_learn.research_latch import (
    FITZ_CACHE,
    FITZ_MARGIN,
    PALMER_CACHE,
    PALMER_MARGIN,
    VOICE_PANELS,
    _side_hot_ends,
    _voice_hot_ends,
    apply_research_latch,
)
from experiments.audio_learn.splits import EVAL
from experiments.audio_learn.studio_fit import CONTROLLER
from experiments.audio_learn.voice_hot_fold_score import latch_audit
from experiments.audio_learn.product_scorecard import load_accepted
from tools.gpu_lab.audio_load import load_coverage

OUT = DATA / "clarissa_ad_gate"
BLIND = "hush_20261015_210805"
# Strong sponsorship / sportsbook lexicon only. Bare "visit"/"learn more" false-hit desk.
STRONG_AD_RE = re.compile(
    r"\b("
    r"draft\s*kings|draftkings|fan\s*duel|fanduel|betmgm|caesars|"
    r"chase\s*sapphire|sapphire\s*reserve|pnc\s*bank|energizer|"
    r"royal\s*caribbean|apple\s*watch|"
    r"sports\s*book|sportsbook|same\s*game\s*parlay|promo\s*code|"
    r"bonus\s*bet|download\s*the\s*app|crown\s*is\s*yours|"
    r"gambling\s*problem|must\s*be\s*21|terms\s*apply|"
    r"sponsored\s*by|brought\s*to\s*you|drink\s*responsibly|"
    r"amex|american\s*express|geico|progressive|state\s*farm|"
    r"chili'?s|mcdonald|toyota|chevrolet|bud\s*light"
    r")\b",
    re.I,
)


def _merge(ranges: list[tuple[float, float]], pad: float = 0.0) -> list[tuple[float, float]]:
    if not ranges:
        return []
    ordered = sorted((a - pad, b + pad) for a, b in ranges)
    out = [list(ordered[0])]
    for a, b in ordered[1:]:
        if a <= out[-1][1] + 0.5:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(float(a), float(b)) for a, b in out]


def clarissa_cover_spans(session: str, times: np.ndarray, cool_p: np.ndarray) -> list[tuple[float, float]]:
    """Spans where cool is covering and Clarissa panel is hot."""
    rows = decisions(times.tolist(), cool_p.tolist(), **CONTROLLER)
    covering = np.array([r["action"] == "cover" for r in rows], dtype=bool)
    hot = _voice_hot_ends(session, "Clarissa Thompson", 0.10)
    if hot.size == 0:
        return []
    right = np.searchsorted(hot, times, side="right")
    left = np.searchsorted(hot, times - HOLD_S, side="left")
    mask = covering & (right > left)
    if not np.any(mask):
        return []
    t = times[mask]
    spans: list[tuple[float, float]] = []
    a = float(t[0])
    prev = float(t[0])
    for x in t[1:]:
        x = float(x)
        if x - prev > 0.6:
            spans.append((a, prev + 0.25))
            a = x
        prev = x
    spans.append((a, prev + 0.25))
    return _merge(spans)


def whisper_span(session: str, a: float, b: float, model) -> str:
    mid = 0.5 * (a + b)
    # Cap whisper work; long Clarissa runs sample up to 3 windows.
    windows = []
    if b - a <= 14.0:
        windows.append((a, b))
    else:
        windows.append((a, min(b, a + 8.0)))
        windows.append((max(a, mid - 4.0), min(b, mid + 4.0)))
        windows.append((max(a, b - 8.0), b))
    texts = []
    for w0, w1 in windows:
        if w1 - w0 < 1.5:
            continue
        audio = load_coverage(session, w0, w1)
        segments, _info = model.transcribe(audio, vad_filter=True, beam_size=1)
        texts.append(" ".join(seg.text.strip() for seg in segments if seg.text.strip()))
    return " ".join(t for t in texts if t)


def classify_text(text: str) -> tuple[str, str]:
    if not text.strip():
        return "empty", "empty transcript"
    ad_hits = STRONG_AD_RE.findall(text)
    show_hits = SHOW_RE.findall(text)
    ad_u = sorted({str(x).lower() for x in ad_hits})
    show_u = sorted({str(x).lower() for x in show_hits})
    if ad_u and not show_u:
        return "block_clarissa", f"ad keywords: {ad_u[:6]}"
    if show_u and not ad_u:
        return "allow_clarissa", f"show keywords: {show_u[:6]}"
    if ad_u and show_u:
        # Prefer blocking Clarissa when brand language is present (sponsorship VO).
        return "block_clarissa", f"mixed ad={ad_u[:4]} show={show_u[:4]}"
    return "allow_clarissa", "no strong keywords"


def build_blocks(session: str, times: np.ndarray, cool_p: np.ndarray, model) -> list[dict]:
    spans = clarissa_cover_spans(session, times, cool_p)
    rows = []
    for a, b in spans:
        started = time.perf_counter()
        try:
            text = whisper_span(session, a, b, model)
            err = None
        except Exception as exc:  # noqa: BLE001 — probe keeps going
            text = ""
            err = str(exc)
        decision, reason = classify_text(text)
        rows.append(
            {
                "session": session,
                "start_s": round(a, 3),
                "end_s": round(b, 3),
                "dur_s": round(b - a, 3),
                "text": text[:400],
                "decision": decision if err is None else "allow_clarissa",
                "reason": reason if err is None else f"whisper_failed:{err}",
                "whisper_s": round(time.perf_counter() - started, 2),
            }
        )
    return rows


def _clarissa_hot_gated(session: str, blocked: list[tuple[float, float]]) -> np.ndarray:
    hot = _voice_hot_ends(session, "Clarissa Thompson", 0.10)
    if hot.size == 0 or not blocked:
        return hot
    keep = []
    for te in hot:
        if any(a <= float(te) < b for a, b in blocked):
            continue
        keep.append(float(te))
    return np.asarray(keep, dtype=float)


def apply_gated_latch(
    session: str,
    times: np.ndarray,
    probs: np.ndarray,
    blocked: list[tuple[float, float]],
) -> np.ndarray:
    """Cool + Whit/Palmer/Fitz + gated Clarissa."""
    out = apply_research_latch(session, times, probs, with_voice=False)
    rows = decisions(times.tolist(), out.tolist(), **CONTROLLER)
    covering = np.array([r["action"] == "cover" for r in rows], dtype=bool)
    parts = [
        _clarissa_hot_gated(session, blocked),
        _voice_hot_ends(session, "Andrew Whitworth", 0.15),
        _side_hot_ends(session, PALMER_CACHE, "palmer", PALMER_MARGIN),
        _side_hot_ends(session, FITZ_CACHE, "fitz", FITZ_MARGIN),
    ]
    parts = [p for p in parts if p.size]
    if not parts:
        return out
    hot = np.unique(np.concatenate(parts))
    right = np.searchsorted(hot, times, side="right")
    left = np.searchsorted(hot, times - HOLD_S, side="left")
    out = np.array(out, dtype=np.float64, copy=True)
    out[covering & (right > left)] = 0.0
    return out


def _decide(delta: dict) -> tuple[str, list[str]]:
    decision = "KEEP"
    reasons = []
    if -delta["cov_delta"] > 0.02:
        decision = "REJECT"
        reasons.append(f"coverage drop {-delta['cov_delta']:.4f} > 0.02")
    if delta["amex_delta"] < -2 or delta["chilis_delta"] < -2:
        decision = "REJECT"
        reasons.append(f"spot leak amex={delta['amex_delta']} chilis={delta['chilis_delta']}")
    if decision == "KEEP":
        reasons.append("coverage held; spots held; gated Clarissa still frees desk vs cooldown")
    return decision, reasons


def main() -> None:
    import sys

    OUT.mkdir(parents=True, exist_ok=True)
    reuse = "--reuse" in sys.argv
    frozen = load_frozen_probs(tuple(list(EVAL) + [BLIND]))
    cool = {s: (t, apply_research_latch(s, t, p, with_voice=False)) for s, (t, p) in frozen.items()}

    all_blocks: list[dict] = []
    blocked_by_session: dict[str, list[tuple[float, float]]] = {}
    cache_path = OUT / "clarissa_cover_transcripts.jsonl"
    if reuse and cache_path.is_file():
        print("reclassify cached Clarissa transcripts...", flush=True)
        for line in cache_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            decision, reason = classify_text(row.get("text") or "")
            if decision == "empty":
                decision = "allow_clarissa"
            row["decision"] = decision
            row["reason"] = reason
            all_blocks.append(row)
    else:
        from faster_whisper import WhisperModel

        model = WhisperModel("base.en", device="cpu", compute_type="int8", cpu_threads=4)
        for session, (times, _) in cool.items():
            print(f"whisper clarissa covers {session}...", flush=True)
            rows = build_blocks(session, times, cool[session][1], model)
            all_blocks.extend(rows)
            print(
                f"  spans={len(rows)} block={sum(1 for r in rows if r['decision']=='block_clarissa')} "
                f"allow={sum(1 for r in rows if r['decision']=='allow_clarissa')}",
                flush=True,
            )
        cache_path.write_text("".join(json.dumps(r) + "\n" for r in all_blocks), encoding="utf-8")

    for row in all_blocks:
        if row["decision"] != "block_clarissa":
            continue
        blocked_by_session.setdefault(row["session"], []).append((row["start_s"], row["end_s"]))
    for session, spans in list(blocked_by_session.items()):
        blocked_by_session[session] = _merge(spans)
        print(
            f"{session}: blocked_spans={len(blocked_by_session[session])}",
            flush=True,
        )

    # Product EVAL score
    eval_cool = {s: cool[s] for s in EVAL}
    eval_stack = {
        s: (cool[s][0], apply_gated_latch(s, cool[s][0], frozen[s][1], blocked_by_session.get(s, [])))
        for s in EVAL
    }
    baseline = {
        s: (cool[s][0], apply_research_latch(s, cool[s][0], frozen[s][1], with_voice=True))
        for s in EVAL
    }
    cool_rep = score_run("cooldown_8s_only", eval_cool, OUT)
    gate_rep = score_run("clarissa_ad_gated", eval_stack, OUT)
    base_rep = score_run("research_stack_baseline", baseline, OUT)
    cool_a, gate_a, base_a = cool_rep["aggregate"], gate_rep["aggregate"], base_rep["aggregate"]

    def delta_vs(cool_agg, other):
        return {
            "cov_delta": round(other["non_broadcast_coverage"] - cool_agg["non_broadcast_coverage"], 4),
            "broadcast_muted_delta": round(other["broadcast_muted_s"] - cool_agg["broadcast_muted_s"], 1),
            "desk_delta": round(other["cells"]["desk_s"] - cool_agg["cells"]["desk_s"], 1),
            "odell_delta": round(
                other["focus"]["hush_20260924_220624"]["odell"] - cool_agg["focus"]["hush_20260924_220624"]["odell"],
                2,
            ),
            "amex_delta": round(
                other["focus"]["hush_20261008_205100"]["amex"] - cool_agg["focus"]["hush_20261008_205100"]["amex"],
                2,
            ),
            "chilis_delta": round(
                other["focus"]["hush_20260924_220624"]["chilis"] - cool_agg["focus"]["hush_20260924_220624"]["chilis"],
                2,
            ),
        }

    gate_delta = delta_vs(cool_a, gate_a)
    base_delta = delta_vs(cool_a, base_a)
    decision, reasons = _decide(gate_delta)

    # Blind voice-hot audit vs ungated stack
    accepted = load_accepted()
    bt, bp = frozen[BLIND]
    cool_b = cool[BLIND][1]
    gate_b = apply_gated_latch(BLIND, bt, bp, blocked_by_session.get(BLIND, []))
    base_b = apply_research_latch(BLIND, bt, bp, with_voice=True)
    audit_gate = latch_audit(accepted, bt, cool_b, gate_b)
    audit_base = latch_audit(accepted, bt, cool_b, base_b)

    summary = {
        "probe": "clarissa_ad_keyword_gate",
        "panels": [{"name": n, "margin": m} for n, m in VOICE_PANELS]
        + [
            {"name": "James Palmer", "margin": PALMER_MARGIN},
            {"name": "Ryan Fitzpatrick", "margin": FITZ_MARGIN},
        ],
        "clarissa_rule": "m0.10 only if whisper window is not ad-keyword-positive",
        "blocked_spans": {
            s: [{"start_s": a, "end_s": b} for a, b in blocked_by_session.get(s, [])] for s in list(EVAL) + [BLIND]
        },
        "n_transcript_spans": len(all_blocks),
        "n_blocked": sum(1 for r in all_blocks if r["decision"] == "block_clarissa"),
        "decision_vs_cooldown": {"decision": decision, "reasons": reasons, "delta": gate_delta},
        "baseline_stack_delta": base_delta,
        "cooldown_8s_only": cool_a,
        "clarissa_ad_gated": gate_a,
        "research_stack_baseline": base_a,
        "blind_voice_hot_audit": {"gated": audit_gate, "baseline_stack": audit_base},
        "line": LINE,
        "hold_s": HOLD_S,
        "live": False,
    }
    (OUT / "SUMMARY.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    md = [
        "# Clarissa ad-keyword gate",
        "",
        "Clarissa m0.10 clears only when whisper is not ad-keyword-positive. Whit/Palmer/Fitz unchanged.",
        "",
        f"## vs cooldown_8s: **{decision}**",
        *[f"- {r}" for r in reasons],
        f"- gated delta `{json.dumps(gate_delta)}`",
        f"- baseline stack delta `{json.dumps(base_delta)}`",
        "",
        f"## Absolute gated",
        f"- coverage {gate_a['non_broadcast_coverage']} (cool {cool_a['non_broadcast_coverage']}, baseline {base_a['non_broadcast_coverage']})",
        f"- desk_s {gate_a['cells']['desk_s']} (cool {cool_a['cells']['desk_s']}, baseline {base_a['cells']['desk_s']})",
        f"- broadcast_muted_s {gate_a['broadcast_muted_s']}",
        "",
        f"## Blind 10-15 voice-hot latch audit",
        f"- gated `{json.dumps(audit_gate)}`",
        f"- baseline `{json.dumps(audit_base)}`",
        "",
        f"Blocked {summary['n_blocked']} / {summary['n_transcript_spans']} Clarissa-cover spans.",
        "",
        "Not wired to ohush_live.",
    ]
    (OUT / "KEEP_REJECT.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(json.dumps(summary["decision_vs_cooldown"], indent=2), flush=True)
    print("blind gated", audit_gate, flush=True)
    print("blind baseline", audit_base, flush=True)
    print("WROTE", OUT, flush=True)


if __name__ == "__main__":
    main()
