"""Whole-game split for the first audio-learning proof.

Prime games are the product environment and are not used to fit weights or to
choose the volume controller. ESPN is the calibration game: the controller
grid is scored there and nowhere else. Sealed sessions are not members of any
split and are not opened.

The grid below is the operating policy. It was declared with the split, before
Prime probabilities exist.
"""

from __future__ import annotations

from tools.gpu_lab.splits import HOLDOUTS

EXPERIMENT = "OHUSH_AUDIO_LEARNING_001"

TRAIN = (
    "hush_20260909_213047",  # Sept 9 NBC football
    "hush_20260913_210542",  # Sept 13 NBC football
    "hush_20260913_150934",  # Sept 13 FOX RedZone, program only
    "hush_20261011_135700",  # Oct 11 afternoon football
    "hush_20261012_204200",  # Oct 12 Monday Night Football
)
CALIBRATE = ("hush_20260914_212529",)  # Sept 14 ESPN, controller only
EVAL = (
    "hush_20261008_205100",  # Oct 8 Prime Thursday Night Football
    "hush_20260924_220624",  # Sept 24 Prime football
)
# Labeled, and left out of this proof. Not an exam set.
RESERVED = (
    "hush_20261010_222400",  # mixed cable, not a football-only tape
    "hush_20261011_204300",  # Sunday night cable, program note is Gilmore Girls
    "hush_20260827_135935",  # Hulu scripted
    "hush_20261007_220650",  # Hulu scripted
)

WINDOW_S = 4.0
CONTEXT_S = 10.0
HOP_S = 0.25
SR = 16000
SEQUENCE = 16
HIDDEN = 64
SEED = 1

# Hysteresis on P(commercial). Streaks are decision counts at HOP_S.
ON_THRESHOLDS = (0.50, 0.65, 0.80, 0.90)
OFF_THRESHOLDS = (0.20, 0.35, 0.50)
ON_STREAKS = (2, 4, 8)
OFF_STREAKS = (2, 4)

MODEL_NAME = "frame_mn10"
CHECKPOINT_NAME = "frame_mn10_strong_1"
CHECKPOINT_URL = (
    "https://github.com/fschmid56/PretrainedSED/releases/download/v0.0.1/frame_mn10_strong_1.pt"
)


def assert_split() -> None:
    train, calibrate, evaluate, reserved = set(TRAIN), set(CALIBRATE), set(EVAL), set(RESERVED)
    if train & calibrate or train & evaluate or calibrate & evaluate:
        raise RuntimeError("a game is in more than one of train, calibrate, eval")
    if (train | calibrate | evaluate | reserved) & set(HOLDOUTS):
        raise RuntimeError("a sealed holdout is in the audio-learning split")
    if train & reserved or calibrate & reserved or evaluate & reserved:
        raise RuntimeError("a reserved tape is also in an active split")
    if len(EVAL) < 2:
        raise RuntimeError("the product claim needs both labeled Prime games")
