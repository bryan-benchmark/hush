"""Case file for the frozen NFL75 mean. Does not retune or touch the live booth.

    python -m experiments.nfl75.forensics_main
"""

from __future__ import annotations

import bisect
import json
from pathlib import Path

import numpy as np

from experiments.nfl75.forensics import MATCH, assign_cause
from experiments.nfl75.mean import rolling_means
from experiments.nfl75.persist import _logits, nbc_lines
from experiments.nfl75.promo_class import load_overlay

REPO = Path(__file__).resolve().parents[2]
RESEARCH = REPO / "docs" / "ohush" / "research"
MEAN = RESEARCH / "NFL75_MEAN_001" / "results.json"
BOOTH = RESEARCH / "NFL75_BOOTH_HOLD_001" / "results.json"
PROTECT = RESEARCH / "NFL75_PROTECT_001"
OVERLAY_DIR = RESEARCH / "NFL75_PROMO_CLASS_001"
ASR = RESEARCH / "NFL75_BROADCAST_OPPORTUNITY_001" / "asr_chunks.jsonl"
EVENTS = RESEARCH / "NFL_EVENT_ENGINE_001" / "football_events.jsonl"
OUT = RESEARCH / "OHUSH_FAILURE_FORENSICS_001"
POLICIES = ("unprotected", "hold_1")
CLOCKS = ("oracle", "actual")
_EPS = 1e-6


def _round(value, places: int):
    if value is None:
        return None
    if isinstance(value, float) and value != value:
        return None
    return round(float(value), places)


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def _load_jsonl(path: Path) -> list[dict]:
    rows = []
    if not path.is_file():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


class SpeakerTape:
    def __init__(self, path: Path, names: list[str]):
        bundle = np.load(path)
        self.starts = np.asarray(bundle["start"], dtype=np.float64)
        self.ends = np.asarray(bundle["end"], dtype=np.float64)
        self.cosine = np.asarray(bundle["cosine"], dtype=np.float64)
        self.people = np.asarray(bundle["people"], dtype=np.float64)
        self.names = list(names)
        self.missing = [
            "raw VAD region times were not saved; only ECAPA windows that were embedded",
            "live booth similarity at 0.55 was not measured on these tapes",
            "no human named the speaker of each window",
        ]

    def peak(self, t0: float, t1: float) -> tuple[float | None, str | None, int]:
        hi = int(bisect.bisect_right(self.ends, t1 + 1e-9))
        lo = int(bisect.bisect_right(self.ends, t0 + 1e-9))
        best = None
        name = None
        count = 0
        for index in range(lo, hi):
            count += 1
            value = float(self.cosine[index])
            if value != value:
                continue
            if best is None or value > best:
                best = value
                name = self._name(index)
        return best, name, count

    def covering(self, moment: float) -> tuple[float | None, str | None, bool]:
        best = None
        name = None
        open_ = False
        for index, (start, end) in enumerate(zip(self.starts, self.ends)):
            if float(start) <= moment < float(end):
                open_ = True
                value = float(self.cosine[index])
                if value != value:
                    continue
                if best is None or value > best:
                    best = value
                    name = self._name(index)
        return best, name, open_

    def _name(self, index: int) -> str | None:
        row = self.people[index]
        if not np.isfinite(row).any():
            return None
        return self.names[int(np.nanargmax(row))]

    def commercial_seconds(self, breaks: list[dict], line: float) -> float:
        total = 0.0
        cursor = 0
        order = np.argsort(self.starts)
        for row in breaks:
            t = float(row["start_s"])
            end = float(row["end_s"])
            while t < end - _EPS:
                step = min(1.0, end - t)
                mid = t + step / 2.0
                while cursor < len(order) and float(self.ends[order[cursor]]) <= mid:
                    cursor += 1
                hit = False
                probe = cursor
                while probe < len(order) and float(self.starts[order[probe]]) <= mid:
                    index = int(order[probe])
                    if float(self.ends[index]) > mid:
                        value = float(self.cosine[index])
                        if value == value and value + _EPS >= line:
                            hit = True
                            break
                    probe += 1
                if hit:
                    total += step
                t += step
        return total


