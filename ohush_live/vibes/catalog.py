"""Vibe catalog for VIBE_STARTER_001. Default is Wednesday Night."""

from __future__ import annotations

DEFAULT_VIBE = "wednesday_night"

# Bed name → track metadata. Bed names are ListenerGate replacement keys.
TRACKS: dict[str, dict] = {
    "wednesday_night": {
        "vibe": "wednesday_night",
        "title": "Chill Lofi Inspired",
        "creator": "qubodup",
        "source_id": "wednesday_chill_lofi",
        "role": "primary",
        "labels": ["Relaxed", "Warm", "Easygoing"],
    },
    "wednesday_night_lofi_again": {
        "vibe": "wednesday_night",
        "title": "Lofi Again",
        "creator": "omfgdude",
        "source_id": "wednesday_lofi_again",
        "role": "alt",
        "labels": ["Relaxed", "Warm", "Easygoing"],
    },
    "wednesday_night_cup_of_tea": {
        "vibe": "wednesday_night",
        "title": "A Cup of Tea",
        "creator": "TAD",
        "source_id": "wednesday_cup_of_tea",
        "role": "alt",
        "labels": ["Relaxed", "Warm", "Easygoing"],
    },
    "friends_over": {
        "vibe": "friends_over",
        "title": "Funked Up",
        "creator": "Joth",
        "source_id": "friends_funked_up",
        "role": "primary",
        "labels": ["Social", "Energetic", "Game day"],
    },
    "friends_over_disco": {
        "vibe": "friends_over",
        "title": "Funky Disco Beats",
        "creator": "Fupi",
        "source_id": "friends_funky_disco",
        "role": "alt",
        "labels": ["Social", "Energetic", "Game day"],
    },
    "friends_over_empty_stretch": {
        "vibe": "friends_over",
        "title": "Empty Stretch",
        "creator": "Zane Little Music",
        "source_id": "friends_empty_stretch",
        "role": "alt",
        "labels": ["Social", "Energetic", "Game day"],
    },
    "cocktail_lounge": {
        "vibe": "cocktail_lounge",
        "title": "Coffee House Bump",
        "creator": "OatCog",
        "source_id": "cocktail_coffee_house",
        "role": "primary",
        "labels": ["Smooth", "Social", "Sophisticated"],
    },
    "cocktail_lounge_bossa": {
        "vibe": "cocktail_lounge",
        "title": "Bossa Nova",
        "creator": "Joth",
        "source_id": "cocktail_bossa_nova",
        "role": "alt",
        "labels": ["Smooth", "Social", "Sophisticated"],
    },
    "rainy_night": {
        "vibe": "rainy_night",
        "title": "Soft Rain Loop",
        "creator": "_lynks",
        "source_id": "rain_soft_loop",
        "role": "primary",
        "labels": ["Calm", "Atmospheric", "Low energy"],
    },
    "stadium_vibe": {
        "vibe": "stadium",
        "title": "Sports Crowd Various Sounds",
        "creator": "FlatHill",
        "source_id": "stadium_crowd",
        "role": "primary",
        "labels": ["Immersive", "Sport-specific", "Familiar"],
    },
}

VIBES: dict[str, dict] = {
    "wednesday_night": {
        "label": "Wednesday Night",
        "default_track": "wednesday_night",
        "description": "Warm, mellow instrumental grooves.",
    },
    "friends_over": {
        "label": "Friends Over",
        "default_track": "friends_over",
        "description": "Upbeat funk and social energy.",
    },
    "cocktail_lounge": {
        "label": "Cocktail Lounge",
        "default_track": "cocktail_lounge",
        "description": "Smooth jazz / lounge interludes.",
    },
    "rainy_night": {
        "label": "Rainy Night",
        "default_track": "rainy_night",
        "description": "Soft rain ambience.",
    },
    "stadium": {
        "label": "Stadium",
        "default_track": "stadium_vibe",
        "description": "Crowd atmosphere (edit disruptive cheers).",
    },
}

# Order for selector / evaluation matrix.
VIBE_ORDER = (
    "silence",
    "wednesday_night",
    "friends_over",
    "cocktail_lounge",
    "rainy_night",
    "stadium",
)


def vibe_bed_names() -> list[str]:
    """Replacement keys exposed when the vibe experiment is enabled."""
    names = ["silence"]
    for vibe in VIBE_ORDER:
        if vibe == "silence":
            continue
        meta = VIBES[vibe]
        primary = meta["default_track"]
        names.append(primary)
        for bed, track in TRACKS.items():
            if track["vibe"] == vibe and bed != primary:
                names.append(bed)
    return names


def resolve_vibe_track(vibe_or_bed: str) -> str:
    """Map a vibe id or bed name to a concrete bed key."""
    if vibe_or_bed == "silence":
        return "silence"
    if vibe_or_bed in TRACKS:
        return vibe_or_bed
    if vibe_or_bed in VIBES:
        return VIBES[vibe_or_bed]["default_track"]
    raise KeyError(vibe_or_bed)
