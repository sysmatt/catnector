"""Protocol message construction and inspection (SPEC.md §6, §7).

Kept free of Qt so the awkward parts are testable without an event loop.
"""

from __future__ import annotations

import itertools
import time
from dataclasses import dataclass, field
from typing import Any

PROTOCOL_VERSION = 1
SUBPROTOCOL = "catnector.v1"

#: Optional features this client implements and advertises in `hello`.
CLIENT_FEATURES = ("ack", "follow_state")

#: Terminal close codes: the session ended for a reason reconnecting cannot
#: fix, and a client that retries will fight the machine that replaced it
#: (SPEC.md §11).
CLOSE_SUPERSEDED = 4001
CLOSE_BAD_TOKEN = 4002
CLOSE_BAD_VERSION = 4003
CLOSE_GOING_AWAY = 4004

TERMINAL_CLOSE_CODES = {CLOSE_SUPERSEDED, CLOSE_BAD_TOKEN, CLOSE_BAD_VERSION}

CLOSE_EXPLANATIONS = {
    CLOSE_SUPERSEDED: (
        "This session was disconnected because catnector signed in on "
        "another computer using the same account.\n\n"
        "Only one catnector session can be live at a time. If that was not "
        "you, change your token on the site."
    ),
    CLOSE_BAD_TOKEN: (
        "The site rejected this token. It may have been revoked or "
        "regenerated.\n\nPaste a new token to reconnect."
    ),
    CLOSE_BAD_VERSION: (
        "This site speaks a version of the catnector protocol that this "
        "version of catnector does not.\n\nUpdating catnector should fix it."
    ),
}


def explain_close(code: int, reason: str = "") -> str:
    """A sentence an operator can act on, rather than a number."""
    if code in CLOSE_EXPLANATIONS:
        return CLOSE_EXPLANATIONS[code]
    if reason:
        return f"The connection to the site closed: {reason}"
    return "The connection to the site closed."


def is_terminal(code: int) -> bool:
    return code in TERMINAL_CLOSE_CODES


class Ids:
    """Message identifiers, unique within a session."""

    def __init__(self, prefix: str = "c") -> None:
        self._counter = itertools.count(1)
        self._prefix = prefix

    def next(self) -> str:
        return f"{self._prefix}{next(self._counter)}"


def now_ms() -> int:
    return int(time.time() * 1000)


def envelope(mtype: str, message_id: str, **fields: Any) -> dict[str, Any]:
    return {"v": PROTOCOL_VERSION, "type": mtype, "id": message_id, **fields}


def hello(
    message_id: str, client_name: str, client_version: str, rig: dict[str, Any] | None = None
) -> dict[str, Any]:
    message = envelope(
        "hello",
        message_id,
        client={"name": client_name, "version": client_version},
        features=list(CLIENT_FEATURES),
    )
    if rig is not None:
        message["rig"] = rig
    return message


def ping(message_id: str) -> dict[str, Any]:
    return envelope("ping", message_id)


def ack(message_id: str, re: str) -> dict[str, Any]:
    return envelope("ack", message_id, re=re)


def nack(message_id: str, re: str, reason: str, detail: str = "") -> dict[str, Any]:
    message = envelope("nack", message_id, re=re, reason=reason)
    if detail:
        message["detail"] = detail[:512]
    return message


@dataclass(frozen=True)
class SessionInfo:
    """What `welcome` told us (SPEC.md §7.2)."""

    session_id: str = ""
    user: str = ""
    callsign: str = ""
    telemetry_interval_ms: int = 1000
    features: tuple[str, ...] = field(default_factory=tuple)
    site_name: str = ""
    host: str = ""

    def supports(self, feature: str) -> bool:
        return feature in self.features

    @property
    def identity(self) -> str:
        """What the UI shows. A callsign is a label, never an identifier."""
        return self.callsign or self.user or "unknown"


def parse_welcome(
    message: dict[str, Any], site_name: str = "", host: str = "", default_interval: int = 1000
) -> SessionInfo:
    session = message.get("session") or {}
    interval = message.get("telemetry_interval_ms", default_interval)
    return SessionInfo(
        session_id=str(session.get("id", "")),
        user=str(session.get("user", "")),
        callsign=str(session.get("callsign", "")),
        telemetry_interval_ms=int(interval) if isinstance(interval, int) else default_interval,
        features=tuple(message.get("features") or ()),
        site_name=site_name,
        host=host,
    )


def unsupported_required_fields(message: dict[str, Any], understood: set[str]) -> list[str]:
    """Fields named in ``req`` that this client does not understand.

    A message naming any of them must be refused **whole** — never applied in
    part. Ignoring an unknown field is safe for a filter width and unsafe for
    a split frequency, where it would put an operator on top of the station
    they were trying to work (SPEC.md §8.2).
    """
    return [name for name in message.get("req") or [] if name not in understood]
