"""Catnector — stage a ham radio's frequency and mode from a spotting site.

Catnector sets **frequency and mode only**. It never keys the transmitter;
the licensed operator always does that themselves. See the protocol
specification at https://github.com/sysmatt/catnector-protocol.

Copyright (C) 2026 Matt Hoskins, K2TTA
Licensed under the GNU General Public License v3 or later. See LICENSE.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _version

try:
    __version__ = _version("catnector")
except PackageNotFoundError:  # running from a source tree without an install
    __version__ = "0.0.0+unknown"

#: Protocol version this client speaks (catnector-protocol SPEC.md).
PROTOCOL_VERSION = 1

__all__ = ["PROTOCOL_VERSION", "__version__"]
