"""EXP-01 micro-production cuts.

Frozen before any recording is scored.

Literature baseline, from Ramires, Cocharro, and Davies, arXiv:1811.02411.
Their silence grid is 1920 samples at 48 kHz, which is 40 ms, and their
energy cut is -60 dB. The regression they trained on Portuguese television
is not reproduced: the coefficients are not published, and fitting them here
would train on this gold.

Relative candidate, also frozen, and not fit on any game:
- A frame is hot when it is at least 18 dB below the median of the previous
  2 seconds, and that median is at least -45 dB.
- A short dip is a hot run lasting 10 to 200 ms that recovers to within 6 dB
  of the pre-dip median on the next frame.
- The same 18 / 6 / 2 second numbers are used at 10, 20, 40, 100, 250 and
  500 ms. Nothing is retuned per scale.
- A coarse episode is one or more consecutive frames each 18 dB below the
  past median, with no 200 ms cap. It exists so the long windows can still
  be measured. It is not the production-cut rule.
- Availability is the end of the recovery frame for a short dip, and the end
  of the first hot frame for a coarse episode. Audio after that is not used.

The research gate uses only the 40 ms mono short dip.
MET if football program episodes/hour are at most 215/5 and RedZone
episodes/hour are at most 474/5, and football-start recall within 1 second
is at least 0.25.
COMPLEMENTARY if that gate is missed, program episodes/hour are at most 20,
and at least 10 football starts without a fresh DSP episode are hit within
0.5 seconds.
Otherwise NOT_MET.
The gate is not a mute decision.
"""

from __future__ import annotations

import csv
import hashlib
import json
import resource
import sys
import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from experiments.broadcast_intelligence.batch1 import SR, commercials, coverage, load_catalog, read_span
from hush.audio import find_session, load_session

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "docs/ohush/research/FIRST_PRINCIPLES_BROADCAST_V2/EXP_01_MICRO_PRODUCTION_CUTS"
RECORDINGS = REPO / "recordings"
EPISODES = REPO / "docs/ohush/research/CANDIDATE_VERIFICATION_001/episodes.csv"
REDZONE = "hush_20260913_150934"
HOP = 480
SCALES_MS = (10, 20, 40, 100, 250, 500)
DROP_DB = 18.0
RECOVERY_DB = 6.0
PAST_S = 2.0
PAST_FLOOR_DB = -45.0
ABSOLUTE_DB = -60.0
ABSOLUTE_PAST_FLOOR_DB = -40.0
DIP_MIN_S = 0.010
DIP_MAX_S = 0.200
WINDOWS = (0.25, 0.5, 1.0, 2.0, 3.0)
PRE_S = 5.0
COLLAR_S = 15.0
DSP_FOOTBALL_PER_HOUR = 215.0
DSP_REDZONE_PER_HOUR = 474.0
GATE_RECALL_1S = 0.25
COMPLEMENT_RATE = 20.0
COMPLEMENT_HITS = 10
BLOCK_S = 60.0


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def to_db(power: np.ndarray) -> np.ndarray:
    return 20.0 * np.log10(np.sqrt(np.maximum(power, 0.0)) + 1e-12)


