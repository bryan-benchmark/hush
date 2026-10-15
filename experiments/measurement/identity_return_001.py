"""IDENTITY-RETURN-001: read-only return feasibility.

Oracle-start rows use the gold commercial start only to place the pre-break
reference. They are not an operational result. The causal path uses a published
Exp003b freeze and audio that ended at or before that freeze.

Thresholds below are copied from the published experiments. This script does
not search them. It does not write into experiment outputs, live workers, or
gold files.
"""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from experiments.ledger import TRUTH_PATH, read_jsonl, resolve_ledger  # noqa: E402
from hush.frozen_identity import cloud_distance, reference_bounds  # noqa: E402
from hush.overlay003b import COVER_S  # noqa: E402
from hush.overlay005 import RETURN_HORIZON_S  # noqa: E402
from hush.program_cloud import MIN_REFERENCE_S, WINDOW_S as ACOUSTIC_WINDOW_S  # noqa: E402
from hush.speaker_memory import MATCH_COSINE  # noqa: E402

# Published Exp002 absence, reused as the minimum time a voice must already
# have been the dominant recurring speaker. Not searched.
SPEAKER_PRESENCE_S = 30.0
# Requested return windows. The 120 s horizon is the published Exp005 horizon.
HORIZONS_S = (2.0, 5.0, 10.0, 15.0, 30.0)
# Declared before scoring. A service can support a later causal experiment
# only when one signal meets every line on the causal path.
QUICK_S = 10.0
FALSE_RETURN_MAX_RATE = 0.20
DEPARTURE_COVERAGE_MIN = 0.50
MIN_PROGRAM_TAIL_S = 2.0

