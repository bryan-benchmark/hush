"""What the live machine would do. This never changes the speakers."""

from __future__ import annotations

from ohush_live.bridge import BRIDGE, evidence_from_families
from ohush_live.policy import PRODUCT


class Shadow:
    """Watch the shared bridge. `applied` stays false. The gate is not here."""

    def __init__(self) -> None:
        from ohush_live.bridge import Bridge

        self.bridge = Bridge()
        self.machine = self.bridge.machine
        self.pending: str | None = None
        self.last: dict | None = None
        self.last_decision: dict | None = None

    def observe_evidence(self, audio_time: float, evidence: dict) -> dict:
        decision = self.bridge.step(float(audio_time), evidence)
        self.last_decision = decision
        self.machine = self.bridge.machine
        return decision

    def observe(self, timestamp: float, families: dict) -> dict | None:
        decision = self.observe_evidence(timestamp, evidence_from_families(timestamp, families))
        if decision["action"] == "NO_CHANGE":
            return None
        would = "cover" if decision["action"] == "COVER" else "return"
        row = {
            "t": decision["audio_time"],
            "event": "shadow",
            "would": would,
            "applied": False,
            "reason": decision["reason"],
            "state_after": "MUTED" if decision["action"] == "COVER" else "PLAY",
            "product": PRODUCT,
            "bridge": BRIDGE,
            "configuration_id": decision["configuration_id"],
        }
        self.pending = would
        self.last = row
        return row

    def answer(self, timestamp: float, verdict: str) -> dict:
        if verdict not in ("confirm", "reject"):
            raise ValueError(verdict)
        row = {
            "t": round(float(timestamp), 3),
            "event": "shadow_answer",
            "verdict": verdict,
            "would": self.pending,
            "applied": False,
            "category": "known_commercial" if verdict == "confirm" and self.pending == "cover" else "uncertain",
            "product": PRODUCT,
        }
        self.pending = None
        self.last = row
        return row

    def view(self) -> dict:
        return {"state": self.machine.state, "pending": self.pending, "last": self.last}


def receipt(rows: list[dict]) -> dict:
    """Seconds the rule would have held. Program seconds still need a later label."""
    open_at: float | None = None
    held = 0.0
    covers = 0
    returns = 0
    confirms = 0
    rejects = 0
    for row in rows:
        if row.get("applied") is True:
            raise ValueError("a shadow row applied a cover")
        if row.get("event") == "shadow" and row.get("would") == "cover":
            covers += 1
            if open_at is None:
                open_at = float(row["t"])
        elif row.get("event") == "shadow" and row.get("would") == "return" and open_at is not None:
            returns += 1
            held += float(row["t"]) - open_at
            open_at = None
        elif row.get("event") == "shadow_answer" and row.get("verdict") == "confirm":
            confirms += 1
        elif row.get("event") == "shadow_answer" and row.get("verdict") == "reject":
            rejects += 1
    return {
        "would_cover": covers,
        "would_return": returns,
        "would_cover_s": round(held, 3),
        "confirms": confirms,
        "rejects": rejects,
        "applied": 0,
    }
