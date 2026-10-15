"""Causal streaming fingerprint reader.

Isolated from the published 90-second audfprint cut. Count 10 and count 200
are not refit. Gold, holdouts, live playback, and UNIVERSAL_V1 artifacts
are not modified.

The horizon is frozen from when finalized hashes stop changing as more
future audio is supplied. It is not chosen from the 72 false covers.
"""

from __future__ import annotations

import csv
import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np
import scipy.signal
from numba import njit

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "experiments/broadcast_intelligence/third_party/audfprint"))
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))

import audfprint_analyze as afp
from experiments.broadcast_intelligence.batch1 import commercials, coverage, load_catalog, read_span
from experiments.broadcast_intelligence.known_ad_fingerprint import (
    HOP,
    TARGET_SR,
    allow_mask,
    best_match,
    build_index,
    frame_of,
    sha256_file,
    window_hashes,
)
from experiments.universal_v1.replay import (
    COUNT_ABLATION,
    COUNT_V1,
    REDZONE,
    actions_for,
    score_group,
)
from hush.audio import find_session, load_session

RECORDINGS = REPO / "recordings"
OUT = REPO / "docs/ohush/research/FINGERPRINT_CAUSAL_STREAM_001"
DECISIONS = REPO / "docs/ohush/research/UNIVERSAL_V1/decisions.jsonl"
V1_RESULTS = REPO / "docs/ohush/research/UNIVERSAL_V1/results.json"
WARM_RESULTS = REPO / "docs/ohush/research/FINGERPRINT_WARM_CONTEXT_002/results.json"
GOLD = REPO / "docs/ohush/microgap_handoff/gold"
GATE_SESSION = "hush_20261011_135700"
N_FFT = 512
N_BINS = 256
UP = 147
DOWN = 640
GUARD_IN = 800
MINDT = 2
TARGETDT = 63
TARGETDF = 31
MAX_PAIRS = 3
MAX_PEAKS = 5
F_SD = 30.0
HPF_POLE = 0.98
DECISIONS_SHA = "08b1b8d9a56c33681b493dff1d3337951ac9a51b812c83d2e6009afdefb86713"
CONTROL_A = ("hush_20261008_205100", 145.0, 272, "hush_20260924_220624", 234.244)
CONTROL_B = ("hush_20261012_204200", 5085.0, 208, "hush_20260914_212529", 6852.564)
HORIZON_CANDIDATES = (43, 86, 129, 172, 258, 344)

# Frozen before the causal ledger is scored. Applies only to a later recording.
PROSPECTIVE_BAR = {
    "commercial_seconds_covered_at_least_fraction_of_count_10": 0.95,
    "program_seconds_covered_below_count_10": True,
    "longest_interruption_not_above_count_10": True,
    "redzone_program_seconds_not_above_count_10": True,
    "inconclusive_if_the_recording_has_no_false_program_cover_under_count_10": True,
}


def sha256_bytes(path: Path) -> str:
    return sha256_file(path)


def decay() -> float:
    return float((1 - 0.01 * (100.0 * np.sqrt(HOP / 352.8) / 35.0)) ** 1)


def kernel() -> np.ndarray:
    npts = N_BINS
    return np.exp(-0.5 * ((np.arange(-npts, npts + 1) / F_SD) ** 2))


A_DEC = decay()
KERNEL = kernel()
WINDOW = np.hanning(N_FFT + 2)[1:-1].astype(np.float64)
HPF_B = np.array([1.0, -1.0])
HPF_A = np.array([1.0, -(HPF_POLE ** 1)])


@njit
def _spread(thresh, pos, val, kernel, npts):
    base = npts - pos
    for i in range(npts):
        cand = val * kernel[i + base]
        if cand > thresh[i]:
            thresh[i] = cand


@njit
def _locmax(vec):
    n = vec.shape[0]
    mask = np.zeros(n, np.uint8)
    if n == 1 or vec[0] > vec[1]:
        mask[0] = 1
    for i in range(1, n - 1):
        if vec[i] >= vec[i - 1] and vec[i] > vec[i + 1]:
            mask[i] = 1
    if n >= 2 and vec[n - 1] >= vec[n - 2]:
        mask[n - 1] = 1
    return mask


@njit
def _spread_locmax(vec, kernel):
    npts = vec.shape[0]
    thresh = np.zeros(npts)
    mask = _locmax(vec)
    for pos in range(npts):
        if mask[pos] == 1:
            _spread(thresh, pos, vec[pos], kernel, npts)
    return thresh


@njit
def _sort_desc(values, positions, n):
    for a in range(n):
        best = a
        for b in range(a + 1, n):
            if values[b] > values[best] or (values[b] == values[best] and positions[b] > positions[best]):
                best = b
        if best != a:
            values[a], values[best] = values[best], values[a]
            positions[a], positions[best] = positions[best], positions[a]


@njit
def _forward_column(col, thresh, kernel, a_dec):
    npts = col.shape[0]
    mask = _locmax(col)
    positions = np.empty(npts, np.int32)
    values = np.empty(npts)
    n = 0
    for i in range(npts):
        if mask[i] == 1 and col[i] > thresh[i]:
            positions[n] = i
            values[n] = col[i]
            n += 1
    _sort_desc(values, positions, n)
    peaks = np.zeros(npts, np.uint8)
    take = MAX_PEAKS if n > MAX_PEAKS else n
    for k in range(take):
        _spread(thresh, positions[k], values[k], kernel, npts)
        peaks[positions[k]] = 1
    for i in range(npts):
        thresh[i] *= a_dec
    return peaks


