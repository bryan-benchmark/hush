"""Product rules for tonight. These are not Exp002–005 constants and must not be copied back into them.

Speaker drop 0.35 and return score 0.25 match the frozen listing definitions so the
live speaker vote means the same thing as a collapse or a return event. The audio
bars are product choices taken from the already-finished Prime overlay
(pod median about 0.20, program median about 0.06), not fit to tonight.
"""

PRODUCT = "OHUSH_LIVE_V0"

AUDIO_STRONG = 0.18
AUDIO_RETURN = 0.10
SPEAKER_DROP = 0.35
SPEAKER_RETURN = 0.25

MUTE_PERSIST_S = 3.0
PLAY_PERSIST_S = 5.0
MIN_MUTE_HOLD_S = 8.0

MIN_AGREE = 2
