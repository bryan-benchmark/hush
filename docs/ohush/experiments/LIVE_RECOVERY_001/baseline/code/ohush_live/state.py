"""Asymmetric mute state. Departure can mute. Return must be strong and persistent."""

from __future__ import annotations

from ohush_live.policy import (
    MIN_AGREE,
    MIN_MUTE_HOLD_S,
    MUTE_PERSIST_S,
    PLAY_PERSIST_S,
    PRODUCT,
)


class Machine:
    def __init__(self) -> None:
        self.state = "PLAY"
        self._mute_streak = 0.0
        self._play_streak = 0.0
        self._muted_at: float | None = None

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
        departure = _votes(families, "strong_departure")
        returning = _votes(families, "strong_return")
        if self.state == "PLAY":
            self._play_streak = 0.0
            if departure >= MIN_AGREE:
                self._mute_streak += dt
            else:
                self._mute_streak = 0.0
            if self._mute_streak + 1e-9 >= MUTE_PERSIST_S:
                self.state = "MUTED"
                self._muted_at = timestamp
                self._mute_streak = 0.0
                return self._event(timestamp, "MUTED", families, f"{MIN_AGREE}_of_strong", False)
            return None

        held = self._muted_at is not None and timestamp - self._muted_at + 1e-9 < MIN_MUTE_HOLD_S
        if held or returning < MIN_AGREE:
            self._play_streak = 0.0
            return None
        self._play_streak += dt
        if self._play_streak + 1e-9 < PLAY_PERSIST_S:
            return None
        self.state = "PLAY"
        self._muted_at = None
        self._play_streak = 0.0
        return self._event(timestamp, "PLAY", families, f"{MIN_AGREE}_of_return", False)

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


def _votes(families: dict, key: str) -> int:
    votes = 0
    for reading in families.values():
        if reading is None:
            continue
        if reading.get(key):
            votes += 1
    return votes


def _score(families: dict, name: str, kind: str) -> float | None:
    reading = families.get(name)
    if not reading:
        return None
    value = reading.get(kind)
    if value is None:
        return None
    return round(float(value), 4)
