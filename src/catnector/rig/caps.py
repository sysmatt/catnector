"""Rig models and capabilities, read from hamlib itself.

The rig picker is built from hamlib's model list, never raw model numbers,
and the settings form is generated from a model's capabilities rather than
hand-maintained. Hamlib already knows each rig's legal baud rates, framing,
and what it can and cannot do — so catnector can offer only valid choices
and grey out the rest (docs/PLANNING.md §8.3).
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .daemon import RIGCTL_EXECUTABLE, find_executable

# Anchored on hamlib's backend version stamp rather than on column spacing.
# Two rows in hamlib 4.6.5 defeat column-counting: "Digital World Traveller"
# is separated from its version by a single space, and PRM8060's stamp has
# three parts (``20231002.0.0``) rather than two.
MODEL_LINE = re.compile(r"^\s*(\d+)\s+(.*?)\s+(\d{6,8}(?:\.\d+)+)\s+(\S+)")
SERIAL_SPEED = re.compile(r"(\d+)\.\.(\d+)\s+baud,\s*(\S+)(?:,\s*ctrl=(\S+))?")


@dataclass(frozen=True)
class RigModel:
    """One entry in the rig picker."""

    model: int
    manufacturer: str
    name: str
    status: str = ""

    @property
    def label(self) -> str:
        """What the operator sees. Never a bare model number."""
        return f"{self.manufacturer} {self.name}".strip() or f"model {self.model}"


@dataclass(frozen=True)
class RigCaps:
    """What a model can do, per hamlib."""

    model: int
    name: str = ""
    manufacturer: str = ""
    port_type: str = ""
    serial_speeds: tuple[int, ...] = ()
    serial_framing: str = ""
    can_set_freq: bool = False
    can_set_mode: bool = False
    can_set_vfo: bool = False
    can_get_ptt: bool = False
    can_set_split_freq: bool = False
    raw: dict[str, str] = field(default_factory=dict)

    @property
    def is_network(self) -> bool:
        """flrig, FlexRadio and the SmartSDR slices land here.

        They are ordinary rig-picker entries, not a special code path.
        """
        return "network" in self.port_type.lower()

    @property
    def is_serial(self) -> bool:
        return "rs-232" in self.port_type.lower() or "usb" in self.port_type.lower()

    @property
    def needs_device(self) -> bool:
        return self.is_serial


def _run(executable: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            [str(executable), *args], capture_output=True, text=True, timeout=30
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"{executable} {' '.join(args)}: {exc}") from exc
    return result.stdout


def list_models(executable: str | os.PathLike[str] | None = None) -> list[RigModel]:
    """Parse ``rigctl -l``.

    Read from the binary catnector will actually use, and cached by the
    caller — so the list is self-consistent with the shipped hamlib rather
    than drifting from a vendored copy.
    """
    binary = find_executable(RIGCTL_EXECUTABLE, executable)
    models: list[RigModel] = []
    for line in _run(binary, "-l").splitlines():
        if line.lstrip().startswith("Rig #"):
            continue
        match = MODEL_LINE.match(line)
        if not match:
            continue
        # Manufacturer and model sit in separate columns; some rows have an
        # empty model (FLRig), leaving the manufacturer standing alone.
        parts = [p for p in re.split(r"\s{2,}", match.group(2).strip()) if p]
        models.append(
            RigModel(
                model=int(match.group(1)),
                manufacturer=parts[0] if parts else "",
                name=" ".join(parts[1:]),
                status=match.group(4).strip(),
            )
        )
    return models


def dump_caps(model: int, executable: str | os.PathLike[str] | None = None) -> RigCaps:
    """Parse ``rigctl -m <model> --dump-caps`` into the fields the UI needs."""
    binary = find_executable(RIGCTL_EXECUTABLE, executable)
    raw: dict[str, str] = {}
    for line in _run(binary, "-m", str(model), "--dump-caps").splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().lower()
        if key and key not in raw:
            raw[key] = value.strip()

    speeds: tuple[int, ...] = ()
    framing = ""
    speed_line = raw.get("serial speed", "")
    speed_match = SERIAL_SPEED.search(speed_line)
    if speed_match:
        low, high = int(speed_match.group(1)), int(speed_match.group(2))
        framing = speed_match.group(3)
        speeds = tuple(
            s
            for s in (1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200, 230400)
            if low <= s <= high
        )

    def yes(key: str) -> bool:
        return raw.get(key, "").strip().upper().startswith("Y")

    return RigCaps(
        model=model,
        name=raw.get("model name", ""),
        manufacturer=raw.get("mfg name", ""),
        port_type=raw.get("port type", ""),
        serial_speeds=speeds,
        serial_framing=framing,
        can_set_freq=yes("can set frequency"),
        can_set_mode=yes("can set mode"),
        can_set_vfo=yes("can set vfo"),
        can_get_ptt=yes("can get ptt"),
        can_set_split_freq=yes("can set split freq"),
        raw=raw,
    )