class ScoreTape:
    def __init__(self, times, scores, means):
        self.times = [float(item) for item in times]
        self.scores = [float(item) for item in scores]
        self.means = [None if item is None else float(item) for item in means]

    def at(self, moment: float) -> tuple[float | None, float | None]:
        index = bisect.bisect_left(self.times, moment - 1e-6)
        if index >= len(self.times) or abs(self.times[index] - moment) > 0.6:
            if index and abs(self.times[index - 1] - moment) <= 0.6:
                index -= 1
            else:
                return None, None
        return self.means[index], self.scores[index]

    def crossed(self, t0: float, t1: float, line: float) -> bool:
        for moment, mean in zip(self.times, self.means):
            if moment < t0:
                continue
            if moment >= t1:
                break
            if mean is not None and mean >= line:
                return True
        return False

    def stayed_hot(self, t0: float, t1: float) -> bool:
        """True when the raw score never holds at or below zero for three seconds."""
        cold = 0.0
        previous = None
        for moment, score in zip(self.times, self.scores):
            if moment < t0:
                continue
            if moment > t1 + _EPS:
                break
            dt = 0.0 if previous is None else moment - previous
            previous = moment
            if score <= 0.0:
                cold += dt
                if cold + _EPS >= 3.0:
                    return False
            else:
                cold = 0.0
        return True


def _hearing(session: str) -> list[dict]:
    categories = json.loads((PROTECT / "categories.json").read_text(encoding="utf-8"))
    rows = []
    for row in _load_jsonl(PROTECT / "transcripts.jsonl"):
        if row["session"] != session:
            continue
        row = dict(row)
        row["category"] = categories[session][str(row["episode"])]
        rows.append(row)
    return rows


def _best_hear(hearing: list[dict], start: float, end: float) -> dict | None:
    best = None
    amount = 0.0
    for row in hearing:
        overlap = _overlap(start, end, float(row["start_s"]), float(row["end_s"]))
        if overlap > amount:
            amount = overlap
            best = row
    if best is None or amount < 0.5:
        return None
    return best


def _overlay_class(spans: list[dict], start: float, end: float) -> str | None:
    best = None
    amount = 0.0
    for row in spans:
        overlap = _overlap(start, end, float(row["start_s"]), float(row["end_s"]))
        if overlap > amount:
            amount = overlap
            best = row["overlay_class"]
    if amount < 0.5:
        return None
    return best


def _text(chunks: list[dict], start: float, end: float) -> str:
    parts = []
    for row in chunks:
        if _overlap(start, end, float(row["t0"]), float(row["t1"])) <= 0:
            continue
        text = " ".join(str(row.get("text") or "").split())
        if text:
            parts.append(text)
    blob = " ".join(parts)
    return blob[:420]


def _events(rows: list[dict], start: float, end: float) -> dict:
    kinds: dict[str, int] = {}
    for row in rows:
        if _overlap(start, end, float(row["audio_t"]), float(row.get("heard_until") or row["audio_t"])) <= 0:
            continue
        kinds[row["kind"]] = kinds.get(row["kind"], 0) + 1
    return {
        "count": sum(kinds.values()),
        "kinds": kinds,
        "used_by_this_candidate": False,
    }


def _role(start: float, end: float, breaks: list[dict]) -> str:
    for row in breaks:
        if abs(start - float(row["end_s"])) <= 1.0:
            return "return"
    for row in breaks:
        if abs(end - float(row["start_s"])) <= 5.0:
            return "pre_break"
    return "in_program"


def _timeline(speaker: SpeakerTape, scores: ScoreTape, start: float) -> list[dict]:
    points = []
    for offset in (-20, -10, -5, -1, 0, 5, 10, 20):
        moment = start + offset
        if moment < 0:
            continue
        mean, score = scores.at(moment)
        fresh, name, windows = speaker.peak(moment - 1.0, moment)
        _cover, _cover_name, open_ = speaker.covering(moment)
        points.append(
            {
                "t": _round(moment, 3),
                "offset_s": offset,
                "mean": _round(mean, 4),
                "score": _round(score, 4),
                "fresh_cosine": _round(fresh, 4),
                "fresh_name": name,
                "windows_ended": windows,
                "speech_window_open": open_,
            }
        )
    return points


