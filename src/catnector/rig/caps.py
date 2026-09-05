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
RANGE_HEADER = re.compile(r"^(TX|RX) ranges #\d+", re.IGNORECASE)
RANGE_LINE = re.compile(r"^\s+(\d+)\s*Hz\s*-\s*(\d+)\s*Hz\s*$")


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
class FrequencyRange:
    """One contiguous span the rig can tune, in hertz."""

    low_hz: int
    high_hz: int

    def contains(self, hz: int) -> bool:
        return self.low_hz <= hz <= self.high_hz

    def describe(self) -> str:
        return f"{self.low_hz / 1_000_000:.3f}-{self.high_hz / 1_000_000:.3f} MHz"


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
    #: What the rig can tune to at all. The clamp in docs/PLANNING.md §10.2
    #: uses these rather than the transmit ranges: catnector never keys, and
    #: refusing to *listen* somewhere the radio can tune would be catnector
    #: overreaching into a decision that belongs to the operator.
    rx_ranges: tuple[FrequencyRange, ...] = ()
    #: Where the rig is designed to transmit. Shown, never enforced.
    tx_ranges: tuple[FrequencyRange, ...] = ()
    raw: dict[str, str] = field(default_factory=dict)

    def can_tune(self, hz: int) -> bool:
        """True when the rig can reach this frequency, or when unknown."""
        if not self.rx_ranges:
            return True  # nothing known: do not invent a limit
        return any(span.contains(hz) for span in self.rx_ranges)

    def is_transmit_range(self, hz: int) -> bool:
        if not self.tx_ranges:
            return True
        return any(span.contains(hz) for span in self.tx_ranges)

    def describe_ranges(self) -> str:
        return ", ".join(span.describe() for span in self.rx_ranges) or "unknown"

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


def _parse_ranges(
    lines: list[str],
) -> tuple[tuple[FrequencyRange, ...], tuple[FrequencyRange, ...]]:
    r"""Pull the TX and RX frequency spans out of a --dump-caps listing.

    Ranges are read from ``--dump-caps`` rather than from a live rig's
    ``\dump_state`` because they must be known at profile-setup time, with
    no radio attached.
    """
    collected: dict[str, list[FrequencyRange]] = {"TX": [], "RX": []}
    section: str | None = None
    for line in lines:
        header = RANGE_HEADER.match(line)
        if header:
            section = header.group(1).upper()
            continue
        if section is None:
            continue
        if line and not line[0].isspace():
            section = None
            continue
        span = RANGE_LINE.match(line)
        if span:
            low, high = int(span.group(1)), int(span.group(2))
            if high > low:
                collected[section].append(FrequencyRange(low, high))

    def merge(spans: list[FrequencyRange]) -> tuple[FrequencyRange, ...]:
        """Hamlib lists the same span once per mode group; fold them."""
        merged: list[FrequencyRange] = []
        for span in sorted(spans, key=lambda s: (s.low_hz, s.high_hz)):
            if merged and span.low_hz <= merged[-1].high_hz:
                last = merged[-1]
                merged[-1] = FrequencyRange(last.low_hz, max(last.high_hz, span.high_hz))
            else:
                merged.append(span)
        return tuple(merged)

    return merge(collected["TX"]), merge(collected["RX"])


def dump_caps(model: int, executable: str | os.PathLike[str] | None = None) -> RigCaps:
    """Parse ``rigctl -m <model> --dump-caps`` into the fields the UI needs."""
    binary = find_executable(RIGCTL_EXECUTABLE, executable)
    listing = _run(binary, "-m", str(model), "--dump-caps").splitlines()
    raw: dict[str, str] = {}
    for line in listing:
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().lower()
        if key and key not in raw:
            raw[key] = value.strip()
    tx_ranges, rx_ranges = _parse_ranges(listing)

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
        rx_ranges=rx_ranges,
        tx_ranges=tx_ranges,
        raw=raw,
    )
