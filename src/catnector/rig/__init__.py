"""Catnector's rig control layer.

Everything reaches the radio through hamlib's ``rigctld`` over TCP —
never by opening the serial port directly, and never by linking hamlib
in-process. See docs/PLANNING.md §8 for why.
"""

from __future__ import annotations

from .backend import PeerInfo, RigBackend, RigHealth, RigState
from .caps import RigCaps, RigModel, dump_caps, list_models
from .daemon import RigctldOptions, RigctldProcess, find_executable, hamlib_version
from .errors import (
    HamlibTooOld,
    RigCommandError,
    RigctldNotFound,
    RigError,
    RigUnavailable,
)
from .netrigctl import HAMLIB_FLOOR, NetRigctlBackend
from .wire import MODES

#: The rig profile shipped so catnector is usable, testable and demonstrable
#: with no radio attached (docs/PLANNING.md §8.1).
DUMMY_MODEL = 1

__all__ = [
    "DUMMY_MODEL",
    "HAMLIB_FLOOR",
    "MODES",
    "HamlibTooOld",
    "NetRigctlBackend",
    "PeerInfo",
    "RigBackend",
    "RigCaps",
    "RigCommandError",
    "RigError",
    "RigHealth",
    "RigModel",
    "RigState",
    "RigUnavailable",
    "RigctldNotFound",
    "RigctldOptions",
    "RigctldProcess",
    "dump_caps",
    "find_executable",
    "hamlib_version",
    "list_models",
]
