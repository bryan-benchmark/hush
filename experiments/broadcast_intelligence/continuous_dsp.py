"""CONTINUOUS_DSP_001: every-second scan of the three frozen Batch 1 probes.

The boundary-centered hit counts are reproduced first. The scan does not
start if those counts differ. Thresholds are the leave-one-recording-out
95th percentiles of the same program-control windows Batch 1 used. They are
not recomputed from the continuous timeline, and they are not refit.

Rules frozen before the continuous counts are read:

- Candidate time t is an integer second on the recording clock.
- Previous audio is [t-2, t). Following audio is [t, t+1). Available at t+1.
- A start or end is credited only when start <= t <= boundary+W, for
  W in {1, 3, 5, 10, 30}. An alarm in the 5 seconds before the boundary is
  reported as already active and is not credited.
- Consecutive positive seconds are one episode. No refractory is applied.
- Pod collars of 10 seconds and a 15-second program collar are scoring
  bins, not detector rules.
- Departure and return are scored separately. PASS if football OR-recall
  within 3 seconds is at least 0.50. FAIL if it is under 0.25. Otherwise
  INCONCLUSIVE. Overall PASS only when both departure and return PASS.
  This scan does not emit a mute.
"""

from __future__ import annotations

import csv
import json
import resource
import sys
import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from experiments.broadcast_intelligence.batch1 import (
    SR,
    acoustics,
    commercials,
    coverage,
    load_catalog,
    percentile,
    read_span,
)
from hush.audio import find_session, load_session

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "docs/ohush/research/CONTINUOUS_DSP_001"
RECORDINGS = REPO / "recordings"
REDZONE = "hush_20260913_150934"
FEATURES = ("rms", "flatness", "centroid")
WINDOWS = (1, 3, 5, 10, 30)
PRE_LOOKBACK_S = 5.0
COLLAR_S = 10.0
PROGRAM_COLLAR_S = 15.0
BLOCK_S = 120
PUBLISHED = {
    "starts": {"rms": 71, "flatness": 74, "centroid": 62},
    "program_false": {"rms": 24, "flatness": 22, "centroid": 19},
    "program_tested": 440,
    "overlap": {
        "flatness_and_rms": 54,
        "flatness_only": 12,
        "rms_only": 15,
        "centroid_only": 12,
        "any_of_three": 103,
    },
    "redzone_false": {"rms": 1, "flatness": 4, "centroid": 5},
    "redzone_tested": 40,
    "redzone_p95": {"rms": 9.79367, "flatness": 0.077202, "centroid": 1652.848264},
}


def mono_of(audio: np.ndarray) -> np.ndarray:
    return 0.5 * (audio[:, 0].astype(np.float64) + audio[:, 1].astype(np.float64))


def deltas_from_parts(pre: np.ndarray, post: np.ndarray) -> tuple[float, float, float]:
    """Signed post-minus-pre RMS dB, flatness, and centroid. Same math as acoustics()."""
    pre_w = np.hanning(len(pre))
    post_w = np.hanning(len(post))
    pre_mag = np.maximum(np.abs(np.fft.rfft(pre * pre_w)), 1e-12)
    post_mag = np.maximum(np.abs(np.fft.rfft(post * post_w)), 1e-12)
    pre_freq = np.fft.rfftfreq(len(pre), 1.0 / SR)
    post_freq = np.fft.rfftfreq(len(post), 1.0 / SR)
    rms = float(np.sqrt(np.mean(pre * pre)) + 1e-12)
    rms2 = float(np.sqrt(np.mean(post * post)) + 1e-12)
    flat = float(np.exp(np.mean(np.log(pre_mag))) / np.mean(pre_mag))
    flat2 = float(np.exp(np.mean(np.log(post_mag))) / np.mean(post_mag))
    cent = float(np.sum(pre_freq * pre_mag) / np.sum(pre_mag))
    cent2 = float(np.sum(post_freq * post_mag) / np.sum(post_mag))
    return 20.0 * np.log10(rms2) - 20.0 * np.log10(rms), flat2 - flat, cent2 - cent


