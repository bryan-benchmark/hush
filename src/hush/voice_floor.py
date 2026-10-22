"""When the enrolled show is back, so the audio can come back.

The labels were made for the return. A score at or over 0.10 means the show
is here again. The cut into a commercial is a different model and is not
this one. 0.10 is a placeholder for the return, not an optimized start.

The published SpeechBrain line stays 0.25. That constant was chosen before
these tapes. On the labeled football, with the 3-second enrollment and a
30-second rolling max, using 0.15 or 0.20 as a mute would turn the show off.
0.10 would not. The one game-column hit at 0.10 is a promo.

This module does not mute. A missing voice does not start a commercial.
"""

from __future__ import annotations

FLOOR = 0.10
MEMORY_S = 30.0
# Return only. The commercial cut is a different model.
ROLE = "return"
GAME_S = 67428
COMMERCIAL_S = 17648.4

# Seconds the sound would be off, after the postgame tape, the local news,
# and the unmarked spots were taken out of the game column. Not a fitted mute.
MEASURED = (
    {"line": 0.10, "ad_off_s": 288, "game_off_s": 4},
    {"line": 0.15, "ad_off_s": 1036, "game_off_s": 112},
    {"line": 0.20, "ad_off_s": 2612, "game_off_s": 324},
    {"line": 0.25, "ad_off_s": 4956, "game_off_s": 736},
)

# Stretches that pick the floor. The 0.10 row is a promo. The 0.15 rows are
# the show. The 0.20 row is a booth call.
RECEIPTS = (
    {
        "line": 0.10,
        "keeps_the_floor": True,
        "session": "hush_20260914_212529",
        "network": "ESPN",
        "start": 5788,
        "seconds": 4,
        "peak": 0.041,
        "who": "Troy Aikman",
        "heard": "Giants, Rams, at eight on ABC and ESPN",
        "what": "network promo",
    },
    {
        "line": 0.15,
        "keeps_the_floor": False,
        "session": "hush_20260914_212529",
        "network": "ESPN",
        "start": 1144,
        "seconds": 40,
        "peak": 0.147,
        "who": "Troy Aikman",
        "heard": "They'll hit the sacks. The way you neutralize those",
        "what": "Allstate halftime",
    },
    {
        "line": 0.15,
        "keeps_the_floor": False,
        "session": "hush_20260914_212529",
        "network": "ESPN",
        "start": 6728,
        "seconds": 40,
        "peak": 0.149,
        "who": "Joe Buck",
        "heard": "He did a great job stepping in, filling in",
        "what": "Kenneth Walker interview",
    },
    {
        "line": 0.15,
        "keeps_the_floor": False,
        "session": "hush_20260914_212529",
        "network": "ESPN",
        "start": 1080,
        "seconds": 12,
        "peak": 0.106,
        "who": "Troy Aikman",
        "heard": "Welcome to the Allstate halftime",
        "what": "Allstate halftime",
    },
    {
        "line": 0.15,
        "keeps_the_floor": False,
        "session": "hush_20260914_212529",
        "network": "ESPN",
        "start": 3804,
        "seconds": 4,
        "peak": 0.123,
        "who": "Joe Buck",
        "heard": "the biggest night of both of our lives",
        "what": "sideline interview",
    },
    {
        "line": 0.15,
        "keeps_the_floor": False,
        "session": "hush_20260914_212529",
        "network": "ESPN",
        "start": 2208,
        "seconds": 4,
        "peak": 0.145,
        "who": "Joe Buck",
        "heard": "The puck drops September 29th on ESPN",
        "what": "promo",
    },
    {
        "line": 0.15,
        "keeps_the_floor": False,
        "session": "hush_20260914_212529",
        "network": "ESPN",
        "start": 4676,
        "seconds": 4,
        "peak": 0.148,
        "who": "Joe Buck",
        "heard": "We'll see you next time",
        "what": "sign-off",
    },
    {
        "line": 0.15,
        "keeps_the_floor": False,
        "session": "hush_20260914_212529",
        "network": "ESPN",
        "start": 5788,
        "seconds": 4,
        "peak": 0.041,
        "who": "Troy Aikman",
        "heard": "Giants, Rams, at eight on ABC and ESPN",
        "what": "network promo",
    },
    {
        "line": 0.15,
        "keeps_the_floor": False,
        "session": "hush_20260924_220624",
        "network": "Prime",
        "start": 3004,
        "seconds": 4,
        "peak": 0.141,
        "who": "Ryan Fitzpatrick",
        "heard": "This Chili's 3 for me is the best $10.99 you can eat",
        "what": "unmarked commercial",
    },
    {
        "line": 0.20,
        "keeps_the_floor": False,
        "session": "hush_20260914_212529",
        "network": "ESPN",
        "start": 1316,
        "seconds": 12,
        "peak": 0.172,
        "who": "Joe Buck",
        "heard": "Isaiah Likely, one of two touchdowns",
        "what": "booth call",
    },
)


def show_present(rolling_max: float) -> bool:
    return rolling_max >= FLOOR


def decide(rolling_max: float | None) -> dict:
    """Whether the show is back. This does not start a commercial."""
    if rolling_max is None:
        present = None
        reason = "no voice score"
    elif show_present(rolling_max):
        present = True
        reason = "the show is back at or over 0.10"
    else:
        present = False
        reason = "under 0.10 does not start a commercial"
    return {
        "role": ROLE,
        "placeholder": True,
        "line": FLOOR,
        "memory_s": MEMORY_S,
        "rolling_max": rolling_max,
        "show_present": present,
        "starts_commercial": False,
        "mute": False,
        "reason": reason,
    }
