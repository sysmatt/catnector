"""Shared fixtures.

Every rig test runs against a real ``rigctld`` driving hamlib's dummy rig,
so the layer is exercised against the actual protocol rather than a mock of
what we believe the protocol to be. It needs no radio, which is the point.
"""

from __future__ import annotations

import os
import shutil
from types import SimpleNamespace

import pytest

# Qt must be told to run headless before any QApplication exists. Set here
# rather than in CI so a contributor without a display gets the same result.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from catnector.rig import DUMMY_MODEL, NetRigctlBackend, RigctldOptions, RigctldProcess

HAMLIB_PRESENT = shutil.which("rigctld") is not None and shutil.which("rigctl") is not None
MOCK_SITE = shutil.which("catnector-mock-server")


def pytest_collection_modifyitems(config, items):
    """Skip tests marked ``hamlib`` when the binaries are absent.

    A marker rather than an importable decorator: test modules then need no
    cross-module imports, and CI without hamlib installed reports skips
    rather than collection errors.
    """
    if not HAMLIB_PRESENT:
        skip = pytest.mark.skip(reason="hamlib (rigctl/rigctld) is not installed")
        for item in items:
            if "hamlib" in item.keywords:
                item.add_marker(skip)
    if MOCK_SITE is None:
        skip = pytest.mark.skip(reason="catnector-protocol reference site is not installed")
        for item in items:
            if "protocol" in item.keywords:
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


@pytest.fixture
def mock_site():
    """The reference site from catnector-protocol, as a subprocess.

    A subprocess rather than an in-process server: the reference site runs on
    asyncio and these tests run a Qt event loop, and there is no reason to
    make those two share a thread.
    """
    import json
    import socket
    import subprocess
    import time
    import urllib.error
    import urllib.request

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    process = subprocess.Popen(
        [MOCK_SITE, "--port", str(port)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )

    base = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("the reference site exited during startup")
        try:
            with urllib.request.urlopen(f"{base}/.well-known/catnector", timeout=1) as reply:
                json.load(reply)
                break
        except (urllib.error.URLError, OSError, ValueError):
            time.sleep(0.1)
    else:
        process.terminate()
        raise RuntimeError("the reference site did not start")

    try:
        yield SimpleNamespace(port=port, base=base, host=f"127.0.0.1:{port}", process=process)
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


@pytest.fixture
def site_post():
    """POST to the reference site's /mock/ control surface.

    A fixture rather than a shared import: pytest puts test modules in the
    root namespace, so cross-module imports between them do not work.
    """
    import json
    import urllib.request

    def post(base: str, path: str, body: dict) -> dict:
        request = urllib.request.Request(
            f"{base}{path}",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=15) as reply:
            return json.load(reply)

    return post
