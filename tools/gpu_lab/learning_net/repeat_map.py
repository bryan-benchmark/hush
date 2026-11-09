"""How many commercial seconds are copies of an ad already heard.

The copy bar is the 10th percentile of cosine similarity between two seconds
five seconds apart inside the same training commercial. October is scored once
at that bar.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from tools.gpu_lab.ladder import pairs
from tools.gpu_lab.learning_net.data import bridge_masks, input_hashes, load_cache
from tools.gpu_lab.learning_net.log import finish_probe, open_probe
from tools.gpu_lab.prepare import DATA_ROOT
from tools.gpu_lab.splits import CALIBRATE, DEVELOP, TRAIN

MODULE = Path(__file__)
PROBE_ID = "repeat_map"
QUESTION = "What fraction of commercial seconds copies an ad from another game, and do program seconds copy those ads too?"
WINDOW_S = 5.0
SHIFT_S = 5
COPY_PERCENTILE = 10.0


def _normalize(vectors: np.ndarray) -> np.ndarray:
    scale = np.linalg.norm(vectors, axis=1, keepdims=True)
    scale = np.maximum(scale, 1e-12)
    return vectors / scale


def _span_id(time_s: float, spans: list[tuple[float, float]]) -> int | None:
    end = time_s + 1.0
    for index, (start, stop) in enumerate(spans):
        if start <= time_s + 1e-9 and end <= stop + 1e-9:
            return index
    return None


def _max_cosine(query: np.ndarray, library: np.ndarray, chunk: int = 2048) -> np.ndarray:
    if len(query) == 0 or len(library) == 0:
        return np.zeros(len(query), dtype=np.float64)
    best = np.full(len(query), -np.inf, dtype=np.float64)
    for start in range(0, len(query), chunk):
        block = query[start : start + chunk]
        scores = block @ library.T
        best[start : start + len(block)] = scores.max(axis=1)
    return best


def _pack(session: str, root: Path) -> dict:
    cached = load_cache(session, WINDOW_S, root)
    mask = bridge_masks()[session]
    commercials = pairs(mask, "verified_commercial")
    times = cached["t"]
    labels = cached["label"]
    vectors = _normalize(cached["emb"])
    commercial = labels == 1
    program = labels == 0
    span_ids = np.full(len(times), -1, dtype=np.int16)
    for index, moment in enumerate(times):
        if commercial[index]:
            found = _span_id(float(moment), commercials)
            if found is not None:
                span_ids[index] = found
    return {"t": times, "vectors": vectors, "commercial": commercial, "program": program, "span": span_ids}


def _same_ad_cosines(packed: dict) -> np.ndarray:
    times = packed["t"]
    vectors = packed["vectors"]
    span = packed["span"]
    found = []
    lookup = {round(float(moment), 3): index for index, moment in enumerate(times)}
    for index, moment in enumerate(times):
        if span[index] < 0:
            continue
        other = lookup.get(round(float(moment) + SHIFT_S, 3))
        if other is None or span[other] != span[index]:
            continue
        found.append(float(np.dot(vectors[index], vectors[other])))
    return np.asarray(found, dtype=np.float64)


def _fraction(values: np.ndarray, bar: float) -> dict:
    if len(values) == 0:
        return {"n": 0, "copy_n": 0, "copy_fraction": None, "median_cosine": None}
    hits = values >= bar
    return {
        "n": int(len(values)),
        "copy_n": int(hits.sum()),
        "copy_fraction": round(float(hits.mean()), 6),
        "median_cosine": round(float(np.median(values)), 6),
    }


def run(root: Path = DATA_ROOT) -> dict:
    parameters = {
        "window_s": WINDOW_S,
        "embedding": "cached AST CLS, L2-normalized cosine",
        "same_ad_pair": f"two commercial seconds {SHIFT_S}s apart inside one gold commercial span",
        "copy_bar": f"{COPY_PERCENTILE:g}th percentile of those training cosines",
        "library": list(TRAIN),
        "october_sessions": list(DEVELOP),
        "october_may_choose_cutoff": False,
    }
    folder = open_probe(PROBE_ID, QUESTION, parameters, MODULE)
    packed = {session: _pack(session, root) for session in list(TRAIN) + list(CALIBRATE) + list(DEVELOP)}
    positives = np.concatenate([_same_ad_cosines(packed[session]) for session in TRAIN])
    bar = float(np.percentile(positives, COPY_PERCENTILE))
    train_library = np.concatenate([packed[session]["vectors"][packed[session]["commercial"]] for session in TRAIN])
    print(f"  copy bar {bar:.4f} from {len(positives)} same-ad pairs, library {len(train_library)}", flush=True)

    train_rows = []
    for session in TRAIN:
        others = np.concatenate([packed[other]["vectors"][packed[other]["commercial"]] for other in TRAIN if other != session])
        commercial_vectors = packed[session]["vectors"][packed[session]["commercial"]]
        program_vectors = packed[session]["vectors"][packed[session]["program"]]
        train_rows.append(
            {
                "session": session,
                "commercial_vs_other_train_ads": _fraction(_max_cosine(commercial_vectors, others), bar),
                "program_vs_other_train_ads": _fraction(_max_cosine(program_vectors, others), bar),
            }
        )
        print(f"  train {session} ad copies {train_rows[-1]['commercial_vs_other_train_ads']['copy_fraction']}", flush=True)

    october_rows = []
    for session in DEVELOP:
        commercial_vectors = packed[session]["vectors"][packed[session]["commercial"]]
        program_vectors = packed[session]["vectors"][packed[session]["program"]]
        october_rows.append(
            {
                "session": session,
                "commercial_vs_train_ads": _fraction(_max_cosine(commercial_vectors, train_library), bar),
                "program_vs_train_ads": _fraction(_max_cosine(program_vectors, train_library), bar),
            }
        )
        print(
            f"  october {session} ads {october_rows[-1]['commercial_vs_train_ads']['copy_fraction']} "
            f"program {october_rows[-1]['program_vs_train_ads']['copy_fraction']}",
            flush=True,
        )

    def _sum(rows: list[dict], key: str) -> dict:
        n = sum(row[key]["n"] for row in rows)
        hits = sum(row[key]["copy_n"] for row in rows)
        return {"n": n, "copy_n": hits, "copy_fraction": None if n == 0 else round(hits / n, 6)}

    result = {
        "probe_id": PROBE_ID,
        "inputs": input_hashes(WINDOW_S, list(TRAIN) + list(CALIBRATE) + list(DEVELOP), root),
        "copy_bar_cosine": round(bar, 6),
        "same_ad_pairs": int(len(positives)),
        "same_ad_cosine_p10": round(bar, 6),
        "same_ad_cosine_p50": round(float(np.percentile(positives, 50)), 6),
        "train": train_rows,
        "train_commercial_copy_fraction": _sum(train_rows, "commercial_vs_other_train_ads"),
        "train_program_false_copy_fraction": _sum(train_rows, "program_vs_other_train_ads"),
        "october": october_rows,
        "october_commercial_copy_fraction": _sum(october_rows, "commercial_vs_train_ads"),
        "october_program_false_copy_fraction": _sum(october_rows, "program_vs_train_ads"),
        "calibrate_session_not_in_library": CALIBRATE[0],
    }
    finish_probe(folder, PROBE_ID, QUESTION, parameters, result, MODULE)
    return result
