"""Verified program-speaker enrollment. Not a mute.

The names a person typed live in the voice roster. The latest save for each
clip is the one that counts. Cluster ids, booth_present, and .booth.json are
not enrollments. This script does not open those files and does not invent a
speaker.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from experiments.measurement.verified_speaker_001 import latest_names, spans_from  # noqa: E402

OUT = REPO / "docs/ohush/research/UNIVERSAL_V4_SPEAKER_ENROLLMENT_001"
NAMES = REPO / "docs/ohush/research/VOICE_ROSTER_001/names.jsonl"
LEDGER = OUT / "verified.jsonl"
OTHER_PEOPLE = {
    "snf broadcaster mike tomlin": "Mike Tomlin",
    "broadcaster mike tomlin": "Mike Tomlin",
    "tnf broadcaster andrew whitworth": "Andrew Whitworth",
    "tnf broadcaster richard shermann": "Richard Shermann",
    "tnf broadcaster ryan fitzpatrick": "Ryan Fitzpatrick",
    "broadcaster - maria taylor": "Maria Taylor",
    "clarissa thompson": "Clarissa Thompson",
    "nfl player interview - bijan robinson": "Bijan Robinson",
    "steve harvey family feud after the game is over": "Steve Harvey",
    "troy aikman laughing": "Troy Aikman",
    "mike tirico saying chevrolet postgame is coming up": "Mike Tirico",
}


def person_name(span: dict) -> str | None:
    if span["kind"] == "announcer" and span["name"]:
        return span["name"]
    return OTHER_PEOPLE.get(" ".join(span["who"].lower().split()))


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    spans = []
    for row in latest_names():
        spans.extend(spans_from(row))
    named = [span for span in spans if person_name(span)]
    unidentified = [span for span in spans if span["kind"] in {"announcer", "other_voice"} and not person_name(span)]
    other = [span for span in spans if span["kind"] not in {"announcer", "other_voice"}]
    counts: dict[str, int] = {}
    for span in named:
        counts[person_name(span)] = counts.get(person_name(span), 0) + 1
    people = [{"name": name, "spans": counts[name]} for name in sorted(counts)]
    payload = {
        "system": "universal_v4_speaker_enrollment",
        "verdict": "EVIDENCE_ONLY" if named else "NOT_MEASURED",
        "mute_policy": False,
        "source": str(NAMES.relative_to(REPO)),
        "latest_clips": len({span["clip_id"] for span in spans}),
        "named_person_spans": len(named),
        "named_people": people,
        "unidentified_spans": len(unidentified),
        "not_person_spans": len(other),
        "append_log_rows": sum(1 for line in LEDGER.read_text(encoding="utf-8").splitlines() if line.strip()) if LEDGER.exists() else 0,
        "append_log_note": "verified.jsonl keeps every save. It is not the enrollment count.",
        "refused_as_enrollment": [".booth.json", "cluster ids", "booth_present"],
        "booth_files_read": False,
        "measurement": "docs/ohush/research/VERIFIED_SPEAKER_001/REPORT.md",
    }
    (OUT / "results.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    (OUT / "REPORT.md").write_text(render(payload), encoding="utf-8")
    print(json.dumps({"verdict": payload["verdict"], "named_person_spans": payload["named_person_spans"], "people": payload["named_people"]}, indent=2))


def render(payload: dict) -> str:
    names = "\n".join(f"- {row['name']}: {row['spans']} span{'s' if row['spans'] != 1 else ''}" for row in payload["named_people"])
    return "\n".join(
        [
            "# Verified program-speaker enrollment",
            "",
            "Verdict: **EVIDENCE ONLY**. This is not a mute.",
            "",
            f"A person named {payload['named_person_spans']} speech spans across {payload['latest_clips']} latest clips. "
            f"{payload['unidentified_spans']} spans describe a voice without naming the person. "
            f"{payload['not_person_spans']} spans are ads, promos, crowd, music, or stream lag, and those are not enrollments.",
            "",
            "The names are the latest save for each clip in `docs/ohush/research/VOICE_ROSTER_001/names.jsonl`. "
            f"`verified.jsonl` has {payload['append_log_rows']} appended rows because every edit was kept. That log is not the count.",
            "",
            "An earlier copy of this report said nothing had been written. That was the counter before these saves were read.",
            "",
            "Named spans:",
            "",
            names,
            "",
            "`.booth.json`, cluster ids, and `booth_present` were not read. They are not enrollments. "
            "The identity-probe answers say whether a clip is still a game or a show. They do not name an announcer.",
            "",
            "Whether those names can be recognized in other audio is a separate measurement: "
            "`docs/ohush/research/VERIFIED_SPEAKER_001/REPORT.md`.",
            "",
            "No playback rule was built from speakers.",
            "",
        ]
    )


if __name__ == "__main__":
    main()
