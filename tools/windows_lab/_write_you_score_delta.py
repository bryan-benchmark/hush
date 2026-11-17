import json
from datetime import datetime, timezone

from tools.windows_lab.coverage_farm import farm_label_dir


def main() -> None:
    label = farm_label_dir()
    sc = json.loads((label / "LIVE_SCORECARD.json").read_text(encoding="utf-8"))
    apply = json.loads((label / "audit" / "EPISODE_YOU_APPLY.json").read_text(encoding="utf-8"))
    hn = []
    for s in sc.get("sessions") or []:
        for c in s.get("clips") or []:
            if "you_" in str(c.get("clip") or "") and c.get("role") == "play" and not c.get("ok"):
                hn.append(
                    {
                        "session": s.get("session"),
                        "clip": c.get("clip"),
                        "t0": c.get("t0"),
                        "t1": c.get("t1"),
                        "program_muted_s": c.get("covered_s"),
                    }
                )
    out = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "step": "apply_you_marks + export + live_scorecard",
        "apply": {
            k: apply.get(k)
            for k in ["utc", "you_ranges", "new_you_clips_n", "sessions", "backup"]
        },
        "scorecard_after": sc.get("aggregate"),
        "scorecard_before_approx": {
            "program_muted_s": 206.75,
            "commercial_coverage": 0.8617,
            "broken": True,
            "note": "prior LIVE_SCORECARD after triage patches",
        },
        "you_hard_negatives": hn,
        "you_hard_negatives_n": len(hn),
        "you_hard_negatives_program_muted_s": round(
            sum(float(x["program_muted_s"] or 0) for x in hn), 3
        ),
        "next": [
            "Keep you_hard_negatives as train targets (muter covered You=keep)",
            "Optional: shadow head refit on farm embeds + these ranges",
            "Do not retune live Mac controller tonight",
        ],
    }
    path = label / "audit" / "EPISODE_YOU_SCORE_DELTA.json"
    path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    lines = [
        f"# Episode You → gold score delta",
        "",
        f"generated: {out['generated_utc'][:19]}Z",
        "",
        "## Applied",
        f"- You ranges: **{apply.get('you_ranges')}** → **{apply.get('new_you_clips_n')}** clips",
        f"- sessions: {', '.join(apply.get('sessions') or [])}",
        "",
        "## Live scorecard",
        "- before program_muted_s: **206.75**",
        f"- after program_muted_s: **{sc['aggregate'].get('program_muted_s')}**",
        f"- after commercial_coverage: **{sc['aggregate'].get('commercial_coverage')}**",
        f"- still broken: **{sc['aggregate'].get('broken')}**",
        "",
        f"## You keep hard-negatives ({len(hn)} clips / {out['you_hard_negatives_program_muted_s']}s muted)",
        "",
    ]
    for x in hn:
        lines.append(
            f"- `{x['session']}` {x['t0']}–{x['t1']} covered={x['program_muted_s']}s"
        )
    lines.append("")
    (label / "audit" / "EPISODE_YOU_SCORE_DELTA.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"receipt": str(path), "hn_n": len(hn), "agg": sc.get("aggregate")}, indent=2))


if __name__ == "__main__":
    main()
