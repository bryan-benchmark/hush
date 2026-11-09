"""Second classification for promotional reads. Gold stays binary.

The consumer scenario drops a promotional read out of the false-mute total.
A mixed mention and a program span stay in that total. The historical
intervals are read and never written.
"""

from __future__ import annotations

import json
from pathlib import Path

from experiments.nfl75.score import merge_false_mute_episodes

REPO = Path(__file__).resolve().parents[2]
OVERLAY_PATH = REPO / "docs" / "ohush" / "research" / "NFL75_PROMO_CLASS_001" / "overlay.json"
BOOTH_PATH = REPO / "docs" / "ohush" / "research" / "NFL75_BOOTH_HOLD_001" / "results.json"

_EPS = 1e-6
_CLASSES = {"promotional_read", "mixed_mention", "program"}
_VIEWS = ("research", "consumer", "sponsored_read", "audited_bucket")
_REQUIRED = (
    "id",
    "session",
    "start_s",
    "end_s",
    "audited_false_mute_s",
    "overlay_class",
    "subtype",
    "gold_label",
    "in_audited_promo_bucket",
)


def load_overlay(path: Path | None = None) -> dict:
    payload = json.loads((path or OVERLAY_PATH).read_text(encoding="utf-8"))
    if payload.get("gold_labels_changed") is not False:
        raise ValueError("the overlay must leave the historical labels unchanged")
    seen = set()
    for row in payload["spans"]:
        missing = [key for key in _REQUIRED if key not in row]
        if missing:
            raise ValueError(f"{row.get('id')} is missing {missing}")
        if row["id"] in seen:
            raise ValueError(f"duplicate span {row['id']}")
        seen.add(row["id"])
        if row["gold_label"] != "program":
            raise ValueError(f"{row['id']} would change the historical label")
        if row["overlay_class"] not in _CLASSES:
            raise ValueError(f"{row['id']} has class {row['overlay_class']}")
        start, end = float(row["start_s"]), float(row["end_s"])
        if end <= start:
            raise ValueError(f"{row['id']} ends before it starts")
        audited = bool(row["in_audited_promo_bucket"])
        if row["overlay_class"] == "program" and audited:
            raise ValueError(f"{row['id']} is program and also in the promo bucket")
        if row["overlay_class"] != "program" and not audited:
            raise ValueError(f"{row['id']} is a promo class left out of the audited bucket")
        if row["overlay_class"] == "promotional_read" and row["subtype"] not in {
            "sponsored_read",
            "campaign_read",
            "show_promo",
        }:
            raise ValueError(f"{row['id']} promotional subtype {row['subtype']}")
    return payload


def spans_for(overlay: dict, session: str, view: str) -> list[tuple[float, float]]:
    """Clock bounds removed from program under one scoring view.

    `research` removes nothing. `consumer` removes promotional reads.
    `sponsored_read` removes only the paid reads. `audited_bucket` removes
    every span the earlier listen called a sponsor read, including mixed ones.
    """
    if view not in _VIEWS:
        raise ValueError(f"unknown view {view}")
    chosen = []
    for row in overlay["spans"]:
        if row["session"] != session:
            continue
        take = False
        if view == "consumer":
            take = row["overlay_class"] == "promotional_read"
        elif view == "sponsored_read":
            take = row["subtype"] == "sponsored_read"
        elif view == "audited_bucket":
            take = bool(row["in_audited_promo_bucket"])
        if take:
            chosen.append((float(row["start_s"]), float(row["end_s"])))
    return _merge(chosen)


def audited_seconds(overlay: dict, session: str, *, bucket: bool) -> float:
    total = 0.0
    for row in overlay["spans"]:
        if row["session"] != session:
            continue
        if bucket and not row["in_audited_promo_bucket"]:
            continue
        if not bucket and row["overlay_class"] != "promotional_read":
            continue
        total += float(row["audited_false_mute_s"])
    return total


def _merge(ranges: list[tuple[float, float]]) -> list[tuple[float, float]]:
    ordered = sorted((start, end) for start, end in ranges if end > start)
    if not ordered:
        return []
    out = [ordered[0]]
    for start, end in ordered[1:]:
        prev_s, prev_e = out[-1]
        if start <= prev_e + _EPS:
            out[-1] = (prev_s, max(prev_e, end))
        else:
            out.append((start, end))
    return out


