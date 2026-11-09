"""Landmark fingerprints of the two seconds at a commercial boundary.

The spectrum test on these windows already failed. This is the landmark
pass that test left open. Settings are the published audfprint line:
11,025 Hz, density 100, match window 2 frames, accept count 200.
A later game is not in the library. The count is not lowered after the
scores are read. RedZone is a control and is not enrolled. Nothing mutes.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from scipy.signal import resample_poly

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "experiments/broadcast_intelligence/third_party/audfprint"))

import audfprint_analyze as afp  # noqa: E402

PUBLISHED_COUNT = 200
DENSITY = 100.0
MATCH_WIN = 2


def fingerprint(samples: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    analyzer = afp.Analyzer(density=DENSITY)
    if len(samples) < analyzer.n_fft:
        return np.zeros(0, np.int32), np.zeros(0, np.int32)
    peaks = analyzer.find_peaks(samples, 11025)
    landmarks = analyzer.peaks2landmarks(peaks)
    if len(landmarks) == 0:
        return np.zeros(0, np.int32), np.zeros(0, np.int32)
    packed = np.asarray(landmarks, dtype=np.int32)
    hashes = afp.landmarks2hashes(packed)
    return hashes[:, 0].astype(np.int32), hashes[:, 1].astype(np.int32)


def build_index(refs: list[dict]) -> dict[int, np.ndarray]:
    grouped: dict[int, list[tuple[int, int]]] = {}
    for ref in refs:
        for frame, hash_ in zip(ref["frames"].tolist(), ref["hashes"].tolist()):
            grouped.setdefault(int(hash_), []).append((int(ref["id"]), int(frame)))
    return {key: np.asarray(value, dtype=np.int32) for key, value in grouped.items()}


def best_match(frames: np.ndarray, hashes: np.ndarray, index: dict[int, np.ndarray], allow: np.ndarray) -> dict:
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
    empty = {"score": 0, "n_hashes": int(frames.size)}
    if not hit_rids:
        return empty
    rids = np.concatenate(hit_rids)
    offs = np.concatenate(hit_offs)
    order = np.argsort(rids, kind="mergesort")
    rids = rids[order]
    offs = offs[order]
    best_score = 0
    start = 0
    kernel = np.ones(2 * MATCH_WIN + 1, dtype=np.int32)
    while start < rids.size:
        stop = start + 1
        while stop < rids.size and rids[stop] == rids[start]:
            stop += 1
        if stop - start >= 5:
            local = offs[start:stop]
            shifted = local - int(local.min())
            counts = np.bincount(shifted)
            if counts.size == 1:
                score = int(counts[0])
            else:
                smoothed = np.convolve(counts, kernel, mode="same")
                score = int(smoothed[int(np.argmax(smoothed))])
            if score > best_score:
                best_score = score
        start = stop
    empty["score"] = best_score
    return empty
from tools.gpu_lab.audio_load import load_coverage  # noqa: E402
from tools.gpu_lab.ladder import pairs  # noqa: E402
from tools.gpu_lab.learning_net.data import bridge_masks  # noqa: E402

OUT = REPO / "docs/ohush/research/STING_LANDMARKS_001"
REDZONE = "hush_20260913_150934"
ORDER = (
    ("hush_20260909_213047", "Sept 9 NBC"),
    ("hush_20260913_150934", "Sept 13 RedZone"),
    ("hush_20260913_210542", "Sept 13 NBC"),
    ("hush_20260914_212529", "Sept 14 ESPN"),
    ("hush_20260924_220624", "Sept 24 Prime"),
    ("hush_20261008_205100", "Oct 8 Prime Video"),
    ("hush_20261010_222400", "Oct 10 cable"),
    ("hush_20261011_135700", "Oct 11 afternoon"),
    ("hush_20261011_204300", "Oct 11 night"),
    ("hush_20261012_204200", "Oct 12 MNF"),
)
KINDS = ("before_start", "after_start", "before_end")


def clip_span(kind: str, start: float, end: float) -> tuple[float, float]:
    if kind == "before_start":
        return start - 2.0, start
    if kind == "after_start":
        return start, start + 2.0
    if kind == "before_end":
        return end - 2.0, end
    raise ValueError(kind)


def to_11025(audio: np.ndarray) -> np.ndarray:
    return resample_poly(audio.astype(np.float64), 441, 640)


def take(audio: np.ndarray, origin: float, t0: float, t1: float) -> tuple[np.ndarray, np.ndarray] | None:
    a = int(round((t0 - origin) * 16000))
    b = int(round((t1 - origin) * 16000))
    if a < 0 or b > len(audio) or b - a < 16000:
        return None
    frames, hashes = fingerprint(to_11025(audio[a:b]))
    if frames.size == 0:
        return np.zeros(0, np.int32), np.zeros(0, np.int32)
    return frames, hashes


def summarize(hits: list[dict]) -> dict:
    scores = [row["score"] for row in hits]
    return {
        "n": len(hits),
        "max_score": max(scores) if scores else 0,
        "median_score": int(np.median(scores)) if scores else 0,
        "median_hashes": int(np.median([row["n_hashes"] for row in hits])) if hits else 0,
        "at_200": sum(score >= PUBLISHED_COUNT for score in scores),
    }


def main() -> None:
    masks = bridge_masks()
    library: dict[str, list[dict]] = {kind: [] for kind in KINDS}
    steps = []
    for session, name in ORDER:
        mask = masks[session]
        coverage = pairs(mask, "coverage")[0]
        pods = pairs(mask, "verified_commercial")
        print(f"load {name}", flush=True)
        audio = load_coverage(session, coverage[0], coverage[1])
        boundary = {kind: [] for kind in KINDS}
        for start, end in pods:
            for kind in KINDS:
                span = clip_span(kind, start, end)
                hashed = take(audio, coverage[0], span[0], span[1])
                if hashed is None:
                    continue
                boundary[kind].append({"t": round(start, 3), "frames": hashed[0], "hashes": hashed[1]})
        program = []
        cursor = coverage[0] + 60.0
        while cursor + 2.0 < coverage[1]:
            if any(start - 30.0 <= cursor <= end + 30.0 for start, end in pods):
                cursor += 60.0
                continue
            hashed = take(audio, coverage[0], cursor, cursor + 2.0)
            if hashed is not None:
                program.append({"t": round(cursor, 3), "frames": hashed[0], "hashes": hashed[1]})
            cursor += 60.0
        step = {"session": session, "name": name, "enrolled": session != REDZONE, "kinds": {}}
        for kind in KINDS:
            refs = library[kind]
            if not refs:
                step["kinds"][kind] = {"library": 0, "boundaries": None, "program": None}
                continue
            index = build_index(refs)
            allow = np.ones(len(refs), dtype=bool)

            def query(rows: list[dict]) -> list[dict]:
                found = []
                for row in rows:
                    hit = best_match(row["frames"], row["hashes"], index, allow)
                    found.append({"score": int(hit["score"]), "n_hashes": int(hit["n_hashes"])})
                return found

            step["kinds"][kind] = {
                "library": len(refs),
                "boundaries": None if session == REDZONE else summarize(query(boundary[kind])),
                "program": summarize(query(program)),
            }
        if session != REDZONE:
            for kind in KINDS:
                for row in boundary[kind]:
                    library[kind].append({
                        "id": len(library[kind]),
                        "session": session,
                        "frames": row["frames"],
                        "hashes": row["hashes"],
                    })
        steps.append(step)
        kind = step["kinds"]["after_start"]
        boundaries = kind["boundaries"] or {}
        program_row = kind["program"] or {}
        print(
            f"  after_start library {kind['library']} "
            f"boundary max {boundaries.get('max_score')} at200 {boundaries.get('at_200')} "
            f"program max {program_row.get('max_score')} at200 {program_row.get('at_200')}",
            flush=True,
        )
        del audio

    first = next(row for row in library["after_start"] if row["session"] == ORDER[0][0])
    self_index = build_index([{"id": 0, "frames": first["frames"], "hashes": first["hashes"]}])
    self_hit = best_match(first["frames"], first["hashes"], self_index, np.ones(1, dtype=bool))
    payload = {
        "id": "STING_LANDMARKS_001",
        "accept_count": PUBLISHED_COUNT,
        "windows": {
            "before_start": "2 seconds ending at the labeled start",
            "after_start": "2 seconds beginning at the labeled start",
            "before_end": "2 seconds ending at the labeled end",
        },
        "library": "earlier football boundary windows of the same kind only",
        "october_may_choose_cutoff": False,
        "live_mute_changed": False,
        "self_match": {"score": int(self_hit["score"]), "n_hashes": int(self_hit["n_hashes"])},
        "steps": steps,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"self-match {payload['self_match']}", flush=True)
    print(f"wrote {OUT / 'results.json'}", flush=True)


if __name__ == "__main__":
    main()
