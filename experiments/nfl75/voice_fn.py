"""Classify one frozen ECAPA window. The 0.25 line is not moved.

A class describes the cosine and the speech detector. It does not name the
person. That name stays empty until a person labels the clip.
"""

from __future__ import annotations

MATCH = 0.25
FRESH_S = 1.0


def _best(scores: dict[str, float]) -> tuple[str | None, float | None, str | None, float | None]:
    finite = [(name, float(value)) for name, value in scores.items() if value == value]
    if not finite:
        return None, None, None, None
    finite.sort(key=lambda item: item[1], reverse=True)
    second = finite[1] if len(finite) > 1 else (None, None)
    return finite[0][0], finite[0][1], second[0], second[1]


def _hit(scores: dict[str, float], line: float = MATCH) -> bool:
    _name, score, _other, _second = _best(scores)
    return score is not None and score + 1e-12 >= line


def classify_episode(
    start: float,
    end: float,
    windows: list[dict],
    speech_s: float | None,
    *,
    line: float = MATCH,
) -> dict:
    """One false-mute span against the windows the embedder actually wrote.

    `windows` use the session clock. A window can be used at its end and not
    before. `speech_s` is detector speech inside the span. None means the
    detector was not rerun.
    """
    if line != MATCH:
        raise ValueError("the cosine line stays at 0.25")
    # A score is usable when the window ends. A window that finishes after
    # the mute ends cannot explain that mute.
    finished = [
        row for row in windows if start + 1e-9 < float(row["end"]) <= end + 1e-9
    ]
    fresh = [
        row
        for row in windows
        if start - FRESH_S - 1e-9 <= float(row["end"]) <= start + 1e-9 and _hit(row["scores"], line)
    ]
    inside_hits = [row for row in finished if _hit(row["scores"], line)]
    peak = None
    for row in finished:
        name, score, other, second = _best(row["scores"])
        if score is None:
            continue
        if peak is None or score > peak["cosine"]:
            peak = {
                "start": float(row["start"]),
                "end": float(row["end"]),
                "name": name,
                "cosine": score,
                "second_name": other,
                "second_cosine": second,
            }
    if fresh:
        chosen = max(fresh, key=lambda row: _best(row["scores"])[1] or -1.0)
        name, score, other, second = _best(chosen["scores"])
        kind = "decision_ignored_match"
        available = float(chosen["end"])
    elif inside_hits:
        first = min(inside_hits, key=lambda row: float(row["end"]))
        name, score, other, second = _best(first["scores"])
        kind = "delayed_recognition"
        available = float(first["end"])
    elif finished and not any(row["scores"] for row in finished):
        kind = "missing_reference"
        name = score = other = second = available = None
    elif finished:
        kind = "below_line"
        name = score = other = second = available = None
        if peak is not None:
            name, score = peak["name"], peak["cosine"]
            other, second = peak["second_name"], peak["second_cosine"]
    elif speech_s is not None and speech_s < 0.25:
        kind = "no_speech_detected"
        name = score = other = second = available = None
    elif speech_s is not None and speech_s >= 1.0:
        kind = "speech_without_embedding_window"
        name = score = other = second = available = None
    else:
        kind = "no_embedding_window"
        name = score = other = second = available = None
    return {
        "kind": kind,
        "identity_verified": False,
        "windows": len(finished),
        "speech_s": speech_s,
        "available_at_s": available,
        "seconds_after_open": None if available is None else round(available - start, 3),
        "cited_name": name,
        "cited_cosine": None if score is None else round(float(score), 4),
        "second_name": other,
        "second_cosine": None if second is None else round(float(second), 4),
        "peak": peak,
    }
