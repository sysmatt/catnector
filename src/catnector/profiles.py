"""Rig profiles, stored as plain INI.

Human-readable and hand-editable on purpose: ham operators skew comfortable
with plain-text config, and a format they can copy between machines is worth
more here than one that is tidy to parse (docs/PLANNING.md §4).
"""

from __future__ import annotations

import configparser
from dataclasses import dataclass, field, replace
from pathlib import Path

from .rig import DUMMY_MODEL, RigctldOptions

#: How catnector reaches the radio for a given profile (docs/PLANNING.md §8.1).
MANAGED = "managed"  # catnector starts and supervises rigctld itself
ATTACH = "attach"  # something else is already running rigctld

CONNECTIONS = (MANAGED, ATTACH)

DUMMY_PROFILE_NAME = "Hamlib Dummy (no radio)"


@dataclass
class RigProfile:
    """One radio, as the operator configured it.

    ``device`` is not assumed to be a serial port: hamlib models flrig, Flex
    and the SmartSDR slices as network backends, so a profile's target is
    ``/dev/ttyUSB0`` for one rig and ``192.168.1.50:4992`` for another
    (docs/PLANNING.md §7).
    """

    name: str
    model: int = DUMMY_MODEL
    connection: str = MANAGED
    device: str = ""
    serial_speed: int | None = None
    host: str = "127.0.0.1"
    port: int = 0
    rigctld_path: str = ""
    extra_args: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_attach(self) -> bool:
        return self.connection == ATTACH

    def daemon_options(self) -> RigctldOptions:
        """Arguments for the rigctld this profile would start."""
        return RigctldOptions(
            model=self.model,
            device=self.device or None,
            serial_speed=self.serial_speed,
            port=self.port,
            extra_args=tuple(self.extra_args),
        )

    def describe(self) -> str:
        if self.is_attach:
            return f"attach to {self.host}:{self.port or 4532}"
        target = self.device or "network"
        return f"managed rigctld, model {self.model}, {target}"


def dummy_profile() -> RigProfile:
    """The built-in profile that needs no radio.

    Ships so catnector is usable, testable and demonstrable with nothing
    attached — and so a user can prove the site half works before blaming
    their cable (docs/PLANNING.md §8.1).
    """
    return RigProfile(name=DUMMY_PROFILE_NAME, model=DUMMY_MODEL, connection=MANAGED)


def _to_int(value: str, default: int | None = None) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def load_profiles(path: Path) -> list[RigProfile]:
    """Read profiles from an INI file. A missing or broken file yields none."""
    parser = configparser.ConfigParser()
    try:
        parser.read(path, encoding="utf-8")
    except (OSError, configparser.Error):
        return []

    profiles: list[RigProfile] = []
    for name in parser.sections():
        section = parser[name]
        connection = section.get("connection", MANAGED).strip().lower()
        profiles.append(
            RigProfile(
                name=name,
                model=_to_int(section.get("model", ""), DUMMY_MODEL) or DUMMY_MODEL,
                connection=connection if connection in CONNECTIONS else MANAGED,
                device=section.get("device", "").strip(),
                serial_speed=_to_int(section.get("serial_speed", "")),
                host=section.get("host", "127.0.0.1").strip() or "127.0.0.1",
                port=_to_int(section.get("port", ""), 0) or 0,
                rigctld_path=section.get("rigctld_path", "").strip(),
            )
        )
    return profiles


def save_profiles(path: Path, profiles: list[RigProfile]) -> None:
    """Write profiles, preserving nothing else in the file.

    The built-in dummy profile is not written out: it is provided by the
    application, and writing it would make it look editable and deletable
    when it is neither.
    """
    parser = configparser.ConfigParser()
    for profile in profiles:
        if profile.name == DUMMY_PROFILE_NAME:
            continue
        section: dict[str, str] = {
            "model": str(profile.model),
            "connection": profile.connection,
        }
        if profile.device:
            section["device"] = profile.device
        if profile.serial_speed:
            section["serial_speed"] = str(profile.serial_speed)
        if profile.is_attach or profile.port:
            section["host"] = profile.host
            section["port"] = str(profile.port)
        if profile.rigctld_path:
            section["rigctld_path"] = profile.rigctld_path
        parser[profile.name] = section

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        handle.write("# catnector rig profiles — safe to copy between computers.\n")
        handle.write("# Contains no credentials; site tokens live in sites.ini.\n\n")
        parser.write(handle)


def with_unique_name(profiles: list[RigProfile], profile: RigProfile) -> RigProfile:
    """Give *profile* a name no existing profile uses."""
    taken = {p.name for p in profiles}
    if profile.name not in taken:
        return profile
    stem, index = profile.name, 2
    while f"{stem} ({index})" in taken:
        index += 1
    return replace(profile, name=f"{stem} ({index})")
