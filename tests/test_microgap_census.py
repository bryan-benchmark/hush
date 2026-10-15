"""The near-silence scanner finds an injected digital hole and ignores loud noise."""

import numpy as np

from experiments.microgap_census.scan import WIN, runs_from_db, window_db


def test_injected_50ms_zero_is_one_deep_run():
    rng = np.random.default_rng(0)
    audio = (0.1 * rng.standard_normal((48000, 2))).astype(np.float32)
    audio[int(0.40 * 48000) : int(0.45 * 48000)] = 0
    levels = window_db(audio)
    deep = runs_from_db(levels, 0.0, -80.0)
    shallow = runs_from_db(levels, 0.0, -20.0)
    assert len(deep) == 1
    assert 0.39 <= deep[0]["start"] <= 0.41
    assert 0.045 <= deep[0]["duration"] <= 0.055
    assert shallow
    assert all(event["duration"] < 0.2 for event in deep)


def test_window_is_five_milliseconds():
    assert WIN == 240
