"""Cause labels for one frozen candidate. No threshold is chosen here.

The candidate is the NFL75 10-second mean. Speaker evidence, when it is
consulted at all, is the research SpeechBrain cosine at 0.25. The live
booth match at 0.55 is a different system and is not a label in this module.
"""

from __future__ import annotations

START_LINE = 0.1632588496059179
MATCH = 0.25
# A descriptive bin of this cosine. Not a proposed operating point.
NEAR = 0.15

GROUPS = {
    "recognized_enrolled_voice_still_muted": (
        "Recognized announcer, but system still muted",
        1,
    ),
    "recognition_not_fresh_at_open": (
        "Recognized announcer, but system still muted",
        1,
    ),
    "enrolled_voice_not_matched": (
        "Announcer speaking but speaker detector missed them",
        2,
    ),
    "no_speech_window": (
        "Announcer speaking but speaker detector missed them",
        2,
    ),
    "other_programming_muted": (
        "Other genuine programming muted",
        3,
    ),
    "commercial_not_started": (
        "Commercial began but OHush didn't recognize departure",
        4,
    ),
    "commercial_missed": (
        "Commercial began but OHush didn't recognize departure",
        4,
    ),
    "late_return": (
        "Commercial ended but OHush stayed muted",
        5,
    ),
    "promotional_tradeoff": (
        "Announcer-voiced or in-broadcast promotional material",
        6,
    ),
}

SPEECH_CATEGORIES = {"announcer_commentary", "other_commentary"}


def _finite(value) -> bool:
    return isinstance(value, (int, float)) and value == value


def _at_least(value, line: float) -> bool:
    return _finite(value) and float(value) + 1e-12 >= line


def assign_cause(row: dict) -> dict:
    """Label one failure. Observations are the fields already measured.

    `fresh` is the highest research cosine whose window ended in the last
    second. `max_in_episode` and `max_prior_5` are the same cosine over
    those clocks. A missing value stays missing. The listen category is a
    retrospective transcript note, not a live speaker name.
    """
    kind = row.get("kind")
    if kind == "late_return":
        return _pack(
            "late_return",
            ["return_rule_needs_three_cold_seconds"],
            observation=(
                "The cover was still on after the gold commercial ended. "
                "The return rule needs the raw score at or below zero for three seconds."
            ),
            hypothesis="The score stayed hot across the boundary, so the cover walked into the game.",
            confidence="high" if row.get("score_stayed_hot") else "medium",
        )
    if kind in ("missed_break", "late_start"):
        code = "commercial_missed" if kind == "missed_break" else "commercial_not_started"
        held = bool(row.get("speaker_held_the_open"))
        return _pack(
            code,
            ["speaker_veto_held_the_open"] if held else ["mean_did_not_cross_in_time"],
            observation=(
                "A gold commercial was open. The rolling mean had not crossed the frozen line "
                "at the boundary."
                if not held
                else "A gold commercial was open. A fresh 0.25 match was holding the cover off."
            ),
            hypothesis=(
                "Football still inside the 10-second window kept the mean cold."
                if not held
                else "The veto treated the start of the break as announcer audio."
            ),
            confidence="high" if row.get("mean_crossed_inside") is not None else "medium",
        )
    if row.get("overlay") == "promotional_read":
        matched = _at_least(row.get("fresh"), MATCH) or _at_least(row.get("max_in_episode"), MATCH)
        return _pack(
            "promotional_tradeoff",
            ["enrolled_voice_matched"] if matched else ["no_enrolled_match_at_the_open"],
            observation=(
                "The listen called this span a promotional read, and the gold file calls it program. "
                "The mean covered it."
            ),
            hypothesis="Leaving a read in an enrolled voice playing is the accepted tradeoff.",
            confidence="medium" if row.get("listen_is_opening_only") else "high",
        )
    fresh_hit = _at_least(row.get("fresh"), MATCH)
    nearby = _at_least(row.get("max_in_episode"), MATCH) or _at_least(row.get("max_prior_5"), MATCH)
    category = row.get("category")
    speech = category in SPEECH_CATEGORIES
    windows = int(row.get("speech_windows_in_episode") or 0)
    if fresh_hit:
        ignored = not row.get("policy_reads_speaker")
        return _pack(
            "recognized_enrolled_voice_still_muted",
            ["speaker_not_an_input"] if ignored else ["protection_expired_while_mean_stayed_hot"],
            observation=(
                f"A research cosine of {float(row['fresh']):.3f} named "
                f"{row.get('fresh_name') or 'an enrolled voice'} in the second the mute began. "
                + (
                    "This policy does not read that cosine."
                    if ignored
                    else "The one-second hold ended while the mean was still at or above the line."
                )
            ),
            hypothesis="The decision code, not a missing embedding, authorized the rest of the mute.",
            confidence="high",
        )
    if nearby and (speech or category is None):
        return _pack(
            "recognition_not_fresh_at_open",
            ["match_outside_the_one_second_window"],
            observation=(
                "A cosine at or above 0.25 exists in the episode or the five seconds before it. "
                "No such window ended in the second the mute began."
            ),
            hypothesis=(
                "A short pause, or a window that ended just too early, left the open unprotected. "
                "Absence of a fresh match is not evidence that the broadcast had gone to a commercial."
            ),
            confidence="high" if speech else "medium",
        )
    if speech and windows == 0:
        return _pack(
            "no_speech_window",
            ["no_ecapa_window_on_this_span"],
            observation=(
                "The listen heard speech. No ECAPA window overlaps the muted span. "
                "Raw VAD regions were not saved, so this does not say the detector called the span silence."
            ),
            hypothesis="The speech front end never produced a window the cosine could score.",
            confidence="medium" if row.get("listen_is_opening_only") else "high",
        )
    if speech:
        peak = row.get("max_in_episode")
        near = _at_least(peak, NEAR)
        return _pack(
            "enrolled_voice_not_matched",
            ["cosine_below_0.25", "near_the_research_line" if near else "weak_match_to_the_enrolled_cast"],
            observation=(
                "Speech windows exist. The highest cosine inside the span stays below 0.25."
                + (f" The peak is {float(peak):.3f}." if _finite(peak) else " The peak was not finite.")
            ),
            hypothesis=(
                "The enrolled prototypes do not sit close to this voice, or this cosine's 0.25 line is above the match."
            ),
            confidence="medium" if row.get("listen_is_opening_only") else "high",
        )
    return _pack(
        "other_programming_muted",
        ["listen_is_not_a_named_announcer_call"],
        observation=(
            f"The listen category is {category or 'missing'}. "
            "The mean covered the span. A person-level speaker label was not recorded."
        ),
        hypothesis="This is programming the cast list was not built to hold.",
        confidence="low" if category in (None, "other_uncertain", "stadium") else "medium",
    )


def _pack(code: str, contributing: list[str], *, observation: str, hypothesis: str, confidence: str) -> dict:
    group, priority = GROUPS[code]
    return {
        "primary": code,
        "group": group,
        "priority": priority,
        "contributing": contributing,
        "observation": observation,
        "hypothesis": hypothesis,
        "confidence": confidence,
    }
