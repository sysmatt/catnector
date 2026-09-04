"""Framing for hamlib's rigctl network protocol.

Pure functions, no I/O, so the awkward parts are testable without a radio or
a running daemon.

Catnector uses hamlib's **extended response** mode: every command is sent
with a leading ``+``, and the reply is a labelled block terminated by a
``RPRT <n>`` line::

    +\\get_mode        ->   get_mode:
                            Mode: USB
                            Passband: 2400
                            RPRT 0

The alternative — bare values, one per line — is not self-delimiting: a
reader cannot tell how many lines a reply has without knowing every command's
arity. The extended form costs a few bytes and removes that whole class of
parsing bug.

Two behaviours of real rigctld that this module has to accommodate:

* ``\\chk_vfo`` answers ``ChkVFO: n`` and sends **no** ``RPRT`` line.
* An unknown command produces **no reply at all**, so reads need a timeout
  rather than waiting for a terminator that will never arrive.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

RPRT = re.compile(r"^RPRT\s+(-?\d+)\s*$")
LABELLED = re.compile(r"^([A-Za-z][\w ()/.-]*):\s*(.*)$")

#: Hamlib mode tokens. Normative for the protocol too — see
#: catnector-protocol SPEC.md §6.1.
MODES = frozenset(
    {
        "USB",
        "LSB",
        "CW",
        "CWR",
        "RTTY",
        "RTTYR",
        "AM",
        "FM",
        "WFM",
        "AMS",
        "PKTLSB",
        "PKTUSB",
        "PKTFM",
        "ECSSUSB",
        "ECSSLSB",
        "FAX",
        "SAM",
        "SAL",
        "SAH",
        "DSB",
    }
)


@dataclass
class Response:
    """A parsed extended-mode reply."""

    command: str
    values: dict[str, str] = field(default_factory=dict)
    lines: list[str] = field(default_factory=list)
    rprt: int | None = None

    @property
    def ok(self) -> bool:
        return self.rprt == 0

    def value(self, key: str) -> str | None:
        return self.values.get(key.lower())


def format_command(
    verb: str, *args: object, vfo_mode: bool = False, vfo: str = "currVFO"
) -> str:
    """Build one extended-mode command line.

    When the peer runs in VFO mode (``rigctld -o``) every rig command takes a
    VFO argument first. Omitting it does not produce an error — **rigctld
    resets the connection** — which is why the caller must know, and why
    :func:`parse_chk_vfo` is consulted before any other command is sent.
    """
    parts = [f"+\\{verb}"]
    if vfo_mode:
        parts.append(vfo)
    parts.extend(str(a) for a in args)
    return " ".join(parts) + "\n"


def is_terminated(text: str) -> bool:
    """True when *text* holds a complete extended-mode reply."""
    return any(RPRT.match(line.strip()) for line in text.splitlines())


def parse_response(text: str) -> Response:
    """Parse an extended-mode reply block."""
    lines = [line.rstrip("\r") for line in text.strip("\n").split("\n") if line.strip()]
    response = Response(command="")
    if not lines:
        return response

    head = lines[0]
    if head.endswith(":") or LABELLED.match(head):
        response.command = head.split(":", 1)[0].strip()
        lines = lines[1:]

    for line in lines:
        terminator = RPRT.match(line.strip())
        if terminator:
            response.rprt = int(terminator.group(1))
            continue
        labelled = LABELLED.match(line.strip())
        if labelled:
            response.values[labelled.group(1).strip().lower()] = labelled.group(2).strip()
        else:
            response.lines.append(line.strip())
    return response


def parse_chk_vfo(text: str) -> bool:
    """Read ``\\chk_vfo``'s reply, which carries no ``RPRT`` terminator."""
    for line in text.splitlines():
        labelled = LABELLED.match(line.strip())
        if labelled and labelled.group(1).strip().lower() == "chkvfo":
            return labelled.group(2).strip().startswith("1")
    return False


def parse_hamlib_version(text: str) -> tuple[int, int, int]:
    """Extract a version from ``rigctld --version`` output.

    ``rigctld Hamlib 4.6.5 2025-09-05T19:49:48Z SHA=8a6bd5 64-bit``
    """
    found = re.search(r"Hamlib\s+(\d+)\.(\d+)(?:\.(\d+))?", text)
    if not found:
        raise ValueError(f"no hamlib version in {text!r}")
    major, minor, patch = found.group(1), found.group(2), found.group(3) or "0"
    return int(major), int(minor), int(patch)


def parse_dump_state_version(response: Response) -> int | None:
    """The first bare number of ``\\dump_state`` is its protocol version."""
    for line in response.lines:
        token = line.split()[0] if line.split() else ""
        if token.isdigit():
            return int(token)
    return None
