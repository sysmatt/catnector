"""Talk to hamlib over the rigctl network protocol.

Catnector never opens the serial port itself. A serial port has exactly one
owner, and an operator who is being followed is *operating* — WSJT-X, a
logger or flrig very likely already holds that port. See
docs/PLANNING.md §8.
"""

from __future__ import annotations

import contextlib
import socket
import time

from .backend import PeerInfo, RigBackend, RigHealth, RigState
from .errors import HamlibTooOld, RigCommandError, RigUnavailable
from .wire import (
    format_command,
    is_terminated,
    parse_chk_vfo,
    parse_dump_state_version,
    parse_response,
)

#: docs/PLANNING.md §8.2 — old enough that any installed hamlib passes, new
#: enough to skip the worst of the protocol drift.
HAMLIB_FLOOR = (4, 5, 0)

DEFAULT_PORT = 4532


class NetRigctlBackend(RigBackend):
    """A rigctl network client.

    Connects to a ``rigctld`` this process started (managed mode) or one that
    was already running (attach mode). The two are identical from here — only
    who owns the daemon differs.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = DEFAULT_PORT,
        timeout: float = 3.0,
        hamlib_version: tuple[int, int, int] | None = None,
    ):
        self.host = host
        self.port = port
        self.timeout = timeout
        self._socket: socket.socket | None = None
        self._peer = PeerInfo(hamlib_version=hamlib_version)

    # ------------------------------------------------------------ plumbing

    @property
    def connected(self) -> bool:
        return self._socket is not None

    @property
    def peer(self) -> PeerInfo:
        return self._peer

    def _send(
        self, verb: str, *args: object, needs_vfo: bool = True, expect_rprt: bool = True
    ) -> str:
        if self._socket is None:
            raise RigUnavailable("not connected")
        line = format_command(verb, *args, vfo_mode=self._peer.vfo_mode and needs_vfo)
        try:
            self._socket.sendall(line.encode("ascii"))
            return self._read(expect_rprt=expect_rprt)
        except (TimeoutError, OSError) as exc:
            self.close()
            raise RigUnavailable(f"{verb}: {exc}") from exc

    def _read(self, expect_rprt: bool = True) -> str:
        """Read until the reply is terminated, or the deadline passes.

        An unknown command produces no reply at all, and ``\\chk_vfo``
        produces one with no ``RPRT`` line, so a deadline is the only safe
        stopping condition.
        """
        assert self._socket is not None
        deadline = time.monotonic() + self.timeout
        chunks: list[str] = []
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            self._socket.settimeout(remaining)
            try:
                data = self._socket.recv(65536)
            except TimeoutError:
                break
            if not data:
                raise RigUnavailable("connection closed by the rigctld peer")
            chunks.append(data.decode("utf-8", "replace"))
            text = "".join(chunks)
            if expect_rprt and is_terminated(text):
                break
            if not expect_rprt and text.strip():
                break
        return "".join(chunks)

    def _command(self, verb: str, *args: object, needs_vfo: bool = True):
        response = parse_response(self._send(verb, *args, needs_vfo=needs_vfo))
        if response.rprt not in (0, None):
            raise RigCommandError(response.rprt, verb)
        return response

    # ----------------------------------------------------------- lifecycle

    def open(self) -> PeerInfo:
        try:
            self._socket = socket.create_connection((self.host, self.port), self.timeout)
        except OSError as exc:
            self._socket = None
            raise RigUnavailable(
                f"cannot reach rigctld at {self.host}:{self.port} — {exc}"
            ) from exc
        try:
            self._probe()
        except Exception:
            self.close()
            raise
        return self._peer

    def _probe(self) -> None:
        """Probe, never assume — in every mode, including the bundled one.

        Running this unconditionally means there is exactly one code path,
        rather than a probe whose first real test happens on a stranger's
        computer (docs/PLANNING.md §8.2).
        """
        vfo_mode = parse_chk_vfo(self._send("chk_vfo", needs_vfo=False, expect_rprt=False))
        self._peer = PeerInfo(
            hamlib_version=self._peer.hamlib_version,
            vfo_mode=vfo_mode,
            model_name=self._peer.model_name,
        )
        state = self._command("dump_state", needs_vfo=False)
        self._peer = PeerInfo(
            hamlib_version=self._peer.hamlib_version,
            vfo_mode=vfo_mode,
            protocol_version=parse_dump_state_version(state),
            model_name=self._peer.model_name,
        )
        version = self._peer.hamlib_version
        if version is not None and version < HAMLIB_FLOOR:
            raise HamlibTooOld(version, HAMLIB_FLOOR)

    def close(self) -> None:
        if self._socket is not None:
            with contextlib.suppress(OSError):
                self._socket.close()
            self._socket = None

    def __enter__(self) -> NetRigctlBackend:
        self.open()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # ------------------------------------------------------------ rig I/O

    def read_state(self) -> RigState:
        """Read the rig. Never raises: a failure is a health value."""
        now = int(time.time() * 1000)
        if not self.connected:
            return RigState(health=RigHealth.OFFLINE, read_at_ms=now, detail="not connected")
        try:
            freq = int(float(self._command("get_freq").value("frequency") or 0))
            mode_response = self._command("get_mode")
            mode = mode_response.value("mode")
            passband = mode_response.value("passband")
            return RigState(
                freq_hz=freq,
                mode=mode,
                passband_hz=int(passband) if passband and passband.isdigit() else None,
                ptt=self._read_ptt(),
                health=RigHealth.OK,
                read_at_ms=now,
            )
        except RigUnavailable as exc:
            return RigState(health=RigHealth.OFFLINE, read_at_ms=now, detail=str(exc))
        except (RigCommandError, ValueError) as exc:
            return RigState(health=RigHealth.ERROR, read_at_ms=now, detail=str(exc))

    def _read_ptt(self) -> bool | None:
        """Current PTT, or None when it could not be read just now.

        None means "unknown at this moment", not "this rig cannot do it" —
        hamlib will answer ENAVAIL transiently (the dummy rig does exactly
        this on its first call). Whether a rig can report PTT at all is a
        *capability* question, answered by ``RigCaps.can_get_ptt``, and that
        is what the PTT guard in docs/PLANNING.md §10.1 should consult. The
        guard degrades gracefully rather than refusing to work.
        """
        try:
            value = self._command("get_ptt").value("ptt")
        except RigCommandError as exc:
            if exc.unsupported:
                return None
            raise
        if value is None:
            return None
        return not value.strip().startswith("0")

    def set_frequency(self, hz: int) -> None:
        if not isinstance(hz, int):
            raise TypeError("frequency must be an integer number of hertz")
        self._command("set_freq", hz)

    def set_mode(self, mode: str, passband_hz: int | None = None) -> None:
        self._command("set_mode", mode, passband_hz if passband_hz is not None else 0)
