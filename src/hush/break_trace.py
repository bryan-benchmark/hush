"""What changed, and why the action is play or cover.

A step records the speech score, the music score, and whether this show's
booth is over the published line. The voice floor is a separate module for
the return: the show is back at 0.10. It is a placeholder, and it does not
decide the cut into a commercial. The only
cover this module will authorize is one passed in from an already published
rule. A song arriving, or the booth dropping under the line, is written down
and does not mute.
"""

from __future__ import annotations

from hush.voice_floor import decide as voice_floor_decide

MUSIC_LOW = 0.30
MUSIC_HIGH = 0.70
BOOTH_LINE = 0.25
ARM_MEMORY_S = 20.0
CONFIRM_WITHIN_S = 30.0


def pattern(music: float, booth_over_line: bool) -> str:
    if booth_over_line and music >= MUSIC_HIGH:
        return "booth_over_song"
    if booth_over_line and music < MUSIC_LOW:
        return "booth_over_quiet"
    if booth_over_line:
        return "booth"
    if music >= MUSIC_HIGH:
        return "song_without_booth"
    if music < MUSIC_LOW:
        return "quiet_without_booth"
    return "in_between"


def changes(previous: dict | None, music: float, booth_over_line: bool) -> list[str]:
    if previous is None:
        return []
    found = []
    if previous["music"] < MUSIC_LOW and music >= MUSIC_HIGH:
        found.append("music_rose")
    if previous["music"] >= MUSIC_HIGH and music < MUSIC_LOW:
        found.append("music_fell")
    if previous["booth_over_line"] and not booth_over_line:
        found.append("booth_left")
    if booth_over_line and not previous["booth_over_line"]:
        found.append("booth_returned")
    if music >= MUSIC_HIGH and previous["pattern"] != pattern(music, booth_over_line):
        found.append("pattern_changed")
    return found


def decide(
    found: list[str],
    authorized_cover: bool,
    rolling_max: float | None = None,
) -> dict:
    """Candidates are observations. Cover requires an outside authorization.

    The voice floor is the return module. It can keep the action on play.
    It cannot start a commercial, and it cannot authorize a cover.
    """
    candidates = []
    blocked = []
    if "music_rose" in found:
        candidates.append("song_arrived_under_the_broadcast")
        blocked.append("a song under the booth is still the broadcast")
    if "booth_left" in found:
        candidates.append("booth_dropped_under_the_line")
        blocked.append("the booth cosine falling is not a commercial")
    voice = None if rolling_max is None else voice_floor_decide(rolling_max)
    if voice and voice["show_present"]:
        blocked.append("the show is back over the 0.10 floor")
    elif voice and voice["show_present"] is False:
        blocked.append(voice["reason"])
    if authorized_cover:
        decision = {
            "action": "cover",
            "authorized_by": "universal_v1_count_200",
            "candidates": candidates,
            "blocked": [],
        }
    else:
        if not blocked:
            blocked.append("no authorized commercial evidence")
        decision = {
            "action": "play",
            "authorized_by": None,
            "candidates": candidates,
            "blocked": blocked,
        }
    if voice is not None:
        decision["voice_floor"] = voice
    return decision


def sentence(found: list[str], decision: dict, booth_name: str | None) -> str:
    who = booth_name or "the booth"
    parts = []
    if "music_rose" in found:
        parts.append(f"Music rose while {who} was the recent voice.")
    if "music_fell" in found:
        parts.append("Music fell back under the quiet line.")
    if "booth_left" in found:
        parts.append(f"{who} dropped under the voice line.")
    if "booth_returned" in found:
        parts.append(f"{who} is back over the voice line.")
    if decision["action"] == "cover":
        parts.append("Cover. A published fingerprint at count 200 matched known commercial audio.")
    else:
        parts.append("Play. " + decision["blocked"][0].capitalize() + ".")
    return " ".join(parts)


class SignOff:
    """Song arrives while the booth was just here, then the booth is under the line.

    This marks a candidate. It never returns a cover.
    """

    def __init__(self) -> None:
        self.recent_booth: list[float] = []
        self.armed_at: float | None = None
        self.confirmed = False
        self.music: float | None = None

    def step(self, t: float, music: float, booth_over_line: bool, music_rose: bool) -> str | None:
        self.recent_booth = [old for old in self.recent_booth if t - old <= ARM_MEMORY_S]
        if booth_over_line:
            self.recent_booth.append(t)
        if self.music is not None and music < MUSIC_LOW:
            self.armed_at = None
            self.confirmed = False
        event = None
        if music_rose and self.recent_booth and self.armed_at is None:
            self.armed_at = t
            event = "arm"
        elif (
            self.armed_at is not None
            and not self.confirmed
            and t - self.armed_at <= CONFIRM_WITHIN_S
            and music >= MUSIC_HIGH
            and not booth_over_line
        ):
            self.confirmed = True
            event = "confirm"
        self.music = music
        return event