@njit
def _backward_keep(sgram, peaks, start, horizon, kernel, a_dec):
    npts = sgram.shape[0]
    last = start + horizon
    thresh = _spread_locmax(sgram[:, last], kernel)
    keep = peaks[:, start].copy()
    positions = np.empty(npts, np.int32)
    values = np.empty(npts)
    for offset in range(horizon, -1, -1):
        col = start + offset
        n = 0
        for i in range(npts):
            if peaks[i, col] == 1:
                positions[n] = i
                values[n] = sgram[i, col]
                n += 1
        _sort_desc(values, positions, n)
        for k in range(n):
            pos = positions[k]
            val = values[k]
            if val >= thresh[pos]:
                _spread(thresh, pos, val, kernel, npts)
            elif offset == 0:
                keep[pos] = 0
        for i in range(npts):
            thresh[i] *= a_dec
    return keep


@njit
def _finalize_ready(sgram, peaks, horizon, kernel, a_dec):
    n_out = sgram.shape[1] - horizon
    out = np.zeros((sgram.shape[0], n_out), np.uint8)
    for c in range(n_out):
        out[:, c] = _backward_keep(sgram, peaks, c, horizon, kernel, a_dec)
    return out


def _analyzer_kernel() -> np.ndarray:
    analyzer = afp.Analyzer(density=100.0)
    analyzer.spreadpeaks([(0, 1.0)], npoints=N_BINS, width=F_SD)
    return np.asarray(analyzer._Analyzer__sp_vals)


class StreamingResampler:
    """resample_poly(147, 640) with enough history that interior samples match one shot."""

    def __init__(self) -> None:
        self.buf = np.zeros(0, np.float64)
        self.origin = 0
        self.seen = 0
        self.emitted = 0

    def push(self, mono: np.ndarray, final: bool = False) -> np.ndarray:
        if mono.size:
            self.buf = np.concatenate([self.buf, np.asarray(mono, dtype=np.float64)])
            self.seen += int(mono.size)
        if self.buf.size == 0:
            return np.zeros(0, np.float64)
        if self.origin % DOWN != 0:
            raise RuntimeError("resampler origin left the 640-sample grid")
        decoded = scipy.signal.resample_poly(self.buf, UP, DOWN)
        base = self.origin * UP // DOWN
        if final:
            end = base + decoded.size
        else:
            guard_out = int(np.ceil(GUARD_IN * UP / DOWN)) + 2
            end = base + max(0, decoded.size - guard_out)
        start = self.emitted
        if end <= start:
            return np.zeros(0, np.float64)
        piece = decoded[start - base : end - base]
        self.emitted = end
        keep_from = max(0, self.seen - GUARD_IN - DOWN)
        keep_from -= keep_from % DOWN
        if keep_from > self.origin:
            drop = keep_from - self.origin
            self.buf = self.buf[drop:]
            self.origin = keep_from
        return piece

    def finish(self) -> np.ndarray:
        return self.push(np.zeros(0, np.float64), final=True)


def _reflect_index(index: int, length: int) -> int:
    if length <= 1:
        return 0
    if index < 0:
        return _reflect_index(-index, length)
    if index >= length:
        return _reflect_index(2 * (length - 1) - index, length)
    return index


