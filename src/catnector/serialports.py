"""Serial port access, and explaining it when it fails.

The setup flow should detect "permission denied" and tell the operator
exactly what to run, rather than surfacing a raw hamlib error to someone who
has never opened a terminal (docs/PLANNING.md §15, M2).
"""

from __future__ import annotations

import glob
import os
import sys
from dataclasses import dataclass

#: Groups that conventionally own serial devices on Linux distributions.
SERIAL_GROUPS = ("dialout", "uucp", "plugdev")


@dataclass(frozen=True)
class PortCheck:
    """Whether a device can be opened, and what to do when it cannot."""

    path: str
    exists: bool
    readable: bool
    writable: bool
    advice: str = ""

    @property
    def usable(self) -> bool:
        return self.exists and self.readable and self.writable


def list_serial_ports() -> list[str]:
    """Plausible serial devices, for the setup form's suggestions."""
    if sys.platform == "win32":
        return [f"COM{n}" for n in range(1, 33)]
    patterns = ("/dev/ttyUSB*", "/dev/ttyACM*", "/dev/ttyS[0-9]", "/dev/cu.*", "/dev/tty.usb*")
    found: list[str] = []
    for pattern in patterns:
        found.extend(sorted(glob.glob(pattern)))
    return found


def _group_advice(path: str) -> str:
    """Name the group that owns the device, and the command that fixes it."""
    try:
        import grp

        owner = grp.getgrgid(os.stat(path).st_gid).gr_name
    except Exception:
        owner = next(iter(SERIAL_GROUPS))
    return (
        f"You do not have permission to use {path}.\n\n"
        f"It belongs to the '{owner}' group. Add yourself with:\n\n"
        f"    sudo usermod -a -G {owner} $USER\n\n"
        "then log out and back in — a new terminal is not enough, the group "
        "is only applied at login."
    )


def check_port(path: str) -> PortCheck:
    """Can this device be used, and if not, what should the operator do?"""
    if not path:
        return PortCheck(path, False, False, False, "No device selected.")
    if not os.path.exists(path):
        if sys.platform == "win32":
            advice = (
                f"{path} was not found. Check the cable, and that the "
                "USB-serial driver (CP210x, FTDI or CH340) is installed."
            )
        else:
            advice = (
                f"{path} was not found. Check the cable — the device "
                "usually appears as /dev/ttyUSB0 or /dev/ttyACM0 when "
                "the radio is plugged in and switched on."
            )
        return PortCheck(path, False, False, False, advice)

    readable = os.access(path, os.R_OK)
    writable = os.access(path, os.W_OK)
    advice = ""
    if not (readable and writable):
        advice = (
            _group_advice(path)
            if sys.platform != "win32"
            else f"{path} exists but cannot be opened. Another program may already be using it."
        )
    return PortCheck(path, True, readable, writable, advice)
