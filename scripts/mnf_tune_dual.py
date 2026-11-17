"""Tune Nougat32 -> US: ESPN (MNF) and Nougat32_1 -> US: ESPN 2 (Manningcast).

Uses the locked parent→child nav routes (US SPORTS → US: ESPN / US: ESPN 2).
"""
from __future__ import annotations

import json
from tools.windows_lab.multi_instance import main as mi_main
from tools.windows_lab.streamers_nav import run_route


def main() -> int:
    mi_main(["route-audio"])
    a = run_route("ESPN_US", instance_id="Nougat32", open_player=True, save_as="ESPN_US")
    b = run_route("ESPN2_US", instance_id="Nougat32_1", open_player=True, save_as="ESPN2_US")
    print(
        json.dumps(
            {
                "Nougat32": {
                    "ok": a.get("ok"),
                    "final_place": a.get("final_place"),
                    "selected": next(
                        (
                            (s.get("result") or {}).get("chosen")
                            for s in reversed(a.get("atoms") or [])
                            if (s.get("result") or {}).get("chosen")
                        ),
                        None,
                    ),
                },
                "Nougat32_1": {
                    "ok": b.get("ok"),
                    "final_place": b.get("final_place"),
                    "selected": next(
                        (
                            (s.get("result") or {}).get("chosen")
                            for s in reversed(b.get("atoms") or [])
                            if (s.get("result") or {}).get("chosen")
                        ),
                        None,
                    ),
                },
            },
            indent=2,
        )
    )
    return 0 if a.get("ok") and b.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