class CausalReader:
    def __init__(self, horizon: int, frame_origin: int = 0) -> None:
        if horizon < 1:
            raise ValueError("horizon must cover at least one future frame")
        self.horizon = int(horizon)
        self.frame_origin = int(frame_origin)
        self.resampler = StreamingResampler()
        self.samples = np.zeros(0, np.float64)
        self.sample0 = 0
        self.received = 0
        self.next_frame = 0
        self.running_max = 0.0
        self.zi = np.zeros(N_BINS, np.float64)
        self.thresh = None
        self.init_cols: list[np.ndarray] = []
        self.pending_s = np.zeros((N_BINS, 0), np.float64)
        self.pending_p = np.zeros((N_BINS, 0), np.uint8)
        self.pending0 = 0
        self.peaks_at: dict[int, list[int]] = {}
        self.pair_count: dict[tuple[int, int], int] = {}
        self.frames: list[int] = []
        self.hashes: list[int] = []
        self.dts: list[int] = []
        self.hash_ready: list[int] = []
        self.hash_full: list[int] = []
        self.closing = False
        self.finished = False

    @property
    def sample_count(self) -> int:
        return self.frame_origin * HOP + self.received

    def push_48k(self, stereo: np.ndarray) -> None:
        mono = 0.5 * (stereo[:, 0].astype(np.float64) + stereo[:, 1].astype(np.float64))
        settled = self.resampler.push(mono, final=False)
        self._push_11025(settled)

    def finish(self) -> None:
        if self.finished:
            return
        settled = self.resampler.finish()
        self._push_11025(settled)
        self.closing = True
        self._finish_tail()
        self.finished = True

    def _push_11025(self, samples: np.ndarray) -> None:
        if samples.size:
            self.samples = np.concatenate([self.samples, samples])
            self.received += int(samples.size)
        self._drain(final=False)

    def _column(self, frame_index: int, final: bool) -> np.ndarray | None:
        start = frame_index * HOP - N_FFT // 2
        stop = start + N_FFT
        if not final and stop > self.received:
            return None
        if final and start >= self.received:
            return None
        wave = np.empty(N_FFT, np.float64)
        length = self.received
        for offset, index in enumerate(range(start, stop)):
            if index < 0 or (final and index >= length):
                index = _reflect_index(index, length)
            if index < self.sample0 or index >= self.sample0 + self.samples.size:
                return None
            wave[offset] = self.samples[index - self.sample0]
        spec = np.fft.rfft(wave * WINDOW, n=N_FFT)
        return np.abs(spec[:N_BINS])

    def _accept_columns(self, columns: list[np.ndarray]) -> None:
        if not columns:
            return
        logged = np.empty((N_BINS, len(columns)), np.float64)
        for index, column in enumerate(columns):
            peak = float(np.max(column)) if column.size else 0.0
            if peak > self.running_max:
                self.running_max = peak
            floor = self.running_max / 1e6 if self.running_max > 0.0 else 1e-12
            logged[:, index] = np.log(np.maximum(column, floor))
        filtered = np.empty_like(logged)
        for bin_index in range(N_BINS):
            filtered[bin_index], zf = scipy.signal.lfilter(HPF_B, HPF_A, logged[bin_index], zi=np.array([self.zi[bin_index]]))
            self.zi[bin_index] = float(zf[0])
        if self.thresh is None:
            self.init_cols.extend(filtered[:, index] for index in range(filtered.shape[1]))
            if len(self.init_cols) < 10:
                return
            block = np.column_stack(self.init_cols)
            self.init_cols = []
            self.thresh = _spread_locmax(np.max(block[:, :10], axis=1), KERNEL)
            filtered = block
        peaks = np.zeros((N_BINS, filtered.shape[1]), np.uint8)
        assert self.thresh is not None
        for index in range(filtered.shape[1]):
            peaks[:, index] = _forward_column(filtered[:, index], self.thresh, KERNEL, A_DEC)
        if self.pending_s.shape[1] == 0:
            self.pending0 = self.next_frame - filtered.shape[1]
        self.pending_s = np.concatenate([self.pending_s, filtered], axis=1)
        self.pending_p = np.concatenate([self.pending_p, peaks], axis=1)
        self._finalize_pending(final=False)

    def _drain(self, final: bool) -> None:
        columns = []
        while True:
            column = self._column(self.next_frame, final=final)
            if column is None:
                break
            columns.append(column)
            self.next_frame += 1
            if len(columns) == 256:
                self._accept_columns(columns)
                columns = []
        self._accept_columns(columns)

    def _finalize_pending(self, final: bool) -> None:
        if final:
            width = self.pending_s.shape[1]
            if width == 0:
                return
            kept = np.zeros((N_BINS, width), np.uint8)
            futures = []
            for c in range(width):
                future = min(self.horizon, width - 1 - c)
                futures.append(future)
                kept[:, c] = _backward_keep(self.pending_s, self.pending_p, c, future, KERNEL, A_DEC)
            self._emit(kept, futures)
            self.pending_s = np.zeros((N_BINS, 0), np.float64)
            self.pending_p = np.zeros((N_BINS, 0), np.uint8)
            return
        ready = self.pending_s.shape[1] - self.horizon
        if ready <= 0:
            return
        kept = _finalize_ready(self.pending_s, self.pending_p, self.horizon, KERNEL, A_DEC)
        self._emit(kept, [self.horizon] * kept.shape[1])
        self.pending_s = self.pending_s[:, ready:]
        self.pending_p = self.pending_p[:, ready:]
        self.pending0 += ready
        self._drop_samples()

    def _emit(self, kept: np.ndarray, futures: list[int]) -> None:
        for offset in range(kept.shape[1]):
            frame = self.pending0 + offset
            bins = [int(bin_index) for bin_index in np.nonzero(kept[:, offset])[0]]
            self.peaks_at[frame] = bins
            future = futures[offset]
            ready_local = (frame + future) * HOP + N_FFT // 2
            if ready_local > self.received + N_FFT // 2 and not self.closing:
                raise RuntimeError(f"finalized local frame {frame} at sample {ready_local} after receiving {self.received}")
            ready_abs = (self.frame_origin + frame + future) * HOP + N_FFT // 2
            self._pairs(frame, ready_abs, future == self.horizon)
        self._forget_old_peaks()

    def _pairs(self, frame: int, ready_sample: int, full: bool) -> None:
        bins_here = self.peaks_at.get(frame, [])
        for dt in range(MINDT, TARGETDT):
            anchor = frame - dt
            for peak in self.peaks_at.get(anchor, []):
                used = self.pair_count.get((anchor, peak), 0)
                if used >= MAX_PAIRS:
                    continue
                for peak2 in bins_here:
                    if used >= MAX_PAIRS:
                        break
                    if abs(peak2 - peak) < TARGETDF:
                        packed = afp.landmarks2hashes(np.array([[self.frame_origin + anchor, peak, peak2, dt]], dtype=np.int32))
                        self.frames.append(self.frame_origin + int(anchor))
                        self.hashes.append(int(packed[0, 1]))
                        self.dts.append(int(dt))
                        self.hash_ready.append(int(ready_sample))
                        self.hash_full.append(1 if full else 0)
                        used += 1
                        self.pair_count[(anchor, peak)] = used

    def _forget_old_peaks(self) -> None:
        oldest = self.pending0 - TARGETDT - 2
        for frame in [frame for frame in self.peaks_at if frame < oldest]:
            for peak in self.peaks_at[frame]:
                self.pair_count.pop((frame, peak), None)
            del self.peaks_at[frame]

    def _drop_samples(self) -> None:
        need = self.pending0 * HOP - N_FFT
        if need > self.sample0 + 1024:
            drop = need - self.sample0
            self.samples = self.samples[drop:]
            self.sample0 = need

    def _finish_tail(self) -> None:
        self._drain(final=True)
        self._finalize_pending(final=True)

    def arrays(self) -> dict[str, np.ndarray]:
        return {
            "frames": np.asarray(self.frames, dtype=np.int32),
            "hashes": np.asarray(self.hashes, dtype=np.int32),
            "dts": np.asarray(self.dts, dtype=np.int16),
            "ready": np.asarray(self.hash_ready, dtype=np.int64),
            "full": np.asarray(self.hash_full, dtype=np.uint8),
        }


def decision_sample(t1: float, horizon: int) -> int:
    f1 = frame_of(t1)
    return (f1 - 1 + horizon) * HOP + N_FFT // 2


def decision_time(t1: float, horizon: int) -> float:
    return decision_sample(t1, horizon) / TARGET_SR + GUARD_IN / 48000.0


