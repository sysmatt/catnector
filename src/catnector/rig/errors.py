"""Errors raised by the rig control layer.

Hamlib's own error strings are not fit to show a ham operator. The layer
translates them; these types are what the rest of catnector catches.
"""

from __future__ import annotations

#: Hamlib error codes, as returned in ``RPRT -n``.
HAMLIB_ERRORS = {
    -1: ("EINVAL", "invalid parameter"),
    -2: ("ECONF", "invalid configuration"),
    -3: ("ENOMEM", "memory shortage"),
    -4: ("ENIMPL", "function not implemented"),
    -5: ("ETIMEOUT", "communication timed out"),
    -6: ("EIO", "input/output error"),
    -7: ("EINTERNAL", "internal hamlib error"),
    -8: ("EPROTO", "protocol error"),
    -9: ("ERJCTED", "command rejected by the rig"),
    -10: ("ETRUNC", "command value truncated"),
    -11: ("ENAVAIL", "function not available on this rig"),
    -12: ("ENTARGET", "VFO not targetable"),
    -13: ("BUSERROR", "error talking on the bus"),
    -14: ("BUSBUSY", "collision on the bus"),
    -15: ("EARG", "null argument"),
    -16: ("EVFO", "invalid VFO"),
    -17: ("EDOM", "argument out of domain"),
}


class RigError(Exception):
    """Base class for every rig-layer failure."""


class RigUnavailable(RigError):
    """The rig could not be reached at all — no connection, or it dropped."""


class RigctldNotFound(RigError):
    """No ``rigctld`` binary could be located."""


class HamlibTooOld(RigError):
    """The peer's hamlib predates the supported floor."""

    def __init__(self, found: tuple[int, ...], floor: tuple[int, ...]) -> None:
        self.found, self.floor = found, floor
        super().__init__(
            f"hamlib {'.'.join(map(str, found))} is older than the supported "
            f"minimum {'.'.join(map(str, floor))}"
        )


class RigCommandError(RigError):
    """The rig or hamlib refused a command (``RPRT -n``)."""

    def __init__(self, code: int, command: str) -> None:
        self.code = code
        self.command = command
        name, description = HAMLIB_ERRORS.get(code, ("EUNKNOWN", "unknown error"))
        self.name = name
        super().__init__(f"{command}: {description} ({name}, {code})")

    @property
    def unsupported(self) -> bool:
        """True when the rig simply cannot do this, so callers can degrade."""
        return self.code in (-4, -11, -12)
