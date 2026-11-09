"""See whether game seconds above the head's midpoint form a few stretches.

The midpoint is the same zero logged by program_names. Ten equal time bins
are declared here, before the counts are read. No cutoff is fit on October.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from experiments.ledger import sha256_text
from tools.gpu_lab.decisions import HOP_S
from tools.gpu_lab.learning_net.data import BRIDGE, load_cache, load_head, logits_for
from tools.gpu_lab.learning_net.game_sounds import _role
from tools.gpu_lab.learning_net.log import finish_probe, open_probe
from tools.gpu_lab.prepare import DATA_ROOT
from tools.gpu_lab.splits import CONTROL

MODULE = Path(__file__)
PROBE_ID = "program_spread"
QUESTION = "Are the game seconds scored above zero gathered in a few stretches, or spread through the broadcast?"
WINDOW_S = 10.0
BINS = 10
NAMES_FOLDER = "20261023T043744Z_program_names"
NAMES_SHA256 = "77a91c725dfc8c6d8ea19c486ce13499191267c4138ea2f35c16c15b12062777"


def contiguous_runs(times: np.ndarray, hop_s: float = HOP_S) -> list[dict]:
    if len(times) == 0:
        return []
    ordered = np.sort(np.asarray(times, dtype=np.float64))
    runs = []
    start = float(ordered[0])
    previous = start
    count = 1
    for raw in ordered[1:]:
        current = float(raw)
        if current - previous <= hop_s + 1e-6:
            previous = current
            count += 1
            continue
        runs.append(
            {
                "start_seconds": round(start, 3),
                "end_seconds": round(previous + hop_s, 3),
                "n": count,
            }
        )
        start = current
        previous = current
        count = 1
    runs.append({"start_seconds": round(start, 3), "end_seconds": round(previous + hop_s, 3), "n": count})
    return runs


def bin_counts(times: np.ndarray, start: float, end: float, bins: int = BINS) -> list[int]:
    if end <= start:
        raise ValueError("broadcast span must be positive")
    counts = [0] * bins
    if len(times) == 0:
        return counts
    width = (end - start) / bins
    for raw in np.asarray(times, dtype=np.float64):
        index = int((float(raw) - start) / width)
        if index == bins:
            index = bins - 1
        if index < 0 or index >= bins:
            continue
        counts[index] += 1
    return counts


def _cited(root: Path, folder: str, expected: str) -> None:
    path = root / "learning_net" / "probes" / folder / "result.json"
    digest = sha256_text(path.read_text(encoding="utf-8"))
    if digest != expected:
        raise RuntimeError(f"{folder} hash {digest} does not match {expected}")


def run(root: Path = DATA_ROOT) -> dict:
    parameters = {
        "window_s": WINDOW_S,
        "split": "program seconds with logistic decision_function above 0",
        "bins": BINS,
        "hop_s": HOP_S,
        "october_may_choose_cutoff": False,
        "compared_with": {"probe_id": "program_names", "folder": NAMES_FOLDER, "result_sha256": NAMES_SHA256},
    }
    folder = open_probe(PROBE_ID, QUESTION, parameters, MODULE)
    _cited(root, NAMES_FOLDER, NAMES_SHA256)
    names_doc = json.loads((root / "learning_net" / "probes" / NAMES_FOLDER / "result.json").read_text(encoding="utf-8"))
    cited_fraction = {row["session"]: row["program_above_zero_fraction"] for row in names_doc["rows"]}
    _path, head = load_head(WINDOW_S, root)
    rows = []
    for session in BRIDGE:
        cached = load_cache(session, WINDOW_S, root)
        labels = cached["label"].astype(np.int8)
        times = cached["t"].astype(np.float64)
        scores = logits_for(head, cached["emb"])
        chosen = times[(labels == 0) & (scores > 0)]
        program_n = int((labels == 0).sum())
        fraction = round(float(len(chosen)) / program_n, 6) if program_n else None
        if fraction != cited_fraction.get(session):
            raise RuntimeError(f"{session} above-zero fraction {fraction} does not match program_names")
        runs = contiguous_runs(chosen)
        longest = max(runs, key=lambda row: row["n"]) if runs else None
        span_start = float(times[0])
        span_end = float(times[-1]) + HOP_S
        counts = bin_counts(chosen, span_start, span_end, BINS)
        occupied = sum(count > 0 for count in counts)
        busiest = max(counts) if counts else 0
        row = {
            "session": session,
            "role": _role(session),
            "program_n": program_n,
            "program_above_zero_n": int(len(chosen)),
            "program_above_zero_fraction": fraction,
            "incidents": len(runs),
            "longest": longest,
            "median_incident_n": None if not runs else int(np.median([item["n"] for item in runs])),
            "bins": counts,
            "bins_occupied": occupied,
            "busiest_bin_n": busiest,
            "busiest_bin_fraction": None if len(chosen) == 0 else round(busiest / len(chosen), 6),
        }
        rows.append(row)
        print(
            f"  {session} seconds {row['program_above_zero_n']} incidents {row['incidents']} "
            f"longest {None if longest is None else longest['n']} bins {occupied}/{BINS}",
            flush=True,
        )
    result = {
        "probe_id": PROBE_ID,
        "rows": rows,
        "october_may_choose_cutoff": False,
        "program_names_result_sha256": NAMES_SHA256,
        "control_session": CONTROL[0],
    }
    finish_probe(folder, PROBE_ID, QUESTION, parameters, result, MODULE)
    return result
