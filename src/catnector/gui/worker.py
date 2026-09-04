"""Rig I/O on its own thread.

The GUI thread performs no rig I/O at all. A serial-attached radio can take
hundreds of milliseconds to answer a single CAT command, and a UI that
blocks on that is a UI that appears frozen while someone spins a VFO
(docs/PLANNING.md §8.4).

Poll rate is deliberately separate from report rate. The site's telemetry
interval governs what catnector *sends*; it has nothing to say about how
often a given radio can be asked.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from ..profiles import RigProfile
from ..rig import (
    NetRigctlBackend,
    PeerInfo,
    RigctldProcess,
    RigError,
    RigHealth,
    RigState,
)

#: How often to ask the radio where it is. Not the reporting interval.
DEFAULT_POLL_MS = 1000


class RigWorker(QObject):
    """Owns the rig connection. Lives on a worker thread, never the GUI's."""

    connected = Signal(object)  # PeerInfo
    disconnected = Signal(str)  # reason, empty when deliberate
    state_changed = Signal(object)  # RigState
    failed = Signal(str)  # human-readable, already translated

    def __init__(self, poll_ms: int = DEFAULT_POLL_MS) -> None:
        super().__init__()
        self._daemon: RigctldProcess | None = None
        self._backend: NetRigctlBackend | None = None
        self._timer: QTimer | None = None
        self._poll_ms = poll_ms
        self._last = RigState()

    @property
    def peer(self) -> PeerInfo | None:
        return self._backend.peer if self._backend else None

    @property
    def last_state(self) -> RigState:
        return self._last

    # ----------------------------------------------------------- lifecycle

    @Slot(object)
    def connect_to(self, profile: RigProfile) -> None:
        """Start (or attach to) rigctld and open the control connection."""
        self.disconnect_from()
        try:
            if profile.is_attach:
                host, port = profile.host, profile.port or 4532
                version = None
            else:
                self._daemon = RigctldProcess(
                    profile.daemon_options(), executable=profile.rigctld_path or None
                )
                port = self._daemon.start()
                host = "127.0.0.1"
                version = self._daemon.version

            self._backend = NetRigctlBackend(host=host, port=port, hamlib_version=version)
            peer = self._backend.open()
        except RigError as exc:
            self._teardown()
            self.failed.emit(str(exc))
            self.disconnected.emit(str(exc))
            return

        self.connected.emit(peer)
        self._start_polling()
        self._poll()

    @Slot()
    def disconnect_from(self) -> None:
        deliberate = self._backend is not None
        self._teardown()
        if deliberate:
            self.disconnected.emit("")

    def _teardown(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
        if self._backend is not None:
            self._backend.close()
            self._backend = None
        if self._daemon is not None:
            self._daemon.stop()
            self._daemon = None
        self._last = RigState()

    def _start_polling(self) -> None:
        # Created here so the timer belongs to the worker thread's event loop.
        self._timer = QTimer(self)
        self._timer.setInterval(self._poll_ms)
        self._timer.timeout.connect(self._poll)
        self._timer.start()

    # --------------------------------------------------------------- work

    @Slot()
    def _poll(self) -> None:
        if self._backend is None:
            return
        state = self._backend.read_state()
        self._last = state
        self.state_changed.emit(state)
        if state.health is RigHealth.OFFLINE and not self._backend.connected:
            reason = state.detail or "the rig connection was lost"
            self._teardown()
            self.disconnected.emit(reason)

    @Slot(int)
    def set_frequency(self, hz: int) -> None:
        if self._backend is None:
            return
        try:
            self._backend.set_frequency(int(hz))
        except RigError as exc:
            self.failed.emit(str(exc))
            return
        self._poll()

    @Slot(str, int)
    def set_mode(self, mode: str, passband_hz: int = 0) -> None:
        if self._backend is None:
            return
        try:
            self._backend.set_mode(mode, passband_hz or None)
        except RigError as exc:
            self.failed.emit(str(exc))
            return
        self._poll()
