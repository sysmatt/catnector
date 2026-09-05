"""Timing for the safety envelope: countdowns, deferral, coalescing.

The rules themselves are in `catnector.control`, which is pure. This holds
the parts that need a clock: announcing a tune before it happens, holding one
while the operator transmits, and rate-limiting what a site can do to a
radio.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from ..control import (
    ANNOUNCE_SECONDS,
    MAX_APPLY_RATE_MS,
    PTT_DEFER_TIMEOUT_MS,
    Decision,
    Limits,
    TuneRequest,
    announcement,
    evaluate,
)
from ..rig import RigState


class TuneController(QObject):
    """Decides when an inbound tune actually reaches the radio."""

    apply_requested = Signal(object)  # TuneRequest
    accepted = Signal(str)  # message id -> ack
    refused = Signal(str, str, str)  # message id, reason, detail
    announced = Signal(str, int)  # text, seconds remaining (0 = done)
    pending_changed = Signal(object)  # TuneRequest | None (manual mode)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.limits = Limits()
        self.manual = False
        self.following: str | None = None
        self._rig = RigState()

        self._pending: TuneRequest | None = None  # awaiting the operator
        self._deferred: TuneRequest | None = None  # awaiting PTT to drop
        self._deferred_since = 0
        self._announcing: TuneRequest | None = None
        self._countdown = 0
        self._applied_once = False

        self._announce_timer = QTimer(self)
        self._announce_timer.setInterval(1000)
        self._announce_timer.timeout.connect(self._tick_announcement)

        self._defer_timer = QTimer(self)
        self._defer_timer.setInterval(500)
        self._defer_timer.timeout.connect(self._retry_deferred)

        self._rate_gate = QTimer(self)
        self._rate_gate.setSingleShot(True)
        self._rate_gate.setInterval(MAX_APPLY_RATE_MS)

    # ------------------------------------------------------------- external

    @property
    def pending(self) -> TuneRequest | None:
        return self._pending

    def set_rig_state(self, state: RigState) -> None:
        self._rig = state

    def reset(self) -> None:
        """Forget everything. Used when the site or the rig goes away."""
        self._announce_timer.stop()
        self._defer_timer.stop()
        self._pending = self._deferred = self._announcing = None
        self._applied_once = False
        self.pending_changed.emit(None)
        self.announced.emit("", 0)

    @Slot(dict)
    def submit(self, message: dict) -> None:
        """Handle one inbound `set_rig`."""
        request = TuneRequest.from_message(message)
        if request is None:
            self.refused.emit(
                str(message.get("id", "")),
                "rejected",
                "that message did not carry a usable frequency",
            )
            return

        # Latest wins; whatever it replaced is answered rather than queued.
        for superseded in (self._deferred, self._announcing, self._pending):
            if superseded is not None and superseded.message_id != request.message_id:
                self.refused.emit(
                    superseded.message_id, "rejected", "superseded by a newer tune"
                )
        self._deferred = self._announcing = self._pending = None
        self._announce_timer.stop()
        self._defer_timer.stop()

        self._act(request)

    def accept_pending(self) -> None:
        """The operator accepted a tune offered in manual mode."""
        request, self._pending = self._pending, None
        self.pending_changed.emit(None)
        if request is not None:
            self._apply(request)

    def dismiss_pending(self) -> None:
        request, self._pending = self._pending, None
        self.pending_changed.emit(None)
        if request is not None:
            self.refused.emit(request.message_id, "rejected", "declined")

    def cancel_announcement(self) -> None:
        request, self._announcing = self._announcing, None
        self._announce_timer.stop()
        self.announced.emit("", 0)
        if request is not None:
            self.refused.emit(request.message_id, "rejected", "cancelled")

    def apply_now(self) -> None:
        """Skip the remaining countdown."""
        request, self._announcing = self._announcing, None
        self._announce_timer.stop()
        self.announced.emit("", 0)
        if request is not None:
            self._apply(request)

    # -------------------------------------------------------------- internal

    def _act(self, request: TuneRequest) -> None:
        verdict = evaluate(request, rig=self._rig, limits=self.limits, manual=self.manual)

        if verdict.decision is Decision.REFUSE:
            self.refused.emit(request.message_id, verdict.reason, verdict.detail)
            return

        if verdict.decision is Decision.OFFER:
            self._pending = request
            self.pending_changed.emit(request)
            return

        if verdict.decision is Decision.DEFER:
            self._deferred = request
            self._deferred_since = 0
            self._defer_timer.start()
            self.announced.emit(
                f"Waiting — you are transmitting. Holding {request.describe()}.", -1
            )
            return

        # Announce once on entry, then show state. A countdown on every
        # follow update would make following feel broken and would train the
        # operator to ignore the warning (docs/PLANNING.md §10.4).
        if not self._applied_once and ANNOUNCE_SECONDS > 0:
            self._announcing = request
            self._countdown = ANNOUNCE_SECONDS
            self.announced.emit(announcement(request, self.following), self._countdown)
            self._announce_timer.start()
            return

        self._apply(request)

    @Slot()
    def _tick_announcement(self) -> None:
        self._countdown -= 1
        if self._announcing is None:
            self._announce_timer.stop()
            return
        if self._countdown > 0:
            self.announced.emit(announcement(self._announcing, self.following), self._countdown)
            return
        self._announce_timer.stop()
        self.apply_now()

    @Slot()
    def _retry_deferred(self) -> None:
        request = self._deferred
        if request is None:
            self._defer_timer.stop()
            return
        self._deferred_since += self._defer_timer.interval()
        if self._deferred_since >= PTT_DEFER_TIMEOUT_MS:
            # Abandon rather than apply late: moving the radio at an
            # arbitrary later moment is its own surprise.
            self._deferred = None
            self._defer_timer.stop()
            self.announced.emit("", 0)
            self.refused.emit(
                request.message_id, "ptt_timeout", "the radio was transmitting for too long"
            )
            return
        if not self._rig.ptt:
            self._deferred = None
            self._defer_timer.stop()
            self.announced.emit("", 0)
            self._apply(request)

    def _apply(self, request: TuneRequest) -> None:
        if self._rate_gate.isActive():
            # A site should not be able to spin a VFO. The radio's own speed
            # is the real limit; this is the backstop.
            self.refused.emit(
                request.message_id,
                "rejected",
                "tunes are arriving faster than the radio can follow",
            )
            return
        self._rate_gate.start()
        self._applied_once = True
        self.apply_requested.emit(request)
        self.accepted.emit(request.message_id)
        self.announced.emit(f"{request.source or 'Tuned'} — {request.describe()}", 0)
