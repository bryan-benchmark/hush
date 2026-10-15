"""Run synthetic fixtures against two code roots; emit metrics JSON."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _run_alias(code_root: Path, alias: str) -> dict:
    script = f"""
import json, sys
from pathlib import Path
sys.path.insert(0, {str(REPO)!r})
from ohush_live.recovery.load_machine import load_machine
from ohush_live.recovery.fixtures import FIXTURES, run_fixture
Machine = load_machine(Path({str(code_root.resolve())!r}), alias={alias!r})
out = {{}}
for name, fix in FIXTURES.items():
    result = run_fixture(Machine, fix)
    key = "expect_defect_peak" if {alias!r} == "defect_peak" else "expect_candidate"
    expect = fix[key]
    ok = result["final"] == expect["final"]
    if expect.get("reason"):
        ok = ok and expect["reason"] in result["reasons"]
    if expect.get("forbid_reason"):
        ok = ok and expect["forbid_reason"] not in result["reasons"]
    out[name] = {{
        "result": result,
        "expect": expect,
        "pass": ok,
        "defect": fix["defect"],
        "title": fix["title"],
    }}
print(json.dumps(out))
"""
    proc = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or "") + "\n" + (proc.stdout or ""))
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip().startswith("{")]
    return json.loads(lines[-1])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--defect-peak", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    peak = _run_alias(args.defect_peak, "defect_peak")
    cand = _run_alias(args.candidate, "candidate")
    report = {"defect_peak": peak, "candidate": cand, "gates": {}}
    for name in peak:
        p, c = peak[name], cand[name]
        report["gates"][name] = {
            "defect_peak_matches_broken_expect": p["pass"],
            "candidate_matches_fixed_expect": c["pass"],
        }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "wrote": str(args.out),
                "defect_peak_ok": all(
                    g["defect_peak_matches_broken_expect"] for g in report["gates"].values()
                ),
                "candidate_ok": all(
                    g["candidate_matches_fixed_expect"] for g in report["gates"].values()
                ),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