class ReadResult:
    def __init__(self, parts: list[dict[str, np.ndarray]], sample_count: int) -> None:
        keys = ("frames", "hashes", "dts", "ready", "full")
        if not parts:
            self.bag = {key: np.zeros(0, np.int64) for key in keys}
        else:
            self.bag = {key: np.concatenate([part[key] for part in parts]) for key in keys}
        self.sample_count = sample_count
        self.frames = self.bag["frames"]

    def arrays(self) -> dict[str, np.ndarray]:
        return self.bag


def feed(session: dict, chunk_s: float, horizon: int, limit: float | None = None) -> tuple[ReadResult, list[dict]]:
    cov0, cov1 = session["coverage"]
    if limit is not None:
        cov1 = min(cov1, cov0 + limit)
    holes = []
    parts = []
    cursor = cov0
    reader = CausalReader(horizon, frame_of(cursor))
    while cursor < cov1 - 1e-9:
        take = min(chunk_s, cov1 - cursor)
        try:
            audio = read_span(session["dir"], session["meta"], cursor, cursor + take)
        except RuntimeError:
            hole = min(5.0, cov1 - cursor)
            holes.append({"session": session["id"], "start": cursor, "end": cursor + hole})
            reader.finish()
            parts.append(reader.arrays())
            cursor += hole
            reader = CausalReader(horizon, frame_of(cursor))
            continue
        reader.push_48k(audio)
        cursor += take
    reader.finish()
    parts.append(reader.arrays())
    return ReadResult(parts, reader.sample_count), holes


def pack_key(frames: np.ndarray, hashes: np.ndarray) -> set[tuple[int, int]]:
    return set(zip(frames.tolist(), hashes.tolist()))


def test_kernel_matches_analyzer() -> None:
    got = kernel()
    published = _analyzer_kernel()
    if got.shape != published.shape or not np.allclose(got, published):
        raise SystemExit("gaussian kernel does not match Analyzer")
    rng = np.random.default_rng(1)
    sgram = rng.normal(size=(N_BINS, 40))
    analyzer = afp.Analyzer(density=100.0)
    forward = analyzer._decaying_threshold_fwd_prune(sgram, A_DEC)
    thresh = _spread_locmax(np.max(sgram[:, :10], axis=1), KERNEL)
    mine = np.zeros_like(forward)
    for column in range(sgram.shape[1]):
        mine[:, column] = _forward_column(sgram[:, column].copy(), thresh, KERNEL, A_DEC)
    if not np.array_equal(mine, forward):
        raise SystemExit("forward prune does not match Analyzer")
    backward = analyzer._decaying_threshold_bwd_prune_peaks(sgram, forward.copy(), A_DEC)
    kept = _backward_keep(sgram, forward, 0, sgram.shape[1] - 1, KERNEL, A_DEC)
    if not np.array_equal(kept, backward[:, 0]):
        raise SystemExit("backward prune does not match Analyzer at the first column")


def test_resampler_and_chunks() -> None:
    rng = np.random.default_rng(2)
    seconds = 3
    mono = rng.normal(size=48000 * seconds)
    whole = scipy.signal.resample_poly(mono, UP, DOWN)
    stream = StreamingResampler()
    parts = []
    step = 48000
    for start in range(0, mono.size, step):
        parts.append(stream.push(mono[start : start + step]))
    parts.append(stream.finish())
    streamed = np.concatenate(parts)
    if streamed.shape != whole.shape or not np.allclose(streamed, whole, atol=1e-8, rtol=0):
        raise SystemExit(f"resampler diverged: {streamed.shape} vs {whole.shape}")
    horizon = 43
    audio = rng.normal(size=TARGET_SR * 8)
    stereo_source = np.column_stack([audio, audio])

    def run(chunk: int) -> set[tuple[int, int]]:
        reader = CausalReader(horizon)
        # Feed already-at-rate audio through the 11025 path by pretending the resampler emitted it.
        for start in range(0, audio.size, chunk):
            reader._push_11025(audio[start : start + chunk])
        reader.finish()
        bag = reader.arrays()
        return pack_key(bag["frames"], bag["hashes"])

    continuous = run(1000)
    chopped = run(TARGET_SR)
    if continuous != chopped:
        raise SystemExit(f"11025 chunk hashes diverged: {len(continuous)} vs {len(chopped)}")
    del stereo_source


def test_timestamps_do_not_lead_the_audio() -> None:
    horizon = 86
    t1 = 10.0
    available = decision_time(t1, horizon)
    if available < t1:
        raise SystemExit("decision time precedes the query window")
    sample = decision_sample(t1, horizon)
    consumed = (sample * DOWN / UP + GUARD_IN) / 48000.0
    if abs(consumed - available) > 1e-12:
        raise SystemExit("available_at is not the last consumed sample")


def verify_baselines() -> dict:
    decision_hash = sha256_bytes(DECISIONS)
    if decision_hash != DECISIONS_SHA:
        raise SystemExit("published decisions.jsonl hash changed")
    v1 = json.loads(V1_RESULTS.read_text(encoding="utf-8"))
    football = v1["groups"]["ablation_count_10"]["football"]
    if football["false_cover_incidents"] != 72 or football["program_seconds_covered"] != 432.1:
        raise SystemExit("published count-10 ledger does not match 72 / 432.1")
    heard = football["commercial_seconds_heard"]
    covered = round(sum(row["ad_seconds"] for row in football["sessions"]) - heard, 1)
    if covered != 3903.2 or v1["holes_s"] != 275.0:
        raise SystemExit(f"published commercial cover {covered} or holes {v1['holes_s']} drifted")
    controls = {}
    for line in DECISIONS.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        for spec in (CONTROL_A, CONTROL_B):
            if row["session"] == spec[0] and row["query_t0"] == spec[1]:
                if row["score"] != spec[2] or row["ref_session"] != spec[3] or row["ref_start"] != spec[4]:
                    raise SystemExit(f"control drifted: {row}")
                controls[spec[0]] = row
    if len(controls) != 2:
        raise SystemExit("the two count-200 controls were not in decisions.jsonl")
    warm = json.loads(WARM_RESULTS.read_text(encoding="utf-8"))
    holes = warm["holes_s"]
    if holes.get("cold") != 275.0 or holes.get("warm") != 280.0:
        raise SystemExit(f"warm hole accounting drifted: {holes}")
    gold_hashes = {name: sha256_bytes(GOLD / name) for name in ("GOLD_DATASET_20261013.json", "GOLD_DEV_V1.json", "GOLD_REPLICATION_V1.json")}
    spans = coverage()
    gate = next(row for row in spans if row["session"] == GATE_SESSION)
    return {
        "decisions_sha256": decision_hash,
        "gold_sha256": gold_hashes,
        "holes_s_published": 275.0,
        "holes_s_warm_replay": holes,
        "count_10_football": {"commercial_covered_s": 3903.2, "program_s": 432.1, "incidents": 72},
        "count_200_football_commercial_covered_s": 25.0,
        "controls": {
            "prime_145": {"score": 272, "ref_session": CONTROL_A[3], "ref_start": CONTROL_A[4]},
            "monday_5085": {"score": 208, "ref_session": CONTROL_B[3], "ref_start": CONTROL_B[4]},
        },
        "gate_session_coverage": [gate["from_seconds"], gate["to_seconds"]],
        "warm_hole_note": "The warm replay's extra 5.0 s is a read hole, not an advertisement gained at count 200.",
    }


