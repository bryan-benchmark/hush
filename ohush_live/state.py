"""Asymmetric mute state. Departure can mute. Return must be strong and persistent.

Knowing booth identities is not the same as hearing them. Protect verified
booth speech and a bounded outro hold only. Generic continuity / recurrence
must not lift cover.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hush.voice_floor import show_present  # noqa: E402
from ohush_live.policy import (  # noqa: E402
    AUDIO_RETURN,
    AUDIO_STRONG,
    BOOTH_RETURN_PERSIST_S,
    HUMAN_COVER_RETURN_PERSIST_S,
    MIN_AGREE,
    MIN_MUTE_HOLD_S,
    MUTE_PERSIST_S,
    PLAY_PERSIST_S,
    PRODUCT,
    SOLO_FAMILY,
    SOLO_MUTE_PERSIST_S,
    SOLO_PLAY_PERSIST_S,
    SOLO_SPEAKER_PLAY_PERSIST_S,
    SPEAKER_BOOTH_MATCH,
)


class Machine:
    def __init__(self) -> None:
        self.state = "PLAY"
        self.audio_strong = AUDIO_STRONG
        self._mute_streak = 0.0
        self._play_streak = 0.0
        self._muted_at: float | None = None
        self._human_cover = False

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
        self._human_cover = after == "MUTED"
        return event

    def step(self, timestamp: float, dt: float, families: dict) -> dict | None:
        if self.state == "PLAY":
            self._play_streak = 0.0
            yes, need, tag, persist = _quorum(families, depart=True, audio_strong=self.audio_strong)
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

        # Verified booth, or the enrolled show over 0.10: do not sit through the hold.
        booth = _booth_heard(families.get("speaker")) or _show_floor(families.get("speaker"))
        held = (
            not booth
            and self._muted_at is not None
            and timestamp - self._muted_at + 1e-9 < MIN_MUTE_HOLD_S
        )
        yes, need, tag, persist = _quorum(families, depart=False)
        if self._human_cover and tag == "booth_voice":
            persist = max(persist, HUMAN_COVER_RETURN_PERSIST_S)
        if held or yes < need:
            self._play_streak = 0.0
            return None
        self._play_streak += dt
        if self._play_streak + 1e-9 < persist:
            return None
        self.state = "PLAY"
        self._muted_at = None
        self._play_streak = 0.0
        self._human_cover = False
        return self._event(timestamp, "PLAY", families, tag, False)

    def restore_from_output(self, timestamp: float, families: dict) -> dict | None:
        """The speakers are already back. A hand on Cover is left covered."""
        if self.state != "MUTED" or self._human_cover:
            return None
        event = self._event(timestamp, "PLAY", families, "output_fail_open", False)
        self.state = "PLAY"
        self._muted_at = None
        self._mute_streak = 0.0
        self._play_streak = 0.0
        return event

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


def _family_yes(name: str, reading: dict, *, depart: bool, audio_strong: float = AUDIO_STRONG) -> bool:
    """Product vote. Audio uses the raw distance so thresholds stay in policy.py."""
    if depart:
        if name == "audio":
            value = reading.get("departure")
            if value is not None:
                return float(value) >= audio_strong
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
    """True when the family has a real score — identity metadata alone does not count."""
    if reading is None:
        return False
    # Active booth protection (speech or bounded outro hold) is real evidence.
    if reading.get("booth_present"):
        return True
    if reading.get("departure") is not None or reading.get("return") is not None:
        return True
    return bool(reading.get("strong_departure") or reading.get("strong_return"))


def _booth_match(speaker: dict) -> bool:
    """Verified booth speech.

    A published similarity decides. `booth_present=true` with a similarity
    below SPEAKER_BOOTH_MATCH is a contradiction, not a match. That is the
    October 8 run29 pattern (cluster outside the trusted ids, similarity
    ~0.12–0.18, flag still true).

    When no similarity was published, a cluster id that is in this row's
    `booth_ids` is still trusted. That path is explicit and unproven: cluster
    ids were not shown to survive an engine restart as the same person.
    """
    sim = speaker.get("similarity_to_booth")
    if sim is not None:
        return float(sim) + 1e-9 >= SPEAKER_BOOTH_MATCH
    cluster = speaker.get("cluster_id")
    trusted = {str(item) for item in (speaker.get("booth_ids") or [])}
    return bool(cluster) and str(cluster) in trusted


def _booth_heard(speaker: dict | None) -> bool:
    """True only when a verified booth announcer is speaking now."""
    if not speaker or not speaker.get("speech"):
        return False
    return _booth_match(speaker)


def _booth_still_talking(speaker: dict | None) -> bool:
    """Verified booth speech, or a bounded outro that the similarity does not contradict."""
    if not speaker:
        return False
    if _booth_heard(speaker):
        return True
    if speaker.get("speech"):
        return False
    sim = speaker.get("similarity_to_booth")
    if sim is not None and float(sim) + 1e-9 < SPEAKER_BOOTH_MATCH:
        return False
    # Outro hold: daemon may keep booth_present=True briefly after the last line.
    return bool(speaker.get("booth_present"))


def _present_for(families: dict, *, depart: bool) -> dict:
    """Families that may vote. Non-booth speaker chatter does not raise the mute bar."""
    out: dict = {}
    for name, reading in families.items():
        if not _alive(reading):
            continue
        if depart and name == "speaker":
            if _booth_still_talking(reading):
                out[name] = reading
            elif reading.get("strong_departure"):
                out[name] = reading
            # else: speaker unavailable for commercial detection
            continue
        # A person who is not a return vote must not hold the mute.
        # Tonight: Herbstreit stayed on the air, audio had already returned,
        # and his unrecognized voice kept the quorum at 2-of-2.
        if not depart and name == "speaker" and not _family_yes(name, reading, depart=False):
            continue
        out[name] = reading
    return out


def _show_floor(speaker: dict | None) -> bool:
    """True when the enrolled show is at or over 0.10 in the last 30 seconds."""
    if not isinstance(speaker, dict):
        return False
    rolling = speaker.get("enroll_rolling_max")
    if rolling is None:
        return False
    try:
        return show_present(float(rolling))
    except (TypeError, ValueError):
        return False


def _quorum(families: dict, *, depart: bool, audio_strong: float = AUDIO_STRONG) -> tuple[int, int, str, float]:
    """Return (yes_votes, needed, reason_tag, persist_s)."""
    speaker_reading = families.get("speaker")
    if _show_floor(speaker_reading if isinstance(speaker_reading, dict) else None):
        if depart:
            return 0, 10**9, "show_floor", 10**9
        return 1, 1, "show_floor", BOOTH_RETURN_PERSIST_S
    present = _present_for(families, depart=depart)
    yes = sum(
        1
        for name, reading in present.items()
        if _family_yes(name, reading, depart=depart, audio_strong=audio_strong)
    )
    if not present:
        return 0, 10**9, "no_families", 10**9
    # Verified booth voice → leave cover immediately.
    if not depart:
        speaker = present.get("speaker")
        if _booth_heard(speaker):
            return 1, 1, "booth_voice", BOOTH_RETURN_PERSIST_S
        if speaker is not None and _family_yes("speaker", speaker, depart=False):
            return 1, 1, "speaker_return", SOLO_SPEAKER_PLAY_PERSIST_S
    # Protect verified booth speech / outro hold only — never "booth_locked" alone.
    speaker = present.get("speaker")
    if depart and _booth_still_talking(speaker):
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
