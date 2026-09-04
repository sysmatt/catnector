"""The site connection: discovery, handshake, heartbeat, close handling.

Built on Qt's own ``QWebSocket`` and ``QNetworkAccessManager``. Both are
event-driven and never block, so this runs on the GUI thread — unlike the rig
layer, where a serial radio genuinely blocks for hundreds of milliseconds and
needs a worker thread. No asyncio anywhere in the client.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from enum import Enum
from typing import Any

from PySide6.QtCore import QObject, QTimer, QUrl, Signal, Slot
from PySide6.QtNetwork import (
    QAbstractSocket,
    QNetworkAccessManager,
    QNetworkReply,
    QNetworkRequest,
)
from PySide6.QtWebSockets import QWebSocket, QWebSocketHandshakeOptions

from .. import __version__
from .messages import (
    PROTOCOL_VERSION,
    SUBPROTOCOL,
    Ids,
    SessionInfo,
    ack,
    explain_close,
    hello,
    is_terminal,
    nack,
    parse_welcome,
    ping,
    unsupported_required_fields,
)
from .tokens import Token

#: SPEC.md §10 — ping every 10 s, five unanswered means the connection is dead.
HEARTBEAT_MS = 10_000
HEARTBEAT_MISSES = 5

#: Fields this client understands well enough to satisfy a `req` naming them.
UNDERSTOOD_FIELDS = {"freq", "mode", "passband", "source"}

BACKOFF_START_MS = 1_000
BACKOFF_MAX_MS = 60_000


def close_code_value(raw: object) -> int:
    """Qt reports the close code as an enum, not an integer.

    The application range this protocol uses (4000-4999, SPEC.md §11) is
    outside that enum, so the value has to be unwrapped rather than compared
    against enum members.
    """
    value = getattr(raw, "value", raw)
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


class Phase(str, Enum):
    OFFLINE = "offline"
    DISCOVERING = "discovering"
    CONNECTING = "connecting"
    HANDSHAKING = "handshaking"
    ONLINE = "online"
    STOPPED = "stopped"  # terminal: needs the operator, not a retry


@dataclass(frozen=True)
class Capabilities:
    """The `/.well-known/catnector` document (SPEC.md §4.2)."""

    websocket_url: str
    protocol_versions: tuple[int, ...] = (PROTOCOL_VERSION,)
    telemetry_interval_ms: int = 1000
    features: tuple[str, ...] = ()
    site_name: str = ""


class SiteClient(QObject):
    """One connection to one site."""

    phase_changed = Signal(str)  # Phase value
    welcomed = Signal(object)  # SessionInfo
    closed = Signal(int, str, bool)  # code, explanation, terminal
    failed = Signal(str)  # human-readable
    set_rig_received = Signal(dict)  # M4 wires this to the rig
    follow_state_changed = Signal(object)  # str | None

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._network = QNetworkAccessManager(self)
        self._reply: QNetworkReply | None = None
        # Parented, so the socket is not destroyed independently of us.
        self._socket = QWebSocket()
        self._socket.setParent(self)
        self._ids = Ids()
        self._token: Token | None = None
        self._site_name = ""
        self._caps: Capabilities | None = None
        self._session: SessionInfo | None = None
        self._phase = Phase.OFFLINE
        self._rig_snapshot: dict[str, Any] | None = None
        #: Whether there is a radio to command. Set by the owner; when false,
        #: control messages are refused with `rig_offline` rather than
        #: silently dropped, so the site never believes a radio moved.
        self._rig_available = False

        self._heartbeat = QTimer(self)
        self._heartbeat.setInterval(HEARTBEAT_MS)
        self._heartbeat.timeout.connect(self._send_ping)
        self._unanswered = 0

        self._retry = QTimer(self)
        self._retry.setSingleShot(True)
        self._retry.timeout.connect(self._reconnect)
        self._backoff_ms = BACKOFF_START_MS
        self._want_connection = False

        self._socket.connected.connect(self._on_socket_connected)
        self._socket.disconnected.connect(self._on_socket_disconnected)
        self._socket.textMessageReceived.connect(self._on_text)

    # ------------------------------------------------------------- accessors

    @property
    def phase(self) -> Phase:
        return self._phase

    @property
    def session(self) -> SessionInfo | None:
        return self._session

    @property
    def capabilities(self) -> Capabilities | None:
        return self._caps

    @property
    def online(self) -> bool:
        return self._phase is Phase.ONLINE

    def set_rig_snapshot(self, rig: dict[str, Any] | None) -> None:
        """The rig block sent in `hello`. Updated as profiles change."""
        self._rig_snapshot = rig

    def set_rig_available(self, available: bool) -> None:
        """Tell the client whether a radio is connected and commandable."""
        self._rig_available = bool(available)

    def _set_phase(self, phase: Phase) -> None:
        if phase is not self._phase:
            self._phase = phase
            self.phase_changed.emit(phase.value)

    # ------------------------------------------------------------- lifecycle

    def connect_to(self, token: Token, site_name: str = "") -> None:
        """Discover the endpoint, then open the socket."""
        self.disconnect_from()
        self._token = token
        self._site_name = site_name
        self._want_connection = True
        self._backoff_ms = BACKOFF_START_MS
        self._discover()

    def disconnect_from(self) -> None:
        """Deliberate disconnect. Cancels any pending retry."""
        self._want_connection = False
        self._retry.stop()
        self._heartbeat.stop()
        self._abort_discovery()
        self._session = None
        if self._socket.state() != QAbstractSocket.SocketState.UnconnectedState:
            self._socket.close()
        self._set_phase(Phase.OFFLINE)

    # ------------------------------------------------------------- discovery

    def _abort_discovery(self) -> None:
        """Cancel an in-flight capability request.

        Without this, a reply outlives a deliberate disconnect and fires
        against an object that may already be gone.
        """
        reply, self._reply = self._reply, None
        if reply is not None:
            reply.finished.disconnect()
            reply.abort()
            reply.deleteLater()

    def _discover(self) -> None:
        assert self._token is not None
        self._abort_discovery()
        self._set_phase(Phase.DISCOVERING)
        request = QNetworkRequest(QUrl(self._token.wellknown_url))
        request.setRawHeader(b"Accept", b"application/json")
        request.setAttribute(
            QNetworkRequest.Attribute.RedirectPolicyAttribute,
            QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy,
        )
        self._reply = self._network.get(request)
        self._reply.finished.connect(self._discovery_finished)

    @Slot()
    def _discovery_finished(self) -> None:
        reply, self._reply = self._reply, None
        if reply is None:
            return
        reply.deleteLater()
        self._on_discovered(reply)

    def _on_discovered(self, reply: QNetworkReply) -> None:
        if not self._want_connection:
            return
        if reply.error() != QNetworkReply.NetworkError.NoError:
            self._fail_or_retry(
                f"Could not reach {self._token.host if self._token else 'the site'}: "
                f"{reply.errorString()}"
            )
            return
        try:
            document = json.loads(bytes(reply.readAll().data()).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            self._fail_or_retry(
                f"{self._token.host if self._token else 'The site'} did not return a "
                "valid catnector capability document."
            )
            return

        versions = tuple(document.get("protocol_versions") or ())
        websocket_url = str(document.get("websocket_url") or "")
        if not websocket_url:
            self._fail_or_retry("The site did not say where to connect.")
            return
        if PROTOCOL_VERSION not in versions:
            self._stop(
                f"{self._token.host if self._token else 'That site'} speaks protocol "
                f"version(s) {', '.join(map(str, versions)) or 'unknown'}, and this "
                f"catnector speaks {PROTOCOL_VERSION}. Updating catnector should fix it."
            )
            return
        if (
            self._token is not None
            and self._token.secure
            and not websocket_url.startswith("wss://")
        ):
            self._stop("That site offered an unencrypted connection. Refusing.")
            return

        self._caps = Capabilities(
            websocket_url=websocket_url,
            protocol_versions=versions,
            telemetry_interval_ms=int(document.get("telemetry_interval_ms") or 1000),
            features=tuple(document.get("features") or ()),
            site_name=str(document.get("site_name") or ""),
        )
        self._open_socket()

    # -------------------------------------------------------------- socket

    def _open_socket(self) -> None:
        assert self._caps is not None and self._token is not None
        self._set_phase(Phase.CONNECTING)
        request = QNetworkRequest(QUrl(self._caps.websocket_url))
        request.setRawHeader(b"Authorization", f"Bearer {self._token.site_token}".encode())
        options = QWebSocketHandshakeOptions()
        options.setSubprotocols([SUBPROTOCOL])
        self._socket.open(request, options)

    @Slot()
    def _on_socket_connected(self) -> None:
        self._set_phase(Phase.HANDSHAKING)
        self._unanswered = 0
        self._send(hello(self._ids.next(), "catnector", __version__, rig=self._rig_snapshot))

    @Slot()
    def _on_socket_disconnected(self) -> None:
        self._heartbeat.stop()
        self._session = None
        code = close_code_value(self._socket.closeCode())
        reason = self._socket.closeReason() or ""
        if not self._want_connection:
            self._set_phase(Phase.OFFLINE)
            return

        terminal = is_terminal(code)
        explanation = explain_close(code, reason)
        self.closed.emit(code, explanation, terminal)
        if terminal:
            # SPEC.md §11: never retry. Two computers sharing a token that
            # both reconnect will supersede each other indefinitely.
            self._want_connection = False
            self._set_phase(Phase.STOPPED)
            return
        self._schedule_retry()

    def _send(self, message: dict[str, Any]) -> None:
        self._socket.sendTextMessage(json.dumps(message, separators=(",", ":")))

    # ------------------------------------------------------------- messages

    @Slot(str)
    def _on_text(self, raw: str) -> None:
        try:
            message = json.loads(raw)
        except ValueError:
            return
        if not isinstance(message, dict):
            return
        handler = getattr(self, f"_on_{message.get('type')}", None)
        if handler is not None:
            handler(message)

    def _on_welcome(self, message: dict[str, Any]) -> None:
        self._session = parse_welcome(
            message,
            site_name=self._site_name or (self._caps.site_name if self._caps else ""),
            host=self._token.host if self._token else "",
            default_interval=self._caps.telemetry_interval_ms if self._caps else 1000,
        )
        self._backoff_ms = BACKOFF_START_MS
        self._set_phase(Phase.ONLINE)
        self._unanswered = 0
        self._heartbeat.start()
        self.welcomed.emit(self._session)

    def _on_pong(self, _message: dict[str, Any]) -> None:
        self._unanswered = 0

    def _on_follow_state(self, message: dict[str, Any]) -> None:
        """Display only. The client derives no behaviour from it (SPEC.md §7.5)."""
        following = message.get("following")
        self.follow_state_changed.emit(following if following else None)

    def _on_error(self, message: dict[str, Any]) -> None:
        detail = message.get("detail") or message.get("code") or "unspecified"
        self.failed.emit(f"The site reported a problem: {detail}")

    def _on_set_rig(self, message: dict[str, Any]) -> None:
        """Refuse whole, never in part (SPEC.md §8.2)."""
        missing = unsupported_required_fields(message, UNDERSTOOD_FIELDS)
        if missing:
            self.reject(
                message,
                "unsupported_req",
                f"this catnector does not implement: {', '.join(missing)}",
            )
            return
        if not self._rig_available:
            # Refusing is honest; silence would leave the site believing a
            # radio moved when none did.
            self.reject(message, "rig_offline", "no rig is connected")
            return
        self.set_rig_received.emit(message)

    # --------------------------------------------------------------- replies

    def accept(self, message: dict[str, Any]) -> None:
        self._send(ack(self._ids.next(), str(message.get("id", ""))))

    def reject(self, message: dict[str, Any], reason: str, detail: str = "") -> None:
        self._send(nack(self._ids.next(), str(message.get("id", "")), reason, detail))

    def send(self, message: dict[str, Any]) -> None:
        """Send an already-built message. Used by telemetry in M4."""
        if self.online:
            self._send(message)

    # ------------------------------------------------------------- heartbeat

    @Slot()
    def _send_ping(self) -> None:
        if self._unanswered >= HEARTBEAT_MISSES:
            # Silently dead is the failure that matters when someone believes
            # their radio is following a station (SPEC.md §10).
            self._heartbeat.stop()
            self._socket.abort()
            return
        self._unanswered += 1
        self._send(ping(self._ids.next()))

    # ---------------------------------------------------------------- retry

    def _schedule_retry(self) -> None:
        self._set_phase(Phase.CONNECTING)
        jitter = random.uniform(0.8, 1.2)
        self._retry.start(int(self._backoff_ms * jitter))
        self._backoff_ms = min(self._backoff_ms * 2, BACKOFF_MAX_MS)

    @Slot()
    def _reconnect(self) -> None:
        if self._want_connection and self._token is not None:
            self._discover()

    def _fail_or_retry(self, message: str) -> None:
        self.failed.emit(message)
        if self._want_connection:
            self._schedule_retry()
        else:
            self._set_phase(Phase.OFFLINE)

    def _stop(self, message: str) -> None:
        """A failure retrying cannot fix."""
        self._want_connection = False
        self._retry.stop()
        self.failed.emit(message)
        self._set_phase(Phase.STOPPED)
