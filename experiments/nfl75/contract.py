"""Product acceptance for Prime Thursday Night Football. Not the research ladder.

The research score stays in docs/ohush/research/ACCURACY_LADDER_001/KPI.md.
A muted second of football still breaks that ladder. NFL75 is a different
question: how much advertising a run holds inside a hard cap on hidden football.
"""

from __future__ import annotations

EXPERIMENT = "NFL75_001"

COVERAGE_MIN = 0.75
FALSE_MUTES_PER_HOUR_MAX = 1.0
LONGEST_FALSE_MUTE_S_MAX = 10.0
PROGRAM_HIDDEN_PER_HOUR_MAX = 5.0

# A one-second unmute must not split one interruption into two passing episodes.
# Gaps of 2.0 seconds or less merge. The gap was heard, so it is not added to
# the episode duration. Duration is the sum of verified-program seconds covered.
MERGE_GAP_S = 2.0

MERGE_RULE = (
    "Covered stretches of eligible program are one false-mute episode when the "
    "uncovered gap between them is at most 2.0 seconds. Duration is the sum of "
    "those program seconds. The gap itself was heard and is not part of the "
    "duration. A mute that starts in a commercial and continues into the game "
    "counts only the program seconds after the gold boundary. One second of "
    "unmute does not create a second episode."
)

THRESHOLDS = {
    "commercial_coverage_at_least": COVERAGE_MIN,
    "false_mute_episodes_per_program_hour_below": FALSE_MUTES_PER_HOUR_MAX,
    "longest_false_mute_seconds_below": LONGEST_FALSE_MUTE_S_MAX,
    "false_muted_program_seconds_per_program_hour_below": PROGRAM_HIDDEN_PER_HOUR_MAX,
}
