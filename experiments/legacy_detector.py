"""discontinuity_legacy_v0: the scorer and selector that produced the saved candidates.

Score every frame, sort high to low, greedily keep frames at least min_gap_s
apart, stop at top_k. No local-maximum filter and no score floor.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

import numpy as np

DETECTOR_ID = "discontinuity_legacy_v0"
FEATURE_SCHEMA = "legacy_v0_trace_1"
BREAK_DETECTOR_ID = "break_structure_legacy_v0"

# Historical candidate file was generated with top_k=6.
# The old CLI default (--top-k-per-chunk) was 8; do not treat that as the freeze.
DEFAULT_TOP_K = 6

PARAMS = {
    "detector_id": DETECTOR_ID,
    "win_s": 0.25,
    "hop_s": 0.125,
    "jump_lag_hops": 8,
    "flux_weight": 0.75,
    "silence_bonus": 0.5,
    "silence_db": -45.0,
    "silence_radius_hops": 4,
    "min_gap_s": 25.0,
    "top_k": DEFAULT_TOP_K,
    "silent_chunk_max_abs": 1e-4,
    "normalization_scope": "chunk",
}

BREAK_PARAMS = {
    "detector_id": BREAK_DETECTOR_ID,
    "pre_s": 15.0,
    "post_s": 240.0,
    "fade_db": -42.0,
    "fade_drop_prev_db": 6.0,
    "fade_drop_next_db": 4.0,
    "fade_min_gap_s": 10.0,
    "fade_skip_after_in_s": 10.0,
    "out_db": -40.0,
    "out_min_after_in_s": 90.0,
    "out_max_after_in_s": 240.0,
    "out_recovery_hops": 7,
    "out_flux_weight": 0.3,
    "fade_keep_limit": 15,
    "out_keep_reported": 8,
}


_PCM_CACHE: dict[str, tuple] = {}
_PCM_ORDER: list[str] = []


def load_pcm16(path: Path):
    key = str(Path(path).resolve())
    hit = _PCM_CACHE.get(key)
    if hit is not None:
        return hit
    loaded = _load_pcm16_uncached(path)
    _PCM_CACHE[key] = loaded
    _PCM_ORDER.append(key)
    while len(_PCM_ORDER) > 3:
        _PCM_CACHE.pop(_PCM_ORDER.pop(0), None)
    return loaded


def _load_pcm16_uncached(path: Path):
    raw = path.read_bytes()
    if raw[0:4] != b"RIFF":
        raise RuntimeError(f"not wav: {path}")
    ch = struct.unpack_from("<H", raw, 22)[0]
    rate = struct.unpack_from("<I", raw, 24)[0]
    pos = 12
    data_off = 44
    while pos + 8 <= len(raw):
        cid = raw[pos : pos + 4]
        sz = struct.unpack_from("<I", raw, pos + 4)[0]
        if cid == b"data":
            data_off = pos + 8
            break
        pos += 8 + sz + (sz % 2)
    payload = raw[data_off:]
    usable = len(payload) - (len(payload) % (ch * 2))
    x = np.frombuffer(payload[:usable], dtype="<i2").astype(np.float32)
    x = x.reshape(-1, ch).mean(axis=1) / 32768.0
    n_samples = int(x.shape[0])
    return rate, ch, n_samples, x


def wav_header(path: Path):
    """Header facts without decoding samples."""
    raw = path.read_bytes()[:4096]
    if raw[0:4] != b"RIFF":
        raise RuntimeError(f"not wav: {path}")
    ch = struct.unpack_from("<H", raw, 22)[0]
    rate = struct.unpack_from("<I", raw, 24)[0]
    pos = 12
    data_off = None
    data_sz = None
    while pos + 8 <= len(raw):
        cid = raw[pos : pos + 4]
        sz = struct.unpack_from("<I", raw, pos + 4)[0]
        if cid == b"data":
            data_off = pos + 8
            data_sz = sz
            break
        pos += 8 + sz + (sz % 2)
    if data_off is None or data_sz is None:
        raise RuntimeError(f"no data chunk: {path}")
    # data_sz can be wrong if the header probe was truncated; use file size.
    file_size = path.stat().st_size
    payload = max(0, file_size - data_off)
    usable = payload - (payload % (ch * 2))
    n_frames = usable // (ch * 2)
    return {
        "sample_rate": int(rate),
        "channels": int(ch),
        "n_frames": int(n_frames),
        "duration_seconds": n_frames / float(rate),
        "data_offset": int(data_off),
    }


def frame_features(x: np.ndarray, rate: int, win_s: float = 0.25, hop_s: float = 0.125):
    """Vectorized equivalent of the original per-frame RMS + positive spectral flux."""
    win = int(win_s * rate)
    hop = int(hop_s * rate)
    if len(x) < win:
        n = 1
        return np.arange(n) * hop_s, np.zeros(n), np.zeros(n)
    n = 1 + (len(x) - win) // hop
    usable = (n - 1) * hop + win
    xv = np.ascontiguousarray(x[:usable])
    frames = np.lib.stride_tricks.as_strided(
        xv,
        shape=(n, win),
        strides=(xv.strides[0] * hop, xv.strides[0]),
        writeable=False,
    )
    mean_sq = np.mean(frames * frames, axis=1)
    rms = np.sqrt(mean_sq + 1e-12)
    hann = np.hanning(win)
    spec = np.abs(np.fft.rfft(frames * hann, axis=1))
    flux = np.zeros(n, dtype=np.float64)
    if n > 1:
        diff = spec[1:] - spec[:-1]
        flux[1:] = np.sum(np.where(diff > 0, diff, 0.0), axis=1)
    times = np.arange(n, dtype=np.float64) * hop_s
    return times, rms, flux


def frame_features_loop(x: np.ndarray, rate: int, win_s: float = 0.25, hop_s: float = 0.125):
    """Original frame loop, kept so tests can prove the vectorized path matches."""
    win = int(win_s * rate)
    hop = int(hop_s * rate)
    n = 1 + max(0, (len(x) - win) // hop)
    rms = np.zeros(n, dtype=np.float64)
    flux = np.zeros(n, dtype=np.float64)
    prev = None
    for i in range(n):
        seg = x[i * hop : i * hop + win]
        if len(seg) < win:
            break
        rms[i] = np.sqrt(np.mean(seg * seg) + 1e-12)
        spec = np.abs(np.fft.rfft(seg * np.hanning(win)))
        if prev is None:
            flux[i] = 0.0
        else:
            diff = spec - prev
            flux[i] = float(np.sum(diff[diff > 0]))
        prev = spec
    times = np.arange(n) * hop_s
    return times, rms, flux


def score_frames(rms: np.ndarray, flux: np.ndarray, params: dict | None = None):
    p = params or PARAMS
    lag = int(p["jump_lag_hops"])
    radius = int(p["silence_radius_hops"])
    rms_db = 20 * np.log10(rms + 1e-12)
    jump = np.zeros_like(rms_db)
    jump[lag:] = np.abs(rms_db[lag:] - rms_db[:-lag])
    flux_std = float(flux.std())
    jump_std = float(jump.std())
    flux_mean = float(flux.mean())
    jump_mean = float(jump.mean())
    flux_z = (flux - flux_mean) / (flux_std + 1e-9)
    jump_z = (jump - jump_mean) / (jump_std + 1e-9)
    silent = rms_db < float(p["silence_db"])
    score = jump_z + float(p["flux_weight"]) * flux_z
    pad = np.pad(silent, (radius, radius), constant_values=False)
    windows = np.lib.stride_tricks.sliding_window_view(pad, radius * 2 + 1)
    near = np.asarray(windows.any(axis=1))
    bonus = np.where(near, float(p["silence_bonus"]), 0.0).astype(np.float64)
    score = score + bonus
    norm = {
        "jump_mean": jump_mean,
        "jump_std": jump_std,
        "flux_mean": flux_mean,
        "flux_std": flux_std,
        "scope": "chunk",
    }
    return {
        "rms_db": rms_db,
        "jump_db": jump,
        "flux_raw": flux,
        "flux_z": flux_z,
        "jump_z": jump_z,
        "silent": silent,
        "near_silence": near,
        "silence_bonus": bonus,
        "score": score,
        "norm": norm,
    }


def _legacy_row(idx: int, times, scored) -> dict:
    t = float(times[idx])
    i = int(idx)
    return {
        "elapsed_seconds": round(t, 3),
        "score": round(float(scored["score"][i]), 3),
        "rms_dbfs": round(float(scored["rms_db"][i]), 2),
        "loudness_jump_db": round(float(scored["jump_db"][i]), 2),
        "flux_z": round(float(scored["flux_z"][i]), 2),
        "near_silence": bool(scored["near_silence"][i]),
        "_frame_index": i,
        "_t_exact": t,
    }


def select_legacy(times: np.ndarray, scored: dict, params: dict | None = None):
    """Rank every frame. Return keeps, min-gap suppressions, and the top_k cutoff.

    Suppressions are only those evaluated before top_k filled. Frames after the
    cutoff are not individually listed; `cutoff` describes the next frame in
    score order and whether min-gap would have rejected it.
    """
    p = params or PARAMS
    min_gap_s = float(p["min_gap_s"])
    top_k = int(p["top_k"])
    score = scored["score"]
    order = np.argsort(score)[::-1]
    picked: list[dict] = []
    suppressed: list[dict] = []
    cutoff = None

    for rank, idx in enumerate(order):
        idx = int(idx)
        t = float(times[idx])
        blocker = None
        gap = None
        for prev in picked:
            gap_s = abs(t - prev["elapsed_seconds"])
            if gap_s < min_gap_s:
                blocker = prev
                gap = gap_s
                break
        if blocker is not None:
            if len(picked) < top_k:
                row = _legacy_row(idx, times, scored)
                suppressed.append(
                    {
                        **row,
                        "score_rank": int(rank),
                        "reason": "min_gap",
                        "winning_frame_index": blocker["_frame_index"],
                        "gap_seconds": round(float(gap), 6),
                    }
                )
            continue
        if len(picked) >= top_k:
            break
        row = _legacy_row(idx, times, scored)
        row["score_rank"] = int(rank)
        picked.append(row)
        if len(picked) >= top_k:
            if rank + 1 < len(order):
                nxt = int(order[rank + 1])
                nt = float(times[nxt])
                blocker = None
                gap = None
                for prev in picked:
                    gap_s = abs(nt - prev["elapsed_seconds"])
                    if gap_s < min_gap_s:
                        blocker = prev
                        gap = gap_s
                        break
                cutoff = {
                    "action": "exclude",
                    "reason": "top_k",
                    "cutoff_score_rank": int(rank),
                    "keeps": top_k,
                    "next_frame_index": nxt,
                    "next_chunk_seconds_exact": nt,
                    "next_score": round(float(score[nxt]), 3),
                    "next_score_exact": float(score[nxt]),
                    "would_suppress_min_gap": blocker is not None,
                    "winning_frame_index": None if blocker is None else blocker["_frame_index"],
                    "gap_seconds": None if gap is None else round(float(gap), 6),
                }
            else:
                cutoff = {
                    "action": "exclude",
                    "reason": "top_k",
                    "cutoff_score_rank": int(rank),
                    "keeps": top_k,
                    "next_frame_index": None,
                }
            break

    picked_sorted = sorted(picked, key=lambda d: d["elapsed_seconds"])
    return picked_sorted, suppressed, cutoff


def legacy_public_row(row: dict, session: str, file: str, chunk_offset: float) -> dict:
    local = row["elapsed_seconds"]
    return {
        "elapsed_seconds": round(chunk_offset + local, 3),
        "score": row["score"],
        "rms_dbfs": row["rms_dbfs"],
        "loudness_jump_db": row["loudness_jump_db"],
        "flux_z": row["flux_z"],
        "near_silence": row["near_silence"],
        "session": session,
        "file": file,
        "chunk_elapsed_seconds": local,
    }


def iter_session_wavs(session_dir: Path):
    return sorted(session_dir.glob("audio_*.wav"))


def legacy_candidate_rows(session_dir: Path, top_k: int = DEFAULT_TOP_K, max_chunks: int = 0) -> list[dict]:
    """Reproduce find_candidates.main kept rows, including silent-chunk skip."""
    params = dict(PARAMS)
    params["top_k"] = int(top_k)
    session_name = session_dir.name
    rows = []
    chunk_offset = 0.0
    wavs = iter_session_wavs(session_dir)
    if max_chunks:
        wavs = wavs[:max_chunks]
    for wav in wavs:
        _rate, _ch, _n, x = load_pcm16(wav)
        dur = len(x) / _rate
        if np.max(np.abs(x)) < float(params["silent_chunk_max_abs"]):
            chunk_offset += dur
            continue
        times, rms, flux = frame_features(x, _rate)
        scored = score_frames(rms, flux, params)
        picked, _sup, _cut = select_legacy(times, scored, params)
        for c in picked:
            rows.append(legacy_public_row(c, session_name, wav.name, chunk_offset))
        chunk_offset += dur
    return rows


def hop_samples(rate: int, params: dict | None = None) -> int:
    p = params or PARAMS
    return int(float(p["hop_s"]) * rate)


def analyze_break(rate: int, x: np.ndarray, in_local_s: float, abs_start: float, params: dict | None = None):
    """Frozen break_structure.analyze_break. Same fades, outs, and suggested OUT."""
    p = params or BREAK_PARAMS
    times, rms, flux = frame_features(x, rate)
    rms_db = 20 * np.log10(rms + 1e-12)
    hop = hop_samples(rate)

    fades = []
    fade_suppressed = []
    for i in range(2, len(rms_db) - 2):
        t = float(times[i])
        if t < in_local_s + float(p["fade_skip_after_in_s"]):
            continue
        if not (
            rms_db[i] < float(p["fade_db"])
            and rms_db[i] < rms_db[i - 1] - float(p["fade_drop_prev_db"])
            and rms_db[i] < rms_db[i + 1] - float(p["fade_drop_next_db"])
        ):
            continue
        abs_t = abs_start + t
        row = {
            "elapsed_seconds": round(abs_t, 3),
            "local_seconds": round(t, 3),
            "rms_dbfs": round(float(rms_db[i]), 2),
            "kind": "fade_or_pad",
            "frame_index": int(i),
            "sample_index": int(i * hop),
            "session_sample_index": int(round(abs_start * rate)) + int(i * hop),
        }
        if not fades or abs_t - fades[-1]["elapsed_seconds"] > float(p["fade_min_gap_s"]):
            fades.append(row)
        else:
            fade_suppressed.append(
                {
                    **row,
                    "reason": "min_gap",
                    "winning_elapsed_seconds": fades[-1]["elapsed_seconds"],
                    "gap_seconds": round(abs_t - fades[-1]["elapsed_seconds"], 6),
                }
            )

    outs = []
    for i in range(2, len(rms_db) - 8):
        t = float(times[i])
        if t < in_local_s + float(p["out_min_after_in_s"]) or t > in_local_s + float(p["out_max_after_in_s"]):
            continue
        if rms_db[i] > float(p["out_db"]):
            continue
        recovery = float(np.max(rms_db[i + 1 : i + 8]) - rms_db[i])
        flux_z = (flux[i] - flux.mean()) / (flux.std() + 1e-9)
        score = recovery + float(p["out_flux_weight"]) * max(0.0, float(flux_z))
        outs.append(
            {
                "elapsed_seconds": round(abs_start + t, 3),
                "local_seconds": round(t, 3),
                "rms_dbfs": round(float(rms_db[i]), 2),
                "recovery_db": round(recovery, 2),
                "score": round(float(score), 3),
                "kind": "content_return_candidate",
                "frame_index": int(i),
                "sample_index": int(i * hop),
                "session_sample_index": int(round((abs_start + t) * rate)),
                "flux_z": float(flux_z),
                "recovery_db_exact": recovery,
                "score_exact": float(score),
            }
        )

    outs_sorted = sorted(outs, key=lambda d: d["score"], reverse=True)
    best_out = outs_sorted[0] if outs_sorted else None
    published = {
        "fades": [
            {k: f[k] for k in ("elapsed_seconds", "local_seconds", "rms_dbfs", "kind")}
            for f in fades[: int(p["fade_keep_limit"])]
        ],
        "out_candidates": [
            {
                k: o[k]
                for k in (
                    "elapsed_seconds",
                    "local_seconds",
                    "rms_dbfs",
                    "recovery_db",
                    "score",
                    "kind",
                )
            }
            for o in outs_sorted[: int(p["out_keep_reported"])]
        ],
        "suggested_out": (
            None
            if not best_out
            else {
                k: best_out[k]
                for k in (
                    "elapsed_seconds",
                    "local_seconds",
                    "rms_dbfs",
                    "recovery_db",
                    "score",
                    "kind",
                )
            }
        ),
        "break_duration_if_suggested": (
            None
            if not best_out
            else round(best_out["elapsed_seconds"] - (abs_start + in_local_s), 2)
        ),
    }
    return {
        "published": published,
        "fades": fades,
        "fade_suppressed": fade_suppressed,
        "outs": outs_sorted,
        "best_out": best_out,
        "window_norm": {
            "flux_mean": float(flux.mean()),
            "flux_std": float(flux.std()),
            "scope": "break_window",
        },
    }


def load_session_mono(session: Path, start_s: float, dur_s: float):
    meta = json.loads((session / "session.json").read_text(encoding="utf-8"))
    chunks = meta.get("chunks") or []
    running = 0.0
    for c in chunks:
        if "start_elapsed_seconds" not in c:
            c["start_elapsed_seconds"] = running
        running = c["start_elapsed_seconds"] + float(c["seconds"])

    end_s = start_s + dur_s
    pieces = []
    rate = 48000
    for c in chunks:
        c0 = float(c["start_elapsed_seconds"])
        c1 = c0 + float(c["seconds"])
        a = max(start_s, c0)
        b = min(end_s, c1)
        if b <= a:
            continue
        rate, _ch, _n, x = load_pcm16(session / c["file"])
        pieces.append(x[int((a - c0) * rate) : int((b - c0) * rate)])
    if not pieces:
        raise RuntimeError("no audio in range")
    return rate, np.concatenate(pieces)


def break_at_session_in(session: Path, in_s: float, params: dict | None = None):
    p = params or BREAK_PARAMS
    start = max(0.0, in_s - float(p["pre_s"]))
    dur = float(p["pre_s"]) + float(p["post_s"])
    rate, x = load_session_mono(session, start, dur)
    in_local = in_s - start
    result = analyze_break(rate, x, in_local, start, p)
    result["window_start"] = start
    result["window_duration"] = dur
    result["in_elapsed_seconds"] = in_s
    result["sample_rate"] = rate
    return result
