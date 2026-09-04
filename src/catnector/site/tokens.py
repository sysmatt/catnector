"""Catnector tokens (catnector-protocol SPEC.md §4.1).

    cnx1_<payload>.<check>

``payload`` is unpadded base64url of ``{"h": host, "t": site_token}``;
``check`` is the first 6 characters of unpadded base64url of the SHA-256 of
the payload text. The separator before the checksum is ``.`` rather than
``_`` because ``_`` is in the base64url alphabet.

Implemented here rather than imported from the protocol repository: catnector
is a client written against the specification, not a consumer of the
reference tooling. If the two ever disagree, that is a finding.

The encoding is **not encryption**. A token is a credential equivalent to a
password — stored restrictively, never logged, never put in a URL.
"""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass

PREFIX = "cnx1"
CHECK_LENGTH = 6


class TokenError(ValueError):
    """The token is not a well-formed catnector token."""


class TokenDamaged(TokenError):
    """The checksum does not match — truncated or altered in transit.

    Deliberately distinct from a server rejecting a valid token: "that token
    looks damaged" is actionable, "authentication failed" is not.
    """


@dataclass(frozen=True)
class Token:
    host: str
    site_token: str

    @property
    def secure(self) -> bool:
        """False only for the local carve-out in SPEC.md §5.1."""
        return not is_local(self.host)

    @property
    def base_url(self) -> str:
        return f"{'https' if self.secure else 'http'}://{self.host}"

    @property
    def wellknown_url(self) -> str:
        return f"{self.base_url}/.well-known/catnector"


def split_host_port(host: str) -> tuple[str, str]:
    """Split ``host[:port]`` without mangling IPv6 addresses.

    ``[::1]:8443`` -> ``("::1", "8443")``; ``::1`` -> ``("::1", "")``;
    ``example.org:443`` -> ``("example.org", "443")``.
    """
    text = host.strip()
    if text.startswith("["):
        address, _, rest = text[1:].partition("]")
        return address, rest.lstrip(":")
    if text.count(":") == 1:
        name, _, port = text.partition(":")
        return name, port
    # No colon at all, or several — a bare IPv6 address either way.
    return text, ""


def is_local(host: str) -> bool:
    """Hosts exempt from the TLS requirement (SPEC.md §5.1)."""
    name, _ = split_host_port(host)
    return name.lower() in ("localhost", "127.0.0.1", "::1")


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _checksum(payload: str) -> str:
    return _b64(hashlib.sha256(payload.encode("ascii")).digest())[:CHECK_LENGTH]


def encode(host: str, site_token: str) -> str:
    """Build a token. Used by tests and by nothing else in the client."""
    if not host or not site_token:
        raise TokenError("host and site token are both required")
    payload = _b64(
        json.dumps({"h": host, "t": site_token}, separators=(",", ":")).encode("utf-8")
    )
    return f"{PREFIX}_{payload}.{_checksum(payload)}"


def decode(token: str) -> Token:
    """Parse a token, verifying its checksum first."""
    text = token.strip()
    if not text.startswith(PREFIX + "_"):
        raise TokenError("That does not look like a catnector token — they begin with 'cnx1_'.")
    parts = text[len(PREFIX) + 1 :].split(".")
    if len(parts) != 2 or not all(parts):
        raise TokenDamaged(
            "That token is incomplete. Copy the whole thing, including the "
            "characters after the final full stop."
        )
    payload, check = parts
    if _checksum(payload) != check:
        raise TokenDamaged(
            "That token appears to have been damaged in transit — it was "
            "probably truncated when it was copied. Try copying it again."
        )
    try:
        decoded = json.loads(_unb64(payload))
    except Exception as exc:
        raise TokenDamaged("That token could not be read.") from exc
    if not isinstance(decoded, dict) or "h" not in decoded or "t" not in decoded:
        raise TokenError("That token is missing its endpoint or credential.")
    return Token(host=str(decoded["h"]), site_token=str(decoded["t"]))
