"""One decision step for replay and live shadow.

The step calls the existing Machine. It does not start a cover on the
speakers. Raw scores stay raw: nothing here is a probability.

A reading may be used only after both the audio it describes and the score
itself are available. A missing or stale reading is not evidence of a
commercial. While an automatic cover is up, no usable reading fails open
to play. A cover a person started is left alone.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hush.voice_floor import FLOOR  # noqa: E402
from ohush_live.policy import (
    AUDIO_RETURN,
    AUDIO_STRONG,
    BOOTH_RETURN_PERSIST_S,
    MIN_MUTE_HOLD_S,
    MUTE_PERSIST_S,
    PLAY_PERSIST_S,
    PRODUCT,
    SOLO_MUTE_PERSIST_S,
    SOLO_PLAY_PERSIST_S,
)
from ohush_live.state import Machine

BRIDGE = "NFL75_BRIDGE_001"
# Freshness only. Not a mute threshold. A score older than this is absent.
EVIDENCE_STALE_S = 15.0
# A hole longer than this does not count as sustained evidence.
HOLE_S = 2.0
FAMILIES = ("audio", "speaker", "semantic")
FORBIDDEN = frozenset({"gold", "labels", "label", "retrospective", "gold_end", "future_audio"})
_EPS = 1e-6


def configuration() -> dict:
    body = {
        "bridge": BRIDGE,
        "product": PRODUCT,
        "audio_strong": AUDIO_STRONG,
        "audio_return": AUDIO_RETURN,
        "solo_mute_persist_s": SOLO_MUTE_PERSIST_S,
        "solo_play_persist_s": SOLO_PLAY_PERSIST_S,
        "mute_persist_s": MUTE_PERSIST_S,
        "play_persist_s": PLAY_PERSIST_S,
        "min_mute_hold_s": MIN_MUTE_HOLD_S,
        "booth_return_persist_s": BOOTH_RETURN_PERSIST_S,
        "show_floor": FLOOR,
        "evidence_stale_s": EVIDENCE_STALE_S,
        "automatic_mute_enabled": False,
    }
    digest = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    body["id"] = digest[:16]
    return body


def _reject_forbidden(payload: dict, where: str) -> None:
    found = FORBIDDEN.intersection(payload)
    if found:
        raise ValueError(f"{where} carries {sorted(found)}; the decision step does not read it")


def evidence_from_families(audio_time: float, families: dict | None) -> dict:
    """Stamp live readings that did not bring their own availability time.

    Those readings are available at `audio_time`. They do not describe audio
    after that instant.
    """
    families = families or {}
    readings = []
    for name in FAMILIES:
        raw = families.get(name)
        if not isinstance(raw, dict):
            readings.append(
                {"family": name, "raw": None, "audio_end_s": None, "available_at_s": None}
            )
            continue
        body = {key: value for key, value in raw.items() if key not in ("audio_end_s", "available_at_s")}
        audio_end = raw.get("audio_end_s", audio_time)
        available = raw.get("available_at_s", audio_time)
        readings.append(
            {
                "family": name,
                "raw": body,
                "audio_end_s": None if audio_end is None else float(audio_end),
                "available_at_s": None if available is None else float(available),
            }
        )
    return {"readings": readings}


class Bridge:
    def __init__(self) -> None:
        self.machine = Machine()
        self.configuration = configuration()
        self._last_t: float | None = None

    def reset(self) -> None:
        self.machine = Machine()
        self._last_t = None

    def manual(self, audio_time: float, action: str, evidence: dict | None = None) -> dict:
        if action not in ("play", "mute"):
            raise ValueError(action)
        packet = evidence or {"readings": []}
        _reject_forbidden(packet, "evidence")
        families = _usable_families(float(audio_time), packet)[0]
        event = self.machine.manual(float(audio_time), action, families)
        self._last_t = float(audio_time)
        played = "PLAY" if action == "play" else "COVER"
        return self._decision(
            float(audio_time),
            played,
            "manual",
            [],
            applied=False,
        ) | {"state_after": event["state_after"]}

    def step(self, audio_time: float, evidence: dict) -> dict:
        audio_time = float(audio_time)
        if not isinstance(evidence, dict):
            raise TypeError("evidence must be a dict of readings")
        _reject_forbidden(evidence, "evidence")
        if self._last_t is not None and audio_time < self._last_t - _EPS:
            raise ValueError("decision time moved backwards")
        if self._last_t is not None and abs(audio_time - self._last_t) <= _EPS:
            return self._decision(audio_time, "NO_CHANGE", "same_instant", [], applied=False)
        dt = 1.0 if self._last_t is None else audio_time - self._last_t
        if dt > HOLE_S:
            self.machine._mute_streak = 0.0
            self.machine._play_streak = 0.0
            dt = 1.0
        families, trace = _usable_families(audio_time, evidence)
        self._last_t = audio_time
        if not families:
            return self._fail_open(audio_time, trace)
        event = self.machine.step(audio_time, dt, families)
        if event is None:
            return self._decision(audio_time, "NO_CHANGE", "holding", trace, applied=False)
        action = "COVER" if event["state_after"] == "MUTED" else "PLAY"
        return self._decision(audio_time, action, event["reason"], trace, applied=False)

    def _fail_open(self, audio_time: float, trace: list[dict]) -> dict:
        if self.machine.state == "MUTED" and not self.machine._human_cover:
            self.machine.restore_from_output(audio_time, {})
            return self._decision(audio_time, "PLAY", "stale_fail_open", trace, applied=False)
        if self.machine.state == "MUTED" and self.machine._human_cover:
            return self._decision(audio_time, "NO_CHANGE", "human_cover_held", trace, applied=False)
        return self._decision(audio_time, "NO_CHANGE", "missing_or_stale", trace, applied=False)

    def _decision(self, audio_time: float, action: str, reason: str, trace: list[dict], *, applied: bool) -> dict:
        return {
            "bridge": BRIDGE,
            "configuration_id": self.configuration["id"],
            "product": PRODUCT,
            "audio_time": round(audio_time, 3),
            "action": action,
            "reason": reason,
            "applied": applied,
            "automatic_mute_enabled": False,
            "evidence": trace,
        }


def _usable_families(audio_time: float, evidence: dict) -> tuple[dict, list[dict]]:
    families: dict = {}
    trace: list[dict] = []
    readings = evidence.get("readings") or []
    for reading in readings:
        if not isinstance(reading, dict):
            raise TypeError("a reading must be a dict")
        _reject_forbidden(reading, "reading")
        raw = reading.get("raw")
        if isinstance(raw, dict):
            _reject_forbidden(raw, "raw score")
        name = str(reading.get("family") or "")
        status, age = _status(audio_time, reading)
        trace.append(
            {
                "family": name,
                "audio_end_s": reading.get("audio_end_s"),
                "available_at_s": reading.get("available_at_s"),
                "age_s": None if age is None else round(age, 3),
                "status": status,
                "raw": raw if isinstance(raw, dict) else None,
            }
        )
        if status == "used" and isinstance(raw, dict) and name in FAMILIES:
            families[name] = raw
    return families, trace


def _status(audio_time: float, reading: dict) -> tuple[str, float | None]:
    raw = reading.get("raw")
    if not isinstance(raw, dict):
        return "missing", None
    audio_end = reading.get("audio_end_s")
    available = reading.get("available_at_s")
    if audio_end is None or available is None:
        return "missing", None
    ready = max(float(audio_end), float(available))
    if float(audio_end) > float(available) + _EPS:
        return "future_audio", None
    if ready > audio_time + _EPS:
        return "not_yet_available", None
    age = audio_time - ready
    if age > EVIDENCE_STALE_S:
        return "stale", age
    return "used", age


def replay(rows: list[dict]) -> list[dict]:
    """Offline path. Each row is one decision time and the readings available then."""
    bridge = Bridge()
    decisions = []
    for row in rows:
        if not isinstance(row, dict):
            raise TypeError("replay row must be a dict")
        _reject_forbidden(row, "replay row")
        evidence = {"readings": row.get("readings") or []}
        decisions.append(bridge.step(float(row["audio_time"]), evidence))
    return decisions


def live_shadow(rows: list[dict]) -> list[dict]:
    """Live shadow path. Same step as replay. Speakers are not in this function."""
    from ohush_live.shadow import Shadow

    shadow = Shadow()
    return [shadow.observe_evidence(float(row["audio_time"]), {"readings": row.get("readings") or []}) for row in rows]


def carry_out(gate, decision: dict, *, enabled: bool) -> dict:
    """Move the existing gate only when the experimental switch is on.

    The default is off. A return uses the gate's automatic fade, which is
    1.5 seconds, not the shorter manual fade.
    """
    if not enabled:
        return {"applied": False, "reason": "automatic_mute_disabled", "return_fade_s": None}
    action = decision.get("action")
    if action == "COVER":
        gate.play_replacement()
        return {"applied": True, "hearing": "replacement", "return_fade_s": None}
    if action == "PLAY" and (gate.mode == "replacement" or gate._pending_program):
        gate.play_program(prompt=False)
        return {"applied": True, "hearing": "program", "return_fade_s": gate._return_s}
    return {"applied": False, "reason": "no_change", "return_fade_s": None}
