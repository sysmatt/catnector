"""Sending rig state up to the site, at the rate the site asked for.

Throttled **in catnector**, not by relying on the site to reject the excess:
a conforming client never sends the flood in the first place (SPEC.md §9.1).
The interval comes from the site, so a change in its load characteristics or
a faster tier needs no catnector release.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from ..rig import RigState
from ..site import report
from ..site.messages import Ids

#: Used until a site says otherwise.
DEFAULT_INTERVAL_MS = 1000


class Telemetry(QObject):
    """Coalesces rig state into reports no faster than the negotiated rate."""

    report_ready = Signal(dict)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._ids = Ids("t")
        self._interval_ms = DEFAULT_INTERVAL_MS
        self._profile_name = ""
        self._latest: RigState | None = None
        self._sent_signature: tuple | None = None
        self._enabled = False

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._flush)

    def configure(self, interval_ms: int, profile_name: str) -> None:
        self._interval_ms = max(int(interval_ms or DEFAULT_INTERVAL_MS), 50)
        self._profile_name = profile_name
        if self._enabled:
            self._timer.start(self._interval_ms)

    def start(self) -> None:
        self._enabled = True
        self._sent_signature = None
        self._timer.start(self._interval_ms)

    def stop(self) -> None:
        self._enabled = False
        self._timer.stop()
        self._latest = None

    @Slot(object)
    def rig_state_changed(self, state: RigState) -> None:
        """Record the newest state. The timer decides when it is sent."""
        self._latest = state

    def _signature(self, state: RigState) -> tuple:
        return (
            state.freq_hz,
            state.mode,
            state.passband_hz,
            state.health.value,
            self._profile_name,
        )

    @Slot()
    def _flush(self) -> None:
        if not self._enabled or self._latest is None:
            return
        signature = self._signature(self._latest)
        if signature == self._sent_signature:
            # Reports are sent when values change; the heartbeat, not
            # telemetry, is what demonstrates liveness (SPEC.md §9.1).
            return
        self._sent_signature = signature
        state = self._latest
        self.report_ready.emit(
            report(
                self._ids.next(),
                freq_hz=state.freq_hz,
                mode=state.mode,
                passband_hz=state.passband_hz,
                rig_profile=self._profile_name,
                rig_health=state.health.value,
                read_at_ms=state.read_at_ms,
            )
        )
