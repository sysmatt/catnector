"""Timing behaviour of the safety envelope: countdown, deferral, coalescing."""

from __future__ import annotations

import pytest

from catnector.control import Limits, TuneRequest
from catnector.gui.controller import TuneController
from catnector.rig import FrequencyRange, RigHealth, RigState
from catnector.rig.caps import RigCaps

HEALTHY = RigState(freq_hz=14074000, mode="USB", health=RigHealth.OK, ptt=False)
TRANSMITTING = RigState(freq_hz=14074000, mode="USB", health=RigHealth.OK, ptt=True)


def message(message_id="s1", freq=14195000, mode="USB", source=""):
    return {
        "v": 1,
        "type": "set_rig",
        "id": message_id,
        "freq": freq,
        "mode": mode,
        "source": source,
    }


@pytest.fixture
def controller(qtbot):
    control = TuneController()
    control.set_rig_state(HEALTHY)
    return control


def test_the_first_tune_of_a_session_is_announced_before_it_happens(qtbot, controller):
    """Warn once on entry — a radio should not move without saying why."""
    with qtbot.waitSignal(controller.announced, timeout=3000) as caught:
        controller.submit(message(source="Following W1ABC"))
    text, seconds = caught.args
    assert "W1ABC" in text and seconds > 0

    with qtbot.waitSignal(controller.apply_requested, timeout=8000) as applied:
        pass
    assert applied.args[0].freq_hz == 14195000


def test_later_tunes_apply_immediately(qtbot, controller):
    """A countdown on every follow update would train people to ignore it."""
    with qtbot.waitSignal(controller.apply_requested, timeout=8000):
        controller.submit(message("s1"))
    qtbot.wait(1100)  # clear the rate gate
    with qtbot.waitSignal(controller.apply_requested, timeout=3000) as caught:
        controller.submit(message("s2", freq=14200000))
    assert caught.args[0].freq_hz == 14200000


def test_a_tune_can_be_cancelled_during_the_countdown(qtbot, controller):
    with qtbot.waitSignal(controller.announced, timeout=3000):
        controller.submit(message("s1"))
    with qtbot.waitSignal(controller.refused, timeout=3000) as caught:
        controller.cancel_announcement()
    assert caught.args[0] == "s1"
    assert caught.args[1] == "rejected"


def test_transmitting_holds_the_tune_then_applies_it(qtbot, controller):
    controller.set_rig_state(TRANSMITTING)
    with qtbot.waitSignal(controller.announced, timeout=3000) as caught:
        controller.submit(message("s1"))
    assert "transmitting" in caught.args[0].lower()

    controller.set_rig_state(HEALTHY)
    with qtbot.waitSignal(controller.apply_requested, timeout=5000) as applied:
        pass
    assert applied.args[0].message_id == "s1"


def test_a_superseded_tune_is_answered_not_queued(qtbot, controller):
    """Applying a backlog makes the radio chase positions already stale."""
    controller.set_rig_state(TRANSMITTING)
    controller.submit(message("s1", freq=14195000))
    with qtbot.waitSignal(controller.refused, timeout=3000) as caught:
        controller.submit(message("s2", freq=14200000))
    assert caught.args[0] == "s1"
    assert "superseded" in caught.args[2]


def test_manual_mode_offers_the_tune_and_waits(qtbot, controller):
    controller.manual = True
    with qtbot.waitSignal(controller.pending_changed, timeout=3000) as caught:
        controller.submit(message("s1", source="Tune to W1ABC"))
    assert isinstance(caught.args[0], TuneRequest)

    with qtbot.waitSignal(controller.apply_requested, timeout=3000) as applied:
        controller.accept_pending()
    assert applied.args[0].message_id == "s1"


def test_declining_a_manual_tune_tells_the_site(qtbot, controller):
    controller.manual = True
    with qtbot.waitSignal(controller.pending_changed, timeout=3000):
        controller.submit(message("s1"))
    with qtbot.waitSignal(controller.refused, timeout=3000) as caught:
        controller.dismiss_pending()
    assert caught.args[1] == "rejected"


def test_a_flood_of_tunes_cannot_spin_the_vfo(qtbot, controller):
    """§10.3 — the radio's speed is the real limit; this is the backstop."""
    applied: list = []
    refused: list = []
    controller.apply_requested.connect(applied.append)
    controller.refused.connect(lambda mid, reason, detail: refused.append(reason))

    with qtbot.waitSignal(controller.apply_requested, timeout=8000):
        controller.submit(message("s1"))
    for index in range(2, 8):
        controller.submit(message(f"s{index}", freq=14195000 + index * 1000))
    qtbot.wait(300)

    assert len(applied) == 1, "only the first tune should have reached the radio"
    assert refused, "the rest must be answered, not dropped"


def test_an_out_of_range_tune_never_reaches_the_radio(qtbot, controller):
    controller.limits = Limits(
        caps=RigCaps(model=1, rx_ranges=(FrequencyRange(1_800_000, 54_000_000),))
    )
    applied: list = []
    controller.apply_requested.connect(applied.append)
    with qtbot.waitSignal(controller.refused, timeout=3000) as caught:
        controller.submit(message("s1", freq=440_000_000))
    assert caught.args[1] == "out_of_range"
    assert applied == []


def test_reset_forgets_everything(qtbot, controller):
    controller.manual = True
    controller.submit(message("s1"))
    controller.reset()
    assert controller.pending is None
