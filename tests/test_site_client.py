"""The site client, against the reference site from catnector-protocol.

Testing against the reference implementation rather than a mock of our own
reading of the specification is the point: if the two disagree, one of them
is wrong, and finding out here beats finding out on someone's radio.
"""

from __future__ import annotations

import json
import threading
import urllib.request

import pytest

from catnector.site import Phase, SiteClient, tokens

pytestmark = pytest.mark.protocol


def post(base: str, path: str, body: dict) -> dict:
    """Ask the reference site to do something a person would have clicked."""
    request = urllib.request.Request(
        f"{base}{path}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=15) as reply:
        return json.load(reply)


def post_async(base: str, path: str, body: dict) -> tuple[threading.Thread, dict]:
    """POST on a thread, because the site blocks until the client answers."""
    captured: dict = {}

    def run() -> None:
        try:
            captured.update(post(base, path, body))
        except Exception as exc:
            captured["error"] = repr(exc)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread, captured


@pytest.fixture
def client(qtbot, mock_site):
    site = SiteClient()
    token = tokens.decode(tokens.encode(mock_site.host, "conformance-token"))
    yield site, token
    site.disconnect_from()


def connect(qtbot, site, token, timeout=20000):
    with qtbot.waitSignal(site.welcomed, timeout=timeout) as caught:
        site.connect_to(token, site_name="Reference")
    return caught.args[0]


def test_discovery_handshake_and_identity(qtbot, client):
    site, token = client
    session = connect(qtbot, site, token)
    assert site.phase is Phase.ONLINE
    assert session.session_id
    assert session.identity == "K2TTA"
    assert session.telemetry_interval_ms > 0
    assert site.capabilities and site.capabilities.websocket_url.startswith("ws")


def test_heartbeat_keeps_the_session_alive(qtbot, client):
    """SPEC.md §10 — ping every 10 s, five unanswered is dead."""
    site, token = client
    connect(qtbot, site, token)
    site._send_ping()
    qtbot.waitUntil(lambda: site._unanswered == 0, timeout=10000)
    assert site.phase is Phase.ONLINE


def test_control_is_refused_when_no_rig_is_connected(qtbot, client, mock_site):
    """Silence would leave the site believing a radio moved. It did not."""
    site, token = client
    connect(qtbot, site, token)
    site.set_rig_available(False)

    thread, result = post_async(
        mock_site.base, "/mock/set_rig", {"freq": 14195000, "mode": "USB"}
    )
    qtbot.waitUntil(lambda: bool(result), timeout=15000)
    thread.join(timeout=5)
    assert result["result"]["type"] == "nack"
    assert result["result"]["reason"] == "rig_offline"


def test_a_required_field_we_do_not_understand_is_refused_whole(qtbot, client, mock_site):
    """SPEC.md §8.2 — never apply part of a message."""
    site, token = client
    connect(qtbot, site, token)
    site.set_rig_available(True)
    applied: list[dict] = []
    site.set_rig_received.connect(applied.append)

    thread, result = post_async(
        mock_site.base,
        "/mock/set_rig",
        {"freq": 14195000, "mode": "USB", "req": ["split"], "split": {"tx_freq": 14200000}},
    )
    qtbot.waitUntil(lambda: bool(result), timeout=15000)
    thread.join(timeout=5)
    assert result["result"]["type"] == "nack"
    assert result["result"]["reason"] == "unsupported_req"
    assert applied == [], "a refused message must not reach the rig at all"


def test_an_understood_control_message_is_delivered_and_acked(qtbot, client, mock_site):
    site, token = client
    connect(qtbot, site, token)
    site.set_rig_available(True)
    site.set_rig_received.connect(site.accept)

    thread, result = post_async(
        mock_site.base,
        "/mock/set_rig",
        {"freq": 14195000, "mode": "USB", "source": "Following W1ABC"},
    )
    qtbot.waitUntil(lambda: bool(result), timeout=15000)
    thread.join(timeout=5)
    assert result["result"]["type"] == "ack"


def test_follow_state_is_displayed_and_cleared(qtbot, client, mock_site):
    """The indicator must be able to stop claiming a follow that is over."""
    site, token = client
    connect(qtbot, site, token)

    with qtbot.waitSignal(site.follow_state_changed, timeout=15000) as caught:
        post(mock_site.base, "/mock/follow_state", {"following": "W1ABC"})
    assert caught.args[0] == "W1ABC"

    with qtbot.waitSignal(site.follow_state_changed, timeout=15000) as caught:
        post(mock_site.base, "/mock/follow_state", {"following": None})
    assert caught.args[0] is None


def test_being_superseded_is_terminal_and_does_not_reconnect(qtbot, client, mock_site):
    """SPEC.md §11. Two machines that both retry kick each other forever."""
    site, token = client
    connect(qtbot, site, token)

    other = SiteClient()
    try:
        with qtbot.waitSignal(site.closed, timeout=20000) as caught:
            other.connect_to(token, site_name="Interloper")
        code, explanation, terminal = caught.args
        assert code == 4001
        assert terminal
        assert "another computer" in explanation
        assert site.phase is Phase.STOPPED

        # Give a retry every chance to happen; it must not.
        qtbot.wait(2500)
        assert site.phase is Phase.STOPPED
        assert not site.online
    finally:
        other.disconnect_from()


def test_a_site_that_is_not_there_reports_it(qtbot, client):
    site, _ = client
    token = tokens.decode(tokens.encode("127.0.0.1:1", "x"))
    with qtbot.waitSignal(site.failed, timeout=20000) as caught:
        site.connect_to(token)
    assert "could not reach" in caught.args[0].lower()


def test_disconnecting_mid_discovery_is_safe(qtbot, client):
    """A deliberate disconnect must cancel an in-flight capability request."""
    site, _ = client
    site.connect_to(tokens.decode(tokens.encode("198.51.100.1:8443", "x")))
    site.disconnect_from()
    qtbot.wait(500)
    assert site.phase is Phase.OFFLINE


def test_deliberate_disconnect_is_not_reported_as_a_failure(qtbot, client):
    site, token = client
    connect(qtbot, site, token)
    site.disconnect_from()
    qtbot.waitUntil(lambda: site.phase is Phase.OFFLINE, timeout=10000)
    assert not site.online
