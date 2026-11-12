"""Kept research cover latch, adapted for the live desk.

Acoustic start: frame_mn10 + frozen GRU head + 0.90/0.50 × 8/2 controller.
Live cooldown: after a cover→play transition, force play for 8s (causal stand-in
for the label-oracle cooldown_8s after accepted ad ends).

Voice panel vetoes (Clarissa/Whit/Palmer/Fitz) are not wired here yet — they need
portable ECAPA prototypes and a live Clarissa ad gate.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MODELS = REPO / "ohush_live" / "models"
CACHE = REPO / "ohush_live" / "cache" / "research_muter"
WEIGHTS = CACHE / "frame_mn10_strong_1.pt"
HEAD = MODELS / "frozen_head.pt"

# Locked operating point from experiments.audio_learn.studio_fit.CONTROLLER
ON = 0.90
OFF = 0.50
ON_STREAK = 8
OFF_STREAK = 2
COOLDOWN_S = 8.0
HOP_S = 0.25
SR = 16000
WINDOW_S = 4.0
CONTEXT_S = 10.0
SEQUENCE = 16

FRAME_MN10_URL = (
    "https://github.com/fschmid56/PretrainedSED/releases/download/v0.0.1/frame_mn10_strong_1.pt"
)
FRAME_MN10_SHA256 = "4a0fe320d5369987b772394c51881fb20a602967e6842f72f3e5c8181065ece7"
FROZEN_HEAD_SHA256 = "58b8ad09f2da60b519b05558935d25c9b79a20ef288b15838c337748abc20bf2"


def assets_ready() -> tuple[bool, str]:
    if not HEAD.is_file():
        return False, f"missing frozen head at {HEAD}"
    if not WEIGHTS.is_file():
        # Fall back to the Windows lab copy if present.
        lab = Path(r"C:\OHushData\gpu_lab\audio_learn\weights\frame_mn10_strong_1.pt")
        if lab.is_file():
            CACHE.mkdir(parents=True, exist_ok=True)
            WEIGHTS.write_bytes(lab.read_bytes())
        else:
            return False, f"missing frame_mn10 at {WEIGHTS} (fetch {FRAME_MN10_URL})"
    if not (REPO / "third_party" / "PretrainedSED" / "models" / "frame_mn" / "Frame_MN_wrapper.py").is_file():
        return False, "PretrainedSED missing under third_party/PretrainedSED"
    return True, "ok"


@dataclass
class LiveController:
    """Online copy of experiments.audio_learn.controller.decisions."""

    on: float = ON
    off: float = OFF
    on_streak: int = ON_STREAK
    off_streak: int = OFF_STREAK
    cooldown_s: float = COOLDOWN_S
    state: str = "play"
    hot: int = 0
    cold: int = 0
    force_play_until: float = 0.0

    def step(self, t: float, probability: float) -> dict:
        probability = float(probability)
        t = float(t)
        if t < self.force_play_until:
            probability = 0.0
        prior = self.state
        if self.state == "play":
            self.hot = self.hot + 1 if probability >= self.on else 0
            if self.hot >= self.on_streak:
                self.state = "cover"
                self.cold = 0
        else:
            self.cold = self.cold + 1 if probability <= self.off else 0
            if self.cold >= self.off_streak:
                self.state = "play"
                self.hot = 0
                # Causal stand-in for cooldown after an ad end: stay on play.
                self.force_play_until = max(self.force_play_until, t + self.cooldown_s)
        return {
            "t": t,
            "action": "cover" if self.state == "cover" else "play",
            "probability": probability,
            "raw_probability": float(probability) if t >= self.force_play_until else None,
            "transition": prior != self.state,
            "force_play": t < self.force_play_until,
            "state_before": prior,
        }
