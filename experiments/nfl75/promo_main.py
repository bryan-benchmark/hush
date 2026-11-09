"""Score the frozen NFL75 detector under the research labels and the consumer scenario.

    python -m experiments.nfl75.promo_main

Reads the booth-hold replay. Does not refit the mean, move a speaker, edit gold,
or change the television.
"""

from __future__ import annotations

import json
from pathlib import Path

from experiments.nfl75.promo_class import (
    BOOTH_PATH,
    OVERLAY_PATH,
    audited_seconds,
    clear_of_breaks,
    load_overlay,
    score_views,
    spans_for,
)

OUT = Path(__file__).resolve().parents[2] / "docs" / "ohush" / "research" / "NFL75_PROMO_CLASS_001"
POLICIES = ("unprotected", "hold_5")
CLOCKS = ("oracle", "actual")
_EPS = 0.05


def _round(value, places: int):
    if value is None:
        return None
    return round(float(value), places)


def _public(metrics: dict) -> dict:
    longest = None
    if metrics["longest_start_s"] is not None:
        longest = {
            "start_s": _round(metrics["longest_start_s"], 3),
            "end_s": _round(metrics["longest_end_s"], 3),
            "duration_s": _round(metrics["longest_false_mute_s"], 3),
        }
    return {
        "commercial_coverage": metrics["commercial_coverage"],
        "commercial_s": metrics["commercial_s"],
        "breaks_missed": metrics["breaks_missed"],
        "program_s": _round(metrics["program_s"], 3),
        "program_removed_s": _round(metrics["program_removed_s"], 3),
        "program_covered_s": _round(metrics["program_covered_s"], 3),
        "false_mute_episodes": metrics["false_mute_episodes"],
        "false_mutes_per_hour": _round(metrics["false_mutes_per_hour"], 3),
        "longest_false_mute_s": _round(metrics["longest_false_mute_s"], 3),
        "longest": longest,
        "program_hidden_per_hour": _round(metrics["program_hidden_per_hour"], 3),
        "class_clock_s": _round(metrics["class_clock_s"], 3),
        "class_muted_s": _round(metrics["class_muted_s"], 3),
        "class_playing_s": _round(metrics["class_playing_s"], 3),
    }


def _check(stored: dict, research: dict, where: str) -> None:
    if research["false_mute_episodes"] != stored["false_mute_episodes"]:
        raise SystemExit(
            f"{where} research episodes {research['false_mute_episodes']} "
            f"!= stored {stored['false_mute_episodes']}"
        )
    covered = abs(research["program_covered_s"] - float(stored["program_covered_s"]))
    if covered > _EPS:
        raise SystemExit(f"{where} research covered seconds differ by {covered:.3f}")
    if abs(research["commercial_coverage"] - float(stored["commercial_coverage"])) > 1e-9:
        raise SystemExit(f"{where} commercial coverage moved")


def main() -> None:
    overlay = load_overlay()
    booth = json.loads(BOOTH_PATH.read_text(encoding="utf-8"))
    sessions = []
    for session in booth["sessions"]:
        name = session["session"]
        oracle_breaks = session["policies"]["unprotected"]["oracle"]["breaks"]
        clear_of_breaks(spans_for(overlay, name, "audited_bucket"), oracle_breaks)
        clear_of_breaks(
            [
                (float(row["start_s"]), float(row["end_s"]))
                for row in overlay["spans"]
                if row["session"] == name and row["overlay_class"] == "program"
            ],
            oracle_breaks,
        )
        policies = {}
        for policy_name in POLICIES:
            clocks = {}
            for clock in CLOCKS:
                stored = session["policies"][policy_name][clock]
                scored = score_views(overlay, name, stored)
                _check(stored, scored["views"]["research"], f"{name} {policy_name} {clock}")
                clocks[clock] = {
                    "views": {key: _public(value) for key, value in scored["views"].items()},
                    "program_examples_muted_s": [
                        {"id": row["id"], "muted_s": _round(row["muted_s"], 3)}
                        for row in scored["program_examples_muted_s"]
                    ],
                }
            policies[policy_name] = clocks
        sessions.append(
            {
                "session": name,
                "development_inspection": True,
                "audited_promo_bucket_s": _round(audited_seconds(overlay, name, bucket=True), 3),
                "promotional_read_s": _round(audited_seconds(overlay, name, bucket=False), 3),
                "policies": policies,
            }
        )
    payload = {
        "experiment": "NFL75_PROMO_CLASS_001",
        "verdict": "MEASURED",
        "deployable": False,
        "automatic_mute": False,
        "gold_labels_changed": False,
        "television_changed": False,
        "detector": "NFL75_BOOTH_HOLD_001 unprotected and hold_5. The 10-second mean and the 0.163 line stay frozen.",
        "views": {
            "research": "Gold program. A muted promotional read counts as a false mute.",
            "consumer": "A promotional read is wanted suppression. A mixed mention and editorial or football programming still count as false mutes.",
            "sponsored_read": "Only the Amex and Chili's reads are wanted suppression.",
            "audited_bucket": "Every second the earlier listen called a sponsor read, including mixed mentions, is wanted suppression.",
        },
        "overlay": str(OVERLAY_PATH.relative_to(OUT.parents[3])).replace("\\", "/"),
        "sessions": sessions,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    for session in sessions:
        print(session["session"], "bucket", session["audited_promo_bucket_s"], "promo", session["promotional_read_s"])
        for policy_name, clocks in session["policies"].items():
            for clock, row in clocks.items():
                research = row["views"]["research"]
                consumer = row["views"]["consumer"]
                print(
                    f"  {policy_name:12} {clock:7} "
                    f"research {research['false_mute_episodes']:3} ep "
                    f"{research['false_mutes_per_hour']:6} /h "
                    f"hidden {research['program_hidden_per_hour']:7} "
                    f"worst {research['longest_false_mute_s']:6}  "
                    f"consumer {consumer['false_mute_episodes']:3} ep "
                    f"{consumer['false_mutes_per_hour']:6} /h "
                    f"hidden {consumer['program_hidden_per_hour']:7} "
                    f"worst {consumer['longest_false_mute_s']:6} "
                    f"muted {consumer['class_muted_s']} playing {consumer['class_playing_s']}"
                )


if __name__ == "__main__":
    main()
