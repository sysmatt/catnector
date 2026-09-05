"""The safety envelope for inbound control (docs/PLANNING.md §10).

A site instructs; catnector decides. These rules exist because the protocol
lets a website move physical equipment belonging to someone who is not
looking at the screen at that moment.

Deliberately pure — no Qt, no I/O — so every rule is testable directly. The
timing machinery that uses it (countdowns, deferral, coalescing) lives in
`gui.controller`.

`SPEC.md` §12 makes most of this binding on any conforming client. What is
here is how catnector meets it, and where it goes further.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .rig import MODES, FrequencyRange, RigCaps, RigHealth, RigState

#: Never apply changes faster than this, whatever the site sends
#: (docs/PLANNING.md §10.3). The real ceiling is the radio; this is a
#: backstop for a site that misbehaves.
MAX_APPLY_RATE_MS = 1000

#: How long to hold a tune while the operator is transmitting before giving
#: up on it. Applying it late would move the radio at an arbitrary moment.
PTT_DEFER_TIMEOUT_MS = 15_000

#: Countdown shown before the first tune of a session (§10.4).
ANNOUNCE_SECONDS = 2


class Decision(str, Enum):
    APPLY = "apply"  # do it now
    DEFER = "defer"  # hold: the operator is transmitting
    OFFER = "offer"  # manual mode: present it, do not act
    REFUSE = "refuse"  # nack, with a reason


@dataclass(frozen=True)
class TuneRequest:
    """One inbound `set_rig`, reduced to what catnector acts on."""

    message_id: str
    freq_hz: int
    mode: str | None = None
    passband_hz: int | None = None
    source: str = ""

    @classmethod
    def from_message(cls, message: dict) -> TuneRequest | None:
        """None when the message is not usable as a tune."""
        freq = message.get("freq")
        if not isinstance(freq, int) or isinstance(freq, bool):
            return None
        passband = message.get("passband")
        mode = message.get("mode")
        return cls(
            message_id=str(message.get("id", "")),
            freq_hz=freq,
            mode=str(mode) if isinstance(mode, str) else None,
            passband_hz=passband if isinstance(passband, int) else None,
            source=str(message.get("source") or ""),
        )

    def describe(self) -> str:
        megahertz = self.freq_hz / 1_000_000
        parts = [f"{megahertz:.6f}".rstrip("0").rstrip(".") + " MHz"]
        if self.mode:
            parts.append(self.mode)
        return " ".join(parts)


@dataclass(frozen=True)
class Verdict:
    decision: Decision
    reason: str = ""  # a SPEC.md §7.6 nack reason when refusing
    detail: str = ""

    @property
    def refused(self) -> bool:
        return self.decision is Decision.REFUSE


@dataclass
class Limits:
    """What the operator and the radio allow."""

    caps: RigCaps | None = None
    #: Operator-configured ranges. **Empty by default and never required.**
    #: Catnector deliberately implements no licence-privilege checking:
    #: worldwide privilege data drifts constantly, a wrong answer is worse
    #: than no answer, and the licensed operator is the only party who
    #: transmits (docs/PLANNING.md §10.6).
    operator_ranges: tuple[FrequencyRange, ...] = field(default_factory=tuple)

    def rejects(self, hz: int) -> str:
        """A reason the frequency is not allowed, or ""."""
        if self.caps is not None and not self.caps.can_tune(hz):
            return (
                f"{hz / 1_000_000:.3f} MHz is outside what this radio can "
                f"tune ({self.caps.describe_ranges()})"
            )
        if self.operator_ranges and not any(span.contains(hz) for span in self.operator_ranges):
            allowed = ", ".join(span.describe() for span in self.operator_ranges)
            return f"{hz / 1_000_000:.3f} MHz is outside the ranges you allowed ({allowed})"
        return ""


def evaluate(request: TuneRequest, *, rig: RigState, limits: Limits, manual: bool) -> Verdict:
    """Decide what to do with one control request.

    Order matters: refusals that will never become valid are answered first,
    so a site is told promptly rather than after a deferral times out.
    """
    if rig.health is not RigHealth.OK:
        return Verdict(Decision.REFUSE, "rig_offline", rig.detail or "no rig is connected")

    if request.mode is not None and request.mode not in MODES:
        # Never substitute a "close enough" mode (SPEC.md §6.1).
        return Verdict(
            Decision.REFUSE,
            "unknown_mode",
            f"{request.mode} is not a mode this rig understands",
        )

    out_of_range = limits.rejects(request.freq_hz)
    if out_of_range:
        return Verdict(Decision.REFUSE, "out_of_range", out_of_range)

    if manual:
        return Verdict(Decision.OFFER, detail="waiting for you to accept")

    if rig.ptt:
        # Retuning during transmission can drive an amplifier or tuner
        # matched for the previous band (docs/PLANNING.md §10.1).
        return Verdict(Decision.DEFER, detail="waiting for transmission to end")

    return Verdict(Decision.APPLY)


def coalesce(
    pending: TuneRequest | None, incoming: TuneRequest
) -> tuple[TuneRequest, TuneRequest | None]:
    """Keep the newest request; report the one it replaced.

    Applying a backlog in sequence makes the radio chase positions that are
    already stale, so the superseded request is answered and dropped rather
    than queued (docs/PLANNING.md §10.3).
    """
    return incoming, pending


def announcement(request: TuneRequest, following: str | None) -> str:
    """What the operator is told when the radio is about to move.

    A radio that retunes itself must always be able to say who moved it.
    """
    who = request.source or (f"Following {following}" if following else "A site")
    return f"{who} — tuning to {request.describe()}"
