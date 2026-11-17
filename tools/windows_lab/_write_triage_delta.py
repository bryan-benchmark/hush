import json
from pathlib import Path


def row(d, sess):
    for s in d["sessions"]:
        if s["session"] == sess:
            return s
    return {}


def main() -> None:
    before = json.loads(
        Path(r"C:\OHushData\indexes\farm_labels\LIVE_SCORECARD_BEFORE_TRIAGE.json").read_text(encoding="utf-8")
    )
    after = json.loads(Path(r"C:\OHushData\indexes\farm_labels\LIVE_SCORECARD.json").read_text(encoding="utf-8"))
    ba, aa = before["aggregate"], after["aggregate"]
    delta = {
        "mute_labeled_s": round(aa["mute_labeled_s"] - ba["mute_labeled_s"], 2),
        "play_labeled_s": round(aa["play_labeled_s"] - ba["play_labeled_s"], 2),
        "commercial_covered_s": round(aa["commercial_covered_s"] - ba["commercial_covered_s"], 2),
        "commercial_coverage": (
            None
            if ba["commercial_coverage"] is None or aa["commercial_coverage"] is None
            else round(aa["commercial_coverage"] - ba["commercial_coverage"], 4)
        ),
        "program_muted_s": round(aa["program_muted_s"] - ba["program_muted_s"], 2),
    }
    b1339 = row(before, "20261110T1339Z_pluto_cbs_sports_hq")
    a1339 = row(after, "20261110T1339Z_pluto_cbs_sports_hq")
    out = {
        "before": ba,
        "after": aa,
        "delta": delta,
        "session_1339": {
            "before": {k: b1339.get(k) for k in ["mute_labeled_s", "play_labeled_s", "commercial_coverage", "program_muted_s", "broken"]},
            "after": {k: a1339.get(k) for k in ["mute_labeled_s", "play_labeled_s", "commercial_coverage", "program_muted_s", "broken"]},
        },
    }
    p = Path(r"C:\OHushData\indexes\farm_labels\audit\EPISODE_TRIAGE.json")
    blob = json.loads(p.read_text(encoding="utf-8"))
    blob["scorecard_delta"] = out
    p.write_text(json.dumps(blob, indent=2) + "\n", encoding="utf-8")
    md = Path(r"C:\OHushData\indexes\farm_labels\audit\EPISODE_TRIAGE.md")
    extra = "\n".join(
        [
            "## Scorecard delta (full 12 sessions)",
            "",
            f"- program_muted_s: {ba['program_muted_s']} → {aa['program_muted_s']} (**{delta['program_muted_s']:+}s**)",
            f"- mute gold: {ba['mute_labeled_s']} → {aa['mute_labeled_s']} ({delta['mute_labeled_s']:+}s)",
            f"- commercial_coverage: {ba['commercial_coverage']} → {aa['commercial_coverage']}",
            f"- broken: {ba['broken']} → {aa['broken']}",
            "",
            "### 1339 session",
            f"- program_muted_s: {b1339.get('program_muted_s')} → {a1339.get('program_muted_s')}",
            f"- mute_labeled_s: {b1339.get('mute_labeled_s')} → {a1339.get('mute_labeled_s')}",
            f"- coverage: {b1339.get('commercial_coverage')} → {a1339.get('commercial_coverage')}",
            "",
        ]
    )
    md.write_text(md.read_text(encoding="utf-8") + extra, encoding="utf-8")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
