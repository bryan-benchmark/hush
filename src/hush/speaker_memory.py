"""Causal speaker memory for Experiment 002.

Constants below are exp002-v1. They were chosen before any labeled plot of
this experiment and are not to be revised against commercial labels.

At time t the match decision for an embedding window uses only prototypes
built from windows that ended earlier. The current window is folded into
memory after that decision.

Non-speech is not treated as evidence that program speakers are gone.
Fractions, entropy, turnover, and the continuity score use embedding windows
only. Silence leaves those scores empty.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

EXPERIMENT_SPEC_VERSION = "exp002-v1"
FEATURE_SCHEMA_VERSION = "exp002-speaker-v1"

SR = 16000
MIN_SPEECH_S = 1.0
EMBED_WIN_S = 2.0
EMBED_HOP_S = 1.0

# Silero get_speech_timestamps defaults. Not fit to this broadcast.
VAD_THRESHOLD = 0.5
VAD_MIN_SPEECH_MS = 250
VAD_MIN_SILENCE_MS = 100
VAD_SPEECH_PAD_MS = 30

# Published SpeechBrain verify_batch threshold for spkrec-ecapa-voxceleb.
MATCH_COSINE = 0.25

RECUR_MIN_APPEARANCES = 3
RECUR_MIN_SPAN_S = 60.0
RECUR_MIN_CUMULATIVE_S = 6.0
# A pause longer than this starts a new appearance. Shorter than a pod,
# longer than a breath. Not fit to labels.
APPEARANCE_GAP_S = 10.0

RETURN_ABSENCE_S = 30.0
RETURN_STRENGTH_SPEECH_S = 30.0
RETURN_STRENGTH_APPEARANCES = 5.0
RETURN_ABSENCE_SATURATE_S = 60.0

TIMELINE_STEP_S = 1.0
SPEECH_ACTIVE_MIN_S = 0.5
CONTINUITY_WINDOW_S = 15.0

# Unlabeled summary listing only. Not a mute rule.
EPISODE_BRIDGE_S = 5.0
DROP_WINDOW_S = 10.0
DROP_MIN = 0.35
EVENT_REFRACTORY_S = 45.0
RETURN_EVENT_MIN = 0.25

EMBEDDING_MODEL_ID = "speechbrain/spkrec-ecapa-voxceleb"
VAD_IMPL = "silero_vad.get_speech_timestamps"

PARAMS: dict = {
    "min_speech_s": MIN_SPEECH_S,
    "embed_win_s": EMBED_WIN_S,
    "embed_hop_s": EMBED_HOP_S,
    "vad_threshold": VAD_THRESHOLD,
    "vad_min_speech_ms": VAD_MIN_SPEECH_MS,
    "vad_min_silence_ms": VAD_MIN_SILENCE_MS,
    "vad_speech_pad_ms": VAD_SPEECH_PAD_MS,
    "match_cosine": MATCH_COSINE,
    "recur_min_appearances": RECUR_MIN_APPEARANCES,
    "recur_min_span_s": RECUR_MIN_SPAN_S,
    "recur_min_cumulative_s": RECUR_MIN_CUMULATIVE_S,
    "appearance_gap_s": APPEARANCE_GAP_S,
    "return_absence_s": RETURN_ABSENCE_S,
    "return_strength_speech_s": RETURN_STRENGTH_SPEECH_S,
    "return_strength_appearances": RETURN_STRENGTH_APPEARANCES,
    "return_absence_saturate_s": RETURN_ABSENCE_SATURATE_S,
    "timeline_step_s": TIMELINE_STEP_S,
    "speech_active_min_s": SPEECH_ACTIVE_MIN_S,
    "continuity_window_s": CONTINUITY_WINDOW_S,
    "episode_bridge_s": EPISODE_BRIDGE_S,
    "drop_window_s": DROP_WINDOW_S,
    "drop_min": DROP_MIN,
    "event_refractory_s": EVENT_REFRACTORY_S,
    "return_event_min": RETURN_EVENT_MIN,
    "match_rule": (
        "Assign the window to the existing prototype with the highest cosine "
        "if that cosine is >= match_cosine. Otherwise open a new cluster and "
        "mark the window NOVEL. The prototype is the L2-normalized sum of "
        "embeddings already assigned to the cluster, excluding this window."
    ),
    "recurring_rule": (
        "Before the current window is added, a cluster is RECURRING when it "
        "has at least 3 appearances, last_seen - first_seen is at least 60s, "
        "and attributed speech is at least 6s. The current window cannot make "
        "itself recurring."
    ),
    "appearance_rule": (
        "occurrence_count starts at 1. It increments when "
        "window_start - previous last_seen is greater than 10s."
    ),
    "cumulative_speech_rule": (
        "Attributed speech adds only newly covered seconds. A later overlapping "
        "window of the same cluster does not count the shared span twice."
    ),
    "continuity_score": (
        "Mean, over embedding windows with window_end in (t-15s, t], of "
        "speaker_is_recurring multiplied by cosine similarity to the best "
        "existing prototype. Null when no embedding window completed in that "
        "span. Silence is not in the denominator."
    ),
    "return_score": (
        "On a window that matches a cluster already RECURRING, with "
        "window_start - last_seen >= 30s: similarity * strength * absence_factor. "
        "strength = min(1, cumulative_speech/30) * min(1, occurrence_count/5), "
        "using the cluster state before this window. "
        "absence_factor = min(1, absence/60). Otherwise 0. "
        "The timeline second keeps the max of windows that ended during it."
    ),
    "fraction_denominator": (
        "Trailing fractions use embedding windows whose window_end lies in "
        "(t-W, t]. Seconds with no completed window are omitted, so crowd "
        "noise and silence do not count as lost speakers."
    ),
    "turnover_rate_30s": (
        "Number of assigned-cluster changes between successive embedding "
        "windows that ended inside (t-30s, t]. A count per trailing 30s, not "
        "a per-second rate."
    ),
    "vad_lookahead": (
        "Silero confirms a speech end after 100ms of silence and pads 30ms. "
        "That hangover is internal to the segmenter. Cluster memory never "
        "sees a window that has not ended."
    ),
}


def _unit(vec: np.ndarray) -> np.ndarray:
    arr = np.asarray(vec, dtype=np.float64)
    norm = float(np.linalg.norm(arr))
    if not math.isfinite(norm) or norm < 1e-6:
        raise ValueError("embedding has no usable magnitude")
    return arr / norm


def _is_recurring(occurrence_count: int, first_seen: float, last_seen: float, cumulative_s: float) -> bool:
    span = last_seen - first_seen
    return (
        occurrence_count >= RECUR_MIN_APPEARANCES
        and span >= RECUR_MIN_SPAN_S
        and cumulative_s >= RECUR_MIN_CUMULATIVE_S
    )


@dataclass
class _Cluster:
    cluster_id: str
    proto: np.ndarray
    n_emb: int
    cum_s: float
    first_seen: float
    last_seen: float
    occurrence_count: int


@dataclass
class OnlineSpeakerMemory:
    """Online clusters. observe() is causal in window end time."""

    clusters: list[_Cluster] = field(default_factory=list)
    _next_id: int = 1

    def observe(self, embedding: np.ndarray, window_start: float, window_end: float) -> dict:
        emb = _unit(embedding)
        duration = float(window_end - window_start)
        if duration <= 0:
            raise ValueError("window duration must be positive")

        if not self.clusters:
            opened = self._open(emb, window_start, window_end, duration)
            return self._novel(window_start, window_end, duration, None, None, opened)

        sims = [float(np.dot(emb, cluster.proto)) for cluster in self.clusters]
        best_i = int(np.argmax(sims))
        best_sim = sims[best_i]
        recur_sims = [
            sim
            for sim, cluster in zip(sims, self.clusters)
            if _is_recurring(cluster.occurrence_count, cluster.first_seen, cluster.last_seen, cluster.cum_s)
        ]
        best_recur = max(recur_sims) if recur_sims else None

        if best_sim < MATCH_COSINE:
            opened = self._open(emb, window_start, window_end, duration)
            return self._novel(window_start, window_end, duration, best_sim, best_recur, opened)

        cluster = self.clusters[best_i]
        recurring = _is_recurring(cluster.occurrence_count, cluster.first_seen, cluster.last_seen, cluster.cum_s)
        absence = float(window_start - cluster.last_seen)
        age = float(window_end - cluster.first_seen)
        before_cum = cluster.cum_s
        before_occ = cluster.occurrence_count
        if recurring and absence >= RETURN_ABSENCE_S:
            strength = min(1.0, before_cum / RETURN_STRENGTH_SPEECH_S) * min(
                1.0, before_occ / RETURN_STRENGTH_APPEARANCES
            )
            absence_factor = min(1.0, absence / RETURN_ABSENCE_SATURATE_S)
            return_score = float(best_sim * strength * absence_factor)
        else:
            return_score = 0.0
        self._update(cluster, emb, window_start, window_end, duration)
        return {
            "window_start": float(window_start),
            "window_end": float(window_end),
            "duration": duration,
            "match_decision": "MATCH",
            "assigned_cluster_id": cluster.cluster_id,
            "matched_cluster_id": cluster.cluster_id,
            "similarity_to_best_known": best_sim,
            "similarity_to_best_recurring": best_recur,
            "speaker_is_novel": False,
            "speaker_is_recurring": recurring,
            "cluster_age_seconds": age,
            "cluster_last_seen_seconds": absence,
            "cluster_cumulative_speech_seconds": before_cum,
            "cluster_occurrence_count": before_occ,
            "program_speaker_return_score": return_score,
            "cum_after": cluster.cum_s,
            "occ_after": cluster.occurrence_count,
            "first_seen": cluster.first_seen,
            "last_seen_after": cluster.last_seen,
            "recurring_after": _is_recurring(
                cluster.occurrence_count, cluster.first_seen, cluster.last_seen, cluster.cum_s
            ),
        }

    def _open(self, emb: np.ndarray, window_start: float, window_end: float, duration: float) -> _Cluster:
        cluster = _Cluster(
            cluster_id=f"c{self._next_id:04d}",
            proto=emb.copy(),
            n_emb=1,
            cum_s=duration,
            first_seen=float(window_start),
            last_seen=float(window_end),
            occurrence_count=1,
        )
        self._next_id += 1
        self.clusters.append(cluster)
        return cluster

    def _update(self, cluster: _Cluster, emb: np.ndarray, window_start: float, window_end: float, duration: float) -> None:
        if window_start - cluster.last_seen > APPEARANCE_GAP_S:
            cluster.occurrence_count += 1
        if window_start < cluster.last_seen:
            added = max(0.0, float(window_end - cluster.last_seen))
        else:
            added = duration
        cluster.cum_s += added
        cluster.proto = _unit(cluster.proto * cluster.n_emb + emb)
        cluster.n_emb += 1
        cluster.last_seen = float(window_end)

    def _novel(
        self,
        window_start: float,
        window_end: float,
        duration: float,
        best_sim: float | None,
        best_recur: float | None,
        opened: _Cluster,
    ) -> dict:
        return {
            "window_start": float(window_start),
            "window_end": float(window_end),
            "duration": duration,
            "match_decision": "NOVEL",
            "assigned_cluster_id": opened.cluster_id,
            "matched_cluster_id": "NOVEL",
            "similarity_to_best_known": best_sim,
            "similarity_to_best_recurring": best_recur,
            "speaker_is_novel": True,
            "speaker_is_recurring": False,
            "cluster_age_seconds": 0.0,
            "cluster_last_seen_seconds": None,
            "cluster_cumulative_speech_seconds": None,
            "cluster_occurrence_count": None,
            "program_speaker_return_score": 0.0,
            "cum_after": opened.cum_s,
            "occ_after": opened.occurrence_count,
            "first_seen": opened.first_seen,
            "last_seen_after": opened.last_seen,
            "recurring_after": False,
        }


def round_ms(value: float) -> float:
    return round(float(value), 3)


def merge_regions(regions: list[tuple[float, float]]) -> list[tuple[float, float]]:
    ordered = sorted((round_ms(s), round_ms(e)) for s, e in regions if e > s)
    merged: list[list[float]] = []
    for start, end in ordered:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(s, e) for s, e in merged if e - s >= MIN_SPEECH_S]


def embedding_windows(regions: list[tuple[float, float]]) -> list[tuple[float, float]]:
    windows: list[tuple[float, float]] = []
    for start, end in regions:
        cursor = start
        while cursor + MIN_SPEECH_S <= end + 1e-9:
            stop = min(cursor + EMBED_WIN_S, end)
            if stop - cursor + 1e-9 >= MIN_SPEECH_S:
                windows.append((round_ms(cursor), round_ms(stop)))
            cursor = round_ms(cursor + EMBED_HOP_S)
            if cursor >= end:
                break
    windows.sort(key=lambda item: (item[1], item[0]))
    return windows


def _speech_bins(regions: list[tuple[float, float]], n_seconds: int) -> np.ndarray:
    covered = np.zeros(n_seconds, dtype=np.float64)
    for start, end in regions:
        i0 = max(0, int(math.floor(start)))
        i1 = min(n_seconds, int(math.ceil(end)))
        for i in range(i0, i1):
            covered[i] += max(0.0, min(end, i + 1.0) - max(start, float(i)))
    return covered


def _window_slice(ends: np.ndarray, t: float, span: float) -> tuple[int, int]:
    hi = int(np.searchsorted(ends, t, side="right"))
    lo = int(np.searchsorted(ends, t - span, side="right"))
    return lo, hi


def _entropy(ids: list[str]) -> float | None:
    if not ids:
        return None
    _, counts = np.unique(np.asarray(ids), return_counts=True)
    prob = counts.astype(np.float64) / float(counts.sum())
    return float(-(prob * np.log2(prob)).sum())


def build_timeline(
    regions: list[tuple[float, float]],
    windows: list[dict],
    t_end: float,
) -> dict[str, np.ndarray]:
    """One row per second. timestamp t describes (t-1, t]."""
    n_seconds = int(math.floor(t_end / TIMELINE_STEP_S))
    timestamps = np.arange(1, n_seconds + 1, dtype=np.float64)
    covered = _speech_bins(regions, n_seconds)
    speech_active = (covered >= SPEECH_ACTIVE_MIN_S).astype(np.int64)

    ends = np.asarray([w["window_end"] for w in windows], dtype=np.float64) if windows else np.zeros(0)
    if ends.size and np.any(np.diff(ends) < -1e-9):
        raise ValueError("windows must be sorted by window_end")

    n = n_seconds
    state_labels = np.asarray(["NO_SPEECH"] * n, dtype=object)
    cluster_id = np.asarray([None] * n, dtype=object)
    match_id = np.asarray([None] * n, dtype=object)
    sim_known = np.full(n, np.nan)
    sim_recur = np.full(n, np.nan)
    is_novel = np.zeros(n, dtype=np.int64)
    is_recur = np.zeros(n, dtype=np.int64)
    absent = np.zeros(n, dtype=np.int64)
    since_recur = np.full(n, np.nan)
    since_dom = np.full(n, np.nan)
    dom_id = np.asarray([None] * n, dtype=object)
    frac5 = np.full(n, np.nan)
    frac15 = np.full(n, np.nan)
    frac30 = np.full(n, np.nan)
    novel15 = np.full(n, np.nan)
    novel30 = np.full(n, np.nan)
    unique30 = np.zeros(n, dtype=np.int64)
    entropy30 = np.full(n, np.nan)
    turnover30 = np.zeros(n, dtype=np.int64)
    continuity = np.full(n, np.nan)
    return_score = np.zeros(n, dtype=np.float64)
    age = np.full(n, np.nan)
    last_seen = np.full(n, np.nan)
    cum_before = np.full(n, np.nan)
    occ_before = np.full(n, np.nan)

    folded: dict[str, dict] = {}
    last_recurring_end: float | None = None
    applied = 0

    for i, t in enumerate(timestamps):
        while applied < len(windows) and windows[applied]["window_end"] <= t + 1e-9:
            row = windows[applied]
            folded[row["assigned_cluster_id"]] = {
                "cum": row["cum_after"],
                "last": row["last_seen_after"],
                "first": row["first_seen"],
                "recurring": row["recurring_after"],
            }
            if row["speaker_is_recurring"]:
                last_recurring_end = row["window_end"]
            applied += 1

        lo, hi = _window_slice(ends, float(t), TIMELINE_STEP_S) if ends.size else (0, 0)
        if hi > lo:
            row = windows[hi - 1]
            if row["speaker_is_recurring"]:
                state_labels[i] = "SPEECH_RECURRING"
            elif row["speaker_is_novel"]:
                state_labels[i] = "SPEECH_NOVEL"
            else:
                state_labels[i] = "SPEECH_KNOWN_NOT_RECURRING"
            cluster_id[i] = row["assigned_cluster_id"]
            match_id[i] = row["matched_cluster_id"]
            if row["similarity_to_best_known"] is not None:
                sim_known[i] = row["similarity_to_best_known"]
            if row["similarity_to_best_recurring"] is not None:
                sim_recur[i] = row["similarity_to_best_recurring"]
            is_novel[i] = int(row["speaker_is_novel"])
            is_recur[i] = int(row["speaker_is_recurring"])
            absent[i] = int(not row["speaker_is_recurring"])
            age[i] = row["cluster_age_seconds"]
            if row["cluster_last_seen_seconds"] is not None:
                last_seen[i] = row["cluster_last_seen_seconds"]
            if row["cluster_cumulative_speech_seconds"] is not None:
                cum_before[i] = row["cluster_cumulative_speech_seconds"]
            if row["cluster_occurrence_count"] is not None:
                occ_before[i] = row["cluster_occurrence_count"]
            return_score[i] = max(w["program_speaker_return_score"] for w in windows[lo:hi])
        elif speech_active[i]:
            state_labels[i] = "SPEECH_PENDING"

        if last_recurring_end is not None:
            since_recur[i] = float(t - last_recurring_end)

        recurring_now = [cid for cid, st in folded.items() if st["recurring"]]
        if recurring_now:
            dom = max(recurring_now, key=lambda cid: (folded[cid]["cum"], -folded[cid]["first"], cid))
            dom_id[i] = dom
            since_dom[i] = float(t - folded[dom]["last"])

        if ends.size:
            for span, frac_out, novel_out in (
                (5.0, frac5, None),
                (15.0, frac15, novel15),
                (30.0, frac30, novel30),
            ):
                a, b = _window_slice(ends, float(t), span)
                if b > a:
                    chunk = windows[a:b]
                    n_win = len(chunk)
                    frac_out[i] = sum(int(w["speaker_is_recurring"]) for w in chunk) / n_win
                    if novel_out is not None:
                        novel_out[i] = sum(int(w["speaker_is_novel"]) for w in chunk) / n_win
            a30, b30 = _window_slice(ends, float(t), 30.0)
            if b30 > a30:
                ids = [w["assigned_cluster_id"] for w in windows[a30:b30]]
                unique30[i] = len(set(ids))
                entropy30[i] = _entropy(ids)
                turnover30[i] = sum(ids[k] != ids[k - 1] for k in range(1, len(ids)))

    if ends.size:
        for i, t in enumerate(timestamps):
            a, b = _window_slice(ends, float(t), CONTINUITY_WINDOW_S)
            if b > a:
                continuity[i] = float(
                    np.mean(
                        [
                            (w["similarity_to_best_known"] or 0.0) if w["speaker_is_recurring"] else 0.0
                            for w in windows[a:b]
                        ]
                    )
                )

    return {
        "timestamp_seconds": timestamps,
        "speech_active": speech_active,
        "speech_seconds_in_bin": covered,
        "speech_state": state_labels,
        "speaker_cluster_id": cluster_id,
        "matched_cluster_id": match_id,
        "speaker_similarity_to_best_known": sim_known,
        "speaker_similarity_to_best_recurring": sim_recur,
        "speaker_is_novel": is_novel,
        "speaker_is_recurring": is_recur,
        "speech_but_program_speakers_absent": absent,
        "seconds_since_any_recurring_speaker": since_recur,
        "seconds_since_dominant_recurring_speaker": since_dom,
        "dominant_recurring_cluster_id": dom_id,
        "recent_recurring_speaker_fraction_5s": frac5,
        "recent_recurring_speaker_fraction_15s": frac15,
        "recent_recurring_speaker_fraction_30s": frac30,
        "novel_speaker_fraction_15s": novel15,
        "novel_speaker_fraction_30s": novel30,
        "unique_speaker_clusters_30s": unique30,
        "speaker_cluster_entropy_30s": entropy30,
        "speaker_turnover_rate_30s": turnover30,
        "program_speaker_continuity_score": continuity,
        "program_speaker_return_score": return_score,
        "cluster_age_seconds": age,
        "cluster_last_seen_seconds": last_seen,
        "cluster_cumulative_speech_seconds": cum_before,
        "cluster_occurrence_count": occ_before,
    }


def speech_without_recurring_episodes(states: list[str], bridge_s: float = EPISODE_BRIDGE_S, limit: int = 15) -> list[dict]:
    absent = {"SPEECH_NOVEL", "SPEECH_KNOWN_NOT_RECURRING"}
    blocking = {"SPEECH_RECURRING"}
    episodes: list[dict] = []
    i = 0
    n = len(states)
    while i < n:
        if states[i] not in absent:
            i += 1
            continue
        last_absent = i
        j = i + 1
        while j < n:
            if states[j] in blocking:
                break
            if states[j] in absent:
                last_absent = j
                j += 1
                continue
            k = j
            while k < n and states[k] not in absent and states[k] not in blocking:
                k += 1
            if k < n and states[k] in absent and (k - j) <= bridge_s:
                j = k
                continue
            break
        speech_bins = sum(1 for t in range(i, last_absent + 1) if states[t] in absent)
        episodes.append(
            {
                "start_seconds": float(i),
                "end_seconds": float(last_absent + 1),
                "span_seconds": float(last_absent + 1 - i),
                "speech_without_recurring_seconds": int(speech_bins),
            }
        )
        i = last_absent + 1
    episodes.sort(key=lambda row: (-row["span_seconds"], row["start_seconds"]))
    return episodes[:limit]


def top_events(times: np.ndarray, values: np.ndarray, min_value: float, refractory_s: float, limit: int) -> list[dict]:
    order = np.lexsort((times, -values))
    kept: list[tuple[float, float]] = []
    for idx in order:
        value = float(values[idx])
        if not math.isfinite(value) or value < min_value:
            continue
        t = float(times[idx])
        if any(abs(t - prev) <= refractory_s for prev, _ in kept):
            continue
        kept.append((t, value))
        if len(kept) >= limit:
            break
    kept.sort()
    return [{"timestamp_seconds": t, "value": v} for t, v in kept]


def continuity_drops(timeline: dict[str, np.ndarray], limit: int = 20) -> list[dict]:
    times = timeline["timestamp_seconds"]
    score = timeline["program_speaker_continuity_score"]
    drops = np.full(len(times), np.nan)
    window = int(DROP_WINDOW_S)
    for i in range(len(times)):
        if i == 0 or not math.isfinite(float(score[i])):
            continue
        prev = score[max(0, i - window) : i]
        finite = prev[np.isfinite(prev)]
        if finite.size == 0:
            continue
        drops[i] = float(np.max(finite) - score[i])
    events = top_events(times, drops, DROP_MIN, EVENT_REFRACTORY_S, limit)
    for event in events:
        i = int(event["timestamp_seconds"]) - 1
        event["continuity"] = None if not math.isfinite(float(score[i])) else float(score[i])
        event["drop"] = event.pop("value")
    return events


def return_events(timeline: dict[str, np.ndarray], limit: int = 20) -> list[dict]:
    events = top_events(
        timeline["timestamp_seconds"],
        timeline["program_speaker_return_score"],
        RETURN_EVENT_MIN,
        EVENT_REFRACTORY_S,
        limit,
    )
    clusters = timeline["speaker_cluster_id"]
    for event in events:
        i = int(event["timestamp_seconds"]) - 1
        event["return_score"] = event.pop("value")
        event["cluster_id"] = clusters[i]
    return events


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    return float(np.percentile(np.asarray(values, dtype=np.float64), q))


def unlabeled_summary(regions: list[tuple[float, float]], windows: list[dict], timeline: dict[str, np.ndarray]) -> dict:
    attributed = 0.0
    causal_recurring = 0.0
    novel_duration = 0.0
    match_sims: list[float] = []
    novel_sims: list[float] = []
    final: dict[str, dict] = {}
    for row in windows:
        previous_n = final.get(row["assigned_cluster_id"], {}).get("n_windows", 0)
        final[row["assigned_cluster_id"]] = {
            "cluster_id": row["assigned_cluster_id"],
            "cumulative_speech_seconds": row["cum_after"],
            "occurrence_count": row["occ_after"],
            "first_seen": row["first_seen"],
            "last_seen": row["last_seen_after"],
            "recurring": bool(row["recurring_after"]),
            "n_windows": previous_n + 1,
        }
        added = _added_speech(row)
        if row["speaker_is_recurring"]:
            causal_recurring += added
        if row["speaker_is_novel"]:
            novel_duration += row["duration"]
        attributed += added
        sim = row["similarity_to_best_known"]
        if sim is not None:
            if row["speaker_is_novel"]:
                novel_sims.append(float(sim))
            else:
                match_sims.append(float(sim))

    recurring_clusters = [c for c in final.values() if c["recurring"]]
    recurring_clusters.sort(key=lambda c: (-c["cumulative_speech_seconds"], c["cluster_id"]))
    end_recurring_speech = sum(c["cumulative_speech_seconds"] for c in recurring_clusters)
    total_cluster_speech = sum(c["cumulative_speech_seconds"] for c in final.values())
    states = [str(s) for s in timeline["speech_state"]]
    continuity = timeline["program_speaker_continuity_score"]
    finite_cont = continuity[np.isfinite(continuity)]
    speech_bins = int(np.sum(timeline["speech_active"]))
    return {
        "experiment_spec_version": EXPERIMENT_SPEC_VERSION,
        "truth_ledger_read": False,
        "n_speech_regions": len(regions),
        "speech_region_seconds": float(sum(e - s for s, e in regions)),
        "speech_active_seconds": speech_bins,
        "speech_active_fraction": float(speech_bins / max(1, len(timeline["timestamp_seconds"]))),
        "n_embedding_windows": len(windows),
        "n_clusters": len(final),
        "n_recurring_clusters": len(recurring_clusters),
        "novel_window_fraction": float(sum(int(w["speaker_is_novel"]) for w in windows) / len(windows)) if windows else None,
        "causal_fraction_of_attributed_speech_on_already_recurring": (
            None if attributed <= 0 else float(causal_recurring / attributed)
        ),
        "end_state_fraction_of_speech_in_recurring_clusters": (
            None if total_cluster_speech <= 0 else float(end_recurring_speech / total_cluster_speech)
        ),
        "end_state_note": (
            "end_state_fraction labels a cluster by whether it eventually recurred. "
            "It is descriptive. Causal scores never use that future status."
        ),
        "novel_window_duration_seconds": novel_duration,
        "attributed_speech_seconds": attributed,
        "top_recurring_clusters": [
            {
                "cluster_id": c["cluster_id"],
                "cumulative_speech_seconds": c["cumulative_speech_seconds"],
                "occurrence_count": c["occurrence_count"],
                "first_seen": c["first_seen"],
                "last_seen": c["last_seen"],
                "n_windows": c["n_windows"],
            }
            for c in recurring_clusters[:12]
        ],
        "longest_speech_without_recurring": speech_without_recurring_episodes(states),
        "largest_continuity_drops": continuity_drops(timeline),
        "strongest_return_events": return_events(timeline),
        "similarity_when_matched": {
            "p10": _percentile(match_sims, 10),
            "p50": _percentile(match_sims, 50),
            "p90": _percentile(match_sims, 90),
        },
        "similarity_when_novel": {
            "p50": _percentile(novel_sims, 50),
            "p90": _percentile(novel_sims, 90),
            "max": max(novel_sims) if novel_sims else None,
        },
        "continuity_when_defined": {
            "n": int(finite_cont.size),
            "p50": None if finite_cont.size == 0 else float(np.percentile(finite_cont, 50)),
            "p90": None if finite_cont.size == 0 else float(np.percentile(finite_cont, 90)),
        },
        "first_recurring_window_end": next(
            (row["window_end"] for row in windows if row["speaker_is_recurring"]),
            None,
        ),
    }


def _added_speech(row: dict) -> float:
    """Seconds this window added to its cluster, from the before/after cumulative."""
    if row["match_decision"] == "NOVEL":
        return float(row["duration"])
    before = row["cluster_cumulative_speech_seconds"]
    if before is None:
        return float(row["duration"])
    return max(0.0, float(row["cum_after"]) - float(before))
