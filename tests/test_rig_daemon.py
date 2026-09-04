"""Locating, starting and stopping rigctld."""

from __future__ import annotations

import pytest

from catnector.rig import (
    DUMMY_MODEL,
    RigctldNotFound,
    RigctldOptions,
    RigctldProcess,
    RigUnavailable,
    find_executable,
    hamlib_version,
)
from catnector.rig.daemon import EXECUTABLE, free_port

pytestmark = pytest.mark.hamlib


def test_finds_rigctld_on_path():
    assert find_executable(EXECUTABLE).exists()


def test_an_explicit_path_that_does_not_exist_says_so(tmp_path):
    with pytest.raises(RigctldNotFound):
        find_executable(EXECUTABLE, tmp_path / "nowhere")


def test_reports_the_hamlib_version():
    version = hamlib_version(find_executable(EXECUTABLE))
    assert version and version[0] >= 4


def test_starts_and_stops(dummy_daemon):
    assert dummy_daemon.running
    assert dummy_daemon.port > 0
    dummy_daemon.stop()
    assert not dummy_daemon.running
    dummy_daemon.stop()  # idempotent


def test_each_daemon_gets_its_own_port():
    """Two rig profiles must not collide."""
    assert free_port() != 0
    first = RigctldProcess(RigctldOptions(model=DUMMY_MODEL))
    second = RigctldProcess(RigctldOptions(model=DUMMY_MODEL))
    assert first.port != second.port


def test_a_daemon_that_cannot_start_fails_loudly():
    """A bad model must surface as a clear error, not a silent hang."""
    process = RigctldProcess(RigctldOptions(model=999999), startup_timeout=5.0)
    with pytest.raises(RigUnavailable):
        process.start()
    process.stop()
