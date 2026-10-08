#!/usr/bin/env python3
"""
Given a known ad-break IN, search forward for:
  - intra-break fades (ad → ad)
  - likely return-to-content OUT

Broadcast breaks are usually ~90–180s with short pads between 15/30s spots.

Example:
  python experiments/break_structure.py --in 108.25
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from legacy_detector import BREAK_PARAMS, break_at_session_in


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", default="recordings/2026-08-27/hush_20260827_135935")
    ap.add_argument("--in", dest="in_s", type=float, required=True, help="session elapsed IN")
    ap.add_argument("--pre", type=float, default=15.0)
    ap.add_argument("--post", type=float, default=240.0, help="seconds after IN to search")
    args = ap.parse_args()

    session = Path(args.session)
    params = dict(BREAK_PARAMS)
    params["pre_s"] = args.pre
    params["post_s"] = args.post
    result = break_at_session_in(session, args.in_s, params)
    published = result["published"]
    published.update(
        {
            "session": session.name,
            "in_elapsed_seconds": args.in_s,
            "window_start": result["window_start"],
            "window_duration": result["window_duration"],
        }
    )

    out = Path("experiments/candidates") / f"{session.name}_break_{int(args.in_s)}.json"
    out.write_text(json.dumps(published, indent=2), encoding="utf-8")
    print(json.dumps(published, indent=2))
    print(f"\nWrote {out}")


if __name__ == "__main__":
    main()
