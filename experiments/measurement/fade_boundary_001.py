"""Fades like the Sept 13 handoff, and what the existing head scores on each side.

The shape was taken from one clip: session hush_20260913_210542, the fade
that bottoms near 102.8 seconds. The level falls about 14 dB and stays
audible, then the next thing starts. A dead stretch at the 16-bit floor is
a stream stall and is not a fade.

The head is the two-NBC logistic already used. It is not refit on fades.
October stays an inspected set. Nothing here mutes.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from hush.audio import analysis_pieces, find_session, load_session, read_stereo  # noqa: E402
from experiments.measurement.supervised_heldout_001 import (  # noqa: E402
    FIT,
    NAMES,
    OCTOBER,
    REPORT,
    _fit,
    _scores,
)
from tools.gpu_lab.ladder import pairs  # noqa: E402
from tools.gpu_lab.learning_net.data import bridge_masks  # noqa: E402
from tools.gpu_lab.splits import HOLDOUTS  # noqa: E402

OUT = REPO / "docs" / "ohush" / "research" / "FADE_BOUNDARY_001"
SR = 48000
HOP_S = 0.25
EXAMPLE = ("hush_20260913_210542", 102.75)
STALL = ("hush_20260913_210542", 85.8)
NEAR_S = 5.0
CLEAR_S = 8.0


def _db(audio: np.ndarray) -> np.ndarray:
    hop = int(HOP_S * SR)
    usable = len(audio) - (len(audio) % hop)
    frames = audio[:usable].reshape(-1, hop)
    rms = np.sqrt(np.mean(frames * frames, axis=1) + 1e-12)
    return 20.0 * np.log10(rms)


def _envelope(session: str, spans: list[tuple[float, float]]) -> tuple[np.ndarray, np.ndarray]:
    if session in HOLDOUTS:
        raise RuntimeError(f"refusing sealed holdout {session}")
    folder = find_session(REPO / "recordings", session)
    meta = load_session(folder)
    times: list[float] = []
    levels: list[float] = []
    for start, end in spans:
        cursor = start
        while cursor < end - 0.5:
            stop = min(end, cursor + 120.0)
            pieces = analysis_pieces(folder, meta, cursor, stop)
            audio = np.concatenate([read_stereo(piece).mean(axis=1) for piece in pieces])
            levels.extend(_db(audio).tolist())
            count = len(levels) - len(times)
            times.extend((cursor + (i + 0.5) * HOP_S) for i in range(count))
            cursor = stop
    return np.asarray(times), np.asarray(levels)


def _fades(times: np.ndarray, levels: np.ndarray) -> list[dict]:
    found = []
    for index, moment in enumerate(times):
        bottom = float(levels[index])
        if bottom < -55.0 or bottom > -28.0:
            continue
        earlier = [float(levels[j]) for j, stamp in enumerate(times) if 1.0 <= moment - stamp <= 4.0]
        if len(earlier) < 6 or min(earlier) < -60.0:
            continue
        loud = float(np.median(earlier))
        if loud < -32.0 or loud - bottom < 10.0:
            continue
        later = [float(levels[j]) for j, stamp in enumerate(times) if 0 < stamp - moment <= 1.5]
        if len(later) < 3 or float(np.median(later)) < bottom + 6.0:
            continue
        path = [float(levels[j]) for j, stamp in enumerate(times) if 0 <= moment - stamp <= 4.0]
        if min(path) < -60.0:
            continue
        found.append(
            {
                "t": round(float(moment), 3),
                "bottom_db": round(bottom, 2),
                "before_db": round(loud, 2),
                "drop_db": round(loud - bottom, 2),
                "after_db": round(float(np.median(later)), 2),
            }
        )
    kept: list[dict] = []
    for row in found:
        if kept and row["t"] - kept[-1]["t"] <= 2.0:
            if row["bottom_db"] < kept[-1]["bottom_db"]:
                kept[-1] = row
            continue
        kept.append(row)
    return kept


def _nearest_edge(moment: float, commercials: list[tuple[float, float]]) -> tuple[str, float]:
    best = ("none", 10**9)
    for start, end in commercials:
        for kind, edge in (("start", start), ("end", end)):
            distance = abs(moment - edge)
            if distance < best[1]:
                best = (kind, distance)
    return best[0], float(best[1])


def _role(moment: float, commercials: list[tuple[float, float]]) -> str:
    kind, distance = _nearest_edge(moment, commercials)
    inside = any(start <= moment <= end for start, end in commercials)
    if distance <= NEAR_S and kind == "start":
        return "break_in"
    if distance <= NEAR_S and kind == "end":
        return "break_out"
    if inside and distance > CLEAR_S:
        return "during_ad"
    if not inside and distance > CLEAR_S:
        return "during_show"
    return "shoulder"


def _at(times: np.ndarray, scores: np.ndarray, moment: float) -> float | None:
    if len(times) == 0:
        return None
    index = int(np.argmin(np.abs(times - moment)))
    if abs(float(times[index]) - moment) > 1.0:
        return None
    return round(float(scores[index]), 3)


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return round(ordered[mid], 3)
    return round(0.5 * (ordered[mid - 1] + ordered[mid]), 3)


def _plot_example(times: np.ndarray, levels: np.ndarray, fades: list[dict]) -> None:
    mask = (times >= 70.0) & (times <= 105.0)
    figure, axis = plt.subplots(figsize=(9, 3.2))
    axis.plot(times[mask] - 70.0, levels[mask], color="#5b4b8a", linewidth=1)
    for row in fades:
        if 70.0 <= row["t"] <= 105.0:
            axis.axvline(row["t"] - 70.0, color="#c4554a", linewidth=1)
    axis.axvspan(15.3, 16.3, color="#bbbbbb", alpha=0.45)
    axis.set_ylim(-80, -10)
    axis.set_xlabel("Seconds into the clip")
    axis.set_ylabel("dBFS")
    axis.set_title("Sept 13, 70–105 s. Red is a fade. Grey is the dead stretch.")
    figure.tight_layout()
    figure.savefig(OUT / "example_clip.png", dpi=120)
    plt.close(figure)


def _plot_sides(rows: list[dict]) -> None:
    colors = {
        "break_in": "#c4554a",
        "break_out": "#2f6f4e",
        "during_show": "#5b4b8a",
        "during_ad": "#d7a441",
        "shoulder": "#888888",
    }
    figure, axis = plt.subplots(figsize=(6.2, 5.2))
    for role, color in colors.items():
        chosen = [row for row in rows if row["role"] == role and row["before_score"] is not None and row["after_score"] is not None]
        axis.scatter(
            [row["before_score"] for row in chosen],
            [row["after_score"] for row in chosen],
            s=18,
            alpha=0.75,
            color=color,
            label=f"{role} ({len(chosen)})",
        )
    axis.axhline(0, color="#cccccc", linewidth=0.8)
    axis.axvline(0, color="#cccccc", linewidth=0.8)
    axis.set_xlabel("Score of the 5 s that faded")
    axis.set_ylabel("Score of the next 5 s")
    axis.legend(frameon=False, fontsize=8)
    figure.tight_layout()
    figure.savefig(OUT / "sides.png", dpi=120)
    plt.close(figure)


def main() -> None:
    sessions = list(FIT) + [sid for sid, _name, _role in REPORT] + [sid for sid, _name in OCTOBER]
    masks = bridge_masks()
    head, receipt = _fit(FIT)
    per_session = []
    rows = []
    example_found = False
    stall_found = False
    for session in sessions:
        if session in HOLDOUTS:
            raise RuntimeError(f"refusing sealed holdout {session}")
        coverage = [(float(a), float(b)) for a, b in pairs(masks[session], "coverage")]
        commercials = [(float(a), float(b)) for a, b in pairs(masks[session], "verified_commercial")]
        times, levels = _envelope(session, coverage)
        fades = _fades(times, levels)
        score_t, score_v, _labels = _scores(head, session)
        if session == EXAMPLE[0]:
            _plot_example(times, levels, fades)
            example_found = any(abs(row["t"] - EXAMPLE[1]) <= 0.6 for row in fades)
            stall_found = any(abs(row["t"] - STALL[1]) <= 1.0 for row in fades)
        starts_hit = 0
        for start, _end in commercials:
            if any(abs(row["t"] - start) <= NEAR_S for row in fades):
                starts_hit += 1
        counts: dict[str, int] = {}
        for row in fades:
            role = _role(row["t"], commercials)
            full = {
                **row,
                "session": session,
                "name": NAMES.get(session, session),
                "role": role,
                "before_score": _at(score_t, score_v, row["t"]),
                "after_score": _at(score_t, score_v, row["t"] + 5.0),
            }
            rows.append(full)
            counts[role] = counts.get(role, 0) + 1
        per_session.append(
            {
                "session": session,
                "name": NAMES.get(session, session),
                "fades": len(fades),
                "commercials": len(commercials),
                "starts_with_a_fade": starts_hit,
                "roles": counts,
            }
        )
        print(f"{NAMES.get(session, session)} fades={len(fades)} starts={starts_hit}/{len(commercials)}", flush=True)
    if not example_found or stall_found:
        raise SystemExit(f"example fade found={example_found} stall flagged={stall_found}")
    summary = {}
    for role in ("break_in", "break_out", "during_show", "during_ad", "shoulder"):
        chosen = [row for row in rows if row["role"] == role]
        summary[role] = {
            "n": len(chosen),
            "before_score_median": _median([row["before_score"] for row in chosen if row["before_score"] is not None]),
            "after_score_median": _median([row["after_score"] for row in chosen if row["after_score"] is not None]),
            "show_then_ad": sum(
                row["before_score"] is not None
                and row["after_score"] is not None
                and row["before_score"] < 0
                and row["after_score"] > 0
                for row in chosen
            ),
            "ad_then_show": sum(
                row["before_score"] is not None
                and row["after_score"] is not None
                and row["before_score"] > 0
                and row["after_score"] < 0
                for row in chosen
            ),
        }
    OUT.mkdir(parents=True, exist_ok=True)
    _plot_sides(rows)
    payload = {
        "rule": {
            "from": "Sept 13 NBC clip 70–105 s, fade near 102.8 s",
            "bottom_db": [-55, -28],
            "drop_db": 10,
            "lookback_s": [1, 4],
            "recovery_db": 6,
            "stall_below_db": -60,
            "near_boundary_s": NEAR_S,
        },
        "head": receipt,
        "example_fade_found": example_found,
        "stall_flagged": stall_found,
        "sessions": per_session,
        "roles": summary,
        "fades": rows,
    }
    (OUT / "results.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"roles": summary, "example": example_found, "stall": stall_found}, indent=2), flush=True)


if __name__ == "__main__":
    main()
