"""Line-in selection for a Fire tablet headphone cable. No live audio required."""

from __future__ import annotations

import pytest

from tools.windows_lab.capture import describe_line_level, select_line_in


DEVICES = [
    {
        "index": 1,
        "name": "Microphone (MZ-631M  USB Speaker Bar )",
        "channels": 2,
        "hostapi": "Windows WASAPI",
    },
    {
        "index": 14,
        "name": "Stereo Mix (Realtek HD Audio Stereo input)",
        "channels": 2,
        "hostapi": "Windows WDM-KS",
    },
    {
        "index": 16,
        "name": "Line In (Realtek HD Audio Line input)",
        "channels": 2,
        "hostapi": "Windows WDM-KS",
    },
    {
        "index": 20,
        "name": "Line In (Realtek(R) Audio)",
        "channels": 2,
        "hostapi": "Windows WASAPI",
    },
]


def test_selects_realtek_line_in_over_mic_and_stereo_mix():
    chosen = select_line_in(DEVICES)
    assert chosen["index"] == 20
    assert "line in" in chosen["name"].lower()


def test_uses_wdm_line_in_when_the_jack_is_still_unplugged():
    unplugged = [d for d in DEVICES if d["hostapi"] != "Windows WASAPI" or "Microphone" in d["name"]]
    chosen = select_line_in(unplugged)
    assert chosen["index"] == 16


def test_missing_line_in_is_an_error():
    mics = [d for d in DEVICES if "Line In" not in d["name"]]
    with pytest.raises(LookupError):
        select_line_in(mics)


def test_mono_line_name_is_skipped():
    mono = [
        {
            "index": 3,
            "name": "Line In (headset)",
            "channels": 1,
            "hostapi": "Windows WASAPI",
        }
    ]
    with pytest.raises(LookupError):
        select_line_in(mono)


@pytest.mark.parametrize(
    ("peak", "level"),
    [(0.0, "silent"), (0.005, "quiet"), (0.2, "live"), (0.99, "clipping")],
)
def test_line_level_words(peak: float, level: str):
    assert describe_line_level(peak)["level"] == level