def _episode_row(
    session: str,
    policy: str,
    clock: str,
    episode: dict,
    speaker: SpeakerTape,
    scores: ScoreTape,
    hearing: list[dict],
    spans: list[dict],
    chunks: list[dict],
    events: list[dict],
    breaks: list[dict],
    line: float,
) -> dict:
    start = float(episode["start_s"])
    end = float(episode["end_s"])
    heard = _best_hear(hearing, start, end)
    fresh, fresh_name, fresh_n = speaker.peak(start - 1.0, start)
    max_in, max_name, windows = speaker.peak(start, end)
    prior5, _prior5_name, prior5_n = speaker.peak(start - 5.0, start)
    prior20, prior20_name, prior20_n = speaker.peak(start - 20.0, start)
    mean, score = scores.at(start)
    overlay = _overlay_class(spans, start, end)
    category = None if heard is None else heard["category"]
    opening_only = bool(heard and float(episode["duration_s"]) > float(heard.get("clip_s") or 20) + 0.2)
    cause = assign_cause(
        {
            "kind": "false_mute",
            "overlay": overlay,
            "category": category,
            "fresh": fresh,
            "fresh_name": fresh_name,
            "max_in_episode": max_in,
            "max_prior_5": prior5,
            "speech_windows_in_episode": windows,
            "policy_reads_speaker": policy == "hold_1",
            "listen_is_opening_only": opening_only,
        }
    )
    if overlay == "mixed_mention":
        cause["contributing"] = cause["contributing"] + ["sponsor_line_shares_the_span"]
    if policy == "hold_1" and prior5 is not None and prior5 >= MATCH:
        cause["contributing"] = cause["contributing"] + ["one_second_hold_had_a_match_just_before_this_open"]
    clip = None if heard is None else str(heard.get("wav") or "")
    return {
        "candidate": "NFL75_MEAN_001",
        "session": session,
        "policy": policy,
        "clock": clock,
        "kind": "false_mute",
        "role": _role(start, end, breaks),
        "start_s": _round(start, 3),
        "end_s": _round(end, 3),
        "duration_s": _round(float(episode["duration_s"]), 3),
        "clip": clip or None,
        "gold": "program",
        "listen_category": category,
        "listen_opening_only": opening_only,
        "overlay": overlay,
        "transcript": (None if heard is None else heard.get("transcript")),
        "asr_context": _text(chunks, start - 20.0, min(end, start + 20.0)),
        "football_events": _events(events, start - 20.0, end + 20.0),
        "speaker": {
            "model": "speechbrain/spkrec-ecapa-voxceleb",
            "line": MATCH,
            "line_is": "research cosine, not the live 0.55 booth match",
            "fresh_cosine": _round(fresh, 4),
            "fresh_name": fresh_name,
            "windows_ended_in_last_second": fresh_n,
            "max_cosine_in_episode": _round(max_in, 4),
            "max_name_in_episode": max_name,
            "speech_windows_in_episode": windows,
            "max_cosine_prior_5s": _round(prior5, 4),
            "windows_prior_5s": prior5_n,
            "max_cosine_prior_20s": _round(prior20, 4),
            "max_name_prior_20s": prior20_name,
            "windows_prior_20s": prior20_n,
            "human_speaker_name": None,
        },
        "classifier": {
            "what": "10-second mean of the NBC logistic decision function",
            "mean_at_start": _round(mean, 4),
            "score_at_start": _round(score, 4),
            "start_line": line,
            "hot": mean is not None and mean >= line,
            "attribution": "no per-sound class was saved; the number is the only classifier evidence",
        },
        "state": {
            "machine": "covers_from_mean" if policy == "unprotected" else "covers_protected hold 1s",
            "open_condition": (
                "10-second mean at or above the frozen line"
                if policy == "unprotected"
                else "10-second mean at or above the frozen line and no 0.25 match in the last second"
            ),
            "speaker_is_an_input": policy == "hold_1",
            "return_condition": "raw score at or below zero for three seconds, on the causal clock",
        },
        "cause": cause,
        "timeline": _timeline(speaker, scores, start),
    }


