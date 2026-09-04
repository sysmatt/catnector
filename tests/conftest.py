"""Shared fixtures.

Every rig test runs against a real ``rigctld`` driving hamlib's dummy rig,
so the layer is exercised against the actual protocol rather than a mock of
what we believe the protocol to be. It needs no radio, which is the point.
"""

from __future__ import annotations

import shutil

import pytest

from catnector.rig import DUMMY_MODEL, NetRigctlBackend, RigctldOptions, RigctldProcess

HAMLIB_PRESENT = shutil.which("rigctld") is not None and shutil.which("rigctl") is not None


def pytest_collection_modifyitems(config, items):
    """Skip tests marked ``hamlib`` when the binaries are absent.

    A marker rather than an importable decorator: test modules then need no
    cross-module imports, and CI without hamlib installed reports skips
    rather than collection errors.
    """
    if HAMLIB_PRESENT:
        return
    skip = pytest.mark.skip(reason="hamlib (rigctl/rigctld) is not installed")
    for item in items:
        if "hamlib" in item.keywords:
            item.add_marker(skip)


@pytest.fixture
def dummy_daemon():
    """A rigctld running hamlib's dummy rig on an ephemeral port."""
    with RigctldProcess(RigctldOptions(model=DUMMY_MODEL)) as daemon:
        yield daemon


@pytest.fixture
def vfo_mode_daemon():
    """A rigctld in VFO mode (``-o``), where commands need a VFO argument."""
    with RigctldProcess(RigctldOptions(model=DUMMY_MODEL, extra_args=("-o",))) as daemon:
        yield daemon


@pytest.fixture
def rig(dummy_daemon):
    with NetRigctlBackend(
        port=dummy_daemon.port, hamlib_version=dummy_daemon.version
    ) as backend:
        yield backend
