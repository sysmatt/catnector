"""Locate, start and supervise ``rigctld``.

Managed mode is the entire normal experience: the operator picks their radio
in catnector, exactly as they would in WSJT-X, and never learns that
``rigctld`` exists (docs/PLANNING.md §8.1).
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from .errors import RigctldNotFound, RigUnavailable
from .wire import parse_hamlib_version

#: Where a packaged build keeps its bundled binaries (M5).
BUNDLED_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "bin"

EXECUTABLE = "rigctld.exe" if os.name == "nt" else "rigctld"
RIGCTL_EXECUTABLE = "rigctl.exe" if os.name == "nt" else "rigctl"


def find_executable(name: str, explicit: str | os.PathLike[str] | None = None) -> Path:
    """Bundled first, then an explicit path, then ``PATH``.

    The explicit path exists because hamlib adds radio backends continuously
    and someone with a brand-new rig should not have to wait for a catnector
    release (docs/PLANNING.md §8.1).
    """
    if explicit:
        candidate = Path(explicit)
        if candidate.is_dir():
            candidate = candidate / name
        if candidate.exists():
            return candidate
        raise RigctldNotFound(f"{candidate} does not exist")

    bundled = BUNDLED_DIR / name
    if bundled.exists():
        return bundled

    found = shutil.which(name)
    if found:
        return Path(found)
    raise RigctldNotFound(
        f"{name} was not found. Install hamlib, or point catnector at an "
        f"existing installation in the rig profile's advanced settings."
    )


def hamlib_version(executable: Path) -> tuple[int, int, int] | None:
    """Ask a binary its hamlib version. None if it will not say."""
    try:
        result = subprocess.run(
            [str(executable), "--version"], capture_output=True, text=True, timeout=15
        )
    except (OSError, subprocess.SubprocessError):
        return None
    for stream in (result.stdout, result.stderr):
        try:
            return parse_hamlib_version(stream)
        except ValueError:
            continue
    return None


def free_port() -> int:
    """Ask the OS for an unused port, so two profiles never collide."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@dataclass
class RigctldOptions:
    """How to start a daemon for one rig profile."""

    model: int
    device: str | None = None
    serial_speed: int | None = None
    host: str = "127.0.0.1"
    port: int = 0  # 0 asks the OS for a free one
    extra_args: tuple[str, ...] = ()

    def argv(self, executable: Path, port: int) -> list[str]:
        argv = [str(executable), "-m", str(self.model), "-t", str(port), "-T", self.host]
        if self.device:
            argv += ["-r", self.device]
        if self.serial_speed:
            argv += ["-s", str(self.serial_speed)]
        argv += list(self.extra_args)
        return argv


class RigctldProcess:
    """A ``rigctld`` this process owns.

    Not used in attach mode, where the daemon belongs to someone else and
    catnector must not manage its lifetime.
    """

    def __init__(
        self,
        options: RigctldOptions,
        executable: str | os.PathLike[str] | None = None,
        startup_timeout: float = 10.0,
    ) -> None:
        self.options = options
        self.executable = find_executable(EXECUTABLE, executable)
        self.startup_timeout = startup_timeout
        self.port = options.port or free_port()
        self._process: subprocess.Popen | None = None
        self._stderr_path: Path | None = None

    @property
    def running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    @property
    def version(self) -> tuple[int, int, int] | None:
        return hamlib_version(self.executable)

    def start(self) -> int:
        """Start the daemon and wait until its port answers. Returns the port."""
        if self.running:
            return self.port
        argv = self.options.argv(self.executable, self.port)
        try:
            self._process = subprocess.Popen(
                argv, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
            )
        except OSError as exc:
            raise RigUnavailable(f"could not start {self.executable}: {exc}") from exc

        deadline = time.monotonic() + self.startup_timeout
        while time.monotonic() < deadline:
            if not self.running:
                raise RigUnavailable(f"rigctld exited immediately: {self._drain_stderr()}")
            try:
                with socket.create_connection((self.options.host, self.port), 0.5):
                    return self.port
            except OSError:
                time.sleep(0.1)
        self.stop()
        raise RigUnavailable(
            f"rigctld did not accept connections within {self.startup_timeout:.0f}s"
        )

    def _drain_stderr(self) -> str:
        if self._process is None or self._process.stderr is None:
            return ""
        try:
            return self._process.stderr.read().decode("utf-8", "replace").strip()[:500]
        except (OSError, ValueError):
            return ""

    def stop(self, timeout: float = 5.0) -> None:
        """Terminate, then kill if it will not go."""
        if self._process is None:
            return
        if self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=timeout)
        if self._process.stderr:
            self._process.stderr.close()
        self._process = None

    def __enter__(self) -> RigctldProcess:
        self.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.stop()
