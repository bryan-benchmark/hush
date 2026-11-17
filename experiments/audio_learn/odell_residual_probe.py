"""Probe Odell residual under KEEP stack without Michaels/Gonzalez.

Variants (cover-only, Odell span emphasis reported; product scored full-tape):
  1) baseline gated stack
  2) Whit margin 0.10 (was 0.15) globally on stack
  3) Whit margin 0.10 only while inside Odell desk span (local)
  4) Clarissa∪Whit both required (tandem) — expect worse on Odell; control
  5) HOLD_S +1s for Whit/Clarissa only (2s → treat as 3s via duplicated ends)

KEEP if cov drop vs cool ≤0.02 and spots held. Prefer Odell mute reduction.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from experiments.audio_learn.boundary_recovery import apply_cooldown
from experiments.audio_learn.controller import decisions
from experiments.audio_learn.desk_voice_hold import HOLD_S
from experiments.audio_learn.product_scorecard import DATA, load_frozen_probs, score_run
from experiments.audio_learn.research_latch import (
    FITZ_CACHE,
    FITZ_MARGIN,
    PALMER_CACHE,
    PALMER_MARGIN,
    COOLDOWN_S,
    _clarissa_blocked_spans,
    _filter_blocked,
    _side_hot_ends,
    _voice_hot_ends,
    non_broadcast_ends,
)
from experiments.audio_learn.splits import EVAL
from experiments.audio_learn.studio_fit import CONTROLLER

OUT = DATA / "odell_residual_probe"
ODELL = ("hush_20260924_220624", 7035.0, 7095.2)


def _apply(
    session: str,
    times: np.ndarray,
    probs: np.ndarray,
    *,
    whit_margin: float = 0.15,
    whit_local_margin: float | None = None,
    whit_local_span: tuple[float, float] | None = None,
    tandem_clarissa_whit: bool = False,
    hold_s: float = HOLD_S,
) -> np.ndarray:
    out = apply_cooldown(times, np.asarray(probs, dtype=np.float64), non_broadcast_ends(session), COOLDOWN_S)
    rows = decisions(times.tolist(), out.tolist(), **CONTROLLER)
    covering = np.array([r["action"] == "cover" for r in rows], dtype=bool)

    clar = _filter_blocked(_voice_hot_ends(session, "Clarissa Thompson", 0.10), _clarissa_blocked_spans(session))
    if whit_local_margin is not None and whit_local_span is not None and session == ODELL[0]:
        whit_lo = _voice_hot_ends(session, "Andrew Whitworth", whit_local_margin)
        whit_hi = _voice_hot_ends(session, "Andrew Whitworth", whit_margin)
        a0, a1 = whit_local_span
        whit = np.unique(
            np.concatenate(
                [
                    whit_hi[(whit_hi < a0) | (whit_hi >= a1)] if whit_hi.size else np.array([], dtype=float),
                    whit_lo[(whit_lo >= a0) & (whit_lo < a1)] if whit_lo.size else np.array([], dtype=float),
                ]
            )
        )
    else:
        whit = _voice_hot_ends(session, "Andrew Whitworth", whit_margin)
    palm = _side_hot_ends(session, PALMER_CACHE, "palmer", PALMER_MARGIN)
    fitz = _side_hot_ends(session, FITZ_CACHE, "fitz", FITZ_MARGIN)

    if tandem_clarissa_whit:
        # clear only when both Clarissa and Whit are recent
        parts = []
        if clar.size and whit.size:
            # mark times where both holds fire
            cr = np.searchsorted(clar, times, side="right")
            cl = np.searchsorted(clar, times - hold_s, side="left")
            wr = np.searchsorted(whit, times, side="right")
            wl = np.searchsorted(whit, times - hold_s, side="left")
            both = covering & (cr > cl) & (wr > wl)
            out = np.array(out, dtype=np.float64, copy=True)
            out[both] = 0.0
            # still allow Palmer/Fitz alone
            for side in (palm, fitz):
                if side.size == 0:
                    continue
                r = np.searchsorted(side, times, side="right")
                l = np.searchsorted(side, times - hold_s, side="left")
                out[covering & (r > l)] = 0.0
            return out
        hot = np.unique(np.concatenate([p for p in (palm, fitz) if p.size])) if (palm.size or fitz.size) else np.array([], dtype=float)
    else:
        parts = [p for p in (clar, whit, palm, fitz) if p.size]
        hot = np.unique(np.concatenate(parts)) if parts else np.array([], dtype=float)

    if hot.size == 0:
        return out
    right = np.searchsorted(hot, times, side="right")
    left = np.searchsorted(hot, times - hold_s, side="left")
    out = np.array(out, dtype=np.float64, copy=True)
    out[covering & (right > left)] = 0.0
    return out


def _delta(cool_a: dict, other: dict) -> dict:
    return {
        "cov_delta": round(other["non_broadcast_coverage"] - cool_a["non_broadcast_coverage"], 4),
        "broadcast_muted_delta": round(other["broadcast_muted_s"] - cool_a["broadcast_muted_s"], 1),
        "desk_delta": round(other["cells"]["desk_s"] - cool_a["cells"]["desk_s"], 1),
        "odell_delta": round(
            other["focus"]["hush_20260924_220624"]["odell"] - cool_a["focus"]["hush_20260924_220624"]["odell"],
            2,
        ),
        "amex_delta": round(
            other["focus"]["hush_20261008_205100"]["amex"] - cool_a["focus"]["hush_20261008_205100"]["amex"],
            2,
        ),
        "chilis_delta": round(
            other["focus"]["hush_20260924_220624"]["chilis"] - cool_a["focus"]["hush_20260924_220624"]["chilis"],
            2,
        ),
        "odell_muted_s": other["focus"]["hush_20260924_220624"]["odell"],
    }


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
        reasons.append("coverage held; spots held")
        if delta["odell_delta"] < -0.5:
            reasons.append(f"Odell muted {delta['odell_muted_s']}s (delta {delta['odell_delta']})")
    return decision, reasons


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    frozen = load_frozen_probs(EVAL)
    cool = {
        s: (
            t,
            apply_cooldown(t, p, non_broadcast_ends(s), COOLDOWN_S),
        )
        for s, (t, p) in frozen.items()
    }
    variants = {
        "baseline_gated": lambda s, t, p: _apply(s, t, p),
        "whit_m0.10_global": lambda s, t, p: _apply(s, t, p, whit_margin=0.10),
        "whit_m0.10_odell_local": lambda s, t, p: _apply(
            s, t, p, whit_margin=0.15, whit_local_margin=0.10, whit_local_span=ODELL[1:]
        ),
        "hold_3s": lambda s, t, p: _apply(s, t, p, hold_s=3.0),
        "tandem_clarissa_whit": lambda s, t, p: _apply(s, t, p, tandem_clarissa_whit=True),
    }
    cool_rep = score_run("cool", cool, OUT)
    cool_a = cool_rep["aggregate"]
    summary = {"cool": cool_a, "variants": {}}
    lines = ["# Odell residual probe (no Michaels/Gonzalez)", ""]
    for name, fn in variants.items():
        run = {s: (t, fn(s, t, p)) for s, (t, p) in frozen.items()}
        rep = score_run(name, run, OUT)
        delta = _delta(cool_a, rep["aggregate"])
        # also vs baseline gated
        decision, reasons = _decide(delta)
        summary["variants"][name] = {
            "decision_vs_cool": {"decision": decision, "reasons": reasons, "delta": delta},
            "aggregate": rep["aggregate"],
        }
        lines += [
            f"## {name}: **{decision}**",
            *[f"- {r}" for r in reasons],
            f"- `{json.dumps(delta)}`",
            f"- desk {rep['aggregate']['cells']['desk_s']} odell {rep['aggregate']['focus']['hush_20260924_220624']['odell']}",
            "",
        ]
        print(name, decision, delta, flush=True)

    base = summary["variants"]["baseline_gated"]["decision_vs_cool"]["delta"]
    for name, block in summary["variants"].items():
        if name == "baseline_gated":
            continue
        d = block["decision_vs_cool"]["delta"]
        block["vs_baseline_gated"] = {
            "cov_delta": round(d["cov_delta"] - base["cov_delta"], 4),
            "odell_delta": round(d["odell_delta"] - base["odell_delta"], 2),
            "desk_delta": round(d["desk_delta"] - base["desk_delta"], 1),
        }
    (OUT / "SUMMARY.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (OUT / "KEEP_REJECT.md").write_text("\n".join(lines) + "\nNot wired to ohush_live.\n", encoding="utf-8")
    print("WROTE", OUT)


if __name__ == "__main__":
    main()
