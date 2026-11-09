"""Oracle boundaries for a bottleneck split. Not a deployable mute.

Perfect endings keep the detector's starts and unmute at the gold commercial
end. Perfect starts begin at the gold commercial start and keep the detector's
end, including a tail into the game. A cover that never touches a commercial
is left alone, so a mid-game false mute is not erased by either oracle.
"""

from __future__ import annotations

from experiments.measurement.metrics import Span

from experiments.nfl75.score import _merge, playback_from_covers

_EPS = 1e-9


def _covers(playback: list[Span]) -> list[tuple[float, float]]:
    return _merge([(span.start, span.end) for span in playback if span.state == "covered"])


def _hits(cover: tuple[float, float], ads: list[tuple[float, float]]) -> list[tuple[float, float]]:
    c0, c1 = cover
    return [(a0, a1) for a0, a1 in ads if min(c1, a1) - max(c0, a0) > _EPS]


def perfect_endings(playback: list[Span], commercials: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Real starts, gold endings. Late tails and bridges after a gold end are dropped.

    An early let-go inside a commercial is extended to the gold end.
    """
    emit: list[tuple[float, float]] = []
    for c0, c1 in _covers(playback):
        hits = _hits((c0, c1), commercials)
        if not hits:
            emit.append((c0, c1))
            continue
        first_start = hits[0][0]
        if c0 < first_start:
            emit.append((c0, first_start))
        for a0, a1 in hits:
            on0 = max(c0, a0)
            on1 = min(c1, a1)
            if on1 <= on0:
                continue
            emit.append((on0, a1))
    return _merge(emit)


def perfect_starts(playback: list[Span], commercials: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Gold starts, real endings. The tail past the gold end stays."""
    emit: list[tuple[float, float]] = []
    for c0, c1 in _covers(playback):
        hits = _hits((c0, c1), commercials)
        if not hits:
            emit.append((c0, c1))
            continue
        start = hits[0][0]
        if c1 > start:
            emit.append((start, c1))
    return _merge(emit)


def oracle_playback(
    coverage: tuple[float, float],
    playback: list[Span],
    commercials: list[tuple[float, float]],
    mode: str,
) -> list[Span]:
    if mode == "joint":
        covers = _covers(playback)
    elif mode == "perfect_endings":
        covers = perfect_endings(playback, commercials)
    elif mode == "perfect_starts":
        covers = perfect_starts(playback, commercials)
    else:
        raise ValueError(f"unknown oracle mode {mode}")
    return playback_from_covers(coverage, covers)


def bottleneck(joint: dict, endings: dict, starts: dict) -> dict:
    """Say whether advertising escapes at the start, the return, or both.

    The oracles only repair a cover the detector already made. A run that
    never covers has a start problem, and the return cannot be measured yet.
    """
    missed = float(joint["commercial_missed_s"])
    recovered_return = missed - float(endings["commercial_missed_s"])
    recovered_start = missed - float(starts["commercial_missed_s"])
    hidden = float(joint["program_covered_s"])
    hidden_by_return = hidden - float(endings["program_covered_s"])
    hidden_by_early_start = hidden - float(starts["program_covered_s"])
    no_cover = float(joint["commercial_covered_s"]) <= _EPS and hidden <= _EPS
    escape = []
    if no_cover and missed > _EPS:
        escape.append(
            {
                "cause": "start",
                "commercial_seconds": missed,
                "note": "No cover starts, so neither oracle has a boundary to repair.",
            }
        )
    else:
        if recovered_start > 1e-3:
            escape.append({"cause": "start", "commercial_seconds": recovered_start})
        if recovered_return > 1e-3:
            escape.append({"cause": "return", "commercial_seconds": recovered_return})
        escape.sort(key=lambda row: row["commercial_seconds"], reverse=True)
    hiding = []
    if hidden_by_return > 1e-3:
        hiding.append({"cause": "return", "program_seconds": hidden_by_return})
    if hidden_by_early_start > 1e-3:
        hiding.append({"cause": "early_start", "program_seconds": hidden_by_early_start})
    if no_cover and missed > _EPS:
        primary = "start"
    elif escape and hiding:
        primary = "both"
    elif escape:
        primary = escape[0]["cause"] if len({row["cause"] for row in escape}) == 1 else "both"
    elif hiding:
        primary = "return"
    else:
        primary = "neither"
    return {
        "primary": primary,
        "oracle": True,
        "deployable": False,
        "advertising_escape": escape,
        "football_hidden_by": hiding,
        "note": (
            "Oracle rows use gold boundaries. They are not a product result "
            "and they cannot satisfy NFL75 acceptance."
        ),
    }
