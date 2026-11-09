"""The 32–34 s fade on Sept 13 NBC, then the same shape elsewhere in that game.

Clip hush time 70–105 s. The marked handoff is 32–34 s into the clip,
session time 102–104 s. A frame at the 16-bit floor is a stall and is
skipped. Holdouts stay sealed. Nothing here mutes.
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
CLIP0 = 70.0
DROP0 = 102.0
DROP1 = 104.0
SR = 48000
HOP_S = 0.05
FINE_S = 0.02


def _load(folder: Path, meta: dict, start: float, end: float) -> np.ndarray:
    pieces = analysis_pieces(folder, meta, start, end)
    return np.concatenate([read_stereo(piece) for piece in pieces], axis=0)


def _frame_db(mono: np.ndarray, hop_s: float) -> np.ndarray:
    hop = int(hop_s * SR)
    usable = len(mono) - (len(mono) % hop)
    frames = mono[:usable].reshape(-1, hop)
    rms = np.sqrt(np.mean(frames * frames, axis=1) + 1e-12)
    return 20.0 * np.log10(rms)


def _envelope(folder: Path, meta: dict, spans: list[tuple[float, float]]) -> tuple[np.ndarray, np.ndarray]:
    times: list[float] = []
    levels: list[float] = []
    for start, end in spans:
        cursor = start
        while cursor < end - 0.2:
            stop = min(end, cursor + 90.0)
            audio = _load(folder, meta, cursor, stop).mean(axis=1)
            chunk = _frame_db(audio, HOP_S)
            levels.extend(chunk.tolist())
            times.extend((cursor + (index + 0.5) * HOP_S) for index in range(len(chunk)))
            cursor = stop
    return np.asarray(times), np.asarray(levels)


def _peaks(score: np.ndarray, times: np.ndarray, height: float, gap_s: float) -> list[int]:
    chosen: list[int] = []
    order = np.argsort(score)[::-1]
    for index in order:
        if score[index] < height:
            break
        moment = float(times[index])
        if any(abs(moment - float(times[prior])) < gap_s for prior in chosen):
            continue
        chosen.append(int(index))
    chosen.sort(key=lambda index: float(times[index]))
    return chosen


def _nearest(moment: float, commercials: list[tuple[float, float]]) -> dict:
    best = {"kind": "none", "edge": None, "distance_s": None}
    inside = None
    for start, end in commercials:
        if start <= moment <= end:
            inside = [round(start, 3), round(end, 3)]
        for kind, edge in (("start", start), ("end", end)):
            distance = abs(moment - edge)
            if best["distance_s"] is None or distance < best["distance_s"]:
                best = {"kind": kind, "edge": round(edge, 3), "distance_s": round(distance, 3)}
    best["inside_commercial"] = inside
    return best


def main() -> None:
    masks = bridge_masks()
    coverage = [(float(a), float(b)) for a, b in pairs(masks[SESSION], "coverage")]
    commercials = [(float(a), float(b)) for a, b in pairs(masks[SESSION], "verified_commercial")]
    folder = find_session(REPO / "recordings", SESSION)
    meta = load_session(folder)
    close = _load(folder, meta, 99.0, 106.0)
    mono = close.mean(axis=1)
    fine_db = _frame_db(mono, FINE_S)
    fine_t = 99.0 + (np.arange(len(fine_db)) + 0.5) * FINE_S
    left = _frame_db(close[:, 0], FINE_S)
    right = _frame_db(close[:, 1], FINE_S)
    detail = []
    for moment, level, ell, arr in zip(fine_t, fine_db, left, right):
        if 101.5 <= moment <= 104.5:
            detail.append(
                {
                    "session_s": round(float(moment), 3),
                    "clip_s": round(float(moment - CLIP0), 3),
                    "db": round(float(level), 2),
                    "left_db": round(float(ell), 2),
                    "right_db": round(float(arr), 2),
                }
            )
    times, levels = _envelope(folder, meta, coverage)
    start = int(np.argmin(np.abs(times - DROP0)))
    stop = int(np.argmin(np.abs(times - DROP1)))
    template = levels[start:stop].astype(np.float64)
    if len(template) < 10:
        raise SystemExit("template is too short")
    template = template - template.mean()
    template = template / (template.std() + 1e-9)
    windows = np.lib.stride_tricks.sliding_window_view(levels, len(template))
    centered = windows - windows.mean(axis=1, keepdims=True)
    corr = (centered @ template) / (len(template) * (centered.std(axis=1) + 1e-9))
    origin = times[: len(corr)]
    stall = windows.min(axis=1) < -60.0
    corr = np.where(stall, -1.0, corr)
    self_at = int(np.argmin(np.abs(origin - DROP0)))
    peak_index = _peaks(corr, origin, 0.85, 3.0)
    matches = []
    for index in peak_index:
        moment = float(origin[index])
        window = levels[index : index + len(template)]
        place = _nearest(moment + 1.0, commercials)
        matches.append(
            {
                "session_s": round(moment, 3),
                "clip_if_this_tape": round(moment - CLIP0, 3),
                "source": abs(moment - DROP0) < 1.0,
                "correlation": round(float(corr[index]), 3),
                "bottom_db": round(float(window.min()), 2),
                "drop_db": round(float(window[:8].mean() - window.min()), 2),
                **place,
            }
        )
    near_start = [row for row in matches if row["kind"] == "start" and row["distance_s"] <= 8.0]
    near_end = [row for row in matches if row["kind"] == "end" and row["distance_s"] <= 8.0]
    in_show = [row for row in matches if row["distance_s"] is not None and row["distance_s"] > 20.0 and not row["inside_commercial"]]
    starts_hit = 0
    for start_s, _end_s in commercials:
        if any(row["kind"] == "start" and abs(row["edge"] - start_s) < 0.05 and row["distance_s"] <= 8.0 for row in matches):
            starts_hit += 1
    OUT.mkdir(parents=True, exist_ok=True)
    figure, axis = plt.subplots(figsize=(8, 3.2))
    show = (fine_t >= 101.0) & (fine_t <= 105.0)
    axis.plot(fine_t[show] - CLIP0, fine_db[show], color="#5b4b8a")
    axis.axvspan(32.0, 34.0, color="#c4554a", alpha=0.15)
    axis.set_xlabel("Seconds into the clip")
    axis.set_ylabel("dBFS")
    axis.set_title("Sept 13 NBC, 20 ms level through the marked handoff")
    figure.tight_layout()
    figure.savefig(OUT / "handoff.png", dpi=130)
    plt.close(figure)
    payload = {
        "session": SESSION,
        "template_session_s": [DROP0, DROP1],
        "template_clip_s": [DROP0 - CLIP0, DROP1 - CLIP0],
        "self_correlation": round(float(corr[self_at]), 3),
        "fine": detail,
        "matches": len(matches),
        "within_8s_of_a_start": len(near_start),
        "within_8s_of_an_end": len(near_end),
        "more_than_20s_from_a_break": len(in_show),
        "commercials": len(commercials),
        "starts_with_a_match": starts_hit,
        "rows": matches,
    }
    (OUT / "results.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {key: payload[key] for key in ("self_correlation", "matches", "within_8s_of_a_start", "within_8s_of_an_end", "more_than_20s_from_a_break", "starts_with_a_match", "commercials")},
            indent=2,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
