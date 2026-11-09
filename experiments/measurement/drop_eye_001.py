"""Catch the dip the eye sees, on one labeled game.

The logger draws a peak envelope. This uses that, smoothed over about
half a second, so a syllable gap is not a dip and a dead stream is not a dip.
The depth is taken from the marked handoff at session 102–104 s and then
left alone. Holdouts stay sealed. Nothing here mutes.
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
SR = 48000
HOP_S = 0.05
SMOOTH = 8  # 0.4 s
SHOULDER = 20  # 1.0 s
EXAMPLE = 102.8


def _load(folder, meta, start, end):
    pieces = analysis_pieces(folder, meta, start, end)
    return np.concatenate([read_stereo(piece) for piece in pieces], axis=0)


def _peaks(audio: np.ndarray) -> np.ndarray:
    hop = int(HOP_S * SR)
    usable = len(audio) - (len(audio) % hop)
    frames = audio[:usable].reshape(-1, hop)
    peak = np.max(np.abs(frames), axis=1) + 1e-9
    return 20.0 * np.log10(peak)


def _smooth(levels: np.ndarray) -> np.ndarray:
    kernel = np.ones(SMOOTH) / SMOOTH
    return np.convolve(levels, kernel, mode="same")


def _envelope(folder, meta, spans):
    times: list[float] = []
    levels: list[float] = []
    for start, end in spans:
        cursor = start
        while cursor < end - 0.2:
            stop = min(end, cursor + 90.0)
            audio = _load(folder, meta, cursor, stop).mean(axis=1)
            chunk = _peaks(audio)
            levels.extend(chunk.tolist())
            times.extend(cursor + (index + 0.5) * HOP_S for index in range(len(chunk)))
            cursor = stop
    raw = np.asarray(levels, dtype=np.float64)
    return np.asarray(times), raw, _smooth(raw)


def _dips(times, smooth, need_drop):
    found = []
    span = SHOULDER
    for index in range(span, len(times) - span):
        bottom = float(smooth[index])
        if bottom < -55.0:
            continue
        if bottom > float(smooth[index - 1]) or bottom > float(smooth[index + 1]):
            continue
        before = float(np.max(smooth[index - span : index - span // 2]))
        after = float(np.max(smooth[index + span // 2 : index + span]))
        drop = before - bottom
        rise = after - bottom
        if drop < need_drop or rise < 6.0:
            continue
        half = bottom + 0.5 * min(drop, rise)
        left = index
        while left > 0 and float(smooth[left]) <= half:
            left -= 1
        right = index
        while right < len(smooth) - 1 and float(smooth[right]) <= half:
            right += 1
        width = (right - left) * HOP_S
        if found and float(times[index]) - found[-1]["t"] < 1.5 and bottom >= found[-1]["bottom_db"]:
            continue
        if found and float(times[index]) - found[-1]["t"] < 1.5:
            found[-1] = None
        row = {
            "t": round(float(times[index]), 3),
            "bottom_db": round(bottom, 2),
            "before_db": round(before, 2),
            "after_db": round(after, 2),
            "drop_db": round(drop, 2),
            "width_s": round(width, 2),
        }
        if found and found[-1] is None:
            found[-1] = row
        else:
            found.append(row)
    return [row for row in found if row]


def _place(moment, commercials):
    best = ("none", None, 10**9)
    inside = False
    for start, end in commercials:
        if start - 8 <= moment <= end + 8:
            inside = inside or (start <= moment <= end)
        for kind, edge in (("start", start), ("end", end)):
            distance = abs(moment - edge)
            if distance < best[2]:
                best = (kind, edge, distance)
    return best[0], None if best[1] is None else round(best[1], 3), round(best[2], 3), inside


def main() -> None:
    mask = bridge_masks()[SESSION]
    coverage = [(float(a), float(b)) for a, b in pairs(mask, "coverage")]
    commercials = [(float(a), float(b)) for a, b in pairs(mask, "verified_commercial")]
    folder = find_session(REPO / "recordings", SESSION)
    meta = load_session(folder)
    times, raw, smooth = _envelope(folder, meta, coverage)
    window = (times >= 101.0) & (times <= 105.0)
    example_bottom = float(np.min(smooth[(times >= 102.0) & (times <= 104.0)]))
    example_before = float(np.max(smooth[(times >= 100.5) & (times <= 102.0)]))
    example_drop = round(example_before - example_bottom, 2)
    need = max(6.0, example_drop - 3.0)
    dips = _dips(times, smooth, need)
    if not any(abs(row["t"] - EXAMPLE) <= 1.0 for row in dips):
        raise SystemExit(f"the marked dip was missed, example drop {example_drop} dB, need {need}")
    rows = []
    for row in dips:
        kind, edge, distance, inside = _place(row["t"], commercials)
        rows.append({**row, "kind": kind, "edge": edge, "distance_s": distance, "inside_or_beside_break": inside})
    near_start = [row for row in rows if row["kind"] == "start" and row["distance_s"] <= 8]
    near_end = [row for row in rows if row["kind"] == "end" and row["distance_s"] <= 8]
    show = [row for row in rows if row["distance_s"] > 20 and not row["inside_or_beside_break"]]
    starts = []
    for start, end in commercials:
        hit = [row for row in rows if abs(row["t"] - start) <= 8 or (start <= row["t"] <= start + 8)]
        starts.append({"start": round(start, 3), "end": round(end, 3), "dips_within_8s": len(hit)})
    hours = sum(end - start for start, end in coverage) / 3600.0
    example = min(rows, key=lambda row: abs(row["t"] - EXAMPLE))
    wide = [row for row in rows if row["width_s"] >= 0.8]
    wide_show = [row for row in wide if row["distance_s"] > 20 and not row["inside_or_beside_break"]]
    wide_starts = 0
    for start, _end in commercials:
        if any(row["width_s"] >= 0.8 and (abs(row["t"] - start) <= 8 or start <= row["t"] <= start + 8) for row in rows):
            wide_starts += 1
    OUT.mkdir(parents=True, exist_ok=True)
    figure, axis = plt.subplots(figsize=(8, 3.2))
    axis.plot(times[window] - 70.0, smooth[window], color="#5b4b8a")
    axis.set_xlabel("Seconds into the clip")
    axis.set_ylabel("Smoothed peak, dB")
    axis.set_title("What the eye is tracking through the marked handoff")
    figure.tight_layout()
    figure.savefig(OUT / "eye_dip.png", dpi=130)
    plt.close(figure)
    payload = {
        "session": SESSION,
        "example_drop_db": example_drop,
        "need_drop_db": need,
        "smooth_s": SMOOTH * HOP_S,
        "hours": round(hours, 2),
        "dips": len(rows),
        "dips_per_hour": round(len(rows) / hours, 2),
        "within_8s_of_a_start": len(near_start),
        "within_8s_of_an_end": len(near_end),
        "in_the_show": len(show),
        "example_width_s": example["width_s"],
        "width_at_least_0.8s": len(wide),
        "wide_in_the_show": len(wide_show),
        "starts_with_a_wide_dip": wide_starts,
        "starts_with_a_dip": sum(row["dips_within_8s"] > 0 for row in starts),
        "commercials": len(commercials),
        "starts": starts,
        "rows": rows,
    }
    (OUT / "eye.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: payload[key] for key in payload if key not in ("rows", "starts")}, indent=2), flush=True)


if __name__ == "__main__":
    main()
