"""TNF lab control rules. No audio device."""

from ohush_live.tnf_lab import TnfLab


def _families(score: float, *, booth: bool = False, strong: bool = False) -> dict:
    return {
        "audio": {"departure": score, "strong_departure": strong or score >= 0.22},
        "speaker": {
            "speech": booth,
            "booth_present": booth,
            "similarity_to_booth": 0.8 if booth else 0.1,
            "strong_departure": False,
            "strong_return": booth,
        },
        "semantic": None,
    }


def test_observe_and_suggest_do_not_switch_audio():
    lab = TnfLab()
    for mode in ("observe", "suggest"):
        lab.configure(mode=mode, t=0)
        for second in range(1, 8):
            out = lab.tick(second, second * 48000, _families(0.3, strong=True))
            assert out["audio"] is None
    assert lab.view()["fingerprint"] == "not_run"


def test_auto_covers_on_departure_and_ignores_a_vanished_match():
    lab = TnfLab()
    lab.configure(mode="auto", return_policy="manual", fail_open_s=30, t=0)
    assert lab.tick(1, 1, _families(0.2))["audio"] is None
    assert lab.tick(2, 2, _families(0.2))["audio"] == "cover"
    for second in range(3, 12):
        out = lab.tick(second, second, _families(0.01))
        assert out["audio"] is None
        assert lab.covering is True


def test_show_wins_and_stays_won_while_the_detector_is_still_hot():
    lab = TnfLab()
    lab.configure(mode="auto", return_policy="manual", t=0)
    lab.tick(1, 1, _families(0.2))
    lab.tick(2, 2, _families(0.2))
    lab.note_human("play", 3, 3)
    assert lab.manual_rescues == 1
    out = lab.tick(4, 4, _families(0.2))
    assert out["audio"] is None
    assert lab.covering is False


def test_fail_open_and_kill_return_to_play():
    lab = TnfLab()
    lab.configure(mode="auto", return_policy="manual", fail_open_s=30, t=0)
    lab.tick(1, 1, _families(0.2))
    assert lab.tick(2, 2, _families(0.2))["audio"] == "cover"
    assert lab.tick(32, 32, _families(0.2))["audio"] == "play"
    lab.configure(mode="auto", t=33)
    lab.tick(34, 34, _families(0.2))
    lab.tick(35, 35, _families(0.2))
    assert lab.kill(36)["audio"] == "play"
    assert lab.mode == "observe"
    assert lab.fail_open("device lost", 37)["audio"] == "play"
    assert lab.mode == "observe"


def test_machine_return_needs_a_positive_booth_match():
    lab = TnfLab()
    lab.configure(mode="auto", return_policy="machine", fail_open_s=180, t=0)
    lab.tick(1, 1, _families(0.2))
    lab.tick(2, 2, _families(0.2))
    assert lab.covering
    # Score stays hot, so only the booth match is allowed to restore.
    assert lab.tick(3, 3, _families(0.2))["audio"] is None
    assert lab.tick(4, 4, _families(0.2, booth=True))["audio"] is None
    assert lab.tick(5, 5, _families(0.2, booth=True))["audio"] is None
    assert lab.tick(6, 6, _families(0.2, booth=True))["audio"] == "play"
    # The score is still hot. A machine return must not immediately re-cover.
    assert lab.tick(7, 7, _families(0.2))["audio"] is None
    assert lab.tick(8, 8, _families(0.2))["audio"] is None
    assert lab.covering is False


def test_machine_cover_ends_when_the_authorizing_score_drops():
    lab = TnfLab()
    lab.configure(mode="auto", return_policy="machine", fail_open_s=180, t=0)
    assert lab.tick(1, 1, _families(0.2))["audio"] is None
    assert lab.tick(2, 2, _families(0.2))["audio"] == "cover"
    assert lab.tick(3, 3, _families(0.05))["audio"] is None
    assert lab.tick(4, 4, _families(0.05))["audio"] == "play"
    assert lab.covering is False
    # Quiet score stays quiet: do not start another cover.
    assert lab.tick(5, 5, _families(0.05))["audio"] is None
    assert lab.tick(6, 6, _families(0.05))["audio"] is None


def test_human_cover_is_not_cleared_by_a_quiet_score():
    lab = TnfLab()
    lab.configure(mode="auto", return_policy="machine", fail_open_s=30, t=0)
    lab.note_human("mute", 1, 1)
    for second in range(2, 12):
        out = lab.tick(second, second, _families(0.01))
        assert out["audio"] is None
        assert lab.covering is True
    assert lab.tick(40, 40, _families(0.01))["audio"] is None
    lab.note_human("play", 41, 41)
    assert lab.covering is False


def test_consecutive_machine_covers_do_not_stick():
    lab = TnfLab()
    lab.configure(mode="auto", return_policy="machine", fail_open_s=180, t=0)
    t = 0
    for _ in range(4):
        t += 1
        assert lab.tick(t, t, _families(0.3))["audio"] is None
        t += 1
        assert lab.tick(t, t, _families(0.3))["audio"] == "cover"
        t += 1
        assert lab.tick(t, t, _families(0.05))["audio"] is None
        t += 1
        assert lab.tick(t, t, _families(0.05))["audio"] == "play"
        t += 1
        lab.tick(t, t, _families(0.05))
        t += 1
        lab.tick(t, t, _families(0.05))
    assert lab.machine_covers == 4
    assert lab.covering is False


def test_record_only_releases_a_machine_cover():
    lab = TnfLab()
    lab.configure(mode="auto", return_policy="machine", t=0)
    lab.tick(1, 1, _families(0.3))
    assert lab.tick(2, 2, _families(0.3))["audio"] == "cover"
    assert lab.tick(3, 3, _families(0.3), record_only=True)["audio"] == "play"
    assert lab.covering is False
    assert lab.tick(4, 4, _families(0.3), record_only=True)["audio"] is None


def test_missing_score_restores_a_machine_cover():
    lab = TnfLab()
    lab.configure(mode="auto", return_policy="machine", fail_open_s=180, t=0)
    lab.tick(1, 1, _families(0.3))
    assert lab.tick(2, 2, _families(0.3))["audio"] == "cover"
    assert lab.tick(3, 3, None)["audio"] is None
    assert lab.tick(4, 4, None)["audio"] == "play"


def test_human_label_does_not_change_the_mode():
    lab = TnfLab()
    lab.label("commercial", 10, 10, 10)
    lab.label("program", 20, 20, 20)
    assert lab.mode == "observe"
    assert lab.covering is False
