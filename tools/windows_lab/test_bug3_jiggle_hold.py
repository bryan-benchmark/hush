"""Regression: Bug 3 — identity-gated jiggle + intended-hold quiet cap."""

from __future__ import annotations

from .heartbeat_fix import (
    _arm_intended_hold,
    _clear_intended_hold,
    _hold_fail_cap,
    _hold_quiet_s,
)
from .streamers_recover import evaluate_jiggle_intended


def _espn_intended() -> dict:
    return {
        "nav_route": "ESPN_US",
        "open_via": "nav",
        "channel_id": "MNF_ESPN",
        "shortcut_id": "MNF_ESPN",
        "label": "MNF ESPN",
    }


def test_jiggle_refuses_nfl_a_pack() -> None:
    out = evaluate_jiggle_intended(
        picture_ok=True,
        kind="player_fullscreen",
        verdict="likely_playing",
        texts=["NFL A", "NFL TEAMS/CHANNELS", "NFL 01"],
        intended=_espn_intended(),
    )
    assert out["ok"] is False
    assert out["root_cause"] == "jiggle_wrong_pack"
    assert "NFL A" in (out.get("wrong_pack") or [])


def test_jiggle_refuses_entertainment() -> None:
    out = evaluate_jiggle_intended(
        picture_ok=True,
        kind="section_grid",
        verdict="likely_playing",
        texts=["US ENTERTAINMENT", "BBC", "AWE"],
        intended=_espn_intended(),
    )
    assert out["ok"] is False
    assert out["root_cause"] == "jiggle_wrong_pack"


def test_jiggle_accepts_us_espn_row() -> None:
    out = evaluate_jiggle_intended(
        picture_ok=True,
        kind="section_grid",
        verdict="ok",
        texts=["US SPORTS", "US: ESPN", "US: ESPN 2"],
        intended=_espn_intended(),
    )
    assert out["ok"] is True
    assert out["root_cause"] == "jiggle_intended_identity_ok"
    assert out.get("matched_label") == "US: ESPN"


def test_jiggle_accepts_player_espn_chrome() -> None:
    out = evaluate_jiggle_intended(
        picture_ok=True,
        kind="player_fullscreen",
        verdict="likely_playing",
        texts=["ESPN", "LIVE", "FHD"],
        intended=_espn_intended(),
    )
    assert out["ok"] is True
    assert out["root_cause"] == "jiggle_player_chrome_ok"


def test_jiggle_rejects_espnu_as_espn_us() -> None:
    out = evaluate_jiggle_intended(
        picture_ok=True,
        kind="player_fullscreen",
        verdict="likely_playing",
        texts=["ESPNU", "LIVE"],
        intended=_espn_intended(),
    )
    assert out["ok"] is False
    assert out["root_cause"] == "jiggle_picture_ok_identity_unknown"


def test_jiggle_identity_unknown_without_markers() -> None:
    out = evaluate_jiggle_intended(
        picture_ok=True,
        kind="player_fullscreen",
        verdict="likely_playing",
        texts=["FHD", "TV guide"],
        intended=_espn_intended(),
    )
    assert out["ok"] is False
    assert out["root_cause"] == "jiggle_picture_ok_identity_unknown"


def test_unnamed_picture_ok() -> None:
    out = evaluate_jiggle_intended(
        picture_ok=True,
        kind="player_fullscreen",
        verdict="likely_playing",
        texts=["FHD"],
        intended={"channel_id": "ON_AIR_CONTINUE"},
    )
    # ON_AIR is not linear nav → unnamed picture contract
    assert out["ok"] is True
    assert out["root_cause"] == "jiggle_picture_ok_unnamed"


def test_hold_arms_quiet_after_cap() -> None:
    st: dict = {}
    cap = _hold_fail_cap()
    for i in range(cap - 1):
        q = _arm_intended_hold(st, root_cause="intended_channel_hold_no_local", channel_id="MNF_ESPN")
        assert q["quiet_armed"] is False
        assert q["fails"] == i + 1
    q = _arm_intended_hold(st, root_cause="intended_channel_hold_no_local", channel_id="MNF_ESPN")
    assert q["quiet_armed"] is True
    assert q["fails"] == cap
    assert st.get("intended_hold_quiet_until")
    assert _hold_quiet_s() >= 60.0
    _clear_intended_hold(st)
    assert "intended_hold_quiet_until" not in st
    assert "intended_hold_fails" not in st


if __name__ == "__main__":
    test_jiggle_refuses_nfl_a_pack()
    test_jiggle_refuses_entertainment()
    test_jiggle_accepts_us_espn_row()
    test_jiggle_accepts_player_espn_chrome()
    test_jiggle_rejects_espnu_as_espn_us()
    test_jiggle_identity_unknown_without_markers()
    test_unnamed_picture_ok()
    test_hold_arms_quiet_after_cap()
    print("bug3 jiggle/hold regression: PASS")
