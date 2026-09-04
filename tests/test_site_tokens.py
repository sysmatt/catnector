"""Token encoding (SPEC.md §4.1).

Catnector implements the format rather than importing the protocol repo's
codec, so these tests are also a cross-check between two independent
implementations of the same specification.
"""

from __future__ import annotations

import random
import string

import pytest

from catnector.site import tokens


def test_round_trip():
    token = tokens.decode(tokens.encode("hamqsy.app", "sk_live_9f2c"))
    assert token.host == "hamqsy.app"
    assert token.site_token == "sk_live_9f2c"
    assert token.wellknown_url == "https://hamqsy.app/.well-known/catnector"


def test_round_trip_survives_arbitrary_content():
    """base64url contains '_', which is why the checksum separator is '.'."""
    for _ in range(500):
        host = "".join(random.choices(string.ascii_lowercase + ".-", k=12)) + ":8443"
        secret = "".join(
            random.choices(string.ascii_letters + string.digits + "_-", k=random.randint(8, 60))
        )
        decoded = tokens.decode(tokens.encode(host, secret))
        assert (decoded.host, decoded.site_token) == (host, secret)


def test_local_hosts_are_the_only_ones_allowed_plain_http():
    """SPEC.md §5.1 — the carve-out exists so the mock site needs no certs."""
    for host in ("localhost:8799", "127.0.0.1:8799", "::1"):
        assert tokens.decode(tokens.encode(host, "x")).base_url.startswith("http://")
    assert tokens.decode(tokens.encode("example.org", "x")).base_url.startswith("https://")


def test_a_truncated_token_is_reported_as_damaged_not_rejected():
    """ "That token looks damaged" is actionable; "auth failed" is not."""
    good = tokens.encode("hamqsy.app", "sk_live_9f2c")
    with pytest.raises(tokens.TokenDamaged) as caught:
        tokens.decode(good[:-2])
    assert "damaged" in str(caught.value).lower()


def test_something_that_is_not_a_token_says_so():
    with pytest.raises(tokens.TokenError) as caught:
        tokens.decode("hunter2")
    assert "cnx1_" in str(caught.value)


def test_missing_checksum_is_damaged():
    with pytest.raises(tokens.TokenDamaged):
        tokens.decode("cnx1_abcdef")
