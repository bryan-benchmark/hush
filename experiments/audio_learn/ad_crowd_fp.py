"""Crowd score on gold commercial interiors. Crowd-detector FP = ad with live-level bed."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from experiments.audio_learn.crowd_pattern_mine import _stereo, frozen_p, measures
from experiments.measurement.metrics import target_commercials
from experiments.nfl75.inventory import active_intervals

OUT = Path(r"C:\OHushData\gpu_lab\audio_learn\acoustic_receipts")
LIVE_FLOOR = 0.622  # min quiet_crowd on succeed_play in patterns.json
SESSIONS = ("hush_20260924_220624", "hush_20261008_205100")


def main() -> None:
    rows = []
    for session in SESSIONS:
        ads = target_commercials(active_intervals(session))
        for i, (a0, a1) in enumerate(ads):
            if a1 - a0 < 12:
                continue
            # three probes: 25%, 50%, 75% into the break
            for frac, tag in ((0.25, "q1"), (0.5, "mid"), (0.75, "q3")):
                t = round(a0 + frac * (a1 - a0), 2)
                if t - 8 < a0:
                    continue
                stereo = _stereo(session, t - 8.0, t)
                m = measures(stereo)
                p = frozen_p(session, t)
                crowd_fp = m["quiet_crowd"] >= LIVE_FLOOR
                rows.append(
                    {
                        "session": session,
                        "break": i + 1,
                        "break_start": round(a0, 2),
                        "break_end": round(a1, 2),
                        "probe": tag,
                        "t": t,
                        "frozen_p": p,
                        "muted_ok": p is not None and p >= 0.90,
                        "quiet_crowd": m["quiet_crowd"],
                        "quiet_low": m["quiet_low"],
                        "centroid": m["centroid"],
                        "quiet_side_mid": m["quiet_side_mid"],
                        "crowd_detector_fp": crowd_fp,
                    }
                )
                mark = "CROWD_FP" if crowd_fp else ("ok" if (p or 0) >= 0.9 else "weak_p")
                print(
                    f"{session[-6:]} br{i+1:02d} {tag:3} t={t:7.1f} "
                    f"crowd={m['quiet_crowd']:.3f} low={m['quiet_low']:.3f} "
                    f"cent={m['centroid']:.0f} p={p} {mark}",
                    flush=True,
                )

    fps = [r for r in rows if r["crowd_detector_fp"]]
    muted_fps = [r for r in fps if r["muted_ok"]]
    open_fps = [r for r in fps if not r["muted_ok"]]
    summary = {
        "live_floor_quiet_crowd": LIVE_FLOOR,
        "ad_probes": len(rows),
        "crowd_detector_fp_probes": len(fps),
        "of_those_frozen_still_mutes": len(muted_fps),
        "of_those_frozen_leaves_open": len(open_fps),
        "fp_rate_among_ad_probes": round(len(fps) / max(len(rows), 1), 4),
        "breaks_with_any_fp": len({(r["session"], r["break"]) for r in fps}),
        "breaks_total": len({(r["session"], r["break"]) for r in rows}),
    }
    print(json.dumps(summary, indent=2), flush=True)
    # list the FP ads
    print("=== ads that trip live-level crowd ===", flush=True)
    for r in sorted(fps, key=lambda x: -x["quiet_crowd"]):
        print(
            f"  {r['session'][-6:]} break {r['break']} {r['probe']} "
            f"t={r['t']} crowd={r['quiet_crowd']} p={r['frozen_p']} "
            f"muted={r['muted_ok']}",
            flush=True,
        )
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "ad_crowd_fp.json").write_text(
        json.dumps({"summary": summary, "rows": rows, "crowd_fps": fps}, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
