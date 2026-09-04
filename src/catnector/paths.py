"""Where catnector keeps its configuration.

Two files, deliberately separate — `rigs.ini` and `sites.ini` — because the
whole point is that an operator can hand-copy one without the other: the rig
profiles onto a laptop that has no site tokens yet, or the site tokens onto a
machine that already has its own radio set up (docs/PLANNING.md §4).

Implemented against the platform conventions directly rather than through
Qt's ``QStandardPaths``, so that configuration can be read and tested with no
Qt application instance in existence. The resulting locations are the same
ones Qt would report.
"""

from __future__ import annotations

import contextlib
import os
import stat
import sys
from pathlib import Path

APP_NAME = "catnector"

#: Overrides everything. Documented, because §4 is explicitly about people
#: moving these files between machines.
ENV_OVERRIDE = "CATNECTOR_CONFIG_DIR"

RIGS_FILENAME = "rigs.ini"
SITES_FILENAME = "sites.ini"

RIGS_EXAMPLE = """\
# catnector rig profiles.
#
# One section per radio. Copy this file to another computer to take your
# rigs with you; it contains no credentials.
#
# [My FT-991]
# model = 1035            ; hamlib model number, chosen in the app
# connection = managed    ; managed | attach
# device = /dev/ttyUSB0   ; serial rigs only
# serial_speed = 38400
#
# [Shack flrig]
# model = 4
# connection = managed
# host = 127.0.0.1
# port = 12345
"""

SITES_EXAMPLE = """\
# catnector site connections.
#
# THIS FILE CONTAINS CREDENTIALS. A token is equivalent to a password.
# It is created readable only by you; keep it that way if you copy it.
#
# [HamQSY]
# token = cnx1_...
"""


def config_dir() -> Path:
    """The configuration directory for this platform."""
    override = os.environ.get(ENV_OVERRIDE)
    if override:
        return Path(override).expanduser()
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming"
        return Path(base) / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / APP_NAME


def rigs_path() -> Path:
    return config_dir() / RIGS_FILENAME


def sites_path() -> Path:
    return config_dir() / SITES_FILENAME


def restrict_permissions(path: Path) -> None:
    """Make a file readable only by its owner.

    ``sites.ini`` holds bearer tokens in plain text — deliberately, since a
    keyring would destroy the portability §4 is buying. On Windows this is
    effectively a no-op and the protection is that ``%APPDATA%`` is already
    user-scoped (docs/PLANNING.md §4.2).
    """
    with contextlib.suppress(OSError):
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def is_world_readable(path: Path) -> bool:
    """True when others can read the file. Always False on Windows."""
    if sys.platform == "win32" or not path.exists():
        return False
    try:
        mode = path.stat().st_mode
    except OSError:
        return False
    return bool(mode & (stat.S_IRGRP | stat.S_IROTH))


def ensure_config_dir() -> Path:
    """Create the directory and, on first run, commented example files.

    Writing examples rather than nothing means someone who opens the folder
    finds the schema instead of having to guess it.
    """
    directory = config_dir()
    directory.mkdir(parents=True, exist_ok=True)

    rigs = directory / RIGS_FILENAME
    if not rigs.exists():
        rigs.write_text(RIGS_EXAMPLE, encoding="utf-8")

    sites = directory / SITES_FILENAME
    if not sites.exists():
        sites.write_text(SITES_EXAMPLE, encoding="utf-8")
        restrict_permissions(sites)
    return directory
