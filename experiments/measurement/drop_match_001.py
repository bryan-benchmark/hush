"""Draw the marked 32–34 s shape and slide it past each logged break.

September 13 NBC only. The shape is the peak level the logger draws,
from session 102 s to 104 s. A stall at the 16-bit floor is not a match.
The same slide is scored in the show, away from breaks, so a high score
at a break has something to be compared with. Nothing here mutes.
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
from tools.gpu_lab.ladder import pairs  # noqa: E402
from tools.gpu_lab.learning_net.data import bridge_masks  # noqa: E402

OUT = REPO / "docs" / "ohush" / "research" / "DROP_SHAPE_001"
SESSION = "hush_20260913_210542"
DROP0 = 102.0
DROP1 = 104.0
SR = 48000
HOP_S = 0.05
RADIUS = 12.0


def _load(folder, meta, start, end):
    pieces = analysis_pieces(folder, meta, start, end)
    return np.concatenate([read_stereo(piece) for piece in pieces], axis=0)


def _peaks(audio):
    hop = int(HOP_S * SR)
    usable = len(audio) - (len(audio) % hop)
    frames = audio[:usable].reshape(-1, hop)
    return 20.0 * np.log10(np.max(np.abs(frames), axis=1) + 1e-9)


def _envelope(folder, meta, spans):
    times: list[float] = []
    levels: list[float] = []
    for start, end in spans:
        cursor = start
        while cursor < end - 0.2:
            stop = min(end, cursor + 90.0)
            chunk = _peaks(_load(folder, meta, cursor, stop).mean(axis=1))
            levels.extend(chunk.tolist())
            times.extend(cursor + (index + 0.5) * HOP_S for index in range(len(chunk)))
            cursor = stop
    return np.asarray(times), np.asarray(levels, dtype=np.float64)


def _best(corr, origin, center, skip):
    mask = np.abs(origin - center) <= RADIUS
    if skip is not None:
        mask &= np.abs(origin - skip) > 1.0
    if not np.any(mask):
        return None
    index = int(np.argmax(np.where(mask, corr, -2.0)))
    return {"at_s": round(float(origin[index]), 3), "correlation": round(float(corr[index]), 3), "offset_s": round(float(origin[index]) - center, 3)}


def _quantile(values, q):
    if not values:
        return None
    ordered = sorted(values)
    return round(float(ordered[min(len(ordered) - 1, int(q * (len(ordered) - 1)))]), 3)


def main() -> None:
    mask = bridge_masks()[SESSION]
    coverage = [(float(a), float(b)) for a, b in pairs(mask, "coverage")]
    commercials = [(float(a), float(b)) for a, b in pairs(mask, "verified_commercial")]
    folder = find_session(REPO / "recordings", SESSION)
    meta = load_session(folder)
    times, levels = _envelope(folder, meta, coverage)
    start = int(np.argmin(np.abs(times - DROP0)))
    stop = int(np.argmin(np.abs(times - DROP1)))
    template = levels[start:stop].copy()
    shape = template - template.mean()
    shape = shape / (shape.std() + 1e-9)
    windows = np.lib.stride_tricks.sliding_window_view(levels, len(shape))
    centered = windows - windows.mean(axis=1, keepdims=True)
    corr = (centered @ shape) / (len(shape) * (centered.std(axis=1) + 1e-9))
    origin = times[: len(corr)]
    corr = np.where(windows.min(axis=1) < -60.0, -1.0, corr)
    breaks = []
    for edge_s, end_s in commercials:
        for kind, edge in (("start", edge_s), ("end", end_s)):
            hit = _best(corr, origin, edge, DROP0)
            breaks.append({"kind": kind, "edge_s": round(edge, 3), **(hit or {})})
    show = []
    cursor = coverage[0][0] + 30.0
    while cursor < coverage[0][1] - 30.0:
        away = all(edge - 30.0 > cursor or cursor > edge + 30.0 for start_s, end_s in commercials for edge in (start_s, end_s))
        inside = any(start_s <= cursor <= end_s for start_s, end_s in commercials)
        if away and not inside:
            hit = _best(corr, origin, cursor, DROP0)
            if hit:
                show.append(hit["correlation"])
        cursor += 30.0
    show_p95 = _quantile(show, 0.95)
    other_starts = [row for row in breaks if row["kind"] == "start" and abs(row["edge_s"] - 100.129) > 1]
    above = [row for row in other_starts if row.get("correlation", -1) >= (show_p95 or 1)]
    OUT.mkdir(parents=True, exist_ok=True)
    clock = np.arange(len(template)) * HOP_S
    figure, axis = plt.subplots(figsize=(7.2, 3.2))
    axis.plot(clock, template, color="#5b4b8a", linewidth=1.6)
    axis.set_xlabel("Seconds through the marked handoff")
    axis.set_ylabel("Peak level, dB")
    axis.set_title("The shape drawn from 32–34 s in the clip")
    figure.tight_layout()
    figure.savefig(OUT / "shape.png", dpi=140)
    plt.close(figure)
    figure, axis = plt.subplots(figsize=(7.2, 3.6))
    axis.scatter([row["correlation"] for row in breaks if row["kind"] == "start"], [0] * sum(row["kind"] == "start" for row in breaks), color="#c4554a", label="Break start", zorder=3)
    axis.scatter([row["correlation"] for row in breaks if row["kind"] == "end"], [1] * sum(row["kind"] == "end" for row in breaks), color="#2f6f4e", label="Break end", zorder=3)
    axis.scatter(show, [-1] * len(show), color="#5b4b8a", alpha=0.45, label="Show, away from breaks", zorder=2)
    axis.axvline(show_p95 or 0, color="#888888", linewidth=0.8)
    axis.set_yticks([-1, 0, 1], ["Show", "Start", "End"])
    axis.set_xlabel("Best correlation with the drawn shape, within 12 s")
    axis.legend(frameon=False, fontsize=8)
    figure.tight_layout()
    figure.savefig(OUT / "shape_matches.png", dpi=140)
    plt.close(figure)
    payload = {
        "template_s": [DROP0, DROP1],
        "show_n": len(show),
        "show_median": _quantile(show, 0.5),
        "show_p95": show_p95,
        "other_starts": len(other_starts),
        "other_starts_at_or_above_show_p95": len(above),
        "breaks": breaks,
    }
    (OUT / "shape_matches.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: payload[key] for key in payload if key != "breaks"}, indent=2), flush=True)


if __name__ == "__main__":
    main()
