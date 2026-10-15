"""OHUSH_LIVE_V0_SPORTS. A product session, not a change to Exp001–005."""

from __future__ import annotations

PRODUCT = "OHUSH_LIVE_V0_SPORTS"
SCIENTIFIC_AUTHORITY = False
ALLOWED_TO_CHANGE_EXP001_005 = False
DATASET_ROLE = "live_dev"

# Soft beds first (wife veto round); older sports/noise beds kept at the end.
REPLACEMENTS = (
    "silence",
    "neon",
    "charge",
    "volt",
    "drop",
    "hush",
    "pad",
    "ocean",
    "stream",
    "birds",
    "breeze",
    "night",
    "chimes",
    "piano",
    "harp",
    "meadow",
    "stadium",
    "rain",
    "fireplace",
    "pink",
    "brown",
)
DEFAULT_REPLACEMENT = "neon"
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
        if return_votes >= 1:
            self.streak += dt
        else:
            self.streak = 0.0
        if self.streak + 1e-9 >= HINT_STREAK_S and not self.fired:
            self.fired = True
            return True
        return False


class AutoLatch:
    """Manual Show during a covered break holds auto-mute until that break ends.

    Pressing Show while already on program must NOT block the next ad — that
    bug left departure_votes=1 forever suppressed and mute_streak stuck at 0.

    Manual Cover must NEVER block auto-return. Tonight's logs showed play_streak
    stuck at 0 for 25s+ of program-like audio because suppress_play returned
    False whenever return_votes>=1 (exactly when the show was back).
    """

    def __init__(self) -> None:
        self.suppress_mute = False

    def human_play(self, *, was_replacement: bool) -> None:
        self.suppress_mute = bool(was_replacement)

    def human_mute(self, *, was_program: bool) -> None:
        # Cover is a one-shot correction. Keep hunting for program return.
        del was_program
        self.suppress_mute = False

    def allow_auto_mute(self, departure_votes: int) -> bool:
        if not self.suppress_mute:
            return True
        # Hold only while the break that was covered is still signaling.
        if departure_votes <= 0:
            self.suppress_mute = False
            return True
        return False

    def allow_auto_play(self, return_votes: int) -> bool:
        del return_votes
        return True


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


def decision_row(
    timestamp: float,
    state: str,
    source: str,
    families: dict,
    replacement: str,
    human: bool,
    *,
    noop: bool = False,
    prior_hearing: str | None = None,
    departure_votes: int | None = None,
    return_votes: int | None = None,
    lag_ms: float | None = None,
    mute_streak_s: float | None = None,
    play_streak_s: float | None = None,
) -> dict:
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
        "noop": bool(noop),
        "prior_hearing": prior_hearing,
        "departure_votes": departure_votes,
        "return_votes": return_votes,
        "lag_ms": None if lag_ms is None else round(float(lag_ms), 1),
        "mute_streak_s": None if mute_streak_s is None else round(float(mute_streak_s), 2),
        "play_streak_s": None if play_streak_s is None else round(float(play_streak_s), 2),
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
