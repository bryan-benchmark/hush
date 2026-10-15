"""Asymmetric mute state. Departure can mute. Return must be strong and persistent.

Hearing the locked booth (Al Michaels / color) always lifts cover immediately.
"""

from __future__ import annotations

from ohush_live.policy import (
    AUDIO_RETURN,
    AUDIO_STRONG,
    BOOTH_RETURN_PERSIST_S,
    MIN_AGREE,
    MIN_MUTE_HOLD_S,
    MUTE_PERSIST_S,
    PLAY_PERSIST_S,
    PRODUCT,
    SOLO_FAMILY,
    SOLO_MUTE_PERSIST_S,
    SOLO_PLAY_PERSIST_S,
    SOLO_SPEAKER_PLAY_PERSIST_S,
    SPEAKER_BOOTH_CONTINUITY,
)


class Machine:
    def __init__(self) -> None:
        self.state = "PLAY"
        self._mute_streak = 0.0
        self._play_streak = 0.0
        self._muted_at: float | None = None

    def diagnostics(self) -> dict:
        return {
            "state": self.state,
            "mute_streak_s": round(self._mute_streak, 2),
            "play_streak_s": round(self._play_streak, 2),
        }

    def muted_for(self, timestamp: float) -> float | None:
        if self._muted_at is None:
            return None
        return round(max(0.0, timestamp - self._muted_at), 2)

    def manual(self, timestamp: float, action: str, families: dict) -> dict:
        if action not in ("mute", "play"):
            raise ValueError(action)
        after = "MUTED" if action == "mute" else "PLAY"
        event = self._event(timestamp, after, families, "manual", True)
        self.state = after
        self._mute_streak = 0.0
        self._play_streak = 0.0
        self._muted_at = timestamp if after == "MUTED" else None
        return event

    def step(self, timestamp: float, dt: float, families: dict) -> dict | None:
        if self.state == "PLAY":
            self._play_streak = 0.0
            yes, need, tag, persist = _quorum(families, depart=True)
            if yes >= need:
                self._mute_streak += dt
            else:
                self._mute_streak = 0.0
            if self._mute_streak + 1e-9 >= persist:
                self.state = "MUTED"
                self._muted_at = timestamp
                self._mute_streak = 0.0
                return self._event(timestamp, "MUTED", families, tag, False)
            return None

        # Al / booth in the clear: never sit on cover through a mute hold.
        booth = _booth_heard(families.get("speaker"))
        held = (
            not booth
            and self._muted_at is not None
            and timestamp - self._muted_at + 1e-9 < MIN_MUTE_HOLD_S
        )
        yes, need, tag, persist = _quorum(families, depart=False)
        if held or yes < need:
            self._play_streak = 0.0
            return None
        self._play_streak += dt
        if self._play_streak + 1e-9 < persist:
            return None
        self.state = "PLAY"
        self._muted_at = None
        self._play_streak = 0.0
        return self._event(timestamp, "PLAY", families, tag, False)

    def _event(self, timestamp: float, after: str, families: dict, reason: str, manual: bool) -> dict:
        return {
            "product": PRODUCT,
            "timestamp": round(float(timestamp), 3),
            "state_before": self.state,
            "state_after": after,
            "reason": reason,
            "manual_override": manual,
            "speaker_departure": _score(families, "speaker", "departure"),
            "audio_departure": _score(families, "audio", "departure"),
            "semantic_departure": _score(families, "semantic", "departure"),
            "speaker_return": _score(families, "speaker", "return"),
            "audio_return": _score(families, "audio", "return"),
            "semantic_return": _score(families, "semantic", "return"),
        }


