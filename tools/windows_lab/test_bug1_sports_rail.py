"""Regression: Bug 1 soft-success — bare All / Entertainment must not pass as Sports."""

from __future__ import annotations

from .streamers_nav import (
    _dump_texts_empty,
    _guide_rail_chrome,
    _guide_rail_ready,
    _rail_has_us_sports,
    _section_open_confirmed,
    _wrong_us_parent,
)


def test_bare_all_not_ready_for_espn() -> None:
    texts = ["All channels", "Favorites", "NFL A"]
    assert _guide_rail_chrome(texts) is True
    assert _guide_rail_ready(texts, need_us_sports=True) is False
    assert _guide_rail_ready(texts, need_us_sports=False) is True


def test_entertainment_rejected_as_sports() -> None:
    texts = ["US ENTERTAINMENT", "BBC", "AWE", "All channels"]
    assert _wrong_us_parent(texts) == "US ENTERTAINMENT"
    assert _section_open_confirmed(texts, "US SPORTS") is False
    assert _guide_rail_ready(texts, need_us_sports=True) is False


def test_sports_rail_and_children_confirm() -> None:
    texts = ["US SPORTS", "US: ESPN", "US: ESPN 2", "All channels"]
    assert _rail_has_us_sports(texts) is True
    assert _guide_rail_ready(texts, need_us_sports=True) is True
    assert _section_open_confirmed(texts, "US SPORTS") is True


def test_tap_all_channels_fail_logic_when_sports_missing() -> None:
    """Mirror atom_tap_all_channels hard-fail (no soft ok:True)."""
    texts_after = ["US ENTERTAINMENT", "All channels", "NFL A"]
    ok_scroll = True and _rail_has_us_sports(texts_after)
    assert ok_scroll is False
    wrong = _wrong_us_parent(texts_after)
    assert wrong == "US ENTERTAINMENT"
    result = {
        "ok": False,
        "us_sports_visible": False,
        "wrong_parent": wrong,
        "error": "us_sports_not_visible_after_rail_scroll",
    }
    assert result["ok"] is False
    assert result["us_sports_visible"] is False


def test_empty_dump_abort_helper() -> None:
    assert _dump_texts_empty([]) is True
    assert _dump_texts_empty([""]) is True
    assert _dump_texts_empty(["US SPORTS"]) is False


if __name__ == "__main__":
    test_bare_all_not_ready_for_espn()
    test_entertainment_rejected_as_sports()
    test_sports_rail_and_children_confirm()
    test_tap_all_channels_fail_logic_when_sports_missing()
    test_empty_dump_abort_helper()
    print("bug1 soft-success regression: PASS")