def deltas_block(mono: np.ndarray, n_steps: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """n_steps probes. mono begins 2 seconds before the first candidate."""
    need = (n_steps + 2) * SR
    if len(mono) < need:
        raise RuntimeError(f"block mono is {len(mono)} samples, need {need}")
    mono = mono[:need]
    pres = np.lib.stride_tricks.sliding_window_view(mono[: (n_steps + 1) * SR], 2 * SR)[::SR]
    posts = mono[2 * SR : (n_steps + 2) * SR].reshape(n_steps, SR)
    if pres.shape[0] != n_steps:
        raise RuntimeError(f"expected {n_steps} pre windows, got {pres.shape[0]}")
    pre_w = np.hanning(2 * SR)
    post_w = np.hanning(SR)
    pre_mag = np.maximum(np.abs(np.fft.rfft(pres * pre_w, axis=1)), 1e-12)
    post_mag = np.maximum(np.abs(np.fft.rfft(posts * post_w, axis=1)), 1e-12)
    pre_freq = np.fft.rfftfreq(2 * SR, 1.0 / SR)
    post_freq = np.fft.rfftfreq(SR, 1.0 / SR)
    rms = np.sqrt(np.mean(pres * pres, axis=1)) + 1e-12
    rms2 = np.sqrt(np.mean(posts * posts, axis=1)) + 1e-12
    flat = np.exp(np.mean(np.log(pre_mag), axis=1)) / np.mean(pre_mag, axis=1)
    flat2 = np.exp(np.mean(np.log(post_mag), axis=1)) / np.mean(post_mag, axis=1)
    cent = np.sum(pre_freq * pre_mag, axis=1) / np.sum(pre_mag, axis=1)
    cent2 = np.sum(post_freq * post_mag, axis=1) / np.sum(post_mag, axis=1)
    return 20.0 * np.log10(rms2) - 20.0 * np.log10(rms), flat2 - flat, cent2 - cent


def window_deltas(session_dir: Path, meta: dict, origin: float) -> tuple[float, float, float] | None:
    try:
        block = read_span(session_dir, meta, origin - 5.0, origin + 2.0)
    except RuntimeError:
        return None
    if len(block) < int(6.5 * SR):
        return None
    pre = mono_of(block[int(3.0 * SR) : int(5.0 * SR)])
    post = mono_of(block[int(5.0 * SR) : int(6.0 * SR)])
    return deltas_from_parts(pre, post)


def reproduce(sessions: dict, prepared: list[dict]) -> dict:
    """Recompute Batch 1's three boundary probes and return per-session thresholds."""
    boundaries = []
    for row in prepared:
        bag = sessions[row["session"]]
        for kind, origin in (("start", row["start_s"]), ("end", row["end_s"])):
            got = window_deltas(bag["dir"], bag["meta"], origin)
            if got is None:
                continue
            boundaries.append(
                {
                    "session": row["session"],
                    "kind": kind,
                    "origin_s": origin,
                    "rms": got[0],
                    "flatness": got[1],
                    "centroid": got[2],
                }
            )
    controls = []
    rng = np.random.default_rng(20261013)
    for sid, bag in sessions.items():
        cov0, cov1 = bag["coverage"]
        banned = [(row["start_s"] - 20.0, row["end_s"] + 20.0) for row in prepared if row["session"] == sid]
        times = np.arange(cov0 + 30.0, cov1 - 30.0, 45.0)
        times = [float(t) for t in times if not any(lo <= t <= hi for lo, hi in banned)]
        if len(times) > 40:
            times = list(rng.choice(times, size=40, replace=False))
        for origin in times:
            got = window_deltas(bag["dir"], bag["meta"], origin)
            if got is None:
                continue
            controls.append({"session": sid, "origin_s": origin, "rms": got[0], "flatness": got[1], "centroid": got[2]})

    check = window_deltas(sessions[prepared[0]["session"]]["dir"], sessions[prepared[0]["session"]]["meta"], prepared[0]["start_s"])
    if check is None:
        raise SystemExit("reproduction probe could not read the first commercial")
    block = read_span(
        sessions[prepared[0]["session"]]["dir"],
        sessions[prepared[0]["session"]]["meta"],
        prepared[0]["start_s"] - 5.0,
        prepared[0]["start_s"] + 2.0,
    )
    pre_a = acoustics(block[int(3.0 * SR) : int(5.0 * SR)])
    post_a = acoustics(block[int(5.0 * SR) : int(6.0 * SR)])
    reference = (
        post_a["rms_db"] - pre_a["rms_db"],
        post_a["flatness"] - pre_a["flatness"],
        post_a["centroid_hz"] - pre_a["centroid_hz"],
    )
    if max(abs(a - b) for a, b in zip(check, reference)) > 1e-9:
        raise SystemExit(f"slim probe disagrees with acoustics(): {check} vs {reference}")

    starts = [row for row in boundaries if row["kind"] == "start"]
    levels: dict[str, dict[str, float]] = {sid: {} for sid in sessions}
    hits = {name: set() for name in FEATURES}
    program_false = {name: 0 for name in FEATURES}
    program_tested = 0
    for sid in {row["session"] for row in starts}:
        others = [row for row in controls if row["session"] != sid]
        if len(others) < 20:
            continue
        level = {name: percentile([abs(row[name]) for row in others], 95) for name in FEATURES}
        levels[sid] = level
        tested_here = [row for row in starts if row["session"] == sid]
        if tested_here:
            program_tested += sum(1 for row in controls if row["session"] == sid)
        for row in tested_here:
            for name in FEATURES:
                if abs(row[name]) >= level[name]:
                    hits[name].add((row["session"], round(row["origin_s"], 3)))
        for row in controls:
            if row["session"] != sid:
                continue
            for name in FEATURES:
                if abs(row[name]) >= level[name]:
                    program_false[name] += 1
    redzone_controls = [row for row in controls if row["session"] == REDZONE]
    others = [row for row in controls if row["session"] != REDZONE]
    redzone_level = {name: percentile([abs(row[name]) for row in others], 95) for name in FEATURES}
    levels[REDZONE] = redzone_level
    redzone_false = {
        name: sum(1 for row in redzone_controls if abs(row[name]) >= redzone_level[name]) for name in FEATURES
    }
    flat, rms, cent = hits["flatness"], hits["rms"], hits["centroid"]
    overlap = {
        "flatness_and_rms": len(flat & rms),
        "flatness_only": len(flat - rms - cent),
        "rms_only": len(rms - flat - cent),
        "centroid_only": len(cent - flat - rms),
        "any_of_three": len(flat | rms | cent),
    }
    problems = []
    for name in FEATURES:
        if len(hits[name]) != PUBLISHED["starts"][name]:
            problems.append(f"{name} starts {len(hits[name])} != {PUBLISHED['starts'][name]}")
        if program_false[name] != PUBLISHED["program_false"][name]:
            problems.append(f"{name} program false {program_false[name]} != {PUBLISHED['program_false'][name]}")
        if redzone_false[name] != PUBLISHED["redzone_false"][name]:
            problems.append(f"{name} redzone false {redzone_false[name]} != {PUBLISHED['redzone_false'][name]}")
        if round(redzone_level[name], 6) != PUBLISHED["redzone_p95"][name]:
            problems.append(f"{name} redzone p95 {redzone_level[name]} != {PUBLISHED['redzone_p95'][name]}")
    if program_tested != PUBLISHED["program_tested"] or len(redzone_controls) != PUBLISHED["redzone_tested"]:
        problems.append(f"control counts program {program_tested} redzone {len(redzone_controls)}")
    for key, value in overlap.items():
        if value != PUBLISHED["overlap"][key]:
            problems.append(f"overlap {key} {value} != {PUBLISHED['overlap'][key]}")
    if problems:
        raise SystemExit("Batch 1 probe was not reproduced:\n" + "\n".join(problems))
    return {
        "n_start_windows": len(starts),
        "n_controls": len(controls),
        "hits": {name: len(hits[name]) for name in FEATURES},
        "overlap": overlap,
        "program_false": program_false,
        "redzone_false": redzone_false,
        "thresholds": {sid: {name: level[name] for name in FEATURES} for sid, level in levels.items() if level},
    }


def scan_session(bag: dict, level: dict[str, float]) -> dict:
    cov0, cov1 = bag["coverage"]
    t_first = int(np.ceil(cov0 + 2.0 - 1e-9))
    t_last = int(np.floor(cov1 - 1.0 + 1e-9))
    times = np.arange(t_first, t_last + 1, dtype=np.int32)
    flags = {name: np.zeros(times.size, dtype=bool) for name in FEATURES}
    missing = np.zeros(times.size, dtype=bool)
    cursor = 0
    while cursor < times.size:
        # The integer grid is contiguous, so a block is one read.
        step = min(BLOCK_S, int(times.size - cursor))
        if int(times[cursor + step - 1]) != int(times[cursor]) + step - 1:
            step = 1
        t0 = int(times[cursor])
        try:
            audio = read_span(bag["dir"], bag["meta"], t0 - 2.0, float(t0 + step))
            mono = mono_of(audio)
        except RuntimeError:
            missing[cursor] = True
            cursor += 1
            continue
        available = len(mono) // SR - 2
        if available < 1:
            missing[cursor] = True
            cursor += 1
            continue
        step = min(step, available)
        rms, flat, cent = deltas_block(mono, step)
        signed = {"rms": rms, "flatness": flat, "centroid": cent}
        for name in FEATURES:
            flags[name][cursor : cursor + step] = np.abs(signed[name]) >= level[name]
        cursor += step
    return {"t_first": t_first, "times": times, "flags": flags, "missing": missing}


def assert_block_matches_scalar() -> None:
    mono = np.random.default_rng(1).standard_normal((6) * SR)
    scalar = deltas_from_parts(mono[SR : 3 * SR], mono[3 * SR : 4 * SR])
    batched = deltas_block(mono[SR : 6 * SR], 3)
    got = (float(batched[0][0]), float(batched[1][0]), float(batched[2][0]))
    if max(abs(a - b) for a, b in zip(scalar, got)) > 1e-8:
        raise SystemExit(f"batched probe disagrees with the scalar probe: {got} vs {scalar}")


def episodes(times: np.ndarray, mask: np.ndarray) -> list[tuple[int, int, int]]:
    runs = []
    start = None
    previous = None
    count = 0
    for t, on in zip(times.tolist(), mask.tolist()):
        if not on:
            if start is not None:
                runs.append((start, previous, count))
            start = None
            previous = None
            count = 0
            continue
        if start is None or t != previous + 1:
            if start is not None:
                runs.append((start, previous, count))
            start = t
            count = 1
        else:
            count += 1
        previous = t
    if start is not None:
        runs.append((start, previous, count))
    return runs


def in_span(t: float, spans: list[tuple[float, float]]) -> bool:
    return any(lo <= t < hi for lo, hi in spans)


def first_credit(times: np.ndarray, mask: np.ndarray, boundary: float, limit: float) -> float | None:
    if times.size == 0:
        return None
    # Integer candidates at or after the boundary, through boundary+limit.
    lo = np.searchsorted(times, boundary, side="left")
    hi = np.searchsorted(times, boundary + limit, side="right")
    chosen = np.flatnonzero(mask[lo:hi])
    if chosen.size == 0:
        return None
    return float(times[lo + int(chosen[0])])


def rate(count: float, seconds: float) -> float | None:
    if seconds <= 0:
        return None
    return count / (seconds / 3600.0)


def verdict_for(recall: float | None) -> str:
    if recall is None:
        return "INCONCLUSIVE"
    if recall >= 0.50:
        return "PASS"
    if recall < 0.25:
        return "FAIL"
    return "INCONCLUSIVE"


def main() -> None:
    sys.stdout.reconfigure(line_buffering=True)
    started = time.perf_counter()
    assert_block_matches_scalar()
    catalog = load_catalog()
    spans = coverage()
    rows = commercials(spans)
    if len(rows) != 166:
        raise SystemExit(f"expected 166 target commercials, found {len(rows)}")
    sessions = {}
    for span in spans:
        sid = span["session"]
        if sid in sessions:
            continue
        folder = find_session(RECORDINGS, sid)
        meta = load_session(folder)
        sessions[sid] = {
            "dir": folder,
            "meta": meta,
            "coverage": (float(span["from_seconds"]), float(span["to_seconds"])),
        }
    prepared = []
    for row in rows:
        info = catalog.get(row["session"], {})
        prepared.append(
            {
                "session": row["session"],
                "network": info.get("network_or_service") or "unknown",
                "content": info.get("content_type") or "",
                "show": info.get("show") or "",
                "start_s": float(row["start_seconds"]),
                "end_s": float(row["end_seconds"]),
            }
        )
    print("phase 1: reproducing frozen boundary probes", flush=True)
    frozen = reproduce(sessions, prepared)
    print("phase 1 matched Batch 1", json.dumps(frozen["hits"]), json.dumps(frozen["overlap"]), flush=True)

    scans = {}
    for sid, bag in sessions.items():
        level = frozen["thresholds"].get(sid)
        if not level:
            raise SystemExit(f"no reproduced threshold for {sid}")
        print(f"scan {sid}", flush=True)
        scans[sid] = scan_session(bag, level)
        scans[sid]["level"] = level
        n_or = int(np.any(np.vstack([scans[sid]["flags"][name] for name in FEATURES]), axis=0).sum())
        print(f"  seconds {scans[sid]['times'].size} missing {int(scans[sid]['missing'].sum())} or_alarms {n_or}", flush=True)

    cnn_rows = list(csv.DictReader((REPO / "docs/ohush/research/AUDIO_SIGNAL_REPLICATION_001/nbc_breaks.csv").open(encoding="utf-8")))
    by_session: dict[str, list[dict]] = {}
    for row in prepared:
        by_session.setdefault(row["session"], []).append(row)

    start_table = []
    end_table = []
    recording_rows = []
    episode_rows = []
    example = {"longest_program_episode": None, "busiest_pod": None}

    for sid, bag in sessions.items():
        scan = scans[sid]
        times = scan["times"]
        info = catalog.get(sid, {})
        network = info.get("network_or_service") or "unknown"
        content = info.get("content_type") or ""
        pods = [(row["start_s"], row["end_s"]) for row in by_session.get(sid, [])]
        or_mask = np.any(np.vstack([scan["flags"][name] for name in FEATURES]), axis=0) & ~scan["missing"]
        masks = {name: scan["flags"][name] & ~scan["missing"] for name in FEATURES}
        masks["or"] = or_mask
        program = np.asarray([not in_span(float(t), pods) for t in times], dtype=bool) & ~scan["missing"]
        in_pod = np.asarray([in_span(float(t), pods) for t in times], dtype=bool) & ~scan["missing"]
        near_boundary = np.zeros(times.size, dtype=bool)
        for lo, hi in pods:
            near_boundary |= (times >= lo - PROGRAM_COLLAR_S) & (times < lo)
            near_boundary |= (times >= hi) & (times < hi + PROGRAM_COLLAR_S)
        near_boundary &= program
        far = program & ~near_boundary

        def region_seconds(name: str) -> dict:
            mask = masks[name]
            return {
                "scanned": int((~scan["missing"]).sum()),
                "program_seconds": int(program.sum()),
                "program_alarm_seconds": int((mask & program).sum()),
                "program_alarm_seconds_per_hour": rate(int((mask & program).sum()), float(program.sum())),
                "program_near_boundary_alarm_seconds": int((mask & near_boundary).sum()),
                "program_near_boundary_seconds": int(near_boundary.sum()),
                "program_far_alarm_seconds": int((mask & far).sum()),
                "program_far_seconds": int(far.sum()),
                "pod_alarm_seconds": int((mask & in_pod).sum()),
                "pod_seconds_on_grid": int(in_pod.sum()),
            }

        feature_regions = {name: region_seconds(name) for name in ("or", *FEATURES)}
        for name, mask in masks.items():
            for t0, t1, count in episodes(times, mask):
                episode_rows.append(
                    {
                        "session": sid,
                        "network": network,
                        "content": content,
                        "feature": name,
                        "t_start": t0,
                        "t_end": t1,
                        "n_seconds": count,
                        "available_at": t0 + 1,
                    }
                )
                if name == "or" and count > 0 and all(not in_span(float(t), pods) for t in range(t0, t1 + 1)):
                    current = example["longest_program_episode"]
                    if current is None or count > current["n_seconds"]:
                        example["longest_program_episode"] = {
                            "session": sid,
                            "network": network,
                            "t_start": t0,
                            "t_end": t1,
                            "n_seconds": count,
                            "available_at": t0 + 1,
                        }

        pod_alarm_seconds = []
        middle_alarm = 0
        middle_seconds = 0
        near_end_alarm = 0
        near_end_seconds = 0
        near_start_alarm = 0
        near_start_seconds = 0
        for row in by_session.get(sid, []):
            grid = (times >= row["start_s"]) & (times < row["end_s"]) & ~scan["missing"]
            n_alarm = int((or_mask & grid).sum())
            pod_alarm_seconds.append(n_alarm)
            if example["busiest_pod"] is None or n_alarm > example["busiest_pod"]["or_alarm_seconds"]:
                example["busiest_pod"] = {
                    "session": sid,
                    "start_s": row["start_s"],
                    "end_s": row["end_s"],
                    "or_alarm_seconds": n_alarm,
                    "pod_grid_seconds": int(grid.sum()),
                }
            middle = (times >= row["start_s"] + COLLAR_S) & (times < row["end_s"] - COLLAR_S) & ~scan["missing"]
            tail = (times >= row["end_s"] - COLLAR_S) & (times < row["end_s"]) & ~scan["missing"]
            head = (times >= row["start_s"]) & (times < row["start_s"] + COLLAR_S) & ~scan["missing"]
            middle_alarm += int((or_mask & middle).sum())
            middle_seconds += int(middle.sum())
            near_end_alarm += int((or_mask & tail).sum())
            near_end_seconds += int(tail.sum())
            near_start_alarm += int((or_mask & head).sum())
            near_start_seconds += int(head.sum())

        or_eps = [row for row in episode_rows if row["session"] == sid and row["feature"] == "or"]
        program_eps = [
            row for row in or_eps if all(not in_span(float(t), pods) for t in range(row["t_start"], row["t_end"] + 1))
        ]
        recording_rows.append(
            {
                "session": sid,
                "network": network,
                "content": content,
                "show": info.get("show") or "",
                "coverage": list(bag["coverage"]),
                "missing_seconds": int(scan["missing"].sum()),
                "thresholds": {name: scan["level"][name] for name in FEATURES},
                "features": feature_regions,
                "or_episodes": len(or_eps),
                "or_program_episodes": len(program_eps),
                "or_program_episodes_per_hour": rate(len(program_eps), float(program.sum())),
                "pod_middle_or_alarm_seconds": middle_alarm,
                "pod_middle_seconds": middle_seconds,
                "pod_near_end_or_alarm_seconds": near_end_alarm,
                "pod_near_end_seconds": near_end_seconds,
                "pod_near_start_or_alarm_seconds": near_start_alarm,
                "pod_near_start_seconds": near_start_seconds,
            }
        )

        for kind, table, boundary_key in (("start", start_table, "start_s"), ("end", end_table, "end_s")):
            for row in by_session.get(sid, []):
                boundary = row[boundary_key]
                eligible_idx = np.flatnonzero((times >= boundary) & (times <= boundary + 30) & ~scan["missing"])
                entry = {
                    "session": sid,
                    "network": network,
                    "content": content,
                    "boundary_s": boundary,
                    "other_s": row["end_s"] if kind == "start" else row["start_s"],
                    "eligible": bool(eligible_idx.size),
                    "already_active_in_prior_5s": bool(
                        np.any(or_mask[(times >= boundary - PRE_LOOKBACK_S) & (times < boundary)])
                    ),
                }
                earliest = {}
                for name, mask in masks.items():
                    hit = {str(window): first_credit(times, mask, boundary, window) is not None for window in WINDOWS}
                    first = first_credit(times, mask, boundary, 30)
                    earliest[name] = {
                        "within": hit,
                        "earliest_t": first,
                        "delay_s": None if first is None else round(first - boundary, 3),
                    }
                which = {}
                for name in FEATURES:
                    which[name] = earliest[name]["within"]["30"]
                entry["features"] = earliest
                entry["unique_within_30s"] = {
                    "rms": bool(which["rms"] and not which["flatness"] and not which["centroid"]),
                    "flatness": bool(which["flatness"] and not which["rms"] and not which["centroid"]),
                    "centroid": bool(which["centroid"] and not which["rms"] and not which["flatness"]),
                }
                if sid == "hush_20260909_213047" and kind == "start":
                    match = None
                    for cnn in cnn_rows:
                        if abs(float(cnn["start_s"]) - boundary) <= 0.05:
                            match = cnn
                            break
                    entry["cnn_failure"] = None if match is None else match["failure"]
                    raw_hit = None if match is None else match["first_causal_hit_during_break_s"]
                    entry["cnn_causal_hit_s"] = None if raw_hit in (None, "") else float(raw_hit)
                table.append(entry)

    def summarize(table: list[dict], football_only: bool) -> dict:
        chosen = [row for row in table if (row["content"] == "sports") == football_only or not football_only]
        if football_only:
            chosen = [row for row in table if row["content"] == "sports"]
        eligible = [row for row in chosen if row["eligible"]]
        out = {"events": len(chosen), "eligible": len(eligible), "startup_or_grid_unavailable": len(chosen) - len(eligible)}
        for name in ("or", *FEATURES):
            delays = [row["features"][name]["delay_s"] for row in eligible if row["features"][name]["delay_s"] is not None]
            out[name] = {
                "within": {
                    str(window): sum(1 for row in eligible if row["features"][name]["within"][str(window)])
                    for window in WINDOWS
                },
                "never_within_30s": sum(1 for row in eligible if row["features"][name]["delay_s"] is None),
                "median_delay_s": None if not delays else round(float(np.median(delays)), 3),
                "p95_delay_s": None if not delays else round(float(np.percentile(delays, 95)), 3),
            }
        out["already_active_in_prior_5s"] = sum(1 for row in eligible if row["already_active_in_prior_5s"])
        out["unique_within_30s"] = {
            name: sum(1 for row in eligible if row["unique_within_30s"][name]) for name in FEATURES
        }
        recall = None
        if eligible:
            recall = out["or"]["within"]["3"] / len(eligible)
        out["or_recall_within_3s"] = None if recall is None else round(recall, 4)
        out["verdict"] = verdict_for(recall)
        return out

    football_starts = summarize(start_table, True)
    football_ends = summarize(end_table, True)
    all_starts = summarize(start_table, False)
    all_ends = summarize(end_table, False)
    if football_starts["verdict"] == "PASS" and football_ends["verdict"] == "PASS":
        overall = "PASS"
    elif football_starts["verdict"] == "FAIL" and football_ends["verdict"] == "FAIL":
        overall = "FAIL"
    else:
        overall = "INCONCLUSIVE"

    sept9 = [row for row in start_table if row["session"] == "hush_20260909_213047"]
    dsp30 = [row for row in sept9 if row["features"]["or"]["within"]["30"]]
    cnn = [row for row in sept9 if row.get("cnn_causal_hit_s") is not None]
    both = [row for row in sept9 if row["features"]["or"]["within"]["30"] and row.get("cnn_causal_hit_s") is not None]
    dsp_only = [row for row in sept9 if row["features"]["or"]["within"]["30"] and row.get("cnn_causal_hit_s") is None]
    cnn_only = [row for row in sept9 if row.get("cnn_causal_hit_s") is not None and not row["features"]["or"]["within"]["30"]]
    sept9_summary = {
        "starts": len(sept9),
        "dsp_or_within_30s": len(dsp30),
        "dsp_or_within_3s": sum(1 for row in sept9 if row["features"]["or"]["within"]["3"]),
        "cnn_causal_hit": len(cnn),
        "both_within_30s": len(both),
        "dsp_only_within_30s": len(dsp_only),
        "cnn_only": len(cnn_only),
        "neither_within_30s": len(sept9) - len(dsp30) - len(cnn_only),
        "dsp_only_starts": [row["boundary_s"] for row in dsp_only],
        "cnn_only_starts": [row["boundary_s"] for row in cnn_only],
        "missed_by_both": [row["boundary_s"] for row in sept9 if not row["features"]["or"]["within"]["30"] and row.get("cnn_causal_hit_s") is None],
    }

    elapsed = time.perf_counter() - started
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # macOS reports bytes. Linux reports kilobytes.
    if rss > 10**12:
        rss_bytes = rss
    elif sys.platform == "darwin":
        rss_bytes = rss
    else:
        rss_bytes = rss * 1024

    payload = {
        "rule": {
            "grid": "integer recording seconds",
            "credit": "boundary <= t <= boundary+W; prior 5 s is not credited",
            "windows_s": list(WINDOWS),
            "pass_recall_within_3s": 0.50,
            "fail_recall_within_3s": 0.25,
            "collars_s": {"pod": COLLAR_S, "program": PROGRAM_COLLAR_S},
        },
        "reproduction": {
            "matched_batch1": True,
            "hits": frozen["hits"],
            "overlap": frozen["overlap"],
            "n_start_windows": frozen["n_start_windows"],
            "n_controls": frozen["n_controls"],
            "redzone_false": frozen["redzone_false"],
            "thresholds": frozen["thresholds"],
        },
        "football_starts": football_starts,
        "football_ends": football_ends,
        "all_starts": all_starts,
        "all_ends": all_ends,
        "overall_verdict": overall,
        "sept9_vs_cnn14": sept9_summary,
        "recordings": recording_rows,
        "examples": example,
        "compute": {"wall_s": round(elapsed, 1), "max_rss_bytes": int(rss_bytes)},
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    def write_events(path: Path, table: list[dict]) -> None:
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "session",
                    "network",
                    "content",
                    "boundary_s",
                    "eligible",
                    "already_active_in_prior_5s",
                    "or_delay_s",
                    "or_within_1",
                    "or_within_3",
                    "or_within_5",
                    "or_within_10",
                    "or_within_30",
                    "rms_within_30",
                    "flatness_within_30",
                    "centroid_within_30",
                    "unique_rms",
                    "unique_flatness",
                    "unique_centroid",
                    "cnn_failure",
                    "cnn_causal_hit_s",
                ],
            )
            writer.writeheader()
            for row in table:
                feat = row["features"]
                writer.writerow(
                    {
                        "session": row["session"],
                        "network": row["network"],
                        "content": row["content"],
                        "boundary_s": row["boundary_s"],
                        "eligible": row["eligible"],
                        "already_active_in_prior_5s": row["already_active_in_prior_5s"],
                        "or_delay_s": feat["or"]["delay_s"],
                        "or_within_1": feat["or"]["within"]["1"],
                        "or_within_3": feat["or"]["within"]["3"],
                        "or_within_5": feat["or"]["within"]["5"],
                        "or_within_10": feat["or"]["within"]["10"],
                        "or_within_30": feat["or"]["within"]["30"],
                        "rms_within_30": feat["rms"]["within"]["30"],
                        "flatness_within_30": feat["flatness"]["within"]["30"],
                        "centroid_within_30": feat["centroid"]["within"]["30"],
                        "unique_rms": row["unique_within_30s"]["rms"],
                        "unique_flatness": row["unique_within_30s"]["flatness"],
                        "unique_centroid": row["unique_within_30s"]["centroid"],
                        "cnn_failure": row.get("cnn_failure", ""),
                        "cnn_causal_hit_s": row.get("cnn_causal_hit_s", ""),
                    }
                )

    write_events(OUT / "starts.csv", start_table)
    write_events(OUT / "ends.csv", end_table)
    with (OUT / "episodes.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["session", "network", "content", "feature", "t_start", "t_end", "n_seconds", "available_at"],
        )
        writer.writeheader()
        writer.writerows(episode_rows)

    fig, ax = plt.subplots(figsize=(7.5, 4.2))
    for name, style in (("or", "-"), ("rms", "--"), ("flatness", "--"), ("centroid", ":")):
        ys = [football_starts[name]["within"][str(window)] / max(football_starts["eligible"], 1) for window in WINDOWS]
        ax.plot(list(WINDOWS), ys, style, label=name, lw=1.8)
    ax.set_ylim(0, 1)
    ax.set_xlabel("Seconds after the commercial start")
    ax.set_ylabel("Football starts with a candidate")
    ax.set_title("Continuous probe recall, football starts")
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(OUT / "recall_starts.png", dpi=120)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8.5, 4.4))
    labels = []
    values = []
    for row in recording_rows:
        labels.append("RedZone" if row["session"] == REDZONE else row["network"][:12])
        values.append(row["or_program_episodes_per_hour"] or 0)
    ax.bar(range(len(values)), values, color=["#b00020" if row["session"] == REDZONE else "#444444" for row in recording_rows])
    ax.set_xticks(range(len(labels)), labels, rotation=45, ha="right")
    ax.set_ylabel("Program episodes per hour")
    ax.set_title("OR candidate episodes on program audio")
    fig.tight_layout()
    fig.savefig(OUT / "program_episodes_per_hour.png", dpi=120)
    plt.close(fig)

    print(json.dumps({
        "overall": overall,
        "football_starts": football_starts["or"]["within"],
        "football_start_recall_3s": football_starts["or_recall_within_3s"],
        "football_ends": football_ends["or"]["within"],
        "football_end_recall_3s": football_ends["or_recall_within_3s"],
        "sept9": sept9_summary,
        "wall_s": payload["compute"]["wall_s"],
    }, indent=2))


if __name__ == "__main__":
    main()