def _break_rows(
    session: str,
    policy: str,
    clock: str,
    breaks: list[dict],
    speaker: SpeakerTape,
    scores: ScoreTape,
    line: float,
) -> list[dict]:
    rows = []
    for row in breaks:
        delay = row.get("start_delay_s")
        late = float(row.get("late_return_s") or 0.0)
        missed = bool(row["missed_break"])
        late_start = delay is not None and float(delay) > 1.0
        if not missed and not late_start and late <= 1.0:
            continue
        start = float(row["start_s"])
        end = float(row["end_s"])
        fresh, fresh_name, _n = speaker.peak(start - 1.0, start)
        mean, score = scores.at(start)
        crossed = scores.crossed(start, end, line)
        kinds = []
        if missed:
            kinds.append("missed_break")
        if late_start:
            kinds.append("late_start")
        if late > 1.0:
            kinds.append("late_return")
        for kind in kinds:
            held = policy == "hold_1" and fresh is not None and fresh >= MATCH and kind != "late_return"
            cause = assign_cause(
                {
                    "kind": kind,
                    "speaker_held_the_open": held,
                    "mean_crossed_inside": crossed,
                    "score_stayed_hot": scores.stayed_hot(end, end + max(late, 3.0)) if kind == "late_return" else None,
                }
            )
            rows.append(
                {
                    "candidate": "NFL75_MEAN_001",
                    "session": session,
                    "policy": policy,
                    "clock": clock,
                    "kind": kind,
                    "break": row["break"],
                    "start_s": _round(start, 3),
                    "end_s": _round(end, 3),
                    "length_s": _round(end - start, 3),
                    "start_delay_s": None if delay is None else _round(float(delay), 3),
                    "late_return_s": _round(late, 3),
                    "missed_break": missed,
                    "gold": "commercial",
                    "speaker": {
                        "fresh_cosine_at_gold_start": _round(fresh, 4),
                        "fresh_name": fresh_name,
                        "line_is": "research cosine 0.25, not the live 0.55 booth match",
                    },
                    "classifier": {
                        "mean_at_gold_start": _round(mean, 4),
                        "score_at_gold_start": _round(score, 4),
                        "mean_crossed_inside_the_break": crossed,
                        "start_line": line,
                    },
                    "cause": cause,
                    "timeline": _timeline(speaker, scores, start if kind != "late_return" else end),
                }
            )
    return rows


def _matrix(rows: list[dict], program_s: float) -> dict:
    groups: dict[str, dict] = {}
    for row in rows:
        if row["kind"] != "false_mute":
            continue
        cause = row["cause"]
        bucket = groups.setdefault(
            cause["group"],
            {"episodes": 0, "seconds": 0.0, "priority": cause["priority"], "recognized": 0, "missed_voice": 0},
        )
        bucket["episodes"] += 1
        bucket["seconds"] += float(row["duration_s"])
        primary = cause["primary"]
        if primary in ("recognized_enrolled_voice_still_muted", "recognition_not_fresh_at_open"):
            bucket["recognized"] += 1
        if primary in ("enrolled_voice_not_matched", "no_speech_window"):
            bucket["missed_voice"] += 1
    false_rows = [row for row in rows if row["kind"] == "false_mute"]
    seconds = sum(float(row["duration_s"]) for row in false_rows)
    hours = None if program_s <= 0 else program_s / 3600.0
    recognized_s = 0.0
    missed_s = 0.0
    for row in false_rows:
        primary = row["cause"]["primary"]
        if row.get("overlay") == "promotional_read":
            continue
        if primary in ("recognized_enrolled_voice_still_muted", "recognition_not_fresh_at_open"):
            recognized_s += float(row["duration_s"])
        if primary in ("enrolled_voice_not_matched", "no_speech_window"):
            missed_s += float(row["duration_s"])
    rendered = []
    for name, bucket in sorted(groups.items(), key=lambda item: item[1]["priority"]):
        rendered.append(
            {
                "group": name,
                "priority": bucket["priority"],
                "episodes": bucket["episodes"],
                "seconds": _round(bucket["seconds"], 3),
                "share_of_false_mute_seconds": None if seconds <= 0 else _round(bucket["seconds"] / seconds, 4),
            }
        )
    return {
        "false_mute_episodes": len(false_rows),
        "false_mute_seconds": _round(seconds, 3),
        "false_mutes_per_hour": None if hours is None else _round(len(false_rows) / hours, 3),
        "groups": rendered,
        "genuine_seconds_despite_a_research_match": _round(recognized_s, 3),
        "genuine_seconds_without_a_research_match": _round(missed_s, 3),
    }