HOLDOUTS = ("hush_20260917_205513", "hush_20260920_200635")
OUT = REPO / "docs/ohush/research/IDENTITY_RETURN_001"
SESSIONS = (
    {
        "session": "hush_20260914_212529",
        "service": "ESPN",
        "show": "Monday Night Football",
        "coverage": (0.0, 6899.0),
        "clock_offset_s": 0.0,
    },
    {
        "session": "hush_20260924_220624",
        "service": "Prime",
        "show": "NFL",
        "coverage": (0.0, 7600.0),
        "clock_offset_s": 0.0,
    },
    {
        "session": "hush_20260827_135935",
        "service": "Hulu",
        "show": "August Hulu",
        "coverage": (300.0, 7200.0),
        "clock_offset_s": 300.0,
    },
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_truth() -> list[dict]:
    rows = resolve_ledger(read_jsonl(TRUTH_PATH), "gold_id")
    kept = []
    for row in rows:
        if row.get("retracted") or row.get("event") == "retracted":
            continue
        if "start_seconds" not in row:
            continue
        if row.get("session") in HOLDOUTS:
            raise SystemExit("refusing a sealed holdout")
        kept.append(row)
    return kept


def commercials(rows: list[dict], session: str, coverage: tuple[float, float]) -> list[dict]:
    c0, c1 = coverage
    chosen = []
    for row in rows:
        if row.get("session") != session:
            continue
        if row.get("event_class") != "commercial" or row.get("desired_action") != "mute":
            continue
        if row.get("confidence") == "unsure":
            continue
        start, end = float(row["start_seconds"]), float(row["end_seconds"])
        if start < c0 or end > c1:
            raise SystemExit(f"{session} commercial leaves coverage: {start} {end}")
        chosen.append({"start": start, "end": end})
    chosen.sort(key=lambda item: item["start"])
    return chosen


def overlaps(a0: float, a1: float, b0: float, b1: float) -> bool:
    return a0 < b1 - 1e-9 and b0 < a1 - 1e-9


def reference_contaminated(starts: np.ndarray, ends: np.ndarray, mask: np.ndarray, pods: list[dict]) -> bool:
    for index in np.flatnonzero(mask):
        for pod in pods:
            if overlaps(float(starts[index]), float(ends[index]), pod["start"], pod["end"]):
                return True
    return False


def first_time(times: np.ndarray, flags: np.ndarray, origin: float, horizon: float) -> float | None:
    chosen = np.flatnonzero((times > origin) & (times <= origin + horizon) & flags)
    if chosen.size == 0:
        return None
    return float(times[chosen[0]])


def premature(times: np.ndarray, values: np.ndarray, start: float, stop: float, level: float) -> bool:
    chosen = np.flatnonzero((times > start) & (times <= stop) & np.isfinite(values))
    seen_above = False
    for index in chosen:
        if values[index] > level:
            seen_above = True
        elif seen_above and values[index] <= level:
            return True
    return False


def program_seconds(start: float, stop: float, pods: list[dict]) -> float:
    if stop <= start:
        return 0.0
    cuts = [start, stop]
    for pod in pods:
        if start < pod["end"] and pod["start"] < stop:
            cuts.extend([max(start, pod["start"]), min(stop, pod["end"])])
    points = sorted(set(cuts))
    total = 0.0
    for left, right in zip(points, points[1:]):
        if any(pod["start"] <= left and right <= pod["end"] for pod in pods):
            continue
        total += right - left
    return total


def empty_signal() -> dict:
    row = {
        "available": False,
        "reason": None,
        "threshold": None,
        "reentry": False,
        "false_return": False,
        "ad_resemble_s": None,
        "ad_scored_s": None,
        "recovery_latency_s": None,
        "operational_latency_s": None,
        "missed_program_s": None,
        "program_false_mute_s": None,
        "ad_uncovered_s": None,
        "first_match_id": None,
    }
    for horizon in HORIZONS_S:
        key = str(int(horizon))
        row[f"recovery_by_{key}"] = None
        row[f"operational_by_{key}"] = None
    return row


def horizon_flags(latency: float | None, false_return: bool, program_tail: float) -> dict:
    flags = {}
    for horizon in HORIZONS_S:
        key = str(int(horizon))
        if program_tail + 1e-9 < horizon:
            flags[f"recovery_by_{key}"] = None
            flags[f"operational_by_{key}"] = None
            continue
        recovered = latency is not None and latency <= horizon
        flags[f"recovery_by_{key}"] = recovered
        flags[f"operational_by_{key}"] = False if false_return else recovered
    return flags


def score_levels(
    times: np.ndarray,
    values: np.ndarray,
    level: float,
    departure: float,
    gold_end: float,
    program_tail: float,
    pods: list[dict],
) -> dict:
    """Low values resemble the frozen reference. `level` is that snapshot's own median."""
    row = empty_signal()
    row["available"] = True
    row["threshold"] = level
    finite = (times > departure) & (times <= gold_end) & np.isfinite(values)
    row["ad_scored_s"] = float(np.count_nonzero(finite))
    row["ad_resemble_s"] = float(np.count_nonzero(finite & (values <= level)))
    row["reentry"] = premature(times, values, departure, gold_end, level)
    reach = (gold_end + RETURN_HORIZON_S) - departure
    resembles = np.isfinite(values) & (values <= level)
    crossing = first_time(times, resembles, departure, reach)
    false_return = crossing is not None and crossing <= gold_end
    row["false_return"] = false_return
    recovery = first_time(times, resembles, gold_end, RETURN_HORIZON_S)
    recovery_latency = None if recovery is None else recovery - gold_end
    row["recovery_latency_s"] = recovery_latency
    row["operational_latency_s"] = None if false_return else recovery_latency
    if false_return and crossing is not None:
        row["ad_uncovered_s"] = gold_end - crossing
        row["missed_program_s"] = 0.0
        row["program_false_mute_s"] = 0.0
    elif recovery_latency is not None:
        missed = min(recovery_latency, program_tail)
        row["ad_uncovered_s"] = 0.0
        row["missed_program_s"] = missed
        row["program_false_mute_s"] = missed
    else:
        missed = min(program_tail, RETURN_HORIZON_S)
        row["ad_uncovered_s"] = 0.0
        row["missed_program_s"] = missed
        row["program_false_mute_s"] = missed
    row.update(horizon_flags(recovery_latency, false_return, program_tail))
    row["pods_checked"] = len(pods)
    return row


def load_acoustic(session: str) -> dict:
    frame = pd.read_parquet(REPO / "experiments/exp003" / session / "program_cloud.parquet")
    embeddings = np.vstack([np.asarray(row, dtype=np.float64) for row in frame["embedding"]])
    return {
        "starts": frame["window_start"].to_numpy(dtype=np.float64),
        "ends": frame["window_end"].to_numpy(dtype=np.float64),
        "embeddings": embeddings,
    }


def load_semantic(session: str) -> dict:
    frame = pd.read_parquet(REPO / "experiments/exp005" / session / "semantic.parquet")
    embeddings = np.load(REPO / "experiments/exp005" / session / "semantic_embeddings.npy").astype(np.float64)
    if len(embeddings) != len(frame):
        raise RuntimeError(f"{session} semantic embeddings do not align")
    present = frame["n_words"].to_numpy(dtype=int) >= 8
    return {
        "starts": frame["window_start"].to_numpy(dtype=np.float64),
        "ends": frame["window_end"].to_numpy(dtype=np.float64),
        "embeddings": embeddings,
        "present": present,
    }


def load_speakers(session: str) -> dict:
    frame = pd.read_parquet(REPO / "experiments/exp002" / session / "speaker_timeline.parquet")
    clusters = frame["dominant_recurring_cluster_id"].astype("string")
    active = frame["speaker_cluster_id"].astype("string")
    return {
        "times": frame["timestamp_seconds"].to_numpy(dtype=np.float64),
        "speech": frame["speech_active"].to_numpy(dtype=int),
        "dominant": clusters.to_numpy(),
        "active": active.to_numpy(),
        "similarity": frame["speaker_similarity_to_best_known"].to_numpy(dtype=np.float64),
    }


def load_freezes(session: str) -> list[dict]:
    return json.loads((REPO / "experiments/exp003b" / session / "freezes.json").read_text(encoding="utf-8"))


def distance_from_mask(ends: np.ndarray, embeddings: np.ndarray, mask: np.ndarray, present: np.ndarray | None) -> tuple[np.ndarray, float] | None:
    chosen = mask if present is None else mask & present
    if int(chosen.sum()) < 2:
        return None
    chosen_ends = ends[chosen]
    if float(chosen_ends[-1] - chosen_ends[0]) < MIN_REFERENCE_S:
        return None
    reference = embeddings[chosen]
    current = embeddings if present is None else embeddings
    distances, level = cloud_distance(current, reference)
    if present is not None:
        scored = np.full(len(ends), np.nan)
        scored[present] = distances[present]
        distances = scored
    return distances, level


def acoustic_snapshot(acoustic: dict, trigger: float, pods: list[dict]) -> tuple[np.ndarray, float] | str:
    start, stop = reference_bounds(trigger)
    mask = (acoustic["ends"] > start) & (acoustic["ends"] <= stop)
    if reference_contaminated(acoustic["starts"], acoustic["ends"], mask, pods):
        return "reference_overlaps_commercial"
    scored = distance_from_mask(acoustic["ends"], acoustic["embeddings"], mask, None)
    if scored is None:
        return "reference_shorter_than_60s"
    return scored


def semantic_snapshot(semantic: dict, trigger: float, pods: list[dict]) -> tuple[np.ndarray, float] | str:
    start, stop = reference_bounds(trigger)
    mask = (semantic["ends"] > start) & (semantic["ends"] <= stop)
    if reference_contaminated(semantic["starts"], semantic["ends"], mask, pods):
        return "reference_overlaps_commercial"
    scored = distance_from_mask(semantic["ends"], semantic["embeddings"], mask, semantic["present"])
    if scored is None:
        return "reference_shorter_than_60s_or_under_8_words"
    return scored


def speaker_ids(speakers: dict, trigger: float, pods: list[dict]) -> list[str] | str:
    start, stop = reference_bounds(trigger)
    times = speakers["times"]
    mask = (times > start) & (times <= stop)
    if not np.any(mask):
        return "reference_shorter_than_60s"
    if float(times[mask][-1] - times[mask][0]) < MIN_REFERENCE_S:
        return "reference_shorter_than_60s"
    for index in np.flatnonzero(mask):
        left = float(times[index]) - 1.0
        right = float(times[index])
        if any(overlaps(left, right, pod["start"], pod["end"]) for pod in pods):
            return "reference_overlaps_commercial"
    counts: dict[str, int] = {}
    for cid in speakers["dominant"][mask]:
        if cid is None or cid is pd.NA:
            continue
        text = str(cid)
        if text in {"", "<NA>", "nan", "None"}:
            continue
        counts[text] = counts.get(text, 0) + 1
    chosen = sorted(cid for cid, seconds in counts.items() if seconds >= SPEAKER_PRESENCE_S)
    if not chosen:
        return "no_dominant_speaker_for_30s"
    return chosen


def speaker_flags(speakers: dict, ids: list[str]) -> np.ndarray:
    active = speakers["active"]
    similarity = speakers["similarity"]
    flags = np.zeros(len(active), dtype=bool)
    allowed = set(ids)
    for index, cid in enumerate(active):
        if cid is None or cid is pd.NA:
            continue
        text = str(cid)
        if text not in allowed:
            continue
        if speakers["speech"][index] != 1:
            continue
        if np.isfinite(similarity[index]) and similarity[index] >= MATCH_COSINE:
            flags[index] = True
    return flags


def score_speaker(
    speakers: dict,
    ids: list[str],
    departure: float,
    gold_end: float,
    program_tail: float,
) -> dict:
    flags = speaker_flags(speakers, ids)
    times = speakers["times"]
    row = empty_signal()
    row["available"] = True
    row["threshold"] = MATCH_COSINE
    row["first_match_id"] = ",".join(ids)
    inside = (times > departure) & (times <= gold_end)
    row["ad_scored_s"] = float(np.count_nonzero(inside))
    row["ad_resemble_s"] = float(np.count_nonzero(inside & flags))
    absent = 0
    reentry = False
    for index in np.flatnonzero(inside):
        if flags[index]:
            if absent >= SPEAKER_PRESENCE_S:
                reentry = True
                break
            absent = 0
        else:
            absent += 1
    row["reentry"] = reentry
    reach = (gold_end + RETURN_HORIZON_S) - departure
    crossing = first_time(times, flags, departure, reach)
    false_return = crossing is not None and crossing <= gold_end
    row["false_return"] = false_return
    recovery = first_time(times, flags, gold_end, RETURN_HORIZON_S)
    recovery_latency = None if recovery is None else recovery - gold_end
    row["recovery_latency_s"] = recovery_latency
    row["operational_latency_s"] = None if false_return else recovery_latency
    if false_return and crossing is not None:
        row["ad_uncovered_s"] = gold_end - crossing
        row["missed_program_s"] = 0.0
        row["program_false_mute_s"] = 0.0
    elif recovery_latency is not None:
        missed = min(recovery_latency, program_tail)
        row["ad_uncovered_s"] = 0.0
        row["missed_program_s"] = missed
        row["program_false_mute_s"] = missed
    else:
        missed = min(program_tail, RETURN_HORIZON_S)
        row["ad_uncovered_s"] = 0.0
        row["missed_program_s"] = missed
        row["program_false_mute_s"] = missed
    row.update(horizon_flags(recovery_latency, false_return, program_tail))
    return row


def qualifying_freeze(freezes: list[dict], start: float, pods: list[dict]) -> tuple[dict | None, str]:
    near = [
        row
        for row in freezes
        if not row.get("skipped") and start < float(row["trigger_s"]) <= start + COVER_S
    ]
    near.sort(key=lambda row: float(row["trigger_s"]))
    if not near:
        return None, "no_freeze_within_60s"
    saw_include = False
    saw_overlap = False
    for row in near:
        trigger = float(row["trigger_s"])
        ref_start, ref_stop = reference_bounds(trigger)
        if ref_stop > start + 1e-9:
            saw_include = True
            continue
        if any(overlaps(ref_start, ref_stop, pod["start"], pod["end"]) for pod in pods):
            saw_overlap = True
            continue
        return row, "clean_freeze"
    if saw_include:
        return None, "reference_includes_this_commercial"
    if saw_overlap:
        return None, "reference_overlaps_commercial"
    return None, "no_freeze_within_60s"


def observe(times: np.ndarray, values: np.ndarray, level: float, start: float, stop: float, resemble_low: bool) -> list[tuple[float, float, bool]]:
    chosen = (times > start) & (times <= stop) & np.isfinite(values)
    rows = []
    for index in np.flatnonzero(chosen):
        value = float(values[index])
        resembles = value <= level if resemble_low else value >= level
        rows.append((float(times[index]), value, resembles))
    return rows


def median(values: list[float]) -> float | None:
    clean = [value for value in values if value is not None and np.isfinite(value)]
    if not clean:
        return None
    return float(np.median(clean))


def rate(flags: list[bool]) -> float | None:
    if not flags:
        return None
    return float(sum(flags) / len(flags))


def signal_rollup(rows: list[dict], prefix: str) -> dict:
    available = [row for row in rows if row[f"{prefix}_available"]]
    operational = [row[f"{prefix}_operational_latency_s"] for row in available if not row[f"{prefix}_false_return"]]
    rollup = {
        "n_available": len(available),
        "n_false_return": sum(1 for row in available if row[f"{prefix}_false_return"]),
        "n_reentry": sum(1 for row in available if row[f"{prefix}_reentry"]),
        "false_return_rate": rate([row[f"{prefix}_false_return"] for row in available]),
        "median_ad_resemble_s": median([row[f"{prefix}_ad_resemble_s"] for row in available]),
        "median_operational_latency_when_valid_s": median(
            [row[f"{prefix}_operational_latency_s"] for row in available if row[f"{prefix}_operational_latency_s"] is not None]
        ),
        "median_recovery_latency_s": median([row[f"{prefix}_recovery_latency_s"] for row in available]),
        "median_missed_program_s": median([row[f"{prefix}_missed_program_s"] for row in available]),
        "median_program_false_mute_s": median([row[f"{prefix}_program_false_mute_s"] for row in available]),
        "median_ad_uncovered_s": median([row[f"{prefix}_ad_uncovered_s"] for row in available]),
        "n_operational_latency": sum(row[f"{prefix}_operational_latency_s"] is not None for row in available),
    }
    for horizon in HORIZONS_S:
        key = str(int(horizon))
        known = [row for row in available if row[f"{prefix}_recovery_by_{key}"] is not None]
        rollup[f"recovery_by_{key}"] = rate([bool(row[f"{prefix}_recovery_by_{key}"]) for row in known])
        rollup[f"operational_by_{key}"] = rate([bool(row[f"{prefix}_operational_by_{key}"]) for row in known])
        rollup[f"n_horizon_{key}"] = len(known)
    rollup["meets_quick_rule"] = bool(
        available
        and (rollup["false_return_rate"] or 0) <= FALSE_RETURN_MAX_RATE
        and (rollup["operational_by_10"] or 0) > 0.5
        and rollup["median_program_false_mute_s"] is not None
        and rollup["median_program_false_mute_s"] <= QUICK_S
    )
    return rollup


def false_departure_cost(freezes: list[dict], acoustic: dict, pods: list[dict], paired: set[float]) -> dict:
    events = []
    mute_s = 0.0
    n_contaminated = 0
    for row in freezes:
        if row.get("skipped"):
            continue
        trigger = float(row["trigger_s"])
        if trigger in paired:
            continue
        if any(pod["start"] < trigger <= pod["end"] for pod in pods):
            continue
        snapshot = acoustic_snapshot(acoustic, trigger, pods)
        if isinstance(snapshot, str):
            n_contaminated += 1
            events.append({"trigger_s": trigger, "status": snapshot})
            continue
        distances, level = snapshot
        recovery = first_time(
            acoustic["ends"],
            np.isfinite(distances) & (distances <= level),
            trigger,
            RETURN_HORIZON_S,
        )
        if recovery is None:
            span = program_seconds(trigger, trigger + RETURN_HORIZON_S, pods)
        else:
            span = program_seconds(trigger, recovery, pods)
        mute_s += span
        events.append({"trigger_s": trigger, "program_false_mute_s": round(span, 3), "returned": recovery is not None})
    return {
        "n_false_departures": len(events),
        "n_contaminated_reference": n_contaminated,
        "n_scored": len(events) - n_contaminated,
        "program_false_mute_s": round(mute_s, 3),
        "events": events,
    }


def prefix_fields(signal: dict, prefix: str) -> dict:
    out = {}
    for key, value in signal.items():
        if key == "pods_checked":
            continue
        out[f"{prefix}_{key}"] = value
    return out


def jsonable(value):
    if isinstance(value, dict):
        return {key: jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [jsonable(item) for item in value]
    if isinstance(value, float) and not np.isfinite(value):
        return None
    if isinstance(value, (np.floating,)):
        number = float(value)
        return None if not np.isfinite(number) else number
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    return value


def main() -> None:
    if any(job["session"] in HOLDOUTS for job in SESSIONS):
        raise SystemExit("refusing a sealed holdout")
    truth = load_truth()
    OUT.mkdir(parents=True, exist_ok=True)
    break_rows: list[dict] = []
    timeline: list[dict] = []
    coverage: dict = {
        "experiment": "IDENTITY-RETURN-001",
        "oracle_is_not_operational": True,
        "decision_rule": {
            "quick_s": QUICK_S,
            "false_return_max_rate": FALSE_RETURN_MAX_RATE,
            "departure_coverage_min": DEPARTURE_COVERAGE_MIN,
            "applies_to": "causal path only; oracle-start cannot satisfy it",
            "speaker_match_cosine": MATCH_COSINE,
            "speaker_presence_s": SPEAKER_PRESENCE_S,
            "self_distance": "snapshot median distance to its own centroid",
            "reference": "window ends in (trigger-210s, trigger-30s], span at least 60s, no commercial audio",
            "horizons_s": list(HORIZONS_S),
            "published_return_horizon_s": RETURN_HORIZON_S,
            "causal_cover_s": COVER_S,
        },
        "sessions": {},
        "signals_not_scored": {
            "microgap": "Closed negative census. No operating threshold was published, so none was applied.",
            "audfprint": "The library is vendored. No frozen fingerprint index exists for these sessions, so none was built.",
        },
    }
    inputs = [
        TRUTH_PATH,
        REPO / "experiments/gold/GOLD_DEV_V1.json",
        REPO / "experiments/gold/GOLD_REPLICATION_V1.json",
        Path(__file__),
    ]

    for job in SESSIONS:
        session = job["session"]
        offset = job["clock_offset_s"]
        pods_rec = commercials(truth, session, job["coverage"])
        pods = [{"start": pod["start"] - offset, "end": pod["end"] - offset} for pod in pods_rec]
        coverage_end = job["coverage"][1] - offset
        acoustic = load_acoustic(session)
        semantic = load_semantic(session)
        speakers = load_speakers(session)
        freezes = load_freezes(session)
        inputs.extend(
            [
                REPO / "experiments/exp003" / session / "program_cloud.parquet",
                REPO / "experiments/exp005" / session / "semantic.parquet",
                REPO / "experiments/exp005" / session / "semantic_embeddings.npy",
                REPO / "experiments/exp002" / session / "speaker_timeline.parquet",
                REPO / "experiments/exp003b" / session / "freezes.json",
            ]
        )
        session_rows = []
        paired: set[float] = set()
        excluded = []
        for index, pod in enumerate(pods, start=1):
            recording_start = pod["start"] + offset
            recording_end = pod["end"] + offset
            next_cut = coverage_end
            if index < len(pods):
                next_cut = min(next_cut, pods[index]["start"])
            program_tail = max(0.0, next_cut - pod["end"])
            base = {
                "session": session,
                "service": job["service"],
                "show": job["show"],
                "break_index": index,
                "recording_start_s": recording_start,
                "recording_end_s": recording_end,
                "feature_start_s": pod["start"],
                "feature_end_s": pod["end"],
                "program_tail_s": program_tail,
                "eligible": True,
                "exclusion": "",
            }
            if job["coverage"][1] - recording_end < MIN_PROGRAM_TAIL_S:
                base["eligible"] = False
                base["exclusion"] = "no_subsequent_program_audio"
                base["causal_departure_status"] = "not_eligible"
                excluded.append(
                    {
                        "break_index": index,
                        "recording_start_s": recording_start,
                        "recording_end_s": recording_end,
                        "reason": base["exclusion"],
                    }
                )
                for name in ("oracle_acoustic", "oracle_semantic", "oracle_speaker", "causal_acoustic", "causal_semantic", "causal_speaker"):
                    base.update(prefix_fields(empty_signal(), name))
                session_rows.append(base)
                continue

            oracle_stop = pod["end"] + min(30.0, program_tail)
            for name, snapshot, series_ends, resemble_low in (
                ("oracle_acoustic", acoustic_snapshot(acoustic, pod["start"], pods), acoustic["ends"], True),
                ("oracle_semantic", semantic_snapshot(semantic, pod["start"], pods), semantic["ends"], True),
            ):
                if isinstance(snapshot, str):
                    signal = empty_signal()
                    signal["reason"] = snapshot
                else:
                    distances, level = snapshot
                    signal = score_levels(series_ends, distances, level, pod["start"], pod["end"], program_tail, pods)
                    for t_feature, value, resembles in observe(series_ends, distances, level, pod["start"], oracle_stop, True):
                        timeline.append(
                            {
                                "kind": "sample",
                                "path": "oracle_start",
                                "signal": name.removeprefix("oracle_"),
                                "session": session,
                                "service": job["service"],
                                "break_index": index,
                                "t_feature": round(t_feature, 3),
                                "t_recording": round(t_feature + offset, 3),
                                "available_at_feature": round(t_feature, 3),
                                "value": round(value, 6),
                                "threshold": round(level, 6),
                                "resembles_program": resembles,
                                "gold_end_recording": round(recording_end, 3),
                            }
                        )
                base.update(prefix_fields(signal, name))

            ids = speaker_ids(speakers, pod["start"], pods)
            if isinstance(ids, str):
                signal = empty_signal()
                signal["reason"] = ids
            else:
                signal = score_speaker(speakers, ids, pod["start"], pod["end"], program_tail)
                flags = speaker_flags(speakers, ids)
                chosen = (speakers["times"] > pod["start"]) & (speakers["times"] <= oracle_stop)
                for sample in np.flatnonzero(chosen):
                    similarity = speakers["similarity"][sample]
                    timeline.append(
                        {
                            "kind": "sample",
                            "path": "oracle_start",
                            "signal": "speaker",
                            "session": session,
                            "service": job["service"],
                            "break_index": index,
                            "t_feature": round(float(speakers["times"][sample]), 3),
                            "t_recording": round(float(speakers["times"][sample]) + offset, 3),
                            "available_at_feature": round(float(speakers["times"][sample]), 3),
                            "value": None if not np.isfinite(similarity) else round(float(similarity), 6),
                            "threshold": MATCH_COSINE,
                            "resembles_program": bool(flags[sample]),
                            "frozen_speakers": ids,
                            "gold_end_recording": round(recording_end, 3),
                        }
                    )
            base.update(prefix_fields(signal, "oracle_speaker"))

            freeze, departure_status = qualifying_freeze(freezes, pod["start"], pods)
            base["causal_departure_status"] = departure_status
            if freeze is None:
                for name in ("causal_acoustic", "causal_semantic", "causal_speaker"):
                    signal = empty_signal()
                    signal["reason"] = "no_clean_departure_freeze"
                    base.update(prefix_fields(signal, name))
            else:
                trigger = float(freeze["trigger_s"])
                paired.add(trigger)
                base["causal_freeze_s"] = trigger
                base["causal_freeze_latency_s"] = trigger - pod["start"]
                causal_stop = pod["end"] + min(30.0, program_tail)
                for name, snapshot, series_ends in (
                    ("causal_acoustic", acoustic_snapshot(acoustic, trigger, pods), acoustic["ends"]),
                    ("causal_semantic", semantic_snapshot(semantic, trigger, pods), semantic["ends"]),
                ):
                    if isinstance(snapshot, str):
                        signal = empty_signal()
                        signal["reason"] = snapshot
                    else:
                        distances, level = snapshot
                        signal = score_levels(series_ends, distances, level, trigger, pod["end"], program_tail, pods)
                        for t_feature, value, resembles in observe(series_ends, distances, level, trigger, causal_stop, True):
                            timeline.append(
                                {
                                    "kind": "sample",
                                    "path": "causal_departure",
                                    "signal": name.removeprefix("causal_"),
                                    "session": session,
                                    "service": job["service"],
                                    "break_index": index,
                                    "t_feature": round(t_feature, 3),
                                    "t_recording": round(t_feature + offset, 3),
                                    "available_at_feature": round(t_feature, 3),
                                    "value": round(value, 6),
                                    "threshold": round(level, 6),
                                    "resembles_program": resembles,
                                    "departure_available_at_feature": round(trigger, 3),
                                    "gold_end_recording": round(recording_end, 3),
                                }
                            )
                    base.update(prefix_fields(signal, name))
                ids = speaker_ids(speakers, trigger, pods)
                if isinstance(ids, str):
                    signal = empty_signal()
                    signal["reason"] = ids
                else:
                    signal = score_speaker(speakers, ids, trigger, pod["end"], program_tail)
                    flags = speaker_flags(speakers, ids)
                    chosen = (speakers["times"] > trigger) & (speakers["times"] <= causal_stop)
                    for sample in np.flatnonzero(chosen):
                        similarity = speakers["similarity"][sample]
                        timeline.append(
                            {
                                "kind": "sample",
                                "path": "causal_departure",
                                "signal": "speaker",
                                "session": session,
                                "service": job["service"],
                                "break_index": index,
                                "t_feature": round(float(speakers["times"][sample]), 3),
                                "t_recording": round(float(speakers["times"][sample]) + offset, 3),
                                "available_at_feature": round(float(speakers["times"][sample]), 3),
                                "value": None if not np.isfinite(similarity) else round(float(similarity), 6),
                                "threshold": MATCH_COSINE,
                                "resembles_program": bool(flags[sample]),
                                "frozen_speakers": ids,
                                "departure_available_at_feature": round(trigger, 3),
                                "gold_end_recording": round(recording_end, 3),
                            }
                        )
                base.update(prefix_fields(signal, "causal_speaker"))
            session_rows.append(base)

        for row in session_rows:
            for path in ("oracle", "causal"):
                best = None
                which = ""
                if row["eligible"]:
                    for signal_name in ("acoustic", "semantic", "speaker"):
                        if not row.get(f"{path}_{signal_name}_available"):
                            continue
                        if row.get(f"{path}_{signal_name}_false_return"):
                            continue
                        latency = row.get(f"{path}_{signal_name}_operational_latency_s")
                        if latency is None:
                            continue
                        if best is None or latency < best:
                            best = latency
                            which = signal_name
                row[f"{path}_earliest_valid_return_s"] = best
                row[f"{path}_earliest_valid_signal"] = which
                row[f"{path}_earliest_is_not_a_combined_rule"] = True

        eligible = [row for row in session_rows if row["eligible"]]
        departure_rate = rate(
            [
                any(row.get(f"causal_{signal}_available") for signal in ("acoustic", "semantic", "speaker"))
                for row in eligible
            ]
        )
        service_rollups = {}
        supported = []
        for path in ("oracle", "causal"):
            service_rollups[path] = {}
            for signal in ("acoustic", "semantic", "speaker"):
                rollup = signal_rollup(eligible, f"{path}_{signal}")
                service_rollups[path][signal] = rollup
                if path == "causal" and rollup["meets_quick_rule"] and (departure_rate or 0) >= DEPARTURE_COVERAGE_MIN:
                    supported.append(signal)
        coverage["sessions"][session] = {
            "service": job["service"],
            "show": job["show"],
            "coverage_recording_s": list(job["coverage"]),
            "clock_offset_s": offset,
            "n_commercials": len(pods),
            "n_eligible": len(eligible),
            "n_excluded": len(excluded),
            "excluded": excluded,
            "program_seconds": round(
                program_seconds(job["coverage"][0] - offset, coverage_end, pods),
                3,
            ),
            "commercial_seconds": round(sum(pod["end"] - pod["start"] for pod in pods), 3),
            "causal_departure_rate": departure_rate,
            "causal_departure_meets_coverage": (departure_rate or 0) >= DEPARTURE_COVERAGE_MIN,
            "signals": service_rollups,
            "causal_signals_meeting_rule": supported,
            "published_false_departures": false_departure_cost(freezes, acoustic, pods, paired),
        }
        break_rows.extend(session_rows)

    fields: list[str] = []
    for row in break_rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with (OUT / "per_break_results.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in break_rows:
            writer.writerow({key: jsonable(row.get(key)) for key in fields})
    with (OUT / "timeline.jsonl").open("w", encoding="utf-8") as handle:
        for row in timeline:
            handle.write(json.dumps(jsonable(row), sort_keys=True) + "\n")

    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, check=True, capture_output=True, text=True).stdout.strip()
    receipts = {
        "experiment": "IDENTITY-RETURN-001",
        "git_head": head,
        "command": ".venv/bin/python experiments/measurement/identity_return_001.py",
        "holdouts_opened": False,
        "embeddings_recomputed": False,
        "thresholds_fit": False,
        "live_workers_modified": False,
        "configuration": coverage["decision_rule"],
        "inputs": {str(path.relative_to(REPO)): sha256(path) for path in inputs},
        "integrity": {
            "n_breaks": len(break_rows),
            "n_timeline_rows": len(timeline),
            "oracle_rows_labeled": True,
            "sessions": [job["session"] for job in SESSIONS],
            "holdouts_absent": all(job["session"] not in HOLDOUTS for job in SESSIONS),
            "acoustic_window_s": ACOUSTIC_WINDOW_S,
        },
    }
    coverage["receipt_git_head"] = head
    (OUT / "coverage_summary.json").write_text(json.dumps(jsonable(coverage), indent=2) + "\n", encoding="utf-8")
    receipts["outputs"] = {
        name: sha256(OUT / name)
        for name in ("per_break_results.csv", "timeline.jsonl", "coverage_summary.json")
    }
    (OUT / "receipts.json").write_text(json.dumps(receipts, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(jsonable({job["session"]: coverage["sessions"][job["session"]]["signals"] for job in SESSIONS}), indent=2))
    print("departures", {job["session"]: coverage["sessions"][job["session"]]["causal_departure_rate"] for job in SESSIONS})
    print("supported", {job["session"]: coverage["sessions"][job["session"]]["causal_signals_meeting_rule"] for job in SESSIONS})
    print("excluded", {job["session"]: coverage["sessions"][job["session"]]["excluded"] for job in SESSIONS})
    print("false_departures", {job["session"]: {k: coverage["sessions"][job["session"]]["published_false_departures"][k] for k in ("n_false_departures", "program_false_mute_s")} for job in SESSIONS})


if __name__ == "__main__":
    main()
