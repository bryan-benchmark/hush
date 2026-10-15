"""Product rules for live cover. These are not Exp002–005 constants and must not be copied back into them.

Speaker drop / return listing bars still match Exp002 definitions for the speaker
worker. Audio bars below are product live thresholds fit to tonight's optical
sports feed (program usually ~0.05–0.10, ads rising through ~0.14–0.35). Exp003
offline MIN_REFERENCE_S=60 is intentionally NOT used here.

Quorum: missing families are unavailable, not a "no". Solo audio may mute when
speaker/semantic are null. Exp001–005 scoring code is untouched.
"""

PRODUCT = "OHUSH_LIVE_V0"

# Solo-audio cover is a last resort before the booth pair is locked.
# Tonight's false covers sat ~0.19–0.25 while Al was still in — raise the bar.
AUDIO_STRONG = 0.22
AUDIO_RETURN = 0.12
# Live-only warm-up so the first break is not blind. Exp003 stays at 60s.
AUDIO_MIN_REFERENCE_S = 15.0
SPEAKER_DROP = 0.35
# Exp002 return listing floor. Product booth speech bypasses this — hearing
# the locked announcer pair always lifts cover (see state._booth_heard).
SPEAKER_RETURN = 0.25
# Continuity that means any booth announcer is still in the mix.
SPEAKER_BOOTH_CONTINUITY = 0.12
# Al outro → bumper gap is often 6–10s of near-silence. Hold cover-off
# through that handoff so solo-audio cannot fire mid-outro.
BOOTH_HOLD_S = 12.0
# Lock the booth crew (play-by-play, color, and occasional sideline).
# Persisted under ohush_live/sessions/.booth.json across engine restarts.
BOOTH_MIN_CUMULATIVE_S = 6.0
BOOTH_MIN_OCCURRENCES = 2
BOOTH_TOP_N = 4

MUTE_PERSIST_S = 2.5
SOLO_MUTE_PERSIST_S = 4.0
PLAY_PERSIST_S = 3.0
SOLO_PLAY_PERSIST_S = 3.0
# Booth voice return is immediate — do not make the user wait out a hold.
BOOTH_RETURN_PERSIST_S = 0.0
SOLO_SPEAKER_PLAY_PERSIST_S = 1.0
MIN_MUTE_HOLD_S = 6.0

MIN_AGREE = 2
SOLO_FAMILY = "audio"