def _review(false_rows: list[dict], commercial_rows: list[dict], protect_rows: list[dict]) -> dict:
    genuine = [row for row in false_rows if row.get("overlay") != "promotional_read"]
    genuine.sort(key=lambda row: float(row["duration_s"]), reverse=True)
    commercials = sorted(
        commercial_rows,
        key=lambda row: float(row.get("late_return_s") or 0) + float(row.get("start_delay_s") or 0) + (1000 if row["missed_break"] else 0),
        reverse=True,
    )
    protected = [row for row in protect_rows if row.get("fate") == "cleared" and row.get("category") != "promo_sponsor"]
    protected.sort(key=lambda row: float(row["duration_s"]), reverse=True)
    return {
        "highest_harm_programming": [_card(row) for row in genuine[:10]],
        "commercial_failures": [_card(row) for row in commercials[:10]],
        "protected_programming": [row for row in protected[:5]],
    }


def _shown_seconds(row: dict):
    kind = row["kind"]
    if kind == "late_start":
        return row.get("start_delay_s")
    if kind == "late_return":
        return row.get("late_return_s")
    if kind == "missed_break":
        return row.get("length_s")
    return row.get("duration_s")


def _card(row: dict) -> dict:
    cause = row["cause"]
    return {
        "session": row["session"],
        "policy": row["policy"],
        "clock": row["clock"],
        "kind": row["kind"],
        "start_s": row["start_s"],
        "end_s": row["end_s"],
        "duration_s": _shown_seconds(row),
        "role": row.get("role"),
        "listen_category": row.get("listen_category"),
        "overlay": row.get("overlay"),
        "clip": row.get("clip"),
        "fresh_cosine": (row.get("speaker") or {}).get("fresh_cosine")
        or (row.get("speaker") or {}).get("fresh_cosine_at_gold_start"),
        "fresh_name": (row.get("speaker") or {}).get("fresh_name"),
        "mean_at_boundary": (row.get("classifier") or {}).get("mean_at_start")
        or (row.get("classifier") or {}).get("mean_at_gold_start"),
        "primary": cause["primary"],
        "group": cause["group"],
        "priority": cause["priority"],
        "confidence": cause["confidence"],
        "observation": cause["observation"],
        "hypothesis": cause["hypothesis"],
        "transcript": (row.get("transcript") or "")[:240] or None,
    }