def load_sessions() -> tuple[dict, list[dict]]:
    catalog = load_catalog()
    spans = coverage()
    sessions = {}
    for span in spans:
        sid = span["session"]
        if sid in {"hush_20260917_205513", "hush_20260920_200635"}:
            raise SystemExit("refusing a sealed holdout")
        if sid in sessions:
            continue
        folder = find_session(RECORDINGS, sid)
        info = catalog.get(sid, {})
        sessions[sid] = {
            "id": sid,
            "dir": folder,
            "meta": load_session(folder),
            "coverage": (float(span["from_seconds"]), float(span["to_seconds"])),
            "network": info.get("network_or_service") or "unknown",
            "content": info.get("content_type") or "",
        }
    pods = []
    for index, row in enumerate(commercials(spans)):
        sid = row["session"]
        pods.append({
            "id": index,
            "session": sid,
            "network": sessions[sid]["network"],
            "content": sessions[sid]["content"],
            "start": float(row["start_seconds"]),
            "end": float(row["end_seconds"]),
        })
    return sessions, pods


def comparable(bag: dict[str, np.ndarray], horizon: int, sample_count: int) -> set[tuple[int, int]]:
    last = sample_count - horizon * HOP - N_FFT
    last_frame = last // HOP
    keep = bag["ready"] <= last
    return pack_key(bag["frames"][keep], bag["hashes"][keep])


def choose_horizon(session: dict) -> dict:
    """Smallest candidate whose interior hashes match the next longer candidate."""
    limit = 180.0
    readers = {}
    for horizon in HORIZON_CANDIDATES:
        started = time.perf_counter()
        reader, holes = feed(session, 15.0, horizon, limit=limit)
        if holes:
            raise SystemExit("horizon slice hit a read hole")
        readers[horizon] = reader
        print(f"  horizon {horizon} hashes {len(reader.frames)} in {time.perf_counter() - started:.1f}s", flush=True)
    sample_count = readers[HORIZON_CANDIDATES[-1]].sample_count
    report = []
    frozen = None
    for left, right in zip(HORIZON_CANDIDATES, HORIZON_CANDIDATES[1:]):
        a = comparable(readers[left].arrays(), right, sample_count)
        b = comparable(readers[right].arrays(), right, sample_count)
        same = a == b
        report.append({"horizon": left, "against": right, "same": same, "left": len(a), "right": len(b)})
        print(f"  {left} vs {right}: {'same' if same else 'different'} ({len(a)} / {len(b)})", flush=True)
        if same and frozen is None:
            frozen = left
    settled = frozen is not None
    if frozen is None:
        frozen = HORIZON_CANDIDATES[-1]
    return {"candidates": report, "frozen_horizon_frames": frozen, "settled": settled, "slice_s": limit}


def equivalence(session: dict, horizon: int) -> dict:
    feeds = {"continuous_7s": 7.0, "chunk_45s": 45.0, "chunk_90s": 90.0, "chunk_180s": 180.0}
    bags = {}
    hole_counts = {}
    for name, chunk in feeds.items():
        started = time.perf_counter()
        reader, holes = feed(session, chunk, horizon)
        bags[name] = reader.arrays()
        hole_counts[name] = holes
        print(f"  {name} hashes {bags[name]['frames'].size} in {time.perf_counter() - started:.1f}s", flush=True)
    base_name = "continuous_7s"
    base = bags[base_name]
    comparisons = {}
    ok = True
    for name, bag in bags.items():
        if name == base_name:
            continue
        keys_a = pack_key(base["frames"], base["hashes"])
        keys_b = pack_key(bag["frames"], bag["hashes"])
        same = keys_a == keys_b
        ready_same = np.array_equal(np.sort(base["ready"]), np.sort(bag["ready"])) if same else False
        ok = ok and same
        comparisons[name] = {
            "same_finalized_hashes": same,
            "same_ready_samples": bool(ready_same),
            "base_hashes": len(keys_a),
            "other_hashes": len(keys_b),
            "only_base": len(keys_a - keys_b),
            "only_other": len(keys_b - keys_a),
            "holes": hole_counts[name],
        }
    queries = query_against_self(base, horizon, session)
    query_agree = True
    for name, bag in bags.items():
        if name == base_name:
            continue
        other = query_against_self(bag, horizon, session)
        same_q = queries == other
        query_agree = query_agree and same_q
        comparisons[name]["same_self_match_scores"] = same_q
    return {
        "session": session["id"],
        "horizon_frames": horizon,
        "chunk_stable": ok and query_agree,
        "comparisons": comparisons,
        "continuous_holes": hole_counts[base_name],
    }


