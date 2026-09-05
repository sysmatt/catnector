"""Outbound telemetry (SPEC.md §9.1, §7.3)."""

from __future__ import annotations

import pytest

from catnector.gui.telemetry import Telemetry
from catnector.rig import RigHealth, RigState
from catnector.site.messages import report


def state(freq=14074000, mode="USB", health=RigHealth.OK, read_at_ms=1788451200000):
    return RigState(
        freq_hz=freq, mode=mode, passband_hz=2400, health=health, read_at_ms=read_at_ms
    )


def test_a_report_carries_when_it_was_read_not_when_it_was_sent():
    """So a site can show a value's age rather than implying currency."""
    message = report(
        "t1",
        freq_hz=14074000,
        mode="USB",
        passband_hz=2400,
        rig_profile="Shack",
        rig_health="ok",
        read_at_ms=1788451200000,
    )
    assert message["ts"] == 1788451200000
    assert message["rig"] == {"profile": "Shack", "health": "ok"}
    assert message["freq"] == 14074000


def test_a_report_from_an_unreachable_rig_may_carry_no_frequency():
    message = report(
        "t1",
        freq_hz=None,
        mode=None,
        passband_hz=None,
        rig_profile="Shack",
        rig_health="offline",
        read_at_ms=1,
    )
    assert "freq" not in message
    assert message["rig"]["health"] == "offline"


@pytest.fixture
def telemetry(qtbot):
    sender = Telemetry()
    sender.configure(60, "Shack FT-991")
    return sender


def test_nothing_is_sent_before_it_is_started(qtbot, telemetry):
    sent: list = []
    telemetry.report_ready.connect(sent.append)
    telemetry.rig_state_changed(state())
    qtbot.wait(200)
    assert sent == []


def test_state_is_reported_once_started(qtbot, telemetry):
    telemetry.start()
    telemetry.rig_state_changed(state())
    with qtbot.waitSignal(telemetry.report_ready, timeout=3000) as caught:
        pass
    message = caught.args[0]
    assert message["freq"] == 14074000
    assert message["rig"]["profile"] == "Shack FT-991"


def test_unchanged_state_is_not_resent(qtbot, telemetry):
    """The heartbeat demonstrates liveness; telemetry reports change."""
    sent: list = []
    telemetry.report_ready.connect(sent.append)
    telemetry.start()
    telemetry.rig_state_changed(state())
    qtbot.wait(400)
    assert len(sent) == 1

    telemetry.rig_state_changed(state())
    qtbot.wait(300)
    assert len(sent) == 1, "identical state must not be reported again"

    telemetry.rig_state_changed(state(freq=14195000))
    qtbot.waitUntil(lambda: len(sent) == 2, timeout=3000)
    assert sent[1]["freq"] == 14195000


def test_health_changes_are_reported_even_at_the_same_frequency(qtbot, telemetry):
    """ "Connected, rig offline" is exactly what a site needs to show."""
    sent: list = []
    telemetry.report_ready.connect(sent.append)
    telemetry.start()
    telemetry.rig_state_changed(state())
    qtbot.waitUntil(lambda: len(sent) == 1, timeout=3000)
    telemetry.rig_state_changed(state(health=RigHealth.OFFLINE))
    qtbot.waitUntil(lambda: len(sent) == 2, timeout=3000)
    assert sent[1]["rig"]["health"] == "offline"


def test_the_site_sets_the_rate(qtbot, telemetry):
    """A site can change its load characteristics with no catnector release."""
    sent: list = []
    telemetry.report_ready.connect(sent.append)
    telemetry.configure(1000, "Shack")
    telemetry.start()
    telemetry.rig_state_changed(state())
    qtbot.wait(300)
    assert sent == [], "must not report faster than the negotiated interval"
    qtbot.waitUntil(lambda: len(sent) == 1, timeout=3000)


def test_stopping_ends_reporting(qtbot, telemetry):
    sent: list = []
    telemetry.report_ready.connect(sent.append)
    telemetry.start()
    telemetry.rig_state_changed(state())
    qtbot.waitUntil(lambda: len(sent) == 1, timeout=3000)
    telemetry.stop()
    telemetry.rig_state_changed(state(freq=14195000))
    qtbot.wait(300)
    assert len(sent) == 1
