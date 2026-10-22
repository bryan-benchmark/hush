"""Which show is on, and whether that show still owns the audio.

Each national broadcast has its own booth. Those booths are not candidates
for each other. Sunday Night Football never asks whether a voice is Scott
Hanson. RedZone never asks whether a voice is Mike Tirico.

Membership is 1 when that booth was just heard and 0 after five minutes
without them. RedZone authorizes no commercial decision while membership
is still above 0. A game show keeps its own commercial rules available.
Membership at 0 means this show's rule has let go. It does not mute.
"""

from __future__ import annotations

RELEASE_S = 300.0

SHOWS = {
    "redzone": ("Scott Hanson",),
    "snf": ("Mike Tirico", "Cris Collinsworth"),
    "mnf": ("Joe Buck", "Troy Aikman"),
    "tnf": ("Al Michaels", "Kirk Herbstreit"),
    "college_saturday": ("Kirk Herbstreit", "Chris Fowler"),
}

# These shows have commercial breaks. RedZone does not, while it is still the show.
COMMERCIAL_SHOWS = frozenset({"snf", "mnf", "tnf", "college_saturday"})


def roster(show: str) -> tuple[str, ...]:
    return SHOWS[show]


def membership(seconds_since_booth: float | None) -> float:
    if seconds_since_booth is None or seconds_since_booth >= RELEASE_S:
        return 0.0
    if seconds_since_booth <= 0:
        return 1.0
    return 1.0 - (seconds_since_booth / RELEASE_S)


def decide(show: str, seconds_since_booth: float | None) -> dict:
    """Return the show rule. This does not mute by itself."""
    if show not in SHOWS:
        raise KeyError(show)
    level = membership(seconds_since_booth)
    on_show = level > 0.0
    if not on_show:
        commercial_rules = "no_show"
    elif show in COMMERCIAL_SHOWS:
        commercial_rules = "on"
    else:
        commercial_rules = "off"
    return {
        "show": show,
        "roster": roster(show),
        "membership": level,
        "on_show": on_show,
        "commercial_rules": commercial_rules,
    }
