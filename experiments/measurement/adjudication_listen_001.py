"""Read the finished 53-clip adjudication. Does not edit gold or any detector.

The latest saved row for each clip is the listen. Keyword tags in that row are
not the coding: several ads are spelled "commerical", and "we're back in 30
seconds" is a sign-off. The phase of each box is read from its words.
"""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ADJ = REPO / "docs/ohush/swarm/adjudication"
OUT = REPO / "docs/ohush/research/BOUNDARY_EVIDENCE_001"
COLLAR_S = 0.2
GOLD_T = 10.0

# A box can carry two facts. These overrides are the mixed lines a single
# keyword would flatten. Keyed by clip id and the saved start time.
OVERRIDES = {
    ("q001", 0.0): "booth",
    ("q001", 8.92): "music_and_ad",
    ("q002", 0.0): "booth_promo",
    ("q002", 9.01): "crowd",
    ("q003", 0.0): "booth",
    ("q005", 0.0): "booth",
    ("q006", 0.0): "booth",
    ("q007", 3.2): "music",
    ("q008", 0.0): "booth",
    ("q008", 9.6): "music",
    ("q011", 5.74): "booth",
    ("q011", 9.68): "crowd",
    ("q012", 8.6): "crowd",
    ("q014", 0.0): "booth",
    ("q014", 5.76): "crowd",
    ("q014", 10.01): "commercial",
    ("q015", 4.25): "music",
    ("q017", 11.08): "commercial",
    ("q025", 0.0): "booth",
    ("q026", 11.92): "booth",
    ("q027", 18.73): "booth",
    ("q028", 15.02): "music",
    ("q028", 17.68): "booth",
    ("q029", 11.57): "crowd",
    ("q029", 13.22): "booth",
    ("q030", 10.55): "announcer_promo",
    ("q031", 10.81): "music",
    ("q031", 12.4): "booth",
    ("q032", 9.41): "booth",
    ("q032", 15.54): "booth",
    ("q034", 7.0): "crowd",
    ("q051", 0.0): "crowd",
    ("q051", 4.88): "commercial",
}


def phase_of(text: str) -> str:
    t = " ".join(
        text.lower()
        .replace("commerical", "commercial")
        .replace("commmercial", "commercial")
        .replace("commotion", "crowdnoise")
        .split()
    )
    if any(word in t for word in ("stream lag", "streaming lag", "steram lag", "stream gap")):
        return "lag"
    if any(word in t for word in ("gap for", "gap break", "dead noise", "break for", "broadcast gap", "broadcast change")):
        return "gap"
    if any(word in t for word in ("before commercial", "into commercial", "to commercial", "for commercial", "signing off")):
        return "music" if "music" in t and "outro music" in t else "booth"
    commercial = any(word in t for word in ("commercial", "trailer")) or t.endswith(" ad") or " ad " in f" {t} " or t.endswith(" ad")
    music = any(word in t for word in ("music", "outro", "intro"))
    if commercial and music:
        return "music_and_ad"
    if commercial:
        return "commercial"
    if music:
        return "music"
    if any(word in t for word in ("crowd", "ambient", "stadium", "presnap", "pre snap", "pre-snap", "whistle")):
        return "crowd"
    return "booth"


