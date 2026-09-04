"""Message construction and close-code policy (SPEC.md §7, §8.2, §11)."""

from __future__ import annotations

import pytest

from catnector.site import messages


def test_hello_advertises_what_this_client_supports():
    message = messages.hello("c1", "catnector", "0.1.0")
    assert message["v"] == 1 and message["type"] == "hello"
    assert set(message["features"]) == set(messages.CLIENT_FEATURES)


def test_welcome_is_parsed_into_something_displayable():
    session = messages.parse_welcome(
        {
            "session": {"id": "s1", "user": "matt@example.invalid", "callsign": "K2TTA"},
            "telemetry_interval_ms": 500,
            "features": ["follow_state"],
        },
        site_name="HamQSY",
        host="hamqsy.app",
    )
    assert session.identity == "K2TTA"
    assert session.telemetry_interval_ms == 500
    assert session.supports("follow_state")


def test_identity_falls_back_when_a_site_sends_no_callsign():
    session = messages.parse_welcome({"session": {"id": "s1", "user": "a@b.invalid"}})
    assert session.identity == "a@b.invalid"
    assert messages.parse_welcome({}).identity == "unknown"


@pytest.mark.parametrize("code", [4001, 4002, 4003])
def test_terminal_codes_are_terminal(code):
    """A client that retries these fights the machine that replaced it."""
    assert messages.is_terminal(code)
    assert messages.explain_close(code)


@pytest.mark.parametrize("code", [4004, 1006, 1001, 0])
def test_everything_else_is_transient(code):
    assert not messages.is_terminal(code)


def test_supersede_explanation_names_the_actual_cause():
    text = messages.explain_close(messages.CLOSE_SUPERSEDED)
    assert "another computer" in text
    assert "one catnector session" in text.lower()


def test_req_fields_we_do_not_understand_are_reported():
    """Ignoring a `split` field would put an operator on top of the DX."""
    message = {"freq": 1, "req": ["split", "freq"]}
    assert messages.unsupported_required_fields(message, {"freq", "mode"}) == ["split"]
    assert messages.unsupported_required_fields({"freq": 1}, {"freq"}) == []


def test_nack_carries_a_reason_and_optional_detail():
    message = messages.nack("c9", "s4", "unsupported_req", "no split here")
    assert message["re"] == "s4" and message["reason"] == "unsupported_req"
    assert message["detail"] == "no split here"
