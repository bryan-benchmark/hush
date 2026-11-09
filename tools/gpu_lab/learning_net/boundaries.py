"""Loudness around gold commercial edges, compared with ordinary seconds.

Training games and ESPN only. October is not used. A 12 dB dip is the
predeclared description of a gap. It is not a mute rule.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from tools.gpu_lab.audio_load import load_coverage
from tools.gpu_lab.ladder import pairs
from tools.gpu_lab.learning_net.data import bridge_masks
from tools.gpu_lab.learning_net.log import finish_probe, open_probe
from tools.gpu_lab.prepare import DATA_ROOT
from tools.gpu_lab.splits import CALIBRATE, TRAIN

MODULE = Path(__file__)
PROBE_ID = "boundaries"
QUESTION = "Do commercial edges have a quiet gap that ordinary game seconds and ordinary ad seconds do not?"
SAMPLE_RATE = 16000
HOP_S = 0.1
EDGE_S = 1.0
INTERIOR_STRIDE_S = 30.0
GAP_DB = 12.0


def _hop_db(audio: np.ndarray) -> np.ndarray:
    hop = int(HOP_S * SAMPLE_RATE)
    if len(audio) < hop:
        return np.array([], dtype=np.float64)
    frames = audio[: len(audio) - (len(audio) % hop)].reshape(-1, hop)
    rms = np.sqrt(np.mean(frames * frames, axis=1) + 1e-12)
    return 20.0 * np.log10(rms)


def _slice(audio: np.ndarray, origin: float, start: float, end: float) -> np.ndarray:
    a = int(round((start - origin) * SAMPLE_RATE))
    b = int(round((end - origin) * SAMPLE_RATE))
    if a < 0 or b > len(audio) or b <= a:
        return np.array([], dtype=np.float32)
    return audio[a:b]


def _measure(audio: np.ndarray, origin: float, center: float) -> float | None:
    window = _slice(audio, origin, center - EDGE_S, center + EDGE_S)
    hops = _hop_db(window)
    if len(hops) < 4:
        return None
    return float(np.median(hops) - np.min(hops))


def _interiors(spans: list[tuple[float, float]]) -> list[float]:
    points = []
    for start, end in spans:
        cursor = start + INTERIOR_STRIDE_S
        while cursor + EDGE_S < end:
            points.append(cursor)
            cursor += INTERIOR_STRIDE_S
    return points


def _summary(dips: list[float]) -> dict:
    values = np.asarray([dip for dip in dips if dip is not None], dtype=np.float64)
    if len(values) == 0:
        return {"n": 0, "median_dip_db": None, "gap_fraction": None}
    return {
        "n": int(len(values)),
        "median_dip_db": round(float(np.median(values)), 3),
        "gap_fraction": round(float(np.mean(values >= GAP_DB)), 6),
    }


def run(root: Path = DATA_ROOT) -> dict:
    del root
    parameters = {
        "sessions": list(TRAIN + CALIBRATE),
        "edge_window_s": EDGE_S * 2,
        "hop_s": HOP_S,
        "gap_db": GAP_DB,
        "interior_stride_s": INTERIOR_STRIDE_S,
        "october_used": False,
    }
    folder = open_probe(PROBE_ID, QUESTION, parameters, MODULE)
    masks = bridge_masks()
    edges: list[float] = []
    program: list[float] = []
    commercial: list[float] = []
    per_session = []
    for session in TRAIN + CALIBRATE:
        mask = masks[session]
        coverage = pairs(mask, "coverage")[0]
        print(f"  load {session}", flush=True)
        audio = load_coverage(session, coverage[0], coverage[1])
        origin = coverage[0]
        edge_points = []
        for start, end in pairs(mask, "verified_commercial"):
            edge_points.extend((start, end))
        session_edges = [_measure(audio, origin, point) for point in edge_points]
        session_program = [_measure(audio, origin, point) for point in _interiors(pairs(mask, "verified_program"))]
        session_commercial = [_measure(audio, origin, point) for point in _interiors(pairs(mask, "verified_commercial"))]
        edges.extend(session_edges)
        program.extend(session_program)
        commercial.extend(session_commercial)
        per_session.append(
            {
                "session": session,
                "edges": _summary(session_edges),
                "program_interior": _summary(session_program),
                "commercial_interior": _summary(session_commercial),
            }
        )
        del audio
    result = {
        "probe_id": PROBE_ID,
        "gap_definition": f"median hop minus quietest hop is at least {GAP_DB:.0f} dB inside a 2 second window",
        "edges": _summary(edges),
        "program_interior": _summary(program),
        "commercial_interior": _summary(commercial),
        "sessions": per_session,
    }
    finish_probe(folder, PROBE_ID, QUESTION, parameters, result, MODULE)
    return result
