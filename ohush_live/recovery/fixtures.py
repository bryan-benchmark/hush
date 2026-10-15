"""Synthetic regression fixtures for LIVE_RECOVERY_001 defects A–D.

These test invariants. They are NOT real-world accuracy evidence.
scientific_authority=false.
"""

from __future__ import annotations

# Each fixture: sequence of (t, families) + expected under correct policy.
# expected_final: PLAY | MUTED
# expected_reasons: optional set of reasons that must appear / must not


def audio_strong(score: float = 0.30) -> dict:
    return {
        "departure": score,
        "strong_departure": score >= 0.22,
        "return": None,
        "strong_return": False,
    }


FIXTURES: dict[str, dict] = {
    "A_permanent_booth_veto": {
        "defect": "A",
        "title": "booth_locked with no speech must not block solo audio mute",
        "steps": [
            {
                "t": float(t),
                "families": {
                    "audio": audio_strong(0.30),
                    "speaker": {
                        "departure": None,
                        "strong_departure": False,
                        "return": 0.0,
                        "strong_return": False,
                        "speech": False,
                        "recurring": False,
                        "booth_present": False,
                        "booth_locked": True,
                        "continuity": None,
                    },
                    "semantic": None,
                },
            }
            for t in range(1, 12)
        ],
        "expect_candidate": {"final": "MUTED", "reason": "solo_audio_depart"},
        "expect_defect_peak": {"final": "PLAY"},
    },
    "B_false_booth_return": {
        "defect": "B",
        "title": "generic continuity/recurring must not return as booth_voice",
        "setup_mute_steps": [
            {
                "t": float(t),
                "families": {
                    "audio": audio_strong(0.30),
                    "speaker": None,
                    "semantic": None,
                },
            }
            for t in range(1, 5)
        ],
        "steps": [
            {
                "t": float(t),
                "families": {
                    "audio": {
                        "departure": 0.30,
                        "strong_departure": True,
                        "return": 0.30,
                        "strong_return": False,
                    },
                    "speaker": {
                        "departure": 0.05,
                        "strong_departure": False,
                        "return": 0.0,
                        "strong_return": False,
                        "speech": True,
                        "recurring": True,
                        "booth_present": False,
                        "booth_locked": True,
                        "continuity": 0.14,
                        "similarity_to_booth": 0.10,
                        "cluster_id": "ad_voice",
                    },
                    "semantic": None,
                },
            }
            for t in range(5, 20)
        ],
        "expect_candidate": {"final": "MUTED", "forbid_reason": "booth_voice"},
        "expect_defect_peak": {"final": "PLAY", "reason": "booth_voice"},
    },
    "C_verified_booth_still_protected": {
        "defect": "safety",
        "title": "verified booth speech still blocks solo audio mute",
        "steps": [
            {
                "t": float(t),
                "families": {
                    "audio": audio_strong(0.30),
                    "speaker": {
                        "departure": 0.02,
                        "strong_departure": False,
                        "return": 0.0,
                        "strong_return": False,
                        "speech": True,
                        "recurring": False,
                        "booth_present": True,
                        "booth_locked": True,
                        "similarity_to_booth": 0.80,
                    },
                    "semantic": None,
                },
            }
            for t in range(1, 12)
        ],
        "expect_candidate": {"final": "PLAY"},
        "expect_defect_peak": {"final": "PLAY"},
    },
    "C_verified_booth_return": {
        "defect": "safety",
        "title": "verified booth voice returns immediately from cover",
        "setup_mute_steps": [
            {
                "t": float(t),
                "families": {
                    "audio": audio_strong(0.30),
                    "speaker": None,
                    "semantic": None,
                },
            }
            for t in range(1, 5)
        ],
        "steps": [
            {
                "t": 5.0,
                "families": {
                    "audio": {
                        "departure": 0.25,
                        "strong_departure": True,
                        "return": 0.25,
                        "strong_return": False,
                    },
                    "speaker": {
                        "departure": 0.05,
                        "strong_departure": False,
                        "return": 0.0,
                        "strong_return": False,
                        "speech": True,
                        "recurring": False,
                        "booth_present": True,
                        "similarity_to_booth": 0.81,
                        "cluster_id": "c0001",
                    },
                    "semantic": None,
                },
            }
        ],
        "expect_candidate": {"final": "PLAY", "reason": "booth_voice"},
        "expect_defect_peak": {"final": "PLAY", "reason": "booth_voice"},
    },
    "D_low_similarity_booth_present_stays_covered": {
        "defect": "D",
        "title": "booth_present with similarity far below 0.55 must not uncover",
        "setup_mute_steps": [
            {
                "t": float(t),
                "families": {
                    "audio": audio_strong(0.30),
                    "speaker": None,
                    "semantic": None,
                },
            }
            for t in range(1, 5)
        ],
        "steps": [
            {
                "t": float(t),
                "families": {
                    "audio": {
                        "departure": 0.234,
                        "strong_departure": True,
                        "return": 0.234,
                        "strong_return": False,
                    },
                    "speaker": {
                        "departure": 0.0,
                        "strong_departure": False,
                        "return": 0.0,
                        "strong_return": False,
                        "speech": True,
                        "recurring": False,
                        "booth_present": True,
                        "booth_locked": True,
                        "booth_ids": ["c0001", "c0002", "c0004", "c0005"],
                        "similarity_to_booth": 0.148,
                        "cluster_id": "c0013",
                        "continuity": 0.0,
                    },
                    "semantic": None,
                },
            }
            for t in range(5, 12)
        ],
        "expect_candidate": {"final": "MUTED", "forbid_reason": "booth_voice"},
        "expect_defect_peak": {"final": "PLAY", "reason": "booth_voice"},
    },
    "A_outro_hold_still_protects": {
        "defect": "safety",
        "title": "bounded booth_present linger still blocks mute",
        "steps": [
            {
                "t": float(t),
                "families": {
                    "audio": audio_strong(0.30),
                    "speaker": {
                        "departure": None,
                        "strong_departure": False,
                        "return": None,
                        "strong_return": False,
                        "speech": False,
                        "recurring": False,
                        "booth_present": True,
                        "booth_locked": True,
                    },
                    "semantic": None,
                },
            }
            for t in range(1, 10)
        ],
        "expect_candidate": {"final": "PLAY"},
        "expect_defect_peak": {"final": "PLAY"},
    },
}


def run_fixture(Machine, fixture: dict) -> dict:
    machine = Machine()
    reasons: list[str] = []
    for step in fixture.get("setup_mute_steps") or []:
        event = machine.step(step["t"], 1.0, step["families"])
        if event:
            reasons.append(event["reason"])
    for step in fixture["steps"]:
        event = machine.step(step["t"], 1.0, step["families"])
        if event:
            reasons.append(event["reason"])
    return {"final": machine.state, "reasons": reasons}