def query_against_self(bag: dict[str, np.ndarray], horizon: int, session: dict) -> list[tuple]:
    cov0, cov1 = session["coverage"]
    refs = []
    t = cov0
    ref_id = 0
    while t + 20.0 <= cov1:
        frames, hashes = window_hashes(bag["frames"], bag["hashes"], bag["dts"], t, t + 20.0)
        refs.append({"id": ref_id, "frames": frames, "hashes": hashes})
        ref_id += 1
        t += 60.0
    if not refs:
        return []
    index = build_index(refs)
    allow = np.ones(len(refs), dtype=bool)
    rows = []
    t = cov0 + 5.0
    while t + 5.0 <= cov1:
        available = decision_time(t + 5.0, horizon)
        frames, hashes = window_hashes(bag["frames"], bag["hashes"], bag["dts"], t, t + 5.0)
        hit = best_match(frames, hashes, index, allow)
        rows.append((round(t, 3), int(hit["score"]), hit["ref_id"], round(available, 6)))
        t += 30.0
    return rows


def causal_queries(sessions, pods, landmarks, refs, index, horizon: int) -> list[dict]:
    by_session: dict[str, list] = {}
    for ref in refs:
        by_session.setdefault(ref["session"], []).append(ref)
    order = sorted(sessions)
    rows = []
    for sid in order:
        cov0, cov1 = sessions[sid]["coverage"]
        earlier = [ref["id"] for name in order if name < sid for ref in by_session.get(name, [])]
        allow = allow_mask(len(refs), earlier)
        bag = landmarks[sid]
        t = cov0
        while t + 5.0 <= cov1:
            t1 = t + 5.0
            available = decision_time(t1, horizon)
            sample = decision_sample(t1, horizon)
            frames, hashes = window_hashes(bag["frames"], bag["hashes"], bag["dts"], t, t1)
            ready = bag["ready"]
            mask = (bag["frames"] >= frame_of(t)) & ((bag["frames"] + bag["dts"].astype(np.int32)) < frame_of(t1))
            if np.any(mask) and np.any(ready[mask] > sample):
                raise RuntimeError(f"{sid} query {t} uses a hash that was not ready")
            if np.any(mask) and np.any(bag["full"][mask] == 0):
                t += 5.0
                continue
            if decision_time(t1, horizon) > cov1:
                t += 5.0
                continue
            hit = best_match(frames, hashes, index, allow)
            ref = None if hit["ref_id"] is None else refs[hit["ref_id"]]
            if available + 1e-9 < t1:
                raise RuntimeError("decision stamped before the window ended")
            rows.append({
                "session": sid,
                "network": sessions[sid]["network"],
                "content": sessions[sid]["content"],
                "query_t0": round(t, 3),
                "query_t1": round(t1, 3),
                "window_end_at": round(t1, 6),
                "sample_max_consumed_at": round(available, 6),
                "finalized_at": round(available, 6),
                "decision_effective_at": round(available, 6),
                "available_at": round(available, 6),
                "score": int(hit["score"]),
                "n_hashes": int(hit["n_hashes"]),
                "offset": None if hit["offset"] is None else int(hit["offset"]),
                "ref_session": None if ref is None else ref["session"],
                "ref_start": None if ref is None else round(float(ref["start"]), 3),
                "same_session": bool(ref is not None and ref["session"] == sid),
            })
            t += 5.0
        print(f"  queried {sid}", flush=True)
    return rows


def commercial_covered(group: dict) -> float:
    heard = group["commercial_seconds_heard"]
    present = sum(row["ad_seconds"] for row in group["sessions"])
    return round(present - heard, 1)


