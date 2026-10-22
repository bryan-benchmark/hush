"""TNF lab. Opt-in experiment. Default is observe, which never touches playback.

Production Auto and policy.AUDIO_STRONG stay as they are. The 0.14 audio
line is a named hypothesis for this lab only. With machine return, a cover
stays up only while that score stays at or above the line. A missing score
or a score that stays below the line restores the television. Manual return
still waits for the person, with the same fail-open backstop. A human Cover
is left alone. Any automatic restore holds the next cover until the score
has been quiet, so one return cannot immediately mute the game again.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

PRODUCT = "TNF_LAB_001"
# Experimental hypothesis. Not policy.AUDIO_STRONG (0.22).
AUDIO_DEPART = 0.14
DEPART_HOLD_S = 2.0
CLEAR_HOLD_S = 2.0
RETURN_HOLD_S = 2.5
DEFAULT_FAIL_OPEN_S = 180.0
BOOTH_SIMILARITY = 0.55

MODES = ("observe", "suggest", "auto")
RETURN_POLICIES = ("manual", "machine")


def predictions(families: dict | None, audio_depart: float = AUDIO_DEPART) -> list[dict]:
    families = families or {}
    audio = families.get("audio")
    speaker = families.get("speaker")
    audio_score = None if not isinstance(audio, dict) else audio.get("departure")
    try:
        audio_score_f = None if audio_score is None else float(audio_score)
    except (TypeError, ValueError):
        audio_score_f = None
    audio_known = isinstance(audio, dict)
    speaker_known = isinstance(speaker, dict)
    audio_strong = bool(audio_known and audio.get("strong_departure"))
    audio_hyp = audio_score_f is not None and audio_score_f >= float(audio_depart)
    booth = _booth_return(speaker)
    speaker_depart = bool(speaker_known and speaker.get("strong_departure"))
    speaker_blocking = bool(speaker_known and speaker.get("speech") and speaker.get("booth_present") and not speaker_depart)
    quorum_ad = audio_known and audio_strong and not speaker_blocking
    combo_ad = audio_known and audio_hyp and not speaker_blocking
    return [
        {
            "id": "live_quorum",
            "label": "Live quorum",
            "call": _call(quorum_ad, audio_known),
            "score": audio_score_f,
            "status": "live",
            "source": "existing audio worker, strong_departure",
        },
        {
            "id": "departure_combo",
            "label": "Departure combo",
            "call": _call(combo_ad, audio_known),
            "score": audio_score_f,
            "status": "live",
            "source": f"audio>={float(audio_depart):.2f} and booth not blocking",
        },
        {
            "id": "fingerprint",
            "label": "Causal fingerprint",
            "call": "unsure",
            "score": None,
            "status": "not_run",
            "source": "not on the live clock",
        },
    ]


def _call(ad: bool, known: bool) -> str:
    if not known:
        return "unsure"
    return "ad" if ad else "game"


def _booth_return(speaker: dict | None) -> bool:
    if not isinstance(speaker, dict):
        return False
    if not (speaker.get("speech") and speaker.get("booth_present")):
        return False
    try:
        similarity = float(speaker.get("similarity_to_booth") or 0.0)
    except (TypeError, ValueError):
        similarity = 0.0
    return similarity >= BOOTH_SIMILARITY


class TnfLab:
    def __init__(self, log_path: Path | None = None) -> None:
        self.mode = "observe"
        self.return_policy = "manual"
        self.fail_open_s = DEFAULT_FAIL_OPEN_S
        self.phase = 1
        self.covering = False
        self.cover_started_at: float | None = None
        self.cover_source = ""
        self.suppress = False
        self.depart_streak = 0.0
        self.clear_streak = 0.0
        self.score_clear_streak = 0.0
        self.return_streak = 0.0
        self.suggested_starts = 0
        self.machine_covers = 0
        self.manual_rescues = 0
        self.last_reason = "observe"
        self.audio_depart = AUDIO_DEPART
        self.last_score: float | None = None
        self.last_source = "departure_combo"
        self.suggestion = "unsure"
        self.transitions: list[dict] = []
        self._was_probably_ad = False
        self._return_open = False
        self._last_heartbeat = -999.0
        self._error = ""
        self._lock = threading.RLock()
        self._log_handle = None
        if log_path is not None:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            self._log_handle = log_path.open("a", encoding="utf-8")

    def close(self) -> None:
        with self._lock:
            if self._log_handle is not None:
                self._log_handle.close()
                self._log_handle = None

    def configure(
        self,
        *,
        mode: str | None = None,
        return_policy: str | None = None,
        fail_open_s: float | None = None,
        audio_depart: float | None = None,
        t: float = 0.0,
    ) -> dict:
        with self._lock:
            changed = False
            leave_auto = False
            if mode is not None:
                if mode not in MODES:
                    raise ValueError(mode)
                if mode != self.mode:
                    leave_auto = self.mode == "auto" and mode != "auto"
                    self.mode = mode
                    changed = True
            if return_policy is not None:
                if return_policy not in RETURN_POLICIES:
                    raise ValueError(return_policy)
                if return_policy != self.return_policy:
                    self.return_policy = return_policy
                    changed = True
            if fail_open_s is not None:
                capped = float(max(30.0, min(600.0, fail_open_s)))
                if capped != self.fail_open_s:
                    self.fail_open_s = capped
                    changed = True
            if audio_depart is not None:
                bar = float(audio_depart)
                if bar < 0.10 or bar > 0.45:
                    raise ValueError(audio_depart)
                if bar != self.audio_depart:
                    self.audio_depart = bar
                    changed = True
            if changed:
                self.phase += 1
                self._event(t, 0, "phase", self.mode, "user_config")
            if leave_auto:
                self.covering = False
                self.cover_started_at = None
                self.last_reason = "left_auto"
                self._event(t, 0, "play", "observe", "left_auto")
            return {"audio": "play" if leave_auto else None}

    def kill(self, t: float = 0.0) -> dict:
        with self._lock:
            self.mode = "observe"
            self.covering = False
            self.cover_started_at = None
            self.suppress = False
            self.phase += 1
            self.last_reason = "kill"
            self._event(t, 0, "play", "observe", "kill")
            return {"audio": "play"}

    def fail_open(self, reason: str, t: float = 0.0) -> dict:
        with self._lock:
            self.mode = "observe"
            self.covering = False
            self.cover_started_at = None
            self._error = reason[:240]
            self.last_reason = "error_fail_open"
            self.phase += 1
            self._event(t, 0, "play", "observe", "error_fail_open")
            return {"audio": "play"}

    def note_human(self, action: str, t: float, sample_index: int = 0) -> None:
        with self._lock:
            if action == "play":
                if self.covering:
                    self.manual_rescues += 1
                self.covering = False
                self.cover_started_at = None
                self.suppress = True
                self.clear_streak = 0.0
                self.score_clear_streak = 0.0
                self.last_reason = "human_show"
                self._event(t, sample_index, "play", self.mode, "human_show")
            elif action == "mute":
                self.covering = True
                self.cover_started_at = t
                self.cover_source = "human"
                self.suppress = False
                self.last_reason = "human_cover"
                self._event(t, sample_index, "cover", self.mode, "human_cover")

    def release(self, t: float, sample_index: int, reason: str) -> str | None:
        """Drop a machine cover so the speakers match a pass-through or a gate timeout.

        Human Cover is deliberate silence and is cleared only by Record only,
        kill, or Show the game.
        """
        with self._lock:
            if not self.covering:
                return None
            if self.cover_source == "human" and reason not in ("record_only", "kill", "human_show"):
                return None
            return self._release_locked(t, sample_index, reason)

    def _release_locked(self, t: float, sample_index: int, reason: str) -> str:
        self.covering = False
        self.cover_started_at = None
        self.suppress = True
        self.clear_streak = 0.0
        self.score_clear_streak = 0.0
        self.return_streak = 0.0
        self.last_reason = reason
        self._event(t, sample_index, "play", "auto" if self.mode == "auto" else self.mode, reason)
        return "play"

    def label(self, verdict: str, t: float, about: float | None, sample_index: int = 0) -> None:
        if verdict not in ("commercial", "program", "unsure"):
            return
        with self._lock:
            self._write(
                {
                    "event": "human_label",
                    "verdict": verdict,
                    "t": round(t, 3),
                    "about": None if about is None else round(about, 3),
                    "sample_index": int(sample_index),
                    "wall_monotonic": round(time.monotonic(), 3),
                    "reaction": "manual",
                    "phase": self.phase,
                    "mode": self.mode,
                    "product": PRODUCT,
                    "overwrites_prediction": False,
                }
            )

    def tick(self, t: float, sample_index: int, families: dict | None, *, record_only: bool = False, dt: float = 1.0) -> dict:
        with self._lock:
            rows = predictions(families, self.audio_depart)
            combo = next(row for row in rows if row["id"] == "departure_combo")
            self.last_score = combo["score"]
            ad = combo["call"] == "ad"
            if ad:
                self.depart_streak += dt
                self.clear_streak = 0.0
            else:
                self.clear_streak += dt
                self.depart_streak = 0.0
            # Authorization is the departure score itself. Booth blocking is a
            # separate return path. A missing score is not authorization.
            score_hot = self.last_score is not None and self.last_score >= self.audio_depart
            if score_hot:
                self.score_clear_streak = 0.0
            else:
                self.score_clear_streak += dt
            if self.suppress and self.score_clear_streak >= CLEAR_HOLD_S:
                self.suppress = False
            booth = _booth_return((families or {}).get("speaker"))
            if booth:
                self.return_streak += dt
            else:
                self.return_streak = 0.0
                self._return_open = False
            if booth and not self._return_open:
                self._return_open = True
                self._event(t, sample_index, "return_candidate", self.mode, "booth_similarity")
            probably_ad = self.depart_streak >= DEPART_HOLD_S
            if probably_ad and not self._was_probably_ad:
                self.suggested_starts += 1
            self._was_probably_ad = probably_ad
            if probably_ad:
                self.suggestion = "probably_ad"
            elif booth:
                self.suggestion = "probably_game"
            else:
                self.suggestion = "unsure"
            audio = None
            if record_only and self.covering:
                audio = self._release_locked(t, sample_index, "record_only")
            elif self.mode == "auto" and not record_only and self.covering:
                elapsed = 0.0 if self.cover_started_at is None else t - self.cover_started_at
                # A hand on Cover is deliberate silence. Machine covers are not.
                if self.cover_source == "human":
                    pass
                elif self.return_policy == "machine" and self.return_streak >= RETURN_HOLD_S:
                    audio = self._release_locked(t, sample_index, "positive_booth_return")
                elif self.return_policy == "machine" and self.score_clear_streak >= CLEAR_HOLD_S:
                    audio = self._release_locked(t, sample_index, "departure_cleared")
                elif elapsed >= self.fail_open_s:
                    audio = self._release_locked(t, sample_index, "fail_open")
            elif self.mode == "auto" and not record_only and not self.suppress and probably_ad and not self.covering:
                self.covering = True
                self.cover_started_at = t
                self.cover_source = "machine"
                self.machine_covers += 1
                self.last_reason = "departure_combo"
                audio = "cover"
                self._event(t, sample_index, "cover", "auto", "departure_combo")
            elif self.mode != "auto":
                self.last_reason = self.suggestion
            if t - self._last_heartbeat >= 5.0:
                self._last_heartbeat = t
                self._event(t, sample_index, "heartbeat", self.mode, self.last_reason)
            return {"audio": audio, "view": self.view_locked(t)}

    def view(self, t: float = 0.0) -> dict:
        with self._lock:
            return self.view_locked(t)

    def view_locked(self, t: float) -> dict:
        elapsed = None
        if self.covering and self.cover_started_at is not None:
            elapsed = round(max(0.0, t - self.cover_started_at), 1)
        return {
            "product": PRODUCT,
            "mode": self.mode,
            "return_policy": self.return_policy,
            "fail_open_s": self.fail_open_s,
            "audio_depart": self.audio_depart,
            "phase": self.phase,
            "covering": self.covering,
            "cover_elapsed_s": elapsed,
            "cover_source": self.cover_source,
            "suggestion": self.suggestion,
            "last_reason": self.last_reason,
            "last_score": self.last_score,
            "last_source": self.last_source,
            "suggested_starts": self.suggested_starts,
            "machine_covers": self.machine_covers,
            "manual_rescues": self.manual_rescues,
            "transitions": list(self.transitions[-5:]),
            "fingerprint": "not_run",
            "error": self._error,
            "suppress": self.suppress,
            "start": "machine" if self.mode == "auto" else "manual",
            "return": self.return_policy,
        }

    def _event(self, t: float, sample_index: int, kind: str, mode: str, reason: str) -> None:
        row = {
            "event": kind,
            "t": round(float(t), 3),
            "sample_index": int(sample_index),
            "wall_monotonic": round(time.monotonic(), 3),
            "mode": mode,
            "phase": self.phase,
            "reason": reason,
            "return_policy": self.return_policy,
            "fail_open_s": self.fail_open_s,
            "suggestion": self.suggestion,
            "score": self.last_score,
            "covering": self.covering,
            "cover_elapsed_s": (
                None
                if not self.covering or self.cover_started_at is None
                else round(max(0.0, float(t) - self.cover_started_at), 1)
            ),
            "product": PRODUCT,
        }
        if kind != "heartbeat":
            self.transitions.append({"t": row["t"], "kind": kind, "reason": reason})
            if len(self.transitions) > 40:
                del self.transitions[:20]
        self._write(row)

    def _write(self, row: dict) -> None:
        if self._log_handle is None:
            return
        self._log_handle.write(json.dumps(row) + "\n")
        self._log_handle.flush()
