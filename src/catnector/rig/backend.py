"""The rig control interface the rest of catnector talks to.

Deliberately synchronous and blocking. Rig I/O runs on its own worker
thread (docs/PLANNING.md §8.4), so a blocking API is the simple, correct
shape here; making it async would buy nothing and complicate the Qt
integration in M2.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum


class RigHealth(str, Enum):
    """Rig health, reported separately from session health.

    "Site connected, rig offline" is a real and common state — cable pulled,
    control software gone, permissions wrong — and the site must be able to
    show it rather than displaying a stale frequency as though it were live.
    See catnector-protocol SPEC.md §7.3.
    """

    OK = "ok"
    OFFLINE = "offline"
    ERROR = "error"


@dataclass(frozen=True)
class RigState:
    """A snapshot of the rig, and when it was taken.

    ``read_at_ms`` exists so a stale value can be *reported as stale* rather
    than silently passed off as current.
    """

    freq_hz: int | None = None
    mode: str | None = None
    passband_hz: int | None = None
    ptt: bool | None = None
    health: RigHealth = RigHealth.OFFLINE
    read_at_ms: int = 0
    detail: str = ""

    @property
    def is_usable(self) -> bool:
        return self.health is RigHealth.OK and self.freq_hz is not None

    def age_ms(self, now_ms: int | None = None) -> int:
        return (now_ms if now_ms is not None else int(time.time() * 1000)) - self.read_at_ms


@dataclass(frozen=True)
class PeerInfo:
    """What a probe learned about the far end (SPEC-adjacent, §8.2)."""

    hamlib_version: tuple[int, int, int] | None = None
    vfo_mode: bool = False
    protocol_version: int | None = None
    model_name: str = ""

    @property
    def version_text(self) -> str:
        if not self.hamlib_version:
            return "unknown"
        return ".".join(str(part) for part in self.hamlib_version)


class RigBackend(ABC):
    """How catnector reaches a radio.

    Only one implementation exists (`NetRigctlBackend`) and that is the
    intended state: catnector always talks to hamlib over the rigctl network
    protocol, never by opening the serial port itself. The interface exists
    so that a future in-process backend remains possible, not because one is
    planned.
    """

    @abstractmethod
    def open(self) -> PeerInfo:
        """Connect and probe. Raises RigError on failure."""

    @abstractmethod
    def close(self) -> None:
        """Disconnect. Must be safe to call when already closed."""

    @abstractmethod
    def read_state(self) -> RigState:
        """Read the rig. Never raises — failures come back as health."""

    @abstractmethod
    def set_frequency(self, hz: int) -> None:
        """Set frequency in hertz. Integers only."""

    @abstractmethod
    def set_mode(self, mode: str, passband_hz: int | None = None) -> None:
        """Set a hamlib mode token, optionally with a filter width."""

    @property
    @abstractmethod
    def connected(self) -> bool: ...