def write_report(payload: dict) -> None:
    gate = payload["first_gate"]
    horizon = payload["horizon"]
    base = payload["baselines"]
    equiv = payload["equivalence"]
    score = payload.get("score")
    controls = payload.get("controls")
    lines = [
        "# Fingerprint causal stream 001",
        "",
        "Not a mute. The published reader, its decisions, the two counts, and the gold were not modified. Holdouts stayed sealed. Playback stays PLAY.",
        "",
        "This reader carries the resampler, the high-pass filter, and the forward peak threshold across chunks. A peak is finalized only after a frozen number of later frames have arrived, and that backward pass uses exactly that many frames. The decision time is the last recording sample required to finalize the query, including the resampler guard.",
        "",
        f"First gate: **{gate}**.",
        "",
        "## Baselines rechecked",
        "",
        f"Published `decisions.jsonl` is `{base['decisions_sha256']}`. Count 10 on football remains {base['count_10_football']['commercial_covered_s']} commercial seconds covered, {base['count_10_football']['program_s']} program seconds, 72 incidents. Published read holes are 275.0 s. The warm replay's holes are 280.0 s. That extra 5.0 s is why a warm count-200 total can look 5 seconds higher. It is not an advertisement gained.",
        "",
        f"The two published count-200 covers are still in the file: score 272 at {CONTROL_A[0]} t=145 against {CONTROL_A[3]} at {CONTROL_A[4]}, and score 208 at {CONTROL_B[0]} t=5085 against {CONTROL_B[3]} at {CONTROL_B[4]}.",
        "",
        "## Horizon",
        "",
        f"On the first 180 seconds of `{GATE_SESSION}`, candidate horizons were {list(HORIZON_CANDIDATES)} frames. "
        + (
            f"Hashes stopped changing at {horizon['frozen_horizon_frames']} frames, {horizon['frozen_horizon_frames'] * HOP / TARGET_SR:.3f} seconds of future frames, and that value was frozen before the ledger was scored."
            if horizon["settled"]
            else f"Hashes were still changing at {horizon['frozen_horizon_frames']} frames. The longest candidate was used so the chunk test could run. Those peaks are not finalized."
        ),
        "",
        "## Chunk test",
        "",
        f"`{GATE_SESSION}` was read as 7-second continuous pieces and as 45-, 90-, and 180-second chunks. State was not reset at those cuts. Chunk-stable finalized hashes: **{equiv['chunk_stable']}**.",
        "",
    ]
    for name, row in equiv["comparisons"].items():
        lines.append(
            f"- {name}: same hashes {row['same_finalized_hashes']}, only in the continuous read {row['only_base']}, only in this read {row['only_other']}."
        )
    lines += ["", "## Ledger", ""]
    if score is None:
        lines.append("The ledger was not scored.")
    else:
        foot = score["count_10"]["football"]
        v1 = score["count_200"]["football"]
        lines.append(
            f"Football at count 10, with decisions stamped when the audio was actually in hand: "
            f"{commercial_covered(foot)} commercial seconds covered, {foot['program_seconds_covered']} program seconds, "
            f"{foot['false_cover_incidents']} incidents, longest interruption {foot['worst_continuous_program_interruption_s']} seconds, "
            f"premature let-go {foot['ad_seconds_heard_after_a_cover_let_go']} commercial seconds across {foot['premature_return_incidents']} incidents. "
            f"Unscorable holes in this read: {foot['unscorable_s']} seconds."
        )
        lines.append("")
        lines.append(
            f"Football at the unchanged count 200: {commercial_covered(v1)} commercial seconds covered, "
            f"{v1['program_seconds_covered']} program seconds, {v1['false_cover_incidents']} incidents. "
            f"RedZone program seconds at count 10: {score['count_10']['redzone']['program_seconds_covered']}."
        )
        lines.append("")
        lines.append(
            "These figures describe this reader. They are not a correction to subtract from the published 432.1. "
            "October recordings were already inspected."
        )
    lines += ["", "## Controls", ""]
    if controls:
        for row in controls:
            lines.append(
                f"- {row['session']} t={row['query_t0']}: causal score {row['causal_score']} against {row['causal_ref_session']} at {row['causal_ref_start']}. "
                f"Published score {row['published_score']} against {row['published_ref_session']} at {row['published_ref_start']}. "
                f"Same pod: {row['same_pod']}. Decision at {row['decision_effective_at']}, window end {row['window_end_at']}."
            )
    lines += [
        "",
        "## Prospective recording",
        "",
        "No new recording was made. The acceptance bar below was written into the script before this ledger was scored. It applies only to audio recorded after this file, labeled without seeing these decisions. The two sealed holdouts are not that recording. October is not that recording. The afternoon tape used to find the block cut is not that recording.",
        "",
        "On that recording, count 10 with this reader passes only if commercial seconds covered are at least 95 percent of the published count-10 reader on the same labels, program seconds and the longest interruption are both lower than that reader, and RedZone program seconds are not higher. If count 10 on that tape covers no program, the result is INCONCLUSIVE.",
        "",
        "The first gate already decides this experiment. A later recording is not opened while chunk results disagree or a timestamp uses samples that have not arrived.",
        "",
        "## Command",
        "",
        "```",
        ".venv/bin/python experiments/measurement/fingerprint_causal_stream_001.py",
        "```",
        "",
        "PLAY. Universal v1 unchanged. Holdouts sealed. No deployment.",
        "",
    ]
    (OUT / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def write_next(payload: dict) -> None:
    gate = payload["first_gate"]
    if gate == "PASS":
        text = (
            "# Next decision\n\n"
            "The streaming fingerprint is chunk-stable and its timestamps wait for the samples they use. "
            "The next Universal measurement is the remaining 25.1-second program interruption, examined on its own. "
            "Do not open a new voice model or a broader feature combination for that incident. "
            "CUE-OPTICAL-001 stays a separate Enhanced capture and does not block this.\n\n"
            "A prospective recording is still required before any of this is treated as a user-facing gain. "
            "The bar is in the causal-stream report. Playback stays PLAY.\n"
        )
    else:
        text = (
            "# Next decision\n\n"
            f"FINGERPRINT_CAUSAL_STREAM_001 fails as a causal candidate: {payload['fail_reason']} "
            "A retrospective score, if one is attached, does not reopen it.\n\n"
            "Do not promote the two-second historical lead. Its honest two-second delay recovered 31.5 program seconds and gave up 54.4 commercial seconds, and a five-second delay made program coverage worse. "
            "Do not count the warm replay's extra 5.0 seconds at count 200 as an advertisement; that replay has 280.0 seconds of read holes against the published 275.0.\n\n"
            "The 25.1-second interruption stays where it was. It is not the next experiment until a reader is actually chunk-stable and causal. "
            "CUE-OPTICAL-001 remains parallel. Playback stays PLAY. Universal v1 unchanged. Holdouts sealed.\n"
        )
    (OUT / "NEXT_DECISION.md").write_text(text, encoding="utf-8")


def main() -> None:
    sys.stdout.reconfigure(line_buffering=True)
    started = time.perf_counter()
    print("unit checks", flush=True)
    test_kernel_matches_analyzer()
    test_resampler_and_chunks()
    test_timestamps_do_not_lead_the_audio()
    print("baselines", flush=True)
    baselines = verify_baselines()
    sessions, pods = load_sessions()
    gate_session = sessions[GATE_SESSION]
    print("horizon", flush=True)
    horizon_report = choose_horizon(gate_session)
    horizon = int(horizon_report["frozen_horizon_frames"])
    print("chunk gate", flush=True)
    equiv = equivalence(gate_session, horizon)
    timestamps_ok = True
    fail_reasons = []
    if not horizon_report["settled"]:
        fail_reasons.append("finalized hashes still changed when more future audio was added.")
        timestamps_ok = False
    if not equiv["chunk_stable"]:
        fail_reasons.append("finalized hashes changed with the chunk size.")
    first = "PASS" if not fail_reasons else "FAIL"
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "stream_equivalence.json").write_text(json.dumps({"horizon": horizon_report, "equivalence": equiv, "baselines": baselines}, indent=2) + "\n", encoding="utf-8")
    print("ledger", flush=True)
    landmarks = {}
    holes = []
    for sid, session in sessions.items():
        t0 = time.perf_counter()
        reader, session_holes = feed(session, 30.0, horizon)
        landmarks[sid] = reader.arrays()
        holes.extend(session_holes)
        print(f"  {sid} hashes {landmarks[sid]['frames'].size} holes {len(session_holes)} in {time.perf_counter() - t0:.1f}s", flush=True)
    refs = []
    for pod in pods:
        bag = landmarks[pod["session"]]
        frames, hashes = window_hashes(bag["frames"], bag["hashes"], bag["dts"], pod["start"], pod["end"])
        refs.append({**pod, "frames": frames, "hashes": hashes})
    index = build_index(refs)
    rows = causal_queries(sessions, pods, landmarks, refs, index, horizon)
    with (OUT / "causal_availability.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")
    by_session: dict[str, list] = {}
    for row in rows:
        by_session.setdefault(row["session"], []).append(row)
    action_10 = {sid: actions_for(sessions[sid], by_session.get(sid, []), COUNT_ABLATION) for sid in sessions}
    action_200 = {sid: actions_for(sessions[sid], by_session.get(sid, []), COUNT_V1) for sid in sessions}
    score = {
        "count_10": {name: score_group(name, sessions, pods, holes, action_10, COUNT_ABLATION) for name in ("football", "redzone", "scripted")},
        "count_200": {name: score_group(name, sessions, pods, holes, action_200, COUNT_V1) for name in ("football", "redzone", "scripted")},
    }
    controls = []
    for spec in (CONTROL_A, CONTROL_B):
        match = next(row for row in rows if row["session"] == spec[0] and row["query_t0"] == spec[1])
        controls.append({
            "session": spec[0],
            "query_t0": spec[1],
            "published_score": spec[2],
            "published_ref_session": spec[3],
            "published_ref_start": spec[4],
            "causal_score": match["score"],
            "causal_ref_session": match["ref_session"],
            "causal_ref_start": match["ref_start"],
            "offset": match["offset"],
            "same_pod": match["ref_session"] == spec[3] and match["ref_start"] == spec[4],
            "window_end_at": match["window_end_at"],
            "sample_max_consumed_at": match["sample_max_consumed_at"],
            "finalized_at": match["finalized_at"],
            "decision_effective_at": match["decision_effective_at"],
            "score_at_least_200": match["score"] >= 200,
        })
    with (OUT / "control_matches.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(controls[0].keys()))
        writer.writeheader()
        writer.writerows(controls)
    with (OUT / "session_ledger.csv").open("w", encoding="utf-8", newline="") as handle:
        fields = ["count", "population", "session", "network", "commercial_seconds_covered", "program_seconds_covered", "false_cover_incidents", "worst_program_interruption_s", "unscorable_s", "ad_seconds_heard"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for count_name, groups in score.items():
            for population, group in groups.items():
                for row in group["sessions"]:
                    writer.writerow({
                        "count": count_name,
                        "population": population,
                        "session": row["session"],
                        "network": row["network"],
                        "commercial_seconds_covered": round(row["ad_seconds"] - row["ad_seconds_heard"], 1),
                        "program_seconds_covered": row["program_seconds_covered"],
                        "false_cover_incidents": row["false_cover_incidents"],
                        "worst_program_interruption_s": row["worst_program_interruption_s"],
                        "unscorable_s": row["unscorable_s"],
                        "ad_seconds_heard": row["ad_seconds_heard"],
                    })
    payload = {
        "first_gate": first,
        "fail_reason": " ".join(fail_reasons),
        "timestamps_use_only_received_audio": timestamps_ok and all(row["decision_effective_at"] + 1e-9 >= row["window_end_at"] for row in rows),
        "horizon": horizon_report,
        "equivalence": equiv,
        "baselines": baselines,
        "score": {
            "count_10": {name: {key: score["count_10"][name][key] for key in ("commercial_seconds_heard", "program_seconds_covered", "false_cover_incidents", "worst_continuous_program_interruption_s", "premature_return_incidents", "ad_seconds_heard_after_a_cover_let_go", "unscorable_s", "sessions")} for name in score["count_10"]},
            "count_200": {name: {key: score["count_200"][name][key] for key in ("commercial_seconds_heard", "program_seconds_covered", "false_cover_incidents", "worst_continuous_program_interruption_s", "unscorable_s", "sessions")} for name in score["count_200"]},
        },
        "controls": controls,
        "prospective": {"status": "not_run", "bar": PROSPECTIVE_BAR, "reason": "No recording exists that was captured after this reader was frozen."},
        "elapsed_s": round(time.perf_counter() - started, 1),
    }
    # score_group groups are not JSON-safe above if I stripped too little; rebuild a compact copy for results.json
    def compact(group: dict) -> dict:
        return {
            "commercial_seconds_covered": commercial_covered(group),
            "commercial_seconds_heard": group["commercial_seconds_heard"],
            "program_seconds_covered": group["program_seconds_covered"],
            "false_cover_incidents": group["false_cover_incidents"],
            "worst_continuous_program_interruption_s": group["worst_continuous_program_interruption_s"],
            "premature_return_incidents": group["premature_return_incidents"],
            "ad_seconds_heard_after_a_cover_let_go": group["ad_seconds_heard_after_a_cover_let_go"],
            "unscorable_s": group["unscorable_s"],
            "sessions": group["sessions"],
        }
    payload["score"] = {
        "count_10": {name: compact(score["count_10"][name]) for name in score["count_10"]},
        "count_200": {name: compact(score["count_200"][name]) for name in score["count_200"]},
    }
    (OUT / "results.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    write_report(payload)
    write_next(payload)
    print(f"gate {first} in {payload['elapsed_s']}s", flush=True)


if __name__ == "__main__":
    main()