def frame_power(audio: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    usable = (len(audio) // HOP) * HOP
    if usable < HOP:
        empty = np.zeros(0, dtype=np.float64)
        return empty, empty, empty
    frames = audio[:usable].reshape(-1, HOP, 2).astype(np.float64)
    left = np.mean(frames[:, :, 0] * frames[:, :, 0], axis=1)
    right = np.mean(frames[:, :, 1] * frames[:, :, 1], axis=1)
    mono = np.mean(((frames[:, :, 0] + frames[:, :, 1]) * 0.5) ** 2, axis=1)
    return mono, left, right


def pool(power: np.ndarray, factor: int) -> np.ndarray:
    usable = (len(power) // factor) * factor
    if usable < factor:
        return np.zeros(0, dtype=np.float64)
    return power[:usable].reshape(-1, factor).mean(axis=1)


def causal_median(values: np.ndarray, past_n: int) -> np.ndarray:
    out = np.full(values.shape, np.nan, dtype=np.float64)
    if past_n <= 0 or len(values) <= past_n:
        return out
    chunk = 20000
    for start in range(past_n, len(values), chunk):
        stop = min(len(values), start + chunk)
        segment = values[start - past_n : stop]
        view = np.lib.stride_tricks.sliding_window_view(segment, past_n)[: stop - start]
        finite = np.isfinite(view).all(axis=1)
        med = np.median(np.where(finite[:, None], view, 0.0), axis=1)
        med[~finite] = np.nan
        out[start:stop] = med
    return out


def runs(mask: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    padded = np.diff(np.concatenate(([0], mask.astype(np.int8), [0])))
    return np.flatnonzero(padded == 1), np.flatnonzero(padded == -1)


def short_dips(db: np.ndarray, frame_s: float) -> tuple[np.ndarray, np.ndarray, int, int]:
    past_n = int(round(PAST_S / frame_s))
    past = causal_median(db, past_n)
    hot = np.isfinite(past) & (db <= past - DROP_DB) & (past >= PAST_FLOOR_DB)
    starts, ends = runs(hot)
    available = []
    drop = []
    too_long = 0
    no_recovery = 0
    for start, end in zip(starts.tolist(), ends.tolist()):
        duration = (end - start) * frame_s
        if duration > DIP_MAX_S + 1e-9:
            too_long += 1
            continue
        if duration < DIP_MIN_S - 1e-9:
            continue
        if end >= len(db) or not np.isfinite(past[start]):
            no_recovery += 1
            continue
        if db[end] < past[start] - RECOVERY_DB:
            no_recovery += 1
            continue
        available.append((end + 1) * frame_s)
        drop.append(float(past[start] - np.min(db[start:end])))
    return np.asarray(available, dtype=np.float64), np.asarray(drop, dtype=np.float64), too_long, no_recovery


def absolute_dips(db: np.ndarray, frame_s: float) -> tuple[np.ndarray, int]:
    past_n = int(round(PAST_S / frame_s))
    past = causal_median(db, past_n)
    hot = np.isfinite(past) & (db <= ABSOLUTE_DB) & (past >= ABSOLUTE_PAST_FLOOR_DB)
    starts, ends = runs(hot)
    raw = len(starts)
    available = []
    for start, end in zip(starts.tolist(), ends.tolist()):
        duration = (end - start) * frame_s
        if duration < max(frame_s, DIP_MIN_S) - 1e-9 or duration > DIP_MAX_S + 1e-9:
            continue
        if end >= len(db) or db[end] < past[start] - RECOVERY_DB:
            continue
        available.append((end + 1) * frame_s)
    return np.asarray(available, dtype=np.float64), raw


def coarse_episodes(db: np.ndarray, frame_s: float) -> np.ndarray:
    past_n = int(round(PAST_S / frame_s))
    past = causal_median(db, past_n)
    hot = np.isfinite(past) & (db <= past - DROP_DB) & (past >= PAST_FLOOR_DB)
    starts, _ends = runs(hot)
    if len(starts) == 0:
        return np.zeros(0, dtype=np.float64)
    return (starts + 1).astype(np.float64) * frame_s


def self_check() -> None:
    rng = np.random.default_rng(0)
    seconds = 4.0
    audio = np.zeros((int(seconds * SR), 2), dtype=np.float64)
    audio[:] = 0.1 * rng.standard_normal(audio.shape)
    cut = int(3.0 * SR)
    audio[cut : cut + 1920] = 0.0
    mono, _left, _right = frame_power(audio)
    db = to_db(pool(mono, 4))
    available, _drop, _long, _miss = short_dips(db, 0.04)
    if not np.any((available > 3.0) & (available < 3.3)):
        raise SystemExit(f"synthetic 40 ms cut was not detected: {available[:8]}")


def hit(times: np.ndarray, boundary: float, window: float) -> bool:
    if times.size == 0:
        return False
    lo = np.searchsorted(times, boundary, side="left")
    hi = np.searchsorted(times, boundary + window, side="right")
    return hi > lo


def first_delay(times: np.ndarray, boundary: float, window: float) -> float | None:
    if times.size == 0:
        return None
    lo = np.searchsorted(times, boundary, side="left")
    if lo >= times.size or times[lo] > boundary + window:
        return None
    return float(times[lo] - boundary)


def rate(count: int, seconds: float) -> float | None:
    if seconds <= 0:
        return None
    return count / (seconds / 3600.0)


def region_mask(times: np.ndarray, pods: list[tuple[float, float]], far: bool) -> np.ndarray:
    keep = np.ones(times.shape, dtype=bool)
    for start, end in pods:
        keep &= ~((times >= start) & (times < end))
        if far:
            keep &= ~((times >= start - COLLAR_S) & (times < end + COLLAR_S))
    return keep


def main() -> None:
    sys.stdout.reconfigure(line_buffering=True)
    self_check()
    started = time.perf_counter()
    catalog = load_catalog()
    spans = coverage()
    rows = commercials(spans)
    if len(rows) != 166:
        raise SystemExit(f"expected 166 commercials, found {len(rows)}")
    sessions: dict[str, dict] = {}
    for span in spans:
        sid = span["session"]
        if sid in sessions:
            continue
        info = catalog.get(sid, {})
        sessions[sid] = {
            "dir": find_session(RECORDINGS, sid),
            "meta": load_session(find_session(RECORDINGS, sid)),
            "coverage": (float(span["from_seconds"]), float(span["to_seconds"])),
            "network": info.get("network_or_service") or "unknown",
            "content": info.get("content_type") or "",
        }
    pods_by: dict[str, list[tuple[float, float]]] = {sid: [] for sid in sessions}
    boundaries = []
    for row in rows:
        sid = row["session"]
        start, end = float(row["start_seconds"]), float(row["end_seconds"])
        pods_by[sid].append((start, end))
        boundaries.append({
            "session": sid,
            "network": sessions[sid]["network"],
            "content": sessions[sid]["content"],
            "kind": "start",
            "t": start,
        })
        boundaries.append({
            "session": sid,
            "network": sessions[sid]["network"],
            "content": sessions[sid]["content"],
            "kind": "end",
            "t": end,
        })
    fresh = set()
    for row in csv.DictReader(EPISODES.open(encoding="utf-8")):
        if row["class"] == "fresh_start" and row["fresh_start_s"]:
            fresh.add((row["session"], round(float(row["fresh_start_s"]), 3)))

    events: dict[tuple[str, int, str], np.ndarray] = {}
    drops_40: dict[str, np.ndarray] = {}
    description = []
    program_drops = []
    flux_at = []
    flux_program = []
    corr_at = []
    corr_program = []
    floors = {}
    measured_s = {sid: {"program": 0.0, "pod": 0.0, "redzone": 0.0, "scripted": 0.0, "missing": 0.0} for sid in sessions}
    reject = {scale: {"too_long": 0, "no_recovery": 0} for scale in SCALES_MS}

    for sid, bag in sessions.items():
        cov0, cov1 = bag["coverage"]
        n_frames = int(np.floor((cov1 - cov0) * SR / HOP))
        mono_p = np.full(n_frames, np.nan)
        left_p = np.full(n_frames, np.nan)
        right_p = np.full(n_frames, np.nan)
        n40 = n_frames // 4
        flux = np.full(max(n40 - 1, 0), np.nan)
        corr = np.full(n40, np.nan)
        cursor = cov0
        previous_mag = None
        print(f"reading {sid}", flush=True)
        while cursor < cov1 - 0.02:
            take = min(BLOCK_S, cov1 - cursor)
            try:
                audio = read_span(bag["dir"], bag["meta"], cursor, cursor + take)
            except RuntimeError:
                measured_s[sid]["missing"] += take
                cursor += take
                previous_mag = None
                continue
            mono, left, right = frame_power(audio)
            index = int(round((cursor - cov0) * SR / HOP))
            count = min(len(mono), n_frames - index)
            if count > 0:
                mono_p[index : index + count] = mono[:count]
                left_p[index : index + count] = left[:count]
                right_p[index : index + count] = right[:count]
            usable = (len(audio) // (HOP * 4)) * (HOP * 4)
            if usable >= HOP * 4:
                block = audio[:usable].reshape(-1, HOP * 4, 2).astype(np.float64)
                mixed = 0.5 * (block[:, :, 0] + block[:, :, 1])
                window = np.hanning(HOP * 4)
                mag = np.abs(np.fft.rfft(mixed * window, axis=1)) + 1e-12
                logmag = np.log(mag)
                frame40 = int(round((cursor - cov0) / 0.04))
                if previous_mag is not None and frame40 > 0:
                    joined = np.vstack([previous_mag, logmag])
                    delta = np.mean(np.abs(np.diff(joined, axis=0)), axis=1)
                    dest = frame40 - 1
                    ncopy = min(len(delta), len(flux) - dest)
                    if dest >= 0 and ncopy > 0:
                        flux[dest : dest + ncopy] = delta[:ncopy]
                elif frame40 < n40 and len(logmag) > 1:
                    delta = np.mean(np.abs(np.diff(logmag, axis=0)), axis=1)
                    dest = frame40
                    ncopy = min(len(delta), len(flux) - dest)
                    if ncopy > 0:
                        flux[dest : dest + ncopy] = delta[:ncopy]
                previous_mag = logmag[-1:]
                centered_l = block[:, :, 0] - block[:, :, 0].mean(axis=1, keepdims=True)
                centered_r = block[:, :, 1] - block[:, :, 1].mean(axis=1, keepdims=True)
                denom = np.sqrt(np.mean(centered_l * centered_l, axis=1) * np.mean(centered_r * centered_r, axis=1)) + 1e-12
                local_corr = np.mean(centered_l * centered_r, axis=1) / denom
                ncorr = min(len(local_corr), n40 - frame40)
                if frame40 >= 0 and ncorr > 0:
                    corr[frame40 : frame40 + ncorr] = local_corr[:ncorr]
            if count * HOP < 0.5 * take * SR:
                measured_s[sid]["missing"] += take
            cursor += take
        db10 = to_db(mono_p)
        finite = np.isfinite(db10)
        floors[sid] = {
            "p01": None if finite.sum() < 100 else round(float(np.percentile(db10[finite], 1)), 2),
            "p50": None if finite.sum() < 100 else round(float(np.percentile(db10[finite], 50)), 2),
        }
        scale_db = {10: db10}
        for scale in SCALES_MS:
            if scale == 10:
                continue
            factor = scale // 10
            scale_db[scale] = to_db(pool(np.where(finite, mono_p, np.nan), factor))
        for scale in SCALES_MS:
            frame_s = scale / 1000.0
            available, drop, too_long, no_recovery = short_dips(scale_db[scale], frame_s)
            reject[scale]["too_long"] += too_long
            reject[scale]["no_recovery"] += no_recovery
            events[(sid, scale, "short")] = cov0 + available
            if scale == 40:
                drops_40[sid] = drop
            absolute_times, raw_runs = absolute_dips(scale_db[scale], frame_s)
            events[(sid, scale, "absolute")] = cov0 + absolute_times
            reject[scale]["absolute_runs"] = reject[scale].get("absolute_runs", 0) + raw_runs
            events[(sid, scale, "coarse")] = cov0 + coarse_episodes(scale_db[scale], frame_s)
        left_db = to_db(pool(left_p, 4))
        right_db = to_db(pool(right_p, 4))
        stereo_times = []
        past_l = causal_median(left_db, int(round(PAST_S / 0.04)))
        past_r = causal_median(right_db, int(round(PAST_S / 0.04)))
        short40 = events[(sid, 40, "short")]
        for stamp in short40.tolist():
            frame = int(round((stamp - cov0) / 0.04)) - 2
            frame = min(max(frame, 0), len(left_db) - 1)
            if frame <= 0 or not np.isfinite(past_l[frame]) or not np.isfinite(past_r[frame]):
                continue
            if left_db[frame] <= past_l[frame] - 12 and right_db[frame] <= past_r[frame] - 12:
                stereo_times.append(stamp)
        events[(sid, 40, "short_both_channels")] = np.asarray(stereo_times, dtype=np.float64)

        def local_drop(t: float) -> float | None:
            a = int(round((t - 0.25 - cov0) * 100))
            b = int(round((t + 0.25 - cov0) * 100))
            p0 = int(round((t - 2.25 - cov0) * 100))
            p1 = int(round((t - 0.25 - cov0) * 100))
            if p0 < 0 or b > len(db10) or a < 0:
                return None
            past = db10[p0:p1]
            window = db10[a:b]
            if not np.isfinite(past).all() or not np.isfinite(window).any():
                return None
            return float(np.median(past) - np.min(window[np.isfinite(window)]))

        def local_min(t: float) -> float | None:
            a = int(round((t - 0.25 - cov0) * 100))
            b = int(round((t + 0.25 - cov0) * 100))
            if a < 0 or b > len(db10):
                return None
            window = db10[a:b]
            if not np.isfinite(window).any():
                return None
            return float(np.min(window[np.isfinite(window)]))

        for start, end in pods_by[sid]:
            for kind, stamp in (("start", start), ("end", end)):
                description.append({
                    "session": sid,
                    "kind": kind,
                    "content": bag["content"],
                    "drop_db": local_drop(stamp),
                    "min_db": local_min(stamp),
                })
        t = cov0 + 30.0
        while t + 3.0 < cov1:
            if any(start - 20.0 <= t <= end + 20.0 for start, end in pods_by[sid]):
                t += 30.0
                continue
            value = local_drop(t)
            if value is not None:
                program_drops.append({"session": sid, "content": bag["content"], "drop_db": value})
            t += 30.0
        for start, _end in pods_by[sid]:
            frame = int(round((start - cov0) / 0.04))
            if 0 <= frame < len(flux):
                window = flux[frame : min(len(flux), frame + 6)]
                if np.isfinite(window).any():
                    flux_at.append(float(np.nanmax(window)))
            if 0 <= frame < len(corr) and np.isfinite(corr[frame]):
                corr_at.append(float(corr[frame]))
        sample = corr[:: max(len(corr) // 400, 1)]
        corr_program.extend(float(value) for value in sample[np.isfinite(sample)][:400])
        sample_f = flux[:: max(len(flux) // 400, 1)]
        flux_program.extend(float(value) for value in sample_f[np.isfinite(sample_f)][:400])

        times = (np.flatnonzero(finite) + 0.5) * 0.01 + cov0
        outside = region_mask(times, pods_by[sid], far=False)
        if sid == REDZONE:
            measured_s[sid]["redzone"] = float(outside.sum()) * 0.01
        elif bag["content"] == "sports":
            measured_s[sid]["program"] = float(outside.sum()) * 0.01
            measured_s[sid]["pod"] = float((~outside).sum()) * 0.01
        else:
            measured_s[sid]["scripted"] = float(outside.sum()) * 0.01
            measured_s[sid]["pod"] = float((~outside).sum()) * 0.01
        print(f"  floor {floors[sid]} short40 {events[(sid, 40, 'short')].size}", flush=True)

    def pool_times(scale: int, kind: str, sid: str) -> np.ndarray:
        values = events.get((sid, scale, kind))
        if values is None or values.size == 0:
            return np.zeros(0, dtype=np.float64)
        return np.sort(values)

    def recall(scale: int, kind: str, boundary_kind: str, population: str) -> dict:
        chosen = []
        for row in boundaries:
            sports = row["content"] == "sports" and row["session"] != REDZONE
            scripted = row["content"] != "sports"
            if population == "football" and not sports:
                continue
            if population == "scripted" and not scripted:
                continue
            if row["kind"] != boundary_kind:
                continue
            chosen.append(row)
        out = {"n": len(chosen)}
        delays = []
        for window in WINDOWS:
            hits = 0
            for row in chosen:
                times = pool_times(scale, kind, row["session"])
                if hit(times, row["t"], window):
                    hits += 1
                    if window == 1.0 and boundary_kind == "start":
                        delay = first_delay(times, row["t"], window)
                        if delay is not None:
                            delays.append(delay)
            out[str(window)] = hits
        if delays:
            ordered = np.sort(delays)
            out["delay_1s_median"] = round(float(np.median(ordered)), 3)
            out["delay_1s_p95"] = round(float(ordered[int(0.95 * (len(ordered) - 1))]), 3)
        return out

    def episode_rates(scale: int, kind: str) -> dict:
        counts = {"football_program": 0, "football_far": 0, "redzone": 0, "scripted": 0, "pod": 0, "pod_interior": 0}
        seconds = {"football_program": 0.0, "football_far": 0.0, "redzone": 0.0, "scripted": 0.0, "pod": 0.0, "pod_interior": 0.0}
        for sid, bag in sessions.items():
            times = pool_times(scale, kind, sid)
            pods = pods_by[sid]
            outside = region_mask(times, pods, far=False) if times.size else np.zeros(0, dtype=bool)
            far = region_mask(times, pods, far=True) if times.size else np.zeros(0, dtype=bool)
            inside = times.size - int(outside.sum()) if times.size else 0
            interior = 0
            for stamp in times.tolist():
                if any(start + 10.0 <= stamp < end - 10.0 for start, end in pods):
                    interior += 1
            if sid == REDZONE:
                counts["redzone"] += int(times.size)
                seconds["redzone"] += measured_s[sid]["redzone"]
            elif bag["content"] == "sports":
                counts["football_program"] += int(outside.sum()) if times.size else 0
                counts["football_far"] += int(far.sum()) if times.size else 0
                counts["pod"] += inside
                counts["pod_interior"] += interior
                seconds["football_program"] += measured_s[sid]["program"]
                seconds["football_far"] += measured_s[sid]["program"]
                seconds["pod"] += measured_s[sid]["pod"]
                seconds["pod_interior"] += measured_s[sid]["pod"]
            else:
                counts["scripted"] += int(outside.sum()) if times.size else 0
                seconds["scripted"] += measured_s[sid]["scripted"]
        return {
            name: {"episodes": counts[name], "seconds": round(seconds.get(name, 0.0), 1), "per_hour": rate(counts[name], seconds.get(name, 0.0))}
            for name in ("football_program", "football_far", "redzone", "scripted", "pod", "pod_interior")
        }

    start_rows = [row for row in boundaries if row["kind"] == "start" and row["content"] == "sports" and row["session"] != REDZONE]
    complement = 0
    for row in start_rows:
        if (row["session"], round(row["t"], 3)) in fresh:
            continue
        if hit(pool_times(40, "short", row["session"]), row["t"], 0.5):
            complement += 1
    operating = episode_rates(40, "short")
    program_rate = operating["football_program"]["per_hour"] or 0.0
    redzone_rate = operating["redzone"]["per_hour"] or 0.0
    recall_1s = recall(40, "short", "start", "football")
    recall_value = recall_1s["1.0"] / recall_1s["n"] if recall_1s["n"] else 0.0
    met = (
        program_rate <= DSP_FOOTBALL_PER_HOUR / 5.0
        and redzone_rate <= DSP_REDZONE_PER_HOUR / 5.0
        and recall_value >= GATE_RECALL_1S
    )
    complementary = (not met) and program_rate <= COMPLEMENT_RATE and complement >= COMPLEMENT_HITS
    gate = "MET" if met else ("COMPLEMENTARY" if complementary else "NOT_MET")

    def finite_values(rows: list[dict], key: str) -> list[float]:
        return [float(row[key]) for row in rows if row.get(key) is not None]

    start_drops = finite_values([row for row in description if row["kind"] == "start" and row["content"] == "sports"], "drop_db")
    end_drops = finite_values([row for row in description if row["kind"] == "end" and row["content"] == "sports"], "drop_db")
    control_drops = [row["drop_db"] for row in program_drops if row["content"] == "sports" and row["session"] != REDZONE]
    red_drops = [row["drop_db"] for row in program_drops if row["session"] == REDZONE]
    start_mins = finite_values([row for row in description if row["kind"] == "start" and row["content"] == "sports"], "min_db")

    def summarize(values: list[float]) -> dict:
        if not values:
            return {"n": 0}
        ordered = np.sort(values)
        return {
            "n": len(ordered),
            "p50": round(float(np.median(ordered)), 2),
            "p90": round(float(ordered[int(0.9 * (len(ordered) - 1))]), 2),
        }

    table = {}
    for scale in SCALES_MS:
        table[str(scale)] = {
            "short_start": recall(scale, "short", "start", "football"),
            "short_end": recall(scale, "short", "end", "football"),
            "absolute_start": recall(scale, "absolute", "start", "football"),
            "coarse_start": recall(scale, "coarse", "start", "football"),
            "rates_short": episode_rates(scale, "short"),
            "rates_absolute": episode_rates(scale, "absolute"),
            "rates_coarse": episode_rates(scale, "coarse"),
            "rejected": reject[scale],
        }
    table["40_both_channels"] = {
        "start": recall(40, "short_both_channels", "start", "football"),
        "end": recall(40, "short_both_channels", "end", "football"),
        "rates": episode_rates(40, "short_both_channels"),
    }
    payload = {
        "implementation_sha256": sha256_file(Path(__file__)),
        "literature": {
            "source": "https://arxiv.org/abs/1811.02411",
            "frame_samples": 1920,
            "frame_s": 0.04,
            "absolute_db": ABSOLUTE_DB,
            "regression_reproduced": False,
        },
        "relative": {"drop_db": DROP_DB, "recovery_db": RECOVERY_DB, "past_s": PAST_S, "past_floor_db": PAST_FLOOR_DB},
        "gate": gate,
        "gate_inputs": {
            "program_per_hour": program_rate,
            "redzone_per_hour": redzone_rate,
            "start_recall_1s": recall_value,
            "complement_hits_0.5s": complement,
            "football_starts": len(start_rows),
        },
        "scales": table,
        "descriptive_drop_db": {
            "football_starts": summarize(start_drops),
            "football_ends": summarize(end_drops),
            "football_program_controls": summarize(control_drops),
            "redzone_controls": summarize(red_drops),
            "starts_drop_ge_18": sum(1 for value in start_drops if value >= 18),
            "starts_min_db_le_m60": sum(1 for value in start_mins if value <= -60),
            "starts_described": len(start_drops),
        },
        "spectral_flux_40ms": {"at_start_causal_0.25s": summarize(flux_at), "program_sample": summarize(flux_program)},
        "stereo_corr_40ms": {"at_start_frame": summarize(corr_at), "program_sample": summarize(corr_program)},
        "floors": floors,
        "measured_s": measured_s,
        "wall_s": round(time.perf_counter() - started, 1),
        "max_rss_bytes": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    with (OUT / "boundary_drops.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["session", "kind", "content", "drop_db", "min_db"])
        writer.writeheader()
        writer.writerows(description)

    fig, ax = plt.subplots(figsize=(6.6, 4.0))
    for scale, style in ((10, "-"), (20, "--"), (40, "-"), (100, ":")):
        block = table[str(scale)]["short_start"]
        ys = [block[str(window)] / block["n"] for window in WINDOWS]
        ax.plot(list(WINDOWS), ys, style, label=f"{scale} ms", lw=1.6)
    ax.set_ylim(0, 1)
    ax.set_xlabel("Seconds after the commercial start")
    ax.set_ylabel("Football starts with a short dip")
    ax.set_title("Causal short-dip recall")
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(OUT / "recall.png", dpi=120)
    plt.close(fig)
    print(json.dumps({"gate": gate, "inputs": payload["gate_inputs"], "drop": payload["descriptive_drop_db"], "wall": payload["wall_s"]}, indent=2))


if __name__ == "__main__":
    main()
