"""Audit Fitz side-cache on residual desk cores (esp. schedule break ~6599)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from experiments.audio_learn.desk_voice_hold import ECAPA, LINE, NAMES
from experiments.audio_learn.research_latch import FITZ_CACHE, FITZ_MARGIN, _side_hot_ends, _voice_hot_ends

OUT = DATA = Path(r"C:\OHushData\gpu_lab\audio_learn\fitz_residual_audit")
CORES = [
    ("hush_20260924_220624", 6599.5, 6605.75, "fitz_schedule_break"),
    ("hush_20260924_220624", 7047.5, 7054.25, "odell_mid_whit"),
    ("hush_20260924_220624", 6734.0, 6739.75, "gonzalez_halftime"),
    ("hush_20260924_220624", 3647.0, 3652.5, "michaels_moon"),
    ("hush_20261008_205100", 1750.0, 1760.75, "michaels_jerry_jones"),
]


def _ecapa_window(session: str, a: float, b: float) -> dict:
    path = ECAPA / f"{session}.npz"
    if not path.is_file():
        return {"error": "missing ecapa"}
    data = np.load(path)
    ends = data["end"]
    people = data["people"]
    m = (ends > a) & (ends <= b)
    if not np.any(m):
        return {"n": 0}
    scores = people[m]
    out = {"n": int(m.sum())}
    for i, name in enumerate(NAMES):
        col = scores[:, i].astype(float)
        finite = col[np.isfinite(col)]
        if finite.size == 0:
            out[name] = None
            continue
        out[name] = {
            "max": round(float(np.nanmax(finite)), 3),
            "p50": round(float(np.median(finite)), 3),
            "n_ge_line": int(np.sum(finite >= LINE)),
        }
    return out


def _fitz_window(session: str, a: float, b: float) -> dict:
    path = FITZ_CACHE / f"{session}_fitz.npz"
    if not path.is_file():
        return {"error": "missing fitz cache"}
    data = np.load(path)
    ends = data["end"]
    score = data["fitz"].astype(float)
    people5 = data["people5"].astype(float)
    m = (ends > a) & (ends <= b)
    if not np.any(m):
        return {"n": 0}
    s = score[m]
    rival = np.nanmax(people5[m], axis=1)
    gap = s - np.nan_to_num(rival, nan=-1.0)
    hot = np.isfinite(s) & (s >= LINE) & (gap >= FITZ_MARGIN)
    return {
        "n": int(m.sum()),
        "fitz_max": round(float(np.nanmax(s)), 3),
        "fitz_p50": round(float(np.nanmedian(s)), 3),
        "gap_p50": round(float(np.nanmedian(gap)), 3),
        "n_hot_m0.15": int(np.sum(hot)),
        "n_ge_line": int(np.sum(np.isfinite(s) & (s >= LINE))),
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for session, a, b, tag in CORES:
        clar = _voice_hot_ends(session, "Clarissa Thompson", 0.10)
        whit = _voice_hot_ends(session, "Andrew Whitworth", 0.15)
        fitz_hot = _side_hot_ends(session, FITZ_CACHE, "fitz", FITZ_MARGIN)
        def count(hots):
            if hots.size == 0:
                return 0
            return int(np.sum((hots > a) & (hots <= b)))
        row = {
            "tag": tag,
            "session": session,
            "span": [a, b],
            "panel_hot_ends_in_span": {
                "clarissa_m0.10": count(clar),
                "whit_m0.15": count(whit),
                "fitz_m0.15": count(fitz_hot),
            },
            "fitz_cache": _fitz_window(session, a, b),
            "ecapa5": _ecapa_window(session, a, b),
        }
        rows.append(row)
        print(json.dumps(row, indent=2), flush=True)

    # Recommendation from schedule break
    sched = next(r for r in rows if r["tag"] == "fitz_schedule_break")
    fc = sched["fitz_cache"]
    if fc.get("n_hot_m0.15", 0) == 0 and fc.get("n_ge_line", 0) == 0:
        tip = "Fitz cold on labeled schedule break — enroll refresh from 6599–6606 candidate (research only)."
    elif fc.get("n_hot_m0.15", 0) == 0 and fc.get("n_ge_line", 0) > 0:
        tip = "Fitz ≥ line but margin <0.15 — do not drop to m0.10 globally (already REJECT); local enroll may help gap."
    else:
        tip = "Fitz already hot on residual — latch hold/controller timing, not enroll."
    summary = {"cores": rows, "recommendation": tip, "live": False}
    (OUT / "SUMMARY.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (OUT / "AUDIT.md").write_text(
        "\n".join(
            [
                "# Fitz residual audit",
                "",
                tip,
                "",
                *[f"- {r['tag']}: fitz_hot={r['panel_hot_ends_in_span']['fitz_m0.15']} cache={r['fitz_cache']}" for r in rows],
                "",
                "Not wired to ohush_live.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    print("RECOMMEND:", tip)
    print("WROTE", OUT)


if __name__ == "__main__":
    main()