def _subtract_one(start: float, end: float, cut0: float, cut1: float) -> list[tuple[float, float]]:
    if cut1 <= start + _EPS or cut0 >= end - _EPS:
        return [(start, end)]
    out = []
    if cut0 > start + _EPS:
        out.append((start, min(cut0, end)))
    if cut1 < end - _EPS:
        out.append((max(cut1, start), end))
    return [(left, right) for left, right in out if right > left + _EPS]


def subtract_ranges(
    pieces: list[tuple[float, float]],
    spans: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    remaining = [(start, end) for start, end in pieces if end > start]
    for cut0, cut1 in spans:
        nxt: list[tuple[float, float]] = []
        for start, end in remaining:
            nxt.extend(_subtract_one(start, end, cut0, cut1))
        remaining = nxt
    return remaining


def _pieces(episodes: list[dict]) -> list[tuple[float, float]]:
    pieces = []
    for episode in episodes:
        for part in episode["parts"]:
            pieces.append((float(part["start_s"]), float(part["end_s"])))
    return pieces


def _overlap(pieces: list[tuple[float, float]], spans: list[tuple[float, float]]) -> float:
    total = 0.0
    for start, end in pieces:
        for cut0, cut1 in spans:
            total += max(0.0, min(end, cut1) - max(start, cut0))
    return total


def _clock(spans: list[tuple[float, float]]) -> float:
    return sum(end - start for start, end in spans)


def clear_of_breaks(spans: list[tuple[float, float]], breaks: list[dict]) -> None:
    for start, end in spans:
        for row in breaks:
            if min(end, float(row["end_s"])) - max(start, float(row["start_s"])) > _EPS:
                raise ValueError(f"{start:.3f}-{end:.3f} overlaps a gold commercial")


def view_metrics(
    episodes: list[dict],
    program_s: float,
    spans: list[tuple[float, float]],
) -> dict:
    """False mutes after removing `spans` from covered program.

    `program_s` is the gold program clock. The view's program clock drops by
    the full class bounds, including a one-second gap the merger had heard
    inside a read. Covered seconds drop only where a cover actually overlaps
    the class.
    """
    pieces = _pieces(episodes)
    merged = merge_false_mute_episodes(subtract_ranges(pieces, spans))
    covered = sum(float(row["duration_s"]) for row in merged)
    program = float(program_s) - _clock(spans)
    if program <= _EPS:
        raise ValueError("program clock collapsed")
    hours = program / 3600.0
    longest = max(merged, key=lambda row: float(row["duration_s"]), default=None)
    muted = _overlap(pieces, spans)
    return {
        "program_s": program,
        "program_removed_s": _clock(spans),
        "program_covered_s": covered,
        "false_mute_episodes": len(merged),
        "false_mutes_per_hour": len(merged) / hours,
        "longest_false_mute_s": 0.0 if longest is None else float(longest["duration_s"]),
        "longest_start_s": None if longest is None else float(longest["start_s"]),
        "longest_end_s": None if longest is None else float(longest["end_s"]),
        "program_hidden_per_hour": covered / hours,
        "class_muted_s": muted,
        "class_playing_s": _clock(spans) - muted,
    }


def score_views(overlay: dict, session: str, policy: dict) -> dict:
    episodes = policy["episodes"]
    program_s = float(policy["program_s"])
    pieces = _pieces(episodes)
    views = {}
    for name in _VIEWS:
        spans = spans_for(overlay, session, name)
        metrics = view_metrics(episodes, program_s, spans)
        metrics["class_clock_s"] = _clock(spans)
        metrics["commercial_coverage"] = policy["commercial_coverage"]
        metrics["commercial_s"] = policy["commercial_s"]
        metrics["breaks_missed"] = policy["breaks_missed"]
        views[name] = metrics
    examples = []
    for row in overlay["spans"]:
        if row["session"] != session:
            continue
        if row["overlay_class"] != "program":
            continue
        examples.append(
            {
                "id": row["id"],
                "muted_s": _overlap(pieces, [(float(row["start_s"]), float(row["end_s"]))]),
            }
        )
    return {"views": views, "program_examples_muted_s": examples}