def main() -> None:
    frozen = json.loads(MEAN.read_text(encoding="utf-8"))["frozen"]
    line = float(frozen["start_line"])
    window = int(frozen["window_s"])
    if window != 10:
        raise SystemExit("refusing a window other than the frozen 10-second mean")
    head = nbc_lines()["head"]
    booth = json.loads(BOOTH.read_text(encoding="utf-8"))
    overlay = load_overlay(OVERLAY_DIR / "overlay.json")
    asr = _load_jsonl(ASR)
    events = _load_jsonl(EVENTS)
    OUT.mkdir(parents=True, exist_ok=True)
    inventory = []
    summary_sessions = []
    for session_row in booth["sessions"]:
        session = session_row["session"]
        receipt = json.loads((PROTECT / "cache" / f"{session}.json").read_text(encoding="utf-8"))
        speaker = SpeakerTape(PROTECT / "cache" / f"{session}.npz", receipt["names"])
        times, scores, _ignored = _logits(head, session)
        means = rolling_means([float(item) for item in times], [float(item) for item in scores], window)
        score_tape = ScoreTape(times, scores, means)
        hearing = _hearing(session)
        spans = [row for row in overlay["spans"] if row["session"] == session]
        chunks = []
        for row in asr:
            if row.get("session") == session:
                kept = dict(row)
                kept["session_kept"] = session
                chunks.append(kept)
        event_rows = [row for row in events if row.get("session") == session]
        breaks = session_row["policies"]["unprotected"]["oracle"]["breaks"]
        ad_025 = speaker.commercial_seconds(breaks, MATCH)
        ad_055 = speaker.commercial_seconds(breaks, 0.55)
        policies = {}
        for policy in POLICIES:
            clocks = {}
            for clock in CLOCKS:
                stored = session_row["policies"][policy][clock]
                false_rows = [
                    _episode_row(
                        session,
                        policy,
                        clock,
                        episode,
                        speaker,
                        score_tape,
                        hearing,
                        spans,
                        chunks,
                        event_rows,
                        stored["breaks"],
                        line,
                    )
                    for episode in stored["episodes"]
                ]
                commercial_rows = _break_rows(
                    session, policy, clock, stored["breaks"], speaker, score_tape, line
                )
                inventory.extend(false_rows)
                inventory.extend(commercial_rows)
                clocks[clock] = {
                    "stored_false_mute_episodes": stored["false_mute_episodes"],
                    "stored_false_mutes_per_hour": stored["false_mutes_per_hour"],
                    "stored_commercial_coverage": stored["commercial_coverage"],
                    "stored_program_s": stored["program_s"],
                    "matrix": _matrix(false_rows, float(stored["program_s"])),
                    "missed_breaks": sum(1 for row in commercial_rows if row["kind"] == "missed_break"),
                    "late_starts": sum(1 for row in commercial_rows if row["kind"] == "late_start"),
                    "late_returns": sum(1 for row in commercial_rows if row["kind"] == "late_return"),
                    "late_return_s": _round(
                        sum(float(row["late_return_s"]) for row in commercial_rows if row["kind"] == "late_return"),
                        3,
                    ),
                }
                if len(false_rows) != stored["false_mute_episodes"]:
                    raise SystemExit(f"{session} {policy} {clock} episode count drifted")
            policies[policy] = clocks
        recognized = 0
        for row in inventory:
            if (
                row["session"] == session
                and row["policy"] == "unprotected"
                and row["clock"] == "oracle"
                and row["kind"] == "false_mute"
                and row["speaker"]["fresh_cosine"] is not None
                and row["speaker"]["fresh_cosine"] >= MATCH
            ):
                recognized += 1
        summary_sessions.append(
            {
                "session": session,
                "enrollment_names": receipt["names"],
                "enrollment_model": receipt["model"],
                "song_clips": [row["id"] for row in receipt["enrollment_clips"] if row.get("condition") == "song"],
                "speaker_windows": receipt["windows"],
                "vad_regions_saved": False,
                "vad_region_count": receipt["vad"]["n_regions"],
                "gold_commercial_seconds_with_research_cosine_at_or_above_0.25": _round(ad_025, 3),
                "gold_commercial_seconds_with_this_same_cosine_at_or_above_0.55": _round(ad_055, 3),
                "cosine_0.55_note": "A cut of this ECAPA cosine. Not the live booth similarity.",
                "oracle_false_mutes_with_fresh_match": recognized,
                "policies": policies,
            }
        )
    protect = json.loads((PROTECT / "results.json").read_text(encoding="utf-8"))
    saved_hits = []
    for session_row in protect["sessions"]:
        for episode in session_row.get("oracle_episodes") or []:
            voice = episode.get("voice") or {}
            if voice.get("current_would_protect"):
                saved_hits.append(session_row["session"])
    # The published 35 and 10 are the check on this recount.
    recount = {
        row["session"]: row["oracle_false_mutes_with_fresh_match"] for row in summary_sessions
    }
    review_false = [
        row
        for row in inventory
        if row["policy"] == "unprotected" and row["clock"] == "oracle" and row["kind"] == "false_mute"
    ]
    review_ads = [
        row
        for row in inventory
        if row["policy"] == "unprotected" and row["clock"] == "actual" and row["kind"] in ("missed_break", "late_start", "late_return")
    ]
    eliminated = []
    for session_row in protect["sessions"]:
        hearing = _hearing(session_row["session"])
        for episode in session_row.get("oracle_episodes") or []:
            if episode.get("fate") != "cleared":
                continue
            heard = _best_hear(hearing, float(episode["start_s"]), float(episode["end_s"]))
            eliminated.append(
                {
                    "session": session_row["session"],
                    "start_s": episode["start_s"],
                    "end_s": episode["end_s"],
                    "duration_s": episode["duration_s"],
                    "fate": "cleared",
                    "category": None if heard is None else heard["category"],
                    "fresh_cosine": (episode.get("voice") or {}).get("fresh_cosine"),
                    "nearest_name": (episode.get("voice") or {}).get("nearest_name"),
                    "transcript": None if heard is None else (heard.get("transcript") or "")[:240],
                    "clip": None if heard is None else heard.get("wav"),
                    "candidate": "one-second 0.25 veto on the frozen mean",
                }
            )
    clean = []
    for session_row in booth["sessions"]:
        for row in session_row["policies"]["unprotected"]["oracle"]["breaks"]:
            delay = row.get("start_delay_s")
            late = float(row.get("late_return_s") or 0.0)
            length = float(row["end_s"]) - float(row["start_s"])
            if row["missed_break"] or delay is None or float(delay) > 1.0 or late > 1.0:
                continue
            if length <= 0 or float(row["covered_s"]) / length < 0.9:
                continue
            clean.append(
                {
                    "session": session_row["session"],
                    "break": row["break"],
                    "start_s": row["start_s"],
                    "end_s": row["end_s"],
                    "length_s": _round(length, 3),
                    "start_delay_s": delay,
                    "covered_s": row["covered_s"],
                    "candidate": "NFL75_MEAN_001 unprotected oracle",
                }
            )
    clean.sort(key=lambda row: float(row["length_s"]), reverse=True)
    payload = {
        "experiment": "OHUSH_FAILURE_FORENSICS_001",
        "verdict": "DIAGNOSED",
        "deployable": False,
        "thresholds_changed": False,
        "gold_labels_changed": False,
        "television_changed": False,
        "candidate": {
            "name": "NFL75_MEAN_001 unprotected, and the one-second SpeechBrain veto measured beside it",
            "classifier": "logistic on AST embeddings, fit on the two NBC games, 10-second mean, line frozen at 0.1632588496059179",
            "speaker": "speechbrain/spkrec-ecapa-voxceleb cosine 0.25 to the enrolled TNF cast",
            "not_this_candidate": "ohush_live SPEAKER_BOOTH_MATCH 0.55, AUDIO_STRONG 0.22, and the live state machine. Those rules did not produce these episodes.",
        },
        "missing_logs": [
            "raw VAD region timestamps",
            "a human name for the speaker in each window",
            "live booth similarity on these two tapes",
            "an acoustic class such as music, jingle, or crowd from the AST head",
            "word-level times inside a listen that is longer than 20 seconds",
        ],
        "published_match_check": {
            "recount_fresh_matches_on_unprotected_oracle": recount,
            "protect_results_current_would_protect": {
                "hush_20261008_205100": saved_hits.count("hush_20261008_205100"),
                "hush_20260924_220624": saved_hits.count("hush_20260924_220624"),
            },
        },
        "sessions": summary_sessions,
        "review": _review(review_false, review_ads, eliminated),
        "correct_commercials": clean[:5],
    }
    (OUT / "results.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    with (OUT / "episodes.jsonl").open("w", encoding="utf-8") as handle:
        for row in inventory:
            handle.write(json.dumps(row) + "\n")
    print("wrote", OUT)
    for row in summary_sessions:
        print(row["session"], "fresh matches", row["oracle_false_mutes_with_fresh_match"])
        matrix = row["policies"]["unprotected"]["oracle"]["matrix"]
        print("  oracle episodes", matrix["false_mute_episodes"], "despite", matrix["genuine_seconds_despite_a_research_match"], "without", matrix["genuine_seconds_without_a_research_match"])
        for group in matrix["groups"]:
            print(f"    {group['priority']} {group['group']}: {group['episodes']} ep {group['seconds']}s {group['share_of_false_mute_seconds']}")


if __name__ == "__main__":
    main()
