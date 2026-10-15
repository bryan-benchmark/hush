"""Product rules for live cover. These are not Exp002–005 constants and must not be copied back into them.

Speaker drop / return listing bars still match Exp002 definitions for the speaker
worker. Audio bars below are product live thresholds fit to tonight's optical
sports feed (program usually ~0.05–0.10, ads rising through ~0.14–0.35). Exp003
offline MIN_REFERENCE_S=60 is intentionally NOT used here.

Quorum: missing families are unavailable, not a "no". Solo audio may mute when
speaker is null or not currently protecting the booth. Knowing booth identities
never blocks commercial detection by itself.

Exp001–005 scoring code is untouched.
"""

PRODUCT = "OHUSH_LIVE_V0"

AUDIO_STRONG = 0.22
AUDIO_RETURN = 0.12
# Live-only warm-up so the first break is not blind. Exp003 stays at 60s.
AUDIO_MIN_REFERENCE_S = 15.0
SPEAKER_DROP = 0.35
# Exp002 return listing floor. Product booth speech bypasses this — hearing
# a *verified* booth identity always lifts cover (see state._booth_heard).
SPEAKER_RETURN = 0.25
# Verified booth identity via embedding match (stricter than Exp002 cluster glue).
SPEAKER_BOOTH_MATCH = 0.55
# Bounded outro/bumper gap after the last *verified* booth line.
# Knowing who Al is must never imply he is still talking.
BOOTH_HOLD_S = 8.0
# Remember booth crew under ohush_live/sessions/.booth.json (identity only).
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
