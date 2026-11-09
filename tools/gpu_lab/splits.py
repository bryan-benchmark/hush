"""Whole-broadcast split for Bridge 0. Declared before any model score.

October recordings were already inspected, so they are a development score.
The mute rule is locked on the ESPN broadcast and is not refit on October.
Sealed holdouts are absent on purpose.
"""

from __future__ import annotations

REDZONE = "hush_20260913_150934"
HOLDOUTS = frozenset({"hush_20260917_205513", "hush_20260920_200635"})

TRAIN = (
    "hush_20260909_213047",
    "hush_20260913_210542",
    "hush_20260924_220624",
)
CALIBRATE = ("hush_20260914_212529",)
DEVELOP = (
    "hush_20261008_205100",
    "hush_20261010_222400",
    "hush_20261011_135700",
    "hush_20261011_204300",
    "hush_20261012_204200",
)
CONTROL = (REDZONE,)
OUT_OF_SCOPE = (
    "hush_20260827_135935",
    "hush_20261007_220650",
)

FOOTBALL_COMMERCIAL_S = 17648.4
TNF = "hush_20261008_205100"
WINDOW_S = (2.0, 5.0, 10.0)
