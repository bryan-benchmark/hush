"""Salvation screen decisions. No device and no real credentials."""

from tools.windows_lab.salvation import (
    credentials_filled,
    plan_step,
    playlist_name_filled,
    screen_kind,
)

LOGIN = {"service": "Salvation", "username": "user", "password": "secret", "playlist_name": "ohush"}


def test_service_list_taps_salvation():
    texts = ["Service", "Salvation", "Other One", "Cancel"]
    assert screen_kind("PlaylistWizardActivity", texts) == "service_list"
    assert plan_step("service_list", texts, LOGIN) == {"op": "tap", "label": "Salvation"}


def test_empty_credentials_types_username_first():
    texts = ["Username", "Password", "Option row", "Second option", "Next", "Back"]
    assert screen_kind("PlaylistWizardActivity", texts) == "credentials"
    user_ok, pass_ok = credentials_filled(texts)
    assert user_ok is False and pass_ok is False
    step = plan_step("credentials", texts, LOGIN)
    assert step["op"] == "type" and step["label"] == "username"


def test_username_only_types_password_next():
    texts = ["Username", "user", "Password", "Option row", "Second option", "Next", "Back"]
    user_ok, pass_ok = credentials_filled(texts)
    assert user_ok is True and pass_ok is False
    assert plan_step("credentials", texts, LOGIN)["label"] == "password"


def test_filled_credentials_tap_next():
    texts = ["Username", "user", "Password", "secret", "Option row", "Second option", "Next", "Back"]
    user_ok, pass_ok = credentials_filled(texts)
    assert user_ok is True and pass_ok is True
    assert plan_step("credentials", texts, LOGIN) == {"op": "tap", "label": "next"}


def test_playlist_name_then_done():
    empty = ["Playlist name", "Done", "Back"]
    assert screen_kind("PlaylistWizardActivity", empty) == "playlist_name"
    assert playlist_name_filled(empty) is False
    assert plan_step("playlist_name", empty, LOGIN)["label"] == "playlist name"
    filled = ["Playlist name", "ohush", "Done", "Back"]
    assert playlist_name_filled(filled) is True
    assert plan_step("playlist_name", filled, LOGIN) == {"op": "tap", "label": "done"}


def test_welcome_and_home():
    welcome = ["Welcome to Streamers", "Add a playlist to start", "Add playlist", "Settings"]
    assert screen_kind("MainActivity", welcome) == "welcome"
    assert plan_step("welcome", welcome, LOGIN) == {"op": "tap", "label": "add playlist"}
    assert screen_kind("ar.tvplayer.tv/.ui.MainActivity}", ["Live", "Channels"]) == "home"
    assert plan_step("home", [], LOGIN) == {"op": "done"}
