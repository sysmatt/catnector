"""The net-rigctl backend, against a real rigctld driving the dummy rig."""

from __future__ import annotations

import pytest

from catnector.rig import (
    HAMLIB_FLOOR,
    NetRigctlBackend,
    RigHealth,
    RigUnavailable,
)

pytestmark = pytest.mark.hamlib


def test_probe_learns_the_peer(rig):
    peer = rig.peer
    assert peer.vfo_mode is False
    assert peer.protocol_version == 1
    assert peer.hamlib_version >= HAMLIB_FLOOR


def test_probe_detects_vfo_mode(vfo_mode_daemon):
    """rigctld -o needs a VFO argument on every command.

    Getting this wrong is not an error response — the daemon resets the
    connection — so the probe has to be right before anything else is sent.
    """
    with NetRigctlBackend(
        port=vfo_mode_daemon.port, hamlib_version=vfo_mode_daemon.version
    ) as rig:
        assert rig.peer.vfo_mode is True
        rig.set_frequency(14074000)
        assert rig.read_state().freq_hz == 14074000


def test_set_and_read_round_trip(rig):
    rig.set_frequency(14195000)
    rig.set_mode("USB", 2400)
    state = rig.read_state()
    assert state.freq_hz == 14195000
    assert state.mode == "USB"
    assert state.passband_hz == 2400
    assert state.health is RigHealth.OK
    assert state.is_usable


def test_frequency_must_be_an_integer(rig):
    """SPEC.md §6.1 — integer hertz, never floats."""
    with pytest.raises(TypeError):
        rig.set_frequency(14.074)


def test_state_carries_its_own_age(rig):
    state = rig.read_state()
    assert state.read_at_ms > 0
    assert state.age_ms(state.read_at_ms + 1500) == 1500


def test_a_dead_daemon_reports_offline_rather_than_raising(rig, dummy_daemon):
    """read_state never raises: a failure is a health value, not an exception.

    "Site connected, rig offline" has to be reportable (SPEC.md §7.3).
    """
    assert rig.read_state().health is RigHealth.OK
    dummy_daemon.stop()
    state = rig.read_state()
    assert state.health is RigHealth.OFFLINE
    assert state.detail


def test_commands_after_disconnect_raise(rig, dummy_daemon):
    dummy_daemon.stop()
    rig.read_state()  # notices the loss and closes
    with pytest.raises(RigUnavailable):
        rig.set_frequency(14074000)


def test_connecting_to_nothing_fails_clearly():
    backend = NetRigctlBackend(port=1)
    with pytest.raises(RigUnavailable) as caught:
        backend.open()
    assert "cannot reach rigctld" in str(caught.value)
    assert not backend.connected


def test_ptt_is_read_without_breaking_rigs_that_cannot(rig):
    """None means "unknown now", not "unsupported" — see NetRigctlBackend._read_ptt."""
    for _ in range(3):
        assert rig.read_state().ptt in (True, False, None)
