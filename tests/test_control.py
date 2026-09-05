"""The safety envelope's rules (docs/PLANNING.md §10, SPEC.md §12).

Pure policy, no Qt and no radio.
"""

from __future__ import annotations

import pytest

from catnector.control import Decision, Limits, TuneRequest, announcement, evaluate
from catnector.rig import FrequencyRange, RigHealth, RigState
from catnector.rig.caps import RigCaps

HEALTHY = RigState(freq_hz=14074000, mode="USB", health=RigHealth.OK, ptt=False)
TRANSMITTING = RigState(freq_hz=14074000, mode="USB", health=RigHealth.OK, ptt=True)
OFFLINE = RigState(health=RigHealth.OFFLINE, detail="cable unplugged")

HF_ONLY = RigCaps(model=1, rx_ranges=(FrequencyRange(1_800_000, 54_000_000),))


def tune(freq=14195000, mode="USB", **kw):
    return TuneRequest(message_id="s1", freq_hz=freq, mode=mode, **kw)


def test_a_healthy_rig_is_tuned():
    assert (
        evaluate(tune(), rig=HEALTHY, limits=Limits(), manual=False).decision is Decision.APPLY
    )


def test_no_rig_means_refusal_not_silence():
    """Silence would leave the site believing a radio moved. None did."""
    verdict = evaluate(tune(), rig=OFFLINE, limits=Limits(), manual=False)
    assert verdict.decision is Decision.REFUSE
    assert verdict.reason == "rig_offline"
    assert "cable" in verdict.detail


def test_transmitting_defers_rather_than_yanking_the_vfo():
    """Retuning mid-transmission can drive an amp matched for another band."""
    assert (
        evaluate(tune(), rig=TRANSMITTING, limits=Limits(), manual=False).decision
        is Decision.DEFER
    )


def test_an_unknown_mode_is_refused_never_substituted():
    verdict = evaluate(tune(mode="OLIVIA"), rig=HEALTHY, limits=Limits(), manual=False)
    assert verdict.decision is Decision.REFUSE
    assert verdict.reason == "unknown_mode"


def test_a_frequency_the_radio_cannot_reach_is_refused():
    verdict = evaluate(
        tune(freq=440_000_000), rig=HEALTHY, limits=Limits(caps=HF_ONLY), manual=False
    )
    assert verdict.decision is Decision.REFUSE
    assert verdict.reason == "out_of_range"
    assert "MHz" in verdict.detail


def test_unknown_capabilities_impose_no_limit():
    """A rig we know nothing about must not have a limit invented for it."""
    assert (
        evaluate(tune(freq=440_000_000), rig=HEALTHY, limits=Limits(), manual=False).decision
        is Decision.APPLY
    )


def test_operator_ranges_are_empty_by_default_and_optional():
    """No licence-privilege logic anywhere — see §10.6."""
    limits = Limits(caps=HF_ONLY)
    assert limits.operator_ranges == ()
    assert evaluate(tune(), rig=HEALTHY, limits=limits, manual=False).decision is Decision.APPLY


def test_operator_ranges_are_enforced_when_set():
    limits = Limits(caps=HF_ONLY, operator_ranges=(FrequencyRange(7_000_000, 7_300_000),))
    refused = evaluate(tune(freq=14_195_000), rig=HEALTHY, limits=limits, manual=False)
    assert refused.reason == "out_of_range"
    assert "you allowed" in refused.detail
    assert (
        evaluate(tune(freq=7_100_000), rig=HEALTHY, limits=limits, manual=False).decision
        is Decision.APPLY
    )


def test_manual_mode_offers_rather_than_discarding():
    """The toggle must not throw away the feature it is guarding."""
    assert (
        evaluate(tune(), rig=HEALTHY, limits=Limits(), manual=True).decision is Decision.OFFER
    )


def test_refusals_that_can_never_become_valid_come_before_deferral():
    """A site should hear 'no' promptly, not after a deferral times out."""
    verdict = evaluate(tune(mode="OLIVIA"), rig=TRANSMITTING, limits=Limits(), manual=False)
    assert verdict.reason == "unknown_mode"


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ({"id": "s1", "freq": 14195000}, 14195000),
        ({"id": "s1", "freq": 14195000, "mode": "USB", "passband": 2400}, 14195000),
    ],
)
def test_messages_become_requests(message, expected):
    assert TuneRequest.from_message(message).freq_hz == expected


@pytest.mark.parametrize(
    "message",
    [
        {"id": "s1"},
        {"id": "s1", "freq": "14195000"},
        {"id": "s1", "freq": 14.195},
        {"id": "s1", "freq": True},
    ],
)
def test_a_message_without_an_integer_frequency_is_not_a_tune(message):
    """SPEC.md §6.1 — integer hertz. A bool is not a frequency either."""
    assert TuneRequest.from_message(message) is None


def test_requests_describe_themselves_for_the_operator():
    assert tune(freq=14195000).describe() == "14.195 MHz USB"
    assert tune(freq=7000000, mode=None).describe() == "7 MHz"


def test_announcement_always_says_who_moved_the_radio():
    assert "W1ABC" in announcement(tune(source="Following W1ABC"), None)
    assert "W1ABC" in announcement(tune(source=""), "W1ABC")
    assert announcement(tune(source=""), None).startswith("A site")
