"""Serial permission diagnosis — the message matters more than the check."""

from __future__ import annotations

import sys

import pytest

from catnector.serialports import check_port, list_serial_ports


def test_missing_device_explains_itself():
    check = check_port("/dev/definitely-not-a-radio")
    assert not check.usable
    assert "cable" in check.advice.lower() or "not found" in check.advice.lower()


def test_no_device_selected():
    assert not check_port("").usable


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_permission_advice_names_a_command_to_run(tmp_path):
    """A ham who has never opened a terminal needs the exact command."""
    device = tmp_path / "ttyFake"
    device.write_text("")
    device.chmod(0o000)
    check = check_port(str(device))
    if check.usable:  # running as root
        pytest.skip("running with unrestricted access")
    assert "usermod -a -G" in check.advice
    assert "log out" in check.advice


def test_readable_device_is_usable(tmp_path):
    device = tmp_path / "ttyFake"
    device.write_text("")
    assert check_port(str(device)).usable


def test_port_listing_does_not_explode():
    assert isinstance(list_serial_ports(), list)
