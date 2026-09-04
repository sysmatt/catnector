"""Protocol framing. Pure functions, no daemon needed."""

from __future__ import annotations

import pytest

from catnector.rig.wire import (
    MODES,
    format_command,
    is_terminated,
    parse_chk_vfo,
    parse_hamlib_version,
    parse_response,
)


def test_parses_a_labelled_reply():
    response = parse_response("get_mode:\nMode: USB\nPassband: 2400\nRPRT 0\n")
    assert response.ok
    assert response.value("mode") == "USB"
    assert response.value("passband") == "2400"


def test_error_replies_carry_the_hamlib_code():
    response = parse_response("get_ptt:\nRPRT -11\n")
    assert not response.ok
    assert response.rprt == -11


def test_termination_is_detected_only_on_rprt():
    assert not is_terminated("get_freq:\nFrequency: 14074000\n")
    assert is_terminated("get_freq:\nFrequency: 14074000\nRPRT 0\n")


def test_chk_vfo_has_no_rprt_terminator():
    """Real rigctld answers chk_vfo without a terminator; reads must not hang."""
    assert parse_chk_vfo("ChkVFO: 1") is True
    assert parse_chk_vfo("ChkVFO: 0") is False
    assert not is_terminated("ChkVFO: 0")


def test_vfo_mode_puts_the_vfo_first():
    """Omitting it does not error — rigctld resets the connection."""
    assert format_command("set_freq", 14074000) == "+\\set_freq 14074000\n"
    assert (
        format_command("set_freq", 14074000, vfo_mode=True) == "+\\set_freq currVFO 14074000\n"
    )


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("rigctld Hamlib 4.6.5 2025-09-05T19:49:48Z SHA=8a6bd5 64-bit", (4, 6, 5)),
        ("Hamlib 4.5", (4, 5, 0)),
    ],
)
def test_hamlib_version_parsing(text, expected):
    assert parse_hamlib_version(text) == expected


def test_unrecognisable_version_raises():
    with pytest.raises(ValueError):
        parse_hamlib_version("no version here")


def test_mode_vocabulary_matches_the_specification():
    """catnector-protocol SPEC.md §6.1 — hamlib tokens are normative."""
    for mode in ("USB", "LSB", "CW", "PKTUSB", "RTTY"):
        assert mode in MODES
    assert "OLIVIA" not in MODES
