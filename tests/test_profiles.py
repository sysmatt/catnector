"""Rig profile storage. The file is meant to be hand-edited, so parsing is
forgiving and never raises on bad input."""

from __future__ import annotations

from catnector.profiles import (
    ATTACH,
    DUMMY_PROFILE_NAME,
    MANAGED,
    RigProfile,
    dummy_profile,
    load_profiles,
    save_profiles,
    with_unique_name,
)


def test_round_trip(tmp_path):
    path = tmp_path / "rigs.ini"
    original = [
        RigProfile(name="Shack FT-991", model=1035, device="/dev/ttyUSB0", serial_speed=38400),
        RigProfile(name="flrig", model=4, host="127.0.0.1", port=12345),
        RigProfile(name="Club rigctld", model=2, connection=ATTACH, host="10.0.0.5", port=4532),
    ]
    save_profiles(path, original)
    loaded = load_profiles(path)
    assert [p.name for p in loaded] == [p.name for p in original]
    assert loaded[0].serial_speed == 38400
    assert loaded[2].connection == ATTACH


def test_missing_file_is_not_an_error(tmp_path):
    assert load_profiles(tmp_path / "absent.ini") == []


def test_hand_edited_nonsense_does_not_raise(tmp_path):
    """Operators edit this file. Bad values fall back, they do not crash."""
    path = tmp_path / "rigs.ini"
    path.write_text(
        "[Broken]\nmodel = not-a-number\nconnection = sideways\n"
        "serial_speed = fast\nport = ???\n"
    )
    profile = load_profiles(path)[0]
    assert profile.model == 1
    assert profile.connection == MANAGED
    assert profile.serial_speed is None
    assert profile.port == 0


def test_truncated_file_is_not_an_error(tmp_path):
    path = tmp_path / "rigs.ini"
    path.write_text("[Half")
    assert load_profiles(path) == []


def test_the_builtin_dummy_is_never_written_out(tmp_path):
    """It is provided by the app; writing it would imply it can be edited."""
    path = tmp_path / "rigs.ini"
    save_profiles(path, [dummy_profile(), RigProfile(name="Real", model=1035)])
    assert DUMMY_PROFILE_NAME not in path.read_text()
    assert [p.name for p in load_profiles(path)] == ["Real"]


def test_saved_file_says_it_is_safe_to_copy(tmp_path):
    path = tmp_path / "rigs.ini"
    save_profiles(path, [RigProfile(name="Real", model=1035)])
    assert "no credentials" in path.read_text()


def test_names_are_deduplicated():
    existing = [RigProfile(name="Rig"), RigProfile(name="Rig (2)")]
    assert with_unique_name(existing, RigProfile(name="Rig")).name == "Rig (3)"
    assert with_unique_name(existing, RigProfile(name="Other")).name == "Other"


def test_daemon_options_carry_the_profile():
    profile = RigProfile(name="x", model=1035, device="/dev/ttyUSB0", serial_speed=38400)
    options = profile.daemon_options()
    assert options.model == 1035
    assert options.device == "/dev/ttyUSB0"
    assert options.serial_speed == 38400
