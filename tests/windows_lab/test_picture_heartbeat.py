"""Picture heartbeat: blue spinner / cloud-network error in stills."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from tools.windows_lab.frame_watch import BAD_VERDICTS, heuristic_score

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.mark.skipif(not (FIXTURES / "blue_spinner_down.jpg").is_file(), reason="fixture missing")
def test_blue_spinner_detected():
    score = heuristic_score(FIXTURES / "blue_spinner_down.jpg")
    assert score.get("ok")
    assert score.get("verdict") == "blue_spinner"
    assert score.get("picture_ok") is False
    assert score.get("spinner", {}).get("hit") is True
    assert "blue_spinner" in BAD_VERDICTS


@pytest.mark.skipif(not (FIXTURES / "healthy_playing.jpg").is_file(), reason="fixture missing")
def test_healthy_frame_not_spinner():
    score = heuristic_score(FIXTURES / "healthy_playing.jpg")
    assert score.get("ok")
    assert score.get("verdict") != "blue_spinner"
    assert score.get("spinner", {}).get("hit") is False