def latest_judgments() -> dict[str, dict]:
    chosen: dict[str, dict] = {}
    for line in (ADJ / "judgments.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            chosen[row["id"]] = row
    return chosen


def covers(region: dict, t: float) -> bool:
    return float(region["start_s"]) - 1e-9 <= t <= float(region["end_s"]) + 1e-9


def first_phase(regions: list[dict], names: set[str]) -> dict | None:
    for region in regions:
        if region["phase"] in names:
            return region
    return None


def spot_at_mark(regions: list[dict]) -> dict | None:
    """The ad the gold mark falls in, or the next ad after the mark."""
    spots = [region for region in regions if region["phase"] in {"commercial", "music_and_ad"}]
    for region in spots:
        if covers(region, GOLD_T):
            return region
    later = [region for region in spots if float(region["start_s"]) >= GOLD_T - 0.05]
    if later:
        return later[0]
    return spots[0] if spots else None


def code_clip(row: dict, key: dict) -> dict:
    regions = []
    for region in row["regions"]:
        phase = OVERRIDES.get((row["id"], float(region["start_s"])), phase_of(region["what"]))
        regions.append({**region, "phase": phase})
    at_gold = [region for region in regions if covers(region, GOLD_T)]
    creative = spot_at_mark(regions)
    music = first_phase(regions, {"music", "music_and_ad"})
    booth = first_phase(regions, {"booth", "booth_promo"})
    crowd = first_phase(regions, {"crowd"})
    gap = None
    if creative is not None:
        cut = float(creative["start_s"])
        holes = [
            region
            for region in regions
            if region["phase"] in {"gap", "lag"}
            and float(region["start_s"]) < cut
            and cut - float(region["end_s"]) <= 0.75
            and cut - float(region["start_s"]) <= 4.0
        ]
        if holes:
            gap = holes[-1]
    def delta(region: dict | None) -> float | None:
        if region is None:
            return None
        return round(float(region["start_s"]) - GOLD_T, 3)

    creative_delta = delta(creative)
    gap_delta = delta(gap)
    # The heard cut is the hole immediately before the spot, or the spot itself.
    heard = gap if gap is not None else creative
    nearest_break_edge = None if heard is None else round(abs(float(heard["start_s"]) - GOLD_T), 3)
    on_heard_break = any(region["phase"] in {"gap", "lag"} for region in at_gold)
    if creative_delta is not None and abs(creative_delta) <= COLLAR_S:
        on_heard_break = True
    if gap_delta is not None and abs(gap_delta) <= COLLAR_S:
        on_heard_break = True
    program_phases = {"booth", "booth_promo", "music", "crowd"}
    has_program_audio = any(region["phase"] in program_phases for region in regions)
    already_ad = bool(creative) and not has_program_audio
    return {
        "id": row["id"],
        "session": key["session"],
        "network": key["network"],
        "reason": key["reason"],
        "candidate_kind": key["candidate_kind"],
        "center_s": key["center_s"],
        "saved_judgment": row.get("judgment"),
        "regions": [
            {
                "start_s": region["start_s"],
                "end_s": region["end_s"],
                "what": region["what"],
                "phase": region["phase"],
            }
            for region in regions
        ],
        "phase_at_gold": [region["phase"] for region in at_gold],
        "creative_onset_delta_s": creative_delta,
        "gap_onset_delta_s": gap_delta,
        "music_onset_delta_s": delta(music),
        "booth_onset_delta_s": delta(booth),
        "crowd_onset_delta_s": delta(crowd),
        "nearest_break_edge_s": nearest_break_edge,
        "break_edge_within_collar": on_heard_break,
        "already_commercial_before_clip": already_ad,
        "has_program_audio": has_program_audio,
        "gold_inside_gap": any(region["phase"] in {"gap", "lag"} for region in at_gold),
        "gold_inside_creative": any(region["phase"] in {"commercial", "music_and_ad"} for region in at_gold),
    }


def main() -> None:
    judgments = latest_judgments()
    key = {row["id"]: row for row in json.loads((ADJ / "queue_key.json").read_text(encoding="utf-8"))}
    public = json.loads((ADJ / "queue_public.json").read_text(encoding="utf-8"))["items"]
    missing = [item["id"] for item in public if item["id"] not in judgments]
    if missing:
        raise SystemExit(f"unlabeled clips: {missing}")
    coded = [code_clip(judgments[item["id"]], key[item["id"]]) for item in public]
    starts = [row for row in coded if row["candidate_kind"] == "start"]
    summary = {
        "n_saved_rows": sum(1 for line in (ADJ / "judgments.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()),
        "n_clips": len(coded),
        "collar_s": COLLAR_S,
        "returns_queue_labeled": (OUT / "returns_judgments.jsonl").exists(),
        "gold_edited": False,
        "by_reason": dict(Counter(row["reason"] for row in coded)),
        "starts": {
            "n": len(starts),
            "break_edge_within_200ms": sum(row["break_edge_within_collar"] for row in starts),
            "already_commercial_before_clip": sum(row["already_commercial_before_clip"] for row in starts),
            "gold_inside_gap": sum(row["gold_inside_gap"] for row in starts),
            "gold_inside_creative": sum(row["gold_inside_creative"] for row in starts),
        },
    }
    for label, pred in (
        ("dsp_miss", lambda row: row["reason"].startswith("dsp_miss")),
        ("dsp_hit", lambda row: row["reason"].startswith("dsp_hit")),
    ):
        group = [row for row in starts if pred(row)]
        summary["starts"][label] = {
            "n": len(group),
            "break_edge_within_200ms": sum(row["break_edge_within_collar"] for row in group),
            "already_commercial_before_clip": [row["id"] for row in group if row["already_commercial_before_clip"]],
            "gold_inside_gap": sum(row["gold_inside_gap"] for row in group),
            "gold_inside_creative": sum(row["gold_inside_creative"] for row in group),
            "creative_onset_delta_s": [row["creative_onset_delta_s"] for row in group],
            "ids_edge_outside_collar": [row["id"] for row in group if not row["break_edge_within_collar"]],
        }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "adjudication_coding.json").write_text(json.dumps({"summary": summary, "clips": coded}, indent=2) + "\n", encoding="utf-8")
    with (OUT / "cue_table.csv").open("w", newline="", encoding="utf-8") as handle:
        fields = [
            "id", "network", "reason", "candidate_kind", "center_s",
            "phase_at_gold", "creative_onset_delta_s", "gap_onset_delta_s",
            "music_onset_delta_s", "booth_onset_delta_s", "nearest_break_edge_s",
            "break_edge_within_collar", "already_commercial_before_clip",
        ]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in coded:
            writer.writerow({
                **{key: row[key] for key in fields if key != "phase_at_gold"},
                "phase_at_gold": "|".join(row["phase_at_gold"]),
            })
    print(json.dumps(summary, indent=2))
    print("\nPHASES")
    for row in coded:
        print(f"{row['id']} {row['reason']} at10={row['phase_at_gold']} creative={row['creative_onset_delta_s']} gap={row['gap_onset_delta_s']} edge={row['nearest_break_edge_s']} already={row['already_commercial_before_clip']}")
        for region in row["regions"]:
            print(f"    {region['start_s']:.2f}-{region['end_s']:.2f} {region['phase']}: {region['what']}")


if __name__ == "__main__":
    main()
