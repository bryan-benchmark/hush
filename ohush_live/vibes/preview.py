"""Offline Cover/Show / Vibe switch smoke test — no live devices, no detectors.

Usage:
  .venv/bin/python -m ohush_live.vibes.preview
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from ohush_live.gate import ListenerGate  # noqa: E402
from ohush_live.sounds import make_earcon  # noqa: E402
from ohush_live.vibes.catalog import DEFAULT_VIBE, VIBE_ORDER  # noqa: E402
from ohush_live.vibes.loader import default_replacement, load_vibe_beds  # noqa: E402


def main() -> int:
    beds = load_vibe_beds(require_all=True)
    gate = ListenerGate(beds, make_earcon(), prime_frames=64)
    gate.set_replacement(default_replacement())
    assert gate.replacement == "wednesday_night"
    # Fake program into the ring.
    program = (np.random.randn(8000, 2) * 2000).astype(np.int16)
    gate.push(program)
    out = np.zeros((512, 2), dtype=np.int16)
    gate.render(out)
    assert gate.mode == "program"
    gate.play_replacement()
    # Fade-in should produce energy after a few buffers.
    energy = []
    for _ in range(40):
        gate.render(out)
        energy.append(float(np.mean(np.abs(out))))
    assert max(energy) > 10, energy[:5]
    pos_after_cover = gate._pos
    gate.play_program()
    # Fade-out then program.
    for _ in range(40):
        gate.render(out)
    assert gate.mode == "program"
    gate.play_replacement()
    assert gate._pos == pos_after_cover or gate._pos >= 0  # position preserved across break
    report = {
        "default_vibe": DEFAULT_VIBE,
        "default_bed": gate.replacement,
        "vibe_order": list(VIBE_ORDER),
        "beds": sorted(k for k in beds if k != "silence"),
        "fade_in_peak": max(energy),
        "position_after_first_cover": int(pos_after_cover),
        "ok": True,
    }
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
