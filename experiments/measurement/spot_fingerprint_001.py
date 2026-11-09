"""Spot-level fingerprints, earlier games only.

Labeled breaks are split at the published 12 dB hole. Each piece between
those holes is enrolled. A later game is queried with the same 5-second
chronological window Universal v1 used. The library is pieces from earlier
football games. Count 200 is not moved. RedZone is queried and never
enrolled. A program second above the count is the result.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
from scipy.signal import resample_poly

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "experiments/broadcast_intelligence/third_party/audfprint"))

import audfprint_analyze as afp  # noqa: E402

from tools.gpu_lab.audio_load import load_coverage  # noqa: E402
from tools.gpu_lab.ladder import pairs  # noqa: E402
from tools.gpu_lab.learning_net.data import bridge_masks  # noqa: E402
from tools.gpu_lab.splits import HOLDOUTS  # noqa: E402

OUT = REPO / "docs" / "ohush" / "research" / "SPOT_FINGERPRINT_001"
SR = 16000
TARGET_SR = 11025
HOP = 256
MATCH_WIN = 2
DENSITY = 100.0
COUNT = 200
QUERY_S = 5.0
GAP_DB = 12.0
MIN_PIECE_S = 2.0
REDZONE = "hush_20260913_150934"
ORDER = (
    ("hush_20260909_213047", "Sept 9 NBC", True),
    ("hush_20260913_150934", "Sept 13 RedZone", False),
    ("hush_20260913_210542", "Sept 13 NBC", True),
    ("hush_20260914_212529", "Sept 14 ESPN", True),
    ("hush_20260924_220624", "Sept 24 Prime", True),
    ("hush_20261008_205100", "Oct 8 Prime Video", True),
    ("hush_20261010_222400", "Oct 10 cable", True),
    ("hush_20261011_135700", "Oct 11 afternoon", True),
    ("hush_20261011_204300", "Oct 11 night", True),
    ("hush_20261012_204200", "Oct 12 MNF", True),
)


def dip(audio: np.ndarray, origin: float, center: float) -> float | None:
    a = int(round((center - 1.0 - origin) * SR))
    b = int(round((center + 1.0 - origin) * SR))
    if a < 0 or b > len(audio) or b - a < SR:
        return None
    window = audio[a:b]
    hop = int(0.1 * SR)
    frames = window[: len(window) - (len(window) % hop)].reshape(-1, hop)
    rms = np.sqrt(np.mean(frames * frames, axis=1) + 1e-12)
    db = 20.0 * np.log10(rms)
    return float(np.median(db) - np.min(db))


def cuts_in(audio: np.ndarray, origin: float, start: float, end: float) -> list[float]:
    found = []
    center = start + 2.0
    while center <= end - 2.0 + 1e-9:
        gap = dip(audio, origin, center)
        if gap is not None and gap >= GAP_DB:
            found.append((center, gap))
        center += 1.0
    if not found:
        return []
    runs = [[found[0]]]
    for row in found[1:]:
        if row[0] - runs[-1][-1][0] <= 2.0:
            runs[-1].append(row)
        else:
            runs.append([row])
    return [max(run, key=lambda item: item[1])[0] for run in runs]


def pieces_of(audio: np.ndarray, origin: float, commercials: list[tuple[float, float]]) -> list[dict]:
    rows = []
    n_cuts = 0
    for start, end in commercials:
        bounds = [start, *cuts_in(audio, origin, start, end), end]
        n_cuts += max(0, len(bounds) - 2)
        for left, right in zip(bounds, bounds[1:]):
            if right - left < MIN_PIECE_S:
                continue
            rows.append({"t0": round(left, 3), "t1": round(right, 3), "seconds": round(right - left, 3)})
    return rows, n_cuts


def fingerprint(samples: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    analyzer = afp.Analyzer(density=DENSITY)
    if len(samples) < analyzer.n_fft:
        return np.zeros(0, np.int32), np.zeros(0, np.int32)
    peaks = analyzer.find_peaks(samples, TARGET_SR)
    landmarks = analyzer.peaks2landmarks(peaks)
    if len(landmarks) == 0:
        return np.zeros(0, np.int32), np.zeros(0, np.int32)
    packed = np.asarray(landmarks, dtype=np.int32)
    hashes = afp.landmarks2hashes(packed)
    return hashes[:, 0].astype(np.int32), hashes[:, 1].astype(np.int32)


def frame_of(seconds: float) -> int:
    return int(round(seconds * TARGET_SR / HOP))


def slice_hashes(frames: np.ndarray, hashes: np.ndarray, t0: float, t1: float) -> tuple[np.ndarray, np.ndarray]:
    keep = (frames >= frame_of(t0)) & (frames < frame_of(t1))
    return frames[keep], hashes[keep]


def build_index(refs: list[dict]) -> dict[int, np.ndarray]:
    grouped: dict[int, list[tuple[int, int]]] = {}
    for ref in refs:
        for frame, hash_ in zip(ref["frames"].tolist(), ref["hashes"].tolist()):
            grouped.setdefault(int(hash_), []).append((int(ref["id"]), int(frame)))
    return {key: np.asarray(value, dtype=np.int32) for key, value in grouped.items()}


def best_match(frames: np.ndarray, hashes: np.ndarray, index: dict[int, np.ndarray], n_refs: int) -> dict:
    allow = np.ones(n_refs, dtype=bool)
    hit_rids = []
    hit_offs = []
    for frame, hash_ in zip(frames.tolist(), hashes.tolist()):
        bucket = index.get(int(hash_))
        if bucket is None:
            continue
        chosen = bucket[allow[bucket[:, 0]]]
        if chosen.size == 0:
            continue
        hit_rids.append(chosen[:, 0])
        hit_offs.append(chosen[:, 1] - int(frame))
    best = {"score": 0, "ref_id": None, "n_hashes": int(frames.size)}
    if not hit_rids:
        return best
    rids = np.concatenate(hit_rids)
    offs = np.concatenate(hit_offs)
    order = np.argsort(rids, kind="mergesort")
    rids = rids[order]
    offs = offs[order]
    kernel = np.ones(2 * MATCH_WIN + 1, dtype=np.int32)
    start = 0
    while start < rids.size:
        stop = start + 1
        while stop < rids.size and rids[stop] == rids[start]:
            stop += 1
        if stop - start >= 5:
            local = offs[start:stop]
            shifted = local - int(local.min())
            counts = np.bincount(shifted)
            score = int(counts[0]) if counts.size == 1 else int(np.convolve(counts, kernel, mode="same").max())
            if score > best["score"]:
                best = {"score": score, "ref_id": int(rids[start]), "n_hashes": int(frames.size)}
        start = stop
    return best


def overlap(spans: list[tuple[float, float]], regions: list[tuple[float, float]]) -> float:
    total = 0.0
    for left, right in spans:
        for start, end in regions:
            total += max(0.0, min(right, end) - max(left, start))
    return total


def interruptions(covers: list[tuple[float, float]], program: list[tuple[float, float]]) -> list[dict]:
    rows = []
    for left, right in covers:
        seconds = overlap([(left, right)], program)
        if seconds > 1e-9:
            rows.append({"t0": round(left, 3), "t1": round(right, 3), "program_s": round(seconds, 3)})
    return rows


def hashes_of(audio11: np.ndarray, origin: float) -> tuple[np.ndarray, np.ndarray]:
    frames, hashes = fingerprint(audio11)
    return frames + frame_of(origin), hashes


def main() -> None:
    masks = bridge_masks()
    library: list[dict] = []
    prepared: dict[str, dict] = {}
    for session, name, enroll in ORDER:
        if session in HOLDOUTS:
            raise SystemExit(f"refusing sealed holdout {session}")
        started = time.perf_counter()
        coverage = pairs(masks[session], "coverage")[0]
        commercials = pairs(masks[session], "verified_commercial")
        program = pairs(masks[session], "verified_program")
        audio = load_coverage(session, coverage[0], coverage[1])
        piece_rows, n_cuts = pieces_of(audio, coverage[0], commercials)
        audio11 = resample_poly(audio, 441, 640).astype(np.float32)
        del audio
        frames, hashes = hashes_of(audio11, coverage[0])
        del audio11
        own = []
        if enroll:
            for piece in piece_rows:
                part_frames, part_hashes = slice_hashes(frames, hashes, piece["t0"], piece["t1"])
                own.append({**piece, "session": session, "frames": part_frames, "hashes": part_hashes})
        prepared[session] = {
            "name": name,
            "enroll": enroll,
            "coverage": coverage,
            "commercials": commercials,
            "program": program,
            "frames": frames,
            "hashes": hashes,
            "pieces": len(own),
            "cuts": n_cuts,
            "piece_seconds": round(sum(row["seconds"] for row in own), 3),
        }
        print(
            f"prepared {name} pieces {len(own)} cuts {n_cuts} in {time.perf_counter() - started:.0f}s",
            flush=True,
        )
        if own:
            library.extend(own)

    for index, ref in enumerate(library):
        ref["id"] = index
    self_score = None
    long = next((ref for ref in library if ref["seconds"] >= QUERY_S), None)
    if long is not None:
        query_frames, query_hashes = slice_hashes(long["frames"], long["hashes"], long["t0"], long["t0"] + QUERY_S)
        # The slice frames are absolute. Match them against the piece with the
        # same clock by rebuilding that one reference at id 0.
        solo = {"id": 0, "frames": long["frames"], "hashes": long["hashes"]}
        self_score = best_match(query_frames, query_hashes, build_index([solo]), 1)["score"]
        print(f"self match of first long piece {self_score}", flush=True)

    rows = []
    for session, name, _enroll in ORDER:
        bag = prepared[session]
        earlier = [ref for ref in library if ref["session"] < session]
        index = build_index(earlier) if earlier else {}
        covers = []
        hit_rows = []
        commercial_max = 0
        program_max = 0
        program_max_t = None
        hits = 0
        t = bag["coverage"][0] + QUERY_S
        end = bag["coverage"][1]
        while t + QUERY_S <= end + 1e-9:
            query_frames, query_hashes = slice_hashes(bag["frames"], bag["hashes"], t, t + QUERY_S)
            found = best_match(query_frames, query_hashes, index, len(earlier)) if earlier else {"score": 0, "ref_id": None}
            score = int(found["score"])
            query_program = overlap([(t, t + QUERY_S)], bag["program"])
            query_ad = overlap([(t, t + QUERY_S)], bag["commercials"])
            if query_program > query_ad and score >= program_max:
                program_max = score
                program_max_t = round(t, 3)
            elif query_ad > 0:
                commercial_max = max(commercial_max, score)
            if score >= COUNT and found["ref_id"] is not None:
                hits += 1
                cover = (t + QUERY_S, min(end, t + 2 * QUERY_S))
                covers.append(cover)
                ref = next(row for row in earlier if row["id"] == found["ref_id"])
                hit_rows.append(
                    {
                        "query_t0": round(t, 3),
                        "cover_t0": round(cover[0], 3),
                        "cover_t1": round(cover[1], 3),
                        "score": score,
                        "ref_session": ref["session"],
                        "ref_t0": ref["t0"],
                        "ref_t1": ref["t1"],
                    }
                )
            t += QUERY_S
        program_hits = interruptions(covers, bag["program"])
        commercial_s = round(overlap(covers, bag["commercials"]), 3)
        program_s = round(sum(row["program_s"] for row in program_hits), 3)
        worst = max(program_hits, key=lambda row: row["program_s"]) if program_hits else None
        row = {
            "session": session,
            "name": name,
            "role": "control" if session == REDZONE else "football",
            "library_pieces": len(earlier),
            "pieces_enrolled_from_this_game": bag["pieces"],
            "interior_cuts": bag["cuts"],
            "piece_seconds": bag["piece_seconds"],
            "commercial_seconds_marked": commercial_s,
            "program_seconds_marked": program_s,
            "program_interruptions": len(program_hits),
            "queries_at_200": hits,
            "max_score_on_commercial_query": commercial_max,
            "max_score_on_program_query": program_max,
            "max_program_query_t0": program_max_t,
            "hits": hit_rows,
            "worst_program_interruption": None
            if worst is None
            else {**worst, "note": "Times are on the session clock. The clip is not copied."},
        }
        rows.append(row)
        print(
            f"{name} library {len(earlier)} commercial {commercial_s} program {program_s} "
            f"max ad {commercial_max} max show {program_max}",
            flush=True,
        )
        del bag["frames"]
        del bag["hashes"]

    payload = {
        "id": "SPOT_FINGERPRINT_001",
        "count": COUNT,
        "count_lowered": False,
        "query_s": QUERY_S,
        "gap_db": GAP_DB,
        "min_piece_s": MIN_PIECE_S,
        "cover_rule": "a 5-second query at or above 200 covers the next 5 seconds, the Universal v1 clock",
        "library_rule": "spot pieces from earlier football games only; RedZone is never enrolled",
        "self_match_score": self_score,
        "holdouts_opened": False,
        "live_mute_changed": False,
        "sessions": rows,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT / 'results.json'}", flush=True)


if __name__ == "__main__":
    main()
