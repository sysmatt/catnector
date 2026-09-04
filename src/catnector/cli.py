"""Command line entry point.

Catnector is a GUI application; this exists so that a user can answer
"what version are you running?" without opening it, and so that the packaged
binary has something to check in CI. The GUI arrives in M2.
"""

from __future__ import annotations

import argparse
import platform
import sys

from . import PROTOCOL_VERSION, __version__


def version_report() -> str:
    """The lines a bug report should start with."""
    return "\n".join(
        [
            f"catnector {__version__}",
            f"  protocol  {PROTOCOL_VERSION}",
            f"  python    {platform.python_version()} ({sys.implementation.name})",
            f"  platform  {platform.system()} {platform.release()} ({platform.machine()})",
        ]
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="catnector",
        description="Stage your rig's frequency and mode from a spotting site. "
        "Never transmits.",
    )
    parser.add_argument(
        "-V",
        "--version",
        action="store_true",
        help="show version and environment information, then exit",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.version:
        print(version_report())
        return 0
    if args.config_dir:
        from .paths import config_dir

        print(config_dir())
        return 0

    from .gui import run

    return run()


if __name__ == "__main__":
    raise SystemExit(main())