def _family_yes(name: str, reading: dict, *, depart: bool) -> bool:
    """Product vote. Audio uses the raw distance so thresholds stay in policy.py."""
    if depart:
        if name == "audio":
            value = reading.get("departure")
            if value is not None and float(value) >= AUDIO_STRONG:
                return True
            return bool(reading.get("strong_departure"))
        return bool(reading.get("strong_departure"))
    if name == "speaker" and _booth_heard(reading):
        return True
    if name == "audio":
        value = reading.get("departure")
        if value is not None and float(value) <= AUDIO_RETURN:
            return True
        return bool(reading.get("strong_return"))
    return bool(reading.get("strong_return"))


def _alive(reading: dict | None) -> bool:
    """True when the family has a real score — empty placeholders do not block solo audio."""
    if reading is None:
        return False
    if reading.get("booth_present") or reading.get("booth_locked"):
        return True
    if reading.get("departure") is not None or reading.get("return") is not None:
        return True
    return bool(reading.get("strong_departure") or reading.get("strong_return"))


def _booth_heard(speaker: dict | None) -> bool:
    """True when any locked booth announcer (Al, color, sideline) is speaking."""
    if not speaker:
        return False
    if not speaker.get("speech"):
        return False
    if speaker.get("booth_present") or speaker.get("recurring"):
        return True
    sim = speaker.get("similarity_to_booth")
    if sim is not None and float(sim) >= SPEAKER_BOOTH_CONTINUITY:
        return True
    cont = speaker.get("continuity")
    if cont is not None and float(cont) >= SPEAKER_BOOTH_CONTINUITY:
        return True
    return False


def _booth_still_talking(speaker: dict | None) -> bool:
    """Booth hold — speech now, or brief linger after the last booth line."""
    if not speaker:
        return False
    if _booth_heard(speaker):
        return True
    if speaker.get("booth_present"):
        return True
    cont = speaker.get("continuity")
    if cont is not None and float(cont) >= SPEAKER_BOOTH_CONTINUITY:
        return True
    return False


def _quorum(families: dict, *, depart: bool) -> tuple[int, int, str, float]:
    """Return (yes_votes, needed, reason_tag, persist_s)."""
    present = {name: reading for name, reading in families.items() if _alive(reading)}
    yes = sum(1 for name, reading in present.items() if _family_yes(name, reading, depart=depart))
    if not present:
        return 0, 10**9, "no_families", 10**9
    # Hear Al / the booth → always leave cover, immediately.
    if not depart:
        speaker = present.get("speaker")
        if _booth_heard(speaker):
            return 1, 1, "booth_voice", BOOTH_RETURN_PERSIST_S
        if speaker is not None and _family_yes("speaker", speaker, depart=False):
            return 1, 1, "speaker_return", SOLO_SPEAKER_PLAY_PERSIST_S
    # Once the booth pair is locked, never cover on audio world alone.
    speaker = present.get("speaker")
    booth_locked = bool(speaker and speaker.get("booth_locked"))
    if depart and (booth_locked or _booth_still_talking(speaker)):
        audio = present.get("audio")
        audio_yes = audio is not None and _family_yes("audio", audio, depart=True)
        speaker_yes = speaker is not None and bool(speaker.get("strong_departure"))
        if audio_yes and speaker_yes:
            return 2, 2, "booth_and_audio_depart", MUTE_PERSIST_S
        return 0, 10**9, "booth_still_talking", 10**9
    if len(present) == 1:
        name = next(iter(present))
        if name != SOLO_FAMILY:
            return yes, 10**9, "solo_non_audio", 10**9
        persist = SOLO_MUTE_PERSIST_S if depart else SOLO_PLAY_PERSIST_S
        tag = "solo_audio_depart" if depart else "solo_audio_return"
        return yes, 1, tag, persist
    persist = MUTE_PERSIST_S if depart else PLAY_PERSIST_S
    tag = f"{MIN_AGREE}_of_strong" if depart else f"{MIN_AGREE}_of_return"
    return yes, MIN_AGREE, tag, persist


def _score(families: dict, name: str, kind: str) -> float | None:
    reading = families.get(name)
    if not reading:
        return None
    value = reading.get(kind)
    if value is None:
        return None
    return round(float(value), 4)
