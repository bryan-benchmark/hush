"""Bridge 0 commands: prepare, embed, train, score."""

from __future__ import annotations

import json
import sys

from tools.gpu_lab.prepare import build_report, write_report
from tools.gpu_lab.splits import DEVELOP, TRAIN


def main(argv: list[str] | None = None) -> int:
    command = (argv if argv is not None else sys.argv)[1:] or ["prepare"]
    if command[0] == "embed":
        from tools.gpu_lab.embed import embed_all

        embed_all()
        return 0
    if command[0] == "train":
        from tools.gpu_lab.train import fit_all

        fit_all()
        return 0
    if command[0] == "score":
        from tools.gpu_lab.need import write_need
        from tools.gpu_lab.score import score_all

        write_need(score_all())
        return 0
    if command[0] == "sustain":
        from tools.gpu_lab.need import build_need
        from tools.gpu_lab.prepare import DATA_ROOT
        from tools.gpu_lab.sustain import score_sustained

        scored = score_sustained()
        need = build_need(scored)
        need["gate"] = "bridge1_sustain"
        detail = scored["detail"]["windows"]
        if detail:
            need["sustain_s"] = detail[0]["sustain_s"]
        path = DATA_ROOT / "NEED.json"
        path.write_text(json.dumps(need, indent=2), encoding="utf-8")
        print(json.dumps(need, indent=2), flush=True)
        print(f"wrote {path}", flush=True)
        return 0
    if command[0] == "relative":
        from tools.gpu_lab.need import build_need
        from tools.gpu_lab.prepare import DATA_ROOT
        from tools.gpu_lab.relative import score_relative

        scored = score_relative()
        detail = scored["detail"]["windows"]
        if not detail:
            need = {
                "gate": "bridge2_relative",
                "conclusion": "no past-quantile cutoff stays off the ESPN game",
                "failure": "program_mute",
                "next_experiment": "Stop this head. Do not tune it on October.",
                "pass_fail": "A later head has zero program seconds on hush_20260914_212529.",
            }
        else:
            need = build_need(scored)
            need["gate"] = "bridge2_relative"
            need["memory_s"] = detail[0]["memory_s"]
            need["quantile"] = detail[0]["quantile"]
        path = DATA_ROOT / "NEED.json"
        path.write_text(json.dumps(need, indent=2), encoding="utf-8")
        print(json.dumps(need, indent=2), flush=True)
        print(f"wrote {path}", flush=True)
        return 0
    if command[0] == "learn":
        from tools.gpu_lab.learning_net.__main__ import main as learn_main

        return learn_main(command[1:] or ["all"])
    if command[0] != "prepare":
        raise SystemExit(
            f"unknown command {command[0]}. Use prepare, embed, train, score, sustain, relative, or learn."
        )
    return _prepare()


def _prepare() -> int:
    report = build_report()
    path = write_report(report)
    print(f"wrote {path}")
    for mask in report["sessions"]:
        if mask["role"] == "out_of_scope":
            continue
        print(
            f"{mask['role']:10} {mask['session']}  "
            f"ads {mask['commercial_s']:8.1f}s  "
            f"program {mask['program_s']:8.1f}s  "
            f"excluded {mask['excluded_s']:7.1f}s  "
            f"pods {mask['commercials']}"
        )
    print("TNF coverage if each break is caught only after the whole window is inside the ad:")
    for row in report["tnf_delay_ceiling"]:
        print(
            f"  {row['delay_s']:4.0f}s window  "
            f"held {row['held_fraction']:.4f}  "
            f"still heard {row['heard_s']:.1f}s of {row['commercial_s']:.1f}s"
        )
    missing = [row["session"] for row in report["recordings"] if not row["present"]]
    if missing:
        print("BLOCKED: recordings are not on this machine.")
        print("Install the Google Cloud SDK, sign in to project hushdev, then run:")
        print("  python scripts/restore_from_gcs.py")
        print(f"Missing {len(missing)} sessions. Training sessions present: "
              f"{sum(1 for row in report['recordings'] if row['present'] and row['session'] in TRAIN)}/{len(TRAIN)}. "
              f"October development sessions are in the same restore.")
        return 2
    develop = [row for row in report["recordings"] if row["session"] in DEVELOP]
    print(f"recordings restored. development hashes: {len(develop)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
