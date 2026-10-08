"""OHUSH_LIVE_V0_SPORTS. A product session, not a change to Exp001–005."""

from __future__ import annotations

PRODUCT = "OHUSH_LIVE_V0_SPORTS"
SCIENTIFIC_AUTHORITY = False
ALLOWED_TO_CHANGE_EXP001_005 = False
DATASET_ROLE = "live_dev"

REPLACEMENTS = ("silence", "stadium", "rain", "fireplace", "pink", "brown")
DEFAULT_REPLACEMENT = "stadium"
CHUNK_MINUTES = 15
HINT_STREAK_S = 3.0


class ReturnHint:
    """One quiet cue when return is possible and not yet strong enough to play."""

    def __init__(self) -> None:
        self.streak = 0.0
        self.fired = False

    def reset(self) -> None:
        self.streak = 0.0
        self.fired = False

    def update(self, in_replacement: bool, return_votes: int, dt: float) -> bool:
        if not in_replacement:
            self.reset()
            return False
        if return_votes == 1:
            self.streak += dt
        else:
            self.streak = 0.0
        if self.streak + 1e-9 >= HINT_STREAK_S and not self.fired:
            self.fired = True
            return True
        return False


class AutoLatch:
    """A manual press holds for the current break. The next break can be automatic."""

    def __init__(self) -> None:
        self.suppress_mute = False
        self.suppress_play = False

    def human_play(self) -> None:
        self.suppress_mute = True
        self.suppress_play = False

    def human_mute(self) -> None:
        self.suppress_play = True
        self.suppress_mute = False

    def allow_auto_mute(self, departure_votes: int) -> bool:
        if not self.suppress_mute:
            return True
        if departure_votes < 2:
            self.suppress_mute = False
        return False

    def allow_auto_play(self, return_votes: int) -> bool:
        if not self.suppress_play:
            return True
        if return_votes < 2:
            self.suppress_play = False
        return False


def family_score(families: dict, name: str, kind: str) -> float | None:
    reading = families.get(name)
    if not reading:
        return None
    value = reading.get(kind)
    if value is None:
        return None
    return round(float(value), 4)


def votes(families: dict, key: str) -> int:
    count = 0
    for reading in families.values():
        if reading and reading.get(key):
            count += 1
    return count


def decision_row(timestamp: float, state: str, source: str, families: dict, replacement: str, human: bool) -> dict:
    kind = "return" if state == "REPLACEMENT_TO_PROGRAM" else "departure"
    return {
        "t": round(float(timestamp), 3),
        "state": state,
        "decision_source": source,
        "speaker_score": family_score(families, "speaker", kind),
        "audio_world_score": family_score(families, "audio", kind),
        "semantic_score": family_score(families, "semantic", kind),
        "score_kind": kind,
        "replacement": replacement,
        "human_override": human,
        "product": PRODUCT,
        "scientific_authority": SCIENTIFIC_AUTHORITY,
        "allowed_to_change_exp001_005": ALLOWED_TO_CHANGE_EXP001_005,
        "dataset_role": DATASET_ROLE,
    }


def override_row(timestamp: float, action: str, prior_state: str) -> dict:
    return {
        "t": round(float(timestamp), 3),
        "event": "human_override",
        "action": action,
        "prior_state": prior_state,
        "reason": "manual",
        "product": PRODUCT,
        "scientific_authority": SCIENTIFIC_AUTHORITY,
        "dataset_role": DATASET_ROLE,
    }


def next_replacement(current: str) -> str:
    index = REPLACEMENTS.index(current)
    return REPLACEMENTS[(index + 1) % len(REPLACEMENTS)]
